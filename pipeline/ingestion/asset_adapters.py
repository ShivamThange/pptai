"""F04 enrichment after F02. Original structural/parser artifacts remain immutable."""
import json
import re
from pathlib import Path
from PIL import Image, ImageOps
from infrastructure.utils.artifacts import atomic_json, file_hash, sha256_value
from application.jobs.job_context import check, report
from contracts.asset_schema import (AssetRepresentation, FigureAssetContent, FormulaAssetContent,
    PixelTransform, AssetFinding, AssetSemanticCoverage)
from contracts.raw_extraction_schema import SourceAsset, SourceLocation, SourceBlock, RawExtraction
from .asset_adapters_tables import table_content


def load_source_bundles(structural_path, run_root):
    root = Path(run_root).resolve()
    manifest = root / 'source_manifest.json'
    if not manifest.is_file():
        return {}
    index = {}
    for member in json.loads(manifest.read_text(encoding='utf-8'))['members']:
        directory = (root / member['bundle_directory']).resolve()
        if not directory.is_relative_to(root):
            raise ValueError('ASSET_INTEGRITY_ERROR: source bundle outside revision')
        record = directory / 'parse_record.json'
        if file_hash(record) != member['parse_record_sha256']:
            raise ValueError('ASSET_INTEGRITY_ERROR: parser record changed')
        for name, digest in member['artifacts'].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or not path.is_file() or file_hash(path) != digest:
                raise ValueError('ASSET_INTEGRITY_ERROR: original evidence changed')
        index[member['document']['document_id']] = directory
    return index


def representation(path, role, media, editability):
    path = Path(path)
    size = {}
    if media.startswith('image/') and media != 'image/svg+xml':
        with Image.open(path) as image:
            size = {'width': image.width, 'height': image.height}
    return AssetRepresentation(representation_id=role, role=role, path=str(path.resolve()), sha256=file_hash(path),
        media_type=media, editability=editability, **size)


def orientation_transform(orientation, w, h):
    matrices = {1:(1,0,0,0,1,0), 2:(-1,0,w,0,1,0), 3:(-1,0,w,0,-1,h), 4:(1,0,0,0,-1,h),
                5:(0,1,0,1,0,0), 6:(0,-1,h,1,0,0), 7:(0,-1,h,-1,0,w), 8:(0,1,0,-1,0,w)}
    return PixelTransform(source_dimensions=(w,h), destination_dimensions=(h,w) if orientation >= 5 else (w,h),
        matrix=(*matrices[orientation],0,0,1), operations=['exif_orientation'])


def _math_spans(raw, root, bundles):
    # Markdown converters split/strip TeX delimiters. Read retained decoded bytes
    # and register exact original spans instead of guessing from projected text.
    for document_id,directory in bundles.items():
        decoded=directory/'decoded_source.txt'
        if not decoded.is_file():
            continue
        text=decoded.read_bytes().decode('utf-8')
        for match in re.finditer(r'\\\[[\s\S]{1,4000}?\\\]|\$\$[\s\S]{1,4000}?\$\$|\\\([^\n]{1,4000}?\\\)',text):
            ref=f'{document_id}:text:{match.start()}-{match.end()}'
            if any(b.block_id==ref for b in raw.blocks):
                continue
            raw.source_item_ids.append(ref)
            raw.blocks.append(SourceBlock(block_id=ref,source_item_id=ref,document_id=document_id,
                section_path=['Root'],text=match.group(),kind='formula_source',content_sha256=sha256_value(match.group()),
                locations=[SourceLocation(document_id=document_id,source_id=ref,kind='text_span',charspan=match.span())]))
    # Only closed display spans or explicit inline TeX delimiters. Dollar currency is untouched.
    for block in raw.blocks:
        for match in re.finditer(r'\\\[(?P<bracket>[\s\S]{1,4000}?)\\\]|\$\$(?P<dollar>[\s\S]{1,4000}?)\$\$|\\\((?P<inline>[^\n]{1,4000}?)\\\)', block.text):
            expression = next(v for v in match.groupdict().values() if v is not None)
            aid = block.block_id + ':derived:' + sha256_value({'span': match.span(), 'expression': expression})[:20]
            if any(a.asset_id == aid for a in raw.assets):
                continue
            path = root / 'assets' / 'math' / (sha256_value(aid) + '.json')
            atomic_json(path, {'expression': expression, 'block_id': block.block_id, 'span': match.span()})
            raw.assets.append(SourceAsset(asset_id=aid, kind='formula', section_path=block.section_path,
                document_id=block.document_id, source_refs=[block.source_item_id], locations=block.locations,
                file_path=str(path), content_sha256=file_hash(path), content=FormulaAssetContent(
                    source_sha256=block.content_sha256 or sha256_value(block.text), expression=expression,
                    expression_refs=[block.block_id], expression_format='latex', transcription_status='SOURCE_LITERAL')))


