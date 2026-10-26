import pytest
from core.asset_registry import AssetRegistry
from tools.chart_binding import resolve_chart
from f04_helpers import enriched


def test_real_xlsx_chart_exact_cells_no_cache_evidence(tmp_path):
    raw,root,_=enriched('charts.xlsx',tmp_path)
    chart=next(a for a in raw.assets if a.kind=='chart')
    assert chart.content.data_state=='VERIFIED_SOURCE_DATA'
    assert chart.content.categories==['Method A','Method B']
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    bound=registry.resolve_chart(chart.asset_id)
    assert bound['series']==[{'name':'Score','values':[80.,90.]}]
    for supplied in [dict(bound,categories=['Method B','Method A']),dict(bound,chart_type='line'),
                     dict(bound,series=[{'name':'Changed','values':[80.,90.]}]),dict(bound,series=[{'name':'Score','values':[80.,91.]}])]:
        with pytest.raises(ValueError):registry.resolve_chart(chart.asset_id,supplied)


def test_float_precision_loss_rejected(tmp_path):
    raw,_,_=enriched('charts.xlsx',tmp_path)
    chart=next(a for a in raw.assets if a.kind=='chart')
    chart.content.series[0]['values'][0]='80.12345678901234567'
    chart.content.points[0].decimal_value='80.12345678901234567'
    with pytest.raises(ValueError,match='precision'):resolve_chart(chart)


def test_explicit_selected_table_chart_and_no_identifier_or_blank_coercion(tmp_path):
    from tools.chart_binding import bind_selected_table
    from schemas.asset_schema import ChartMapping
    raw,root,_=enriched('results.csv',tmp_path)
    table=raw.assets[0]
    mapping=ChartMapping(table_asset_id=table.asset_id,rows=[1,2],category_column=0,series_columns=[1],header_row=0)
    chart=bind_selected_table(table,mapping,root)
    assert resolve_chart(chart)['series'][0]['values']==[80.,90.]
    assert chart.content.parent_asset_ids==[table.asset_id]
    for text in ['001','','1,23','cached, unverified']:
        changed=table.model_copy(deep=True)
        next(c for c in changed.content.cells if (c['row'],c['column'])==(1,1))['text']=text
        with pytest.raises(ValueError):bind_selected_table(changed,mapping,root)


def test_docx_embedded_workbook_chart_uses_original_cells(tmp_path):
    raw,root,_=enriched('embedded-chart.docx',tmp_path)
    chart=next(a for a in raw.assets if a.kind=='chart')
    assert chart.content.data_origin=='native_cells' and chart.content.data_state=='VERIFIED_SOURCE_DATA'
    assert any(item.embedded_package_part for item in raw.asset_source_items)
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    assert registry.resolve_chart(chart.asset_id)['series'][0]['values']==[80.,90.]
