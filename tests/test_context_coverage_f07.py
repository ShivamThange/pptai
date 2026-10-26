"""Progressive extraction, scoped grounding, recovery and revision integration."""
import json
from dataclasses import replace
from pathlib import Path
import pytest
from config.settings import get_multi_agent_settings
from infrastructure.utils.artifacts import CheckpointCache, sha256_value
from infrastructure.llm.context_budget import ContextBudgetError
from infrastructure.llm.llm_client import LLMClient, LLMBudgetError
from infrastructure.ingestion.knowledge_extractor import generate_validated_ir1, KnowledgeUnit, KnowledgeUnitBatch, KnowledgeUnitDraft
from infrastructure.ingestion.context_fragments import initial_fragments, subdivide
from infrastructure.ingestion.coverage_ledger import initialize_ledger, validate_context_coverage, validate_supplied_evidence, record_call_outcome
from contracts.context_schema import CoverageEvent, ContextCallRecord, CoverageLedger, ContextChunk
from contracts.ir1_schema import EvidenceRef
from contracts.raw_extraction_schema import RawExtraction, SourceBlock
from test_context_budget_f07 import Response


class SourceClient(LLMClient):
    """Fixture answers pass the real preparation/gateway/grounding machinery."""
    cache_version = 'f07-source-fixture-v1'
    def __init__(self, *, capacity=65536, output_tokens=1792, **kwargs):
        settings = kwargs.pop('settings', get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS': str(capacity),
            'LLM_CONTEXT_COUNT_MODE': 'estimate', 'LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS': str(output_tokens)}))
        self.requests = []
        self.fail_at = None
        self.empty = False
        self.unsent = False
        self.source_raw = None
        super().__init__(api_key='fixture-key', settings=settings, transport=self.respond, max_calls_per_minute=9999, **kwargs)
    def respond(self, request, timeout):
        import urllib.error
        payload = json.loads(request.data)
        self.requests.append(payload)
        if self.fail_at == len(self.requests):
            raise urllib.error.HTTPError('fixture', 402, 'billing', {}, None)
        source = json.loads(payload['messages'][1]['content'])['SOURCE_DATA']
        units = []
        if not self.empty:
            for block in source['blocks']:
                units.append(KnowledgeUnitDraft(kind='concept', title='Source passage', summary=block['text'],
                    evidence=[EvidenceRef(source_id=block['id'], excerpt='Unsent source passage' if self.unsent else block['text'])]))
            for asset in source['assets']:
                for cell in (asset.get('data') or {}).get('cells', []):
                    if cell.get('column_header') or cell.get('row_header') or not str(cell['text']).strip():
                        continue
                    ref = EvidenceRef(source_id=asset['id'], kind='cell', row=cell['row'], column=cell['column'], excerpt=cell['text'])
                    from domain.evaluation.claim_verification import evidence_text
                    raw = self.source_raw or getattr(self, 'context_source', None)
                    support, _ = evidence_text(raw, [ref]) if raw else ([cell['text']], [])
                    units.append(KnowledgeUnitDraft(kind='concept', title='Source cell', summary=support[0], evidence=[ref]))
        return Response({'units': [u.model_dump(mode='json') for u in units]})


def raw_source(count=8):
    return RawExtraction(document_name='source.txt', blocks=[SourceBlock(block_id='b'+str(i),
        document_id='doc_'+'a'*64, text='Attention combines values using learned weights. '*2, section_path=['Intro']) for i in range(count)])


def test_full_small_source_one_call_and_output_risk_forces_progressive(tmp_path):
    raw = raw_source(1); gateway = SourceClient(output_tokens=4096)
    ir1 = generate_validated_ir1(raw, gateway, tmp_path/'small')
    assert len(gateway.requests) == 1 and ir1.completeness == 'BASIC_CHECKED'
    raw = raw_source(8); gateway = SourceClient(output_tokens=1792)
    ir1 = generate_validated_ir1(raw, gateway, tmp_path/'large')
    assert len(gateway.requests) == 4 and len(ir1.units) == 8
    ledger = CoverageLedger.model_validate_json((tmp_path/'large/context_coverage.json').read_text())
    assert ledger.context_completeness == 'complete'
    assert ledger.totals['all_text_dispatched_current_run'] is True
    assert all(p['messages'][0] == gateway.requests[0]['messages'][0] for p in gateway.requests)


