"""Dynamic theme tokens and application (F13 step 1: theme tokens + primitives).

A theme is a validated JSON file under ``config/themes/``. Application happens
at the IR2 content level: role-based style defaults are injected into each
content region's ``style`` dict without overriding any key the model or layout
catalog already set. Both renderer backends consume object styles, so themed
output needs no backend-specific code paths.

Theme selection is explicit (``--theme corporate_blue``) or resolved from the
presentation lens (``--theme auto``). Unknown names fail loudly.
"""
from __future__ import annotations

import copy
import functools
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

THEMES_DIR = Path(__file__).resolve().parents[2] / "config" / "themes"

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# "auto" resolution per presentation lens.
LENS_THEME_MAP = {
    "academic": "academic_slate",
    "executive": "corporate_blue",
    "pitch": "warm_editorial",
    "technical": "minimal_mono",
}

DEFAULT_BACKGROUND = "#FFFFFF"


class ThemeSpec(BaseModel):
    """Validated theme tokens; every color is a #RRGGBB string."""

    model_config = {"extra": "forbid"}

    id: str
    name: str
    description: str = ""
    background: str
    text: str
    text_muted: str
    accent: str
    accent_soft: str
    connector: str
    table_header_bg: str
    table_row_color: str
    table_band: str
    heading_font: str | None = None
    body_font: str | None = None
    chart_colors: list[str] = Field(min_length=1)

    @field_validator("background", "text", "text_muted", "accent", "accent_soft",
                     "connector", "table_header_bg", "table_row_color", "table_band",
                     "chart_colors")
    @classmethod
    def _hex_colors(cls, value, info):
        def check(item: str):
            if not _HEX.match(item or ""):
                raise ValueError(f"{info.field_name} must be a #RRGGBB color, got {item!r}")
            return item.upper()
        return [check(c) for c in value] if isinstance(value, list) else check(value)

    def flat(self) -> dict[str, Any]:
        """Flat style dict for the renderer ``theme`` parameter (font faces)."""
        tokens: dict[str, Any] = {}
        if self.body_font:
            tokens["font_name"] = self.body_font
        return tokens

    def swatch(self) -> list[str]:
        return [self.background, self.text, self.accent, self.accent_soft]


@functools.lru_cache(maxsize=16)
def _load_cached(path: str) -> ThemeSpec:
    data = __import__("json").loads(Path(path).read_text(encoding="utf-8"))
    theme_id = Path(path).stem
    return ThemeSpec(id=theme_id, **data)


def available_themes() -> dict[str, dict[str, Any]]:
    """All shipped themes keyed by id, with display metadata for UIs."""
    themes: dict[str, dict[str, Any]] = {}
    for path in sorted(THEMES_DIR.glob("*.json")):
        try:
            theme = _load_cached(str(path))
        except Exception:
            continue  # A broken theme file must not break deck listing.
        themes[theme.id] = {"name": theme.name, "description": theme.description,
                            "swatch": theme.swatch()}
    return themes


def resolve_theme_name(name: str, lens: str | None = None) -> str:
    name = (name or "auto").strip()
    if name.lower() == "auto":
        resolved = LENS_THEME_MAP.get((lens or "executive").strip().lower(), "academic_slate")
        return resolved
    return name


def load_theme(name: str, lens: str | None = None) -> ThemeSpec:
    """Load a theme by id/path; 'auto' resolves through the lens mapping."""
    theme_id = resolve_theme_name(name, lens)
    path = Path(theme_id)
    if not path.is_file():
        path = THEMES_DIR / f"{theme_id}.json"
    if not path.is_file():
        raise ValueError(f"Unknown theme '{theme_id}'. Available: auto, {', '.join(sorted(available_themes()))}")
    return _load_cached(str(path))


def theme_signature(name: str, lens: str | None = None) -> str:
    """Content hash of the resolved theme file for resume/cache identity."""
    from infrastructure.utils.artifacts import file_hash
    theme = load_theme(name, lens)
    source = THEMES_DIR / f"{theme.id}.json"
    return file_hash(source) if source.is_file() else theme.id


def _inject(style: dict[str, Any] | None, tokens: dict[str, Any]) -> dict[str, Any]:
    """setdefault-merge tokens into a style dict; existing keys always win."""
    style = dict(style or {})
    for key, value in tokens.items():
        if value is not None and key not in style:
            style[key] = value
    return style


def apply_theme_to_ir2(content: dict[str, Any], theme: ThemeSpec) -> dict[str, Any]:
    """Return a themed deep copy of an IR2 presentation dict.

    Only presentation-layer style keys are touched: region styles, chart color
    lists, diagram fills, and the slide background when it is still the
    default. Text, tables, grounding, source IDs and asset bindings are
    preserved byte-for-byte, so factual content and evidence hashes survive.
    """
    themed = copy.deepcopy(content)
    for slide in themed.get("slides", []):
        current_bg = (slide.get("background_color") or DEFAULT_BACKGROUND).strip().upper()
        if current_bg in {DEFAULT_BACKGROUND, ""}:
            slide["background_color"] = theme.background
        for region_name, item in (slide.get("content") or {}).items():
            if not isinstance(item, dict):
                continue
            item["style"] = _inject(item.get("style"), _tokens_for(item, region_name, theme))
    return themed


def _tokens_for(item: dict[str, Any], region_name: str, theme: ThemeSpec) -> dict[str, Any]:
    """Role-based style tokens for one content region."""
    kind = item.get("type")
    name = (region_name or "").lower()
    tokens: dict[str, Any] = {}
    if kind in {"heading", "text_group", "bullets", "numbered_list"}:
        tokens["color"] = theme.text
        if kind == "heading":
            if theme.heading_font:
                tokens["font_name"] = theme.heading_font
        elif theme.body_font:
            tokens["font_name"] = theme.body_font
    elif kind == "stat":
        tokens["color"] = theme.accent
        tokens["label_color"] = theme.text_muted
        if theme.heading_font:
            tokens["font_name"] = theme.heading_font
    elif kind == "table":
        tokens.update({"header_bg": theme.table_header_bg, "color": theme.table_row_color,
                       "band_bg": theme.table_band})
        if theme.body_font:
            tokens["font_name"] = theme.body_font
    elif kind == "chart":
        tokens["chart_colors"] = list(theme.chart_colors)
        if theme.body_font:
            tokens["font_name"] = theme.body_font
    elif kind == "diagram":
        tokens.update({"fill": theme.accent_soft, "line_color": theme.accent})
    elif kind in {"card", "metric_card", "callout", "quote", "chips", "compare"}:
        # Predefined visual objects: surface, border and text tokens are injected
        # as style keys; the scene expander consumes them and model styles win.
        tokens.update({"fill": theme.accent_soft, "border_color": theme.accent,
                       "title_color": theme.text, "body_color": theme.text,
                       "muted_color": theme.text_muted, "accent": theme.accent})
    elif kind in {"image", "formula"}:
        # Captions and alt text read the muted token after base.py expansion.
        tokens["color"] = theme.text_muted
    if "subtitle" in name and kind in {"heading", "text_group"}:
        tokens["color"] = theme.text_muted
    if any(hint in name for hint in ("footer", "footnote", "source", "contact", "attribution")) \
            and kind in {"heading", "text_group"}:
        tokens["color"] = theme.text_muted
    return tokens
