import json
import pytest
from PIL import Image
from infrastructure.utils.artifacts import file_hash, atomic_json
from domain.extraction.asset_registry import AssetRegistry
from contracts.asset_schema import TableSelection
from f04_helpers import enriched,FIXTURES


def test_fixture_bytes():
    manifest=json.loads((FIXTURES/'manifest.json').read_text())
    assert manifest['synthetic']
    for name,item in manifest['files'].items():assert file_hash(FIXTURES/name)==item['sha256']


def test_lexical_table_and_immutable_parser(tmp_path):
    raw,root,path=enriched('lexemes.csv',tmp_path)
    asset=raw.assets[0]
    assert raw.schema_version=='4' and json.loads(path.read_text())['schema_version']=='3'
    values=[c['display_text'] for c in asset.content.cells]
    assert all(v in values for v in ['001','1.2300','0','-2','line one\r\nline two',''])
    assert next(c for c in asset.content.cells if c['text']=='001')['normalized_type']=='text'
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids)
    assert registry.select_table(asset.asset_id)['rows'][1][0]=='001'


def test_sparse_hidden_full_sheet_and_cut_merge(tmp_path):
    raw,root,path=enriched('charts.xlsx',tmp_path)
    asset=next(a for a in raw.assets if a.asset_id.endswith(':1:full-table'))
    assert asset.content.row_count==205 and (198,0,4,1) in asset.content.merged_ranges
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    with pytest.raises(ValueError,match='cut merge'):
        registry.select_table(asset.asset_id,TableSelection(asset_id=asset.asset_id,rows=[198,199],columns=[0]))
    selected=registry.select_table(asset.asset_id,TableSelection(asset_id=asset.asset_id,rows=[198,199,200,201],columns=[0]))
    assert selected['merges']==[(0,0,4,1)] and selected['rows'][0][0]=='Merged boundary'
    hidden=next(a for a in raw.assets if a.asset_id.endswith(':2:full-table'))
    assert next(c for c in hidden.content.cells if c.get('formula'))['numeric_state']=='UNKNOWN'


@pytest.mark.parametrize('orientation',range(1,9))
def test_orientation_derivative_preserves_original(tmp_path,orientation):
    from contracts.raw_extraction_schema import SourceAsset,SourceLocation,RawExtraction
    from infrastructure.ingestion.asset_adapters import enrich_assets
    from contracts.asset_schema import AssetOptions
    import shutil
    original=tmp_path/'source.jpg';shutil.copyfile(FIXTURES/f'oriented-{orientation}.jpg',original)
    digest=file_hash(original);ref='doc_fixture:image'
    asset=SourceAsset(asset_id=ref,kind='image',section_path=['Root'],document_id='doc_fixture',source_refs=[ref],
        locations=[SourceLocation(document_id='doc_fixture',source_id=ref,kind='image')],file_path=str(original),content_sha256=digest,width=900,height=450)
    raw=enrich_assets(RawExtraction(document_name='image',source_item_ids=[ref],assets=[asset]),tmp_path/'none',tmp_path,
                      AssetOptions(mode='structured',semantic_understanding='off'))
    assert file_hash(original)==digest and raw.assets[0].content.exif_orientation==orientation
    with Image.open(raw.assets[0].content.representations[1].path) as image:
        assert image.size==((450,900) if orientation>=5 else (900,450))


def test_representation_and_original_package_tamper(tmp_path):
    raw,root,path=enriched('charts.xlsx',tmp_path)
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    chart=next(a for a in raw.assets if a.kind=='chart')
    registry.require(chart.asset_id,'chart')
    original=raw.asset_source_items[0].package_path
    from pathlib import Path
    Path(original).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='original package'):
        registry.require(chart.asset_id,'chart')


def test_docx_original_grid_merge_and_omml_locations(tmp_path):
    raw,root,_=enriched('assets.docx',tmp_path)
    table=next(a for a in raw.assets if a.kind=='table' and any(':ooxml:' in r for r in a.source_refs))
    assert table.content.merged_ranges==[(3,0,1,2)]
    assert all(l.page is None and l.bbox is None for l in table.locations)
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    assert registry.select_table(table.asset_id)['rows'][1]==['Method A','80']
    formula=next(a for a in raw.assets if a.content and a.content.kind=='formula' and a.content.expression_format=='omml')
    assert formula.content.expression==r'\frac{x}{n}' and formula.content.render_status=='RENDERED'
    registry.require_representation(formula.asset_id,'display_png')


def test_exact_unit_annotation_scope(tmp_path):
    raw,root,_=enriched('results.csv',tmp_path)
    table=raw.assets[0]
    annotation=table.content.annotations[0]
    assert annotation['kind']=='unit' and annotation['text']=='%' and annotation['scope']=='column'
    assert annotation['source_refs'][0] in raw.source_item_ids
    assert all(annotation['annotation_id'] in c['unit_refs'] for c in table.content.cells if c['column']==1)


def test_original_package_catalog_cannot_change_document_identity(tmp_path):
    raw,root,_=enriched('charts.xlsx',tmp_path)
    chart=next(a for a in raw.assets if a.kind=='chart')
    item=next(item for item in raw.asset_source_items if item.source_id in chart.source_refs)
    item.document_id='doc_'+'0'*64
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    with pytest.raises(ValueError,match='forged OOXML'):
        registry.require(chart.asset_id,'chart')
