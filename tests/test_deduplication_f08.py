"""Test suite for F08 Evidence-preserving deduplicator."""
import pytest
from unittest.mock import patch

from infrastructure.ingestion.deduplicator import (
    DuplicatePair,
    DedupResult,
    check_fact_compatibility,
    deduplicate_knowledge_units,
    deduplicate_units,
)
from contracts.ir1_schema import KnowledgeUnit, EvidenceRef, MetricFact


def make_unit(
    unit_id: str,
    title: str,
    summary: str,
    source_id: str = "src_1",
    excerpt: str = "sample text",
    priority: str = "MEDIUM",
    metric_facts: list[MetricFact] | None = None,
) -> KnowledgeUnit:
    return KnowledgeUnit(
        unit_id=unit_id,
        kind="concept" if not metric_facts else "metric",
        title=title,
        summary=summary,
        section_path=["Introduction"],
        priority=priority,
        evidence=[EvidenceRef(source_id=source_id, excerpt=excerpt, kind="excerpt")],
        metric_facts=metric_facts or [],
    )


def test_exact_duplicate_units_merge_and_union_evidence():
    u1 = make_unit("u1", "Market Overview", "The global cloud market is expanding rapidly.", source_id="doc1:p1", excerpt="cloud market expanding")
    u2 = make_unit("u1", "Market Overview", "The global cloud market is expanding rapidly.", source_id="doc2:p5", excerpt="cloud market expanding rapidly")
    
    res = deduplicate_knowledge_units([u1, u2])
    assert len(res.canonical_units) == 1
    assert res.merged_count == 1
    canonical = res.canonical_units[0]
    assert len(canonical.evidence) == 2
    assert {e.source_id for e in canonical.evidence} == {"doc1:p1", "doc2:p5"}


def test_verbatim_content_merges_even_with_different_unit_ids():
    u1 = make_unit("u1", "Growth Highlights", "Revenue increased by 20 percent year over year.", source_id="doc1:p1")
    u2 = make_unit("u2", "Growth Highlights", "Revenue increased by 20 percent year over year.", source_id="doc2:p3")
    
    res = deduplicate_knowledge_units([u1, u2])
    assert len(res.canonical_units) == 1
    assert res.merged_count == 1
    assert res.aliases["u2"] == "u1"
    assert len(res.canonical_units[0].evidence) == 2


def test_paraphrase_merges_with_alias_record():
    u1 = make_unit("u1", "Cloud Adoption", "Enterprise adoption of cloud infrastructure increased significantly.")
    u2 = make_unit("u2", "Cloud Adoption", "Companies adopted cloud infrastructure at an accelerated pace.")
    
    # Using low threshold or mock similarity to verify paraphrase merging
    res = deduplicate_knowledge_units([u1, u2], threshold=0.60)
    assert len(res.canonical_units) == 1
    assert res.merged_count == 1
    assert "u2" in res.aliases
    assert res.aliases["u2"] == "u1"


def test_different_numbers_prevent_merge():
    u1 = make_unit("u1", "Sales Results", "Total sales reached 10 million dollars in 2023.")
    u2 = make_unit("u2", "Sales Results", "Total sales reached 25 million dollars in 2023.")
    
    compat, reason = check_fact_compatibility(u1, u2)
    assert not compat
    assert "Differing numbers" in reason or "Conflicting" in reason

    res = deduplicate_knowledge_units([u1, u2], threshold=0.50)
    assert len(res.canonical_units) == 2
    assert any(p.decision == "REJECTED_INCOMPATIBLE" for p in res.duplicate_pairs)


def test_different_measures_prevent_merge():
    m1 = MetricFact(metric_id="m1", subject="Acme", measure="Revenue", value="10", unit="million", period="2023",
                    evidence=[EvidenceRef(source_id="s1", excerpt="Revenue 10 million")])
    m2 = MetricFact(metric_id="m2", subject="Acme", measure="Net Profit", value="10", unit="million", period="2023",
                    evidence=[EvidenceRef(source_id="s2", excerpt="Profit 10 million")])
    
    u1 = make_unit("u1", "Financial Performance", "Acme reported Revenue of 10 million in 2023.", metric_facts=[m1])
    u2 = make_unit("u2", "Financial Performance", "Acme reported Net Profit of 10 million in 2023.", metric_facts=[m2])
    
    compat, reason = check_fact_compatibility(u1, u2)
    assert not compat
    assert "distinct measures" in reason

    res = deduplicate_knowledge_units([u1, u2], threshold=0.50)
    assert len(res.canonical_units) == 2


