"""Explicit Docling configuration; original exporter remains the projection."""
import io
import re
from pathlib import Path
from infrastructure.utils.artifacts import atomic_json
from contracts.ingestion_schema import IngestionError, ParseFinding
from application.jobs.job_context import check
from infrastructure.ingestion.detection import decode_text


def extract(source, output, options, *, context=None, limits=None):
    from infrastructure.ingestion.stage1_docling_parser import run_docling_extraction
    run_docling_extraction(str(source), str(output), use_gpu=options.effective_device == 'cuda', resolved_options=options,
                           context=context, limits=limits)
    import json
    return json.loads(Path(output, 'ir.json').read_text(encoding='utf-8'))


def convert(source, output, options, *, context=None, limits=None):
    from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption, MarkdownFormatOption, ImageFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice, RapidOcrOptions, OcrMode
    from docling.datamodel.backend_options import MarkdownBackendOptions
    from docling.datamodel.document import DocumentStream
    from infrastructure.ingestion.stage1_docling_parser import export_docling_document
    kind = options.resolved_type
    formats = {'pdf': InputFormat.PDF, 'docx': InputFormat.DOCX, 'markdown': InputFormat.MD,
               'png': InputFormat.IMAGE, 'jpeg': InputFormat.IMAGE}
    findings = []
    source_input = Path(source)
    if kind == 'markdown':
        text, _ = decode_text(Path(source).read_bytes(), options.encoding)
        Path(output, 'decoded_source.txt').write_bytes(text.encode('utf-8'))
        source_input = DocumentStream(name='source.md', stream=io.BytesIO(text.encode('utf-8')))
        format_option = MarkdownFormatOption(backend_options=MarkdownBackendOptions(
            enable_remote_fetch=False, enable_local_fetch=False, fetch_images=False))
        if re.search(r'!\[|<img\b', text, re.I):
            findings.append(ParseFinding(code='UNRESOLVED_LINKED_ASSET', message='Linked images are retained as references; external/local fetching is disabled.'))
    elif kind == 'docx':
        format_option = WordFormatOption()
    else:
        pipeline = PdfPipelineOptions()
        pipeline.do_ocr = options.effective_ocr != 'off'
        pipeline.ocr_options = RapidOcrOptions(mode=OcrMode.FULL_PAGE if options.effective_ocr == 'force' else OcrMode.DEFAULT)
        pipeline.do_table_structure = True
        pipeline.generate_page_images = True
        pipeline.generate_picture_images = True
        pipeline.images_scale = 2.0
        pipeline.enable_remote_services = False
        pipeline.do_picture_description = False
        pipeline.do_picture_classification = False
        # Formula-enrichment pilot (PPTAI_FORMULA_ENRICHMENT=true): emits
        # LaTeX text for formulas instead of uncaptioned PNG crops only.
        # Opt-in because it downloads Docling formula models on first use.
        import os as _os
        pipeline.do_formula_enrichment = _os.environ.get('PPTAI_FORMULA_ENRICHMENT', '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if options.configuration.get('artifacts_path'):
            pipeline.artifacts_path = Path(options.configuration['artifacts_path'])
        pipeline.accelerator_options = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CUDA if options.effective_device == 'cuda' else AcceleratorDevice.CPU)
        format_option = (PdfFormatOption if kind == 'pdf' else ImageFormatOption)(pipeline_options=pipeline)
    if kind == 'pdf':
        try:
            from pypdf import PdfReader
            pdf = PdfReader(source)
            if pdf.is_encrypted:
                raise IngestionError('ENCRYPTED_SOURCE', 'Supply an unencrypted PDF.')
            pages = len(pdf.pages)
        except IngestionError:
            raise
        except Exception:
            raise IngestionError('CORRUPT_SOURCE', 'PDF cannot be read; replace the file.') from None
        maximum = getattr(limits, 'max_source_pages', None)
        if maximum and pages > maximum:
            raise IngestionError('SOURCE_PAGE_LIMIT', 'The PDF exceeds the configured page limit.', details={'pages': pages, 'limit': maximum})
    converter = DocumentConverter(allowed_formats=[formats[kind]], format_options={formats[kind]: format_option})
    check(context)
    try:
        result = converter.convert(source_input, raises_on_error=False)
    except Exception as error:
        code = 'OCR_UNAVAILABLE' if options.effective_ocr != 'off' and kind in {'pdf', 'png', 'jpeg'} else 'CORRUPT_SOURCE'
        raise IngestionError(code, 'Conversion failed; inspect the local parser log and configured models.') from error
    check(context)
    status = str(result.status.value)
    atomic_json(Path(output) / 'conversion_diagnostics.json', {'status': status, 'errors': [str(e) for e in result.errors]})
    if status not in {'success', 'partial_success'}:
        raise IngestionError('CORRUPT_SOURCE', 'Docling could not convert this file; replace it or check the configured runtime.')
    ir = export_docling_document(result.document, str(source), str(output))
    ir['schema_version'] = '3'
    ir['parser_version'] = 'docling-ingestion-v3'
    if status == 'partial_success':
        findings.append(ParseFinding(code='PARTIAL_CONVERSION', severity='error', message='Docling processed only part of the source.', blocks_generation=True))
    if kind == 'pdf':
        processed = sorted(result.document.pages)
        ir['page_accounting'] = {'expected': pages, 'processed': processed}
        if processed != list(range(1, pages + 1)):
            findings.append(ParseFinding(code='MISSING_PAGES', severity='error', message='Some PDF pages were not processed.',
                location={'missing_pages': sorted(set(range(1, pages + 1)) - set(processed))}, blocks_generation=True))
    elif hasattr(result.document, 'pages') and result.document.pages:
        ir['page_accounting'] = {'expected': len(result.document.pages), 'processed': sorted(result.document.pages.keys())}
    if kind in {'docx', 'markdown'}:
        # These simple pipelines have item references, not physical page locations.
        for item in [*ir['blocks'], *ir['assets']]:
            for loc in item.get('locations', []) + item.get('caption_locations', []):
                loc.update(page=None, bbox=None, coord_origin=None)
            for cell in item.get('data', {}).get('cells', []):
                for loc in cell.get('locations', []):
                    loc.update(page=None, bbox=None, coord_origin=None)
    ir['findings'] = [f.model_dump(mode='json') for f in findings]
    atomic_json(Path(output) / 'ir.json', ir)
    return ir
