"""Renderer contract v1. Geometry is in inches, resolved before rendering.

The legacy IR2 adapter owns layout-catalog geometry during migration. Future
solvers can submit this same scene contract without a layout catalog.
"""
from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.asset_registry import AssetBindingError, AssetRegistry, validate_asset_content


class Box(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class SceneObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str = Field(min_length=1)
    kind: Literal["heading", "text_group", "bullets", "numbered_list", "table", "chart", "image", "formula", "shape", "connector"]
    box: Box
    content: dict[str, Any]
    style: dict[str, Any] = Field(default_factory=dict)
    role: str = "body"
    required: bool = True
    source_unit_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_content(self):
        c = self.content
        if self.kind == "table":
            headers, rows = c.get("headers", []), c.get("rows", [])
            width = len(headers) or (len(rows[0]) if rows and isinstance(rows[0], list) else 0)
            if not width or not rows or any(not isinstance(row, list) or len(row) != width for row in rows):
                raise ValueError("Table column lengths must match headers/first row and contain rows")
            occupied=set()
            for r,col,rs,cs in c.get('merges',[]):
                if min(r,col)<0 or min(rs,cs)<1 or r+rs>len(rows)+bool(headers) or col+cs>width:
                    raise ValueError('TABLE_SPAN_INVALID: scene merge outside grid')
                cells={(i,j) for i in range(r,r+rs) for j in range(col,col+cs)}
                if occupied & cells:
                    raise ValueError('TABLE_SPAN_INVALID: overlapping scene merges')
                occupied.update(cells)
        elif self.kind == "chart":
            if c.get("chart_type", "column") not in {"column", "bar", "line", "area", "pie"}:
                raise ValueError("Unsupported chart type")
            categories, series = c.get("categories", []), c.get("series", [])
            if not categories or not series or any(not isinstance(s, dict) or len(s.get("values", [])) != len(categories) for s in series):
                raise ValueError("Chart series lengths must match categories")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for s in series for v in s["values"]):
                raise ValueError("Chart values must be finite numbers")
            if c.get("chart_type") == "pie" and (len(series) != 1 or any(v < 0 for v in series[0]["values"]) or not any(series[0]["values"])):
                raise ValueError("Pie charts require one nonnegative, nonzero series")
        elif self.kind in {"image", "formula"}:
            if not c.get("path") or not c.get("content_sha256"):
                raise AssetBindingError("Image/formula requires a real hashed asset")
        elif self.kind in {"bullets", "numbered_list"}:
            if not c.get("items"):
                raise ValueError("List requires items")
        elif self.kind == "shape":
            if c.get("shape_type", "rect") not in {"rect", "roundRect", "diamond", "ellipse"}:
                raise ValueError("Unsupported native shape")
        elif self.kind == "connector":
            if not c.get("from_id") or not c.get("to_id"):
                raise ValueError("Connector requires node IDs")
        elif not c.get("text") and not c.get("lines"):
            raise ValueError("Text object requires visible content")
        return self


class SlideScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slide_id: str
    background_color: str = "#FFFFFF"
    notes: str = ""
    source_unit_ids: list[str] = Field(default_factory=list)
    objects: list[SceneObject] = Field(min_length=1)

    @model_validator(mode="after")
    def relationships(self):
        ids = [o.object_id for o in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate scene object IDs")
        nodes = {o.object_id for o in self.objects if o.kind == "shape"}
        for obj in self.objects:
            if obj.kind == "connector" and not {obj.content["from_id"], obj.content["to_id"]}.issubset(nodes):
                raise ValueError("Connector references an unknown native node")
        return self


class PresentationScene(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["scene-v1"] = "scene-v1"
    adapter_version: str = "direct-scene-v1"
    title: str = "Generated Presentation"
    width_inches: float = Field(gt=0)
    height_inches: float = Field(gt=0)
    slides: list[SlideScene] = Field(min_length=1)

    @model_validator(mode="after")
    def slide_ids(self):
        ids = [s.slide_id for s in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate scene slide IDs")
        return self


@dataclass(frozen=True)
class RenderArtifact:
    path: Path
    backend: str
    version: str
    artifact_hash: str
    warnings: tuple[str, ...]
    capabilities: dict[str, Any]

    def metadata(self):
        return {"backend": self.backend, "version": self.version, "contract": "scene-v1",
                "artifact_hash": self.artifact_hash, "warnings": list(self.warnings), "capabilities": self.capabilities}


class Renderer(Protocol):
    def render(self, scene_graph: PresentationScene, asset_registry: AssetRegistry | None,
               theme: dict[str, Any] | None, output_path: str | Path) -> RenderArtifact: ...


# Predefined visual objects. They are expanded into ordinary scene primitives
# (background shape + text) so both renderer backends keep a simple, versioned
# contract and no backend needs object-specific code.
VISUAL_OBJECT_KINDS = {"card", "metric_card", "callout", "quote", "chips", "compare"}


def _expand_card(box: "Box", c: dict, style: dict, add) -> None:
    pad = 0.2
    add("/card-bg", "shape", box, {"shape_type": "roundRect"}, "background",
        {**style, "fill": style.get("fill", "#F8FAFC"), "line_color": style.get("border_color", "#CBD5E1"),
         "line_width": 1.0})
    inner_w = max(0.2, box.w - 2 * pad)
    title_h = 0.4 if c.get("text") or c.get("metric") else max(0.3, box.h - 2 * pad)
    if c.get("title"):
        add("/card-title", "heading", Box(x=box.x + pad, y=box.y + pad * 0.7, w=inner_w, h=title_h),
            {"text": str(c["title"])}, "body",
            {**style, "font_size": 18, "bold": True, "color": style.get("title_color", "#0F172A"), "align": "left"})
    cursor = box.y + pad * 0.7 + title_h + 0.06
    if c.get("metric"):
        metric = c["metric"]
        add("/card-metric", "heading", Box(x=box.x + pad, y=cursor, w=inner_w, h=0.46),
            {"text": str(metric.get("value", ""))}, "stat",
            {**style, "font_size": 30, "bold": True, "color": style.get("accent", "#2563EB"), "align": "left"})
        cursor += 0.46
        if metric.get("label"):
            add("/card-metric-label", "heading", Box(x=box.x + pad, y=cursor, w=inner_w, h=0.28),
                {"text": str(metric["label"])}, "label",
                {**style, "font_size": 11, "color": style.get("muted_color", "#64748B"), "align": "left"})
            cursor += 0.3
    if c.get("text"):
        body_h = max(0.12, box.y + box.h - pad - cursor)
        add("/card-text", "text_group", Box(x=box.x + pad, y=cursor, w=inner_w, h=body_h),
            {"text": str(c["text"])}, "body",
            {**style, "font_size": 14, "color": style.get("body_color", "#334155"), "align": "left"})


def _expand_metric_card(box: "Box", c: dict, style: dict, add) -> None:
    add("/metric-bg", "shape", box, {"shape_type": "roundRect"}, "background",
        {**style, "fill": style.get("fill", "#F8FAFC"), "line_color": style.get("border_color", "#CBD5E1"),
         "line_width": 1.0})
    add("/metric-value", "heading", Box(x=box.x + 0.08, y=box.y + 0.14, w=max(0.2, box.w - 0.16), h=0.55),
        {"text": str(c.get("value", ""))}, "stat",
        {**style, "font_size": 30, "bold": True, "color": style.get("accent", "#2563EB"), "align": "center"})
    cursor = box.y + 0.7
    if c.get("label"):
        add("/metric-label", "heading", Box(x=box.x + 0.1, y=cursor, w=max(0.2, box.w - 0.2), h=0.28),
            {"text": str(c["label"])}, "label",
            {**style, "font_size": 12, "color": style.get("muted_color", "#64748B"), "align": "center"})
        cursor += 0.28
    if c.get("trend"):
        add("/metric-trend", "heading", Box(x=box.x + 0.1, y=cursor, w=max(0.2, box.w - 0.2), h=0.26),
            {"text": str(c["trend"])}, "label",
            {**style, "font_size": 11, "bold": True, "color": style.get("accent", "#2563EB"), "align": "center"})
        cursor += 0.26
    if c.get("context") and box.y + box.h - cursor > 0.2:
        add("/metric-context", "text_group", Box(x=box.x + 0.12, y=cursor, w=max(0.2, box.w - 0.24),
                                                 h=box.y + box.h - cursor - 0.08),
            {"text": str(c["context"])}, "label",
            {**style, "font_size": 12, "color": style.get("body_color", "#475569"), "align": "center"})


def _expand_callout(box: "Box", c: dict, style: dict, add) -> None:
    add("/callout-bg", "shape", box, {"shape_type": "roundRect"}, "background",
        {**style, "fill": style.get("fill", "#EFF6FF"), "line_color": style.get("accent", "#2563EB"),
         "line_width": 1.5})
    inner_w = max(0.2, box.w - 0.36)
    cursor = box.y + 0.14
    if c.get("title"):
        add("/callout-title", "heading", Box(x=box.x + 0.18, y=cursor, w=inner_w, h=0.34),
            {"text": str(c["title"])}, "body",
            {**style, "font_size": 16, "bold": True, "color": style.get("accent", "#2563EB"), "align": "left"})
        cursor += 0.4
    add("/callout-text", "text_group",
        Box(x=box.x + 0.18, y=cursor, w=inner_w, h=max(0.14, box.y + box.h - cursor - 0.12)),
        {"text": str(c.get("text", ""))}, "body",
        {**style, "font_size": 14, "color": style.get("body_color", "#0F172A"), "align": "left"})


def _expand_quote(box: "Box", c: dict, style: dict, add) -> None:
    add("/quote-bg", "shape", box, {"shape_type": "rect"}, "background",
        {**style, "fill": style.get("fill", "#F8FAFC"), "line_color": style.get("border_color", "#E2E8F0"),
         "line_width": 0.75})
    attribution_h = 0.3 if c.get("attribution") else 0.0
    add("/quote-text", "text_group",
        Box(x=box.x + 0.28, y=box.y + 0.2, w=max(0.2, box.w - 0.56),
            h=max(0.2, box.h - 0.4 - attribution_h)),
        {"text": str(c.get("text", ""))}, "body",
        {**style, "font_size": 20, "italic": True, "color": style.get("title_color", "#0F172A"), "align": "left"})
    if c.get("attribution"):
        add("/quote-attribution", "heading",
            Box(x=box.x + 0.28, y=box.y + box.h - 0.4, w=max(0.2, box.w - 0.56), h=0.28),
            {"text": str(c["attribution"])}, "label",
            {**style, "font_size": 11, "color": style.get("muted_color", "#64748B"), "align": "right"})


def _chip_rows(labels: list[str], width_in: float, font_pt: float = 11.0,
               max_rows: int = 4) -> list[list[tuple[str, float]]]:
    from core import text_metrics as tm
    rows: list[list[tuple[str, float]]] = []
    gap, pad = 0.12, 0.5
    for label in labels:
        text = str(label).strip()
        if not text:
            continue
        chip_w = min(width_in, tm.text_width_pt(text, font_pt) / 72.0 + pad)
        if not rows or sum(w for _, w in rows[-1]) + gap + chip_w > width_in:
            if len(rows) >= max_rows:
                break
            rows.append([])
        rows[-1].append((text, chip_w))
    return rows


def _expand_chips(box: "Box", c: dict, style: dict, add) -> None:
    labels = [str(item) for item in (c.get("labels") or [])]
    chip_h, gap = 0.42, 0.12
    rows = _chip_rows(labels, max(0.4, box.w), max_rows=max(1, int((box.h + gap) // (chip_h + gap))))
    for row_index, row in enumerate(rows):
        y = box.y + row_index * (chip_h + gap)
        x = box.x
        for chip_index, (label, chip_w) in enumerate(row):
            chip_box = Box(x=x, y=y, w=max(0.2, chip_w), h=chip_h)
            add(f"/chip-{row_index}-{chip_index}-bg", "shape", chip_box, {"shape_type": "roundRect"}, "background",
                {**style, "fill": style.get("fill", "#F1F5F9"), "line_color": style.get("accent", "#2563EB"),
                 "line_width": 0.75})
            add(f"/chip-{row_index}-{chip_index}-text", "heading",
                Box(x=x + 0.05, y=y + 0.08, w=max(0.1, chip_w - 0.1), h=chip_h - 0.16),
                {"text": label}, "label",
                {**style, "font_size": 11, "bold": True, "color": style.get("title_color", "#0F172A"),
                 "align": "center"})
            x += chip_w + gap


def _expand_compare(box: "Box", c: dict, style: dict, add) -> None:
    gap = 0.24
    side_w = max(0.3, (box.w - gap) / 2)
    sides = ((c.get("left") or {}, box.x), (c.get("right") or {}, box.x + side_w + gap))
    for index, (side, x) in enumerate(sides):
        side_box = Box(x=x, y=box.y, w=side_w, h=box.h)
        add(f"/compare-{index}-bg", "shape", side_box, {"shape_type": "rect"}, "background",
            {**style, "fill": style.get("fill", "#F8FAFC"), "line_color": style.get("border_color", "#E2E8F0"),
             "line_width": 0.75})
        add(f"/compare-{index}-heading", "heading", Box(x=x + 0.16, y=box.y + 0.12, w=max(0.2, side_w - 0.32), h=0.34),
            {"text": str(side.get("heading", ""))}, "body",
            {**style, "font_size": 15, "bold": True, "color": style.get("accent", "#2563EB"), "align": "left"})
        add(f"/compare-{index}-items", "bullets",
            Box(x=x + 0.16, y=box.y + 0.54, w=max(0.2, side_w - 0.32), h=max(0.2, box.h - 0.66)),
            {"items": [str(item) for item in side.get("items") or []]}, "body",
            {**style, "font_size": 14, "color": style.get("body_color", "#334155"), "align": "left"})


_EXPANDERS = {
    "card": _expand_card,
    "metric_card": _expand_metric_card,
    "callout": _expand_callout,
    "quote": _expand_quote,
    "chips": _expand_chips,
    "compare": _expand_compare,
}


def validate_scene_assets(scene: PresentationScene, registry: AssetRegistry | None):
    """Recheck bytes at the rendering boundary, including direct solver scenes."""
    for slide in scene.slides:
        for obj in slide.objects:
            if obj.kind == "table" and obj.content.get("source_asset_id") and registry is not None:
                # Scene tables were expanded from the verified registry grid, so
                # their header row is promoted out of the body. Re-check the
                # source binding rather than comparing the derived shape to the
                # selection grid.
                registry.require(obj.content["source_asset_id"], "table")
                continue
            if obj.kind in {"table", "chart"} and registry is not None:
                validate_asset_content({**obj.content, "type": obj.kind}, registry)
            if obj.kind not in {"image", "formula"}:
                continue
            path = Path(obj.content["path"])
            if registry is not None:
                asset = registry.require(obj.content.get("source_asset_id"), obj.kind)
                expected_path = registry.require_representation(asset.asset_id).path if asset.content else asset.file_path
                if path.resolve() != Path(expected_path).resolve():
                    raise AssetBindingError("Scene asset path differs from registry")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != obj.content["content_sha256"]:
                raise AssetBindingError("Scene asset missing or hash changed")
            with Image.open(path) as image:
                image.verify()


def legacy_ir2_to_scene(content: dict, layouts: dict, registry=None, search_dirs=(),
                        dynamic_regions: dict[int, dict[str, dict]] | None = None) -> PresentationScene:
    """Explicit IR2-layout-v1 -> scene-v1 adapter; never mutates input facts.

    ``dynamic_regions`` optionally supplies per-slide (1-based index) complete
    region definitions from the F13 layout engine. Each override replaces the
    catalog geometry for that slide only; allowed_types/default_style are
    copied from the catalog by the engine, so validation semantics are stable.
    """
    from renderers.python_primitives import resolve_asset_path
    content = copy.deepcopy(content)
    dims = layouts["slide_dimensions"]
    width, height = dims["width_inches"], dims["height_inches"]
    if not content.get("slides"):
        raise ValueError("IR2 contains no slides; refusing to create an empty presentation")
    slides = []
    supported = {"heading", "text_group", "bullets", "numbered_list", "stat", "image", "formula", "table", "chart", "diagram"} | VISUAL_OBJECT_KINDS
    for index, slide in enumerate(content["slides"], 1):
        layout = layouts["layouts"].get(slide.get("layout"))
        if layout is None:
            raise ValueError(f"Slide {index}: unknown layout '{slide.get('layout')}'")
        if not slide.get("content"):
            raise ValueError(f"Slide {index} has no content regions")
        objects = []
        overrides = (dynamic_regions or {}).get(index) or {}
        for name, c in slide["content"].items():
            region = overrides.get(name) or layout["regions"].get(name)
            if region is None:
                raise ValueError(f"Slide {index}: unknown region '{name}'")
            if not isinstance(c, dict) or c.get("type") not in supported:
                raise ValueError(f"Slide {index} region {name}: unsupported type")
            kind = c["type"]
            if kind not in region.get("allowed_types", []):
                raise ValueError(f"Slide {index} region {name}: type {kind} not allowed")
            # Absolute boxes may be supplied by a solver in scene-v1 directly.
            box = Box(x=region["left"] * width, y=region["top"] * height,
                      w=region["width"] * width, h=region["height"] * height)
            style = {**(region.get("default_style") or {}), **(c.get("style") or {})}
            oid = f"slide-{index}/{name}"
            # A slide retrieval scope is not proof of each object's support.
            # Keep the scope on the slide; R03's actual bindings stay in IR2.
            source_ids = c.get("source_unit_ids", [])
            def add(suffix, kind, box, payload, role="body", style_override=None):
                objects.append(SceneObject(object_id=oid + suffix, kind=kind, box=box, content=payload,
                                           style=style if style_override is None else style_override,
                                           role=role, source_unit_ids=source_ids))
            if registry is not None:
                bound_asset = validate_asset_content(c, registry)
                if bound_asset:
                    if kind == "table":
                        c.update(registry.select_table(bound_asset.asset_id,c.get('selection')))
                    elif kind == 'chart':
                        c.update(registry.resolve_chart(bound_asset.asset_id,c))
                    else:
                        c["path"] = registry.require_representation(bound_asset.asset_id).path if bound_asset.content else bound_asset.file_path
                    c["caption"] = c.get("caption") or bound_asset.caption
            else:
                bound_asset = None
            if kind == "table" and bound_asset is not None:
                header_rows = getattr(bound_asset.content, "header_rows", []) if bound_asset.content else []
                if not c.get("headers") and header_rows == [0] and c.get("rows"):
                    # The rich-grid selection keeps the source header as row 0.
                    # Promote it so renderers style it as a header, not data.
                    c["headers"] = [str(value) for value in c["rows"][0]]
                    c["rows"] = c["rows"][1:]
                    # Merge coordinates are absolute table rows and the header is
                    # re-added at row 0 by the renderer, so they stay unchanged.
            if kind in {"image", "formula"}:
                path = resolve_asset_path(c.get("source_asset_id"), c.get("path"), list(search_dirs))
                if not path:
                    raise AssetBindingError(f"Required {kind} asset is missing")
                with Image.open(path) as image:
                    iw, ih = image.size
                caption = c.pop("caption", None)
                cap_h = .3 if caption and box.h > .5 else 0
                scale = min(box.w / iw, (box.h - cap_h) / ih)
                if kind=='formula' and registry is not None and registry.assets[c['source_asset_id']].content:
                    scale = min(scale, 1/registry.min_ppi)
                ibox = Box(x=box.x + (box.w - iw * scale) / 2, y=box.y + (box.h - cap_h - ih * scale) / 2,
                           w=iw * scale, h=ih * scale)
                c.update(path=str(path.resolve()), content_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                c.update(raster_ppi=min(iw/ibox.w,ih/ibox.h),label_legibility='UNKNOWN')
                c['minimum_ppi']=registry.min_ppi if registry else 150
                c['resolution_status']='ASSET_RESOLUTION_LOW' if c['raster_ppi']<c['minimum_ppi'] else 'ADEQUATE_PIXEL_DENSITY'
                add("", kind, ibox, c)
                if cap_h:
                    caption_style = {**style, "font_size": 10, "italic": True, "align": "center"}
                    caption_style.setdefault("color", "#64748B")
                    add("/caption", "text_group", Box(x=box.x, y=box.y+box.h-cap_h, w=box.w, h=cap_h),
                        {"text": caption}, "caption", caption_style)
            elif kind == "table":
                if c.get("source_asset_id") and not c.get("rows"):
                    import json
                    from pipeline.source_adapter import normalize_table_data
                    filename = c["source_asset_id"]
                    path = resolve_asset_path(filename if filename.endswith(".json") else filename + ".json", search_dirs=list(search_dirs))
                    if not path:
                        raise AssetBindingError("Required table asset is missing")
                    c.update(normalize_table_data(json.loads(path.read_text(encoding="utf-8"))))
                add("", kind, box, c, "table")
            elif kind == "diagram":
                steps, nodes, edges = c.get("steps"), c.get("nodes"), c.get("edges") or []
                if steps and nodes:
                    raise ValueError("Diagram cannot contain both steps and nodes")
                if steps:
                    nodes = [{"id": str(i), "label": step["title"] if isinstance(step, dict) else str(step),
                              "subtext": step.get("description") if isinstance(step, dict) else None} for i, step in enumerate(steps)]
                    edges = [{"from_id": str(i), "to_id": str(i+1)} for i in range(len(nodes)-1)]
                if not nodes:
                    raise ValueError("Diagram requires native nodes or steps; placeholders are unsupported")
                ids = [str(n["id"]) for n in nodes]
                if len(ids) != len(set(ids)):
                    raise ValueError("Duplicate diagram node IDs")
                gap = min(.2, box.w / (len(nodes) * 4))
                nw = (box.w - gap*(len(nodes)-1)) / len(nodes)
                nh = min(box.h, 1.2)
                for i, node in enumerate(nodes):
                    text = node["label"] + ("\n" + node["subtext"] if node.get("subtext") else "")
                    node_style = {**style, "align": "center"}
                    node_style.setdefault("font_size", 13)
                    node_style.setdefault("fill", "#EFF6FF")
                    node_style.setdefault("line_color", "#3B82F6")
                    add("/node-" + str(node["id"]), "shape", Box(x=box.x+i*(nw+gap), y=box.y+(box.h-nh)/2, w=nw, h=nh),
                        {"shape_type": "roundRect", "text": text}, "diagram", node_style)
                for i, edge in enumerate(edges):
                    if str(edge.get("from_id")) not in ids or str(edge.get("to_id")) not in ids:
                        raise ValueError("Diagram edge references an unknown node")
                    if edge.get("label"):
                        raise ValueError("Labeled edges require a resolved scene text object (F14); refusing to skip labels")
                    add("/edge-"+str(i), "connector", box, {"from_id": oid+"/node-"+str(edge["from_id"]),
                        "to_id": oid+"/node-"+str(edge["to_id"])}, "diagram")
            elif kind == "stat":
                items = c.get("items") or [{"value": c.get("value", ""), "label": c.get("label", "")}]
                gap = min(.15, box.w / (len(items)*4))
                cw = (box.w-gap*(len(items)-1))/len(items)
                for i, item in enumerate(items):
                    item_style = {**style, **(item.get("style") or {})}
                    value = str(item.get("value", ""))
                    if not value:
                        raise ValueError("Stat requires a visible value")
                    size = 24 if len(value)>12 else 32 if len(value)>8 else item_style.get("value_font_size", item_style.get("font_size", 42))
                    add("/value-"+str(i), "heading", Box(x=box.x+i*(cw+gap), y=box.y, w=cw, h=box.h*.65),
                        {"text": value}, "stat", {**item_style, "font_size": size, "bold": True, "align": "center"})
                    if item.get("label"):
                        label_style = {"font_size": 11, "align": "center"}
                        label_style["color"] = style.get("label_color") or "#64748B"
                        add("/label-"+str(i), "heading", Box(x=box.x+i*(cw+gap), y=box.y+box.h*.65, w=cw, h=box.h*.35),
                            {"text": item["label"]}, "label", label_style)
            elif kind in VISUAL_OBJECT_KINDS:
                _EXPANDERS[kind](box, c, style, add)
            else:
                if kind == "chart" and c.get("series") and not isinstance(c["series"][0], dict):
                    c["series"] = [{"name": "Series 1", "values": c["series"]}]
                footer_like = any(hint in (name or "").lower() for hint in
                                  ("source", "footer", "footnote", "attribution", "caption"))
                role = ("title" if kind == "heading" else "chart_label" if kind == "chart"
                        else "caption" if footer_like else "body")
                add("", kind, box, c, role)
        slides.append(SlideScene(slide_id=f"slide-{index}", background_color=slide.get("background_color") or "#FFFFFF",
                                 notes=slide.get("notes") or "", source_unit_ids=slide.get("source_unit_ids", []), objects=objects))
    return PresentationScene(adapter_version="ir2-layout-v1", title=content.get("title") or "Generated Presentation",
                             width_inches=width, height_inches=height, slides=slides)
