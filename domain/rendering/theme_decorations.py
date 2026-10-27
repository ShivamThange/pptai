"""Theme chrome decorations over a resolved scene (F13 theme elevation).

Adds presentation-layer chrome - title underline bars, a footer rule with the
deck title and page number, cover/closing accent rails, section numerals and
oversized quote marks - as ordinary scene objects, so both renderer backends
draw them with no backend-specific code path.

Design contract (mirrors the repo's error conventions):

- Pure: returns a deep copy plus a debug report; the input scene, its factual
  content, grounding and evidence are never touched.
- Never fatal: a theme is a data file, so any geometry that does not fit a
  particular slide is skipped for that slide only and recorded in the report.
  The undecorated slide is still a perfectly valid scene, so the pipeline can
  never stall over chrome. Unexpected per-slide errors are caught the same way
  (the report's ``failures`` list names them) instead of raising.
- Never harmful: every decoration is anchored to existing object geometry and
  is skipped when it would intersect content, leave the slide bounds, or
  collide with already-placed chrome - the deterministic quality gate must
  not gain a single new failure from decorations.
- Decorations carry role ``decor`` (shapes / display text, no content) or
  ``caption`` (small footer text, 10pt readability floor) and
  ``required=False``, so coverage verification, the fitting pass and the
  readability floors all treat them as non-essential.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from renderers.base import Box, PresentationScene, SceneObject

SHAPE_ROLE = "decor"          # textless chrome shapes; no readability floor
SMALL_TEXT_ROLE = "caption"   # footer text at 10pt (caption floor is 10pt)
DISPLAY_TEXT_ROLE = "decor"   # numerals / quote marks (well above any floor)

_CLEARANCE = 0.03       # inches kept between chrome boxes and content boxes
_EDGE_CLEARANCE = 0.02  # inches kept between chrome boxes and the slide edge
_FOOTER_CLEARANCE = 0.01  # the footer strip may sit just below the content frame
_FOOTER_BOTTOM_MARGIN = 0.04  # footer text sits this far from the slide edge
_FOOTER_TEXT_HEIGHT = 0.34    # 10pt line (1.22 spacing + gap) + frame insets
_PAGE_NUMBER_WIDTH = 1.5
_FOOTER_RULE_HEIGHT = 0.012

_TITLE_REGIONS = {"title", "header", "section_title", "overlay_title"}
# Region names that mark a chrome-only slide (cover / closing / divider):
# a rail is only drawn where no content region exists.
_TITLEISH_REGIONS = _TITLE_REGIONS | {"subtitle", "section_subtitle",
                                      "message", "contact", "overlay_text"}
# Region names that already carry their own footer-like content.
_FOOTER_REGIONS = {"source", "footer", "footnote", "contact", "attribution"}


class ChromeReport(BaseModel):
    """Debug-friendly record of what chrome was applied or skipped, per slide."""

    engine: str = "theme-chrome-v1"
    theme: str = ""
    applied: dict[str, list[str]] = {}
    skipped: dict[str, list[str]] = {}
    failures: list[str] = []


def apply_theme_decorations(scene: PresentationScene,
                            theme: Any) -> tuple[PresentationScene, ChromeReport]:
    """Return ``(decorated scene, report)``; never raises.

    ``theme`` may be ``None`` or a legacy theme without chrome, in which case
    the scene is returned unchanged with an empty report.
    """
    chrome = getattr(theme, "chrome", None)
    report = ChromeReport(theme=getattr(theme, "id", ""))
    if theme is None or chrome is None:
        return scene, report
    if not (chrome.title_bar or chrome.footer or chrome.cover_rail
            or chrome.section_numeral or chrome.quote_mark):
        return scene, report  # chrome explicitly disabled: byte-identical output

    themed = scene.model_copy(deep=True)
    section_seen = 0
    total = len(themed.slides)
    for number, slide in enumerate(themed.slides, 1):
        if any(_region_of(obj) == "section_title" for obj in slide.objects):
            section_seen += 1
        try:
            _decorate_slide(slide, number, total, section_seen, theme, themed, report)
        except Exception as error:  # One bad slide must never stall the pipeline.
            report.failures.append(f"{slide.slide_id}: chrome skipped "
                                   f"({type(error).__name__}: {error})")
    return themed, report


# ---------------------------------------------------------------------------
# Per-slide dispatch
# ---------------------------------------------------------------------------


def _decorate_slide(slide, number: int, total: int, section_no: int,
                    theme, scene: PresentationScene, report: ChromeReport) -> None:
    chrome = theme.chrome
    width, height = scene.width_inches, scene.height_inches
    occupied = [obj.box for obj in slide.objects]
    kinds = {obj.kind for obj in slide.objects}

    if chrome.cover_rail and _is_titleish(slide, kinds):
        _try_rail(slide, occupied, theme, width, height, report)
    if chrome.title_bar:
        anchor = next((obj for obj in slide.objects
                       if obj.kind == "heading" and obj.role == "title"
                       and _region_of(obj) in _TITLE_REGIONS), None)
        if anchor is not None:
            _try_title_bar(slide, anchor, occupied, theme, width, height, report)
    if chrome.footer:
        _try_footer(slide, occupied, theme, scene, number, total, width, height, report)
    if chrome.section_numeral and section_no:
        _try_numeral(slide, occupied, theme, section_no, width, height, report)
    if chrome.quote_mark:
        _try_quote_mark(slide, occupied, theme, width, height, report)


# ---------------------------------------------------------------------------
# Individual decorations (each guarded, each best-effort)
# ---------------------------------------------------------------------------


def _try_rail(slide, occupied, theme, width: float, height: float,
              report: ChromeReport) -> None:
    """Full-height accent rail on the left edge of chrome-only slides."""
    name = "rail"
    try:
        rail_w = theme.chrome.cover_rail_width_in
        rail = Box(x=0.0, y=0.0, w=rail_w, h=height)
        if rail_w <= 0 or rail_w * 2 >= width:
            return _skip(report, slide, name, "rail width exceeds the slide")
        if any(_intersects(rail, box, _EDGE_CLEARANCE) for box in occupied):
            return _skip(report, slide, name, "content reaches the left edge")
        # Appended, not inserted: chrome must never shift the position of real
        # content objects. The rail is opaque and guarded against every content
        # box, so rendering it last (top of the z-order) is visually identical
        # to rendering it first.
        slide.objects.append(_shape(f"{slide.slide_id}//decor-rail", rail,
                                    theme.accent))
        occupied.append(rail)
        _applied(report, slide, name)
    except Exception as error:
        _fail(report, slide, name, error)


def _try_title_bar(slide, anchor, occupied, theme, width: float, height: float,
                   report: ChromeReport) -> None:
    """Accent underline bar anchored below the slide's title box."""
    name = "title-bar"
    try:
        chrome = theme.chrome
        bar_w = min(chrome.title_bar_width_in, anchor.box.w)
        bar = Box(x=anchor.box.x, y=anchor.box.y + anchor.box.h + _CLEARANCE,
                  w=bar_w, h=chrome.title_bar_height_in)
        # A centered title gets a centered bar; left/right titles anchor at x.
        if (anchor.style or {}).get("align") == "center":
            bar = bar.model_copy(update={"x": anchor.box.x + (anchor.box.w - bar_w) / 2})
        if not _fits_slide(bar, width, height):
            return _skip(report, slide, name, "would leave the slide bounds")
        if any(_intersects(bar, box) and box is not anchor.box for box in occupied):
            return _skip(report, slide, name, "would overlap content")
        slide.objects.append(_shape(f"{slide.slide_id}//decor-title-bar", bar,
                                    theme.accent))
        occupied.append(bar)
        _applied(report, slide, name)
    except Exception as error:
        _fail(report, slide, name, error)


