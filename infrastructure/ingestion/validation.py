"""Shared typed ingestion validation: identity, retention and all asset hashes."""
import json
import hashlib
from pathlib import Path
from infrastructure.utils.artifacts import file_hash
from infrastructure.ingestion.source_adapter import adapt_structural_ir
from contracts.ingestion_schema import IngestionError


def validate_ingestion(path, *, require_complete=True):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    raw = adapt_structural_ir(data, base_dir=path.parent)
    if str(data.get('schema_version')) != '3':
        return raw  # Historical readers keep their original coverage meaning.
    documents = {d.document_id: d for d in raw.documents}
    if not documents:
        raise IngestionError('INVALID_SOURCE_REGISTRY', 'Source registry is missing.')
    if len(documents) != len(raw.documents) or any(d.document_id != 'doc_' + d.source_sha256 for d in raw.documents):
        raise IngestionError('INVALID_SOURCE_REGISTRY', 'Document identity must bind the original byte hash.')
    if data.get('collection_id'):
        manifest_path = Path(data['source_manifest_path'])
        if file_hash(manifest_path) != data['source_manifest_sha256']:
            raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Collection source manifest changed.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if [m['document']['document_id'] for m in manifest['members']] != [d.document_id for d in raw.documents]:
            raise IngestionError('INVALID_SOURCE_REGISTRY', 'Collection membership differs from its manifest.')
        for member in manifest['members']:
            directory = Path(member['parse_directory']).resolve()
            if file_hash(directory / 'source_snapshot.bin') != member['document']['source_sha256'] or file_hash(directory / 'parse_record.json') != member['parse_record_sha256']:
                raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Collection source bytes or parser record changed.')
            for name, digest in member['artifacts'].items():
                target = (directory / name).resolve()
                if not target.is_relative_to(directory) or not target.is_file() or file_hash(target) != digest:
                    raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Collection parser evidence is missing or changed.')
    elif file_hash(path.parent / 'source_snapshot.bin') != raw.documents[0].source_sha256:
        raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Retained source bytes changed.')
    catalog = set(raw.source_item_ids)
    if len(catalog) != len(raw.source_item_ids):
        raise IngestionError('INVALID_SOURCE_REGISTRY', 'Source catalog has duplicate IDs.')
    if any(not any(ref.startswith(d + ':') for d in documents) for ref in catalog):
        raise IngestionError('INVALID_SOURCE_REGISTRY', 'Catalog includes a foreign document.')
    for item in [*raw.blocks, *raw.assets]:
        if item.document_id not in documents:
            raise IngestionError('INVALID_SOURCE_REGISTRY', 'Item belongs to an unknown document.')
        refs = [item.source_item_id] if hasattr(item, 'source_item_id') else item.source_refs
        if hasattr(item, 'text') and item.content_sha256 != hashlib.sha256(item.text.encode('utf-8')).hexdigest():
            raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Retained block text changed.')
        if not refs or not set(refs).issubset(catalog) or any(not r.startswith(item.document_id + ':') for r in refs):
            raise IngestionError('INVALID_SOURCE_REGISTRY', 'Item references a foreign or absent source.')
        for loc in item.locations:
            if loc.document_id != item.document_id or loc.source_id not in refs:
                raise IngestionError('INVALID_SOURCE_REGISTRY', 'Item location belongs to a different source.')
        if hasattr(item, 'data') and item.kind == 'table' and item.data:
            for cell in item.data['cells']:
                if not cell['source_refs'] or not set(cell['source_refs']).issubset(catalog):
                    raise IngestionError('INVALID_SOURCE_REGISTRY', 'Table cell references an absent source.')
                if any(not r.startswith(item.document_id + ':') for r in cell['source_refs']) or any(
                    loc['document_id'] != item.document_id or loc['source_id'] not in cell['source_refs'] for loc in cell['locations']):
                    raise IngestionError('INVALID_SOURCE_REGISTRY', 'Table cell has foreign provenance.')
                if cell.get('formula') and cell.get('cached_state') == 'unknown' and cell['text']:
                    raise IngestionError('FORMULA_VALUE_UNKNOWN', 'Uncomputed formula cannot be evidence.')
    for asset in data.get('assets', []):
        for field, hash_field in [('file_path', 'content_sha256'), ('json_path', 'content_sha256'), ('csv_path', 'csv_sha256')]:
            if not asset.get(field) or asset.get('availability') == 'MISSING':
                continue
            target = Path(asset[field])
            if not target.is_absolute():
                target = path.parent / target
            if not target.is_file() or (asset.get(hash_field) and file_hash(target) != asset[hash_field]):
                raise IngestionError('ASSET_INTEGRITY_ERROR', 'A retained asset is missing or changed.')
    if require_complete and (any(d.completeness != 'complete' for d in raw.documents) or
            any(f.get('blocks_generation') for f in data.get('findings', []) if isinstance(f, dict))):
        raise IngestionError('SOURCE_SET_INCOMPLETE', 'All selected sources must be complete before generation.')
    return raw
