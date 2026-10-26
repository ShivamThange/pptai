import csv
import hashlib
from pathlib import Path
from core.artifacts import atomic_json, file_hash


def base(source):
    digest = file_hash(source)
    return {'schema_version': '3', 'document_name': Path(source).name,
            'document_id': 'doc_' + digest, 'source_sha256': digest,
            'source_item_ids': [], 'blocks': [], 'assets': [], 'relationships': [], 'findings': []}


def block(ir, source_id, text, location, *, section='Root', kind='text'):
    if not text.strip():
        return
    ir['blocks'].append({'block_id': source_id, 'document_id': ir['document_id'],
                         'source_item_id': source_id, 'type': kind, 'text': text,
                         'section': section, 'locations': [location],
                         'content_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()})


def table(ir, output, identity, data, *, section='Root'):
    if not data['rows'] or not any(any(str(v).strip() for v in row) for row in data['rows']):
        return
    path = Path(output) / 'assets' / 'tables' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    atomic_json(path, data)
    csv_path = path.with_suffix('.csv')
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        if data['headers']:
            writer.writerow(data['headers'])
        writer.writerows(data['rows'])
    refs = list(dict.fromkeys(ref for cell in data['cells'] for ref in cell['source_refs']))
    locations = [loc for cell in data['cells'] for loc in cell['locations']]
    ir['assets'].append({'asset_id': identity, 'type': 'table', 'document_id': ir['document_id'],
                         'section': section, 'data': data, 'file_path': str(path), 'json_path': str(path),
                         'csv_path': str(csv_path), 'csv_sha256': file_hash(csv_path), 'source_refs': refs,
                         'locations': locations, 'content_sha256': file_hash(path), 'caption': None})


def finish(ir, output, raw):
    ir['total_blocks'], ir['total_assets'] = len(ir['blocks']), len(ir['assets'])
    atomic_json(Path(output) / 'adapter_raw.json', raw)
    atomic_json(Path(output) / 'ir.json', ir)
    return ir
