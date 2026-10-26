import re
from pathlib import Path
from infrastructure.ingestion.detection import decode_text
from .common import base, block, finish


def extract(source, output, options, *, context=None, limits=None):
    text, _ = decode_text(Path(source).read_bytes(), options.encoding)
    Path(output, 'decoded_source.txt').write_bytes(text.encode('utf-8'))
    ir = base(source)
    offset = 0
    for part in re.split(r'((?:\r?\n)[ \t]*(?:\r?\n))', text):
        start, end = offset, offset + len(part)
        offset = end
        if not part.strip():
            continue
        ref = f"{ir['document_id']}:text:{start}-{end}"
        ir['source_item_ids'].append(ref)
        location = {'kind': 'text_span', 'document_id': ir['document_id'], 'source_id': ref,
                    'charspan': [start, end], 'line_start': text.count('\n', 0, start) + 1,
                    'line_end': text.count('\n', 0, max(start, end - 1)) + 1}
        block(ir, ref, part, location)
    return finish(ir, output, {'text': text, 'character_count': len(text), 'blank_content_retained': True})
