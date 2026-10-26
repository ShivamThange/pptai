"""R03 adversarial grounding and source-to-artifact acceptance fixtures."""
import asyncio
import json
from pathlib import Path

import pytest
from pptx import Presentation

from infrastructure.ingestion.knowledge_extractor import (
    KnowledgeUnitBatch, KnowledgeUnitDraft, generate_validated_ir1, validate_knowledge_units, coverage_ledger,
)
from infrastructure.ingestion.slide_composer import validate_slide_grounding, compose_single_slide, judge_slide_claims
from contracts.ir1_schema import EvidenceRef, KnowledgeUnit, MetricFact, MetricComparison, CalculationTrace
from contracts.ir2_content_schema import SlideSpec
from contracts.raw_extraction_schema import RawExtraction, SourceBlock, SourceAsset
from contracts.storyboard_schema import SlidePlan
from domain.evaluation.claim_verification import validate_claim, judge_semantics, SemanticBatch, migrate_ir1_v2, mentions


def test_verbatim_citation_numbers_are_grounded_and_covered():
    raw = raw_text("[2, 5, 21, 13]")
    unit = claim(raw.blocks[0].text, title="Reference metadata", raw=raw)
    accepted, _, _ = validate_knowledge_units(raw, [unit])
    assert len(accepted) == 1
    assert coverage_ledger(raw, accepted, [unit])[0].status == "COVERED"


def test_changed_citation_number_is_still_rejected():
    raw = raw_text("[2, 5, 21, 13]")
    assert validate_claim(raw, claim("[2, 6, 21, 13]", raw=raw)).status == "REJECTED"


def test_source_passage_mode_retains_actual_blocks_and_table_cells(tmp_path):
    raw = table_raw()
    raw.source_item_ids.append("doc:block")
    raw.blocks = [SourceBlock(block_id="b", source_item_id="doc:block", document_id="doc", text="Revenue = 10; Profit = 2.", section_path=["Results"])]
    class Caller:
        def generate_structured(self, **kwargs):
            raise AssertionError("Source retention must not ask a model to author facts")
    ir1 = generate_validated_ir1(raw, Caller(), tmp_path, extraction_mode="source-passages")
    assert any(unit.summary == raw.blocks[0].text for unit in ir1.units)
    assert {(ref.row, ref.column) for unit in ir1.units for ref in unit.evidence if ref.kind == "cell"} == {(1, 1), (2, 1)}
    assert all(row.status == "COVERED" for row in ir1.coverage)
    assert ir1.completeness == "BASIC_CHECKED"
    assert all(unit.validation.semantic_support == "UNKNOWN" for unit in ir1.units)
    assert json.loads((tmp_path / "knowledge_validation_report.json").read_text())["extraction_mode"] == "source-passages"


@pytest.mark.parametrize("failure", ["provenance", "comparison"])
def test_source_passage_mode_keeps_grounding_gate_active(tmp_path, failure):
    raw = raw_text("Acme revenue 2 USD exceeds Beta revenue 10 USD." if failure == "comparison" else "Revenue = 10.")
    if failure == "provenance":
        raw.source_item_ids = ["doc:real"]
        raw.blocks[0].source_item_id = "doc:missing"
    with pytest.raises(ValueError, match="bounded retry"):
        generate_validated_ir1(raw, object(), tmp_path, extraction_mode="source-passages")
    assert not (tmp_path / "ir1_validated.json").exists()
    assert json.loads((tmp_path / "knowledge_validation_report.json").read_text())["rejected_units"]


def test_unlabelled_number_cannot_borrow_a_labelled_metric():
    raw = raw_text("Acme revenue = 10 USD.")
    assert validate_claim(raw, claim("10 USD", raw=raw)).status == "REJECTED"


def test_comparison_does_not_bind_unrelated_sentences():
    raw = raw_text("Acme revenue = 10 USD. Processing takes 2 seconds. Compared with earlier work, the method is simpler.")
    assert validate_claim(raw, claim(raw.blocks[0].text, raw=raw)).status == "BASIC_CHECKED"


