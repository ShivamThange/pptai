import asyncio
import copy
import pytest
from infrastructure.utils.artifacts import file_hash
from infrastructure.ingestion.knowledge_extractor import generate_validated_ir1
from infrastructure.ingestion.asset_interpreter import asset_insights_to_units, validate_asset_insights, build_asset_context, interpret_assets
from infrastructure.ingestion.slide_composer import retrieve_slide_context, validate_slide_grounding, compose_single_slide
from infrastructure.ingestion.chunker import build_chunks
from contracts.asset_schema import AssetOptions
from contracts.ir2_content_schema import SlideSpec
from contracts.storyboard_schema import SlidePlan,Storyboard,TopicChunk
from f04_helpers import enriched,AssetCaller


def test_checked_table_finding_reaches_text_only_composition(tmp_path):
    caller=AssetCaller()
    raw,root,_=enriched('results.csv',tmp_path,caller,'auto')
    ir1=generate_validated_ir1(raw,caller,root,extraction_mode='source-passages')
    unit=next(u for u in ir1.units if u.origin_insight_ids)
    assert '10 percentage points' in unit.summary and unit.validation.semantic_support=='UNKNOWN'
    chunk=TopicChunk(chunk_id='result',label='Results',unit_ids=[unit.unit_id],digest=unit.summary,token_estimate=100)
    plan=SlidePlan(slide_id=1,title='Comparison',objective='Explain the finding',narrative_role='evidence',chunk_refs=['result'],source_unit_ids=[unit.unit_id])
    context=retrieve_slide_context(plan,ir1,[chunk],Storyboard(document_title='Results',slides=[plan]))
    assert context['knowledge_units'][0]['origin_asset_ids']==[raw.assets[0].asset_id]
    slide=SlideSpec(layout='fixture',content={'body':{'type':'text_group','text':unit.summary}},source_unit_ids=[unit.unit_id])
    validate_slide_grounding(slide,context)
    assert slide.asset_usage['body.text']['usage']=='TEXT_CLAIM'
    assert slide.asset_usage['body.text']['origin_insight_ids']==unit.origin_insight_ids
    # Changed original data cannot continue supporting the computed text.
    context['asset_raw_context']['assets'][0]['content']['cells'][3]['normalized_value']='999'
    with pytest.raises(ValueError):validate_slide_grounding(slide,context)


@pytest.mark.parametrize('change',['foreign_context','wrong_hash','unverified_operand','context_changed'])
def test_insights_reject_forged_or_stale_support(tmp_path,change):
    raw,root,_=enriched('results.csv',tmp_path,AssetCaller(),'auto')
    asset=raw.assets[0];interpretation=asset.content.interpretation
    if change=='foreign_context':interpretation.insights[0].context_refs=['foreign:block']
    if change=='wrong_hash':interpretation.insights[0].anchors[0].source_sha256='0'*64
    if change=='unverified_operand':
        next(c for c in asset.content.cells if (c['row'],c['column'])==(1,1))['numeric_state']='CACHED_UNVERIFIED'
    if change=='context_changed':raw.blocks[0].text+=' changed context'
    checked=validate_asset_insights(interpretation,raw)
    assert checked.insights[0].eligibility=='REJECTED'


def test_all_more_than_eight_assets_have_coverage_and_context_cache(tmp_path):
    raw,root,_=enriched('results.csv',tmp_path)
    original=raw.assets[0]
    raw.assets=[original.model_copy(deep=True) for _ in range(10)]
    for index,asset in enumerate(raw.assets):asset.asset_id+=':'+str(index)
    caller=AssetCaller();options=AssetOptions(mode='structured')
    interpret_assets(raw,options,root,caller=caller)
    assert len(caller.calls)==10 and len(raw.asset_semantic_coverage)==10
    assert all(c.accepted_insight_ids for c in raw.asset_semantic_coverage)
    count=len(caller.calls);interpret_assets(raw,options,root,caller=caller)
    assert len(caller.calls)==count
    raw.blocks[0].text+=' changed original context'
    interpret_assets(raw,options,root,caller=caller)
    assert len(caller.calls)==count+10


