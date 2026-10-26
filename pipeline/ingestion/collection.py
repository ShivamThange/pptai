"""Ordered source collections and reproduction bundles, without another planner."""
import copy
import json
import shutil
from pathlib import Path
from core.artifacts import atomic_json, file_hash, sha256_value, artifact_lock
from schemas.ingestion_schema import IngestionError


def assemble(members, output):
    identities = [(m['result']['document_id'], m['result']['parse_key']) for m in members]
    collection_id = 'collection_' + sha256_value(identities)
    aliases = [{k: m.get(k, []) for k in ('upload_ids', 'aliases')} for m in members]
    # Evidence identity ignores submission aliases; projections preserve them independently.
    root = Path(output).resolve() / '.cache' / 'collections' / collection_id / sha256_value(aliases)
    with artifact_lock(Path(output).resolve() / '.locks' / 'collection.lock'):
        root.mkdir(parents=True, exist_ok=True)
        aggregate = {'schema_version': '3', 'document_name': 'Source collection', 'document_id': None,
            'source_sha256': None, 'collection_id': collection_id, 'documents': [], 'source_item_ids': [],
            'blocks': [], 'assets': [], 'relationships': [], 'findings': []}
        manifest = {'schema_version': 1, 'collection_id': collection_id, 'members': []}
        for member in members:
            path = Path(member['path'])
            data = json.loads(path.read_text(encoding='utf-8'))
            if str(data.get('schema_version')) != '3':
                raise IngestionError('LEGACY_SOURCE_REPARSE_REQUIRED', 'Multi-source generation requires current parser evidence.')
            descriptor = copy.deepcopy(data['documents'][0])
            descriptor['upload_ids'] = member.get('upload_ids', [])
            descriptor['aliases'] = member.get('aliases', [])
            aggregate['documents'].append(descriptor)
            for field in ('source_item_ids', 'blocks', 'assets', 'relationships', 'findings'):
                aggregate[field].extend(data.get(field, []))
            record = json.loads((path.parent / 'parse_record.json').read_text(encoding='utf-8'))
            manifest['members'].append({'document': descriptor, 'parse_directory': str(path.parent),
                'parse_record_sha256': file_hash(path.parent / 'parse_record.json'), 'artifacts': record['artifacts']})
        aggregate['total_blocks'], aggregate['total_assets'] = len(aggregate['blocks']), len(aggregate['assets'])
        atomic_json(root / 'source_manifest.json', manifest)
        aggregate['source_manifest_path'] = str(root / 'source_manifest.json')
        aggregate['source_manifest_sha256'] = file_hash(root / 'source_manifest.json')
        atomic_json(root / 'ir.json', aggregate)
        from .validation import validate_ingestion
        validate_ingestion(root / 'ir.json')
        return root / 'ir.json'


def retain_sources(structural, work):
    """Copy exact parser evidence for every source; projections use separate paths."""
    structural, work = Path(structural), Path(work)
    data = json.loads(structural.read_text(encoding='utf-8'))
    manifest_path = structural.parent / 'source_manifest.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    elif (structural.parent / 'parse_record.json').is_file():
        record = json.loads((structural.parent / 'parse_record.json').read_text(encoding='utf-8'))
        manifest = {'schema_version': 1, 'members': [{'document': (data.get('documents') or [{}])[0],
            'parse_directory': str(structural.parent), 'parse_record_sha256': file_hash(structural.parent / 'parse_record.json'),
            'artifacts': record['artifacts']}]}
    else:
        manifest = {'schema_version': 1, 'members': []}
    for member in manifest['members']:
        origin = Path(member['parse_directory']).resolve()
        if file_hash(origin / 'parse_record.json') != member['parse_record_sha256']:
            raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Pinned parser record changed.')
        directory = work / 'sources' / sha256_value(member['document'].get('document_id') or str(origin))
        directory.mkdir(parents=True, exist_ok=True)
        for name, digest in member['artifacts'].items():
            source = (origin / name).resolve()
            if not source.is_relative_to(origin) or not source.is_file() or file_hash(source) != digest:
                raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Pinned parser evidence changed.')
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        shutil.copyfile(origin / 'parse_record.json', directory / 'parse_record.json')
        member['bundle_directory'] = directory.relative_to(work).as_posix()
    atomic_json(work / 'source_manifest.json', manifest)
    # Legacy single-source snapshots are retained at their historical locations too.
    for name in ('source_snapshot.bin', 'decoded_source.txt', 'adapter_raw.json', 'docling_document.json', 'parse_result.json', 'parse_record.json'):
        if (structural.parent / name).is_file():
            shutil.copyfile(structural.parent / name, work / name)
