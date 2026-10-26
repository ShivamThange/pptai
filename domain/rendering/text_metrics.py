"""Deterministic text measurement for layout fitting (F13).

All sizes are in typographic points (1 pt = 1/72 inch), matching PowerPoint
font sizes. Measurement uses PIL TrueType rasterization at a large reference
size and linear scaling, which is accurate to within a few percent for the
sans-serif families used by the deck themes.

The module is intentionally dependency-light (Pillow only) so the composer,
storyboard planner, and renderer can share one source of truth for capacity.
"""
from __future__ import annotations

import functools
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import ImageFont

# PowerPoint single line spacing is ~1.18-1.25x the font size depending on the
# font's internal metrics. 1.22 is a safe planning value used everywhere here.
DEFAULT_LINE_SPACING = 1.22
# Reference rasterization size (px). Larger = more precise sub-pixel widths.
_REFERENCE_SIZE = 200

_FONT_CANDIDATES = {
    "regular": [
        # Windows (the documented target environment)
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        # Linux
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "bold": [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/chinese/NotoSansSC-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
}


@dataclass(frozen=True)
class MeasuredFont:
    """A loaded font plus the metrics needed to scale measurements."""

    path: str
    reference_size: int
    # Average advance width of a representative character, as a fraction of
    # the reference size. Used for fast capacity estimates.
    average_char_ratio: float
    space_ratio: float

    @property
    def family(self) -> str:
        return Path(self.path).stem


@functools.lru_cache(maxsize=4)
def _load_font(bold: bool) -> MeasuredFont | None:
    candidates = _FONT_CANDIDATES["bold" if bold else "regular"]
    env_override = os.environ.get("PPTAI_METRIC_FONT_BOLD" if bold else "PPTAI_METRIC_FONT")
    if env_override:
        candidates = [env_override, *candidates]
    for candidate in candidates:
        try:
            if not Path(candidate).is_file():
                continue
            font = ImageFont.truetype(candidate, _REFERENCE_SIZE)
            # Measure a mixed sample; digits/letters/punctuation average.
            sample = ("The quick brown fox jumps over 0123456789 "
                      "AEIOU aeiou .,;:()[]%$-+/ average")
            widths = [font.getlength(ch) for ch in sample]
            average = sum(widths) / len(widths)
            space = font.getlength(" ")
            return MeasuredFont(candidate, _REFERENCE_SIZE, average / _REFERENCE_SIZE,
                                space / _REFERENCE_SIZE)
        except Exception:
            continue
    return None


def font_available(bold: bool = False) -> bool:
    return _load_font(bold) is not None


def text_width_pt(text: str, size_pt: float, *, bold: bool = False) -> float:
    """Width of a single-line string in points."""
    if not text:
        return 0.0
    font = _load_font(bold)
    if font is None:
        # Fallback: coarse average (~0.55 em per char for sans-serif text).
        return len(text) * size_pt * (0.58 if bold else 0.54)
    try:
        true_font = ImageFont.truetype(font.path, _REFERENCE_SIZE)
        return true_font.getlength(text) * size_pt / _REFERENCE_SIZE
    except Exception:
        return len(text) * size_pt * 0.54


def average_char_width_pt(size_pt: float, *, bold: bool = False) -> float:
    font = _load_font(bold)
    ratio = font.average_char_ratio if font else (0.58 if bold else 0.54)
    return ratio * size_pt


def line_height_pt(size_pt: float, spacing: float = DEFAULT_LINE_SPACING) -> float:
    return size_pt * spacing


@functools.lru_cache(maxsize=4096)
def _wrap_cached(text: str, size_pt: float, max_width_pt: float, bold: bool) -> tuple[str, ...]:
    return tuple(wrap_text(text, size_pt, max_width_pt, bold=bold))


def wrap_text(text: str, size_pt: float, max_width_pt: float, *, bold: bool = False) -> list[str]:
    """Greedy word wrap. Honors explicit newlines; never returns empty for non-empty input."""
    if max_width_pt <= 0:
        return [text] if text else []
    output: list[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split()
        if not words:
            output.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if text_width_pt(candidate, size_pt, bold=bold) <= max_width_pt:
                current = candidate
            else:
                output.append(current)
                current = word
        output.append(current)
    return output


def wrapped_line_count(text: str, size_pt: float, max_width_pt: float, *, bold: bool = False) -> int:
    if not text:
        return 0
    return len(_wrap_cached(text, size_pt, max_width_pt, bold))


@dataclass(frozen=True)
class Capacity:
    """How much content a box can hold at a given font size."""

    width_pt: float
    height_pt: float
    font_size_pt: float
    max_lines: int
    chars_per_line: int

    @property
    def max_chars(self) -> int:
        return self.max_lines * self.chars_per_line


def capacity_for(box_w_in: float, box_h_in: float, font_size_pt: float, *,
                 bold: bool = False, spacing: float = DEFAULT_LINE_SPACING,
                 horizontal_padding_in: float = 0.1) -> Capacity:
    """Compute line/character capacity of a region box at a font size.

    horizontal_padding_in approximates text-frame internal margins
    (0.05in each side by default in the renderer); tables pass their own.
    """
    width_pt = max(0.0, box_w_in - horizontal_padding_in) * 72.0
    height_pt = max(0.0, box_h_in) * 72.0
    char_width = max(0.1, average_char_width_pt(font_size_pt, bold=bold))
    chars_per_line = max(1, int(width_pt / char_width))
    line_height = line_height_pt(font_size_pt, spacing)
    max_lines = max(0, int(height_pt / line_height)) if line_height > 0 else 0
    return Capacity(width_pt, height_pt, font_size_pt, max_lines, chars_per_line)


@dataclass(frozen=True)
class FitResult:
    fits: bool
    needed_height_pt: float
    available_height_pt: float
    line_count: int

    @property
    def overflow_ratio(self) -> float:
        if self.available_height_pt <= 0:
            return float("inf")
        return self.needed_height_pt / self.available_height_pt


def measure_text_block(lines: Iterable[str], size_pt: float, box_w_in: float, box_h_in: float, *,
                       bold: bool = False, spacing: float = DEFAULT_LINE_SPACING,
                       paragraph_gap_pt: float = 0.0,
                       horizontal_padding_in: float = 0.1) -> FitResult:
    """Measure wrapped height of a sequence of text lines/paragraphs."""
    width_pt = max(0.0, box_w_in - horizontal_padding_in) * 72.0
    available = max(0.0, box_h_in) * 72.0
    total = 0.0
    count = 0
    for index, line in enumerate(lines):
        wrapped = wrap_text(str(line), size_pt, width_pt, bold=bold)
        count += len(wrapped)
        total += len(wrapped) * line_height_pt(size_pt, spacing)
        if index:
            total += paragraph_gap_pt
    return FitResult(total <= available + 0.5, total, available, count)


def font_size_ladder(start_pt: float, minimum_pt: float = 10.0,
                     steps: Sequence[float] = (1.0, 0.94, 0.88, 0.82, 0.76, 0.7, 0.64)) -> list[float]:
    """Descending candidate font sizes, rounded to whole/half points."""
    result: list[float] = []
    for factor in steps:
        size = round(start_pt * factor * 2) / 2
        if size >= minimum_pt and (not result or size < result[-1]):
            result.append(size)
    if not result:
        result.append(max(minimum_pt, round(start_pt * 0.64)))
    return result
