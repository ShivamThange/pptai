"""F19 metric property tests: counterexamples and formal score definitions.

Blank slides and degenerate graphs must fail or renormalize explicitly instead
of receiving fabricated credit from empty denominators.
"""
import pytest

from evaluation.config import load
from evaluation.metrics.faithfulness import ClaimVerdict, evaluate as evaluate_faithfulness
from evaluation.metrics.structure import evaluate as evaluate_structure
from evaluation.metrics.visual import evaluate as evaluate_visual


def shape(shape_id, left, top, width, height, *, role='body', text='', font_sizes=(), **extra):
    box = {'shape_id': shape_id, 'left': left, 'top': top, 'width': width, 'height': height,
           'is_line': False, 'text': text, 'font_sizes': list(font_sizes), 'font_names': [],
           'role': role, 'z_order': 0, 'container_id': None}
    box.update(extra)
    return box


def slide(shapes, slide_no=1, word_count=0, text=''):
    return {'slide_no': slide_no, 'shapes': shapes, 'word_count': word_count, 'text': text}


def test_blank_slide_scores_zero_and_fails():
    rows, summary = evaluate_visual([slide([])], 10, 7.5, load())
    assert rows[0]['components']['density'] == 0
    assert rows[0]['score'] == 0
    assert 'balance_offset' not in rows[0]
    assert summary['status'] == 'EVALUATED_FAIL'


def test_outside_area_fraction_bounds_score():
    box = shape('s1', 8, 0, 4, 5)
    rows, _ = evaluate_visual([slide([box])], 10, 10, load())
    assert rows[0]['out_of_bounds_count'] == 1
    assert rows[0]['components']['bounds'] == pytest.approx(0.5)


def test_fully_coincident_text_fails_overlap():
    boxes = [shape('s1', 0, 0, 4, 4, text='hello world', font_sizes=[16]),
             shape('s2', 0, 0, 4, 4, text='hello world', font_sizes=[16])]
    rows, summary = evaluate_visual([slide(boxes)], 10, 10, load())
    assert len(rows[0]['overlap_pairs']) == 1
    assert rows[0]['components']['overlap'] == pytest.approx(0.5)
    assert summary['status'] == 'EVALUATED_FAIL'


def test_declared_containment_is_not_overlap():
    container = shape('g1', 0, 0, 8, 8, role='container')
    child = shape('s1', 1, 1, 2, 2, text='x', font_sizes=[16], container_id='g1')
    rows, _ = evaluate_visual([slide([container, child])], 10, 10, load())
    assert rows[0]['overlap_pairs'] == []
    assert rows[0]['components']['overlap'] == 1


def test_density_uses_union_area_not_summed_area():
    boxes = [shape('s1', 0, 0, 10, 5), shape('s2', 0, 3, 10, 5)]
    rows, _ = evaluate_visual([slide(boxes)], 10, 10, load())
    assert rows[0]['density_ratio'] == pytest.approx(0.8)
    assert rows[0]['components']['density'] == 1


def test_decorative_background_does_not_inflate_density():
    background = shape('bg', 0, 0, 10, 10, role='background', z_order=0)
    content = shape('s1', 0, 0, 4, 4, text='x', font_sizes=[16], z_order=1)
    rows, _ = evaluate_visual([slide([background, content])], 10, 10, load())
    assert rows[0]['density_ratio'] == pytest.approx(0.16)
    assert rows[0]['components']['density'] == 1


def concept(concept_id, status, best_slide, weight=1):
    return {'concept_id': concept_id, 'status': status, 'best_slide': best_slide, 'weight': weight}


def profile(nodes, edges, concepts, order_pairs=None):
    return {'reference_id': 'ref', 'concepts': [{'concept_id': n, 'weight': w} for n, w in concepts],
            'source_graph': {'nodes': nodes, 'edges': edges},
            **({'order_pairs': order_pairs} if order_pairs else {})}


def test_single_node_graph_retained_scores_one():
    prof = profile(['C1'], [], [('C1', 3)])
    result = evaluate_structure(prof, [concept('C1', 'COVERED', 1, 3)])
    assert result['node_coverage'] == pytest.approx(1.0)
    assert result['components']['edges']['status'] == 'NOT_APPLICABLE'
    assert result['components']['order']['status'] == 'NOT_APPLICABLE'
    assert result['effective_profile'] == {'nodes': 1.0}
    assert result['structural_score'] == pytest.approx(1.0)


def test_single_node_graph_missing_scores_zero():
    prof = profile(['C1'], [], [('C1', 3)])
    result = evaluate_structure(prof, [concept('C1', 'MISSING', None, 3)])
    assert result['structural_score'] == 0


def test_node_f1_penalizes_unmatched_candidate_nodes():
    prof = profile(['C1', 'C2'], [], [('C1', 1), ('C2', 1)])
    concepts = [concept('C1', 'COVERED', 1), concept('C2', 'COVERED', 2)]
    result = evaluate_structure(prof, concepts, candidate_nodes=['X1'])
    assert result['node_coverage'] == pytest.approx(0.8)


