"""F13 predefined visual objects and F04 planned-visual placement."""
import json
from pathlib import Path

import pytest

from application.jobs.builder import PresentationBuilder
from domain.rendering.theme_engine import load_theme
from infrastructure.ingestion.quality_controller import run_deterministic_quality_checks
from infrastructure.ingestion.slide_composer import visible_claims
from infrastructure.ingestion.storyboard_planner import build_layout_catalog
from infrastructure.ingestion.visual_placement import ensure_planned_visual
from renderers.base import VISUAL_OBJECT_KINDS
from contracts.ir2_content_schema import SlideSpec

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "config" / "ppt_default_layouts.json"
SPEC = json.loads(LAYOUTS.read_text(encoding="utf-8"))


def object_deck():
    return {"slides": [
        {"layout": "METRIC_CALLOUT_3_GRID", "content": {
            "header": {"type": "heading", "text": "Numbers"},
            "card_1": {"type": "metric_card", "value": "28.4", "label": "BLEU", "context": "state of the art"},
            "card_2": {"type": "metric_card", "value": "41.0", "label": "BLEU FR", "trend": "+1.0"},
            "card_3": {"type": "metric_card", "value": "6", "label": "layers"}}},
        {"layout": "GRID_2X2", "content": {
            "header": {"type": "heading", "text": "Four points"},
            "quadrant_1": {"type": "card", "title": "Attention", "text": "One step between positions."},
            "quadrant_2": {"type": "callout", "title": "Parallel", "text": "Training parallelises."},
            "quadrant_3": {"type": "quote", "text": "Attention is all you need.", "attribution": "Vaswani"},
            "quadrant_4": {"type": "chips", "labels": ["Encoder", "Decoder"]}}},
        {"layout": "COMPARISON_2_COLUMNS", "content": {
            "header": {"type": "heading", "text": "Compare"},
            "option_a": {"type": "compare",
                         "left": {"heading": "Recurrent", "items": ["Sequential"]},
                         "right": {"heading": "Attention", "items": ["Parallel"]}},
            "option_b": {"type": "card", "title": "Takeaway", "text": "Shorter paths."}}},
    ]}


def test_every_object_kind_is_declared_and_catalogued():
    assert VISUAL_OBJECT_KINDS == {"card", "metric_card", "callout", "quote", "chips", "compare"}
    catalog = build_layout_catalog(SPEC)
    declared = {content_type for layout in catalog.values()
                for region in layout["regions"].values() for content_type in region["allowed_types"]}
    assert VISUAL_OBJECT_KINDS <= declared
    for layout, region in (("METRIC_CALLOUT_3_GRID", "card_1"), ("GRID_2X2", "quadrant_1"),
                           ("COMPARISON_2_COLUMNS", "option_a")):
        assert "card" in SPEC["layouts"][layout]["regions"][region]["allowed_types"]


def test_objects_expand_to_native_scene_primitives_and_pass_the_gate(tmp_path):
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True,
                                  theme=load_theme("academic_slate"))
    target = tmp_path / "objects.pptx"
    warnings = builder.build(object_deck(), str(target))
    assert warnings == []
    # One IR2 region becomes a background shape plus real text objects.
    scene = builder.last_scene
    background = [obj for slide in scene.slides for obj in slide.objects
                  if obj.kind == "shape" and obj.role == "background"]
    assert len(background) == 11  # 3 metric + (card, callout, quote, 2 chips) + (2 compare, 1 card)
    report = run_deterministic_quality_checks(target, tmp_path / "quality", raise_on_failure=False)
    assert report.deterministic.status == "EVALUATED_PASS", report.hard_failures
    assert report.slides and all(row["small_font_count"] == 0 for row in report.slides)


def test_visible_claims_include_object_text():
    slide = SlideSpec(layout="GRID_2X2", content={
        "header": {"type": "heading", "text": "H"},
        "quadrant_1": {"type": "card", "title": "T", "text": "Body", "metric": {"value": "9", "label": "L"}},
        "quadrant_2": {"type": "callout", "title": "C", "text": "Callout body"},
        "quadrant_3": {"type": "quote", "text": "Q", "attribution": "A"},
        "quadrant_4": {"type": "chips", "labels": ["one", "two"]},
    })
    claims = visible_claims(slide)
    values = set(claims.values())
    assert {"T", "Body", "9", "L", "C", "Callout body", "Q", "A", "one", "two"} <= values


