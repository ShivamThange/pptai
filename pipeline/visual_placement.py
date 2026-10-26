"""Deterministic placement of planned source visuals (F04 / F13 integration).

The storyboard may select a figure or formula for a slide, and the composer may
still answer with prose only. This module guarantees that a planned visual is
actually placed: it fills an image/formula region when the current layout has
one, or remaps a text-only slide onto a layout that does. It never invents an
asset and never drops a table/chart/diagram to make room.
"""
from __future__ import annotations

from typing import Any

from contracts.ir2_content_schema import (
    BulletsContent,
    FormulaContent,
    ImageContent,
    SlideSpec,
)

VISUAL_TYPES = {"image", "formula"}
TEXTUAL_TYPES = {"heading", "text_group", "bullets", "numbered_list", "stat",
                 "card", "callout", "quote", "chips", "compare"}
# Preferred replacement layouts, in order. All ship image/formula + text regions.
PREFERRED_VISUAL_LAYOUTS = ("IMAGE_WITH_TEXT_RIGHT", "TEXT_WITH_IMAGE_RIGHT")


def _regions(layouts_spec: dict[str, Any], layout_name: str) -> dict[str, Any]:
    return dict(((layouts_spec.get("layouts") or {}).get(layout_name) or {}).get("regions") or {})


def _region_with(regions: dict[str, Any], types: set[str], *, exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    for name, region in regions.items():
        if name in exclude:
            continue
        if types & set(region.get("allowed_types") or []):
            return name
    return None


def _visual_content(asset: dict[str, Any]):
    caption = asset.get("caption") if asset.get("caption_binding") != "UNKNOWN" else None
    if asset.get("kind") == "formula":
        return FormulaContent(source_asset_id=asset["asset_id"], caption=caption)
    return ImageContent(source_asset_id=asset["asset_id"], caption=caption)


def _text_items(slide: SlideSpec) -> list[str]:
    items: list[str] = []
    for content in slide.content.values():
        kind = content.type
        if kind in {"bullets", "numbered_list"}:
            for item in content.items:
                items.append(item if isinstance(item, str) else item.text)
        elif kind == "text_group":
            if content.lines:
                items.extend(str(line) for line in content.lines)
            elif content.text:
                items.append(str(content.text))
        elif kind == "stat":
            for item in content.items or []:
                items.append(f"{item.value} — {item.label}" if item.label else item.value)
            if content.value:
                items.append(f"{content.value} — {content.label}" if content.label else content.value)
        elif kind == "card":
            items.extend(str(value) for value in (content.title, content.text) if value)
        elif kind == "callout":
            items.extend(str(value) for value in (content.title, content.text) if value)
        elif kind == "quote":
            items.extend(str(value) for value in (content.text, content.attribution) if value)
        elif kind == "chips":
            items.extend(str(value) for value in content.labels)
        elif kind == "compare":
            for side in (content.left, content.right):
                items.append(side.heading)
                items.extend(str(value) for value in side.items)
    return [value for value in items if value.strip()]


def _remap(slide: SlideSpec, layouts_spec: dict[str, Any], asset: dict[str, Any]) -> SlideSpec | None:
    """Move a purely textual slide onto a layout that can host the visual."""
    if not all(content.type in TEXTUAL_TYPES for content in slide.content.values()):
        return None
    for layout_name in PREFERRED_VISUAL_LAYOUTS:
        regions = _regions(layouts_spec, layout_name)
        visual_region = _region_with(regions, VISUAL_TYPES)
        text_region = _region_with(regions, {"bullets", "text_group"})
        if not visual_region or not text_region:
            continue
        header_region = _region_with(regions, {"heading"})
        heading = next((content for content in slide.content.values() if content.type == "heading"), None)
        items = _text_items(slide)
        new_content: dict[str, Any] = {visual_region: _visual_content(asset)}
        if heading is not None and header_region:
            new_content[header_region] = heading
        if items:
            # A list is the most permissive text shape the replacement supports.
            new_content[text_region] = BulletsContent(items=items)
        remapped = slide.model_copy(deep=True)
        remapped.layout = layout_name
        remapped.content = new_content
        return remapped
    return None


def ensure_planned_visual(slide: SlideSpec, plan, context: dict[str, Any],
                          layouts_spec: dict[str, Any]) -> SlideSpec:
    """Place one planned figure/formula when the composed slide omitted it."""
    assets = {asset["asset_id"]: asset for asset in context.get("assets", [])}
    planned = [assets[asset_id] for asset_id in getattr(plan, "candidate_asset_ids", [])
               if asset_id in assets and assets[asset_id].get("kind") in VISUAL_TYPES
               and assets[asset_id].get("availability", "AVAILABLE") == "AVAILABLE"]
    if not planned:
        return slide
    used = {content.source_asset_id for content in slide.content.values()
            if content.type in VISUAL_TYPES and getattr(content, "source_asset_id", None)}
    pending = [asset for asset in planned if asset["asset_id"] not in used]
    if not pending:
        return slide
    asset = pending[0]

    regions = _regions(layouts_spec, slide.layout)
    visual_region = _region_with(regions, VISUAL_TYPES)
    if visual_region:
        existing = slide.content.get(visual_region)
        if existing is None or existing.type in VISUAL_TYPES:
            slide.content[visual_region] = _visual_content(asset)
            return slide
        # The only visual-capable region already holds text: switching layout is
        # safer than replacing that text and silently losing content.
    return _remap(slide, layouts_spec, asset) or slide