def test_reversed_directed_edge_is_not_preserved():
    prof = profile(['C1', 'C2'], [['C1', 'C2', 'dependency']], [('C1', 1), ('C2', 1)])
    concepts = [concept('C1', 'COVERED', 1), concept('C2', 'COVERED', 2)]
    result = evaluate_structure(prof, concepts, candidate_edges=[['C2', 'C1', 'dependency']])
    assert result['edge_coverage'] == 0
    assert result['components']['edges']['counts'] == {'tp': 0, 'fp': 1, 'fn': 1}


def test_adjacency_without_assertion_is_not_an_edge():
    prof = profile(['C1', 'C2'], [['C1', 'C2', 'dependency']], [('C1', 1), ('C2', 1)])
    concepts = [concept('C1', 'COVERED', 1), concept('C2', 'COVERED', 2)]
    result = evaluate_structure(prof, concepts)
    assert result['edge_coverage'] == 0


def test_asserted_edge_preserved_scores_one():
    prof = profile(['C1', 'C2'], [['C1', 'C2', 'dependency']], [('C1', 1), ('C2', 1)])
    concepts = [concept('C1', 'COVERED', 1), concept('C2', 'COVERED', 2)]
    result = evaluate_structure(prof, concepts, candidate_edges=[['C1', 'C2', 'dependency']])
    assert result['edge_coverage'] == pytest.approx(1.0)
    assert result['structural_score'] == pytest.approx(1.0)


def test_order_pairs_score_declared_precedence_only():
    prof = profile(['C1', 'C2'], [], [('C1', 1), ('C2', 1)], order_pairs=[['C1', 'C2']])
    retained = [concept('C1', 'COVERED', 1), concept('C2', 'COVERED', 2)]
    assert evaluate_structure(prof, retained)['order_preservation'] == pytest.approx(1.0)
    reversed_slides = [concept('C1', 'COVERED', 2), concept('C2', 'COVERED', 1)]
    result = evaluate_structure(prof, reversed_slides)
    assert result['order_preservation'] == 0
    assert result['structural_score'] == pytest.approx(5 / 7)


class SequenceJudge:
    def __init__(self, labels, fail_after=None):
        self.labels = list(labels)
        self.fail_after = fail_after if fail_after is not None else len(self.labels)
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        if self.calls > self.fail_after:
            raise RuntimeError('Judge unavailable')
        return ClaimVerdict(label=self.labels[self.calls - 1], explanation='fixture')


CLAIM_SLIDES = [{'slide_no': 1, 'text': ' '.join([
    'Revenue was 10 USD.', 'Profit was 20 USD.', 'Costs reached 30 USD.',
    'Margin stayed 40 percent.', 'Headcount hit 50 people.'])}]
CHUNKS = [{'chunk_id': 's1', 'text': 'Revenue was 10 USD. Profit was 20 USD.'}]


def test_unassessed_claims_widen_full_deck_interval():
    judge = SequenceJudge(['SUPPORTED', 'SUPPORTED', 'PARTIALLY_SUPPORTED', 'UNSUPPORTED'], fail_after=4)
    records, summary = evaluate_faithfulness(CLAIM_SLIDES, CHUNKS, load(), caller=judge)
    assert summary['status'] == 'FAILED'
    assert len(records) == 4
    assert summary['score'] == pytest.approx(0.625)
    assert summary['assessment_completeness'] == pytest.approx(0.8)
    assert summary['interval'] == [pytest.approx(0.5), pytest.approx(0.7)]
    assert summary['hallucination_rate'] == pytest.approx(0.25)


def test_fully_assessed_interval_collapses_to_point():
    judge = SequenceJudge(['SUPPORTED', 'SUPPORTED'])
    slides = [{'slide_no': 1, 'text': 'Revenue was 10 USD. Profit was 20 USD.'}]
    _, summary = evaluate_faithfulness(slides, CHUNKS, load(), caller=judge)
    assert summary['status'] == 'COMPLETED'
    assert summary['score'] == pytest.approx(1.0)
    assert summary['assessment_completeness'] == pytest.approx(1.0)
    assert summary['interval'] == [pytest.approx(1.0), pytest.approx(1.0)]


def test_no_evidence_leaves_interval_unbounded():
    slides = [{'slide_no': 1, 'text': 'Revenue was 10 USD.'}]
    _, summary = evaluate_faithfulness(slides, [], load(), caller=SequenceJudge([]))
    assert summary['status'] == 'FAILED'
    assert summary['score'] is None
    assert summary['assessment_completeness'] == 0
    assert summary['interval'] == [0.0, 1.0]


def test_no_factual_claims_is_not_applicable():
    _, summary = evaluate_faithfulness([{'slide_no': 1, 'text': 'Title only.'}], [], load(), caller=SequenceJudge([]))
    assert summary['status'] == 'NOT_APPLICABLE'
    assert summary['score'] is None
    assert summary['claim_count'] == 0
