import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Any

# Docling labels that are page furniture, never sections or obligations.
PAGE_FURNITURE_KINDS = {"page_header", "page_footer", "footnote", "header", "footer"}


def run_docling_extraction(source_path: str, output_dir: str = "output", use_gpu: bool = False,
                           *, resolved_options=None, context=None, limits=None) -> Dict[str, Any]:
    """Compatibility wrapper using the same explicit routing as service intake."""
    from pipeline.ingestion.router import resolve_options
    from pipeline.ingestion.adapters.docling import convert
    options = resolved_options or resolve_options(source_path, use_gpu=use_gpu)[0]
    return run_docling_extraction_for_type(source_path, output_dir, options, context=context, limits=limits)


def run_docling_extraction_for_type(source_path, output_dir, resolved_options, *, context=None, limits=None):
    from pipeline.ingestion.adapters.docling import convert
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return convert(source_path, output_dir, resolved_options, context=context, limits=limits)


def _item_locations(item, document_id):
    source_id = f"{document_id}:{item.self_ref}"
    locations = []
    for prov in getattr(item, "prov", []):
        bbox = getattr(prov, "bbox", None)
        locations.append(
            {
                "document_id": document_id,
                "source_id": source_id,
                "page": prov.page_no,
                "bbox": [bbox.l, bbox.t, bbox.r, bbox.b] if bbox else None,
                "coord_origin": str(bbox.coord_origin.value) if bbox else None,
                "charspan": (
                    list(prov.charspan) if getattr(prov, "charspan", None) else None
                ),
            }
        )
    # The item reference is real even on non-paginated documents.
    return source_id, locations or [
        {"document_id": document_id, "source_id": source_id}
    ]


def _shared_panel_caption(item, doc):
    """Recover a two-panel caption only when its explicit labels and geometry agree.

    Docling may attach a shared (left)/(right) caption to only one picture.
    Ambiguous, non-paginated, and non-panel captions remain unknown.
    """

    def box(node):
        if len(node.prov) != 1:
            return None
        prov = node.prov[0]
        page = doc.pages.get(prov.page_no)
        if page is None or page.size is None:
            return None
        bbox = prov.bbox.to_top_left_origin(page_height=page.size.height)
        return prov.page_no, bbox

    target = box(item)
    if target is None:
        return None
    matches = []
    for sibling in doc.pictures:
        if sibling.self_ref == item.self_ref or not sibling.captions:
            continue
        caption = sibling.caption_text(doc)
        if "(left)" not in caption.lower() or "(right)" not in caption.lower():
            continue
        other = box(sibling)
        if other is None or other[0] != target[0]:
            continue
        left, right = sorted((target[1], other[1]), key=lambda bbox: bbox.l)
        height = min(left.b - left.t, right.b - right.t)
        overlap = min(left.b, right.b) - max(left.t, right.t)
        if height <= 0 or overlap / height < 0.5 or left.r > right.l:
            continue
        for ref in sibling.captions:
            cap_item = ref.resolve(doc)
            cap = box(cap_item)
            if cap is None or cap[0] != target[0]:
                continue
            cap_box = cap[1]
            if (
                cap_box.l > left.l
                or cap_box.r < right.r
                or cap_box.t < max(left.b, right.b)
            ):
                continue
            if cap_box.t - max(left.b, right.b) > max(
                left.b - left.t, right.b - right.t
            ):
                continue
            # More than two horizontally covered, vertically aligned panels is
            # ambiguous for a caption with only left/right labels.
            covered = []
            for picture in doc.pictures:
                candidate = box(picture)
                if candidate and candidate[0] == target[0]:
                    candidate_box = candidate[1]
                    if (
                        cap_box.l <= candidate_box.l
                        and cap_box.r >= candidate_box.r
                        and min(candidate_box.b, left.b, right.b)
                        > max(candidate_box.t, left.t, right.t)
                    ):
                        covered.append(picture.self_ref)
            if len(covered) == 2:
                matches.append(sibling)
                break
    return matches[0] if len(matches) == 1 else None


