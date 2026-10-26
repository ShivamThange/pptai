"""Test suite for F06 Optional deep source verification."""
import json
from schemas.ir1_schema import KnowledgeUnit, EvidenceRef, ValidationResult
from schemas.raw_extraction_schema import RawExtraction, SourceBlock
from tools.claim_verification import (
    ClaimVerificationCache,
    build_verification_report,
    judge_semantics,
    validate_claim,
    SemanticBatch,
    SemanticJudgment,
)


class VerificationService:
    """Test-local coordinator replacing the deleted pipeline.verification facade."""

    def __init__(self, profile="basic", *, cache=None):
        self.profile = profile
        self.cache = cache or ClaimVerificationCache()

    @property
    def is_deep(self):
        return self.profile == "deep"

    def verify_knowledge_units(self, raw, units, caller=None, *, batch_size=8):
        warnings = []
        for unit in units:
            unit.validation = validate_claim(raw, unit)
            unit.validation_status = "REJECTED" if unit.validation.status == "REJECTED" else "VALIDATED"
        if self.is_deep and caller is not None:
            pending = [u for u in units if u.validation_status != "REJECTED"]
            warnings.extend(judge_semantics(raw, pending, caller, batch_size=batch_size, cache=self.cache))
        return warnings

    def build_report(self, ir1=None, ir2=None):
        return build_verification_report(ir1, ir2, profile=self.profile)

    def write_report(self, target_dir, ir1=None, ir2=None):
        import json as _json
        from pathlib import Path as _Path
        path = _Path(target_dir) / "verification_report.json"
        path.write_text(_json.dumps(self.build_report(ir1, ir2), indent=2), encoding="utf-8")
        return path



def make_raw(text: str = "Acme Corp earned 10 million USD in revenue in 2023.") -> RawExtraction:
    return RawExtraction(
        schema_version="3",
        document_name="test.pdf",
        source_item_ids=["doc1:b1"],
        blocks=[
            SourceBlock(
                block_id="b1",
                source_item_id="doc1:b1",
                document_id="doc1",
                text=text,
                section_path=["Results"],
            )
        ],
        assets=[],
    )


def make_unit(
    unit_id: str,
    title: str,
    summary: str,
    excerpt: str | None = None,
    source_id: str = "b1",
) -> KnowledgeUnit:
    return KnowledgeUnit(
        unit_id=unit_id,
        kind="concept",
        title=title,
        summary=summary,
        section_path=["Results"],
        evidence=[EvidenceRef(source_id=source_id, excerpt=excerpt if excerpt is not None else summary, kind="excerpt")],
    )


def test_basic_mode_cannot_bypass_citation_or_numeric_checks():
    raw = make_raw("Revenue was 10 million USD.")
    bad_citation_unit = make_unit("u1", "Results", "Revenue was 10 million USD.", source_id="unknown_block")
    bad_number_unit = make_unit("u2", "Results", "Revenue was 99 million USD.", excerpt="Revenue was 10 million USD.")

    svc = VerificationService(profile="basic")
    svc.verify_knowledge_units(raw, [bad_citation_unit, bad_number_unit])

    assert bad_citation_unit.validation.citation_exists == "FAILED"
    assert bad_citation_unit.validation_status == "REJECTED"

    assert bad_number_unit.validation.numeric_binding == "FAILED"
    assert bad_number_unit.validation_status == "REJECTED"


def test_deep_mode_verifies_valid_entailment():
    raw = make_raw("The system reduced latency by 35 percent.")
    unit = make_unit("u1", "Latency Reduction", "The system reduced latency by 35 percent.")
    unit.validation = validate_claim(raw, unit)

    class MockCaller:
        def generate_structured(self, **kwargs):
            return SemanticBatch(judgments=[
                SemanticJudgment(unit_id="u1", support="CHECKED", reason="Accurately entails the latency reduction")
            ])

    svc = VerificationService(profile="deep")
    warnings = svc.verify_knowledge_units(raw, [unit], caller=MockCaller())

    assert len(warnings) == 0
    assert unit.validation.semantic_support == "CHECKED"
    assert unit.validation.status == "VERIFIED"
    assert unit.validation_status == "VALIDATED"


def test_deep_mode_catches_unsupported_semantic_claim():
    raw = make_raw("The initiative was adopted by 5 pilot teams.")
    # Excerpt is verbatim in source, but title claims an exaggerated revolution
    unit = make_unit("u1", "Massive Worldwide Revolution", "The initiative was adopted by 5 pilot teams.")
    unit.validation = validate_claim(raw, unit)

    class MockCaller:
        def generate_structured(self, **kwargs):
            return SemanticBatch(judgments=[
                SemanticJudgment(unit_id="u1", support="FAILED", reason="Source only mentions 5 pilot teams, not a worldwide revolution")
            ])

    svc = VerificationService(profile="deep")
    svc.verify_knowledge_units(raw, [unit], caller=MockCaller())

    assert unit.validation.semantic_support == "FAILED"
    assert unit.validation.status == "REJECTED"
    assert unit.validation_status == "REJECTED"


