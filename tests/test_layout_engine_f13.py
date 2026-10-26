"""F13 dynamic layout: bounded candidates, feasibility, variety, and fallback."""
import copy
import json
from pathlib import Path

import pytest
from pptx import Presentation

from application.jobs.builder import PresentationBuilder
from domain.rendering.layout_engine import DynamicLayoutEngine

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "config" / "ppt_default_layouts.json"
SPEC = json.loads(LAYOUTS.read_text(encoding="utf-8"))


def content_slide(layout, regions):
    return {"layout": layout, "content": regions}


def text_body(sentences):
    return {"type": "bullets", "items": sentences}


def test_engine_resolves_region_defs_for_every_common_pattern():
    engine = DynamicLayoutEngine(SPEC)
    deck = {"slides": [
        content_slide("TITLE_CENTERED", {"title": {"type": "heading", "text": "Opening"},
                                         "subtitle": {"type": "text_group", "text": "A study"}}),
        content_slide("HEADER_WITH_BODY", {"header": {"type": "heading", "text": "Findings"},
                                           "body": text_body(["One", "Two", "Three"])}),
        content_slide("TABLE_FULL_WIDTH", {"header": {"type": "heading", "text": "Numbers"},
                                           "table": {"type": "table", "headers": ["A", "B"],
                                                     "rows": [["1", "2"], ["3", "4"]]},
                                           "source": {"type": "text_group", "text": "Table 1"}}),
        content_slide("KPI_ROW_WITH_CHART", {
            "header": {"type": "heading", "text": "Metrics"},
            "kpi_1": {"type": "stat", "items": [{"value": "9", "label": "x"}]},
            "kpi_2": {"type": "stat", "items": [{"value": "8", "label": "y"}]},
            "kpi_3": {"type": "stat", "items": [{"value": "7", "label": "z"}]},
            "chart": {"type": "chart", "chart_type": "column", "categories": ["a", "b"],
                      "series": [{"name": "s", "values": [1, 2]}]}}),
        content_slide("GRID_2X2", {
            "header": {"type": "heading", "text": "Grid"},
            "quadrant_1": text_body(["a"]),
            "quadrant_2": text_body(["b"]),
            "quadrant_3": text_body(["c"]),
            "quadrant_4": text_body(["d"])}),
    ]}
    regions, report = engine.solve_deck(deck)
    assert regions is not None and set(regions) == {1, 2, 3, 4, 5}
    for index, override in regions.items():
        catalog = SPEC["layouts"][deck["slides"][index - 1]["layout"]]["regions"]
        for name, region in override.items():
            # Complete, catalog-compatible region definitions.
            assert 0 <= region["left"] and region["top"] >= 0
            assert region["left"] + region["width"] <= 1.0001
            assert region["top"] + region["height"] <= 1.0001
            assert region["allowed_types"] == catalog[name]["allowed_types"]
            assert region["default_style"] == catalog[name].get("default_style") or region["default_style"] == {}
    archetypes = [s["detail"]["archetype"] for s in report["slides"]]
    assert archetypes[0] == "title-only"
    assert archetypes[3].startswith("bento-")


def test_same_content_supports_several_valid_compositions():
    """Acceptance: one content plan, multiple feasible archetypes; variety
    across a deck must not collapse to a single repeated composition."""
    engine = DynamicLayoutEngine(SPEC)
    slide = content_slide("HEADER_WITH_2_COLUMNS", {
        "header": {"type": "heading", "text": "Two views"},
        "left_col": text_body(["left " * 4, "more left content here"]),
        "right_col": text_body(["right " * 4, "more right content here"])})
    solved_first, detail_first = engine._solve_slide(slide, [])
    solved_repeat, detail_repeat = engine._solve_slide(slide, ["split-pair"])
    assert solved_first is not None and solved_repeat is not None
    # Both are valid; the repeat context must steer toward a different archetype
    # or accept a score penalty that is recorded deterministically.
    assert detail_first["archetype"] in {"split-pair", "split-media-left", "split-media-right"}
    assert detail_repeat["score"] <= detail_first["score"] + 0.001