def test_mid_failure_preserves_success_and_resume_only_missing(tmp_path):
    raw = raw_source(8); gateway = SourceClient()
    cache = CheckpointCache(tmp_path/'.cache', reuse=True)
    gateway.fail_at = 2
    with pytest.raises(LLMBudgetError):
        generate_validated_ir1(raw, gateway, tmp_path/'run', checkpoint_cache=cache)
    failed = CoverageLedger.model_validate_json((tmp_path/'run/context_coverage.json').read_text())
    assert len(gateway.requests) == 2
    assert failed.events[-1].dimension == 'failed'
    assert len(list((tmp_path/'.cache').glob('*.json'))) == 1
    gateway = SourceClient()
    ir1 = generate_validated_ir1(raw, gateway, tmp_path/'run', checkpoint_cache=cache)
    assert len(gateway.requests) == 3 and len(ir1.units) == 8
    ledger = CoverageLedger.model_validate_json((tmp_path/'run/context_coverage.json').read_text())
    assert any(c.outcome == 'CACHE_REUSED' for c in ledger.calls)
    assert ledger.totals['dispatched_historical']['text_characters'] > 0
    assert ledger.totals['all_text_dispatched_current_run'] is False
    gateway = SourceClient()
    generate_validated_ir1(raw, gateway, tmp_path/'all-cached', checkpoint_cache=cache)
    assert not gateway.requests
    ledger = CoverageLedger.model_validate_json((tmp_path/'all-cached/context_coverage.json').read_text())
    assert ledger.totals['dispatched_current_run']['text_characters'] == 0


def test_unsupplied_excerpt_and_foreign_fragment_cannot_certify_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv('VALIDATE_SUPPLIED_EVIDENCE', 'true')
    raw = raw_source(1); gateway = SourceClient(); gateway.unsent = True
    with pytest.raises(ContextBudgetError, match='UNSUPPLIED_EVIDENCE'):
        generate_validated_ir1(raw, gateway, tmp_path)
    part = initial_fragments(raw)[0]
    part.refs[0].document_id = 'foreign'
    assert validate_context_coverage(raw, [part.chunk().model_copy(update={'state':'COMPLETE'})], initialize_ledger(raw))
    part = initial_fragments(raw)[0]
    part.refs[0].projection_hash = 'tampered'
    assert validate_context_coverage(raw, [part.chunk().model_copy(update={'state':'COMPLETE'})], initialize_ledger(raw))


def test_empty_outputs_do_not_cover_failed_siblings(tmp_path):
    raw = raw_source(2); gateway = SourceClient(); gateway.empty = True
    with pytest.raises(ContextBudgetError, match='OUTPUT_INCOMPLETE'):
        generate_validated_ir1(raw, gateway, tmp_path)
    ledger = CoverageLedger.model_validate_json((tmp_path/'context_coverage.json').read_text())
    assert ledger.context_completeness == 'incomplete'
    assert not any(e.dimension == 'processed' for e in ledger.events)


def test_overlap_duplicate_events_and_digests_do_not_inflate_dispatch():
    raw = raw_source(1); part = initial_fragments(raw)[0]; ledger = initialize_ledger(raw)
    ref = part.refs[0]
    for _ in range(3):
        ledger.events.append(CoverageEvent(dimension='dispatched', refs=[ref], stage='knowledge_extraction'))
    digest = ref.model_copy(update={'representation':'digest'})
    ledger.events.append(CoverageEvent(dimension='dispatched', refs=[digest], stage='storyboard_planning'))
    chunks = [part.chunk().model_copy(update={'state':'COMPLETE'})]
    assert not validate_context_coverage(raw, chunks, ledger)
    assert ledger.totals['dispatched_current_run']['text_characters'] == len(raw.blocks[0].text)
    ledger = initialize_ledger(raw)
    ledger.events.append(CoverageEvent(dimension='dispatched', refs=[digest], stage='storyboard_planning'))
    validate_context_coverage(raw, chunks, ledger)
    assert ledger.totals['dispatched_current_run']['text_characters'] == 0