def test_verbatim_false_comparison_is_still_rejected():
    raw = raw_text("Acme revenue 2 USD exceeds Beta revenue 10 USD.")
    assert validate_claim(raw, claim(raw.blocks[0].text, raw=raw)).status == "REJECTED"


def raw_text(text="Revenue = 10; Profit = 2."):
    return RawExtraction(document_name="financial.txt", blocks=[SourceBlock(block_id="b", text=text, section_path=["Results"])])


def claim(summary, *, title="Financial results", raw=None, **kwargs):
    raw = raw or raw_text()
    return KnowledgeUnit(unit_id="u", kind="metric", title=title, summary=summary, section_path=["Results"],
                         evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)], **kwargs)


@pytest.mark.parametrize("summary", ["Profit = 10.", "Revenue = 2.", "Profit = 2 USD.", "Profit = 2%.", "Profit in 2024 = 2.", "Profit = -2."])
def test_swapped_subject_unit_period_and_sign_rejected(summary):
    raw = raw_text()
    result = validate_claim(raw, claim(summary))
    assert result.citation_exists == "CHECKED"
    assert result.numeric_binding == "FAILED"
    assert result.status == "REJECTED"


@pytest.mark.parametrize("summary", ["Revenue = 10.", "Profit = 2.", "Revenue = 10; Profit = 2."])
def test_bound_numbers_are_basic_checked_with_unknown_semantics(summary):
    result = validate_claim(raw_text(), claim(summary))
    assert result.status == "BASIC_CHECKED"
    assert result.numeric_binding == "CHECKED"
    assert result.semantic_support == "UNKNOWN"


@pytest.mark.parametrize("summary", ["Beta revenue = 10", "Profit equals revenue = 10", "Total revenue = 10"])
def test_numeric_binding_does_not_invent_additional_subjects_or_measures(summary):
    assert validate_claim(raw_text(), claim(summary)).numeric_binding == "FAILED"


def test_model_response_schema_excludes_locally_assigned_grounding():
    from contracts.ir2_content_schema import SlideDraft
    assert "grounding" not in SlideDraft.model_json_schema()["properties"]
    assert "grounding" in SlideSpec.model_json_schema()["properties"]


@pytest.mark.parametrize("source,summary", [
    ("Profit in 2024 = 2 USD.", "Profit in 2023 = 2 USD."),
    ("Profit in 2024 = 2 USD.", "Profit in 2024 = 2 EUR."),
    ("Latency = 2 ms.", "Latency = 2 seconds."),
    ("Profit = $2 million.", "Profit = $2 billion."),
    ("Margin = 2%.", "Margin = 2."),
    ("Profit = 2.51 USD.", "Profit = 2.5 USD."),
])
def test_units_periods_scale_and_precision_are_not_number_membership(source, summary):
    raw = raw_text(source)
    assert validate_claim(raw, claim(summary, raw=raw)).status == "REJECTED"


def test_short_excerpt_cannot_borrow_uncited_number():
    raw = raw_text("Revenue = 10; Profit = 2.")
    unit = claim("Profit = 2.")
    unit.evidence[0].excerpt = "Revenue = 10"
    assert validate_claim(raw, unit).status == "REJECTED"


def test_unsupported_title_and_structured_data_rejected():
    unit = claim("Profit = 2.", title="Profit = 10")
    assert validate_claim(raw_text(), unit).status == "REJECTED"
    unit.title = "Results"
    unit.structured_data = {"profit": 10}
    assert validate_claim(raw_text(), unit).status == "REJECTED"


def test_provenance_identity_and_catalog_are_checked():
    raw = raw_text()
    raw.blocks[0].document_id = "doc"
    raw.blocks[0].content_sha256 = "hash"
    unit = claim("Profit = 2")
    unit.evidence[0].document_id = "forged"
    assert validate_claim(raw, unit).citation_exists == "FAILED"
    unit.evidence[0].document_id = "doc"
    unit.evidence[0].content_sha256 = "forged"
    assert validate_claim(raw, unit).citation_exists == "FAILED"
    unit.evidence[0].content_sha256 = "hash"
    raw.source_item_ids = ["doc:actual"]
    raw.blocks[0].source_item_id = "doc:forged"
    assert validate_claim(raw, unit).citation_exists == "FAILED"


