"""Exact source chart binding before conversion to native Office numbers."""
from decimal import Decimal
from infrastructure.utils.artifacts import sha256_value


def bind_selected_table(table, mapping, root):
    from pathlib import Path
    from contracts.asset_schema import ChartMapping,ChartAssetContent,ChartPointBinding,AssetRepresentation
    from contracts.raw_extraction_schema import SourceAsset
    from infrastructure.utils.artifacts import atomic_json,file_hash
    import re
    mapping=ChartMapping.model_validate(mapping.model_dump() if hasattr(mapping,'model_dump') else mapping)
    if mapping.table_asset_id!=table.asset_id or not table.content or table.content.kind!='table':
        raise ValueError('CHART_REFERENCE_UNRESOLVED: table mapping')
    cells={(c['row'],c['column']):c for c in table.content.cells}
    categories=[];series=[];points=[];labels=[];refs=[];locations=[]
    def cell_at(row,column):
        cell=cells.get((row,column))
        if not cell or cell.get('row_span',1)!=1 or cell.get('column_span',1)!=1 or cell.get('formula') or cell.get('cached_state'):
            raise ValueError('CHART_DATA_UNVERIFIED: missing/merged/formula cell')
        refs.extend(cell['source_refs']);locations.extend(cell['locations'])
        return cell
    for row in mapping.rows:
        cell=cell_at(row,mapping.category_column);categories.append(cell['text']);labels.extend(cell['source_refs'])
    for si,col in enumerate(mapping.series_columns):
        header=cell_at(mapping.header_row,col);labels.extend(header['source_refs']);values=[]
        for ci,row in enumerate(mapping.rows):
            cell=cell_at(row,col);text=cell['text']
            # An explicit mapping requests numeric interpretation; no locale/identifier guesses.
            if not re.fullmatch(r'[+-]?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?',text):
                raise ValueError('CHART_DATA_UNVERIFIED: nonnumeric/ambiguous lexical value')
            number=Decimal(text)
            values.append(str(number));points.append(ChartPointBinding(series_index=si,category_index=ci,
                lexical_value=text,decimal_value=str(number),value_refs=cell['source_refs']))
        series.append({'name':header['text'],'values':values})
    aid=table.asset_id+':derived:'+sha256_value(mapping.model_dump())[:20]
    payload={'chart_type':mapping.chart_type,'categories':categories,'series':series,'data_state':'VERIFIED_SOURCE_DATA'}
    path=Path(root)/'assets'/'mapped-charts'/(sha256_value(aid)+'.json');atomic_json(path,payload)
    asset=SourceAsset(asset_id=aid,kind='chart',section_path=table.section_path,document_id=table.document_id,
        source_refs=list(dict.fromkeys(refs)),locations=list({v['source_id']:v for v in locations}.values()),
        file_path=str(path),content_sha256=file_hash(path),content=ChartAssetContent(source_sha256=table.content_sha256,
            origin='derived',parent_asset_ids=[table.asset_id],chart_type=mapping.chart_type,data_origin='selected_table',
            data_state='VERIFIED_SOURCE_DATA',reconstruction_status='EDITABLE',categories=categories,series=series,points=points,label_refs=labels,
            representations=[AssetRepresentation(representation_id='chart_data_json',role='chart_data_json',path=str(path),
                sha256=file_hash(path),media_type='application/json',editability='native_chart')]))
    resolve_chart(asset)
    return asset


def resolve_chart(asset, supplied=None):
    content = asset.content
    if not content or content.kind!='chart' or content.data_state!='VERIFIED_SOURCE_DATA' or content.reconstruction_status!='EDITABLE':
        raise ValueError('CHART_DATA_UNVERIFIED')
    if content.chart_type not in {'column','bar','line','area','pie'}:
        raise ValueError('CHART_ENCODING_UNSUPPORTED')
    series=[]
    for si,source in enumerate(content.series):
        values=[]
        if len(source['values'])!=len(content.categories):
            raise ValueError('CHART_REFERENCE_UNRESOLVED')
        for ci,value in enumerate(source['values']):
            bindings=[p for p in content.points if p.series_index==si and p.category_index==ci]
            if len(bindings)!=1 or Decimal(value)!=Decimal(bindings[0].decimal_value) or not bindings[0].value_refs:
                raise ValueError('CHART_REFERENCE_UNRESOLVED')
            if not set(bindings[0].value_refs)<=set(asset.source_refs) or not set(content.label_refs)<=set(asset.source_refs):
                raise ValueError('CHART_REFERENCE_UNRESOLVED: foreign point/label evidence')
            numeric=float(value)
            if Decimal(str(numeric))!=Decimal(value):
                raise ValueError('CHART_DATA_UNVERIFIED: native float loses source precision')
            values.append(numeric)
        series.append({'name':source['name'],'values':values})
    result={'chart_type':content.chart_type,'categories':content.categories,'series':series,'source_asset_id':asset.asset_id}
    if supplied:
        if supplied.get('chart_type',content.chart_type)!=content.chart_type or supplied.get('categories',content.categories)!=content.categories:
            raise ValueError('CHART_DATA_UNVERIFIED: type/category order changed')
        if supplied.get('series') and supplied['series']!=series:
            raise ValueError('CHART_DATA_UNVERIFIED: series labels/values changed')
    return result
