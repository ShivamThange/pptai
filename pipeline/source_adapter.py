"""Versioned adapters for structural IR; never infer missing evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from core.artifacts import write_validated_json, atomic_json
from schemas.raw_extraction_schema import (
    RawExtraction,
    SourceAsset,
    SourceBlock,
    SourceLocation,
    TableAssetData,
)


# Values SourceAsset.caption_binding legitimately accepts; derived from the
# schema so the adapter can never disagree with the model again.
_CAPTION_BINDINGS = get_args(SourceAsset.model_fields["caption_binding"].annotation)


def normalize_table_data(value: Any) -> dict[str, Any]:
    """Accept the two historical table shapes, retaining values and cell metadata."""
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        headers = list(dict.fromkeys(key for row in value for key in row))
        value = {
            "headers": headers,
            "rows": [[row.get(header, "") for header in headers] for row in value],
        }
    if not isinstance(value, dict) or "rows" not in value:
        raise ValueError(
            "Table asset must contain headers/rows/cells or legacy record rows"
        )
    data = TableAssetData.model_validate(value)
    width = len(data.headers) or max((len(row) for row in data.rows), default=0)
    if not width or not data.rows or any(len(row) != width for row in data.rows):
        raise ValueError("Table asset has empty or inconsistent row dimensions")
    return data.model_dump(mode="json")


def _resolve_file(value: str | None, base_dir: Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    # Legacy exports included output_dir in the relative path. This explicit
    # v1 path migration is confined to the artifact directory and its parent.
    candidates = [base_dir / path, base_dir.parent / path] if base_dir else [path]
    return next(
        (candidate.resolve() for candidate in candidates if candidate.is_file()),
        candidates[0].resolve(),
    )


def _prov_locations(
    item: dict[str, Any], document_id: str, source_id: str
) -> list[SourceLocation]:
    result = []
    for prov in item.get("prov", []):
        if not isinstance(prov, dict):
            continue
        bbox = prov.get("bbox")
        values = (
            [bbox.get(key) for key in ("l", "t", "r", "b")]
            if isinstance(bbox, dict)
            else None
        )
        result.append(
            SourceLocation(
                document_id=document_id,
                source_id=source_id,
                page=prov.get("page_no") or prov.get("page"),
                bbox=(
                    values
                    if values and all(isinstance(v, (int, float)) for v in values)
                    else None
                ),
                coord_origin=(
                    bbox.get("coord_origin") if isinstance(bbox, dict) else None
                ),
                charspan=prov.get("charspan"),
            )
        )
    return result


def _locations(
    item: dict[str, Any], document_id: str, source_id: str
) -> list[SourceLocation]:
    if item.get("locations"):
        return [
            SourceLocation.model_validate(location) for location in item["locations"]
        ]
    return _prov_locations(item, document_id, source_id)


def _safe_locations(
    item: dict[str, Any], document_id: str, source_id: str
) -> tuple[list[SourceLocation], int]:
    """Validate location entries individually; one bad entry drops only itself.

    Extraction output is external evidence. A single malformed location must
    degrade to a recorded gap instead of rejecting the whole document.
    Returns the kept locations plus how many entries were discarded.
    """
    entries = item.get("locations")
    if not entries:
        return _prov_locations(item, document_id, source_id), 0
    kept, dropped = [], 0
    for entry in entries:
        try:
            kept.append(SourceLocation.model_validate(entry))
        except ValidationError:
            dropped += 1
    if not kept:
        return _prov_locations(item, document_id, source_id), dropped
    return kept, dropped


def _safe_location_entries(entries: Any) -> tuple[list[SourceLocation], int]:
    """Per-entry validation for caption_locations-shaped lists."""
    if not isinstance(entries, list):
        return [], 0
    kept, dropped = [], 0
    for entry in entries:
        try:
            kept.append(SourceLocation.model_validate(entry))
        except ValidationError:
            dropped += 1
    return kept, dropped


def _safe_dimension(value: Any) -> int | None:
    """Asset dimensions are optional positive integers; anything else is unknown."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
        or not float(value).is_integer()
    ):
        return None
    return int(value)


