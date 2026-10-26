"""Lightweight signature validation. No converters, OCR or providers at intake."""
import codecs
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
from schemas.ingestion_schema import IngestionError, ParseFinding

EXTENSIONS = {'.pdf': 'pdf', '.docx': 'docx', '.txt': 'txt', '.md': 'markdown',
              '.markdown': 'markdown', '.csv': 'csv', '.xlsx': 'xlsx', '.png': 'png',
              '.jpg': 'jpeg', '.jpeg': 'jpeg'}
TEXT_TYPES = {'txt', 'markdown', 'csv'}
CONTENT_TYPES = {
    'docx': ('word/document.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
    'xlsx': ('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'),
}


def decode_text(data, encoding='auto'):
    if encoding == 'auto':
        encoding = ('utf-8-sig' if data.startswith(codecs.BOM_UTF8) else
                    'utf-16' if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8')
    try:
        canonical = codecs.lookup(encoding).name
        text = data.decode(encoding, errors='strict')
    except (LookupError, UnicodeError):
        raise IngestionError('TEXT_ENCODING_REQUIRED', 'Choose a valid text encoding and retry; original bytes were not decoded.') from None
    if any(ord(ch) < 32 and ch not in '\t\n\r\f' for ch in text):
        raise IngestionError('CORRUPT_SOURCE', 'Binary control characters are not supported text.')
    return text, canonical


def detect(path, *, filename=None, selected_type='auto', encoding='auto'):
    path = Path(path)
    extension = Path(filename or path.name).suffix.lower()
    if extension not in EXTENSIONS:
        raise IngestionError('UNSUPPORTED_TYPE', 'Choose PDF, DOCX, TXT, Markdown, CSV, XLSX, PNG or JPEG.', status=415)
    if selected_type not in {'auto', *EXTENSIONS.values()}:
        raise IngestionError('INVALID_PARSE_OPTIONS', 'Choose a supported input type or Auto.')
    if not path.stat().st_size:
        raise IngestionError('EMPTY_UPLOAD', 'The file is empty.')
    with path.open('rb') as stream:
        header = stream.read(1024)
    kind, basis = None, 'extension and strict text decoding'
    if header.startswith(b'%PDF-'):
        kind, basis = 'pdf', 'PDF signature'
    elif header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff'):
        kind = 'png' if header.startswith(b'\x89PNG') else 'jpeg'
        basis = 'image signature and verification'
        try:
            from PIL import Image
            with Image.open(path) as image:
                if image.format != ('PNG' if kind == 'png' else 'JPEG'):
                    raise ValueError()
                image.verify()
        except Exception:
            raise IngestionError('CORRUPT_SOURCE', 'The image cannot be verified; replace the file.') from None
    elif header.startswith(b'PK'):
        basis = 'OOXML package and main-part content type'
        try:
            with ZipFile(path) as package:
                info = package.getinfo('[Content_Types].xml')
                if info.file_size > 1024 * 1024:
                    raise ValueError()
                types = ET.fromstring(package.read(info))
                for candidate, (main, mime) in CONTENT_TYPES.items():
                    if main in package.namelist() and any(
                        node.get('PartName') == '/' + main and node.get('ContentType') == mime for node in types):
                        kind = candidate
                        break
                if not kind:
                    raise ValueError()
        except (BadZipFile, KeyError, ValueError, ET.ParseError, RuntimeError):
            raise IngestionError('CORRUPT_SOURCE', 'Expected a valid DOCX or XLSX OOXML package.') from None
    expected = EXTENSIONS[extension]
    findings, text_encoding = [], None
    if kind is not None:
        if expected != kind or selected_type not in {'auto', kind}:
            raise IngestionError('TYPE_MISMATCH', f'The bytes are {kind.upper()}; use its extension and select {kind.upper()} or Auto.',
                                 details={'detected_type': kind, 'correction': f'Rename to {next(e for e,t in EXTENSIONS.items() if t == kind)} and select {kind} or auto.'})
    else:
        if expected not in TEXT_TYPES:
            raise IngestionError('CORRUPT_SOURCE', f'The file lacks the expected {expected.upper()} signature.')
        _, text_encoding = decode_text(path.read_bytes(), encoding)
        kind = expected
        if selected_type != 'auto':
            if selected_type not in TEXT_TYPES:
                raise IngestionError('TYPE_MISMATCH', 'This is text; choose TXT, Markdown, CSV or Auto.', details={'detected_type': kind})
            if selected_type != expected:
                findings.append(ParseFinding(code='TEXT_TYPE_OVERRIDE', severity='info', message='Explicit selection resolves the text format.'))
    return {'detected_type': kind, 'selected_type': selected_type,
            'resolved_type': selected_type if kind in TEXT_TYPES and selected_type != 'auto' else kind,
            'detection_basis': basis, 'text_encoding': text_encoding, 'findings': findings}
