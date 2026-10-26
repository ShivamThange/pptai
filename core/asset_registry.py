"""Shared required-asset gate for composition, compilation, and edits."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Any

from PIL import Image
from contracts.raw_extraction_schema import SourceAsset, TableAssetData


class AssetBindingError(ValueError):
    pass


class AssetRegistry:
    def __init__(
        self,
        assets: Iterable[SourceAsset | dict[str, Any]],
        *,
        run_root: str | Path | None = None,
        source_item_ids: Iterable[str] = (),
        asset_source_items=(),
        min_ppi: float = 150,
    ):
        self.source_item_ids = set(source_item_ids)
        import math
        if not math.isfinite(min_ppi) or min_ppi<=0:
            raise ValueError('Asset minimum PPI must be positive and finite')
        self.min_ppi = min_ppi
        self.assets = {}
        self.asset_source_items = {item.source_id if hasattr(item,'source_id') else item['source_id']: item for item in asset_source_items}
        self.run_root = Path(run_root).resolve() if run_root is not None else None
        for value in assets:
            asset = (
                value
                if isinstance(value, SourceAsset)
                else SourceAsset.model_validate(value)
            )
            if asset.asset_id in self.assets:
                raise AssetBindingError(
                    f"Duplicate registry asset ID: {asset.asset_id}"
                )
            self.assets[asset.asset_id] = asset

    def validate_derivation(self, asset_id):
        from infrastructure.utils.artifacts import file_hash
        from contracts.asset_schema import AssetSourceItem
        asset = self.assets[asset_id]
        visiting = set()
        def visit(aid):
            if aid in visiting or aid not in self.assets:
                raise AssetBindingError('INVALID_ASSET_PROVENANCE: parent cycle/missing parent')
            visiting.add(aid)
            value=self.assets[aid]
            if value.content:
                if value.content.kind != {'image':'figure'}.get(value.kind,value.kind):
                    raise AssetBindingError('INVALID_ASSET_PROVENANCE: content kind mismatch')
                for parent in value.content.parent_asset_ids:
                    visit(parent)
                ids=[r.representation_id for r in value.content.representations]
                if len(ids)!=len(set(ids)):
                    raise AssetBindingError('ASSET_INTEGRITY_ERROR: duplicate representation IDs')
                for rep in value.content.representations:
                    if rep.availability!='available':
                        continue
                    path=Path(rep.path).resolve()
                    if self.run_root and not path.is_relative_to(self.run_root) or not path.is_file() or file_hash(path)!=rep.sha256:
                        raise AssetBindingError('ASSET_INTEGRITY_ERROR: representation missing/changed')
                if value.content.kind=='table':
                    from infrastructure.ingestion.asset_adapters_tables import table_content
                    from infrastructure.ingestion.source_adapter import normalize_table_data
                    import json
                    if normalize_table_data(json.loads(Path(value.file_path).read_text(encoding='utf-8')))!=value.data:
                        raise AssetBindingError('ASSET_INTEGRITY_ERROR: table metadata differs from source bytes')
                    expected=table_content(value,[])
                    if value.content.cells!=expected.cells or (value.content.row_count,value.content.column_count)!=(expected.row_count,expected.column_count):
                        raise AssetBindingError('ASSET_INTEGRITY_ERROR: rich table grid differs from source cells')
                if value.content.kind=='chart':
                    import json
                    bound=json.loads(Path(value.file_path).read_text(encoding='utf-8'))
                    if any(bound.get(k)!=getattr(value.content,k) for k in ('chart_type','categories','series','data_state')):
                        raise AssetBindingError('ASSET_INTEGRITY_ERROR: chart payload differs from source mapping')
            visiting.remove(aid)
        visit(asset_id)
        for ref in asset.source_refs:
            if ':ooxml:' not in ref:
                continue
            value=self.asset_source_items.get(ref)
            if value is None:
                raise AssetBindingError('INVALID_ASSET_PROVENANCE: unresolved original OOXML item')
            item=AssetSourceItem.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
            from infrastructure.utils.artifacts import sha256_value
            part=(item.embedded_package_part+'!' if item.embedded_package_part else '')+item.part
            expected_id=item.document_id+':ooxml:'+part+':'+sha256_value(item.xml_path)[:20]
            if item.document_id!=asset.document_id or item.source_id!=ref or ref!=expected_id or \
               item.document_id.startswith('doc_') and item.document_id!='doc_'+item.package_sha256:
                raise AssetBindingError('INVALID_ASSET_PROVENANCE: forged OOXML document/item identity')
            path=Path(item.package_path).resolve()
            if self.run_root and not path.is_relative_to(self.run_root) or not path.is_file() or file_hash(path)!=item.package_sha256:
                raise AssetBindingError('ASSET_INTEGRITY_ERROR: original package changed')
            from zipfile import ZipFile
            from lxml import etree
            try:
                with ZipFile(path) as package:
                    if item.embedded_package_part:
                        import io
                        embedded=package.read(item.embedded_package_part)
                        if hashlib.sha256(embedded).hexdigest()!=item.embedded_sha256:
                            raise ValueError('Original embedded workbook mismatch')
                        with ZipFile(io.BytesIO(embedded)) as workbook:
                            node_bytes=workbook.read(item.part)
                    else:
                        node_bytes=package.read(item.part)
                    tree=etree.fromstring(node_bytes,parser=etree.XMLParser(resolve_entities=False,no_network=True))
                    namespaces={k:v for node in tree.iter() for k,v in node.nsmap.items() if k}
                    found=tree.getroottree().xpath(item.xml_path,namespaces=namespaces)
                    if len(found)!=1 or hashlib.sha256(etree.tostring(found[0])).hexdigest()!=item.snippet_sha256:
                        raise ValueError('Original XML node mismatch')
                    if item.embedded_sha256 and not item.embedded_package_part:
                        from infrastructure.ingestion.asset_adapters_ooxml import relationships
                        targets=relationships(package,item.part)
                        target=targets.get(item.relationship_chain[-1])
                        if not target or hashlib.sha256(package.read(target)).hexdigest()!=item.embedded_sha256:
                            raise ValueError('Original media relationship mismatch')
            except (KeyError,ValueError,OSError,etree.LxmlError) as error:
                raise AssetBindingError('INVALID_ASSET_PROVENANCE: original OOXML locator mismatch') from error

    def require_representation(self, asset_id, role=None):
        asset=self.assets[asset_id]
        self.require(asset_id,asset.kind)
        if not asset.content:
            raise AssetBindingError('Legacy asset has no typed representations')
        priorities=[role] if role else ['display_png','source_crop','original','chart_data_json','table_json']
        rep=next((r for key in priorities for r in asset.content.representations if r.role==key and r.availability=='available'
                  and (role is not None or asset.kind not in {'image','formula'} or r.media_type in {'image/png','image/jpeg'})),None)
        if not rep:
            raise AssetBindingError('FORMULA_RENDER_UNAVAILABLE' if asset.kind=='formula' else 'Required representation unavailable')
        return rep

    def select_table(self, asset_id, selection=None):
        from infrastructure.ingestion.asset_adapters_tables import select_table
        return select_table(self.require(asset_id,'table'),selection)

    def resolve_chart(self, asset_id, supplied=None):
        from domain.evaluation.chart_binding import resolve_chart
        return resolve_chart(self.require(asset_id,'chart'),supplied)

    def require(self, asset_id: str | None, kind: str) -> SourceAsset:
        if not asset_id or asset_id not in self.assets:
            raise AssetBindingError(f"Unknown {kind} source asset ID: {asset_id}")
        asset = self.assets[asset_id]
        if asset.content:
            self.validate_derivation(asset_id)
        if asset.kind != kind:
            raise AssetBindingError(
                f"Wrong-kind asset {asset_id}: expected {kind}, got {asset.kind}"
            )
        if not asset.document_id or not asset.source_refs or not asset.locations:
            raise AssetBindingError(
                f"Asset {asset_id} has no verified source membership; re-extract legacy input"
            )
        if not set([*asset.source_refs, *asset.caption_refs]).issubset(
            self.source_item_ids
        ):
            raise AssetBindingError(
                f"Asset {asset_id} references items outside the source document catalog; re-extract if unavailable"
            )
        if any(
            not ref.startswith(f"{asset.document_id}:") for ref in asset.source_refs
        ):
            raise AssetBindingError(
                f"Asset {asset_id} contains cross-document source references"
            )
        if any(
            location.document_id != asset.document_id
            or location.source_id not in asset.source_refs
            for location in asset.locations
        ):
            raise AssetBindingError(
                f"Asset {asset_id} has inconsistent source locations"
            )
        if set(asset.source_refs) != {
            location.source_id for location in asset.locations
        }:
            raise AssetBindingError(
                f"Asset {asset_id} has unresolved source references"
            )
        if any(
            not ref.startswith(f"{asset.document_id}:") for ref in asset.caption_refs
        ):
            raise AssetBindingError(
                f"Asset {asset_id} contains cross-document captions"
            )
        if set(asset.caption_refs) != {
            location.source_id for location in asset.caption_locations
        } or any(
            location.document_id != asset.document_id
            for location in asset.caption_locations
        ):
            raise AssetBindingError(
                f"Asset {asset_id} has unresolved caption references"
            )
        if asset.availability != "AVAILABLE" or not asset.file_path:
            raise AssetBindingError(
                f"Required asset {asset_id} is unavailable: {'; '.join(asset.findings)}"
            )
        path = Path(asset.file_path).resolve()
        if self.run_root is not None and not path.is_relative_to(self.run_root):
            raise AssetBindingError(
                f"Asset {asset_id} resolves outside the active run: {path}"
            )
        if not path.is_file():
            raise AssetBindingError(
                f"Required asset {asset_id} file is missing: {path}"
            )
        if (
            not asset.content_sha256
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset.content_sha256
        ):
            raise AssetBindingError(
                f"Asset {asset_id} hash mismatch or absent evidence hash"
            )
        if kind == "table":
            data = TableAssetData.model_validate(asset.data)
            width = len(data.headers) or max((len(row) for row in data.rows), default=0)
            if (
                not width
                or not data.rows
                or any(len(row) != width for row in data.rows)
            ):
                raise AssetBindingError(
                    f"Required table {asset_id} contains invalid data"
                )
            if not data.cells:
                raise AssetBindingError(
                    f"Table {asset_id} lacks source-cell references; re-extract legacy input"
                )
            import json
            from infrastructure.ingestion.source_adapter import normalize_table_data

            try:
                file_data = normalize_table_data(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError) as error:
                raise AssetBindingError(
                    f"Required table {asset_id} cannot be loaded: {error}"
                ) from error
            if file_data != data.model_dump(mode="json"):
                raise AssetBindingError(
                    f"Table {asset_id} registry data differs from the hashed source file"
                )
            for cell in data.cells:
                if (
                    not cell.source_refs
                    or not set(cell.source_refs).issubset(asset.source_refs)
                    or not cell.locations
                ):
                    raise AssetBindingError(
                        f"Table {asset_id} has unresolved source cells"
                    )
                if any(
                    location.document_id != asset.document_id
                    or location.source_id not in cell.source_refs
                    for location in cell.locations
                ):
                    raise AssetBindingError(
                        f"Table {asset_id} has cross-document source cells"
                    )
        elif not asset.content or kind == 'image':
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, ValueError) as error:
                raise AssetBindingError(
                    f"Asset {asset_id} is not a usable image: {error}"
                ) from error
        return asset


def validate_asset_content(
    content: dict[str, Any], registry: AssetRegistry
) -> SourceAsset | None:
    kind = content.get("type")
    if kind not in {"image", "table", "formula", "chart"}:
        return None
    asset_id = content.get("source_asset_id")
    if kind=='chart':
        if not asset_id:
            if any(a.content is not None for a in registry.assets.values()):
                raise AssetBindingError('CHART_DATA_UNVERIFIED: structured charts require a source ID')
            return None
        asset=registry.require(asset_id,'chart')
        registry.resolve_chart(asset_id,content)
        return asset
    # Native tables may be composed from retrieved text facts without a source
    # table. When an asset ID is supplied, its binding is always mandatory.
    if kind == "table" and not asset_id:
        if not content.get("rows"):
            raise AssetBindingError(
                "Table needs source_asset_id or nonempty inline data"
            )
        return None
    asset = registry.require(asset_id, kind)
    if kind in {'image','formula'} and asset.content:
        registry.require_representation(asset_id)
    if kind=='table':
        expected=registry.select_table(asset_id,content.get('selection'))
        if 'merges' in content and [tuple(v) for v in content['merges']]!=expected['merges']:
            raise AssetBindingError('TABLE_SELECTION_INVALID: native merge override differs from source')
    if (
        content.get("path")
        and Path(content["path"]).resolve() != Path(asset.file_path).resolve()
    ):
        raise AssetBindingError(
            f"Asset {asset_id} path override does not match the run registry"
        )
    if kind == "table" and (content.get("headers") or content.get("rows")):
        selected = registry.select_table(asset_id,content.get('selection'))
        expected_headers = [str(value) for value in selected['headers']]
        expected_rows = [[str(value) for value in row] for row in selected['rows']]
        if (
            content.get("headers", []) != expected_headers
            or content.get("rows", []) != expected_rows
        ):
            raise AssetBindingError(
                f"Table {asset_id} inline values differ from source data"
            )
    return asset