def adapt_structural_ir(
    structural_ir: dict[str, Any],
    *,
    strict_assets: bool = True,
    base_dir: str | Path | None = None,
) -> RawExtraction:
    version = str(structural_ir.get("schema_version", "1"))
    if version not in {"1", "2", "3"}:
        raise ValueError(f"Unsupported structural IR version: {version}")
    artifact_hash = hashlib.sha256(
        json.dumps(structural_ir, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    document_id = str(
        structural_ir.get("document_id") or f"legacy_{artifact_hash}"
    )
    base = Path(base_dir).resolve() if base_dir else None

    def scoped(value):
        value = str(value)
        return (
            value if version == "3" or value.startswith(f"{document_id}:") else f"{document_id}:{value}"
        )

    def section(item, member_id):
        name = str(item.get('section') or 'Root')
        return [f'{member_id} / {name}'] if structural_ir.get('collection_id') else [name]

    blocks, assets, findings = [], [], []
    if version == "1":
        findings.append(
            "legacy-v1 adapter: document namespace is the artifact hash; source bytes and missing asset provenance are unknown"
        )
    seen = set()
    for item in structural_ir.get("blocks", []):
        if not item.get("block_id") or not str(item.get("text", "")).strip():
            continue
        block_id = scoped(item["block_id"])
        if block_id in seen:
            raise ValueError(f"Duplicate source block ID: {block_id}")
        seen.add(block_id)
        try:
            source_id = scoped(item.get("source_item_id") or item["block_id"])
            member_id = str(item.get("document_id") or document_id)
            locations, dropped_locations = _safe_locations(item, member_id, source_id)
            if dropped_locations:
                findings.append(
                    f"Block {block_id}: dropped {dropped_locations} invalid "
                    "location entries"
                )
            first = next((location for location in locations if location.page), None)
            text = str(item["text"]) if version == "3" else str(item["text"]).strip()
            claimed_hash = item.get("content_sha256")
            if not isinstance(claimed_hash, str):
                claimed_hash = None
            blocks.append(
                SourceBlock(
                    block_id=block_id,
                    document_id=member_id,
                    source_item_id=source_id,
                    kind=str(item.get("type") or "text"),
                    text=text,
                    section_path=section(item, member_id),
                    page=first.page if first else None,
                    bbox=first.bbox if first else None,
                    locations=locations,
                    content_sha256=claimed_hash
                    or hashlib.sha256(text.encode()).hexdigest(),
                )
            )
        except (ValidationError, ValueError, TypeError) as error:
            # One unusable block must not stall ingestion of the whole document;
            # the gap is recorded so QC can see what was lost.
            findings.append(
                f"Block {block_id} skipped: unusable block payload ({error})"
            )
            continue
    seen = set()
    for item in structural_ir.get("assets", []):
        kind = str(item.get("type") or "").lower().replace("diagram", "image")
        if not item.get("asset_id") or kind not in {"image", "table", "formula", "chart"}:
            continue
        asset_id = scoped(item["asset_id"])
        if asset_id in seen:
            raise ValueError(f"Duplicate source asset ID: {asset_id}")
        seen.add(asset_id)
        raw_findings = item.get("findings")
        if isinstance(raw_findings, (list, tuple)):
            asset_findings = [str(finding) for finding in raw_findings]
        else:
            asset_findings = []
            if raw_findings:
                findings.append(
                    f"Asset {asset_id}: malformed findings list discarded"
                )
        try:
            refs = [scoped(ref) for ref in item.get("source_refs", [])]
        except (TypeError, ValueError) as error:
            refs = []
            asset_findings.append(
                f"Unusable source references replaced with none: {error}"
            )
        member_id = str(item.get("document_id") or document_id)
        locations, dropped_locations = _safe_locations(
            item, member_id, refs[0] if refs else ""
        )
        if dropped_locations:
            asset_findings.append(
                f"Dropped {dropped_locations} invalid location entries"
            )
        raw_path = item.get("file_path") or item.get("json_path") or item.get("csv_path")
        if raw_path and not isinstance(raw_path, (str, Path)):
            asset_findings.append(f"Unusable asset path {raw_path!r} discarded")
            raw_path = None
        path = _resolve_file(raw_path, base)
        if not refs or not locations:
            asset_findings.append(
                "Asset source provenance unavailable; re-extract before required use"
            )
        data = None
        if kind == "table":
            try:
                value = item.get("data")
                if value is None:
                    json_path = _resolve_file(item.get("json_path"), base)
                    if json_path and json_path.is_file():
                        value = json.loads(json_path.read_text(encoding="utf-8"))
                data = normalize_table_data(value)
            except (OSError, ValueError, TypeError) as error:
                asset_findings.append(f"Table data unavailable: {error}")
        elif kind == "chart":
            data = item.get("data")
            if data is None and item.get("json_path"):
                json_path = _resolve_file(item.get("json_path"), base)
                if json_path and json_path.is_file():
                    try:
                        data = json.loads(json_path.read_text(encoding="utf-8"))
                    except Exception as error:
                        asset_findings.append(f"Chart data unavailable: {error}")
            if data is not None and not isinstance(data, dict):
                asset_findings.append(
                    "Chart data is not a JSON object; discarded"
                )
                data = None
        exists = bool(path and path.is_file())
        if (
            strict_assets
            and path
            and not exists
            and item.get("availability") != "MISSING"
        ):
            # Retained-evidence integrity stays fatal: a claimed asset that is
            # absent is corruption, not a small extraction quirk.
            raise FileNotFoundError(f"Structural IR references missing asset: {path}")
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
        if item.get("content_sha256") and content_hash != item["content_sha256"]:
            # Provenance hash mismatch is deliberate tamper evidence; never soft.
            raise ValueError(f"Asset hash mismatch: {asset_id}")
        first = next((location for location in locations if location.page), None)
        caption = item.get("caption")
        if caption is not None and not isinstance(caption, str):
            asset_findings.append(f"Unusable caption payload {caption!r} discarded")
            caption = None
        elif isinstance(caption, str):
            caption = caption.strip() or None
        caption_binding = item.get("caption_binding", "UNKNOWN")
        if caption_binding not in _CAPTION_BINDINGS:
            asset_findings.append(
                f"Unknown caption binding {caption_binding!r} recorded as UNKNOWN"
            )
            caption_binding = "UNKNOWN"
        caption_locations, dropped_caption_locations = _safe_location_entries(
            item.get("caption_locations")
        )
        if dropped_caption_locations:
            asset_findings.append(
                f"Dropped {dropped_caption_locations} invalid caption location entries"
            )
        try:
            caption_refs = [scoped(ref) for ref in item.get("caption_refs", [])]
        except (TypeError, ValueError) as error:
            caption_refs = []
            asset_findings.append(
                f"Unusable caption references replaced with none: {error}"
            )
        try:
            assets.append(
                SourceAsset(
                    asset_id=asset_id,
                    document_id=member_id,
                    kind=kind,
                    section_path=section(item, member_id),
                    page=first.page if first else None,
                    file_path=str(path) if path else None,
                    data=data,
                    caption=caption,
                    source_refs=refs,
                    locations=locations,
                    caption_binding=caption_binding,
                    caption_refs=caption_refs,
                    caption_locations=caption_locations,
                    content_sha256=content_hash,
                    width=_safe_dimension(item.get("width")),
                    height=_safe_dimension(item.get("height")),
                    availability=(
                        "AVAILABLE" if exists and (kind != "table" or data) else "MISSING"
                    ),
                    findings=asset_findings,
                )
            )
        except (ValidationError, ValueError, TypeError) as error:
            # Last resort: a single unusable asset is a recorded gap, never a
            # whole-document rejection.
            findings.append(
                f"Asset {asset_id} skipped: unusable asset payload ({error})"
            )
            continue
    return RawExtraction(
        schema_version="3" if version == "3" else "2",
        documents=structural_ir.get("documents", []),
        collection_id=structural_ir.get("collection_id"),
        document_name=str(structural_ir.get("document_name") or "document"),
        document_id=None if structural_ir.get("collection_id") else document_id,
        source_sha256=structural_ir.get("source_sha256"),
        source_item_ids=(
            [scoped(ref) for ref in structural_ir.get("source_item_ids", [])]
            if version in {"2", "3"}
            else [block.source_item_id for block in blocks]
        ),
        adapter_version=f"structural-v{version}-to-raw-v2",
        findings=findings,
        blocks=blocks,
        assets=assets,
    )


def build_raw_extraction(
    ir_path: str | Path, output_dir: str | Path, *, strict_assets: bool = True
) -> RawExtraction:
    source = Path(ir_path).resolve()
    raw = adapt_structural_ir(
        json.loads(source.read_text(encoding="utf-8")),
        strict_assets=strict_assets,
        base_dir=source.parent,
    )
    target = Path(output_dir).resolve()
    # Registry identity is data, never a filesystem path component.
    document_directory = hashlib.sha256((raw.document_id or raw.collection_id).encode()).hexdigest()
    for asset in raw.assets:
        if asset.file_path and Path(asset.file_path).is_file():
            original = Path(asset.file_path)
            filename = (
                hashlib.sha256(asset.asset_id.encode()).hexdigest()[:16]
                + "-"
                + original.name
            )
            destination = target / "assets" / document_directory / asset.kind / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if original.resolve() != destination.resolve():
                shutil.copy2(original, destination)
            asset.file_path = str(destination)
    if raw.collection_id:
        payload = raw.model_dump(mode='json')
        RawExtraction.model_validate(payload)
        atomic_json(target / 'raw_extraction.json', payload)
    else:
        write_validated_json(target / "raw_extraction.json", raw)
    return raw
