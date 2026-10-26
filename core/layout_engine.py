"""Deterministic dynamic layout solver (F13: dynamic geometry and layouts).

Resolves presentation geometry AFTER content planning, per the module spec:
the composer still picks a catalog layout and fills its regions; this engine
re-solves concrete boxes for the regions that were actually filled, using
measured text/table/media requirements instead of fixed catalog fractions.

Design invariants:
- Pure: returns per-slide region definitions (catalog-compatible dicts); the
  IR2 content, grounding and evidence hashes are never touched.
- Bounded candidates: a small fixed set of archetypes (single, split, stack,
  cards, bento variants) is enumerated and scored; no random coordinates and
  no unbounded search.
- Feasibility-first: candidates are ranked only when every region fits its
  box at a font size at or above the role floor; otherwise the candidate is
  rejected. Font floors are never broken silently - tight/floor outcomes are
  recorded in the report.
- Fallback: any per-slide failure returns no override and the proven catalog
  geometry is used unchanged, so a solver defect cannot break a build.
- Variety: consecutive slides are nudged toward different archetypes so the
  same content plan yields varied but coherent compositions.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core import text_metrics as tm

# Role floors (comfort / tight). The renderer's fitting pass (renderers/fitting)
# remains the hard guarantee; these floors steer candidate selection only.
TITLE_FLOOR = 18.0
BODY_COMFORT = 11.0
BODY_TIGHT = 9.5
TABLE_COMFORT = 10.0
TABLE_TIGHT = 8.0
MIN_MEDIA_CELL = 2.3   # inches; image label legibility
MIN_STAT_CELL = (1.6, 1.05)
MIN_STRUCT_CELL = (2.6, 1.8)

# Frame constants (inches on a 13.333 x 7.5 canvas; scales with slide dims).
MARGIN_X = 0.62
MARGIN_TOP = 0.42
MARGIN_BOTTOM = 0.40
GAP = 0.24
SUBTITLE_H = 0.5
FOOTER_H = 0.46

_TITLE_NAMES = {"title", "header", "section_title", "overlay_title"}
_SUBTITLE_NAMES = {"subtitle", "section_subtitle"}
_FOOTER_HINTS = ("footer", "footnote", "source", "contact", "attribution")
_VISUAL_OBJECTS = {"card", "metric_card", "callout", "quote", "chips", "compare"}

# Structural classes get priority when claiming the dominant cell.
_CLASS_PRIORITY = {"table": 0, "chart": 1, "media": 2, "diagram": 3, "stat": 4,
                   "text": 5, "quote": 5}


@dataclass
class Unit:
    """One filled IR2 region prepared for layout solving."""

    name: str
    kind: str
    payload: dict[str, Any]
    region_def: dict[str, Any]
    cls: str
    aspect: float | None = None

    @property
    def priority(self) -> int:
        return _CLASS_PRIORITY.get(self.cls, 5)

    @property
    def font(self) -> float:
        style = self.region_def.get("default_style") or {}
        try:
            return float(style.get("font_size") or _default_font(self.cls))
        except (TypeError, ValueError):
            return _default_font(self.cls)

    @property
    def bold(self) -> bool:
        return bool((self.region_def.get("default_style") or {}).get("bold", self.cls == "quote"))


def _default_font(cls: str) -> float:
    return {"title": 30.0, "subtitle": 16.0, "quote": 20.0, "stat": 20.0,
            "table": 12.0, "diagram": 13.0}.get(cls, 16.0)


@dataclass
class Candidate:
    archetype: str
    boxes: dict[str, tuple[float, float, float, float]]
    fit: dict[str, dict[str, Any]] = field(default_factory=dict)
    feasible: bool = True
    tight: bool = False
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0

    def as_report(self) -> dict[str, Any]:
        return {"archetype": self.archetype, "feasible": self.feasible, "tight": self.tight,
                "score": round(self.score, 3), "reasons": self.reasons}


def _classify(name: str, kind: str) -> str:
    lowered = (name or "").lower()
    if lowered in _TITLE_NAMES or (kind == "heading" and "title" in lowered):
        return "title"
    if lowered in _SUBTITLE_NAMES:
        return "subtitle"
    if any(hint in lowered for hint in _FOOTER_HINTS):
        return "footer"
    if kind in {"image", "formula"}:
        return "media"
    if kind == "table":
        return "table"
    if kind == "chart":
        return "chart"
    if kind == "diagram":
        return "diagram"
    if kind == "stat":
        return "stat"
    if kind == "metric_card":
        return "stat"
    if kind in {"card", "callout", "quote", "chips", "compare"}:
        return "text"
    if "quote" in lowered:
        return "quote"
    return "text"


def _visual_object_lines(payload: dict[str, Any]) -> list[str]:
    """Visible text lines of a predefined visual object, for capacity solving."""
    kind = payload.get("type")
    lines: list[str] = []
    if kind == "card":
        lines.extend(str(value) for value in (payload.get("title"), payload.get("text")) if value)
        metric = payload.get("metric") or {}
        lines.extend(str(value) for value in (metric.get("value"), metric.get("label"), metric.get("context")) if value)
    elif kind == "metric_card":
        lines.extend(str(value) for value in (payload.get("value"), payload.get("label"),
                                              payload.get("trend"), payload.get("context")) if value)
    elif kind == "callout":
        lines.extend(str(value) for value in (payload.get("title"), payload.get("text")) if value)
    elif kind == "quote":
        lines.extend(str(value) for value in (payload.get("text"), payload.get("attribution")) if value)
    elif kind == "chips":
        lines.extend(str(item) for item in payload.get("labels") or [])
    elif kind == "compare":
        for side in (payload.get("left") or {}, payload.get("right") or {}):
            lines.append(str(side.get("heading", "")))
            lines.extend(str(item) for item in side.get("items") or [])
    return [line for line in lines if line.strip()]


def _text_lines(payload: dict[str, Any]) -> list[str]:
    object_lines = _visual_object_lines(payload)
    if object_lines:
        return object_lines
    lines = payload.get("lines") or payload.get("items") or payload.get("bullets")
    if lines is None:
        text = payload.get("text", "")
        return text.split("\n") if isinstance(text, str) and text else ([str(text)] if text else [])
    if isinstance(lines, str):
        return [lines]
    return [item.get("text", "") if isinstance(item, dict) else str(item) for item in lines]


def _needed_text_height_in(lines: list[str], font_pt: float, width_in: float, *, bold: bool,
                           paragraph_gap_pt: float = 4.0) -> float:
    result = tm.measure_text_block(lines, font_pt, width_in, 100.0, bold=bold,
                                   paragraph_gap_pt=paragraph_gap_pt)
    return result.needed_height_pt / 72.0


def _table_shape(payload: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    headers = [str(h) for h in payload.get("headers", [])]
    rows = [[str(c) for c in row] for row in payload.get("rows", [])]
    return headers, rows


def _table_needed_height_in(payload: dict[str, Any], width_in: float, font_pt: float) -> float:
    headers, rows = _table_shape(payload)
    if not rows:
        return 0.6
    n_cols = len(headers) or len(rows[0])
    pad_h, pad_v = 0.12, 0.08
    col_w = max(0.5, (width_in - n_cols * pad_h) / n_cols)
    line_h = tm.line_height_pt(font_pt) / 72.0

    def row_height(cells: list[str]) -> float:
        counts = [tm.wrapped_line_count(cells[c] if c < len(cells) else "", font_pt,
                                        max(36.0, (col_w - pad_h) * 72.0)) for c in range(n_cols)]
        return max(1, max(counts or [1])) * line_h + pad_v

    total = sum(row_height(row) for row in rows)
    if headers:
        total += row_height(headers)
    return total


def _media_aspect(payload: dict[str, Any], search_dirs: list[Path]) -> float | None:
    from renderers.python_primitives import resolve_asset_path
    path = resolve_asset_path(payload.get("source_asset_id"), payload.get("path"), search_dirs)
    if not path:
        return None
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
        return (width / height) if height else None
    except Exception:
        return None


class DynamicLayoutEngine:
    """Per-deck dynamic geometry solver over catalog-compatible region defs."""

    engine_id = "f13-dynamic-v1"

    def __init__(self, layouts_spec: dict[str, Any], asset_search_dirs: list[Path] | None = None):
        self.spec = layouts_spec
        dims = layouts_spec.get("slide_dimensions", {})
        self.width_in = float(dims.get("width_inches", 13.333))
        self.height_in = float(dims.get("height_inches", 7.5))
        self.search_dirs = [Path(p) for p in (asset_search_dirs or [])]

    # ------------------------------------------------------------------ deck

    def solve_deck(self, content: dict[str, Any]) -> tuple[dict[int, dict[str, dict]] | None, dict[str, Any]]:
        regions_out: dict[int, dict[str, dict]] = {}
        report: dict[str, Any] = {"engine": self.engine_id, "slides": []}
        previous: list[str] = []
        for index, slide in enumerate(content.get("slides", []), 1):
            slide_report: dict[str, Any] = {"slide": index, "layout": slide.get("layout")}
            try:
                solved, slide_report["detail"] = self._solve_slide(slide, previous)
            except Exception as error:  # A solver defect must never break a build.
                solved, slide_report["detail"] = None, {"fallback_reason": f"{type(error).__name__}: {error}"}
            if solved is not None:
                regions_out[index] = solved
                slide_report["resolved"] = True
            else:
                slide_report["resolved"] = False
            report["slides"].append(slide_report)
            if solved is not None and slide_report.get("detail", {}).get("archetype"):
                previous.append(slide_report["detail"]["archetype"])
                previous = previous[-2:]
        return (regions_out or None), report

    # ----------------------------------------------------------------- slide

    def _solve_slide(self, slide: dict[str, Any], previous: list[str]):
        layout_name = slide.get("layout")
        layout = (self.spec.get("layouts") or {}).get(layout_name)
        if not layout:
            return None, {"fallback_reason": f"unknown layout {layout_name!r}"}
        catalog_regions = layout.get("regions") or {}

        units: list[Unit] = []
        for name, item in (slide.get("content") or {}).items():
            if not isinstance(item, dict):
                continue
            region_def = catalog_regions.get(name)
            if region_def is None:
                return None, {"fallback_reason": f"unknown region {name!r}"}
            kind = item.get("type")
            cls = _classify(name, kind)
            unit = Unit(name=name, kind=kind, payload=item, region_def=region_def, cls=cls)
            if cls == "media":
                unit.aspect = _media_aspect(item, self.search_dirs)
            units.append(unit)

        title_units = [u for u in units if u.cls == "title"]
        subtitle_units = [u for u in units if u.cls == "subtitle"]
        footer_units = [u for u in units if u.cls == "footer"]
        content_units = [u for u in units if u.cls not in {"title", "subtitle", "footer"}]
        if not content_units and not title_units:
            return None, {"fallback_reason": "no placeable regions"}
        # Title band: measure and walk down to fit at most two lines.
        title_h, title_note = 0.0, None
        if title_units:
            unit = title_units[0]
            text = str(unit.payload.get("text") or "")
            width_in = self.width_in - 2 * MARGIN_X
            font = min(unit.font, 34.0)
            lines = tm.wrap_text(text, font, width_in * 72.0 * 0.96, bold=True)
            while len(lines) > 2 and font > TITLE_FLOOR:
                font = max(TITLE_FLOOR, font - 2.0)
                lines = tm.wrap_text(text, font, width_in * 72.0 * 0.96, bold=True)
            if len(lines) > 2:
                return None, {"fallback_reason": "title cannot fit two lines at the floor"}
            title_h = min(1.15, len(lines) * tm.line_height_pt(font) / 72.0 + 0.16)
            title_note = {"font_pt": font, "lines": len(lines)}

        if not content_units:
            # Title-only slide (openers, dividers, closers): optically centered.
            regions: dict[str, dict] = {}
            block_h = title_h + ((SUBTITLE_H + 0.08) if subtitle_units else 0.0)
            top = max(MARGIN_TOP, (self.height_in - block_h) / 2 - 0.1)
            for unit in title_units:
                regions[unit.name] = self._region_def(unit, MARGIN_X, top,
                                                      self.width_in - 2 * MARGIN_X, title_h or 0.6)
            for offset, unit in enumerate(subtitle_units):
                regions[unit.name] = self._region_def(unit, MARGIN_X + 0.1 * self.width_in,
                                                      top + title_h + 0.08, self.width_in - 2 * MARGIN_X - 0.2 * self.width_in,
                                                      SUBTITLE_H)
            for unit in footer_units:
                regions[unit.name] = self._region_def(unit, MARGIN_X, self.height_in - footer_h - 0.06,
                                                      self.width_in - 2 * MARGIN_X, footer_h or FOOTER_H)
            return regions, {"archetype": "title-only", "score": 3.0, "regions":
                             {n: [round(v, 3) for v in (r["left"] * self.width_in, r["top"] * self.height_in,
                                                        r["width"] * self.width_in, r["height"] * self.height_in)]
                              for n, r in regions.items()}, "fit": {}, "tight": False, "alternatives": []}

        frame_top = MARGIN_TOP + (title_h + 0.14 if title_units else 0.12)
        if subtitle_units:
            frame_top += SUBTITLE_H + 0.08
        frame_bottom = self.height_in - MARGIN_BOTTOM
        footer_h = 0.0
        if footer_units:
            footer_h = min(FOOTER_H, max(0.28, MARGIN_BOTTOM - 0.08))
            frame_bottom -= footer_h + 0.10
            if frame_bottom - frame_top < 1.0:
                footer_h = 0.0
                frame_bottom = self.height_in - MARGIN_BOTTOM
        frame_w = self.width_in - 2 * MARGIN_X
        frame_h = frame_bottom - frame_top
        if frame_h < 1.0:
            return None, {"fallback_reason": "no room left for content"}

        candidates = self._candidates(content_units, frame_top, frame_w, frame_h)
        if not candidates:
            return None, {"fallback_reason": "no compatible archetypes"}

        previous_archetypes = set(previous or [])
        best: Candidate | None = None
        for candidate in candidates:
            if not candidate.feasible:
                continue
            score = candidate.score
            archetype = candidate.archetype.rsplit("-", 1)[0] if candidate.archetype.endswith(("_left", "_right")) else candidate.archetype
            if previous and archetype == previous[-1]:
                score -= 0.9 if len(previous) < 2 or previous[0] != archetype else 1.6
            elif len(previous) >= 2 and archetype == previous[0] == previous[1]:
                score -= 0.6
            else:
                score += 0.5  # Variety keeps decks from repeating one composition.
            if best is None or score > best.score:
                best, best.score = candidate, score
        if best is None:
            return None, {"fallback_reason": "no feasible candidate",
                          "candidates": [c.as_report() for c in candidates]}

        regions: dict[str, dict] = {}
        for unit in title_units:
            regions[unit.name] = self._region_def(unit, MARGIN_X, MARGIN_TOP, frame_w, title_h or 0.6)
        for offset, unit in enumerate(subtitle_units):
            top = MARGIN_TOP + title_h + 0.10
            regions[unit.name] = self._region_def(unit, MARGIN_X + 0.4 * frame_w / 2, top,
                                                  0.8 * frame_w, SUBTITLE_H)
        for unit in footer_units:
            regions[unit.name] = self._region_def(unit, MARGIN_X, self.height_in - footer_h - 0.06,
                                                  frame_w, footer_h or FOOTER_H)
        for name, (x, y, w, h) in best.boxes.items():
            unit = next(u for u in content_units if u.name == name)
            regions[name] = self._region_def(unit, x, y, w, h)

        detail = {"archetype": best.archetype, "score": round(best.score, 3),
                  "regions": {n: [round(v, 3) for v in b] for n, b in best.boxes.items()},
                  "fit": best.fit, "tight": best.tight,
                  "alternatives": [c.as_report() for c in candidates if c is not best]}
        if title_note:
            detail["title"] = title_note
        return regions, detail

    def _region_def(self, unit: Unit, x: float, y: float, w: float, h: float) -> dict[str, Any]:
        return {
            "left": round(x / self.width_in, 4), "top": round(y / self.height_in, 4),
            "width": round(w / self.width_in, 4), "height": round(h / self.height_in, 4),
            "allowed_types": list(unit.region_def.get("allowed_types", [])),
            "default_style": copy.deepcopy(unit.region_def.get("default_style") or {}),
        }

    # ------------------------------------------------------------ archetypes

    def _candidates(self, units: list[Unit], top: float, frame_w: float,
                    frame_h: float) -> list[Candidate]:
        candidates: list[Candidate] = []
        frame = (MARGIN_X, top, frame_w, frame_h)
        classes = {u.cls for u in units}
        if not units:
            return candidates
        if len(units) == 1:
            candidates.append(self._single(units[0], frame))
        elif len(units) == 2:
            if "table" in classes:
                candidates.append(self._stack(units, frame))
            if "table" not in classes:
                candidates.append(self._split(units, frame, media_right=True))
                candidates.append(self._split(units, frame, media_right=False))
        else:
            structural = classes & {"table", "chart", "media", "diagram"}
            if structural:
                candidates.extend(self._bento(units, frame))
            else:
                # Offer both a horizontal object row and a vertical stack; the
                # feasibility/score pass decides which one the text can survive.
                candidates.append(self._cards(units, frame, rows=1, columns=min(len(units), 4)))
                if len(units) > 2:
                    candidates.append(self._cards(units, frame, rows=1, columns=1))
                if len(units) == 4:
                    candidates.append(self._cards(units, frame, rows=2))
        return [self._evaluate(c, units) for c in candidates]

    def _single(self, unit: Unit, frame: tuple[float, float, float, float]) -> Candidate:
        x, y, w, h = frame
        if unit.cls == "media" and unit.aspect:
            media_w = min(w, max(2.4, h * unit.aspect))
            media_h = min(h, media_w / unit.aspect)
            box = (x + (w - media_w) / 2, y + (h - media_h) / 2, media_w, media_h)
        elif unit.cls == "table":
            # Source-bound tables carry no inline rows, so their measured need is
            # unknown here (the renderer loads the hashed asset rows later). Give
            # them the full frame instead of the 1.2in floor: a collapsed box made
            # the renderer shrink the source table below the readability floors and
            # then expand past its declared geometry.
            source_bound = bool(unit.payload.get("source_asset_id")) and not (
                unit.payload.get("rows") or unit.payload.get("headers"))
            height = h if source_bound else min(h, max(1.2, _table_needed_height_in(unit.payload, w, unit.font)))
            box = (x, y, w, height)
        elif unit.cls == "text":
            text_w = min(w, 9.8)
            text_h = self._content_height(unit, text_w, h)
            box = (x + (w - text_w) / 2, y, text_w, text_h)
        else:
            box = (x, y, w, h)
        return Candidate("single", {unit.name: box})

    def _split(self, units: list[Unit], frame: tuple[float, float, float, float],
               media_right: bool) -> Candidate:
        x, y, w, h = frame
        media = next((u for u in units if u.cls == "media"), None)
        if media is not None and media.aspect:
            other = next(u for u in units if u is not media)
            media_w = min(w * 0.55, max(3.4, min(h * media.aspect * 1.12, w - 3.6)))
            text_w = w - GAP - media_w
            text_h = self._content_height(other, text_w, h)
            left = (x, y, text_w, text_h)
            right = (x + text_w + GAP, y, media_w, h)
            media_box = self._media_box(media, right)
            boxes = {other.name: left, media.name: media_box}
            archetype = "split-media-" + ("right" if media_right else "left")
            if not media_right:
                boxes = {other.name: right, media.name: self._media_box(media, left)}
            return Candidate(archetype, boxes)
        # Two non-media regions: split by measured need, clamped to sane shares.
        first, second = units
        need_a = self._preference_width(first, w, h)
        need_b = self._preference_width(second, w, h)
        share = 0.5 if abs(need_a - need_b) < 0.8 else min(0.66, max(0.34, need_a / max(0.1, need_a + need_b)))
        if not media_right:
            share = 1.0 - share
        wa = w * share
        wb = w - GAP - wa
        return Candidate("split-pair", {first.name: (x, y, wa, self._content_height(first, wa, h)),
                                        second.name: (x + wa + GAP, y, wb, self._content_height(second, wb, h))})

    def _stack(self, units: list[Unit], frame: tuple[float, float, float, float]) -> Candidate:
        x, y, w, h = frame
        table = next(u for u in units if u.cls == "table")
        other = next(u for u in units if u is not table)
        table_h = min(h * 0.72, max(1.2, _table_needed_height_in(table.payload, w, table.font)))
        rest = h - table_h - GAP
        if rest < 0.9:  # Not enough room below: give the table what remains.
            table_h = h
            return Candidate("table-full", {table.name: (x, y, w, table_h)})
        return Candidate("table-led", {table.name: (x, y, w, table_h),
                                       other.name: (x, y + table_h + GAP, w,
                                                    self._content_height(other, w, rest))})

    def _cards(self, units: list[Unit], frame: tuple[float, float, float, float],
               rows: int, columns: int | None = None) -> Candidate:
        x, y, w, h = frame
        count = len(units)
        if columns is None:
            columns = 1 if rows == 1 else (2 if count <= 4 else 3)
        columns = max(1, min(columns, count))
        if rows == 2:
            columns = 2 if count == 4 else min(3, count)
        row_count = max(1, (count + columns - 1) // columns)
        card_w = (w - (columns - 1) * GAP) / columns
        card_h = (h - (row_count - 1) * GAP) / row_count
        if rows == 1 and row_count == 1:
            # A single object row should not stretch to the full frame: cards with
            # two lines of text in a 6in-tall panel look empty. Cap at measured
            # need (plus padding) and centre the row optically.
            need = max([self._needed_h(unit, card_w) + 0.55 for unit in units] + [1.4])
            card_h = min(card_h, max(1.4, need))
        boxes = {}
        for index, unit in enumerate(sorted(units, key=lambda u: u.name)):
            row, column = divmod(index, columns)
            box = (x + column * (card_w + GAP), y + row * (card_h + GAP), card_w, card_h)
            boxes[unit.name] = self._media_box(unit, box) if unit.cls == "media" else box
        return Candidate(f"cards-{columns}x{row_count}", boxes)

    def _bento(self, units: list[Unit], frame: tuple[float, float, float, float]) -> list[Candidate]:
        x, y, w, h = frame
        ordered = sorted(units, key=lambda u: (u.priority, u.name))
        dominant, rest = ordered[0], ordered[1:]
        candidates: list[Candidate] = []
        if rest:
            same_class = len(rest) >= 2 and len({u.cls for u in rest}) == 1
            if same_class:
                # A homogeneous group (KPI row, card strip) forms one band.
                band = min(h * (0.42 if rest[0].cls == "stat" else 0.55),
                           max(1.05, self._min_row_h(rest)))
                if band >= 1.0 and h - GAP - band >= 1.0:
                    boxes = self._row_boxes(rest, x, y, w, band)
                    boxes[dominant.name] = (x, y + band + GAP, w, h - band - GAP)
                    candidates.append(Candidate("bento-band-top", boxes))
                    boxes = {dominant.name: (x, y, w, h - GAP - band)}
                    boxes.update(self._row_boxes(rest, x, y + h - band, w, band))
                    candidates.append(Candidate("bento-band-bottom", boxes))
            else:
                # Dominant wide on top, remainder in a row below.
                band = min(h * 0.62, max(1.6, h - GAP - self._min_row_h(rest)))
                if band >= 1.2 and h - GAP - band >= 0.9:
                    boxes = {dominant.name: (x, y, w, band)}
                    boxes.update(self._row_boxes(rest, x, y + band + GAP, w, h - band - GAP))
                    candidates.append(Candidate("bento-wide-top", boxes))
                # Remainder in a row on top, dominant wide below.
                band = min(h * 0.62, max(1.6, h - GAP - self._min_row_h(rest)))
                if band >= 1.2 and h - GAP - band >= 0.9:
                    boxes = self._row_boxes(rest, x, y, w, h - GAP - band)
                    boxes[dominant.name] = (x, y + h - band, w, band)
                    candidates.append(Candidate("bento-wide-bottom", boxes))
            # Dominant tall on one side, remainder stacked on the other.
            side_w = min(w * 0.58, max(3.2, w - GAP - 3.0))
            if w - GAP - side_w >= 2.4:
                for archetype, dom_first in (("bento-tall-left", True), ("bento-tall-right", False)):
                    dom_x = x if dom_first else x + w - side_w
                    rest_x = x + side_w + GAP if dom_first else x
                    boxes = {dominant.name: (dom_x, y, side_w, h)}
                    boxes.update(self._stack_boxes(rest, rest_x, y, w - side_w - GAP, h))
                    candidates.append(Candidate(archetype, boxes))
        if len(units) == 4:
            candidates.append(self._cards(units, frame, rows=2))
        return candidates

    def _row_boxes(self, units: list[Unit], x: float, y: float, w: float, h: float) -> dict:
        count = len(units)
        cell_w = (w - (count - 1) * GAP) / count
        boxes = {}
        for index, unit in enumerate(sorted(units, key=lambda u: u.name)):
            box = (x + index * (cell_w + GAP), y, cell_w, h)
            boxes[unit.name] = self._media_box(unit, box) if unit.cls == "media" else box
        return boxes

    def _stack_boxes(self, units: list[Unit], x: float, y: float, w: float, h: float) -> dict:
        count = len(units)
        cell_h = (h - (count - 1) * GAP) / count
        return {unit.name: (x, y + index * (cell_h + GAP), w, cell_h)
                for index, unit in enumerate(sorted(units, key=lambda u: u.name))}

    def _media_box(self, unit: Unit, box: tuple[float, float, float, float]):
        """Aspect-fit a media unit inside its allocated cell, centered."""
        x, y, w, h = box
        if not unit.aspect:
            return box
        fit_w = min(w, h * unit.aspect)
        fit_h = min(h, fit_w / unit.aspect) if unit.aspect else h
        return (x + (w - fit_w) / 2, y + (h - fit_h) / 2, fit_w, fit_h)

    def _min_row_h(self, units: list[Unit]) -> float:
        return max([1.1] + [self._needed_h(u, 4.0) * 0.9 for u in units])

    def _preference_width(self, unit: Unit, w: float, h: float) -> float:
        if unit.cls == "stat":
            return 3.2
        lines = _text_lines(unit.payload) or [""]
        longest = max(tm.text_width_pt(line, unit.font, bold=unit.bold) for line in lines) or 1.0
        return min(w * 0.66, max(2.8, longest / 72.0 + 0.4))

    def _needed_h(self, unit: Unit, width_in: float) -> float:
        if unit.cls == "text" or unit.cls == "quote":
            return _needed_text_height_in(_text_lines(unit.payload) or [""], unit.font,
                                          width_in, bold=unit.bold)
        if unit.cls == "table":
            return _table_needed_height_in(unit.payload, width_in, unit.font)
        return 1.2

    def _content_height(self, unit: Unit, width_in: float, height_in: float) -> float:
        """Cap text/object boxes at the measured need so panels are not stretched.

        A background card or callout is a visible box: filling a 5.9in frame with
        two lines of text reads as an empty panel. Tables/media keep their frame.
        """
        if unit.cls in {"text", "quote"}:
            is_object = unit.payload.get("type") in _VISUAL_OBJECTS
            padding = 0.55 if is_object else 0.2
            return min(height_in, max(1.1 if is_object else 0.9,
                                      self._needed_h(unit, width_in) + padding))
        if unit.cls == "stat":
            return min(height_in, 1.7)
        return height_in

    # ------------------------------------------------------------ evaluation

    def _evaluate(self, candidate: Candidate, units: list[Unit]) -> Candidate:
        fill_scores: list[float] = []
        font_ratios: list[float] = []
        dominant_area = 0.0
        total_area = 0.0
        dominant = min(units, key=lambda u: (u.priority, u.name), default=None)
        for unit in units:
            box = candidate.boxes.get(unit.name)
            if box is None:
                candidate.feasible = False
                candidate.reasons.append(f"{unit.name}: no box")
                continue
            x, y, w, h = box
            if w <= 0.2 or h <= 0.2 or x < -0.01 or y < -0.01 or x + w > self.width_in + 0.01 or y + h > self.height_in + 0.01:
                candidate.feasible = False
                candidate.reasons.append(f"{unit.name}: out of bounds")
                continue
            status, fill, font_ratio = self._evaluate_unit(unit, w, h)
            candidate.fit[unit.name] = {"status": status, "box_inches": [round(v, 2) for v in box]}
            if status == "overflow":
                candidate.feasible = False
                candidate.reasons.append(f"{unit.name}: overflow at floor")
                continue
            if status == "tight":
                candidate.tight = True
            fill_scores.append(max(0.15, min(1.0, fill)))
            if font_ratio is not None:
                font_ratios.append(font_ratio)
            area = w * h
            total_area += area
            if unit is dominant:
                dominant_area = area
        if not candidate.feasible:
            return candidate
        fill = sum(fill_scores) / len(fill_scores)
        fonts = sum(font_ratios) / len(font_ratios) if font_ratios else 1.0
        emphasis = 1.0 if total_area <= 0 else dominant_area / total_area
        score = 2.0 - (0.9 if candidate.tight else 0.0)
        score += 1.2 * fonts
        score += 1.0 * (1.0 - abs(fill - 0.74) / 0.74)  # Reward ~74% average fill.
        if emphasis >= 0.42:
            score += 0.8
        candidate.score = score
        return candidate

    def _evaluate_unit(self, unit: Unit, w: float, h: float) -> tuple[str, float, float | None]:
        if unit.cls in {"text", "quote"}:
            lines = _text_lines(unit.payload) or [""]
            start = unit.font
            floor = BODY_COMFORT if unit.cls == "text" else 14.0
            font, needed = start, _needed_text_height_in(lines, start, w, bold=unit.bold)
            if needed > h:
                for size in tm.font_size_ladder(start, minimum_pt=BODY_TIGHT):
                    needed = _needed_text_height_in(lines, size, w, bold=unit.bold)
                    font = size
                    if needed <= h:
                        break
            if needed > h:
                return "overflow", 1.0, None
            status = "ok" if font >= floor else "tight"
            return status, needed / max(h, 0.01), font / max(start, 0.01)
        if unit.cls == "table":
            start = unit.font
            font, needed = start, _table_needed_height_in(unit.payload, w, start)
            if needed > h:
                size = start
                while size - 1.0 >= TABLE_TIGHT:
                    size = round(size - 1.0, 1)
                    needed = _table_needed_height_in(unit.payload, w, size)
                    if needed <= h:
                        break
                font = size
            if needed > h:
                return "overflow", 1.0, None
            status = "ok" if font >= TABLE_COMFORT else "tight"
            return status, needed / max(h, 0.01), font / max(start, 0.01)
        if unit.cls == "media":
            if min(w, h) < MIN_MEDIA_CELL:
                return "overflow", 1.0, None
            aspect = unit.aspect or 1.33
            return "ok", min(1.0, (w * h) / max(0.01, (h * aspect) * min(w, h)) ), None
        if unit.cls == "stat":
            min_w, min_h = MIN_STAT_CELL
            if w < min_w or h < min_h:
                return "overflow", 1.0, None
            return "ok", 0.8, None
        # chart / diagram
        min_w, min_h = MIN_STRUCT_CELL
        if w < min_w or h < min_h:
            return "overflow", 1.0, None
        if unit.cls == "diagram":
            nodes = len(unit.payload.get("nodes") or unit.payload.get("steps") or [])
            if nodes and (w - (nodes - 1) * 0.2) / nodes < 1.05:
                return "overflow", 1.0, None
        return "ok", 0.85, None