def _try_footer(slide, occupied, theme, scene: PresentationScene, number: int,
                total: int, width: float, height: float, report: ChromeReport) -> None:
    """Hairline rule plus muted deck title and page number at the bottom."""
    name = "footer"
    try:
        chrome = theme.chrome
        # Slides that already declare footer-like content keep their own footer.
        if any(_region_of(obj) in _FOOTER_REGIONS for obj in slide.objects):
            return _skip(report, slide, name, "slide already carries footer content")
        content = [obj.box for obj in slide.objects if obj.kind != "connector"]
        left = min([0.8, *(box.x for box in content)]) if content else 0.8
        right = max([width / 2 + 1.0,
                     *(min(width - 0.62, box.x + box.w) for box in content)])
        text_box = Box(x=left, y=height - _FOOTER_BOTTOM_MARGIN - _FOOTER_TEXT_HEIGHT,
                       w=right - left, h=_FOOTER_TEXT_HEIGHT)
        # The dynamic layout frame ends 0.40in above the slide edge, so the
        # footer uses a tighter clearance than other chrome to keep firing on
        # solver-laid slides; raw box overlap (what the quality gate checks)
        # is still impossible.
        if any(_intersects(text_box, box, _FOOTER_CLEARANCE) for box in occupied):
            return _skip(report, slide, name, "content reaches the slide bottom")

        if chrome.footer_rule:
            rule = Box(x=left, y=text_box.y - _CLEARANCE - _FOOTER_RULE_HEIGHT,
                       w=right - left, h=_FOOTER_RULE_HEIGHT)
            if _fits_slide(rule, width, height) and not any(
                    _intersects(rule, box) for box in occupied):
                slide.objects.append(_shape(f"{slide.slide_id}//decor-footer-rule",
                                            rule, theme.connector))
                occupied.append(rule)
                _applied(report, slide, "footer-rule")

        muted = {"color": theme.text_muted, "font_size": chrome.footer_font_pt,
                 "align": "left"}
        if theme.body_font:
            muted["font_name"] = theme.body_font
        title_text = (scene.title or "").strip()
        if title_text:
            slide.objects.append(SceneObject(
                object_id=f"{slide.slide_id}//decor-footer-title", kind="text_group",
                box=Box(x=text_box.x, y=text_box.y,
                        w=max(0.5, text_box.w - _PAGE_NUMBER_WIDTH - 0.2),
                        h=text_box.h),
                content={"text": title_text}, role=SMALL_TEXT_ROLE, required=False,
                style=dict(muted)))
            _applied(report, slide, "footer-title")
        if chrome.page_number:
            page = dict(muted, align="right")
            slide.objects.append(SceneObject(
                object_id=f"{slide.slide_id}//decor-page-number", kind="text_group",
                box=Box(x=right - _PAGE_NUMBER_WIDTH, y=text_box.y,
                        w=_PAGE_NUMBER_WIDTH, h=text_box.h),
                content={"text": f"{number} / {total}"}, role=SMALL_TEXT_ROLE,
                required=False, style=page))
            _applied(report, slide, "page-number")
    except Exception as error:
        _fail(report, slide, name, error)


