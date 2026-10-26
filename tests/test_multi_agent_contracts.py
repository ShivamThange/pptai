import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from infrastructure.llm.llm_client import LLMClient
from infrastructure.persistence.revisions import active_artifacts, RevisionStore
from infrastructure.utils.artifacts import portable_value
from infrastructure.ingestion.chunker import build_chunks, write_chunks
from infrastructure.ingestion.knowledge_extractor import (
    KnowledgeUnitBatch,
    KnowledgeUnitDraft,
    generate_validated_ir1,
    validate_knowledge_units,
)
from application.pipeline.orchestrator import MultiAgentOptions, run_multi_agent_pipeline
from application.services.slide_editor import edit_multi_agent_slide
from infrastructure.ingestion.slide_composer import compose_presentation_parallel, validate_slide_spec
from infrastructure.ingestion.source_adapter import adapt_structural_ir, build_raw_extraction
from infrastructure.ingestion.storyboard_planner import validate_storyboard
from contracts.ir1_schema import EvidenceRef, KnowledgeUnit, ValidatedIR1
from contracts.ir2_content_schema import SlideSpec
from contracts.storyboard_schema import SlidePlan, Storyboard


class _LLMResponseModel(BaseModel):
    answer: str


class _FakeGenerateContent:
    def __init__(self):
        self.contents = None

    def generate_content(self, **kwargs):
        self.contents = kwargs["contents"]
        return type("Response", (), {"text": '{"answer":"ok"}', "usage_metadata": None})()


class _FakeClient:
    def __init__(self):
        self.models = _FakeGenerateContent()


