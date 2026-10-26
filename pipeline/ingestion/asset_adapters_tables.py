"""Faithful grids and selections; decimal normalization never replaces display."""
import re
from decimal import Decimal
from schemas.asset_schema import TableAssetContent, TableSelection
from core.artifacts import sha256_value


def rich_cell(cell, *, numeric_column=False):
    result = dict(cell)
    text = str(cell.get('text', ''))
    result.update(display_text=text, display_origin='source_lexeme' if cell.get('lexical_value') == text else 'source_text',
                  normalized_value=None, normalized_type='text' if text else 'blank', numeric_state='NOT_NUMERIC')
    value_type = cell.get('value_type') or ''
    if cell.get('formula') or cell.get('cached_state'):
        result.update(normalized_type='unknown', numeric_state='CACHED_UNVERIFIED' if cell.get('cached_state') == 'cached_unverified' else 'UNKNOWN')
    elif value_type.startswith('b:'):
        result['normalized_type'] = 'boolean'
    elif value_type.startswith('e:'):
        result['normalized_type'] = 'error'
    elif 'date' in value_type or 'time' in value_type:
        result['normalized_type'] = 'date'
    elif (value_type.startswith('n:') or not value_type or numeric_column) and re.fullmatch(r'[+-]?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?', text):
        result.update(normalized_type='number', normalized_value=str(Decimal(text)), numeric_state='SOURCE_LITERAL')
    return result


def table_content(asset, representations):
    data = asset.data or {}
    numeric_columns={c['column'] for c in data.get('cells',[]) if c.get('column_header') and re.search(r'\((?:%|USD|EUR|GBP|kg|ms|seconds?)\)',c['text'])}
    cells = [rich_cell(c,numeric_column=c['column'] in numeric_columns) for c in data.get('cells', [])]
    row_count = max([len(data.get('rows', [])) + bool(data.get('headers')), *[c['row'] + c.get('row_span', 1) for c in cells]])
    col_count = max([len(data.get('headers', [])), *[len(r) for r in data.get('rows', [])], *[c['column'] + c.get('column_span', 1) for c in cells]])
    annotations=[]
    for cell in cells:
        if cell.get('column_header'):
            match=re.search(r'\((%|USD|EUR|GBP|kg|ms|seconds?)\)',cell['text'])
            if match:
                ref=cell['source_refs'][0]
                annotations.append({'annotation_id':ref+':unit','kind':'unit','text':match[1],
                    'source_refs':cell['source_refs'],'scope':'column','column':cell['column'],'canonical_unit':match[1],
                    'scale':None})
                for data_cell in cells:
                    if data_cell['column']==cell['column']:
                        data_cell['unit_refs']=[ref+':unit']
    return TableAssetContent(source_sha256=asset.content_sha256, representations=representations,
        annotations=annotations,
        row_count=row_count, column_count=col_count, cells=cells,
        header_rows=sorted({c['row'] for c in cells if c.get('column_header')}),
        merged_ranges=[(c['row'], c['column'], c.get('row_span', 1), c.get('column_span', 1)) for c in cells
                       if c.get('row_span', 1) > 1 or c.get('column_span', 1) > 1])


def select_table(asset, selection=None):
    content = asset.content
    if not isinstance(content, TableAssetContent):
        if selection:
            raise ValueError('TABLE_SELECTION_INVALID: legacy table has no rich grid')
        return {'headers': asset.data['headers'], 'rows': asset.data['rows'], 'merges': []}
    selection = TableSelection.model_validate(selection) if selection else TableSelection(
        asset_id=asset.asset_id, rows=list(range(content.row_count)), columns=list(range(content.column_count)),
        header_rows=content.header_rows)
    if selection.asset_id != asset.asset_id or max(selection.rows) >= content.row_count or max(selection.columns) >= content.column_count:
        raise ValueError('TABLE_SELECTION_INVALID: foreign asset or out of bounds')
    if selection.annotation_refs and not set(selection.annotation_refs) <= {a.get('annotation_id') for a in content.annotations}:
        raise ValueError('TABLE_SELECTION_INVALID: unknown annotation')
    rmap, cmap = {r: i for i, r in enumerate(selection.rows)}, {c: i for i, c in enumerate(selection.columns)}
    grid = [['' for _ in selection.columns] for _ in selection.rows]
    merges = []
    for cell in content.cells:
        r, c = cell['row'], cell['column']
        rr = list(range(r, r + cell.get('row_span', 1)))
        cc = list(range(c, c + cell.get('column_span', 1)))
        if not (set(rr) & set(selection.rows) and set(cc) & set(selection.columns)):
            continue
        if not set(rr) <= set(selection.rows) or not set(cc) <= set(selection.columns):
            raise ValueError('TABLE_SELECTION_INVALID: cut merge')
        if [rmap[v] for v in rr] != list(range(rmap[r], rmap[r] + len(rr))) or [cmap[v] for v in cc] != list(range(cmap[c], cmap[c] + len(cc))):
            raise ValueError('TABLE_SELECTION_INVALID: reordered merge')
        grid[rmap[r]][cmap[c]] = cell['display_text']
        if len(rr) > 1 or len(cc) > 1:
            merges.append((rmap[r], cmap[c], len(rr), len(cc)))
    return {'headers': [], 'rows': grid, 'merges': merges,
            'selection_digest': sha256_value({'source': content.source_sha256, 'selection': selection.model_dump()})}