def enrich_assets(raw, structural_path, run_root, options, *, caller=None, context=None):
    raw = raw.model_copy(deep=True)
    root = Path(run_root).resolve()
    bundles = load_source_bundles(structural_path, root)
    raw.schema_version = '4'
    _math_spans(raw, root, bundles)
    from .asset_adapters_ooxml import supplement_ooxml
    supplement_ooxml(raw, bundles, root, context=context)
    input_hash = sha256_value(raw.model_dump(mode='json'))
    for index, asset in enumerate(raw.assets):
        check(context)
        report(context, 'asset enrichment', index, len(raw.assets))
        if asset.content is not None and asset.content.kind in {'table', 'chart'}:
            continue
        if asset.availability != 'AVAILABLE' or not asset.file_path:
            raw.asset_semantic_coverage.append(AssetSemanticCoverage(asset_id=asset.asset_id, status='unsupported', reason='Source bytes unavailable'))
            continue
        path = Path(asset.file_path)
        if not path.is_relative_to(root) or not path.is_file() or file_hash(path) != asset.content_sha256:
            raise ValueError('ASSET_INTEGRITY_ERROR: original asset changed')
        if asset.kind == 'table':
            asset.content = table_content(asset, [representation(path, 'original', 'application/json', 'native_table')])
        elif asset.kind == 'image':
            with Image.open(path) as image:
                orientation = image.getexif().get(274, 1)
                orientation = orientation if orientation in range(1,9) else 1
                transform = orientation_transform(orientation, image.width, image.height)
                display = root / 'assets' / 'display' / (sha256_value(asset.asset_id) + '.png')
                display.parent.mkdir(parents=True, exist_ok=True)
                ImageOps.exif_transpose(image).convert('RGBA').save(display)
            asset.content = FigureAssetContent(source_sha256=asset.content_sha256, width=asset.width, height=asset.height,
                exif_orientation=orientation, transform=transform, caption_binding=asset.caption_binding,
                representations=[representation(path, 'original', 'image/' + ('jpeg' if path.suffix.lower() in {'.jpg','.jpeg'} else 'png'), 'raster'),
                                 representation(display, 'display_png', 'image/png', 'raster')])
        elif asset.kind == 'formula':
            content = asset.content or FormulaAssetContent(source_sha256=asset.content_sha256)
            if path.suffix.lower() in {'.png','.jpg','.jpeg'}:
                content.representations.append(representation(path, 'source_crop', 'image/png', 'raster'))
            else:
                content.representations.append(representation(path, 'original', 'application/json', 'vector_source'))
            if content.transcription_status == 'SOURCE_LITERAL' and content.expression:
                from domain.rendering.formula_renderer import render_formula
                result = render_formula(content.expression, {'dpi': options.formula_dpi, 'font_size': options.formula_font_size,
                    'timeout': options.formula_timeout}, root / 'assets' / 'math-render', context=context)
                content.render_status = result['status']
                content.render_expression = content.expression if result['status'] == 'RENDERED' else None
                content.representations.extend(AssetRepresentation.model_validate(r) for r in result['representations'])
            asset.content = content
    from domain.evaluation.chart_binding import bind_selected_table
    for mapping in options.chart_mappings:
        table=next((a for a in raw.assets if a.asset_id==mapping.table_asset_id and a.kind=='table'),None)
        if table is None:
            raise ValueError('CHART_REFERENCE_UNRESOLVED: mapping table ID')
        chart=bind_selected_table(table,mapping,root)
        if chart.asset_id in {a.asset_id for a in raw.assets}:
            raise ValueError('Duplicate chart mapping')
        raw.assets.append(chart)
    from infrastructure.ingestion.asset_interpreter import interpret_assets
    interpret_assets(raw, options, root, caller=caller, context=context)
    if options.describe_assets:
        from domain.evaluation.asset_description import describe_asset
        for asset in raw.assets:
            if isinstance(asset.content,FigureAssetContent) and (not options.description_asset_ids or asset.asset_id in options.description_asset_ids):
                asset.content.descriptions=[describe_asset(asset,root,caller,context=context)]
    # Write asset manifest
    asset_manifest = {
        'schema_version': 'asset-manifest-v1',
        'run_root': str(root),
        'total_assets': len(raw.assets),
        'assets': [
            {
                'asset_id': a.asset_id,
                'kind': a.kind,
                'document_id': a.document_id,
                'page': a.page,
                'file_path': a.file_path,
                'content_sha256': a.content_sha256,
                'availability': a.availability,
                'caption': a.caption,
                'caption_binding': a.caption_binding,
            }
            for a in raw.assets
        ],
    }
    atomic_json(root / 'asset_manifest.json', asset_manifest)

    atomic_json(root / 'asset_enrichment.json', {'schema_version': 'asset-enrichment-v1', 'options': options.model_dump(),
        'input_sha256': input_hash, 'output_sha256': sha256_value(raw.model_dump(mode='json')),
        'coverage': [c.model_dump() for c in raw.asset_semantic_coverage], 'semantic_completeness': raw.semantic_completeness})
    return RawExtraction.model_validate(raw.model_dump(mode='json'))