def _try_numeral(slide, occupied, theme, section_no: int, width: float,
                 height: float, report: ChromeReport) -> None:
    """Oversized soft numeral above a section divider title."""
    name = "numeral"
    try:
        title = next((obj for obj in slide.objects if _region_of(obj) == "section_title"), None)
        if title is None:
            return
        font_pt = theme.chrome.section_numeral_pt
        numeral_h = font_pt * 1.22 / 72.0 + 0.22  # line height + frame insets + slack
        top = title.box.y - numeral_h - _CLEARANCE
        if top < _EDGE_CLEARANCE + 0.3:
            return _skip(report, slide, name, "no room above the section title")
        numeral = Box(x=title.box.x, y=top, w=min(2.6, title.box.w), h=numeral_h)
        if not _fits_slide(numeral, width, height):
            return _skip(report, slide, name, "would leave the slide bounds")
        if any(_intersects(numeral, box) and box is not title.box for box in occupied):
            return _skip(report, slide, name, "would overlap content")
        style = {"color": theme.surface_raised, "font_size": font_pt,
                 "bold": True, "align": "left"}
        if theme.heading_font:
            style["font_name"] = theme.heading_font
        slide.objects.append(SceneObject(
            object_id=f"{slide.slide_id}//decor-numeral", kind="text_group",
            box=numeral, content={"text": f"{section_no:02d}"},
            role=DISPLAY_TEXT_ROLE, required=False, style=style))
        occupied.append(numeral)
        _applied(report, slide, name)
    except Exception as error:
        _fail(report, slide, name, error)


