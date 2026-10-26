import json
import random
from dataclasses import replace
import pytest
from infrastructure.llm.context_budget import ContextBudgetError
from infrastructure.utils.artifacts import sha256_value
from config.settings import get_multi_agent_settings, TaskBudget
from infrastructure.ingestion.context_fragments import plan_extraction_chunks, initial_fragments, subdivide, combine
from domain.evaluation.coverage_ledger import initialize_ledger, validate_context_coverage
from infrastructure.ingestion.chunker import build_chunks, write_chunks
from contracts.raw_extraction_schema import RawExtraction, SourceBlock, SourceAsset
from contracts.ir1_schema import KnowledgeUnit, ValidatedIR1, EvidenceRef, VisualAsset
from test_context_budget_f07 import client, Answer


def raw_source(text, *, kind='text'):
    return RawExtraction(document_name='source.txt', blocks=[SourceBlock(block_id='b', document_id='doc_'+'a'*64,
        kind=kind, text=text, section_path=['Intro', 'Detail'])])


def factory(gateway):
    def prepare(part, estimate_only=False):
        return gateway.prepare_structured_request(stage='knowledge_extraction', output_model=Answer,
            user_payload={'blocks': [{'id': b.block_id, 'text': b.text} for b in part.blocks],
                'assets': [a.model_dump(mode='json') for a in part.assets]},
            task_budget=TaskBudget(4096), estimate_only=estimate_only)
    return prepare


@pytest.mark.parametrize('capacity', [8192, 16384, 32768])
def test_seeded_huge_unicode_crlf_and_long_run_reconstruct_exactly(capacity):
    random.seed(7021)
    text = ('世界 😀 alpha\r\n' * 7000) + ''.join(random.choice('abcxyz') for _ in range(100001))
    raw = raw_source(text)
    gateway, _ = client(settings=get_multi_agent_settings({'LLM_UNKNOWN_CONTEXT_TOKENS': str(capacity), 'LLM_CONTEXT_COUNT_MODE': 'estimate'}))
    parts = plan_extraction_chunks(raw, factory(gateway), None, gateway.settings)
    spans = sorted([ref.span for p in parts for ref in p.refs])
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(first[1] == second[0] for first, second in zip(spans, spans[1:]))
    assert ''.join(text[s:e] for s,e in spans) == text
    assert sha256_value(''.join(text[s:e] for s,e in spans)) == sha256_value(text)
    for part in parts:
        prepared = factory(gateway)(part)
        assert prepared.context.measurement.input_tokens <= prepared.context.budget.input_ceiling
    again = plan_extraction_chunks(raw, factory(gateway), None, gateway.settings)
    assert [p.chunk().chunk_id for p in parts] == [p.chunk().chunk_id for p in again]


def test_numeric_clause_and_formula_are_indivisible():
    policy = get_multi_agent_settings({})
    for raw in (raw_source('Revenue for Product A is 123 USD in FY2026 ' + 'x'*10000), raw_source('x=y+z'*1000, kind='formula')):
        with pytest.raises(ContextBudgetError, match='INDIVISIBLE_CONTEXT_TOO_LARGE'):
            subdivide(initial_fragments(raw)[0], raw, policy)
    raw = raw_source('Product A revenue is 10 USD in FY2025. Product B revenue is 20 USD in FY2026.')
    parts = subdivide(initial_fragments(raw)[0], raw, policy)
    assert ''.join(b.text for p in parts for b in p.blocks) == raw.blocks[0].text
    assert 'FY2025' in parts[0].blocks[0].text and 'FY2026' in parts[1].blocks[0].text


def test_overlap_has_exact_spans_and_does_not_inflate_primary():
    raw = raw_source('intro repeated passage\r\n' * 100)
    policy = replace(get_multi_agent_settings({}), text_overlap_tokens=20)
    children = subdivide(initial_fragments(raw)[0], raw, policy)
    assert all(p.context_refs for p in children)
    for p in children:
        for ref in p.context_refs:
            assert len(raw.blocks[0].text[slice(*ref.span)].encode('utf-8')) <= 20
    ledger = initialize_ledger(raw)
    chunks = [p.chunk().model_copy(update={'state': 'COMPLETE'}) for p in children]
    assert not validate_context_coverage(raw, chunks, ledger)
    assert ledger.totals['retained']['text_characters'] == len(raw.blocks[0].text)
    assert ledger.totals['dispatched_current_run']['text_characters'] == 0


