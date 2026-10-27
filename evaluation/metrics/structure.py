DECLARED_WEIGHTS = {'nodes': .5, 'edges': .3, 'order': .2}


def _f1(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else None


def _normalized(edge):
    edge = tuple(edge)
    return edge[:2] + ((edge[2],) if len(edge) > 2 else (None,))


def evaluate(profile, concepts, candidate_nodes=None, candidate_edges=None):
    graph = profile['source_graph']
    weights = {c['concept_id']: c.get('weight', 1) for c in profile.get('concepts', [])}
    matched = {r['concept_id']: r['best_slide'] for r in concepts if r['status'] != 'MISSING' and r['best_slide']}
    nodes = graph['nodes']
    tp_v = sum(weights.get(n, 1) for n in nodes if n in matched)
    fn_v = sum(weights.get(n, 1) for n in nodes if n not in matched)
    # Candidate nodes with no reference counterpart are false positives at the default weight.
    fp_v = sum(1 for n in (candidate_nodes or []) if n not in matched)
    reference_edges = [_normalized(e) for e in graph['edges']]
    asserted_edges = [_normalized(e) for e in (candidate_edges or [])]
    tp_e = sum(1 for e in reference_edges if e in asserted_edges)
    fn_e = len(reference_edges) - tp_e
    fp_e = sum(1 for e in asserted_edges if e not in reference_edges)
    order_pairs = [tuple(p) for p in profile.get('order_pairs') or []]
    assessable = [(u, v) for u, v in order_pairs if u in matched and v in matched]
    order = sum(matched[u] < matched[v] for u, v in assessable) / len(assessable) if assessable else None
    components = {
        'nodes': {'status': 'EVALUATED' if tp_v + fp_v + fn_v else 'NOT_APPLICABLE',
                  'value': _f1(tp_v, fp_v, fn_v), 'counts': {'tp': tp_v, 'fp': fp_v, 'fn': fn_v}},
        'edges': {'status': 'EVALUATED' if reference_edges or asserted_edges else 'NOT_APPLICABLE',
                  'value': _f1(tp_e, fp_e, fn_e), 'counts': {'tp': tp_e, 'fp': fp_e, 'fn': fn_e}},
        # An order task with no retained endpoints stays unassessed; it is never credited as satisfied.
        'order': {'status': 'NOT_APPLICABLE' if not order_pairs else 'EVALUATED' if assessable else 'NOT_EVALUATED',
                  'value': order, 'counts': {'assessed': len(assessable), 'total': len(order_pairs)}},
    }
    effective = {name: w for name, w in DECLARED_WEIGHTS.items() if components[name]['status'] != 'NOT_APPLICABLE'}
    total = sum(effective.values())
    score = sum(effective[name] * (components[name]['value'] or 0) for name in effective) / total if total else None
    return {'node_coverage': components['nodes']['value'], 'edge_coverage': components['edges']['value'],
            'order_preservation': components['order']['value'], 'structural_score': score,
            'components': components, 'effective_profile': {name: w / total for name, w in effective.items()} if total else {},
            'status': 'EVALUATED' if total else 'NOT_APPLICABLE'}
