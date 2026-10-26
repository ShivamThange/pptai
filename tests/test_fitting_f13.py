"""F13 deterministic fitting: text measurement and pre-render overflow control."""
import json
from pathlib import Path

import pytest

from core import text_metrics as tm
from renderers.base import Box, PresentationScene, SceneObject, SlideScene
from renderers.fitting import fit_scene

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def make_scene(objects):
    return PresentationScene(width_inches=13.333, height_inches=7.5,
                            slides=[SlideScene(slide_id="slide-1", objects=objects)])


def test_wrap_and_capacity_are_consistent():
    cap = tm.capacity_for(11.7, 4.2, 16)
    assert cap.max_lines > 5 and cap.chars_per_line > 50
    text = "The dominant sequence transduction models use recurrence. " * 6
    lines = tm.wrap_text(text, 16, cap.width_pt)
    assert all(tm.text_width_pt(line, 16) <= cap.width_pt + 0.5 for line in lines)


def test_overflowing_bullets_scale_then_prune():
    bullets = [f"Finding {i}: a long descriptive sentence that will wrap in the region" for i in range(1, 15)]
    obj = SceneObject(object_id="slide-1/body", kind="bullets", box=Box(x=0.8, y=1.5, w=11.7, h=2.2),
                      content={"items": bullets}, style={"font_size": 16}, role="body")
    fitted, report = fit_scene(make_scene([obj]))
    out = fitted.slides[0].objects[0]
    actions = {a.action for a in report.adjustments}
    assert "font_scaled" in actions
    assert out.style["font_size"] < 16
    assert len(out.content["items"]) <= len(bullets)
    # Everything the fitting pass reports must mention real numbers.
    detail = next(a.detail for a in report.adjustments if a.action == "font_scaled")
    assert "pt" in detail


def test_fitting_bullets_keeps_at_least_two_items():
    bullets = ["A very long bullet " * 20, "Another very long bullet " * 20,
               "Third extremely long bullet " * 20, "Fourth " * 40]
    obj = SceneObject(object_id="slide-1/body", kind="bullets", box=Box(x=0.8, y=1.5, w=5.0, h=1.0),
                      content={"items": bullets}, style={"font_size": 16}, role="body")
    fitted, _ = fit_scene(make_scene([obj]))
    assert len(fitted.slides[0].objects[0].content["items"]) >= 2


def test_table_never_loses_rows_and_sets_column_widths():
    headers = ["Model", "BLEU", "Parameters"]
    rows = [[f"System {i}", f"{20 + i}.5", f"{100 + i}M"] for i in range(1, 13)]
    obj = SceneObject(object_id="slide-1/table", kind="table", box=Box(x=0.8, y=1.2, w=11.0, h=2.2),
                      content={"headers": headers, "rows": rows}, style={"font_size": 13}, role="table")
    fitted, report = fit_scene(make_scene([obj]))
    out = fitted.slides[0].objects[0]
    assert len(out.content["rows"]) == len(rows), "source table rows must never be pruned"
    assert len(out.content["col_widths_in"]) == len(headers)
    assert any(a.action == "table_columns" for a in report.adjustments)


def test_fitting_never_mutates_the_input_scene():
    obj = SceneObject(object_id="slide-1/body", kind="bullets", box=Box(x=0.8, y=1.5, w=5.0, h=1.0),
                      content={"items": ["short", "another short one", "a third bullet here"]},
                      style={"font_size": 16}, role="body")
    scene = make_scene([obj])
    before = json.dumps(scene.model_dump())
    fit_scene(scene)
    assert json.dumps(scene.model_dump()) == before


def test_fit_report_is_serializable():
    obj = SceneObject(object_id="slide-1/title", kind="heading", box=Box(x=0.8, y=0.3, w=11.7, h=0.7),
                      content={"text": "A Very Long Title " * 8}, style={"font_size": 34, "bold": True}, role="title")
    _, report = fit_scene(make_scene([obj]))
    payload = json.dumps(report.as_dict())
    assert "adjustments" in payload
