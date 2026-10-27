"""F19 evaluation over a published revision bundle.

Runs the full six-metric evaluation (semantic, coverage, faithfulness,
functional, structure, visual) against a revision's own PPTX using reference
inputs reconstructed from the revision bundle, then stores the report under
``<deck output>/evaluation/<revision_id>/`` where the API serves it to the
Studio UI.

Error conventions (mirrors the rest of the application layer):

- The evaluation of an already-published deck must never damage it: the
  revision directory is read-only here and all outputs land in the separate
  evaluation directory.
- Missing bundle inputs are a hard, actionable refusal (the revision is
  corrupt or too old to evaluate); per-metric failures are recorded inside
  the report by ``evaluation.runner.evaluate_presentation`` and never raise.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_CONFIG = _REPO_ROOT / "evaluation" / "config.yaml"


def evaluation_dir(deck_output_dir: str | Path, revision_id: str) -> Path:
    """Per-revision evaluation output directory (sibling of ``revisions/``)."""
    return Path(deck_output_dir) / "evaluation" / revision_id


def evaluation_report_path(deck_output_dir: str | Path, revision_id: str) -> Path:
    return evaluation_dir(deck_output_dir, revision_id) / "report.json"


def load_evaluation_report(deck_output_dir: str | Path, revision_id: str) -> dict[str, Any] | None:
    """Read a stored evaluation report; ``None`` when this revision has none."""
    path = evaluation_report_path(deck_output_dir, revision_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _reference_ir_projection(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape a RawExtraction dump into the structural-IR form the reference
    builder consumes (blocks with a flat section label, table assets with a
    plain header/rows grid).

    The revision stores the typed RawExtraction, not the parser's structural
    IR; this projection keeps the reference pipeline on its existing contract
    without touching ``evaluation/reference``.
    """

    def section_of(item: dict[str, Any]) -> str:
        parts = [str(part).strip() for part in (item.get("section_path") or []) if str(part).strip()]
        return " / ".join(parts) or "Root"

    blocks = []
    for block in raw.get("blocks", []):
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        blocks.append({"block_id": block.get("block_id"), "section": section_of(block),
                       "text": text, "document_id": block.get("document_id")})
    assets = []
    for asset in raw.get("assets", []):
        if str(asset.get("kind") or "").lower() != "table":
            continue
        data = asset.get("data") or {}
        headers = [str(value) for value in data.get("headers") or []]
        rows = [[("" if value is None else str(value)) for value in row]
                for row in data.get("rows") or []]
        if not headers and not rows:
            continue
        assets.append({"asset_id": asset.get("asset_id"), "kind": "table",
                       "section": section_of(asset), "data": {"headers": headers, "rows": rows}})
    return {"document_name": raw.get("document_name") or "Untitled",
            "collection_id": raw.get("collection_id"),
            "blocks": blocks, "assets": assets}


# Where each F19 metric stores its headline score inside the report block.
METRIC_SCORE_KEYS = {
    "semantic": "score",
    "coverage": "weighted",
    "faithfulness": "score",
    "functional": "functional_sequence_score",
    "structure": "structural_score",
    "visual": "score",
}


