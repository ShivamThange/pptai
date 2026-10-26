"""F08 Evidence-preserving semantic deduplicator.

Merges repeated equivalent statements while retaining all source references,
building alias maps, and keeping contradictory or differently scoped claims distinct.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Iterable, Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from schemas.ir1_schema import EvidenceRef, KnowledgeUnit, MetricFact
from tools.claim_verification import mentions, normalize

NEGATION_TERMS = frozenset({"not", "no", "never", "none", "neither", "nor", "cannot"})
OPPOSING_VERB_PAIRS = [
    ({"succeeded", "success", "successful", "passed", "approved"}, {"failed", "failure", "unsuccessful", "denied", "rejected"}),
    ({"increased", "increase", "growth", "rose", "grew"}, {"decreased", "decrease", "decline", "fell", "dropped"}),
    ({"improved", "improvement", "positive"}, {"worsened", "negative", "deteriorated"}),
]
PRIORITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class DuplicatePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id_a: str
    unit_id_b: str
    similarity_score: float
    decision: Literal["MERGED", "REJECTED_INCOMPATIBLE", "AMBIGUOUS_RETAINED"]
    reason: str


class DedupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_units: list[KnowledgeUnit]
    aliases: dict[str, str] = Field(default_factory=dict)
    duplicate_pairs: list[DuplicatePair] = Field(default_factory=list)
    merged_count: int = 0
    mode: Literal["semantic_hybrid", "exact_fallback"] = "exact_fallback"


def _has_opposing_polarity(text_a: str, text_b: str) -> bool:
    """Detect whether texts have opposing negation or antonym polarity."""
    words_a = set(re.findall(r"\b[a-z']+\b", text_a.casefold()))
    words_b = set(re.findall(r"\b[a-z']+\b", text_b.casefold()))
    neg_a = bool(words_a & NEGATION_TERMS) or any(w.endswith("n't") for w in words_a)
    neg_b = bool(words_b & NEGATION_TERMS) or any(w.endswith("n't") for w in words_b)
    if neg_a != neg_b:
        return True
    for pos_set, neg_set in OPPOSING_VERB_PAIRS:
        if (words_a & pos_set and words_b & neg_set) or (words_a & neg_set and words_b & pos_set):
            return True
    return False


def check_fact_compatibility(unit_a: KnowledgeUnit, unit_b: KnowledgeUnit) -> tuple[bool, str]:
    """Verify that two candidate units do not assert conflicting facts or scopes."""
    text_a = f"{unit_a.title} {unit_a.summary}"
    text_b = f"{unit_b.title} {unit_b.summary}"

    # 1. Opposing polarity check
    if _has_opposing_polarity(text_a, text_b):
        return False, "Opposing negation or sentiment polarity detected between claims"

    # 2. Metric facts compatibility cross-check
    for m_a in unit_a.metric_facts:
        for m_b in unit_b.metric_facts:
            subj_a, subj_b = normalize(m_a.subject), normalize(m_b.subject)
            meas_a, meas_b = normalize(m_a.measure), normalize(m_b.measure)
            val_a, val_b = str(m_a.value).strip(), str(m_b.value).strip()
            unit_val_a, unit_val_b = normalize(m_a.unit or ""), normalize(m_b.unit or "")
            period_a, period_b = normalize(m_a.period or ""), normalize(m_b.period or "")

            # Same subject and measure, but different value -> contradiction / distinct facts
            if subj_a == subj_b and meas_a == meas_b:
                if val_a != val_b:
                    return False, f"Conflicting metric values for {m_a.subject} {m_a.measure}: {val_a} vs {val_b}"
                if unit_val_a != unit_val_b:
                    return False, f"Conflicting metric units for {m_a.subject} {m_a.measure}: {unit_val_a} vs {unit_val_b}"
                if period_a != period_b and period_a and period_b:
                    return False, f"Different metric periods for {m_a.subject} {m_a.measure}: {period_a} vs {period_b}"

            # Same value, but different subjects or measures -> different facts (e.g. $10M Revenue vs $10M Profit)
            if val_a == val_b and (subj_a != subj_b or meas_a != meas_b):
                if subj_a and subj_b and subj_a != subj_b:
                    return False, f"Same value {val_a} belongs to distinct subjects: {m_a.subject} vs {m_b.subject}"
                if meas_a and meas_b and meas_a != meas_b:
                    return False, f"Same value {val_a} belongs to distinct measures: {m_a.measure} vs {m_b.measure}"

    # 3. Numeric text mentions compatibility
    num_a = mentions(text_a)
    num_b = mentions(text_b)
    if num_a and num_b:
        for item_a in num_a:
            for item_b in num_b:
                if item_a.label and item_b.label and (item_a.label & item_b.label):
                    if item_a.value != item_b.value:
                        return False, f"Differing numbers {item_a.value} vs {item_b.value} for shared topic {item_a.label & item_b.label}"
                    if item_a.period and item_b.period and item_a.period != item_b.period:
                        return False, f"Differing periods {item_a.period} vs {item_b.period} for number {item_a.value}"

    return True, "Compatible"


def _union_evidence(evidence_a: list[EvidenceRef], evidence_b: list[EvidenceRef]) -> list[EvidenceRef]:
    """Union source citations deterministically without duplicates."""
    by_key: dict[tuple, EvidenceRef] = {}
    for ref in [*evidence_a, *evidence_b]:
        key = (ref.source_id, ref.kind, ref.row, ref.column, normalize(ref.excerpt))
        if key not in by_key:
            by_key[key] = ref
    return list(by_key.values())


def _merge_two_units(canonical: KnowledgeUnit, absorbed: KnowledgeUnit) -> KnowledgeUnit:
    """Merge absorbed unit into canonical unit, updating evidence, facts, and priority."""
    canonical.evidence = _union_evidence(canonical.evidence, absorbed.evidence)
    canonical.priority = min((canonical.priority, absorbed.priority), key=PRIORITY_ORDER.index)

    # Union metric facts
    existing_metric_ids = {m.metric_id for m in canonical.metric_facts}
    for m in absorbed.metric_facts:
        if m.metric_id not in existing_metric_ids:
            canonical.metric_facts.append(m)
            existing_metric_ids.add(m.metric_id)

    # Union structured data
    if isinstance(canonical.structured_data, dict) and isinstance(absorbed.structured_data, dict):
        for k, v in absorbed.structured_data.items():
            if k not in canonical.structured_data:
                canonical.structured_data[k] = v

    return canonical


def _stem(word: str) -> str:
    """Lightweight suffix stemmer for token similarity."""
    w = word.lower()
    for suffix in ("tion", "tions", "ing", "ed", "es", "s", "ment", "ments", "ly", "al", "ity"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def _builtin_similarity_matrix(texts: list[str]) -> np.ndarray:
    """Pure-Python / numpy TF-IDF similarity with sub-word n-gram support."""
    n = len(texts)
    if n == 0:
        return np.empty((0, 0))
    if n == 1:
        return np.ones((1, 1))

    stopwords = frozenset({
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "it", "its", "that", "this", "these", "those", "as"
    })

    doc_tokens: list[list[str]] = []
    doc_freq: dict[str, int] = {}

    for text in texts:
        raw_words = re.findall(r"\b[a-z0-9]+\b", text.casefold())
        stems = [_stem(w) for w in raw_words if w not in stopwords]
        char_ngrams = []
        for w in raw_words:
            if len(w) >= 4 and w not in stopwords:
                for i in range(len(w) - 2):
                    char_ngrams.append(f"_{w[i:i+3]}")
        tokens = stems + char_ngrams
        doc_tokens.append(tokens)
        for t in set(tokens):
            doc_freq[t] = doc_freq.get(t, 0) + 1

    vocab = sorted(doc_freq.keys())
    if not vocab:
        return np.eye(n)

    v_index = {w: i for i, w in enumerate(vocab)}
    idf = np.array([math.log((1 + n) / (1 + doc_freq[w])) + 1.0 for w in vocab])

    mat = np.zeros((n, len(vocab)), dtype=np.float64)
    for row_idx, tokens in enumerate(doc_tokens):
        if not tokens:
            continue
        counts = Counter(tokens)
        for t, count in counts.items():
            if t in v_index:
                mat[row_idx, v_index[t]] = (count / len(tokens)) * idf[v_index[t]]

    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = mat / norms
    sim = normalized @ normalized.T
    return np.clip(sim, 0.0, 1.0)


def _compute_similarity_matrix(texts: list[str], model_name: str | None = None) -> tuple[np.ndarray, str]:
    """Compute pairwise cosine similarity with fallback to TF-IDF."""
    if not texts or len(texts) < 2:
        return np.eye(len(texts)), "exact_fallback"

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name or "sentence-transformers/all-MiniLM-L6-v2")
        embeddings = model.encode(texts, normalize_embeddings=True)
        embeddings = np.asarray(embeddings)
        sim_matrix = embeddings @ embeddings.T
        return sim_matrix, "semantic_hybrid"
    except Exception:
        pass

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(stop_words="english")
        matrix = vec.fit_transform(texts)
        sim_matrix = (matrix @ matrix.T).toarray()
        return sim_matrix, "semantic_hybrid"
    except Exception:
        pass

    try:
        sim_matrix = _builtin_similarity_matrix(texts)
        return sim_matrix, "semantic_hybrid"
    except Exception:
        return np.eye(len(texts)), "exact_fallback"


def deduplicate_knowledge_units(
    units: Iterable[KnowledgeUnit],
    *,
    threshold: float = 0.85,
    ambiguous_threshold: float = 0.70,
    model_name: str | None = None,
) -> DedupResult:
    """Evidence-preserving deduplicator implementing F08 requirements.

    1. Merges exact-ID and verbatim duplicates first.
    2. Identifies near-duplicate semantic candidates above threshold.
    3. Runs fact-compatibility guards (numbers, units, periods, negation).
    4. Unions evidence and creates canonical ID aliases.
    5. Preserves ambiguous/conflicting pairs in DedupResult.
    """
    unit_list = list(units)
    if not unit_list:
        return DedupResult(canonical_units=[], aliases={}, duplicate_pairs=[], merged_count=0, mode="exact_fallback")

    # Step 1: Exact stable-identity / verbatim merge
    exact_canonical: list[KnowledgeUnit] = []
    aliases: dict[str, str] = {}
    merged_count = 0
    duplicate_pairs: list[DuplicatePair] = []

    seen_exact: dict[tuple[str, str, str], KnowledgeUnit] = {}
    seen_ids: dict[str, KnowledgeUnit] = {}

    for unit in unit_list:
        id_match = seen_ids.get(unit.unit_id)
        if id_match is not None:
            _merge_two_units(id_match, unit)
            aliases[unit.unit_id] = id_match.unit_id
            duplicate_pairs.append(DuplicatePair(
                unit_id_a=id_match.unit_id,
                unit_id_b=unit.unit_id,
                similarity_score=1.0,
                decision="MERGED",
                reason="Exact unit_id match"
            ))
            merged_count += 1
            continue

        verbatim_key = (unit.kind, normalize(unit.title), normalize(unit.summary))
        verbatim_match = seen_exact.get(verbatim_key)
        if verbatim_match is not None:
            _merge_two_units(verbatim_match, unit)
            aliases[unit.unit_id] = verbatim_match.unit_id
            duplicate_pairs.append(DuplicatePair(
                unit_id_a=verbatim_match.unit_id,
                unit_id_b=unit.unit_id,
                similarity_score=1.0,
                decision="MERGED",
                reason="Verbatim title/summary match"
            ))
            merged_count += 1
            continue

        seen_ids[unit.unit_id] = unit
        seen_exact[verbatim_key] = unit
        exact_canonical.append(unit)

    if len(exact_canonical) < 2:
        return DedupResult(
            canonical_units=exact_canonical,
            aliases=aliases,
            duplicate_pairs=duplicate_pairs,
            merged_count=merged_count,
            mode="exact_fallback",
        )

    # Step 2: Semantic near-duplicate candidates
    texts = [f"{u.title}. {u.title}. {u.summary}" for u in exact_canonical]
    sim_matrix, mode = _compute_similarity_matrix(texts, model_name=model_name)

    if mode == "exact_fallback":
        return DedupResult(
            canonical_units=exact_canonical,
            aliases=aliases,
            duplicate_pairs=duplicate_pairs,
            merged_count=merged_count,
            mode="exact_fallback",
        )

    # Step 3: Candidate evaluation with fact compatibility
    n = len(exact_canonical)
    absorbed_into: dict[int, int] = {}  # index -> canonical_index

    for i in range(n):
        if i in absorbed_into:
            continue
        for j in range(i + 1, n):
            if j in absorbed_into:
                continue
            score = float(sim_matrix[i, j])
            unit_a = exact_canonical[i]
            unit_b = exact_canonical[j]

            if score >= threshold:
                compatible, reason = check_fact_compatibility(unit_a, unit_b)
                if compatible:
                    # Merge unit j into canonical unit i
                    _merge_two_units(unit_a, unit_b)
                    absorbed_into[j] = i
                    aliases[unit_b.unit_id] = unit_a.unit_id
                    duplicate_pairs.append(DuplicatePair(
                        unit_id_a=unit_a.unit_id,
                        unit_id_b=unit_b.unit_id,
                        similarity_score=round(score, 4),
                        decision="MERGED",
                        reason=f"Semantic similarity {score:.3f} >= {threshold:.2f} and facts compatible"
                    ))
                    merged_count += 1
                else:
                    duplicate_pairs.append(DuplicatePair(
                        unit_id_a=unit_a.unit_id,
                        unit_id_b=unit_b.unit_id,
                        similarity_score=round(score, 4),
                        decision="REJECTED_INCOMPATIBLE",
                        reason=f"Semantic similarity {score:.3f} but incompatible: {reason}"
                    ))
            elif score >= ambiguous_threshold:
                duplicate_pairs.append(DuplicatePair(
                    unit_id_a=unit_a.unit_id,
                    unit_id_b=unit_b.unit_id,
                    similarity_score=round(score, 4),
                    decision="AMBIGUOUS_RETAINED",
                    reason=f"Borderline similarity {score:.3f}; retained as distinct units (Q13)"
                ))

    # Flatten transitive aliases so each points directly to its final canonical unit
    for alias_key, target_id in list(aliases.items()):
        curr = target_id
        visited = {alias_key}
        while curr in aliases and curr not in visited:
            visited.add(curr)
            curr = aliases[curr]
        aliases[alias_key] = curr

    final_units = [exact_canonical[i] for i in range(n) if i not in absorbed_into]

    return DedupResult(
        canonical_units=final_units,
        aliases=aliases,
        duplicate_pairs=duplicate_pairs,
        merged_count=merged_count,
        mode="semantic_hybrid",
    )


def deduplicate_units(units: Iterable[KnowledgeUnit]) -> list[KnowledgeUnit]:
    """Backward-compatible entry point returning canonical units."""
    result = deduplicate_knowledge_units(units)
    return result.canonical_units