def _same_page_caption(item, doc, used_captions):
    """Bind an uncaptioned picture to a same-page caption item by geometry.

    Academic PDFs frequently detach captions from figures; Docling leaves the
    picture uncaptioned. A caption-labeled text item on the same page that
    horizontally overlaps the picture and sits within 12% of the page height
    is treated as this picture's caption (nearest such candidate wins).
    """

    def box(node):
        if len(node.prov) != 1:
            return None
        prov = node.prov[0]
        page = doc.pages.get(prov.page_no)
        if page is None or page.size is None:
            return None
        return prov.page_no, prov.bbox.to_top_left_origin(page_height=page.size.height)

    target = box(item)
    if target is None:
        return None
    page_no, picture = target
    page_height = doc.pages[page_no].size.height
    best = None
    for text_item in doc.texts:
        label = str(getattr(text_item.label, "value", text_item.label)).lower()
        if "caption" not in label:
            continue
        text = (text_item.text or "").strip()
        # Table captions belong to tables, not pictures.
        if not text or re.match(r"table\b", text, re.I):
            continue
        if text_item.self_ref in used_captions:
            continue
        cap = box(text_item)
        if cap is None or cap[0] != page_no:
            continue
        _, cbox = cap
        overlap = min(cbox.r, picture.r) - max(cbox.l, picture.l)
        if overlap <= 0:
            continue
        gap = min(abs(cbox.t - picture.b), abs(picture.t - cbox.b))
        if gap > 0.12 * page_height:
            continue
        if best is None or gap < best[0]:
            best = (gap, text_item)
    if best is None:
        return None
    used_captions.add(best[1].self_ref)
    return best[1]