def test_planned_visual_is_placed_without_losing_text():
    slide = SlideSpec(layout="HEADER_WITH_BODY", content={
        "header": {"type": "heading", "text": "Architecture"},
        "body": {"type": "bullets", "items": ["Encoder stack", "Decoder stack"]},
    })
    asset = {"asset_id": "image_test", "kind": "image", "caption": "Figure 1: architecture.",
             "caption_binding": "DIRECT"}

    class Plan:
        candidate_asset_ids = ["image_test"]

    placed = ensure_planned_visual(slide, Plan(), {"assets": [asset]}, SPEC)
    assert placed.layout == "IMAGE_WITH_TEXT_RIGHT"
    assert placed.content["image"].type == "image"
    assert placed.content["image"].source_asset_id == "image_test"
    assert placed.content["text"].type == "bullets"
    assert ["Encoder stack", "Decoder stack"] == placed.content["text"].items


def test_planned_visual_never_replaces_existing_text_region():
    slide = SlideSpec(layout="HEADER_WITH_BODY", content={
        "header": {"type": "heading", "text": "H"},
        "body": {"type": "bullets", "items": ["keep me"]},
    })
    asset = {"asset_id": "image_test", "kind": "image", "caption": None, "caption_binding": "UNKNOWN"}

    class Plan:
        candidate_asset_ids = ["image_test"]

    placed = ensure_planned_visual(slide, Plan(), {"assets": [asset]}, SPEC)
    assert any(content.type == "bullets" and "keep me" in content.items
               for content in placed.content.values())


def test_table_slide_is_not_remapped_for_a_visual():
    slide = SlideSpec(layout="TABLE_FULL_WIDTH", content={
        "header": {"type": "heading", "text": "Results"},
        "table": {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
    })
    asset = {"asset_id": "formula_test", "kind": "formula", "caption": None, "caption_binding": "UNKNOWN"}

    class Plan:
        candidate_asset_ids = ["formula_test"]

    placed = ensure_planned_visual(slide, Plan(), {"assets": [asset]}, SPEC)
    assert placed.layout == "TABLE_FULL_WIDTH"
    assert placed.content["table"].type == "table"


def test_planned_visual_remaps_a_stat_slide_without_losing_the_value():
    slide = SlideSpec(layout="BIG_NUMBER_WITH_CONTEXT", content={
        "header": {"type": "heading", "text": "Accuracy"},
        "stat": {"type": "stat", "items": [{"value": "91.2", "label": "accuracy"}]},
        "context": {"type": "text_group", "text": "Measured on the held-out set."},
    })
    asset = {"asset_id": "image_test", "kind": "image", "caption": None, "caption_binding": "UNKNOWN"}

    class Plan:
        candidate_asset_ids = ["image_test"]

    placed = ensure_planned_visual(slide, Plan(), {"assets": [asset]}, SPEC)
    assert placed.layout == "IMAGE_WITH_TEXT_RIGHT"
    assert placed.content["image"].type == "image"
    items = [line for content in placed.content.values() if content.type == "bullets"
             for line in content.items]
    assert "91.2 — accuracy" in items and "Measured on the held-out set." in items


def test_storyboard_attaches_a_section_matched_figure():
    from contracts.ir1_schema import EvidenceRef, KnowledgeUnit, ValidatedIR1, VisualAsset
    from contracts.storyboard_schema import SlidePlan, Storyboard
    from infrastructure.ingestion.storyboard_planner import attach_asset_candidates

    asset = VisualAsset(asset_id="image_a", kind="image", section_path=["3.1 Encoder"],
                        source_refs=[], locations=[], caption_refs=[], caption_locations=[],
                        findings=[], caption="Figure 1: architecture.", caption_binding="DIRECT")
    unit = KnowledgeUnit(unit_id="ku_a", kind="concept", title="Encoder", summary="Encoder stack",
                         section_path=["3.1 Encoder"], validation_status="VALIDATED",
                         evidence=[EvidenceRef(source_id="block_1", excerpt="encoder stack")])
    ir1 = ValidatedIR1(document_title="Paper", units=[unit], assets=[asset])
    storyboard = Storyboard(document_title="Paper", lens="academic", slides=[SlidePlan(
        slide_id=1, title="Architecture", objective="Show it", narrative_role="method",
        chunk_refs=["chunk_a"], source_unit_ids=["ku_a"], candidate_asset_ids=[],
        preferred_layouts=["HEADER_WITH_BODY"])])
    attach_asset_candidates(storyboard, ir1, SPEC)
    assert storyboard.slides[0].candidate_asset_ids == ["image_a"]
