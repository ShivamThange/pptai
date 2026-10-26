"""End-to-end (offline LLM fixture): asset semantics -> IR1 -> selection -> rendered deck."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from f04_helpers import AssetCaller, enriched  # noqa: E402

from core.asset_registry import AssetRegistry  # noqa: E402
from core.builder import PresentationBuilder  # noqa: E402
from core.theme_engine import load_theme  # noqa: E402
from pipeline.asset_interpreter import validate_asset_insights  # noqa: E402
from pipeline.chunker import build_chunks  # noqa: E402
from pipeline.knowledge_extractor import generate_validated_ir1  # noqa: E402
from pipeline.quality_controller import run_deterministic_quality_checks  # noqa: E402
from pipeline.slide_composer import retrieve_slide_context  # noqa: E402
from pipeline.storyboard_planner import attach_asset_candidates, validate_storyboard  # noqa: E402
from pipeline.visual_placement import ensure_planned_visual  # noqa: E402
from schemas.ir2_content_schema import SlideSpec  # noqa: E402
from schemas.storyboard_schema import SlidePlan, Storyboard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "config" / "ppt_default_layouts.json"
SPEC = json.loads(LAYOUTS.read_text(encoding="utf-8"))


def test_figure_semantics_and_pixels_reach_the_final_deck(tmp_path):
    caller = AssetCaller()
    raw, run_root, _ = enriched("assets.docx", tmp_path, caller, "auto")
    # Live models routinely omit the anchor hash, region, qualification and
    # context refs. Local normalization must still accept a bounded observation.
    raw_image = next(asset for asset in raw.assets
                     if asset.kind == "image" and asset.section_path == ["Experimental comparison"])
    for insight in raw_image.content.interpretation.insights:
        if insight.basis == "visual_observation":
            insight.context_refs = []
            insight.qualification = None
            for anchor in insight.anchors:
                anchor.region = None
                anchor.source_sha256 = ""
    validate_asset_insights(raw_image.content.interpretation, raw)
    assert any(insight.eligibility in {"FACTUAL_TEXT", "QUALIFIED_TEXT"}
               for insight in raw_image.content.interpretation.insights)
    ir1 = generate_validated_ir1(raw, caller, run_root, extraction_mode="source-passages")
    chunks = build_chunks(ir1)

    image = next(asset for asset in ir1.assets if asset.kind == "image" and asset.section_path == ["Experimental comparison"])
    insight_unit = next(unit for unit in ir1.units if image.asset_id in unit.origin_asset_ids)
    source_unit = next(unit for unit in ir1.units
                       if not unit.origin_asset_ids and unit.section_path == image.section_path)
    chunk = next(chunk for chunk in chunks if source_unit.unit_id in chunk.unit_ids)

    plan = SlidePlan(slide_id=1, title="Comparison", objective="Explain the comparison",
                     narrative_role="evidence", chunk_refs=[chunk.chunk_id],
                     source_unit_ids=[source_unit.unit_id], candidate_asset_ids=[],
                     preferred_layouts=["HEADER_WITH_BODY"])
    storyboard = Storyboard(document_title="Comparison", lens="academic", slides=[plan])
    attach_asset_candidates(storyboard, ir1, SPEC, chunks)
    validate_storyboard(storyboard, chunks, ir1, SPEC, min_slides=1, max_slides=1)

    plan = storyboard.slides[0]
    assert image.asset_id in plan.candidate_asset_ids
    assert insight_unit.unit_id in plan.source_unit_ids, "asset meaning must enter the slide scope"

    context = retrieve_slide_context(plan, ir1, chunks, storyboard)
    assert any(asset["asset_id"] == image.asset_id for asset in context["assets"])
    assert any(unit["unit_id"] == insight_unit.unit_id for unit in context["knowledge_units"])

    slide = SlideSpec(layout="HEADER_WITH_BODY", content={
        "header": {"type": "heading", "text": "Experimental comparison"},
        "body": {"type": "bullets", "items": [source_unit.summary]},
    })
    placed = ensure_planned_visual(slide, plan, context, SPEC)
    assert placed.layout == "IMAGE_WITH_TEXT_RIGHT"
    assert placed.content["image"].source_asset_id == image.asset_id
    assert placed.content["text"].type == "bullets"

    registry = AssetRegistry(ir1.assets, run_root=run_root, source_item_ids=ir1.source_item_ids,
                             asset_source_items=ir1.asset_source_items)
    builder = PresentationBuilder(LAYOUTS, asset_registry=registry, backend="python",
                                  theme=load_theme("academic_slate"), dynamic_layout=True)
    builder.asset_search_dirs = [run_root / "assets" / "images", run_root / "assets" / "formulas",
                                 run_root / "assets" / "tables", run_root]
    target = tmp_path / "asset_deck.pptx"
    assert builder.build({"slides": [placed.model_dump(exclude_none=True)]}, str(target)) == []
    assert any(obj.kind == "image" and obj.content.get("source_asset_id") == image.asset_id
               for obj in builder.last_scene.slides[0].objects)
    report = run_deterministic_quality_checks(target, tmp_path / "quality", raise_on_failure=False)
    assert report.deterministic.status == "EVALUATED_PASS", report.hard_failures