def test_overlap_evidence_is_supplied_and_removed_before_primary_shrinking():
    from domain.evaluation.coverage_ledger import validate_supplied_evidence
    from infrastructure.ingestion.context_fragments import projected_raw
    raw = raw_source('alpha beta gamma delta epsilon\n' * 30)
    policy = replace(get_multi_agent_settings({}), text_overlap_tokens=40)
    children = subdivide(initial_fragments(raw)[0], raw, policy)
    child = children[0]; ref = child.context_refs[0]
    excerpt = raw.blocks[0].text[slice(*ref.span)]
    unit = KnowledgeUnit(unit_id='u',kind='concept',title='Source',summary=excerpt,
        section_path=['Intro'],evidence=[EvidenceRef(source_id='b',excerpt=excerpt)])
    validate_supplied_evidence([unit], child, raw)
    assert excerpt in projected_raw(raw, child).blocks[0].text
    # An injected final counter verifies this API path separately from byte search.
    calls = []
    gateway, _ = client()
    def prepare(part, estimate_only=False):
        calls.append((len(part.refs),len(part.context_refs)))
        if part.context_refs:
            raise ContextBudgetError('REQUIRED_CONTEXT_TOO_LARGE')
        return factory(gateway)(part, estimate_only)
    # Force initial subdivision, then make only overlap exceed the budget.
    original = prepare
    first = True
    def force(part, estimate_only=False):
        nonlocal first
        if first:
            first = False
            raise ContextBudgetError('REQUIRED_CONTEXT_TOO_LARGE')
        return original(part,estimate_only)
    planned = plan_extraction_chunks(raw, force, None, policy)
    assert any(p.omitted_context_refs for p in planned)
    assert all(not p.context_refs for p in planned)


def test_table_rows_cells_lexemes_and_long_text_projection_preserve_original():
    cells = [{'row': 0, 'column': 0, 'text': 'Name', 'column_header': True},
        {'row': 0, 'column': 1, 'text': 'Value', 'column_header': True},
        {'row': 1, 'column': 0, 'text': 'Product A', 'row_header': True},
        {'row': 1, 'column': 1, 'text': '001', 'lexical_value': '001'},
        {'row': 2, 'column': 0, 'text': 'alpha '*2000},
        {'row': 2, 'column': 1, 'text': '1.2300', 'lexical_value': '1.2300'},
        {'row': 3, 'column': 0, 'text': ''}, {'row': 3, 'column': 1, 'text': '0'}]
    asset = SourceAsset(asset_id='table', kind='table', section_path=['S'], data={'cells': cells, 'rows': [['kept']]})
    raw = RawExtraction(document_name='t.csv', assets=[asset])
    before = raw.model_dump()
    parts = initial_fragments(raw)
    assert parts[1].context_refs
    long = next(p for p in parts if any(r.row == 2 for r in p.refs))
    divided = subdivide(long, raw, get_multi_agent_settings({}))
    textual = next(p for p in divided if p.refs[0].column == 0)
    split = subdivide(textual, raw, get_multi_agent_settings({}))
    others = [p for p in parts if p is not long] + [p for p in divided if p is not textual] + split
    ledger = initialize_ledger(raw)
    assert not validate_context_coverage(raw, [p.chunk().model_copy(update={'state':'COMPLETE'}) for p in others], ledger)
    assert raw.model_dump() == before
    assert ledger.totals['retained']['cells'] == 8
    numeric = next(p for p in divided if p.refs[0].column == 1)
    with pytest.raises(ContextBudgetError, match='INDIVISIBLE_CONTEXT_TOO_LARGE'):
        subdivide(numeric, raw, get_multi_agent_settings({}))


def test_sparse_topic_merge_keeps_full_section_assets_and_document_membership(tmp_path):
    units = [KnowledgeUnit(unit_id='u'+str(i), kind='concept', title='Fact', summary='Fact is supported.',
        evidence=[EvidenceRef(source_id='b'+str(i), excerpt='Fact')], section_path=[section], validation_status='VALIDATED')
        for i,section in enumerate(['A','B'])]
    assets = [VisualAsset(asset_id='a'+str(i), kind='image', section_path=[section], availability='MISSING') for i,section in enumerate(['A','B'])]
    ir1 = ValidatedIR1(document_title='source', units=units, assets=assets)
    chunks = build_chunks(ir1, max_tokens=10000)
    assert len(chunks) == 1 and set(chunks[0].asset_ids) == {'a0','a1'}
    write_chunks(chunks, tmp_path, ir1=ir1)
    richer = json.loads((tmp_path/'context_chunks.json').read_text())['chunks'][0]
    assert richer['section_paths'] == [['A'],['B']]
    assert richer['primary_refs'][0]['representation'] == 'digest'
    assert len(build_chunks(ir1, max_tokens=500)) == 2
    units[0].section_path = ['doc_'+'a'*64+' / Same']
    units[1].section_path = ['doc_'+'b'*64+' / Same']
    assert len(build_chunks(ir1, max_tokens=10000)) == 2