def evaluation_summary(report: dict[str, Any], deck_id: str, revision_id: str) -> dict[str, Any]:
    """Compact, UI-facing view of a full evaluation report.

    The Studio renders scores, statuses and counts from this shape; the full
    report (concepts, claims, per-slide rows) stays behind the report file.
    """
    metrics = report.get("metrics") or {}
    run = report.get("run") or {}
    coverage = metrics.get("coverage") or {}
    faithfulness = metrics.get("faithfulness") or {}
    structure = metrics.get("structure") or {}

    rows = [{"name": name, "score": (metrics.get(name) or {}).get(score_key),
             "status": (metrics.get(name) or {}).get("status")}
            for name, score_key in METRIC_SCORE_KEYS.items()]
    claims = report.get("claims") or []
    claim_counts = {label: sum(1 for claim in claims if claim.get("label") == label)
                    for label in ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED")}
    concepts = report.get("concepts") or []
    concept_counts = {status: sum(1 for concept in concepts if concept.get("status") == status)
                      for status in ("COVERED", "PARTIALLY_COVERED", "MISSING")}
    return {
        "deck_id": deck_id,
        "revision_id": revision_id,
        "run": {key: run.get(key) for key in ("run_id", "tool_name", "timestamp",
                                              "ai_judging", "embedding_backend")},
        "readiness": report.get("readiness"),
        "quality_gate": report.get("quality_gate"),
        "overall": (metrics.get("automated_overall")),
        "available_metrics_score": metrics.get("available_metrics_score"),
        "metrics": rows,
        "coverage": {"counts": concept_counts,
                     "weighted": coverage.get("weighted"), "strict_weighted": coverage.get("strict_weighted"),
                     "unweighted": coverage.get("unweighted")},
        "faithfulness": {"status": faithfulness.get("status"), "score": faithfulness.get("score"),
                         "claim_count": faithfulness.get("claim_count"),
                         "evaluated_claim_count": faithfulness.get("evaluated_claim_count"),
                         "hallucination_rate": faithfulness.get("hallucination_rate"),
                         "contradiction_rate": faithfulness.get("contradiction_rate"),
                         "counts": claim_counts},
        "structure": {"structural_score": structure.get("structural_score")},
        "warnings": (report.get("warnings") or [])[:20],
        "warning_count": len(report.get("warnings") or []),
        "skipped_metrics": report.get("skipped_metrics") or [],
        "slide_count": len(report.get("slides") or []),
        "report_url": f"/api/decks/{deck_id}/revisions/{revision_id}/evaluation/report",
    }


def run_revision_evaluation(
    deck_output_dir: str | Path,
    revision_id: str,
    *,
    deck_id: str = "",
    judge_caller: Any = None,
    config_path: str | Path | None = None,
    ai_judging: bool = True,
) -> dict[str, Any]:
    """Evaluate one published revision and persist the report.

    Raises ``ValueError`` with an actionable message only when the revision
    bundle lacks the inputs evaluation needs; metric-level failures are
    captured inside the report itself.
    """
    from evaluation.config import load
    from evaluation.reference.build_reference import build
    from evaluation.runner import evaluate_presentation
    from infrastructure.persistence.revisions import RevisionStore

    store = RevisionStore(deck_output_dir)
    revision_path = store.path(revision_id)
    if not (revision_path / "revision.json").is_file():
        raise ValueError(f"Revision {revision_id} is not published in this deck; it cannot be evaluated.")
    raw_path = revision_path / "raw_extraction.json"
    ir1_path = revision_path / "content_analysis.json"
    pptx_path = revision_path / "op_ppt.pptx"
    missing = [name for name, path in (("raw_extraction.json", raw_path),
                                       ("content_analysis.json", ir1_path),
                                       ("op_ppt.pptx", pptx_path)) if not path.is_file()]
    if missing:
        raise ValueError(f"Revision {revision_id} cannot be evaluated; missing {', '.join(missing)}")
    record = store.verify(revision_path)  # Integrity refusal is a hard error by design.

    out = evaluation_dir(deck_output_dir, revision_id)
    out.mkdir(parents=True, exist_ok=True)
    # The reference builder consumes parser-shaped JSON files, so the typed
    # RawExtraction projection is staged next to the report it feeds.
    reference_ir_path = out / "reference_ir.json"
    reference_ir_path.write_text(json.dumps(_reference_ir_projection(
        json.loads(raw_path.read_text(encoding="utf-8"))), ensure_ascii=False), encoding="utf-8")
    reference_path = out / "reference.json"
    build(str(reference_ir_path), str(ir1_path), str(reference_path))

    config = load(str(config_path or DEFAULT_EVAL_CONFIG))
    run_id = f"rev-{revision_id[:12]}-{datetime.now():%Y%m%d-%H%M%S}"
    report = evaluate_presentation(reference_path, str(pptx_path), "pptai-studio", run_id, out,
                                   config, ai_judging, judge_caller=judge_caller)
    summary = evaluation_summary(report, deck_id, revision_id)
    summary["evaluation_dir"] = str(out)
    log.info("Evaluation %s for revision %s: overall=%s readiness=%s",
             run_id, revision_id, summary.get("overall"), summary.get("readiness"))
    return summary