def table_raw():
    cells = [
        {"row": 0, "column": 0, "text": "Measure", "column_header": True, "source_refs": ["doc:table"]},
        {"row": 0, "column": 1, "text": "2024 USD", "column_header": True, "source_refs": ["doc:table"]},
        {"row": 1, "column": 0, "text": "Revenue", "row_header": True, "source_refs": ["doc:table"]},
        {"row": 1, "column": 1, "text": "10", "source_refs": ["doc:table"]},
        {"row": 2, "column": 0, "text": "Profit", "row_header": True, "source_refs": ["doc:table"]},
        {"row": 2, "column": 1, "text": "2", "source_refs": ["doc:table"]},
    ]
    return RawExtraction(document_name="table.csv", document_id="doc", source_item_ids=["doc:table"],
        assets=[SourceAsset(asset_id="t", document_id="doc", kind="table", section_path=["Results"], source_refs=["doc:table"],
                            data={"headers": ["Measure", "2024 USD"], "rows": [["Revenue", "10"], ["Profit", "2"]], "cells": cells})])


def cell_claim(row=2, value="2"):
    return KnowledgeUnit(unit_id="table-u", kind="metric", title="Profit", summary=f"Profit in 2024 = {value} USD.",
        section_path=["Results"], evidence=[EvidenceRef(source_id="t", kind="cell", row=row, column=1, excerpt=value)])


def test_table_only_metric_binds_actual_cell_and_headers():
    raw = table_raw()
    unit = cell_claim()
    result = validate_claim(raw, unit)
    assert result.status == "BASIC_CHECKED", result.reason
    assert unit.evidence[0].document_id == "doc"
    assert validate_claim(raw, cell_claim(row=1, value="10")).status == "REJECTED"
    wrong = cell_claim()
    wrong.evidence[0].column = 0
    assert validate_claim(raw, wrong).citation_exists == "FAILED"
    raw.assets[0].data["cells"][-1]["source_refs"] = ["forged"]
    assert validate_claim(raw, unit).citation_exists == "FAILED"


def metric(metric_id, value, raw, *, period=None, measure="Revenue", unit="USD", subject="Acme", excerpt=None):
    return MetricFact(metric_id=metric_id, subject=subject, measure=measure, value=str(value), unit=unit, period=period,
                      evidence=[EvidenceRef(source_id="b", excerpt=excerpt or raw.blocks[0].text)])


def test_structured_metric_precision_and_subject_binding():
    raw = raw_text("Acme revenue in 2024 = 10.50 USD.")
    fact = metric("m", "10.50", raw, period="2024")
    unit = claim("Acme revenue in 2024 = 10.50 USD.", raw=raw, metric_facts=[fact])
    assert validate_claim(raw, unit).status == "BASIC_CHECKED"
    assert fact.source_precision == 2
    fact.measure = "Profit"
    assert validate_claim(raw, unit).status == "REJECTED"


@pytest.mark.parametrize("change", ["unit", "period", "measure", "direction"])
def test_comparisons_require_aligned_operands_and_direction(change):
    raw = raw_text("Acme revenue in 2024 = 10 USD; Beta revenue in 2024 = 2 USD; Beta profit in 2024 = 2 USD; Beta revenue in 2023 = 2 USD; Beta revenue in 2024 = 2 EUR.")
    left = metric("l", 10, raw, period="2024")
    right = metric("r", 2, raw, period="2023" if change == "period" else "2024", subject="Beta",
                   unit="EUR" if change == "unit" else "USD", measure="Profit" if change == "measure" else "Revenue")
    unit = claim("Comparison", raw=raw, metric_facts=[left, right], comparisons=[MetricComparison(left_id="l", right_id="r", operator="lt" if change == "direction" else "gt")])
    assert validate_claim(raw, unit).status == "REJECTED"


