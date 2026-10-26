import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
import pytest
from pydantic import BaseModel, ValidationError
from config.settings import ProviderCapabilities, TaskBudget, get_multi_agent_settings, resolve_environment
from infrastructure.llm.context_budget import ContextBudgetError, resolve_stage_budget, assert_fits, measure_request
from infrastructure.llm.llm_client import LLMClient, RpmLimiter
from contracts.context_schema import TokenMeasurement


class Answer(BaseModel):
    answer: str


class Response:
    def __init__(self, value=None, finish='stop'):
        self.body = {'choices': [{'message': {'content': json.dumps(value or {'answer': 'ok'})}, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 7}}}
    def read(self):
        return json.dumps(self.body).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def client(**options):
    settings = options.pop('settings', get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS': '32768', 'LLM_CONTEXT_COUNT_MODE': 'estimate'}))
    sent = []
    def transport(request, timeout):
        sent.append(json.loads(request.data))
        return Response()
    return LLMClient(settings=settings, api_key='fake-key', max_calls_per_minute=999,
        transport=options.pop('transport', transport), **options), sent


@pytest.mark.parametrize('certainty,ceiling,margin', [('counted', 27033, 1639), ('estimated', 25395, 3277)])
def test_exact_capacity_boundary_and_separate_limits(certainty, ceiling, margin):
    settings = get_multi_agent_settings({})
    caps = ProviderCapabilities(context_tokens=32768)
    resolved = resolve_stage_budget(settings, caps, 'slide_composition', 'model', TaskBudget(4096), certainty=certainty)
    assert (resolved.input_ceiling, resolved.margin) == (ceiling, margin)
    measurement = measure_request('x'); measurement.input_tokens = ceiling
    assert_fits(None, resolved, measurement)
    measurement.input_tokens += 1
    with pytest.raises(ContextBudgetError, match='REQUIRED_CONTEXT_TOO_LARGE'):
        assert_fits(None, resolved, measurement)
    capped = replace(settings, stage_input_tokens={'LLM_SLIDE_COMPOSITION_INPUT_TOKENS': 12000})
    assert resolve_stage_budget(capped, caps, 'slide_composition', 'm', TaskBudget(4096)).input_ceiling == 12000
    assert resolve_stage_budget(settings, replace(caps, input_tokens=11000), 's', 'm', TaskBudget(4096)).input_ceiling == 11000


@pytest.mark.parametrize('value', [None, ''])
def test_unknown_capacity_fails_before_count_or_transport(value):
    environment = {} if value is None else {'LLM_UNKNOWN_CONTEXT_TOKENS': value}
    gateway, sent = client(settings=get_multi_agent_settings(environment))
    with pytest.raises(ContextBudgetError, match='CONTEXT_CAPACITY_REQUIRED'):
        gateway.generate_structured(stage='test', prompt='x', output_model=Answer)
    assert not sent and not gateway.count_records
    assert gateway.usage.records[-1].transport_started is False


@pytest.mark.parametrize('value', ['0', '-1', '1.5', 'NaN', 'abc'])
def test_invalid_capacity_rejected(value):
    with pytest.raises(ValueError):
        get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS': value})


def test_declared_capacity_wins_error_policy_and_override_profiles():
    settings = get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_POLICY': 'error', 'LLM_UNKNOWN_CONTEXT_TOKENS': '99999'})
    gateway, _ = client(settings=settings, capabilities=ProviderCapabilities(context_tokens=32768))
    request = gateway.prepare_structured_request(stage='test', prompt='x', output_model=Answer)
    assert request.context.budget.capacity_origin == 'declared'
    with pytest.raises(ContextBudgetError, match='CONTEXT_CAPACITY_REQUIRED'):
        gateway.prepare_structured_request(stage='test', prompt='x', output_model=Answer, model='other-model')
    settings = replace(settings, model_profiles={'openrouter:other-model': ProviderCapabilities(context_tokens=65536, version='other-v1')})
    gateway.settings = settings
    request = gateway.prepare_structured_request(stage='test', prompt='x', output_model=Answer, model='other-model')
    assert request.context.budget.effective_context_limit == 65536


def test_settings_precedence_and_validation(tmp_path, monkeypatch):
    dotenv = tmp_path / '.env'; dotenv.write_text('LLM_UNKNOWN_CONTEXT_TOKENS=32768\nLLM_UNKNOWN_CONTEXT_POLICY=error\n')
    monkeypatch.setenv('LLM_UNKNOWN_CONTEXT_TOKENS', '65536')
    env = resolve_environment(dotenv, {'LLM_UNKNOWN_CONTEXT_TOKENS': 131072})
    assert get_multi_agent_settings(env).unknown_context_tokens == 131072
    for env in ({'LLM_NO_SUCH_STAGE_INPUT_TOKENS': '100'}, {'LLM_CONTEXT_COUNT_MODE': 'guess'},
                {'CONTEXT_TEXT_OVERLAP_TOKENS': '3001'}, {'LLM_UNKNOWN_CONTEXT_POLICY': 'guess'}):
        with pytest.raises(ValueError):
            get_multi_agent_settings(env)
    with pytest.raises(ValidationError):
        TokenMeasurement(input_tokens=-1, method='byte_estimate', certainty='estimated', counter_version='x',
            included_components=[], request_fingerprint='x')


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_exact_payload_parity_unicode_schema_and_hint(mode):
    gateway, sent = client()
    request = gateway.prepare_structured_request(stage='test', system_prompt='固定 system', user_payload={'source': '世界😀\r\n'},
        output_model=Answer, task_budget=TaskBudget(500, estimated_input_tokens=1))
    expected = measure_request(request.payload).input_tokens
    assert request.context.measurement.input_tokens == expected > 1
    if mode == 'async':
        assert asyncio.run(gateway.generate_prepared_async(request)).answer == 'ok'
    else:
        assert gateway.generate_prepared(request).answer == 'ok'
    assert sent == [request.payload]
    assert gateway.usage.records[-1].cached_input_tokens == 7
    assert gateway.usage.as_dict()['input_tokens'] == 10
    request.payload['messages'][1]['content'] = 'changed'
    with pytest.raises(ContextBudgetError, match='PREPARED_CONTEXT_CHANGED'):
        gateway.generate_prepared(request)
    assert len(sent) == 1


def test_fixed_schema_overflow_and_caller_hint_cannot_bypass():
    gateway, sent = client(capabilities=ProviderCapabilities(context_tokens=2000))
    with pytest.raises(ContextBudgetError):
        gateway.generate_structured(stage='test', prompt='x' * 12000, output_model=Answer,
            task_budget=TaskBudget(100, estimated_input_tokens=1))
    assert not sent
    with pytest.raises(ContextBudgetError, match='CONTEXT_FIXED_OVERHEAD_TOO_LARGE'):
        gateway.generate_structured(stage='test', prompt='x', output_model=Answer, task_budget=TaskBudget(1800))


def test_gemini_hybrid_counts_contents_once_estimates_system_and_memoizes():
    counts, dispatched = [], []
    def counter(**kwargs):
        counts.append(kwargs); return SimpleNamespace(total_tokens=20)
    def generate(**kwargs):
        dispatched.append(kwargs); return SimpleNamespace(text='{"answer":"ok"}', usage_metadata=None, candidates=[])
    settings = get_multi_agent_settings({'LLM_PROVIDER': 'gemini', 'LLM_UNKNOWN_CONTEXT_TOKENS': '32768'})
    gateway, _ = client(settings=settings, gemini_client=SimpleNamespace(models=SimpleNamespace(count_tokens=counter, generate_content=generate)))
    request = gateway.prepare_structured_request(stage='test', prompt='世界', system_prompt='stable', output_model=Answer)
    gateway.prepare_structured_request(stage='test', prompt='世界', system_prompt='stable', output_model=Answer)
    assert len(counts) == 1
    assert request.context.measurement.method == 'hybrid_estimate'
    assert request.context.measurement.certainty == 'estimated'
    gateway.generate_prepared(request)
    assert dispatched[0]['contents'] == counts[0]['contents']
    assert counts[0]['config'].system_instruction is None
    assert dispatched[0]['config'].system_instruction == 'stable'
    assert 'system' in request.context.measurement.estimated_components
    assert dispatched[0]['config'].response_json_schema == request.schema
    assert counts[0]['config'].http_options.retry_options.attempts == 1
    from google.genai import models
    assert models._CountTokensConfig_to_mldev(counts[0]['config']) == {}
    gateway.settings = replace(settings, context_count_mode='provider_required')
    with pytest.raises(ContextBudgetError, match='COMPLETE_TOKEN_COUNT_UNAVAILABLE'):
        gateway.prepare_structured_request(stage='test', prompt='x', output_model=Answer)


def test_media_counts_profile_integrity_and_base64_is_not_tokens(tmp_path):
    media = tmp_path / 'image.png'; media.write_bytes(b'x' * 20000)
    gateway, sent = client()
    with pytest.raises(ContextBudgetError, match='IMAGE_TOKEN_COUNT_UNAVAILABLE'):
        gateway.prepare_multimodal_request(stage='vision_audit', prompt='x', image_paths=[str(media)], output_model=Answer)
    gateway.capabilities = ProviderCapabilities(image_tokens=500, image_counter_version='fixture-v1')
    request = gateway.prepare_multimodal_request(stage='vision_audit', prompt='x', image_paths=[str(media)], output_model=Answer)
    assert request.context.measurement.input_tokens < 3000
    gateway.generate_prepared(request)
    media.write_bytes(b'changed')
    with pytest.raises(ContextBudgetError, match='PREPARED_CONTEXT_CHANGED'):
        gateway.generate_prepared(request)
    assert len(sent) == 1


def test_gemini_media_count_has_unknown_subtotal_not_zero(tmp_path):
    image = tmp_path/'image.png'; image.write_bytes(b'fixture')
    seen = []
    def count(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(total_tokens=1000)
    settings = get_multi_agent_settings({'LLM_PROVIDER':'gemini','LLM_UNKNOWN_CONTEXT_TOKENS':'32768'})
    gateway, _ = client(settings=settings, gemini_client=SimpleNamespace(models=SimpleNamespace(count_tokens=count)))
    request = gateway.prepare_multimodal_request(stage='vision_audit', prompt='x', image_paths=[str(image)], output_model=Answer)
    assert request.context.measurement.media_tokens is None
    assert 'media' in request.context.measurement.included_components
    assert len(seen[0]['contents']) == 2 and request.context.measurement.input_tokens > 1000


def test_clipped_valid_json_is_terminal_and_reservations_are_thread_safe():
    gateway, _ = client(transport=lambda *a, **kw: Response(finish='length'))
    # Truncation now escalates the output budget once before failing, so a
    # permanently clipped transport sees exactly two attempts.
    with pytest.raises(ContextBudgetError, match='OUTPUT_INCOMPLETE'):
        gateway.generate_structured(stage='test', prompt='x', output_model=Answer)
    assert gateway.usage.as_dict()['call_count'] == 2
    assert gateway.usage.records[1].max_output_tokens == min(
        gateway.usage.records[0].max_output_tokens * 2, gateway.capabilities.max_output_tokens)
    settings = replace(gateway.settings, run_max_generation_calls=3)
    gateway, sent = client(settings=settings)
    def call(_):
        try:
            gateway.generate_structured(stage='test', prompt='x', output_model=Answer)
            return True
        except ContextBudgetError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(call, range(12)))
    assert sum(outcomes) == len(sent) == 3
    assert gateway._reserved_calls == 3
    limiter = RpmLimiter(5, max_tokens=100)
    with pytest.raises(ContextBudgetError, match='RUN_CONTEXT_BUDGET_EXHAUSTED'):
        limiter.acquire(tokens=101)


def test_injected_complete_counter_uses_counted_margin_and_version():
    def counter(payload):
        assert payload['messages'][0]['role'] == 'system'
        assert payload['response_format']['json_schema']['schema']['type'] == 'object'
        return TokenMeasurement(input_tokens=12, method='local_tokenizer', certainty='counted',
            counter_version='fixture-complete-v1', included_components=['system','contents','schema','framing'],
            request_fingerprint='pending')
    counter.cache_version = 'fixture-complete-v1'
    settings = get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS':'32768'})
    gateway, _ = client(settings=settings, token_counter=counter)
    prepared = gateway.prepare_structured_request(stage='test', prompt='x', output_model=Answer)
    assert prepared.context.budget.margin == 1639
    assert prepared.context.measurement.certainty == 'counted'
    with pytest.raises(ValidationError):
        prepared.context.measurement.model_copy(update={'certainty':'counted', 'method':'byte_estimate'}).model_validate(
            {'input_tokens':1, 'certainty':'counted', 'method':'byte_estimate', 'counter_version':'x', 'included_components':[], 'request_fingerprint':'x'})


def test_reserved_token_cap_preflight_consumes_no_provider_quota():
    gateway, sent = client(settings=replace(get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS':'32768'}), run_max_reserved_tokens=1))
    with pytest.raises(ContextBudgetError, match='RUN_CONTEXT_BUDGET_EXHAUSTED'):
        gateway.generate_structured(stage='test', prompt='x', output_model=Answer)
    assert not sent and gateway._reserved_calls == 0 and not gateway.limiter._timestamps


def test_planner_falls_back_to_document_digest_and_expands_real_chunks():
    from infrastructure.ingestion.storyboard_planner import plan_storyboard
    from infrastructure.ingestion.chunker import build_chunks
    from contracts.ir1_schema import ValidatedIR1, KnowledgeUnit, EvidenceRef
    units = [KnowledgeUnit(unit_id='u'+str(i), kind='concept', title='Source fact', summary='Source content. '*600,
        section_path=['Intro'], evidence=[EvidenceRef(source_id='b'+str(i), excerpt='Source content.')],
        validation_status='VALIDATED') for i in range(12)]
    ir1 = ValidatedIR1(document_title='Source', units=units)
    chunks = build_chunks(ir1)
    observed = []
    def transport(request, timeout):
        source = json.loads(json.loads(request.data)['messages'][1]['content'])['SOURCE_DATA']
        observed.append(source)
        chunk = source['chunks'][0]
        return Response({'document_title':'Source','slides':[{'slide_id':1,'title':'Source fact','objective':'Explain',
            'narrative_role':'opening','chunk_refs':[chunk['chunk_id']], 'source_unit_ids':chunk['unit_ids'],
            'preferred_layouts':['TITLE_CENTERED']}]})
    gateway, _ = client(transport=transport)
    result = plan_storyboard(ir1, chunks, {'layouts':{'TITLE_CENTERED':{'regions':{}}}}, gateway, min_slides=1, max_slides=1)
    assert observed[0]['chunks'][0]['chunk_id'].startswith('parent_')
    assert set(result.slides[0].chunk_refs) == {c.chunk_id for c in chunks}
    assert any(p.omitted_optional_refs for p in gateway.prepared_contexts.values())


def test_semantic_pairs_pack_and_preserve_completed_judgments():
    from domain.evaluation.claim_verification import judge_semantics
    from infrastructure.ingestion.knowledge_extractor import validate_knowledge_units
    from contracts.ir1_schema import KnowledgeUnit, EvidenceRef
    from contracts.raw_extraction_schema import RawExtraction, SourceBlock
    text = 'Attention uses learned weights. ' * 8
    raw = RawExtraction(document_name='x.txt', blocks=[SourceBlock(block_id='b', text=text, section_path=['S'])])
    units = [KnowledgeUnit(unit_id='u'+str(i), kind='concept', title='Attention', summary=text,
        section_path=['S'], evidence=[EvidenceRef(source_id='b', excerpt=text)]) for i in range(8)]
    accepted, _, _ = validate_knowledge_units(raw, units)
    calls = []
    def transport(request, timeout):
        pairs = json.loads(json.loads(request.data)['messages'][1]['content'])['SOURCE_DATA']
        calls.append(pairs)
        return Response({'judgments':[{'unit_id':p['unit_id'], 'support':'CHECKED', 'reason':'Fixture'} for p in pairs]})
    settings = get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS':'32768', 'LLM_CLAIM_VERIFICATION_INPUT_TOKENS':'1100'})
    gateway, _ = client(settings=settings, transport=transport)
    assert not judge_semantics(raw, accepted, gateway)
    assert len(calls) > 1 and all(u.validation.status=='VERIFIED' for u in accepted)
    assert {p['unit_id'] for batch in calls for p in batch} == {u.unit_id for u in accepted}


def test_adaptive_vision_batches_keep_all_slide_ids_and_hash(tmp_path):
    import re
    from infrastructure.ingestion.visual_reviewer import audit_slide_images
    images = []
    for index in range(4):
        image = tmp_path / (str(index)+'.png'); image.write_bytes(b'fixture'); images.append(str(image))
    calls = []
    def transport(request, timeout):
        body = json.loads(request.data)
        prompt = body['messages'][1]['content'][0]['text']
        ids = json.loads(re.search(r'slide IDs (\[.*?\])', prompt).group(1))
        calls.append(ids)
        return Response({'audits':[{'slide_id':i,'whitespace_balance_score':8,'text_density_score':8,
            'visual_hierarchy_score':8,'contrast_readability_score':8,'passed':True,'critique_summary':'Readable'} for i in ids]})
    gateway, _ = client(capabilities=ProviderCapabilities(context_tokens=10000, image_tokens=1700, image_counter_version='fixture-v1'), transport=transport)
    result = audit_slide_images(images, gateway, artifact_hash='artifact', expected_slide_count=4)
    assert result.status == 'EVALUATED_PASS' and result.artifact_hash == 'artifact'
    assert [i for batch in calls for i in batch] == [1,2,3,4] and len(calls)>1
    assert {r.source_id for p in gateway.prepared_contexts.values() for r in p.refs if r.representation=='pixels'} == {
        'slide_1','slide_2','slide_3','slide_4'}
