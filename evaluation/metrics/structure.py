def evaluate(profile, concepts):
    nodes = profile["source_graph"]["nodes"]
    found = {r["concept_id"]: r["best_slide"] for r in concepts if r["status"] != "MISSING" and r["best_slide"]}
    node = len(found) / max(1, len(nodes))
    edges = profile["source_graph"]["edges"]
    preserved = sum(a in found and b in found and abs(found[a] - found[b]) <= 1 for a, b, *_ in edges)
    edge = preserved / max(1, len(edges))
    pairs = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if a in found and b in found]
    order = sum(found[a] <= found[b] for a, b in pairs) / max(1, len(pairs))
    return {"node_coverage": node, "edge_coverage": edge, "order_preservation": order, "structural_score": .5 * node + .3 * edge + .2 * order}