def test_prose_comparison_alignment_and_direction():
    raw = raw_text("Revenue in 2024 = 10 USD; Profit in 2023 = 2 USD.")
    unit = claim("Revenue in 2024 = 10 USD versus Profit in 2023 = 2 USD.", raw=raw)
    assert validate_claim(raw, unit).status == "REJECTED"
    raw = raw_text()
    assert validate_claim(raw, claim("Profit = 2 is greater than Revenue = 10.")).status == "REJECTED"


def calculation_unit(operation="sum", value="12", *, denominator="2"):
    raw = raw_text(f"Acme revenue = 10 USD; Acme revenue = {denominator} USD.")
    left, right = metric("l", 10, raw), metric("r", denominator, raw)
    derived = metric("d", value, raw, unit="x" if operation == "ratio" else "%" if operation == "percent_change" else "USD")
    derived.evidence = [*left.evidence, *right.evidence]
    derived.calculation = CalculationTrace(operation=operation, operand_ids=["l", "r"])
    unit = claim(f"Acme revenue = {value} {derived.unit}.", raw=raw, metric_facts=[left, right, derived])
    return raw, unit, derived


@pytest.mark.parametrize("operation,value", [("sum", "12"), ("difference", "8"), ("ratio", "5"), ("percent_change", "400")])
def test_calculations_recompute_with_source_operand_refs(operation, value):
    raw, unit, derived = calculation_unit(operation, value)
    result = validate_claim(raw, unit)
    assert result.status == "BASIC_CHECKED", result.reason
    assert derived.calculation.result == value
    assert len(derived.calculation.operand_refs) == 2
    assert derived.calculation.expression


@pytest.mark.parametrize("failure", ["result", "zero", "unaligned", "missing", "nonfinite", "evidence"])
def test_invalid_calculations_fail_closed(failure):
    raw, unit, derived = calculation_unit("ratio" if failure == "zero" else "sum", "5" if failure == "zero" else "12", denominator="0" if failure == "zero" else "2")
    if failure == "result":
        derived.value = "13"
    if failure == "unaligned":
        unit.metric_facts[1].period = "2023"
    if failure == "missing":
        derived.calculation.operand_ids = ["l", "absent"]
    if failure == "nonfinite":
        derived.value = "NaN"
    if failure == "evidence":
        derived.evidence = [EvidenceRef(source_id="forged", excerpt="10")]
    assert validate_claim(raw, unit).status == "REJECTED"


def test_coverage_requires_each_source_item_and_missing_critical_metric():
    raw = raw_text()
    good = claim("Revenue = 10", title="Revenue")
    bad = claim("Profit = 10", title="Profit", priority="CRITICAL")
    bad.unit_id = "bad"
    accepted, failed, _ = validate_knowledge_units(raw, [good, bad])
    assert accepted == [good]
    assert failed == {"Results"}
    row = coverage_ledger(raw, accepted, [good, bad])[0]
    assert "bad" in row.missing_unit_ids
    assert row.status == "INCOMPLETE"
    # Even if the extractor silently omitted Profit entirely, its source metric is missing.
    assert coverage_ledger(raw, accepted, [good])[0].status == "INCOMPLETE"


def test_table_coverage_requires_each_numeric_source_cell():
    raw = table_raw()
    good = cell_claim()
    accepted, failed, _ = validate_knowledge_units(raw, [good])
    # Per-cell obligations are table-level now: a table with at least one
    # cited numeric cell is covered (the renderer can still bind the full
    # source table by asset ID), while a fully-unseen table is flagged.
    assert failed == set()
    row = coverage_ledger(raw, accepted, [good])[0]
    assert "t:cell:1:1" not in row.missing_unit_ids
    assert row.status == "COVERED"
    nobody = coverage_ledger(raw, [], [])[0]
    assert "t:table_numeric_coverage" in nobody.missing_unit_ids