def _try_quote_mark(slide, occupied, theme, width: float, height: float,
                    report: ChromeReport) -> None:
    """Oversized opening quotation mark over an expanded quote object.

    Preferred placement floats the mark above the quote surface. The dynamic
    layout solver tends to center single-object slides vertically, which
    leaves no room above, so a fallback places the mark in the side margin
    next to the quote text instead - the classic editorial pull-quote
    treatment. Both placements are guarded; a slide where neither fits keeps
    its undecorated quote.
    """
    name = "quote-mark"
    try:
        anchor = next((obj for obj in slide.objects
                       if obj.object_id.endswith("/quote-bg")
                       or (obj.kind == "text_group" and obj.object_id.endswith("/quote-text"))), None)
        if anchor is None:
            return
        font_pt = theme.chrome.quote_mark_pt
        mark_h = font_pt * 1.22 / 72.0 + 0.22
        mark_w = 1.1
        mark = _quote_mark_above(anchor, mark_w, mark_h)
        if mark is not None and _fits_slide(mark, width, height) and not any(
                _intersects(mark, box) and box is not anchor.box for box in occupied):
            _append_quote_mark(slide, mark, theme, font_pt, occupied, report)
            return
        # Fallback: the side margin beside the quote text, top-aligned with it.
        mark = _quote_mark_beside(anchor, mark_w, mark_h)
        if mark is None:
            return _skip(report, slide, name, "no room around the quote")
        if not _fits_slide(mark, width, height):
            return _skip(report, slide, name, "would leave the slide bounds")
        if any(_intersects(mark, box) and box is not anchor.box for box in occupied):
            return _skip(report, slide, name, "would overlap content")
        _append_quote_mark(slide, mark, theme, font_pt, occupied, report)
    except Exception as error:
        _fail(report, slide, name, error)


def _quote_mark_above(anchor, mark_w: float, mark_h: float) -> Box | None:
    top = anchor.box.y - mark_h - _EDGE_CLEARANCE
    if top < _EDGE_CLEARANCE + 0.25:
        return None
    return Box(x=anchor.box.x + 0.02, y=top, w=mark_w, h=mark_h)


def _quote_mark_beside(anchor, mark_w: float, mark_h: float) -> Box | None:
    """Opening mark in the margin left of the quote surface, top-aligned with it.

    Single-quote slides are centered by the solver, so the side margin is
    normally the widest free area on the slide."""
    if anchor.box.x - mark_w - _CLEARANCE < _EDGE_CLEARANCE:
        return None
    return Box(x=anchor.box.x - mark_w - _CLEARANCE, y=anchor.box.y, w=mark_w, h=mark_h)


def _append_quote_mark(slide, mark: Box, theme, font_pt: float,
                       occupied: list, report: ChromeReport) -> None:
    style = {"color": theme.accent, "font_size": font_pt, "bold": True,
             "align": "left"}
    if theme.heading_font:
        style["font_name"] = theme.heading_font
    slide.objects.append(SceneObject(
        object_id=f"{slide.slide_id}//decor-quote-mark", kind="text_group",
        box=mark, content={"text": "\u201c"}, role=DISPLAY_TEXT_ROLE,
        required=False, style=style))
    occupied.append(mark)
    _applied(report, slide, "quote-mark")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _shape(object_id: str, box: Box, color: str) -> SceneObject:
    return SceneObject(object_id=object_id, kind="shape", box=box,
                       content={"shape_type": "rect"}, role=SHAPE_ROLE,
                       required=False,
                       style={"fill": color, "line_color": color, "line_width": 0.25})


def _region_of(obj: SceneObject) -> str:
    return obj.object_id.rsplit("/", 1)[-1]


def _is_titleish(slide, kinds: set[str]) -> bool:
    if kinds & {"table", "chart", "image", "formula", "diagram"}:
        return False
    if len(slide.objects) > 6:
        return False
    return all(_region_of(obj) in _TITLEISH_REGIONS for obj in slide.objects)


def _intersects(a: Box, b: Box, clearance: float = _CLEARANCE) -> bool:
    return (a.x < b.x + b.w + clearance and b.x < a.x + a.w + clearance
            and a.y < b.y + b.h + clearance and b.y < a.y + a.h + clearance)


def _fits_slide(box: Box, width: float, height: float) -> bool:
    return (box.x >= _EDGE_CLEARANCE and box.y >= _EDGE_CLEARANCE
            and box.x + box.w <= width - _EDGE_CLEARANCE
            and box.y + box.h <= height - _EDGE_CLEARANCE)


def _applied(report: ChromeReport, slide, name: str) -> None:
    report.applied.setdefault(slide.slide_id, []).append(name)


def _skip(report: ChromeReport, slide, name: str, reason: str) -> None:
    report.skipped.setdefault(slide.slide_id, []).append(f"{name}: {reason}")


def _fail(report: ChromeReport, slide, name: str, error: Exception) -> None:
    report.failures.append(f"{slide.slide_id}/{name}: "
                           f"{type(error).__name__}: {error}")
