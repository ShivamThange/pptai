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

from pydantic import BaseModel, Field, field_validator, model_validator

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


class ChromeSpec(BaseModel):
    """Per-theme slide chrome switches (title bars, footer, rails, numerals).

    Every switch defaults to off so a theme file without a ``chrome`` block
    keeps the exact pre-chrome rendering behavior; validated values fail
    loudly at load time, following the repo's theme conventions.
    """

    model_config = {"extra": "forbid"}

    title_bar: bool = False
    title_bar_height_in: float = Field(default=0.05, gt=0.0, le=0.2)
    title_bar_width_in: float = Field(default=1.2, gt=0.0, le=6.0)
    footer: bool = False
    footer_rule: bool = True
    page_number: bool = True
    footer_font_pt: int = Field(default=10, ge=8, le=14)
    cover_rail: bool = False
    cover_rail_width_in: float = Field(default=0.16, gt=0.0, le=0.5)
    section_numeral: bool = False
    section_numeral_pt: int = Field(default=80, ge=24, le=200)
    quote_mark: bool = False
    quote_mark_pt: int = Field(default=56, ge=24, le=120)


class EffectsSpec(BaseModel):
    """Surface effects consumed by both renderer backends.

    Values are style keys (``shadow``, ``radius_in``, ``line_width``) injected
    into themed objects; renderers treat them as cosmetic and never fail a
    build over an unsupported value.
    """

    model_config = {"extra": "forbid"}

    shadow: bool = False
    shadow_color: str = "#000000"
    shadow_opacity: float = Field(default=0.18, ge=0.0, le=1.0)
    shadow_blur_pt: float = Field(default=10.0, gt=0.0, le=40.0)
    shadow_distance_pt: float = Field(default=3.0, gt=0.0, le=12.0)
    shadow_angle_deg: int = Field(default=90, ge=0, le=359)
    radius_in: float = Field(default=0.08, ge=0.0, le=0.3)
    border_width: float = Field(default=1.0, gt=0.0, le=4.0)

    @field_validator("shadow_color")
    @classmethod
    def _hex_color(cls, value, info):
        if not _HEX.match(value or ""):
            raise ValueError(f"{info.field_name} must be a #RRGGBB color, got {value!r}")
        return value.upper()


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
    # --- v2 tokens (all optional; empty values resolve to v1 counterparts) ---
    surface: str = ""
    surface_raised: str = ""
    table_header_text: str = ""
    border: str = ""
    chrome: ChromeSpec = Field(default_factory=ChromeSpec)
    effects: EffectsSpec = Field(default_factory=EffectsSpec)

    @field_validator("background", "text", "text_muted", "accent", "accent_soft",
                     "connector", "table_header_bg", "table_row_color", "table_band",
                     "surface", "surface_raised", "table_header_text", "border",
                     "chart_colors")
    @classmethod
    def _hex_colors(cls, value, info):
        def check(item: str):
            if not _HEX.match(item or ""):
                raise ValueError(f"{info.field_name} must be a #RRGGBB color, got {item!r}")
            return item.upper()
        return [check(c) for c in value] if isinstance(value, list) else check(value)

    @model_validator(mode="after")
    def _resolve_optional_tokens(self):
        # Optional v2 tokens fall back to their v1 counterparts so downstream
        # consumers (token injection, decorations, renderers) can read them
        # unconditionally without None/empty checks.
        if not self.surface:
            self.surface = self.accent_soft
        if not self.surface_raised:
            self.surface_raised = self.surface
        if not self.border:
            self.border = self.accent
        if not self.table_header_text:
            self.table_header_text = "#FFFFFF"
        return self

    def flat(self) -> dict[str, Any]:
        """Flat style dict for the renderer ``theme`` parameter.

        Carries the body font face, the connector fallback color and the
        shared shadow recipe, so both backends can elevate any object whose
        style opts in with ``shadow: true``. Extra keys are ignored by text
        primitives, exactly like region style keys today.
        """
        tokens: dict[str, Any] = {}
        if self.body_font:
            tokens["font_name"] = self.body_font
        tokens["connector"] = self.connector
        effect = self.effects
        tokens.update({
            "shadow_color": effect.shadow_color,
            "shadow_opacity": effect.shadow_opacity,
            "shadow_blur_pt": effect.shadow_blur_pt,
            "shadow_distance_pt": effect.shadow_distance_pt,
            "shadow_angle_deg": effect.shadow_angle_deg,
        })
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
                       "band_bg": theme.table_band, "header_text": theme.table_header_text})
        if theme.body_font:
            tokens["font_name"] = theme.body_font
    elif kind == "chart":
        tokens["chart_colors"] = list(theme.chart_colors)
        if theme.body_font:
            tokens["font_name"] = theme.body_font
    elif kind == "diagram":
        tokens.update({"fill": theme.accent_soft, "line_color": theme.accent,
                       "line_width": theme.effects.border_width})
    elif kind in {"card", "metric_card", "callout", "quote", "chips", "compare"}:
        # Predefined visual objects: surface, border and text tokens are injected
        # as style keys; the scene expander consumes them and model styles win.
        # metric_card/callout sit on the raised surface; effects carry the
        # elevation recipe (shadow/radius/border weight) for both backends.
        raised = kind in {"metric_card", "callout"}
        tokens.update({"fill": theme.surface_raised if raised else theme.surface,
                       "border_color": theme.border,
                       "title_color": theme.text, "body_color": theme.text,
                       "muted_color": theme.text_muted, "accent": theme.accent,
                       "line_width": theme.effects.border_width,
                       "radius_in": theme.effects.radius_in,
                       "shadow": theme.effects.shadow})
    elif kind in {"image", "formula"}:
        # Captions and alt text read the muted token after base.py expansion.
        tokens["color"] = theme.text_muted
    if "subtitle" in name and kind in {"heading", "text_group"}:
        tokens["color"] = theme.text_muted
    if any(hint in name for hint in ("footer", "footnote", "source", "contact", "attribution")) \
            and kind in {"heading", "text_group"}:
        tokens["color"] = theme.text_muted
    return tokens
