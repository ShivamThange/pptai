import shutil
from pathlib import Path
from PIL import Image
from core.artifacts import atomic_json, file_hash
from .docling import extract as docling_extract


def extract(source, output, options, *, context=None, limits=None):
    # Full decoding is worker work. Original orientation is preserved.
    with Image.open(source) as image:
        image.load()
        width, height = image.size
        orientation = image.getexif().get(274, 1)
    original = Path(output) / 'assets' / ('original.png' if options.resolved_type == 'png' else 'original.jpg')
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, original)
    ir = docling_extract(source, output, options, context=context, limits=limits)
    ref = ir['document_id'] + ':image:original'
    ir['source_item_ids'].append(ref)
    ir['assets'].append({'asset_id': ref, 'document_id': ir['document_id'], 'type': 'image',
                         'section': 'Root', 'file_path': str(original), 'content_sha256': file_hash(original),
                         'width': width, 'height': height, 'source_refs': [ref],
                         'locations': [{'kind': 'image', 'document_id': ir['document_id'], 'source_id': ref,
                                        'bbox': [0, 0, width, height], 'coord_origin': 'TOPLEFT', 'geometry_unit': 'pixel'}]})
    import json
    document = json.loads(Path(output, 'docling_document.json').read_text(encoding='utf-8'))
    transforms = {}
    for page_no, page in document.get('pages', {}).items():
        size = page.get('size') or {}
        if size.get('width') and size.get('height'):
            transforms[page_no] = {'unit': 'point', 'original_unit': 'pixel',
                'scale_x': width / size['width'], 'scale_y': height / size['height'],
                'source_orientation_applied': False, 'coord_origin': 'retain each item origin'}
    atomic_json(Path(output) / 'adapter_raw.json', {'width': width, 'height': height, 'exif_orientation': orientation,
        'original_sha256': file_hash(original), 'ocr_page_to_original': transforms,
        'preprocessing': 'Installed Docling image backend converts RGB without EXIF rotation; original pixels retained'})
    atomic_json(Path(output) / 'ir.json', ir)
    return ir