def test_scoped_retry_preserves_good_units_and_reports_rejected_diagnostics(tmp_path):
    raw = raw_text()
    raw.blocks.append(SourceBlock(block_id="other", text="Unrelated context is retained.", section_path=["Other"]))
    calls = []
    class Caller:
        def generate_structured(self, **kwargs):
            data = json.loads(kwargs["prompt"])["SOURCE_DATA"]
            calls.append([block["id"] for block in data["blocks"]])
            if data["section"] == "Other":
                return KnowledgeUnitBatch(units=[KnowledgeUnitDraft(kind="concept", title="Context", summary="Unrelated context is retained.", evidence=[EvidenceRef(source_id="other", excerpt=raw.blocks[1].text)])])
            first = calls.count(["b"]) == 1
            if not first:
                assert json.loads(kwargs["prompt"])["repair_feedback"]
            return KnowledgeUnitBatch(units=[
                KnowledgeUnitDraft(kind="metric", title="Revenue", summary="Revenue = 10.", evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)]),
                KnowledgeUnitDraft(kind="metric", title="Profit", summary=f"Profit = {10 if first else 2}.", priority="CRITICAL", evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)]),
            ])
    ir1 = generate_validated_ir1(raw, Caller(), tmp_path)
    assert calls == [["b"], ["other"], ["b"]]
    assert len(ir1.units) == 3
    assert len(ir1.rejected_units) == 1
    assert ir1.completeness == "BASIC_CHECKED"
    assert all(unit.confidence is None for unit in ir1.units)
    assert all(row.status == "COVERED" for row in ir1.coverage)
    report = json.loads((tmp_path / "knowledge_validation_report.json").read_text())
    assert report["rejected_units"][0]["validation"]["numeric_binding"] == "FAILED"


def test_failed_coverage_keeps_diagnostics_outside_factual_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("STRICT_SECTION_COVERAGE", "true")
    raw = raw_text()
    class Caller:
        def generate_structured(self, **kwargs):
            return KnowledgeUnitBatch(units=[KnowledgeUnitDraft(kind="metric", title="Profit", summary="Profit = 10.", priority="CRITICAL", evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)])])
    with pytest.raises(ValueError, match="bounded retry"):
        generate_validated_ir1(raw, Caller(), tmp_path)
    assert not (tmp_path / "ir1_validated.json").exists()
    report = json.loads((tmp_path / "knowledge_validation_report.json").read_text())
    assert report["completeness"] == "INCOMPLETE"
    assert report["rejected_units"]


def test_failed_coverage_non_strict_keeps_working(tmp_path, monkeypatch):
    monkeypatch.setenv("STRICT_SECTION_COVERAGE", "false")
    raw = raw_text()
    class Caller:
        def generate_structured(self, **kwargs):
            return KnowledgeUnitBatch(units=[
                KnowledgeUnitDraft(kind="concept", title="Overview", summary="Operating review.", priority="CRITICAL",
                                   evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)]),
                KnowledgeUnitDraft(kind="metric", title="Profit", summary="Profit = 10.", priority="CRITICAL",
                                   evidence=[EvidenceRef(source_id="b", excerpt=raw.blocks[0].text)]),
            ])
    ir1 = generate_validated_ir1(raw, Caller(), tmp_path)
    assert (tmp_path / "ir1_validated.json").exists()
    assert ir1.completeness == "INCOMPLETE"
    assert any("strict coverage disabled" in w for w in json.loads((tmp_path / "knowledge_validation_warnings.json").read_text()))


def test_semantic_batch_failure_preserves_completed_judgments_and_is_unknown():
    raw = raw_text()
    units = [claim("Revenue = 10; Profit = 2", title="Results") for _ in range(3)]
    for index, unit in enumerate(units):
        unit.unit_id = str(index)
        unit.validation = validate_claim(raw, unit)
    class Caller:
        def generate_structured(self, **kwargs):
            payload = json.loads(kwargs["prompt"])["SOURCE_DATA"]
            assert kwargs["stage"] == "claim_verification"
            if payload[0]["unit_id"] == "1":
                raise RuntimeError("judge unavailable")
            return SemanticBatch(judgments=[{"unit_id": payload[0]["unit_id"], "support": "CHECKED" if payload[0]["unit_id"] == "0" else "FAILED", "reason": "Fixture judgment"}])
    warnings = judge_semantics(raw, units, Caller(), batch_size=1)
    assert units[0].validation.status == "VERIFIED"
    assert units[1].validation.semantic_support == "UNKNOWN"
    assert units[2].validation.status == "REJECTED"
    assert len(warnings) == 1