def export_docling_document(doc, source_path: str, output_dir: str) -> Dict[str, Any]:
    """Project installed Docling item APIs without losing locations or captions."""
    source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    document_id = f"doc_{source_hash}"
    assets_dir = Path(output_dir).resolve() / "assets"
    for kind in ("images", "tables", "formulas"):
        (assets_dir / kind).mkdir(parents=True, exist_ok=True)
    doc.save_as_json(Path(output_dir) / "docling_document.json")
    source_item_ids = [
        f"{document_id}:{item.self_ref}"
        for item in [*doc.texts, *doc.pictures, *doc.tables]
    ]
    # Caption text items that are already bound to a picture (directly or via
    # geometry) must not also be emitted as standalone blocks; that duplicated
    # every caption into the knowledge-extraction input.
    bound_caption_refs = set()
    for picture in doc.pictures:
        for ref in picture.captions:
            cap = ref.resolve(doc)
            if cap is not None:
                bound_caption_refs.add(cap.self_ref)
    used_captions = set()
    blocks, assets, relationships = [], [], []
    current_section = "Root"
    for counter, (item, level) in enumerate(doc.iterate_items(), 1):
        block_id = f"{document_id}:block_{counter:04d}"
        item_kind = str(getattr(item.label, "value", item.label)).lower()
        source_id, locations = _item_locations(item, document_id)
        text = getattr(item, "text", "").strip()
        # Only real structural headings advance the section; running heads
        # (page_header) and footers must not pollute section tracking.
        if item_kind in {"title", "section_header", "chapter", "heading"} or (
                "heading" in item_kind and item_kind not in PAGE_FURNITURE_KINDS):
            current_section = text or "Section Header"
        caption, caption_refs, caption_locations = "", [], []
        caption_binding, caption_findings = "UNKNOWN", []
        caption_item = item
        if "picture" in item_kind and not item.captions:
            shared = _shared_panel_caption(item, doc)
            if shared is not None:
                caption_item = shared
                caption_binding = "SHARED_PANEL_GEOMETRY"
                caption_findings.append(
                    "Shared left/right panel caption inferred from explicit labels and same-page geometry"
                )
            else:
                nearby = _same_page_caption(item, doc, used_captions)
                if nearby is not None:
                    caption = (nearby.text or "").strip()
                    caption_binding = "SAME_PAGE_GEOMETRY"
                    cap_id, cap_locations = _item_locations(nearby, document_id)
                    caption_refs = [cap_id]
                    caption_locations = list(cap_locations)
                    bound_caption_refs.add(nearby.self_ref)
                    caption_findings.append(
                        "Caption bound to this picture by same-page overlap and proximity"
                    )
        if not caption and hasattr(caption_item, "caption_text"):
            caption = caption_item.caption_text(doc)
            if caption and caption_binding == "UNKNOWN":
                caption_binding = "DIRECT"
            for ref in caption_item.captions:
                cap_id, cap_locations = _item_locations(ref.resolve(doc), document_id)
                caption_refs.append(cap_id)
                caption_locations.extend(cap_locations)
        asset = None
        if "table" in item_kind:
            asset_id = f"table_{document_id}_block_{counter:04d}"
            df = item.export_to_dataframe(doc=doc)
            has_headers = bool(item.data.grid) and any(
                cell.column_header for cell in item.data.grid[0]
            )
            headers = [str(value) for value in df.columns] if has_headers else []
            rows = [
                [str(value) for value in row]
                for row in df.itertuples(index=False, name=None)
            ]
            cells = []
            for cell in item.data.table_cells:
                cell_locations = []
                for location in locations:
                    location = dict(location)
                    if cell.bbox and len(locations) == 1:
                        location["bbox"] = [
                            cell.bbox.l,
                            cell.bbox.t,
                            cell.bbox.r,
                            cell.bbox.b,
                        ]
                        location["coord_origin"] = str(cell.bbox.coord_origin.value)
                    cell_locations.append(location)
                cells.append(
                    {
                        "row": cell.start_row_offset_idx,
                        "column": cell.start_col_offset_idx,
                        "row_span": cell.row_span,
                        "column_span": cell.col_span,
                        "text": cell.text,
                        "column_header": cell.column_header,
                        "row_header": cell.row_header,
                        "source_refs": [source_id],
                        "locations": cell_locations,
                    }
                )
            data = {"headers": headers, "rows": rows, "cells": cells}
            json_path = assets_dir / "tables" / f"{asset_id}.json"
            csv_path = json_path.with_suffix(".csv")
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                if headers:
                    writer.writerow(headers)
                writer.writerows(rows)
            asset = {
                "asset_id": asset_id,
                "type": "table",
                "data": data,
                "file_path": str(json_path),
                "json_path": str(json_path),
                "csv_path": str(csv_path),
            }
            text = "\n".join(
                " | ".join(row) for row in ([headers] if headers else []) + rows
            )
        elif "picture" in item_kind or "image" in item_kind or item_kind == "formula":
            kind = "formula" if item_kind == "formula" else "image"
            asset_id = f"{kind}_{document_id}_block_{counter:04d}.png"
            image_path = (
                assets_dir / ("formulas" if kind == "formula" else "images") / asset_id
            )
            image = item.get_image(doc)
            findings = []
            if image is not None:
                image.save(image_path)
            else:
                findings.append("Docling returned no image pixels for this source item")
            asset = {
                "asset_id": asset_id,
                "type": kind,
                "file_path": str(image_path),
                "width": image.width if image is not None else None,
                "height": image.height if image is not None else None,
                "availability": "AVAILABLE" if image is not None else "MISSING",
                "findings": findings,
            }
            text = text or caption
        text = text.strip()
        if text and not (item_kind in {"caption", *PAGE_FURNITURE_KINDS}
                         and item.self_ref in bound_caption_refs):
            blocks.append(
                {
                    "block_id": block_id,
                    "document_id": document_id,
                    "source_item_id": source_id,
                    "type": item_kind,
                    "text": text,
                    "section": current_section,
                    "locations": locations,
                    "prov": [
                        p.model_dump(mode="json") for p in getattr(item, "prov", [])
                    ],
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
        if asset:
            path = Path(asset["file_path"])
            asset.update(
                {
                    "document_id": document_id,
                    "source_refs": [source_id],
                    "locations": locations,
                    "caption": caption,
                    "caption_binding": caption_binding,
                    "caption_refs": caption_refs,
                    "caption_locations": caption_locations,
                    "section": current_section,
                    "content_sha256": (
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        if path.is_file()
                        else None
                    ),
                }
            )
            asset.setdefault("findings", []).extend(caption_findings)
            if asset["type"] == "image" and not caption:
                asset["findings"].append(
                    "No unambiguous caption reference supplied by Docling"
                )
            assets.append(asset)
            relationships.append(
                {
                    "source": source_id,
                    "relation": "BELONGS_TO_SECTION",
                    "target": current_section,
                }
            )
    structural_ir = {
        "schema_version": "2",
        "document_name": Path(source_path).name,
        "document_id": document_id,
        "source_sha256": source_hash,
        "source_item_ids": source_item_ids,
        "total_blocks": len(blocks),
        "total_assets": len(assets),
        "blocks": blocks,
        "assets": assets,
        "relationships": relationships,
    }
    (Path(output_dir) / "ir.json").write_text(
        json.dumps(structural_ir, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return structural_ir