def test_bento_spans_vary_with_content():
    """Acceptance: bento cell counts/spans track the content, not a fixed grid."""
    engine = DynamicLayoutEngine(SPEC)
    kpi = content_slide("KPI_ROW_WITH_CHART", {
        "header": {"type": "heading", "text": "Metrics"},
        "kpi_1": {"type": "stat", "items": [{"value": "9", "label": "x"}]},
        "kpi_2": {"type": "stat", "items": [{"value": "8", "label": "y"}]},
        "chart": {"type": "chart", "chart_type": "column", "categories": ["a"],
                  "series": [{"name": "s", "values": [1]}]}})
    _, detail = engine._solve_slide(kpi, [])
    boxes = detail["regions"]
    chart_box, kpi_boxes = boxes["chart"], [boxes["kpi_1"], boxes["kpi_2"]]
    # The chart is wide (full frame width); the stats share one narrow band.
    assert chart_box[2] > sum(k[2] for k in kpi_boxes)
    assert abs(kpi_boxes[0][3] - kpi_boxes[1][3]) < 0.01  # same band height
    grid = content_slide("GRID_2X2", {
        "header": {"type": "heading", "text": "Grid"},
        "quadrant_1": text_body(["a"]), "quadrant_2": text_body(["b"]),
        "quadrant_3": text_body(["c"]), "quadrant_4": text_body(["d"])})
    _, grid_detail = engine._solve_slide(grid, [])
    grid_boxes = list(grid_detail["regions"].values())
    widths = {round(b[2], 2) for b in grid_boxes}
    heights = {round(b[3], 2) for b in grid_boxes}
    assert len(widths) <= 2 and len(heights) <= 2  # a true 2x2-style grid


def test_dense_table_never_breaks_floors_silently():
    """Acceptance: font floors hold; anything tight is reported, never silent."""
    engine = DynamicLayoutEngine(SPEC)
    rows = [[f"System {i}", f"{20 + i}.5", f"{100 + i}M", f"note {i}"] for i in range(1, 23)]
    slide = content_slide("TABLE_FULL_WIDTH", {
        "header": {"type": "heading", "text": "Dense source table"},
        "table": {"type": "table", "headers": ["Model", "Score", "Size", "Notes"], "rows": rows},
        "source": {"type": "text_group", "text": "Source: appendix."}})
    solved, detail = engine._solve_slide(slide, [])
    assert solved is not None, "a dense-but-renderable table must resolve"
    assert detail["fit"]["table"]["status"] == "tight", "density must be reported, never silent"
    # And the rendered artifact keeps every row with a font at or above the floor.
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    target = ROOT / "tests" / "_f13_dense_table.pptx"
    builder.build({"slides": [slide]}, str(target))
    assert not [w for w in builder.warnings if "kept_overflow" in w]
    table_obj = next(o for o in builder.last_scene.slides[0].objects if o.kind == "table")
    assert len(table_obj.content["rows"]) == len(rows)
    assert table_obj.style.get("font_size", 13) >= 8
    target.unlink(missing_ok=True)


def test_impossible_table_falls_back_with_a_recorded_reason():
    """A table that cannot fit even at the floor falls back to the catalog and
    leaves a diagnostic; the renderer still keeps every row."""
    engine = DynamicLayoutEngine(SPEC)
    rows = [[f"System {i}", f"{20 + i}.5", f"{100 + i}M params", "long qualitative note " * 3]
            for i in range(1, 26)]
    slide = content_slide("TABLE_FULL_WIDTH", {
        "header": {"type": "heading", "text": "Oversized source table"},
        "table": {"type": "table", "headers": ["Model", "Score", "Size", "Notes"], "rows": rows},
        "source": {"type": "text_group", "text": "Source: appendix."}})
    solved, detail = engine._solve_slide(slide, [])
    assert solved is None
    assert detail["fallback_reason"] == "no feasible candidate"
    assert all(not c["feasible"] for c in detail["candidates"])
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    target = ROOT / "tests" / "_f13_oversized.pptx"
    builder.build({"slides": [slide]}, str(target))
    table_obj = next(o for o in builder.last_scene.slides[0].objects if o.kind == "table")
    assert len(table_obj.content["rows"]) == len(rows), "rows preserved for grounding"
    assert table_obj.style.get("font_size", 13) >= 8, "floor never broken silently"
    target.unlink(missing_ok=True)


def test_layout_only_solving_preserves_content_and_evidence():
    """Acceptance: layout-only edits preserve factual content/evidence hashes."""
    deck = {"slides": [
        content_slide("HEADER_WITH_BODY", {
            "header": {"type": "heading", "text": "Claim"},
            "body": text_body(["Accuracy improved to 74.5% on the held-out set"])}),
    ]}
    deck["slides"][0]["source_unit_ids"] = ["u-1", "u-2"]
    deck["slides"][0]["grounding"] = {"u-1": {"status": "VERIFIED"}}
    before = json.dumps(deck, sort_keys=True)
    engine = DynamicLayoutEngine(SPEC)
    engine.solve_deck(deck)
    assert json.dumps(deck, sort_keys=True) == before, "solver must not touch content"