def test_disabled_understanding_zero_calls(tmp_path):
    caller=AssetCaller();raw,_,_=enriched('results.csv',tmp_path,caller,'off')
    assert not caller.calls and raw.semantic_completeness=='disabled'
    assert raw.asset_semantic_coverage[0].status=='disabled'


@pytest.mark.parametrize('statement',['the method improves performance by 20%','the diagram causes better accuracy','the result is statistically significant'])
def test_visual_inferences_cannot_establish_numbers_or_causality(tmp_path,statement):
    from contracts.asset_schema import AssetInsight,AssetEvidenceAnchor,AssetInterpretation
    raw,root,_=enriched('results.csv',tmp_path)
    asset=raw.assets[0];packet=build_asset_context(raw,asset.asset_id)
    refs=[c['source_id'] for c in packet['context']]
    interpretation=AssetInterpretation(asset_id=asset.asset_id,context_sha256=packet['context_sha256'],context_refs=refs,
        insights=[AssetInsight(asset_id=asset.asset_id,kind='implication',statement=statement,basis='contextual_interpretation',
            qualification='uncertain',context_refs=refs,anchors=[AssetEvidenceAnchor(asset_id=asset.asset_id,source_sha256=asset.content_sha256)])])
    assert validate_asset_insights(interpretation,raw).insights[0].eligibility=='REJECTED'


def test_capacity_limit_is_explicit_not_semantic_success(tmp_path):
    raw,root,_=enriched('results.csv',tmp_path)
    caller=AssetCaller()
    interpret_assets(raw,AssetOptions(mode='structured',semantic_input_chars=2000),root,caller=caller)
    assert not caller.calls and raw.semantic_completeness=='partial'
    assert raw.asset_semantic_coverage[0].status=='failed' and raw.asset_semantic_coverage[0].unprocessed_refs


def test_verified_native_chart_comparison_is_original_data_knowledge(tmp_path):
    from contracts.asset_schema import AssetInsight,AssetEvidenceAnchor,AssetInterpretation
    raw,root,_=enriched('charts.xlsx',tmp_path)
    asset=next(a for a in raw.assets if a.kind=='chart')
    packet=build_asset_context(raw,asset.asset_id);refs=[c['source_id'] for c in packet['context']]
    asset.content.interpretation=AssetInterpretation(asset_id=asset.asset_id,context_sha256=packet['context_sha256'],context_refs=refs,
        insights=[AssetInsight(asset_id=asset.asset_id,kind='comparison',statement='Candidate',basis='calculated',context_refs=refs,
            calculation={'operation':'difference','points':[[0,0],[0,1]]},
            anchors=[AssetEvidenceAnchor(asset_id=asset.asset_id,source_sha256=asset.content_sha256,series_index=0,category_index=0)])])
    units=asset_insights_to_units(raw)
    assert units[0].summary=='Method B minus Method A for Score: 10.'
    assert units[0].origin_asset_ids==[asset.asset_id] and units[0].validation.semantic_support=='UNKNOWN'


def test_structured_generation_rejects_unbound_chart_without_assets():
    slide=SlideSpec(layout='fixture',content={'body':{'type':'chart','categories':['Method A'],
        'series':[{'name':'Score','values':[80]}]}})
    with pytest.raises(ValueError,match='source asset ID'):
        validate_slide_grounding(slide,{'asset_mode':'structured','knowledge_units':[],'assets':[]})


def test_native_chart_grounding_resolves_verified_dataset(tmp_path):
    from domain.evaluation.chart_binding import resolve_chart
    raw,root,_=enriched('charts.xlsx',tmp_path)
    chart=next(a for a in raw.assets if a.kind=='chart')
    slide=SlideSpec(layout='fixture',content={'body':{'type':'chart',**resolve_chart(chart)}})
    context={'asset_mode':'structured','knowledge_units':[],'assets':[chart.model_dump(mode='json')],
        'source_item_ids':raw.source_item_ids,'asset_source_items':[s.model_dump(mode='json') for s in raw.asset_source_items]}
    validate_slide_grounding(slide,context)
    assert all(g.numeric_binding=='CHECKED' for g in slide.grounding.values())
    assert slide.asset_usage['body.visual']['usage']=='VISUAL_DISPLAY'