def test_source_passages_zero_extraction_dispatch_and_legacy_unknown(tmp_path):
    gateway = SourceClient()
    generate_validated_ir1(raw_source(1), gateway, tmp_path, extraction_mode='source-passages')
    assert not gateway.requests
    ledger = CoverageLedger.model_validate_json((tmp_path/'context_coverage.json').read_text())
    assert ledger.totals['processed_current_run']['text_characters'] > 0
    assert ledger.totals['dispatched_current_run']['text_characters'] == 0
    assert ledger.semantic_completeness == 'basic_checked'


def test_changed_capacity_invalidates_extraction_cache(tmp_path):
    raw = raw_source(1); cache = CheckpointCache(tmp_path/'.cache', reuse=True)
    first = SourceClient(); generate_validated_ir1(raw, first, tmp_path/'one', checkpoint_cache=cache)
    changed = SourceClient(capacity=131072); generate_validated_ir1(raw, changed, tmp_path/'two', checkpoint_cache=cache)
    assert len(changed.requests) == 1


def test_fragment_grounding_repair_is_scoped_and_recounted(tmp_path, monkeypatch):
    monkeypatch.setenv('VALIDATE_FRAGMENT_GROUNDING', 'true')
    gateway = SourceClient(); original = gateway.respond
    def respond(request, timeout):
        gateway.unsent = len(gateway.requests) == 0
        return original(request, timeout)
    gateway._transport = respond
    generate_validated_ir1(raw_source(1), gateway, tmp_path, max_section_retries=1)
    assert len(gateway.requests) == 2
    assert gateway.requests[0]['messages'][0] == gateway.requests[1]['messages'][0]
    assert gateway.requests[0]['messages'][1] != gateway.requests[1]['messages'][1]
    ledger = CoverageLedger.model_validate_json((tmp_path/'context_coverage.json').read_text())
    assert [c.outcome for c in ledger.calls] == ['FAILED','PASSED']
    assert ledger.calls[0].preparation_hash != ledger.calls[1].preparation_hash


def test_proven_context_overflow_never_retries_unchanged_request(tmp_path):
    import io
    import urllib.error
    gateway = SourceClient(); original = gateway.respond
    first = True
    def respond(request, timeout):
        nonlocal first
        if first:
            first = False
            gateway.requests.append(json.loads(request.data))
            raise urllib.error.HTTPError('fixture', 400, 'too large', {},
                io.BytesIO(b'{"error":{"code":"context_length_exceeded"}}'))
        return original(request, timeout)
    gateway._transport = respond
    # Halving an already-small complete request can make fixed instructions
    # indivisible. It must stop after the one proven-overflow attempt.
    with pytest.raises(ContextBudgetError):
        generate_validated_ir1(raw_source(1), gateway, tmp_path)
    assert len(gateway.requests) == 1


def test_r03_scoped_retry_preserves_other_completed_context_chunks(tmp_path):
    gateway = SourceClient(); original = gateway.respond
    def respond(request, timeout):
        response = original(request, timeout)
        if len(gateway.requests) == 1:
            units = json.loads(response.body['choices'][0]['message']['content'])['units']
            return Response({'units':units[:1]})
        return response
    gateway._transport = respond
    ir1 = generate_validated_ir1(raw_source(4), gateway, tmp_path, max_section_retries=1)
    assert len(ir1.units) == 4 and len(gateway.requests) == 3
    from contracts.context_schema import ContextChunksArtifact
    artifact = ContextChunksArtifact.model_validate_json((tmp_path/'extraction_chunks.json').read_text())
    ledger = CoverageLedger.model_validate_json((tmp_path/'context_coverage.json').read_text())
    assert not validate_context_coverage(raw_source(4), artifact.chunks, ledger)


def test_failed_terminal_obligation_is_accounted_but_extraction_incomplete():
    raw = raw_source(1)
    chunk = initial_fragments(raw)[0].chunk(); chunk.state = 'FAILED'
    ledger = initialize_ledger(raw)
    assert validate_context_coverage(raw, [chunk], ledger)
    assert ledger.totals['all_required_extraction_obligations_accounted'] is True
    assert ledger.context_completeness == 'incomplete'