def test_different_time_periods_prevent_merge():
    m1 = MetricFact(metric_id="m1", subject="Acme", measure="Revenue", value="50", unit="million", period="2022",
                    evidence=[EvidenceRef(source_id="s1", excerpt="2022 revenue 50")])
    m2 = MetricFact(metric_id="m2", subject="Acme", measure="Revenue", value="50", unit="million", period="2023",
                    evidence=[EvidenceRef(source_id="s2", excerpt="2023 revenue 50")])
    
    u1 = make_unit("u1", "Revenue 2022", "Revenue was 50 million in 2022.", metric_facts=[m1])
    u2 = make_unit("u2", "Revenue 2023", "Revenue was 50 million in 2023.", metric_facts=[m2])
    
    compat, reason = check_fact_compatibility(u1, u2)
    assert not compat
    assert "periods" in reason.lower()

    res = deduplicate_knowledge_units([u1, u2], threshold=0.50)
    assert len(res.canonical_units) == 2


def test_opposing_polarity_prevents_merge():
    u1 = make_unit("u1", "System Migration", "The database migration succeeded without downtime.")
    u2 = make_unit("u2", "System Migration", "The database migration failed with critical downtime.")
    
    compat, reason = check_fact_compatibility(u1, u2)
    assert not compat
    assert "negation" in reason.lower() or "polarity" in reason.lower()

    res = deduplicate_knowledge_units([u1, u2], threshold=0.50)
    assert len(res.canonical_units) == 2


def test_priority_escalation_on_merge():
    u1 = make_unit("u1", "Core Finding", "Latency was reduced by 40 percent.", priority="LOW")
    u2 = make_unit("u2", "Core Finding", "Latency was reduced by 40 percent.", priority="CRITICAL")
    
    res = deduplicate_knowledge_units([u1, u2])
    assert len(res.canonical_units) == 1
    assert res.canonical_units[0].priority == "CRITICAL"


def test_ambiguous_pairs_retained_in_report():
    u1 = make_unit("u1", "Architecture", "The model utilizes multi-head self-attention mechanisms.")
    u2 = make_unit("u2", "Architecture", "Attention layers allow modeling arbitrary relationships.")
    
    res = deduplicate_knowledge_units([u1, u2], threshold=0.95, ambiguous_threshold=0.30)
    assert len(res.canonical_units) == 2
    ambiguous = [p for p in res.duplicate_pairs if p.decision == "AMBIGUOUS_RETAINED"]
    assert len(ambiguous) >= 1


def test_embedding_failure_falls_back_to_exact():
    u1 = make_unit("u1", "Title A", "Summary A")
    u2 = make_unit("u2", "Title B", "Summary B")
    
    with patch("pipeline.deduplicator._compute_similarity_matrix", return_value=(None, "exact_fallback")):
        res = deduplicate_knowledge_units([u1, u2])
        assert res.mode == "exact_fallback"
        assert len(res.canonical_units) == 2


def test_empty_input_handled_gracefully():
    res = deduplicate_knowledge_units([])
    assert res.canonical_units == []
    assert res.aliases == {}
    assert res.merged_count == 0


def test_backward_compatible_function():
    u1 = make_unit("u1", "Test", "Test summary.")
    u2 = make_unit("u2", "Test", "Test summary.")
    canonical = deduplicate_units([u1, u2])
    assert len(canonical) == 1


def test_transitive_alias_flattening():
    # u2 verbatim matches u3 -> u3 aliased to u2
    # u1 semantically matches u2 -> u2 merged into u1
    u1 = make_unit("u1", "Cloud Infrastructure", "Enterprise cloud migration is increasing rapidly.")
    u2 = make_unit("u2", "Cloud Infrastructure", "Enterprise cloud migration is expanding quickly.")
    u3 = make_unit("u3", "Cloud Infrastructure", "Enterprise cloud migration is expanding quickly.")
    res = deduplicate_knowledge_units([u1, u2, u3], threshold=0.60)
    assert len(res.canonical_units) == 1
    assert res.canonical_units[0].unit_id == "u1"
    # Both u2 and u3 must resolve directly to canonical u1 (not a chain)
    assert res.aliases["u2"] == "u1"
    assert res.aliases["u3"] == "u1"


def test_structured_data_union_on_merge():
    u1 = make_unit("u1", "Market Report", "Market is growing.")
    u1.structured_data = {"category": "Tech", "region": "Global"}
    u2 = make_unit("u2", "Market Report", "Market is growing.")
    u2.structured_data = {"category": "Tech", "growth_rate": "15%"}

    res = deduplicate_knowledge_units([u1, u2])
    assert len(res.canonical_units) == 1
    merged = res.canonical_units[0]
    assert merged.structured_data == {"category": "Tech", "region": "Global", "growth_rate": "15%"}
