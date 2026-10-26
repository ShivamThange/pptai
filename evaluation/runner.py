from datetime import datetime, timezone
from pathlib import Path

from .config import digest
from .extract.pptx_extractor import extract
from .metrics.coverage import evaluate as coverage
from .metrics.faithfulness import evaluate as faithfulness
from .metrics.functional import evaluate as functional
from .metrics.semantic import deck_cosine, similarities
from .metrics.structure import evaluate as structure
from .metrics.visual import evaluate as visual
from .reporting.output import write
from .util import clean, read_json, sha256, write_json


def evaluate_presentation(reference_path, pptx_path, tool_name, run_id, out_dir, config, ai_judging=True, *, judge_caller=None):
    profile = read_json(reference_path); candidate = extract(pptx_path, tool_name); out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    write_json(out / "candidate.json", candidate)
    source = clean(" ".join(c["reference_text"] for c in profile["concepts"]))
    candidate_text = clean(" ".join(s["text"] for s in candidate["slides"]))
    cosine, backend = deck_cosine(source, candidate_text, config["embedding"]["model"])
    matrix, _ = similarities([c["reference_text"] for c in profile["concepts"]], [s["text"] for s in candidate["slides"]], config["embedding"]["model"])
    concepts, coverage_metrics = coverage(profile["concepts"], candidate["slides"], matrix, config)
    roles, functional_metrics = functional(candidate["slides"])
    for slide, role in zip(candidate["slides"], roles): slide["role"] = role
    visual_rows, visual_metrics = visual(candidate["slides"], candidate["slide_width"], candidate["slide_height"], config)
    structure_metrics = structure(profile, concepts)
    claims, faithfulness_metrics = faithfulness(candidate["slides"], profile["source_chunks"], config, ai_judging, caller=judge_caller)
    values = {"semantic": cosine, "coverage": coverage_metrics["weighted"], "functional": functional_metrics["functional_sequence_score"], "structure": structure_metrics["structural_score"], "visual": visual_metrics["score"]}
    if faithfulness_metrics.get("status") == "COMPLETED" and faithfulness_metrics.get("score") is not None: values["faithfulness"] = faithfulness_metrics["score"]
    weights = config["aggregate"]["weights"]; total = sum(weights[k] for k in values); overall = sum(values[k] * weights[k] for k in values) / total
    warnings = functional_metrics["warnings"] + [w for row in visual_rows for w in row["warnings"]]
    skipped = [] if faithfulness_metrics.get("status") == "COMPLETED" else [{"metric": "faithfulness", "status": faithfulness_metrics.get("status"), "reason": faithfulness_metrics.get("reason", "")}]
    critical = visual_metrics["status"] == "EVALUATED_FAIL" or any(c["label"] == "CONTRADICTED" for c in claims)
    factual_status = ("EVALUATED_FAIL" if any(c["label"] in {"CONTRADICTED", "UNSUPPORTED"} for c in claims) else
                      "EVALUATED_PASS" if faithfulness_metrics.get("status") == "COMPLETED" and claims else
                      "FAILED_TO_RUN" if faithfulness_metrics.get("status") == "FAILED" else "NOT_EVALUATED")
    readiness = "BLOCKED" if critical or factual_status == "EVALUATED_FAIL" else "DRAFT_INCOMPLETE"
    # Metric diagnostics are still available, but missing or critical checks cannot be hidden in a weighted mean.
    complete_overall = overall if not critical and factual_status == "EVALUATED_PASS" else None
    report = {"schema_version": "1.0", "run": {"run_id": run_id, "tool_name": tool_name, "candidate_sha256": sha256(pptx_path), "reference_id": profile["reference_id"], "config_sha256": digest(config), "timestamp": datetime.now(timezone.utc).isoformat(), "embedding_backend": backend, "ai_judging": ai_judging},
              "status": "COMPLETED", "readiness": readiness,
              "quality_gate": {"artifact_hash": sha256(pptx_path), "deterministic_status": visual_metrics["status"],
                               "factual_status": factual_status, "rendered_status": "NOT_EVALUATED",
                               "judge_status": "NOT_EVALUATED", "readiness": readiness},
              "metrics": {"semantic": {"score": cosine, "deck_cosine": cosine}, "coverage": coverage_metrics, "faithfulness": faithfulness_metrics, "functional": functional_metrics, "structure": structure_metrics, "visual": visual_metrics,
                          "automated_overall": complete_overall, "available_metrics_score": overall},
              "concepts": concepts, "claims": claims, "slides": [{**s, "visual": v, "warnings": v["warnings"]} for s, v in zip(candidate["slides"], visual_rows)], "warnings": warnings, "skipped_metrics": skipped}
    write(report, out)
    return report