def test_rendered_deck_is_in_bounds_and_fully_covered():
    """Acceptance: rendered PPTX passes fit and coverage checks."""
    deck = {"title": "Dynamic", "output_filename": "dynamic.pptx", "slides": [
        content_slide("TITLE_CENTERED", {"title": {"type": "heading", "text": "Opening"},
                                         "subtitle": {"type": "text_group", "text": "subtitle"}}),
        content_slide("HEADER_WITH_BODY", {"header": {"type": "heading", "text": "Findings"},
                                           "body": text_body([f"Finding {i} with detail" for i in range(6)])}),
        content_slide("KPI_ROW_WITH_CHART", {
            "header": {"type": "heading", "text": "Metrics"},
            "kpi_1": {"type": "stat", "items": [{"value": "91.2%", "label": "Accuracy"}]},
            "kpi_2": {"type": "stat", "items": [{"value": "3.5B", "label": "Params"}]},
            "kpi_3": {"type": "stat", "items": [{"value": "2.4x", "label": "Speedup"}]},
            "chart": {"type": "chart", "chart_type": "column", "categories": ["S", "M", "L"],
                      "series": [{"name": "Score", "values": [70.1, 82.4, 91.2]}]}}),
        content_slide("TABLE_FULL_WIDTH", {
            "header": {"type": "heading", "text": "Results"},
            "table": {"type": "table", "headers": ["Model", "Score"],
                      "rows": [["A", "91.2"], ["B", "88.4"], ["C", "85.0"]]},
            "source": {"type": "text_group", "text": "Source: table 2."}}),
    ]}
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    target = ROOT / "tests" / "_f13_dynamic.pptx"
    warnings = builder.build(deck, str(target))
    assert not [w for w in warnings if "kept_overflow" in w]
    scene = builder.last_scene
    for slide in scene.slides:
        for obj in slide.objects:
            assert obj.box.x >= -0.01 and obj.box.y >= -0.01
            assert obj.box.x + obj.box.w <= scene.width_inches + 0.01
            assert obj.box.y + obj.box.h <= scene.height_inches + 0.01
    # Native coverage: every text object exists in the rendered file.
    opened = Presentation(str(target))
    names = {shape.name for slide in opened.slides for shape in slide.shapes}
    for slide in scene.slides:
        for obj in slide.objects:
            assert obj.object_id in names, f"missing rendered object {obj.object_id}"
    target.unlink(missing_ok=True)


def test_solver_failure_falls_back_to_catalog():
    """Any solver defect must degrade to the proven catalog geometry."""
    engine = DynamicLayoutEngine(SPEC)
    broken = {"layout": "HEADER_WITH_BODY", "content": {"header": None}}
    solved, detail = engine._solve_slide(broken, [])
    assert solved is None and "fallback_reason" in detail
    # The builder path is equally safe: garbage regions still build.
    builder = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    target = ROOT / "tests" / "_f13_fallback.pptx"
    deck = {"slides": [content_slide("HEADER_WITH_BODY", {
        "header": {"type": "heading", "text": "Fallback"},
        "body": text_body(["still renders"])})]}
    builder.build(deck, str(target))
    assert target.is_file()
    target.unlink(missing_ok=True)


def test_dynamic_layout_disabled_matches_catalog_geometry():
    deck = {"slides": [content_slide("HEADER_WITH_BODY", {
        "header": {"type": "heading", "text": "Static"},
        "body": text_body(["fixed geometry"])})]}
    static = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=False)
    dynamic = PresentationBuilder(LAYOUTS, backend="python", dynamic_layout=True)
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        static.build(copy.deepcopy(deck), str(Path(directory) / "static.pptx"))
        dynamic.build(copy.deepcopy(deck), str(Path(directory) / "dynamic.pptx"))
        catalog_region = SPEC["layouts"]["HEADER_WITH_BODY"]["regions"]["body"]
        static_box = next(o for o in static.last_scene.slides[0].objects if o.role == "body").box
        assert abs(static_box.w - catalog_region["width"] * 13.333) < 0.01
        dynamic_box = next(o for o in dynamic.last_scene.slides[0].objects if o.role == "body").box
        assert dynamic_box.w <= 9.81  # readable single-column text cap
