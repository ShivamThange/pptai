from pathlib import Path
import pytest
from domain.rendering.formula_renderer import render_formula
from infrastructure.utils.artifacts import file_hash
from f04_helpers import enriched


def test_mathtext_actual_render_cache_and_tamper(tmp_path):
    expression=r'\frac{\sum_i x_i}{n}'
    first=render_formula(expression,{'dpi':200},tmp_path)
    assert first['status']=='RENDERED' and len(first['representations'])==2
    assert render_formula(expression,{'dpi':200},tmp_path)==first
    rep=first['representations'][0];Path(rep['path']).write_bytes(b'corrupt')
    rerendered=render_formula(expression,{'dpi':200},tmp_path)
    assert file_hash(rep['path'])==rerendered['representations'][0]['sha256']
    assert render_formula(expression,{'dpi':300},tmp_path)['cache_key']!=first['cache_key']


@pytest.mark.parametrize('expression',[r'\input{secret}',r'\unknown{x}',r'\begin{matrix}x\end{matrix}', 'x'*4001])
def test_unsupported_math_no_execution(tmp_path,expression):
    assert render_formula(expression,{},tmp_path)['status']=='FORMULA_UNSUPPORTED'


def test_markdown_exact_math_spans_currency_and_unsupported(tmp_path):
    raw,_,_=enriched('formula.md',tmp_path)
    formulas=[a for a in raw.assets if a.kind=='formula']
    assert len(formulas)==2
    assert any(a.content.render_status=='RENDERED' for a in formulas)
    assert any(a.content.render_status=='FORMULA_UNSUPPORTED' for a in formulas)
    from domain.extraction.asset_registry import AssetRegistry,validate_asset_content
    registry=AssetRegistry(raw.assets,source_item_ids=raw.source_item_ids)
    unsupported=next(a for a in formulas if a.content.render_status=='FORMULA_UNSUPPORTED')
    with pytest.raises(ValueError,match='FORMULA_RENDER_UNAVAILABLE'):
        validate_asset_content({'type':'formula','source_asset_id':unsupported.asset_id},registry)