def test_semantic_missing_or_forged_ids_cannot_mark_verified():
    raw = raw_text()
    unit = claim("Revenue = 10; Profit = 2")
    unit.validation = validate_claim(raw, unit)
    class Caller:
        def generate_structured(self, **kwargs):
            return {"judgments": [{"unit_id": "foreign", "support": "CHECKED", "reason": "wrong id"}]}
    assert judge_semantics(raw, [unit], Caller())
    assert unit.validation.semantic_support == "UNKNOWN"


def slide_context():
    return {"knowledge_units": [{"unit_id": "u", "evidence": [{"source_id": "b", "excerpt": "Revenue = 10; Profit = 2."}]}], "assets": []}


@pytest.mark.parametrize("content", [
    {"title": {"type": "heading", "text": "Profit = 10"}},
    {"body": {"type": "image", "source_asset_id": "image", "caption": "Profit = 10"}},
    {"body": {"type": "stat", "value": "10", "label": "Profit"}},
    {"body": {"type": "bullets", "items": ["Profit = 10"]}},
    {"body": {"type": "chart", "categories": ["Profit"], "series": [{"name": "Results", "values": [10]}]}},
    {"body": {"type": "diagram", "steps": [{"title": "Profit = 10"}]}},
])
def test_visible_numeric_title_caption_stat_chart_and_diagram_are_checked(content):
    slide = SlideSpec(layout="fixture", content=content)
    with pytest.raises(ValueError, match="binding"):
        validate_slide_grounding(slide, slide_context())


def test_composition_repairs_unsupported_title():
    class Caller:
        calls = 0
        async def generate_structured_async(self, **kwargs):
            self.calls += 1
            return SlideSpec(layout="TITLE_CENTERED", content={"title": {"type": "heading", "text": f"Profit = {10 if self.calls == 1 else 2}"}})
    caller = Caller()
    plan = SlidePlan(slide_id=1, title="Profit", objective="Show profit", narrative_role="opening", chunk_refs=["c"], source_unit_ids=["u"], preferred_layouts=["TITLE_CENTERED"])
    layout = {"layouts": {"TITLE_CENTERED": {"regions": {"title": {"allowed_types": ["heading"]}}}}}
    slide = asyncio.run(compose_single_slide(plan, slide_context(), layout, caller))
    assert caller.calls == 2
    assert slide.content["title"].text == "Profit = 2"
    assert slide.grounding["title.text"].status == "BASIC_CHECKED"


def test_composer_keeps_authorized_edits_and_visual_repairs_outside_source_data():
    context = slide_context()
    context.update(user_edit_instruction="Shorten the title", visual_critic_feedback="Use less text")
    class Caller:
        async def generate_structured_async(self, **kwargs):
            payload = json.loads(kwargs["prompt"])
            assert payload["requested_changes"] == {"user_edit_instruction": "Shorten the title", "visual_critic_feedback": "Use less text"}
            assert "user_edit_instruction" not in payload["SOURCE_DATA"]["context"]
            assert "visual_critic_feedback" not in payload["SOURCE_DATA"]["context"]
            assert payload["SOURCE_DATA"]["context"]["knowledge_units"] == context["knowledge_units"]
            return SlideSpec(layout="TITLE_CENTERED", content={"title": {"type": "heading", "text": "Profit"}})
    plan = SlidePlan(slide_id=1, title="Profit", objective="Show profit", narrative_role="opening", chunk_refs=["c"], source_unit_ids=["u"])
    layout = {"layouts": {"TITLE_CENTERED": {"regions": {"title": {"allowed_types": ["heading"]}}}}}
    assert asyncio.run(compose_single_slide(plan, context, layout, Caller())).content["title"].text == "Profit"


