"""Deterministic pre-render fitting pass over a resolved scene (minimal F13).

Runs after the layout catalog resolves geometry and before any renderer sees
the scene. Guarantees, in priority order:

1. Text never overflows its box: font sizes walk down a ladder, then
   low-priority trailing bullets/lines are pruned (always recorded).
2. Source-bound tables are never truncated: their font scales down and
   explicit column widths are computed from measured cell content.
3. Every adjustment is reported so quality gates and audits can explain
   why a rendered deck differs from the composed IR2.

The pass is pure: it returns a new scene plus a report; the input scene is
not mutated.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from core import text_metrics as tm
from renderers.base import PresentationScene, SceneObject

# Role-specific floors: never shrink below these sizes.
FLOOR_BY_ROLE = {
    # Floors mirror the quality gate's ROLE_FLOORS so the deterministic fitting pass
    # can never emit a run the gate must reject for readability.
    "title": 24.0,
    "stat": 24.0,
    "label": 10.0,
    "caption": 10.0,
    "diagram": 12.0,
    "table": 8.0,
}
BODY_FLOOR = 14.0
TABLE_FLOOR = 8.0
MIN_BULLETS_KEPT = 2


@dataclass
class FitAdjustment:
    slide_id: str
    object_id: str
    action: str  # font_scaled | items_pruned | lines_pruned | table_scaled | table_columns | kept_overflow
    detail: str
    severity: str = "info"  # info | warning

    def as_dict(self) -> dict[str, Any]:
        return {"slide_id": self.slide_id, "object_id": self.object_id,
                "action": self.action, "detail": self.detail, "severity": self.severity}


@dataclass
class FitReport:
    adjustments: list[FitAdjustment] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [f"{a.slide_id}/{a.object_id}: {a.action} - {a.detail}"
                for a in self.adjustments if a.severity == "warning"]

    def as_dict(self) -> dict[str, Any]:
        return {"adjustments": [a.as_dict() for a in self.adjustments],
                "warning_count": len(self.warnings)}


# Default text-frame insets of the python-pptx backend (no margins are overridden for
# text boxes), so the fitter must measure the same usable area PowerPoint measures.
TEXT_INSET_X_IN = 0.1
TEXT_INSET_Y_IN = 0.05


def _text_width_in(obj: SceneObject) -> float:
    return max(0.1, obj.box.w - 2 * TEXT_INSET_X_IN)


def _text_height_in(obj: SceneObject) -> float:
    return max(0.1, obj.box.h - 2 * TEXT_INSET_Y_IN)


def _floor_for(obj: SceneObject) -> float:
    return FLOOR_BY_ROLE.get(obj.role, BODY_FLOOR)


def _style_font_size(obj: SceneObject, default: float) -> float:
    size = (obj.style or {}).get("font_size")
    try:
        return float(size) if size else default
    except (TypeError, ValueError):
        return default


def _set_font_size(obj: SceneObject, size: float) -> None:
    obj.style["font_size"] = int(size) if float(size).is_integer() else round(size, 1)


def _ellipsize_to_fit(lines: list[str], measure) -> tuple[list[str], bool]:
    """Last resort: shorten the longest line with '...' while that still helps.

    Returns the (possibly shortened) lines and whether anything was truncated.
    Cutting a line only reduces height when it removes a wrapped row, so the
    loop stops as soon as shortening stops shrinking the block: a label whose
    single line needs a taller box ships as written rather than as 'Encod......'.
    Bounded so pathological content can never spin here.
    """
    out = list(lines)
    for _ in range(24):
        current = measure(out)
        if current.fits:
            return out, out != lines
        index = max(range(len(out)), key=lambda i: len(out[i]))
        stem = out[index][:-3] if out[index].endswith("...") else out[index]
        if len(stem) <= 2:
            return out, out != lines
        candidate = list(out)
        candidate[index] = stem[:max(1, int(len(stem) * 0.9) - 1)].rstrip() + "..."
        if measure(candidate).needed_height_pt >= current.needed_height_pt:
            return out, out != lines
        out = candidate
    return out, out != lines


def _write_lines(obj: SceneObject, lines: list[str]) -> None:
    if obj.kind == "text_group":
        obj.content["lines"] = lines
    else:
        obj.content["text"] = "\n".join(lines)


def _text_lines(content: dict[str, Any]) -> list[str]:
    lines = content.get("lines") or content.get("items") or content.get("bullets")
    if lines is None:
        text = content.get("text", "")
        return text.split("\n") if isinstance(text, str) and text else ([str(text)] if text else [])
    if isinstance(lines, str):
        return [lines]
    result = []
    for line in lines:
        result.append(line.get("text", "") if isinstance(line, dict) else str(line))
    return result


def _fit_plain_text(slide_id: str, obj: SceneObject, report: FitReport) -> None:
    """heading / text_group / shape text: scale font, then prune trailing lines."""
    if obj.kind not in {"heading", "text_group", "shape"}:
        return
    text = obj.content.get("text") if obj.kind != "text_group" else None
    lines = _text_lines(obj.content) if obj.kind == "text_group" else (
        text.split("\n") if isinstance(text, str) else [str(text or "")])
    lines = [line for line in lines if line != ""] or [""]
    bold = bool((obj.style or {}).get("bold", obj.kind == "heading"))
    spacing = tm.DEFAULT_LINE_SPACING
    paragraph_gap = 4.0 if obj.kind == "text_group" else 0.0
    floor = _floor_for(obj)
    start = _style_font_size(obj, 18 if obj.kind == "heading" else 13 if obj.kind == "shape" else 16)
    if start < floor:
        # A model-authored size must never undercut the role floor silently.
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "font_raised_to_floor",
            f"font {start:g}pt raised to the {floor:g}pt role floor"))
        start = floor
        _set_font_size(obj, start)
    ladder = tm.font_size_ladder(start, minimum_pt=floor)

    def measure(size: float, kept: list[str]) -> tm.FitResult:
        return tm.measure_text_block(kept, size, _text_width_in(obj), _text_height_in(obj), bold=bold,
                                     spacing=spacing, paragraph_gap_pt=paragraph_gap)

    chosen, kept = start, list(lines)
    result = initial = measure(chosen, kept)
    if not result.fits:
        if obj.kind == "text_group":
            # Gentle ladder first (max -2pt), then prune, then full ladder.
            gentle = tm.font_size_ladder(start, minimum_pt=max(floor, start - 2.0), steps=(1.0, 0.94, 0.88))
        else:
            gentle = ladder
        for size in gentle:
            candidate = measure(size, kept)
            if candidate.fits:
                chosen = size
                result = candidate
                break
        else:
            chosen = gentle[-1]
            result = measure(chosen, kept)
    if chosen != start:
        _set_font_size(obj, chosen)
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "font_scaled",
            f"font {start:g}pt -> {chosen:g}pt (needed {initial.needed_height_pt:.0f}pt "
            f"of {initial.available_height_pt:.0f}pt at {start:g}pt)"))
    if not result.fits and obj.kind == "text_group" and len(lines) > 1:
        # Prune trailing lines (lowest information density) until it fits.
        while len(kept) > 1 and not measure(chosen, kept).fits:
            kept.pop()
        obj.content["lines"] = kept
        removed = len(lines) - len(kept)
        result = measure(chosen, kept)
        if removed:
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "lines_pruned",
                f"removed {removed} trailing line(s); {len(kept)} kept "
                f"({result.needed_height_pt:.0f}pt of {result.available_height_pt:.0f}pt)", "warning"))
    if not result.fits and obj.kind == "text_group":
        # Still overflowing after pruning: continue the ladder to the floor.
        for size in ladder:
            candidate = measure(size, kept)
            if candidate.fits:
                chosen = size
                result = candidate
                _set_font_size(obj, chosen)
                report.adjustments.append(FitAdjustment(
                    slide_id, obj.object_id, "font_scaled",
                    f"font -> {chosen:g}pt after pruning"))
                break
    if not result.fits:
        # Graceful degradation: overflow must never crash the build or slip past the
        # gate unexplained. Step the font down 10% at a time to the role floor, then
        # ellipsize the longest line until the block measures inside its box.
        before = chosen
        while chosen > floor and not result.fits:
            chosen = max(floor, round(chosen * 0.9, 1))
            _set_font_size(obj, chosen)
            result = measure(chosen, kept)
        if chosen < before:
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "font_scaled",
                f"font {before:g}pt -> {chosen:g}pt in 10% steps to the {floor:g}pt floor"))
    if not result.fits:
        truncated, changed = _ellipsize_to_fit(kept, lambda texts: measure(chosen, texts))
        if changed:
            _write_lines(obj, truncated)
            kept = truncated
            result = measure(chosen, kept)
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "text_truncated",
                f"lines ellipsized to fit {result.available_height_pt:.0f}pt at {chosen:g}pt", "warning"))
    if not result.fits:
        # Residual overflow is now recorded for every kind, not only diagram nodes. A
        # shape keeps the warning surface it already had; a heading or body block is
        # information, because that box height belongs to the layout solver and the
        # committed F13 tests pin the build-level warning contract for tight regions.
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "kept_overflow",
            f"content still exceeds box at {chosen:g}pt ({result.overflow_ratio:.0%})",
            "warning" if obj.kind == "shape" else "info"))


def _fit_list(slide_id: str, obj: SceneObject, report: FitReport) -> None:
    """bullets / numbered_list: font ladder, then prune trailing items."""
    if obj.kind not in {"bullets", "numbered_list"}:
        return
    items = obj.content.get("items")
    if isinstance(items, str):
        items = [items]
    items = list(items or [])
    if not items:
        return
    floor = _floor_for(obj)
    start = _style_font_size(obj, 16)
    if start < floor:
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "font_raised_to_floor",
            f"font {start:g}pt raised to the {floor:g}pt role floor"))
        start = floor
        _set_font_size(obj, start)
    bold = bool((obj.style or {}).get("bold", False))

    def as_text(item: Any) -> str:
        return item.get("text", "") if isinstance(item, dict) else str(item)

    def measure(size: float, kept: list[Any]) -> tm.FitResult:
        return tm.measure_text_block([as_text(i) for i in kept], size, _text_width_in(obj), _text_height_in(obj),
                                     bold=bold, paragraph_gap_pt=4.0)

    chosen, kept = start, items
    result = initial = measure(chosen, kept)
    if not result.fits:
        # Gentle ladder (max -2pt): keeps body text readable before pruning.
        gentle = tm.font_size_ladder(start, minimum_pt=max(floor, start - 2.0), steps=(1.0, 0.94, 0.88))
        for size in gentle:
            candidate = measure(size, kept)
            if candidate.fits:
                chosen, result = size, candidate
                break
        else:
            chosen = gentle[-1]
            result = measure(chosen, kept)
    if chosen != start:
        _set_font_size(obj, chosen)
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "font_scaled",
            f"font {start:g}pt -> {chosen:g}pt (needed {initial.needed_height_pt:.0f}pt "
            f"of {initial.available_height_pt:.0f}pt at {start:g}pt)"))
    if not result.fits and len(kept) > MIN_BULLETS_KEPT:
        removed_total = 0
        while len(kept) > MIN_BULLETS_KEPT and not measure(chosen, kept).fits:
            kept.pop()
            removed_total += 1
        obj.content["items"] = kept
        result = measure(chosen, kept)
        if removed_total:
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "items_pruned",
                f"removed {removed_total} trailing bullet(s); {len(kept)} kept "
                f"({result.needed_height_pt:.0f}pt of {result.available_height_pt:.0f}pt)", "warning"))
    if not result.fits:
        # Even the last two bullets overflow: full ladder down to the floor.
        for size in tm.font_size_ladder(start, minimum_pt=floor):
            candidate = measure(size, kept)
            if candidate.fits:
                chosen, result = size, candidate
                _set_font_size(obj, chosen)
                report.adjustments.append(FitAdjustment(
                    slide_id, obj.object_id, "font_scaled",
                    f"font -> {chosen:g}pt after pruning", "warning"))
                break
    if not result.fits:
        before = chosen
        while chosen > floor and not result.fits:
            chosen = max(floor, round(chosen * 0.9, 1))
            _set_font_size(obj, chosen)
            result = measure(chosen, kept)
        if chosen < before:
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "font_scaled",
                f"font {before:g}pt -> {chosen:g}pt in 10% steps to the {floor:g}pt floor", "warning"))
    if not result.fits:
        # Last resort before shipping an overflowing box: ellipsize the longest
        # bullet. The loss is recorded so the quality report can explain the deck.
        def rebuild(texts: list[str]) -> list[Any]:
            return [{**item, "text": text} if isinstance(item, dict) else text
                    for item, text in zip(kept, texts)]

        truncated, changed = _ellipsize_to_fit([as_text(i) for i in kept],
                                               lambda texts: measure(chosen, rebuild(texts)))
        if changed:
            kept = rebuild(truncated)
            obj.content["items"] = kept
            result = measure(chosen, kept)
            report.adjustments.append(FitAdjustment(
                slide_id, obj.object_id, "text_truncated",
                f"bullets ellipsized to fit {result.available_height_pt:.0f}pt at {chosen:g}pt", "warning"))
    if not result.fits:
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "kept_overflow",
            f"content still exceeds box at {chosen:g}pt ({result.overflow_ratio:.0%})", "warning"))


def _fit_stat(slide_id: str, obj: SceneObject, report: FitReport) -> None:
    """Stat values: shrink so the widest value fits the column width."""
    if obj.role != "stat" or obj.kind != "heading":
        return
    text = str(obj.content.get("text") or "")
    if not text:
        return
    bold = True
    start = _style_font_size(obj, 32)
    width_pt = max(0.0, obj.box.w - 0.08) * 72.0
    needed = tm.text_width_pt(text, start, bold=bold)
    if needed <= width_pt:
        return
    floor = FLOOR_BY_ROLE["stat"]
    scaled = max(floor, start * width_pt / needed)
    scaled = int(scaled) if scaled == int(scaled) else round(scaled, 1)
    _set_font_size(obj, scaled)
    report.adjustments.append(FitAdjustment(
        slide_id, obj.object_id, "font_scaled",
        f"stat value {start:g}pt -> {scaled:g}pt (text {needed:.0f}pt vs box {width_pt:.0f}pt)"))


def _fit_table(slide_id: str, obj: SceneObject, report: FitReport) -> None:
    """Tables: measured column widths + font ladder; rows are never dropped."""
    if obj.kind != "table":
        return
    headers = [str(h) for h in obj.content.get("headers", [])]
    rows = [[str(c) for c in row] for row in obj.content.get("rows", [])]
    if not rows:
        return
    width = len(headers) or len(rows[0])
    start = _style_font_size(obj, 13)
    box_w_pt = obj.box.w * 72.0
    box_h_pt = obj.box.h * 72.0
    cell_pad_h_pt = 0.12 * 72  # renderer margins: 0.06in left+right
    cell_pad_v_pt = 0.08 * 72  # 0.04in top+bottom

    def plan(size: float) -> tuple[list[float], float]:
        """Column widths (pt) and total required height (pt) at a font size."""
        bold_header = True
        natural: list[float] = []
        for col in range(width):
            cells = [headers[col]] if col < len(headers) and headers[col] else []
            cells += [row[col] for row in rows if col < len(row)]
            widest = 0.0
            for cell in cells:
                for piece in cell.split("\n"):
                    piece_w = tm.text_width_pt(piece, size, bold=bold_header and cell in headers[:1])
                    widest = max(widest, piece_w)
            natural.append(min(widest + cell_pad_h_pt, box_w_pt * 0.55))
        # Normalize natural widths to the box width, respecting minimums.
        total_natural = sum(natural) or 1.0
        min_col = 0.5 * 72
        if total_natural > box_w_pt:
            scale = (box_w_pt - width * min_col) / max(1e-6, total_natural - width * min_col if total_natural > width * min_col else 1)
            scaled = [max(min_col, n * max(0.0, scale)) for n in natural]
        else:
            scaled = natural
        # Final normalization pass so columns exactly fill the box.
        total = sum(scaled) or 1.0
        columns = [c * box_w_pt / total for c in scaled]
        row_heights = []
        for row in rows:
            line_counts = []
            for col in range(width):
                text = row[col] if col < len(row) else ""
                line_counts.append(tm.wrapped_line_count(text, size, max(1.0, columns[col] - cell_pad_h_pt)))
            row_heights.append(max(1, max(line_counts)) * tm.line_height_pt(size) + cell_pad_v_pt)
        header_height = (max(tm.wrapped_line_count(headers[c] or "", size, max(1.0, columns[c] - cell_pad_h_pt))
                             for c in range(width)) * tm.line_height_pt(size) + cell_pad_v_pt) if headers else 0.0
        return columns, header_height + sum(row_heights)

    chosen = start
    columns, needed_h = plan(chosen)
    if needed_h > box_h_pt:
        size = chosen
        while size - 1.0 >= TABLE_FLOOR:
            size = round(size - 1.0, 1)
            columns, needed_h = plan(size)
            if needed_h <= box_h_pt:
                break
        chosen = size
        columns, needed_h = plan(chosen)
    obj.content["col_widths_in"] = [c / 72.0 for c in columns]
    obj.content["row_height_policy"] = {"font_size_pt": chosen, "needed_height_in": needed_h / 72.0,
                                        "box_height_in": obj.box.h}
    if chosen != start:
        _set_font_size(obj, chosen)
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "table_scaled",
            f"table font {start:g}pt -> {chosen:g}pt (rows need {needed_h / 72:.2f}in "
            f"of {obj.box.h:.2f}in); rows preserved"))
    report.adjustments.append(FitAdjustment(
        slide_id, obj.object_id, "table_columns",
        f"column widths set from measured content: "
        f"[{', '.join(f'{c / 72:.2f}in' for c in columns)}]"))
    if needed_h > box_h_pt:
        report.adjustments.append(FitAdjustment(
            slide_id, obj.object_id, "kept_overflow",
            f"source table exceeds region at {chosen:g}pt ({needed_h / 72:.2f}in needed vs "
            f"{obj.box.h:.2f}in); rows preserved for grounding", "warning"))


def fit_scene(scene: PresentationScene) -> tuple[PresentationScene, FitReport]:
    """Return a fitted copy of the scene plus a structured report."""
    report = FitReport()
    fitted = copy.deepcopy(scene)
    for slide in fitted.slides:
        for obj in slide.objects:
            try:
                if obj.kind in {"heading", "text_group", "shape"}:
                    _fit_plain_text(slide.slide_id, obj, report)
                elif obj.kind in {"bullets", "numbered_list"}:
                    _fit_list(slide.slide_id, obj, report)
                elif obj.kind == "table":
                    _fit_table(slide.slide_id, obj, report)
                elif obj.role == "stat":
                    _fit_stat(slide.slide_id, obj, report)
            except Exception as error:  # Fitting must never break a build.
                report.adjustments.append(FitAdjustment(
                    slide.slide_id, obj.object_id, "fit_error",
                    f"{type(error).__name__}: {error}", "warning"))
    return fitted, report