def test_judge_failure_preserves_unknown_without_crashing():
    raw = make_raw("Revenue was 10 million USD.")
    unit = make_unit("u1", "Revenue", "Revenue was 10 million USD.")
    unit.validation = validate_claim(raw, unit)

    class FailingCaller:
        def generate_structured(self, **kwargs):
            raise RuntimeError("Provider connection timeout")

    svc = VerificationService(profile="deep")
    warnings = svc.verify_knowledge_units(raw, [unit], caller=FailingCaller())

    assert len(warnings) == 1
    assert any(term in warnings[0].lower() for term in ("unavailable", "failed", "timeout"))
    assert unit.validation.semantic_support == "UNKNOWN"
    assert unit.validation.status == "BASIC_CHECKED"
    assert unit.validation_status == "VALIDATED"


def test_claim_verification_cache_hit_bypasses_llm():
    raw = make_raw("Model latency is 12 ms.")
    unit1 = make_unit("u1", "Model Latency", "Model latency is 12 ms.")
    unit2 = make_unit("u2", "Model Latency", "Model latency is 12 ms.")
    unit1.validation = validate_claim(raw, unit1)
    unit2.validation = validate_claim(raw, unit2)

    call_count = 0

    class CountingCaller:
        def generate_structured(self, **kwargs):
            nonlocal call_count
            call_count += 1
            payload = json.loads(kwargs["prompt"])["SOURCE_DATA"]
            return SemanticBatch(judgments=[
                SemanticJudgment(unit_id=item["unit_id"], support="CHECKED", reason="Verified")
                for item in payload
            ])

    cache = ClaimVerificationCache()
    caller = CountingCaller()

    # First evaluation: cache miss, calls LLM
    judge_semantics(raw, [unit1], caller, cache=cache)
    assert call_count == 1
    assert unit1.validation.semantic_support == "CHECKED"

    # Second evaluation of identical claim & evidence: cache hit, zero LLM calls
    judge_semantics(raw, [unit2], caller, cache=cache)
    assert call_count == 1  # Still 1!
    assert unit2.validation.semantic_support == "CHECKED"
    assert any("Cached (f06-v1)" in r for r in unit2.validation.reason)


def test_cache_invalidation_on_changed_claim():
    raw1 = make_raw("Model latency is 12 ms.")
    raw2 = make_raw("Model latency is 99 ms.")
    unit1 = make_unit("u1", "Model Latency", "Model latency is 12 ms.")
    unit2 = make_unit("u2", "Model Latency Changed", "Model latency is 99 ms.")
    unit1.validation = validate_claim(raw1, unit1)
    unit2.validation = validate_claim(raw2, unit2)

    call_count = 0

    class CountingCaller:
        def generate_structured(self, **kwargs):
            nonlocal call_count
            call_count += 1
            payload = json.loads(kwargs["prompt"])["SOURCE_DATA"]
            return SemanticBatch(judgments=[
                SemanticJudgment(unit_id=item["unit_id"], support="CHECKED", reason="Verified")
                for item in payload
            ])

    cache = ClaimVerificationCache()
    caller = CountingCaller()

    judge_semantics(raw1, [unit1], caller, cache=cache)
    assert call_count == 1

    # Different claim text -> cache miss -> must call LLM
    judge_semantics(raw2, [unit2], caller, cache=cache)
    assert call_count == 2


def test_verification_report_artifact_structure():
    raw = make_raw("Profit was 5 million USD.")
    unit = make_unit("u1", "Profit", "Profit was 5 million USD.", excerpt="Profit was 5 million USD")
    unit.validation = ValidationResult(
        citation_exists="CHECKED",
        numeric_binding="CHECKED",
        semantic_support="CHECKED",
        status="VERIFIED",
        claim_sha256="abc123hash",
        evidence_sha256="def456hash",
        reason=["Verified"],
    )

    class DummyIR1:
        units = [unit]

    report = build_verification_report(ir1=DummyIR1(), profile="deep")
    assert report["schema_version"] == "f06-v1"
    assert report["profile"] == "deep"
    assert report["total_claims"] == 1
    assert report["verified_claims"] == 1
    assert report["rejected_claims"] == 0
    assert report["readiness"] == "VERIFIED"
    assert len(report["checks"]) == 1
    check = report["checks"][0]
    assert check["claim_id"] == "u1"
    assert check["overall_status"] == "VERIFIED"


def test_empty_report_readiness_draft_incomplete():
    report = build_verification_report(ir1=None, ir2=None, profile="basic")
    assert report["total_claims"] == 0
    assert report["readiness"] == "DRAFT_INCOMPLETE"


def test_verification_report_with_dict_grounding():
    class DummySlide:
        slide_id = "slide_1"
        grounding = {
            "title": {
                "claim_sha256": "sha_title",
                "evidence_sha256": "sha_ev",
                "citation_exists": "CHECKED",
                "numeric_binding": "NOT_APPLICABLE",
                "semantic_support": "CHECKED",
                "status": "VERIFIED",
                "reason": ["Entailed"],
            }
        }

    class DummyIR2:
        slides = [DummySlide()]

    report = build_verification_report(ir1=None, ir2=DummyIR2(), profile="deep")
    assert report["total_claims"] == 1
    assert report["verified_claims"] == 1
    assert report["readiness"] == "VERIFIED"
    check = report["checks"][0]
    assert check["claim_id"] == "slide_1:title"
    assert check["overall_status"] == "VERIFIED"

