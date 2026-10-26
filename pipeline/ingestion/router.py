"""Resolve effective options before cache lookup; dispatch only Q05 adapters."""
import importlib.metadata as metadata
import os
from pathlib import Path
from infrastructure.utils.artifacts import file_hash
from infrastructure.ingestion.detection import detect, decode_text
from contracts.ingestion_schema import ParseOptions, ResolvedParseOptions, IngestionError, ParseFinding


def package_versions(names):
    result = {}
    for name in names:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = 'unavailable'
    return result


def model_identity():
    """Bind local weights used by the configured PDF/RapidOCR pipelines."""
    roots = [Path(os.environ.get('PPTAI_DOCLING_MODEL_DIR', Path.home() / '.cache' / 'huggingface' / 'hub'))]
    try:
        dist = metadata.distribution('rapidocr')
        roots += [Path(dist.locate_file('rapidocr/models'))]
    except metadata.PackageNotFoundError:
        pass
    models = {}
    for root in roots:
        if root.is_dir():
            for path in root.rglob('*'):
                if path.is_file() and path.suffix in {'.onnx', '.safetensors', '.bin', '.yaml'} and (
                        'docling' in str(path).lower() or 'rapidocr' in str(path).lower()):
                    models[str(path)] = file_hash(path)
    return models


def resolve_options(source, *, selected_type='auto', parse_options=None, use_gpu=False, upload_spec=None):
    requested = ParseOptions.model_validate(parse_options or {})
    encoding = requested.encoding
    if encoding == 'auto' and upload_spec:
        encoding = upload_spec.get('text_encoding') or 'auto'
    detection = detect(source, selected_type=selected_type or (upload_spec or {}).get('selected_type', 'auto'), encoding=encoding)
    kind = detection['resolved_type']
    try:
        requested.for_type(kind)
    except ValueError as error:
        raise IngestionError('INVALID_PARSE_OPTIONS', str(error)) from None
    adapter = {'txt': 'text', 'csv': 'csv', 'xlsx': 'xlsx', 'png': 'image', 'jpeg': 'image'}.get(kind, 'docling')
    findings = detection['findings']
    resolved = ResolvedParseOptions(resolved_type=kind, requested=requested, adapter=adapter,
        encoding=detection['text_encoding'], versions=package_versions(['openpyxl'] if kind == 'xlsx' else []))
    if kind == 'csv':
        from infrastructure.ingestion.adapters.csv import delimiter_for
        text, _ = decode_text(Path(source).read_bytes(), resolved.encoding)
        resolved.csv_delimiter = delimiter_for(text) if requested.csv_delimiter == 'auto' else requested.csv_delimiter
        resolved.csv_has_header = requested.csv_has_header
    if kind in {'pdf', 'png', 'jpeg', 'docx', 'markdown'}:
        resolved.versions = package_versions(['docling', 'docling-core', 'Pillow', 'marko', 'python-docx'])
    if kind in {'pdf', 'png', 'jpeg'}:
        resolved.versions.update(package_versions(['rapidocr', 'onnxruntime', 'torch', 'pypdf']))
        resolved.requested_device = 'cuda' if use_gpu else 'cpu'
        resolved.requested_ocr = requested.ocr
        resolved.effective_ocr = requested.ocr
        resolved.table_structure, resolved.image_scale = True, 2.0
        if requested.ocr != 'off':
            resolved.ocr_engine, resolved.ocr_languages = 'rapidocr-onnxruntime', ['chinese']
        if use_gpu:
            try:
                import torch
                resolved.effective_device = 'cuda' if torch.cuda.is_available() else 'cpu'
            except ImportError:
                resolved.effective_device = 'cpu'
            if resolved.effective_device != 'cuda':
                findings.append(ParseFinding(code='CPU_FALLBACK', message='CUDA unavailable; parsing uses CPU.'))
        resolved.models = model_identity()
        resolved.configuration = {'remote_services': False, 'enrichment': False, 'page_images': True, 'picture_images': True}
        if os.environ.get('PPTAI_DOCLING_MODEL_DIR'):
            resolved.configuration['artifacts_path'] = str(Path(os.environ['PPTAI_DOCLING_MODEL_DIR']).resolve())
    return resolved, findings


def extract(source, output, options, *, context=None, limits=None):
    from .adapters import text, csv, xlsx, docling, image
    adapters = {'text': text.extract, 'csv': csv.extract, 'xlsx': xlsx.extract,
                'docling': docling.extract, 'image': image.extract}
    return adapters[options.adapter](source, output, options, context=context, limits=limits)
