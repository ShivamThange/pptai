"""F14 evaluation service, worker wiring and API surface acceptance.

Covers the full chain the Studio relies on: the reference projection from a
revision bundle, the worker's evaluate job, the automatic post-generation
enqueue and the summary/report endpoints the UI renders. The end-to-end tests
publish a hand-crafted revision bundle (real PPTX, real evaluation inputs) so
they exercise the evaluation stack without the parsing pipeline.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from application.jobs.builder import PresentationBuilder
from application.services.evaluation_service import (
    _reference_ir_projection,
    evaluation_dir,
    evaluation_summary,
    load_evaluation_report,
    run_revision_evaluation,
)
from config.service_settings import ServiceSettings
from config.settings import get_multi_agent_settings
from infrastructure.persistence.jobs import JobStore
from infrastructure.persistence.revisions import RevisionStore
from infrastructure.utils.artifacts import atomic_json, file_hash

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "config" / "ppt_default_layouts.json"

DECK_CONTENT = {
    "title": "Attention Is All You Need",
    "slides": [
        {"layout": "TITLE_CENTERED", "content": {
            "title": {"type": "heading", "text": "Attention Is All You Need"},
            "subtitle": {"type": "text_group", "text": "A fixture deck for evaluation wiring."}}},
        {"layout": "HEADER_WITH_BODY", "content": {
            "header": {"type": "heading", "text": "Attention summarizes source tokens"},
            "body": {"type": "bullets", "items": [
                "Learned weights combine token values before the projection step.",
                "One step between any two positions keeps the dependency path short.",
                "Training parallelises across positions inside one sequence."]}}},
        {"layout": "QUOTE_CALLOUT", "content": {
            "quote": {"type": "quote", "text": "Attention is all you need.",
                      "attribution": "Vaswani et al."}}},
    ],
}

RAW_EXTRACTION = {
    "schema_version": "4", "document_name": "Attention Is All You Need",
    "document_id": "doc", "collection_id": None,
    "blocks": [
        {"block_id": "doc:block_0001", "text": "Attention combines values using learned weights.",
         "section_path": ["Introduction"], "document_id": "doc"},
        {"block_id": "doc:block_0002", "text": "One step between positions keeps the path short.",
         "section_path": ["Introduction"], "document_id": "doc"},
        {"block_id": "doc:block_0003", "text": "Training parallelises across positions.",
         "section_path": ["Method"], "document_id": "doc"},
    ],
    "assets": [
        {"asset_id": "doc:table_0001", "kind": "table", "section_path": ["Results"],
         "data": {"headers": ["Layer", "Path"], "rows": [["self-attention", "one step"], ["recurrence", "many steps"]]}},
    ],
}

CONTENT_ANALYSIS = {
    "document_title": "Attention Is All You Need",
    "executive_summary": "Attention summarizes source tokens with learned weights and short paths.",
    "concepts": [
        {"title": "Learned weights", "summary": "Attention combines values using learned weights.",
         "source_block_ids": ["doc:block_0001"], "bullets": []},
        {"title": "Short paths", "summary": "One step between positions keeps the path short.",
         "source_block_ids": ["doc:block_0002"], "bullets": []},
    ],
}

METRIC_NAMES = ["semantic", "coverage", "faithfulness", "functional", "structure", "visual"]


def _publish_revision(deck_root: Path, revision_id: str) -> Path:
    """Hand-craft a published revision bundle: real PPTX plus evaluation inputs."""
    revision = deck_root / "revisions" / revision_id
    revision.mkdir(parents=True)
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    pptx_path = revision / "op_ppt.pptx"
    builder.build(DECK_CONTENT, str(pptx_path))
    atomic_json(revision / "ppt_content.json", DECK_CONTENT)
    atomic_json(revision / "raw_extraction.json", RAW_EXTRACTION)
    atomic_json(revision / "content_analysis.json", CONTENT_ANALYSIS)
    for name in ("ir1_validated.json", "chunks.json", "storyboard.json",
                 "run_manifest.json", "suggestions.json"):
        atomic_json(revision / name, {"schema_version": 1, "fixture": True})
    atomic_json(revision / "quality_report.json", {
        "readiness": "BASIC_CHECKED", "artifact_hash": file_hash(pptx_path),
        "deterministic": {"status": "EVALUATED_PASS"}, "factual": {"status": "NOT_EVALUATED"},
        "rendered": {"status": "NOT_EVALUATED", "details": {"images": []}},
        "judge": {"status": "NOT_EVALUATED"}, "slides": []})
    artifacts = {path.name: file_hash(path) for path in revision.iterdir() if path.is_file()}
    atomic_json(revision / "revision.json", {
        "schema_version": 1, "revision_id": revision_id, "parent_id": None,
        "operation": "generate", "job_id": "fixture", "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts, "quality_state": "BASIC_CHECKED"})
    record_sha = file_hash(revision / "revision.json")
    atomic_json(deck_root / "active.json", {"schema_version": 1, "revision_id": revision_id,
                                            "record_sha256": record_sha})
    return revision


def _deck_with_revision(tmp_path: Path):
    """A JobStore-backed deck whose active revision is the hand-crafted bundle."""
    revision_id = "a" * 32
    deck_root = tmp_path / "decks" / "deck1"
    _publish_revision(deck_root, revision_id)
    source = tmp_path / "source.md"
    source.write_text("Attention combines values using learned weights.", encoding="utf-8")
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.add_document("doc", source.name, source, file_hash(source), source.stat().st_size)
    generation = store.create_deck("doc", deck_root, {"min_slides": 3, "max_slides": 3}, deck_id="deck1")
    # The revision is already published; the fixture never runs the generation job.
    store.cancel(generation.id)
    return store, deck_root, revision_id


def test_reference_ir_projection_matches_reference_contract():
    raw = {
        "document_name": "Report", "collection_id": None,
        "blocks": [
            {"block_id": "doc:block_0001", "text": "Revenue grew 12 percent in 2024.",
             "section_path": ["Results"], "document_id": "doc"},
            {"block_id": "doc:block_0002", "text": "   ", "section_path": ["Results"], "document_id": "doc"},
        ],
        "assets": [
            {"asset_id": "table_1", "kind": "table", "section_path": ["Results", "Tables"],
             "data": {"headers": ["Year", "Revenue"], "rows": [[2023, "10.2"], [2024, "11.4"]]}},
            {"asset_id": "fig_1", "kind": "image", "section_path": ["Figures"], "data": {}},
        ],
    }
    projection = _reference_ir_projection(raw)
    assert projection["document_name"] == "Report"
    # Blank blocks are dropped; section paths flatten to the reference label form.
    assert [block["block_id"] for block in projection["blocks"]] == ["doc:block_0001"]
    assert projection["blocks"][0]["section"] == "Results"
    # Only table assets become evidence chunks; cell values are stringified.
    assert len(projection["assets"]) == 1
    assert projection["assets"][0]["data"]["rows"][0] == ["2023", "10.2"]


def test_evaluation_summary_reports_every_metric_and_counts():
    report = {
        "run": {"run_id": "r1", "tool_name": "pptai-studio", "timestamp": "2026-01-01T00:00:00Z",
                "ai_judging": False, "embedding_backend": "tfidf_fallback"},
        "readiness": "DRAFT_INCOMPLETE",
        "quality_gate": {"deterministic_status": "EVALUATED_PASS"},
        "metrics": {
            "semantic": {"score": 0.5}, "coverage": {"weighted": 0.75, "strict_weighted": 0.7, "unweighted": 0.8},
            "faithfulness": {"status": "SKIPPED_DISABLED", "score": None, "claim_count": 0,
                             "evaluated_claim_count": 0, "hallucination_rate": None, "contradiction_rate": None},
            "functional": {"functional_sequence_score": 1.0},
            "structure": {"structural_score": 0.9},
            "visual": {"score": 0.88, "status": "EVALUATED_PASS"},
            "automated_overall": None, "available_metrics_score": 0.8},
        "concepts": [{"status": "COVERED"}, {"status": "PARTIALLY_COVERED"}, {"status": "COVERED"}],
        "claims": [{"label": "SUPPORTED"}, {"label": "UNSUPPORTED"}],
        "slides": [{}, {}, {}],
        "warnings": ["w"] * 25,
        "skipped_metrics": [{"metric": "faithfulness", "status": "SKIPPED_DISABLED", "reason": ""}],
    }
    summary = evaluation_summary(report, "deck1", "rev1")
    assert summary["deck_id"] == "deck1" and summary["revision_id"] == "rev1"
    assert [row["name"] for row in summary["metrics"]] == METRIC_NAMES
    assert summary["coverage"]["counts"] == {"COVERED": 2, "PARTIALLY_COVERED": 1, "MISSING": 0}
    assert summary["faithfulness"]["counts"]["UNSUPPORTED"] == 1
    assert summary["warning_count"] == 25 and len(summary["warnings"]) == 20  # capped for the UI
    assert summary["report_url"] == "/api/decks/deck1/revisions/rev1/evaluation/report"
    assert summary["overall"] is None and summary["available_metrics_score"] == 0.8


def test_run_revision_evaluation_refuses_incomplete_bundles(tmp_path):
    revision = tmp_path / "revisions" / ("a" * 32)
    revision.mkdir(parents=True)
    # Unpublished directory: no revision record at all.
    with pytest.raises(ValueError, match="not published"):
        run_revision_evaluation(tmp_path, "a" * 32, ai_judging=False)
    # Published record but evaluation inputs absent from the bundle.
    (revision / "revision.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        run_revision_evaluation(tmp_path, "a" * 32, ai_judging=False)


def test_run_revision_evaluation_scores_a_published_revision(tmp_path):
    deck_root = tmp_path / "decks" / "deck1"
    revision_id = "a" * 32
    _publish_revision(deck_root, revision_id)
    summary = run_revision_evaluation(deck_root, revision_id, deck_id="deck1", ai_judging=False)

    assert [row["name"] for row in summary["metrics"]] == METRIC_NAMES
    scored = [row["score"] for row in summary["metrics"] if row["name"] != "faithfulness"]
    assert scored and all(score is not None for score in scored)
    assert summary["slide_count"] == len(DECK_CONTENT["slides"])
    assert summary["available_metrics_score"] is not None
    # Deterministic keyless run: faithfulness is skipped, never half-run.
    assert summary["faithfulness"]["status"] == "SKIPPED_DISABLED"
    report = load_evaluation_report(deck_root, revision_id)
    assert report["status"] == "COMPLETED" and report["metrics"]["semantic"]["score"] is not None
    assert (evaluation_dir(deck_root, revision_id) / "report.json").is_file()
    # Evaluation output never lands inside the immutable revision bundle.
    assert not (deck_root / "revisions" / revision_id / "evaluation").exists()
    assert RevisionStore(deck_root).verify(deck_root / "revisions" / revision_id)["revision_id"] == revision_id
    # Re-running is deterministic and overwrites the previous report.
    again = run_revision_evaluation(deck_root, revision_id, deck_id="deck1", ai_judging=False)
    assert again["metrics"] == summary["metrics"]


def test_worker_evaluate_job_completes_and_reports_scores(tmp_path):
    store, deck_root, revision_id = _deck_with_revision(tmp_path)
    settings = ServiceSettings(root=tmp_path, poll_interval=.01)
    worker = __import__("workers.local", fromlist=["LocalWorker"]).LocalWorker(
        settings, store=store, provider_settings=get_multi_agent_settings({}))
    job = store.enqueue("evaluate", {"revision_id": revision_id, "ai_judging": False},
                        deck_id="deck1", document_id="doc")
    with worker.lifetime():
        assert worker.process_next()
    finished = store.get(job.id)
    assert finished.status == "completed"
    payload = finished.result
    assert payload["deck_id"] == "deck1" and payload["revision_id"] == revision_id
    assert [row["name"] for row in payload["evaluation"]["metrics"]] == METRIC_NAMES
    assert payload["evaluation"]["report_url"].endswith("/evaluation/report")
    assert (deck_root / "evaluation" / revision_id / "report.json").is_file()


def test_worker_enqueues_evaluation_after_generation_softly(tmp_path):
    store, deck_root, revision_id = _deck_with_revision(tmp_path)
    settings = ServiceSettings(root=tmp_path, poll_interval=.01)
    workers_module = __import__("workers.local", fromlist=["LocalWorker"])
    worker = workers_module.LocalWorker(settings, store=store,
                                        provider_settings=get_multi_agent_settings({}))
    job = SimpleNamespace(request={"provider_config": {"provider": "gemini", "evaluator_provider": "gemini"}},
                          document_id="doc")
    worker._enqueue_evaluation(job, {"id": "deck1"}, revision_id)
    queued = [entry for entry in store.deck_jobs("deck1") if entry.kind == "evaluate"]
    assert len(queued) == 1 and queued[0].status == "queued"
    # Keyless environments never request AI judging.
    assert queued[0].request["ai_judging"] is False
    assert queued[0].request["revision_id"] == revision_id
    # A broken store must never turn a finished generation into a failure.
    class BrokenStore:
        def enqueue(self, *args, **kwargs):
            raise RuntimeError("database gone")
    worker.store = BrokenStore()
    worker._enqueue_evaluation(job, {"id": "deck1"}, revision_id)  # must not raise


def test_evaluation_endpoints_lifecycle(tmp_path):
    store, deck_root, revision_id = _deck_with_revision(tmp_path)
    settings = ServiceSettings(root=tmp_path, poll_interval=.01)
    worker = __import__("workers.local", fromlist=["LocalWorker"]).LocalWorker(
        settings, store=store, provider_settings=get_multi_agent_settings({}))
    with TestClient(create_app(settings)) as client:
        deck_url = "/api/decks/deck1"
        eval_url = f"{deck_url}/revisions/{revision_id}/evaluation"

        active = client.get(deck_url).json()["active_revision"]
        assert active["revision_id"] == revision_id and active["pptx_url"].endswith("/pptx")

        # Before any evaluation ran the endpoint explains itself instead of erroring opaquely.
        missing = client.get(eval_url)
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "NOT_EVALUATED"
        assert client.get(eval_url + "/report").status_code == 404

        # The re-run button: queue an evaluation job for the published revision.
        rerun = client.post(f"{deck_url}/revisions/{revision_id}/evaluate")
        assert rerun.status_code == 202
        job_id = rerun.json()["job_id"]
        assert store.get(job_id).kind == "evaluate"
        # Unknown revisions and mismatched bodies are rejected.
        assert client.post(f"{deck_url}/revisions/{'b' * 32}/evaluate").status_code == 404
        assert client.post(f"{deck_url}/revisions/{revision_id}/evaluate",
                           json={"revision_id": "c" * 32}).status_code == 422

        with worker.lifetime():
            assert worker.process_next()

        summary = client.get(eval_url).json()
        assert summary["deck_id"] == "deck1" and summary["revision_id"] == revision_id
        assert [row["name"] for row in summary["metrics"]] == METRIC_NAMES
        assert summary["report_url"] == f"{eval_url}/report"
        full = client.get(summary["report_url"])
        assert full.status_code == 200 and full.json()["schema_version"] == "1.0"


def test_theme_chrome_and_effects_fire_for_structured_decks():
    """Every theme feature triggers once the storyboard plans varied structures.

    The F14 prompt changes push the planner toward TITLE_CENTERED openings,
    SECTION_DIVIDER transitions, quotes and card grids; this test pins the
    renderer side of that contract: each planned structure lights up the
    chrome/effect tokens its theme declares.
    """
    from domain.rendering.theme_engine import load_theme

    deck = {"title": "Attention Is All You Need", "slides": [
        {"layout": "TITLE_CENTERED", "content": {
            "title": {"type": "heading", "text": "Attention Is All You Need"},
            "subtitle": {"type": "text_group", "text": "Sequence modelling without recurrence."}}},
        {"layout": "SECTION_DIVIDER", "content": {
            "section_title": {"type": "heading", "text": "Method"},
            "section_subtitle": {"type": "text_group", "text": "How attention works."}}},
        {"layout": "QUOTE_CALLOUT", "content": {
            "quote": {"type": "quote", "text": "Attention is all you need.",
                      "attribution": "Vaswani et al."}}},
        {"layout": "METRIC_CALLOUT_3_GRID", "content": {
            "header": {"type": "heading", "text": "Key numbers"},
            "card_1": {"type": "metric_card", "value": "6", "label": "layers"},
            "card_2": {"type": "card", "title": "Parallel", "text": "Training parallelises."},
            "card_3": {"type": "callout", "title": "Short paths", "text": "One step suffices."}}},
        {"layout": "HEADER_WITH_BODY", "content": {
            "header": {"type": "heading", "text": "Attention summarizes source tokens"},
            "body": {"type": "bullets", "items": [
                "Learned weights combine token values.",
                "One step between positions."]}}},
    ]}
    for theme_id, expected in {
        "academic_slate": {"title-bar", "footer-title", "page-number", "numeral"},
        "corporate_blue": {"title-bar", "footer-title", "page-number", "rail"},
        "dark_tech": {"title-bar", "footer-title", "page-number", "rail"},
        "minimal_mono": {"title-bar", "footer-title", "page-number", "rail"},
        "warm_editorial": {"title-bar", "footer-title", "page-number", "numeral", "quote-mark"},
    }.items():
        builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True,
                                      theme=load_theme(theme_id))
        target = Path(f"/tmp/pptai-theme-fire-{theme_id}.pptx")
        builder.build(deck, str(target))
        applied = {name for names in builder.chrome_report["applied"].values() for name in names}
        missing = expected - applied
        assert not missing, f"{theme_id} did not trigger: {sorted(missing)}; got {sorted(applied)}"
        assert builder.chrome_report["failures"] == []
        # Themed visual objects: card backgrounds carry the theme surface tokens.
        scene = builder.last_scene
        card_bgs = [obj for slide in scene.slides for obj in slide.objects
                    if obj.role == "background" and obj.kind == "shape"]
        assert card_bgs, f"{theme_id} produced no visual-object surfaces"
        theme = load_theme(theme_id)
        fills = {obj.style.get("fill") for obj in card_bgs}
        assert fills <= {theme.surface, theme.surface_raised, theme.accent,
                         theme.accent_soft, theme.background}, f"{theme_id} unthemed fills: {fills}"
        # Effect tokens reach the scene styles the renderers consume.
        if theme.effects.shadow:
            assert any(obj.style.get("shadow") for obj in card_bgs), f"{theme_id} shadows dormant"
        if theme.effects.radius_in:
            assert any(obj.style.get("radius_in") is not None for obj in card_bgs
                       if obj.style.get("fill") != theme.accent), f"{theme_id} radius dormant"
        target.unlink(missing_ok=True)
