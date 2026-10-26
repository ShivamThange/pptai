import json
from pathlib import Path
import pytest
from core.asset_registry import AssetRegistry
from tools.asset_inspection import inspect_asset,list_assets,asset_file
from f04_helpers import enriched,AssetCaller


def test_path_free_inspection_and_verified_allowlisted_download(tmp_path):
    raw,root,_=enriched('results.csv',tmp_path,AssetCaller(),'auto')
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids)
    page=list_assets(registry,limit=1)
    assert page['total']==1 and page['next_offset'] is None
    detail=inspect_asset(registry,raw.assets[0].asset_id)
    assert str(root) not in json.dumps(detail) and 'path' not in detail['representations'][0]
    assert detail['insights'][0]['eligibility']=='FACTUAL_TEXT'
    path,media=asset_file(registry,raw.assets[0].asset_id,'original')
    assert path.is_file() and media=='application/json'
    with pytest.raises(KeyError):asset_file(registry,'foreign','original')
    with pytest.raises(KeyError):asset_file(registry,raw.assets[0].asset_id,'../../secret')
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError):asset_file(registry,raw.assets[0].asset_id,'original')


@pytest.mark.parametrize('offset,limit',[(-1,50),(0,101),(0,0)])
def test_page_bounds(tmp_path,offset,limit):
    with pytest.raises(ValueError):list_assets(AssetRegistry([]),offset=offset,limit=limit)


def test_full_sheet_previews_explicitly_bounded(tmp_path):
    raw,root,_=enriched('charts.xlsx',tmp_path)
    registry=AssetRegistry(raw.assets,run_root=root,source_item_ids=raw.source_item_ids,asset_source_items=raw.asset_source_items)
    detail=inspect_asset(registry,next(a.asset_id for a in raw.assets if a.asset_id.endswith(':1:full-table')))
    assert detail['truncated'] and detail['row_count']==205
    assert all(c['row']<20 for c in detail['preview_cells'])
