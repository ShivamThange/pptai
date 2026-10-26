import pytest
from schemas.asset_schema import AssetOptions, TableAssetContent, TableSelection
from schemas.raw_extraction_schema import RawExtraction
from schemas.raw_extraction_schema import RawExtraction
from schemas.ir1_schema import ValidatedIR1


def load_raw(value):
    return RawExtraction.model_validate(value)


def load_ir1(value):
    return ValidatedIR1.model_validate(value)


@pytest.mark.parametrize('options',[{'min_ppi':float('inf')},{'formula_dpi':0},{'unknown':1},{'description_asset_ids':['x','x']}])
def test_options_fail_closed(options):
    with pytest.raises(ValueError):AssetOptions(**options)


@pytest.mark.parametrize('version',['1','2','3'])
def test_legacy_migration_no_claimed_understanding(version):
    raw=load_raw({'schema_version':version,'document_name':'legacy'})
    assert raw.assets==[] and raw.semantic_completeness=='disabled'
    ir1=load_ir1({'schema_version':'3','document_title':'legacy'})
    assert not ir1.asset_source_items and not ir1.source_blocks


@pytest.mark.parametrize('cells',[[{'row':0,'column':0,'row_span':3}],
    [{'row':0,'column':0,'column_span':2},{'row':0,'column':1}], [{'row':-1,'column':0}]])
def test_grid_bounds_and_overlap(cells):
    with pytest.raises(ValueError):TableAssetContent(source_sha256='a'*64,row_count=2,column_count=2,cells=cells)


@pytest.mark.parametrize('rows,columns',[([1,1],[0]),([-1],[0]),([0],[2,2])])
def test_selections_reject_bad_indices(rows,columns):
    with pytest.raises(ValueError):TableSelection(asset_id='source',rows=rows,columns=columns)