def test_llm_client_forwards_structured_prompt_to_gemini_sdk_without_network(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    client = LLMClient(api_key="test", max_calls_per_minute=999)
    fake = _FakeClient()
    client._client = fake

    result = client.generate_structured(
        stage="unit_test",
        prompt="sentinel prompt",
        output_model=_LLMResponseModel,
    )

    assert result.answer == "ok"
    assert fake.models.contents == "sentinel prompt"


def test_llm_client_sends_openrouter_schema_request_without_network(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    sent = {}

    class FakeResponse:
        def read(self):
            return b'{"choices":[{"message":{"content":"{\\\"answer\\\":\\\"ok\\\"}"}}],"usage":{"prompt_tokens":7,"completion_tokens":3}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode("utf-8"))
        sent["authorization"] = request.get_header("Authorization")
        sent["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("core.llm_client.urllib.request.urlopen", fake_urlopen)
    client = LLMClient(api_key="test-openrouter-key", max_calls_per_minute=999)
    result = client.generate_structured(
        stage="unit_test",
        prompt="sentinel prompt",
        output_model=_LLMResponseModel,
    )

    assert result.answer == "ok"
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["authorization"] == "Bearer test-openrouter-key"
    assert sent["body"]["messages"][0]["role"] == "system"
    assert sent["body"]["messages"][1]["content"] == "sentinel prompt"
    assert sent["body"]["response_format"]["type"] == "json_schema"
    assert sent["body"]["provider"]["require_parameters"] is True


class ExtractionCaller:
    def generate_structured(self, *, stage, prompt, output_model, **kwargs):
        assert stage == "knowledge_extraction"
        return KnowledgeUnitBatch(
            units=[
                KnowledgeUnitDraft(
                    kind="concept",
                    title="Weighted attention",
                    summary="Attention combines values using learned weights.",
                    evidence=[EvidenceRef(source_id=json.loads(prompt)["SOURCE_DATA"]["blocks"][0]["id"], excerpt="Attention combines values")],
                    priority="HIGH",
                )
            ]
        )


class ComposerCaller:
    async def generate_structured_async(self, *, stage, prompt, output_model, **kwargs):
        assert stage == "slide_composition"
        return SlideSpec(
            layout="TITLE_CENTERED",
            content={"title": {"type": "heading", "text": "Attention combines values"}},
        )


class PipelineCaller:
    def __init__(self):
        self.calls = []

    def generate_structured(self, *, stage, prompt, output_model, **kwargs):
        self.calls.append(stage)
        if stage == "knowledge_extraction":
            return KnowledgeUnitBatch(
                units=[
                    KnowledgeUnitDraft(
                        kind="concept",
                        title="Weighted attention",
                        summary="Attention combines values using learned weights.",
                        evidence=[EvidenceRef(source_id=json.loads(prompt)["SOURCE_DATA"]["blocks"][0]["id"], excerpt="Attention combines values")],
                        priority="HIGH",
                    )
                ]
            )
        if stage == "storyboard_planning":
            return Storyboard(
                document_title="attention",
                slides=[
                    SlidePlan(
                        slide_id=1,
                        title="Attention combines values",
                        objective="Explain the mechanism",
                        narrative_role="opening",
                        chunk_refs=["chunk_001"],
                        source_unit_ids=["ku_placeholder"],
                        preferred_layouts=["TITLE_CENTERED"],
                    )
                ],
            )
        raise AssertionError(stage)

    async def generate_structured_async(self, *, stage, prompt, output_model, **kwargs):
        self.calls.append(stage)
        return SlideSpec(
            layout="TITLE_CENTERED",
            content={"title": {"type": "heading", "text": "Attention combines values"}},
        )


def _structural_ir(tmp_path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"image")
    return {
        "document_name": "attention.pdf",
        "blocks": [
            {
                "block_id": "block_0001",
                "type": "text",
                "text": "Attention combines values using learned weights.",
                "section": "Introduction",
                "prov": [{"page_no": 1, "bbox": {"l": 1, "t": 2, "r": 3, "b": 4}}],
            }
        ],
        "assets": [{"asset_id": "image_0001.png", "type": "image", "file_path": str(image), "section": "Introduction"}],
    }


def test_source_adapter_writes_lossless_typed_artifact(tmp_path):
    structural = _structural_ir(tmp_path)
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(structural), encoding="utf-8")

    raw = build_raw_extraction(ir_path, tmp_path)

    assert raw.blocks[0].block_id == f"{raw.document_id}:block_0001"
    assert raw.blocks[0].page == 1
    assert raw.assets[0].asset_id == f"{raw.document_id}:image_0001.png"
    assert (tmp_path / "raw_extraction.json").exists()


def test_grounding_rejects_unknown_or_unsupported_numeric_evidence(tmp_path):
    raw = adapt_structural_ir(_structural_ir(tmp_path))
    unit = KnowledgeUnit(
        unit_id="ku_bad",
        kind="metric",
        title="Unsupported metric",
        summary="Throughput improves by 42%.",
        section_path=["Introduction"],
        evidence=[EvidenceRef(source_id=raw.blocks[0].block_id, excerpt="Attention combines values")],
    )

    accepted, failed_sections, warnings = validate_knowledge_units(raw, [unit])

    assert accepted == []
    assert failed_sections == {"Introduction"}
    assert "unsupported numeric values" in warnings[0]


def test_validated_ir1_chunks_and_legacy_projection_are_written(tmp_path):
    raw = adapt_structural_ir(_structural_ir(tmp_path))
    ir1 = generate_validated_ir1(raw, ExtractionCaller(), tmp_path)

    assert ir1.units[0].validation_status == "VALIDATED"
    assert (tmp_path / "ir1_validated.json").exists()
    assert (tmp_path / "content_analysis.json").exists()
    chunks = build_chunks(ir1)
    write_chunks(chunks, tmp_path)
    assert json.loads((tmp_path / "chunks.json").read_text(encoding="utf-8"))[0]["unit_ids"] == [ir1.units[0].unit_id]


def test_storyboard_and_slide_contracts_reject_invalid_bindings():
    unit = KnowledgeUnit(
        unit_id="ku_1",
        kind="concept",
        title="Attention",
        summary="Attention combines values.",
        section_path=["Intro"],
        evidence=[EvidenceRef(source_id="block_1", excerpt="Attention combines values")],
        validation_status="VALIDATED",
    )
    ir1 = ValidatedIR1(document_title="Attention", units=[unit])
    chunks = build_chunks(ir1)
    storyboard = Storyboard(
        document_title="Attention",
        slides=[
            SlidePlan(
                slide_id=1,
                title="Attention combines values",
                objective="Explain the mechanism",
                narrative_role="opening",
                chunk_refs=[chunks[0].chunk_id],
                source_unit_ids=["ku_1"],
                preferred_layouts=["TITLE_CENTERED"],
            )
        ],
    )
    layouts = {
        "layouts": {
            "TITLE_CENTERED": {"regions": {"title": {"allowed_types": ["heading"]}, "subtitle": {"allowed_types": ["text_group"]}}}
        }
    }
    validate_storyboard(storyboard, chunks, ir1, layouts, min_slides=1, max_slides=1)
    valid = SlideSpec(layout="TITLE_CENTERED", content={"title": {"type": "heading", "text": "Attention"}}, source_unit_ids=["ku_1"])
    validate_slide_spec(valid, layouts, allowed_unit_ids={"ku_1"})
    invalid = SlideSpec(layout="TITLE_CENTERED", content={"subtitle": {"type": "bullets", "items": ["bad"]}}, source_unit_ids=["ku_1"])
    with pytest.raises(ValueError, match="cannot render"):
        validate_slide_spec(invalid, layouts, allowed_unit_ids={"ku_1"})


@pytest.mark.parametrize("repairs", [True, False])
def test_storyboard_repairs_invalid_chunk_binding_with_bounded_feedback(repairs):
    from infrastructure.ingestion.storyboard_planner import plan_storyboard
    from contracts.storyboard_schema import TopicChunk
    units = [KnowledgeUnit(unit_id=key, kind="concept", title="Context", summary="Source context.", section_path=["Context"],
                           evidence=[EvidenceRef(source_id="b", excerpt="Source context.")],
                           validation_status="VALIDATED") for key in ("u1", "u2")]
    ir1 = ValidatedIR1(document_title="Paper", units=units)
    chunks = [TopicChunk(chunk_id=key, label=key, unit_ids=[unit], digest="Context", token_estimate=10)
              for key, unit in (("c1", "u1"), ("c2", "u2"))]
    calls = []
    class Caller:
        def generate_structured(self, **kwargs):
            payload = json.loads(kwargs["prompt"])
            calls.append(payload)
            if len(calls) > 1:
                assert "invalid bindings" in payload["validation_errors"][0]
                assert payload["previous_storyboard"]["slides"][0]["chunk_refs"] == ["unknown"]
            return Storyboard(document_title="Paper", slides=[SlidePlan(
                slide_id=1, title="Context", objective="Explain context", narrative_role="opening",
                source_unit_ids=["u2"], chunk_refs=["c2" if repairs and len(calls) > 1 else "unknown"],
            )])
    if repairs:
        result = plan_storyboard(ir1, chunks, {"layouts": {}}, Caller(), min_slides=1, max_slides=1, max_repairs=1)
        assert result.slides[0].chunk_refs == ["c2"]
    else:
        with pytest.raises(ValueError, match="invalid bindings"):
            plan_storyboard(ir1, chunks, {"layouts": {}}, Caller(), min_slides=1, max_slides=1, max_repairs=1)
    assert len(calls) == 2


def test_storyboard_derives_missing_chunks_for_known_selected_units():
    from infrastructure.ingestion.storyboard_planner import plan_storyboard
    from contracts.storyboard_schema import TopicChunk
    unit = KnowledgeUnit(unit_id="u", kind="concept", title="Context", summary="Source context.", section_path=["Context"],
                         evidence=[EvidenceRef(source_id="b", excerpt="Source context.")], validation_status="VALIDATED")
    ir1 = ValidatedIR1(document_title="Paper", units=[unit])
    chunks = [TopicChunk(chunk_id="c1", label="Context", unit_ids=["other"], digest="Other", token_estimate=10),
              TopicChunk(chunk_id="c2", label="Context", unit_ids=["u"], digest="Context", token_estimate=10)]
    class Caller:
        def generate_structured(self, **kwargs):
            return Storyboard(document_title="Paper", slides=[SlidePlan(slide_id=1, title="Context", objective="Explain context",
                             narrative_role="opening", source_unit_ids=["u"], chunk_refs=["c1"])])
    result = plan_storyboard(ir1, chunks, {"layouts": {}}, Caller(), min_slides=1, max_slides=1, max_repairs=0)
    assert result.slides[0].source_unit_ids == ["u"]
    assert result.slides[0].chunk_refs == ["c1", "c2"]


def test_storyboard_planner_includes_user_instruction():
    from infrastructure.ingestion.storyboard_planner import plan_storyboard
    from contracts.storyboard_schema import TopicChunk
    unit = KnowledgeUnit(unit_id="u", kind="concept", title="Context", summary="Source context.", section_path=["Context"],
                         evidence=[EvidenceRef(source_id="b", excerpt="Source context.")], validation_status="VALIDATED")
    ir1 = ValidatedIR1(document_title="Paper", units=[unit])
    chunks = [TopicChunk(chunk_id="c1", label="Context", unit_ids=["u"], digest="Context", token_estimate=10)]
    recorded = {}
    class Caller:
        def generate_structured(self, **kwargs):
            recorded["system_prompt"] = kwargs["system_prompt"]
            return Storyboard(document_title="Paper", slides=[SlidePlan(slide_id=1, title="Context", objective="Explain context",
                             narrative_role="opening", source_unit_ids=["u"], chunk_refs=["c1"])])
    plan_storyboard(ir1, chunks, {"layouts": {}}, Caller(), min_slides=1, max_slides=1, max_repairs=0, instruction="Focus on multi-head attention")
    assert "USER INSTRUCTION: Focus on multi-head attention" in recorded["system_prompt"]


def test_parallel_composer_preserves_storyboard_order_without_provider_calls():
    unit = KnowledgeUnit(
        unit_id="ku_1",
        kind="concept",
        title="Attention",
        summary="Attention combines values.",
        section_path=["Intro"],
        evidence=[EvidenceRef(source_id="block_1", excerpt="Attention combines values")],
        validation_status="VALIDATED",
    )
    ir1 = ValidatedIR1(document_title="Attention", units=[unit])
    chunks = build_chunks(ir1)
    storyboard = Storyboard(
        document_title="Attention",
        slides=[
            SlidePlan(
                slide_id=1,
                title="Attention combines values",
                objective="Explain the mechanism",
                narrative_role="opening",
                chunk_refs=[chunks[0].chunk_id],
                source_unit_ids=["ku_1"],
                preferred_layouts=["TITLE_CENTERED"],
            )
        ],
    )
    layouts = {
        "layouts": {
            "TITLE_CENTERED": {"regions": {"title": {"allowed_types": ["heading"]}, "subtitle": {"allowed_types": ["text_group"]}}}
        }
    }
    presentation = asyncio.run(
        compose_presentation_parallel(storyboard, ir1, chunks, layouts, ComposerCaller(), max_concurrency=2)
    )
    assert presentation.slides[0].layout == "TITLE_CENTERED"
    assert presentation.slides[0].source_unit_ids == ["ku_1"]


def test_orchestrator_runs_and_resumes_with_a_typed_fake_caller(tmp_path):
    structural = _structural_ir(tmp_path)
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(structural), encoding="utf-8")
    layouts = Path(__file__).parents[1] / "config" / "ppt_default_layouts.json"
    caller = PipelineCaller()

    # The stable ID is calculated from the extraction draft; teach the storyboard
    # fake that ID after a one-item dry calculation by patching its returned plan.
    original = caller.generate_structured

    def with_stable_id(**kwargs):
        result = original(**kwargs)
        if kwargs["stage"] == "storyboard_planning":
            raw_id = "ku_" + __import__("hashlib").sha256(
                f"concept|attention combines values using learned weights.|{adapt_structural_ir(structural).blocks[0].block_id}".encode("utf-8")
            ).hexdigest()[:16]
            result.slides[0].source_unit_ids = [raw_id]
            result.slides[0].chunk_refs = [json.loads(kwargs["prompt"])["SOURCE_DATA"]["chunks"][0]["chunk_id"]]
        return result

    caller.generate_structured = with_stable_id
    options = MultiAgentOptions(
        layouts_path=str(layouts), output_dir=str(tmp_path / "run"), min_slides=1, max_slides=1, max_concurrency=1
    )
    pptx = run_multi_agent_pipeline(ir_path, options, caller=caller)
    assert pptx.exists()
    assert (pptx.parent / "quality_report.json").exists()
    before_resume = list(caller.calls)
    run_multi_agent_pipeline(ir_path, MultiAgentOptions(**{**options.__dict__, "resume": True}), caller=caller)
    assert caller.calls == before_resume


def test_scoped_editor_preserves_validated_ir1(tmp_path):
    structural = _structural_ir(tmp_path)
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(structural), encoding="utf-8")
    layouts = Path(__file__).parents[1] / "config" / "ppt_default_layouts.json"
    caller = PipelineCaller()
    original = caller.generate_structured

    def with_stable_id(**kwargs):
        result = original(**kwargs)
        if kwargs["stage"] == "storyboard_planning":
            raw_id = "ku_" + __import__("hashlib").sha256(
                f"concept|attention combines values using learned weights.|{adapt_structural_ir(structural).blocks[0].block_id}".encode("utf-8")
            ).hexdigest()[:16]
            result.slides[0].source_unit_ids = [raw_id]
            result.slides[0].chunk_refs = [json.loads(kwargs["prompt"])["SOURCE_DATA"]["chunks"][0]["chunk_id"]]
        return result

    caller.generate_structured = with_stable_id
    run_dir = tmp_path / "run"
    options = MultiAgentOptions(layouts_path=str(layouts), output_dir=str(run_dir), min_slides=1, max_slides=1)
    run_multi_agent_pipeline(ir_path, options, caller=caller)
    original_revision = active_artifacts(run_dir)
    before = (original_revision / "ir1_validated.json").read_text(encoding="utf-8")
    updated = edit_multi_agent_slide(
        output_dir=run_dir,
        layouts_path=layouts,
        slide_index=1,
        instruction="Make the title more concise.",
        base_revision=original_revision.name,
        caller=caller,
    )
    assert updated.exists()
    assert (original_revision / "ir1_validated.json").read_text(encoding="utf-8") == before
    assert portable_value(json.loads((updated.parent / "ir1_validated.json").read_text(encoding="utf-8"))) == portable_value(json.loads(before))
    assert json.loads((updated.parent / "edits.json").read_text(encoding="utf-8"))[0]["slide_index"] == 1