def test_visible_unknown_judge_never_claims_fully_verified():
    slide = SlideSpec(layout="fixture", content={"title": {"type": "heading", "text": "Profit = 2"}})
    validate_slide_grounding(slide, slide_context())
    class Caller:
        async def generate_structured_async(self, **kwargs):
            raise RuntimeError("offline")
    asyncio.run(judge_slide_claims(slide, slide_context(), Caller()))
    assert slide.grounding["title.text"].semantic_support == "UNKNOWN"


def test_completed_visible_judgment_survives_only_identical_claim_and_support():
    slide = SlideSpec(layout="fixture", content={"title": {"type": "heading", "text": "Profit = 2"}})
    context = slide_context()
    validate_slide_grounding(slide, context)
    slide.grounding["title.text"].semantic_support = "CHECKED"
    slide.grounding["title.text"].status = "VERIFIED"
    validate_slide_grounding(slide, context)
    assert slide.grounding["title.text"].status == "VERIFIED"
    slide.content["title"].text = "Revenue = 10"
    validate_slide_grounding(slide, context)
    assert slide.grounding["title.text"].semantic_support == "UNKNOWN"
    slide.grounding["title.text"].semantic_support = "CHECKED"
    slide.grounding["title.text"].status = "VERIFIED"
    context["knowledge_units"][0]["evidence"][0]["excerpt"] = "Revenue = 10; Profit = 3."
    validate_slide_grounding(slide, context)
    assert slide.grounding["title.text"].semantic_support == "UNKNOWN"


def test_terminal_semantic_provider_failure_stops_later_batches():
    from infrastructure.llm.llm_client import LLMRequestError
    units = [claim("Profit = 2") for _ in range(3)]
    for index, unit in enumerate(units):
        unit.unit_id = str(index)
        unit.validation = validate_claim(raw_text(), unit)
    class Caller:
        calls = 0
        def generate_structured(self, **kwargs):
            self.calls += 1
            raise LLMRequestError("no credits", error_class="billing")
    caller = Caller()
    judge_semantics(raw_text(), units, caller, batch_size=1)
    assert caller.calls == 1
    assert all(unit.validation.semantic_support == "UNKNOWN" for unit in units)


def test_unbound_table_cannot_hide_numeric_cells_without_headers():
    slide = SlideSpec(layout="fixture", content={"table": {"type": "table", "rows": [["Profit", "10"]]}})
    with pytest.raises(ValueError, match="aligned"):
        validate_slide_grounding(slide, slide_context())


def test_versioned_adapter_revalidates_without_mutating_original():
    original = {"schema_version": "2", "document_title": "Results", "units": [claim("Profit = 10").model_dump()]}
    snapshot = json.dumps(original, sort_keys=True)
    migrated = migrate_ir1_v2(original, raw_text())
    assert migrated.schema_version == "3"
    assert not migrated.units
    assert migrated.rejected_units
    assert migrated.completeness == "INCOMPLETE"
    assert json.dumps(original, sort_keys=True) == snapshot


def test_negative_decimal_exponent_and_currency_values_are_retained():
    values = mentions("Profit = -2.50 USD; Revenue = $1,000; Latency = 1e-3 ms.")
    assert [str(item.value) for item in values] == ["-2.50", "1000", "0.001"]


def test_real_builder_preserves_checked_metrics_in_pptx(tmp_path):
    from application.jobs.builder import PresentationBuilder
    source = raw_text()
    unit = claim("Revenue = 10; Profit = 2")
    assert validate_claim(source, unit).status == "BASIC_CHECKED"
    slide = SlideSpec(layout="TITLE_CENTERED", content={"title": {"type": "heading", "text": "Profit = 2"},
                      "subtitle": {"type": "text_group", "text": "Revenue = 10"}})
    validate_slide_grounding(slide, slide_context())
    target = tmp_path / "grounded.pptx"
    PresentationBuilder(Path(__file__).parents[1] / "config/ppt_default_layouts.json").build({"slides": [slide.model_dump(exclude_none=True)]}, str(target))
    pptx = Presentation(target)
    visible = [shape.text for shape in pptx.slides[0].shapes if shape.has_text_frame]
    assert "Profit = 2" in visible
    assert "Revenue = 10" in visible
