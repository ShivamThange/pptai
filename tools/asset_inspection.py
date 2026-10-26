"""Bounded, path-free published-asset views. Never parsing or inference."""
from pathlib import Path
from core.asset_registry import AssetRegistry, AssetBindingError
from core.artifacts import file_hash


def public_representation(rep):
    return rep.model_dump(exclude={'path'},mode='json')


def inspect_asset(registry, asset_id, *, display_box=None):
    if asset_id not in registry.assets:
        raise KeyError(asset_id)
    asset=registry.assets[asset_id]
    content=asset.content
    result={'asset_id':asset_id,'kind':asset.kind,'caption':asset.caption,'caption_binding':asset.caption_binding,
        'source_refs':asset.source_refs,'locations':[l.model_dump(mode='json') for l in asset.locations],
        'availability':asset.availability,'width':asset.width,'height':asset.height,
        'content_state':'structured' if content else 'legacy_unknown','representations':[],
        'semantic_status':'unavailable','label_legibility':'UNKNOWN'}
    if content:
        registry.validate_derivation(asset_id)
        result['representations']=[public_representation(r) for r in content.representations]
        if content.kind=='table':
            result.update(row_count=content.row_count,column_count=content.column_count,
                preview_cells=[{k:v for k,v in c.items() if k not in {'original_xml'}} for c in content.cells if c['row']<20][:400],
                preview_cell_limit=400,preview_cells_truncated=sum(c['row']<20 for c in content.cells)>400,
                preview_row_limit=20,truncated=content.row_count>20,merged_ranges=content.merged_ranges,
                annotations=content.annotations,sheet_name=content.sheet_name)
        elif content.kind=='chart':
            result.update(chart_type=content.chart_type,data_state=content.data_state,reconstruction_status=content.reconstruction_status,
                categories=content.categories[:20],series=[{**s,'values':s['values'][:20]} for s in content.series[:20]],
                point_count=len(content.categories),truncated=len(content.categories)>20 or len(content.series)>20)
        elif content.kind=='formula':
            result.update(expression=content.expression,expression_format=content.expression_format,
                transcription_status=content.transcription_status,render_status=content.render_status)
        elif content.kind=='figure':
            result.update(exif_orientation=content.exif_orientation,transform=content.transform.model_dump(mode='json') if content.transform else None,
                          descriptions=[d.model_dump() for d in content.descriptions])
        if content.interpretation:
            interpretation=content.interpretation
            result.update(semantic_status=interpretation.completeness,summary=interpretation.summary[:4000],
                insights=[i.model_dump(mode='json') for i in interpretation.insights[:20]],
                insight_count=len(interpretation.insights),insights_truncated=len(interpretation.insights)>20,
                unresolved_questions=interpretation.unresolved_questions[:20])
    if display_box and asset.width and asset.height:
        w,h=display_box
        if w<=0 or h<=0:
            raise ValueError('Display dimensions must be positive')
        result['ppi']=min(asset.width/w,asset.height/h)
    return result


def list_assets(registry, *, kind=None, offset=0, limit=50):
    if offset<0 or not 1<=limit<=100:
        raise ValueError('Asset page offset/limit out of bounds')
    selected=sorted((a for a in registry.assets.values() if kind is None or a.kind==kind),key=lambda a:a.asset_id)
    rows=[{'asset_id':a.asset_id,'kind':a.kind,'availability':a.availability,
        'has_typed_content':a.content is not None,'has_interpretation':bool(a.content and a.content.interpretation),
        'accepted_insights':sum(i.eligibility in {'FACTUAL_TEXT','QUALIFIED_TEXT'} for i in a.content.interpretation.insights)
            if a.content and a.content.interpretation else 0} for a in selected]
    return {'items':rows[offset:offset+limit], 'total':len(rows), 'offset':offset,'limit':limit,
        'next_offset':offset+limit if offset+limit<len(rows) else None,
        'counts':{'discovered':len(rows),'missing':sum(a.availability=='MISSING' for a in selected),
                  'usable':sum(a.availability=='AVAILABLE' and bool(a.content) for a in selected),
                  'unsupported':sum(a.content is None or a.content.kind=='chart' and a.content.reconstruction_status=='UNSUPPORTED' for a in selected),
                  'described':sum(a.content is not None and a.content.kind=='figure' and any(d.status in {'SOURCE_BACKED','UNVERIFIED'} for d in a.content.descriptions) for a in selected),
                  'interpreted':sum(row['has_interpretation'] for row in rows),
                  'with_accepted_insights':sum(row['accepted_insights']>0 for row in rows)}}


def asset_file(registry, asset_id, representation_id):
    if asset_id not in registry.assets:
        raise KeyError(asset_id)
    asset=registry.assets[asset_id]
    if not asset.content:
        if representation_id!='original':
            raise KeyError(representation_id)
        asset=registry.require(asset_id,asset.kind)
        return Path(asset.file_path),'application/json' if asset.kind=='table' else 'image/png'
    rep=next((r for r in asset.content.representations if r.representation_id==representation_id),None)
    if rep is None or rep.availability!='available' or rep.media_type not in {'image/png','image/jpeg','image/svg+xml','application/json'}:
        raise KeyError(representation_id)
    registry.validate_derivation(asset_id)
    return Path(rep.path),rep.media_type
