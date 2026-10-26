"""Safe single-slide editing for completed multi-agent runs."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infrastructure.utils.artifacts import read_validated_json, write_validated_json, update_manifest, atomic_json, file_hash, sha256_value, artifact_lock, portable_value, caller_fingerprint, CheckpointCache
from infrastructure.persistence.revisions import RevisionStore, copy_bundle, _rebase
from application.jobs.builder import PresentationBuilder
from domain.extraction.asset_registry import AssetRegistry
from infrastructure.llm.llm_client import LLMClient, LLMRequestError
from application.jobs.job_context import check, report as progress_report
from infrastructure.llm.llm_run import observe_llm_run
from infrastructure.ingestion.quality_controller import assess_final_artifact, write_quality_report, artifact_hash
from infrastructure.ingestion.slide_composer import compose_single_slide, retrieve_slide_context, write_ir2
from contracts.ir1_schema import ValidatedIR1
from contracts.ir2_content_schema import TargetIR2Presentation
from contracts.storyboard_schema import Storyboard, TopicChunk
from contracts.raw_extraction_schema import RawExtraction
from domain.evaluation.claim_verification import migrate_ir1_v2
from infrastructure.ingestion.knowledge_extractor import coverage_ledger, validate_knowledge_units, build_legacy_projection
from infrastructure.ingestion.slide_composer import validate_slide_grounding


def import_legacy_revision(*, output_dir, layouts_path, caller=None, renderer="python") -> Path:
    """Explicit legacy-v1 to revision-v1 adapter. Original files stay untouched.

    Rebuild and reassess from validated JSON rather than trusting an old deck's
    unbound quality report. Incompatible source/schema requires regeneration.
    """
    store = RevisionStore(output_dir)
    if store.active_id():
        raise ValueError("Run already has committed revisions")
    work = store.root / ".work" / "imports" / uuid.uuid4().hex
    work.mkdir(parents=True)
    for name in ("raw_extraction.json", "ir1_validated.json", "content_analysis.json", "chunks.json",
                 "storyboard.json", "ppt_content.json", "run_manifest.json", "edits.json", "suggestions.json"):
        source = store.root / name
        if source.is_file():
            atomic_json(work / name, _rebase(json.loads(source.read_text(encoding="utf-8")), store.root, work))
    if (store.root / "assets").exists():
        shutil.copytree(store.root / "assets", work / "assets")
    ir1 = read_validated_json(work / "ir1_validated.json", ValidatedIR1)
    raw = read_validated_json(work / "raw_extraction.json", RawExtraction)
    from domain.evaluation.coverage_ledger import initialize_ledger
    legacy_context = initialize_ledger(raw)
    legacy_context.legacy_context_unknown = True
    atomic_json(work / 'context_coverage.json', legacy_context.model_dump(mode='json'))
    accepted, _, _ = validate_knowledge_units(raw, ir1.units)
    if len(accepted) != len(ir1.units) or not accepted:
        raise ValueError("Legacy IR1 failed source grounding; regenerate rather than importing")
    ir1.units = accepted
    write_validated_json(work / "ir1_validated.json", ir1)
    write_validated_json(work / "content_analysis.json", build_legacy_projection(ir1))
    ir2 = read_validated_json(work / "ppt_content.json", TargetIR2Presentation)
    storyboard = read_validated_json(work / "storyboard.json", Storyboard)
    if len(storyboard.slides) != len(ir2.slides):
        raise ValueError("Legacy storyboard/IR2 counts do not match")
    chunks = _load_chunks(work / "chunks.json")
    layouts = json.loads(Path(layouts_path).read_text(encoding="utf-8"))
    from infrastructure.ingestion.slide_composer import validate_slide_spec
    for plan, slide in zip(storyboard.slides, ir2.slides):
        context = retrieve_slide_context(plan, ir1, chunks, storyboard)
        validate_slide_spec(slide, layouts, allowed_unit_ids=set(plan.source_unit_ids), assets=context["assets"],
                            source_item_ids=context["source_item_ids"], asset_source_items=context.get("asset_source_items", []))
        validate_slide_grounding(slide, context)
    builder = PresentationBuilder(layouts_path, backend=renderer, asset_registry=AssetRegistry(ir1.assets, run_root=work, source_item_ids=ir1.source_item_ids, asset_source_items=ir1.asset_source_items))
    deck = work / "op_ppt.pptx"
    builder.build(ir2.model_dump(exclude_none=True), str(deck))
    report = assess_final_artifact(deck, work / "quality_attempts" / artifact_hash(deck), ir1=ir1, ir2=ir2,
                                   caller=caller or LLMClient(), judge_enabled=False)
    if report.rendered.status == "FAILED_TO_RUN" or report.readiness == "BLOCKED":
        raise ValueError("Legacy revision cannot be imported without passing native/grounding checks")
    atomic_json(work / "scene_graph.json", builder.last_scene.model_dump(mode="json"))
    update_manifest(work / "run_manifest.json", renderer=builder.last_result.metadata(), options={"renderer": renderer},
                    assessed_scene_hash=sha256_value(portable_value(builder.last_scene.model_dump(mode="json"))))
    write_ir2(ir2, work)
    write_quality_report(report, work)
    update_manifest(work / "run_manifest.json", pipeline="multi-agent-v1", layouts_hash=sha256_value(layouts),
                    assessed_ir2_hash=sha256_value(portable_value(ir2.model_dump(exclude_none=True))),
                    assessed_ir1_hash=sha256_value(portable_value(ir1.model_dump(exclude_none=True))),
                    migration={"from": "legacy-run-v1", "to": "revision-v1", "original_directory": str(store.root)})
    return store.commit(work, base_revision=None, operation="legacy_import") / "op_ppt.pptx"


def _load_chunks(path: Path) -> list[TopicChunk]:
    return [TopicChunk.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def edit_multi_agent_slide(
    *,
    output_dir: str | Path,
    layouts_path: str | Path,
    slide_index: int,
    instruction: str,
    base_revision: str | None = None,
    max_repairs: int = 1,
    caller: Any | None = None,
    renderer: str | None = None,
    context=None, job_id: str | None = None, settings=None, api_key=None,
) -> Path:
    check(context)
    job_id = job_id or uuid.uuid4().hex
    store = RevisionStore(output_dir)
    with artifact_lock(store.root / ".locks" / ("edit-" + job_id + ".lock")):
        return _edit_revision_job(output_dir=output_dir, layouts_path=layouts_path, slide_index=slide_index,
                                  instruction=instruction, base_revision=base_revision, max_repairs=max_repairs,
                                  caller=caller, job_id=job_id, renderer=renderer, context=context, settings=settings, api_key=api_key)


def _edit_revision_job(*, output_dir, layouts_path, slide_index, instruction, base_revision, max_repairs, caller, job_id, renderer=None, context=None, settings=None, api_key=None):
    store = RevisionStore(output_dir)
    active = store.require_base(base_revision)
    record = store.verify(active)
    recorded_backend = json.loads((active / "run_manifest.json").read_text(encoding="utf-8")).get("renderer", {}).get("backend", "python")
    if renderer is not None and renderer != recorded_backend:
        raise ValueError("Editing retains the revision renderer; regenerate to change backend")
    work = store.root / ".work" / "edits" / job_id
    copy_bundle(active, work)
    if not (work / 'context_coverage.json').exists():
        from domain.evaluation.coverage_ledger import initialize_ledger
        legacy = initialize_ledger(read_validated_json(work / 'raw_extraction.json', RawExtraction))
        legacy.legacy_context_unknown = True
        atomic_json(work / 'context_coverage.json', legacy.model_dump(mode='json'))
    job = {"schema_version": 1, "job_id": job_id, "operation": "slide_edit", "status": "RUNNING",
           "base_revision": base_revision, "work": str(work)}
    atomic_json(store.job_path(job_id), job)
    client = caller or LLMClient(settings=settings, api_key=api_key, cancel_event=context.cancel_event if context else None)
    if hasattr(client, 'prepare_structured_request'):
        client.context_source = read_validated_json(work / 'raw_extraction.json', RawExtraction)
    try:
        _edit_multi_agent_slide(output_dir=work, layouts_path=layouts_path, slide_index=slide_index,
                               instruction=instruction, max_repairs=max_repairs, caller=client, job_context=context)
        update_manifest(work / "run_manifest.json", job_id=job_id)
        progress_report(context, "publication")
        committed = store.commit(work, base_revision=base_revision, operation="slide_edit",
                                 generation_signature=record.get("generation_signature"))
        job.update(status="COMPLETED", revision_id=committed.name)
        # Derived slide caches follow accepted edits, never rejected/stale candidates.
        try:
            from application.pipeline.orchestrator import runtime_dependencies
            from infrastructure.ingestion.slide_composer import slide_cache_key
            with artifact_lock(store.root / ".locks" / "publication.lock"):
                manifest = json.loads((committed / "run_manifest.json").read_text(encoding="utf-8"))
                if store.active_id() == committed.name and manifest.get("generation_model_fingerprint") == caller_fingerprint(client) and manifest.get("generation_dependencies") == runtime_dependencies():
                    ir1 = read_validated_json(committed / "ir1_validated.json", ValidatedIR1)
                    storyboard = read_validated_json(committed / "storyboard.json", Storyboard)
                    chunks = _load_chunks(committed / "chunks.json")
                    ir2 = read_validated_json(committed / "ppt_content.json", TargetIR2Presentation)
                    layouts = json.loads(Path(layouts_path).read_text(encoding="utf-8"))
                    cache = CheckpointCache(store.root / ".cache/slides", reuse=True)
                    for plan, slide in zip(storyboard.slides, ir2.slides):
                        context = retrieve_slide_context(plan, ir1, chunks, storyboard)
                        key = slide_cache_key(plan, context, layouts, client, manifest.get("options", {}).get("max_repairs_per_slide", 1))
                        cache.put(key, slide.model_dump(mode="json"))
        except OSError as error:
            job["cache_warning"] = type(error).__name__  # Committed bundle remains authoritative.
        return committed / "op_ppt.pptx"
    except BaseException as error:
        job.update(status="CANCELLED" if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)) or
                   getattr(error, "error_class", None) == "cancelled" else "FAILED", error=type(error).__name__)
        raise
    finally:
        atomic_json(store.job_path(job_id), job)


def _edit_multi_agent_slide(
    *, output_dir: str | Path, layouts_path: str | Path, slide_index: int, instruction: str,
    max_repairs: int = 1, caller: Any | None = None,
    job_context=None,
) -> Path:
    """Recompose one slide without changing validated source knowledge or other specs."""

    if not instruction.strip():
        raise ValueError("A non-empty edit instruction is required.")
    root = Path(output_dir)
    manifest_path = root / "run_manifest.json"
    required = {
        "manifest": manifest_path,
        "ir1": root / "ir1_validated.json",
        "chunks": root / "chunks.json",
        "storyboard": root / "storyboard.json",
        "ir2": root / "ppt_content.json",
        "pptx": root / "op_ppt.pptx",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Cannot edit slide; missing multi-agent artifacts: {', '.join(missing)}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("pipeline") != "multi-agent-v1":
        raise ValueError("The selected output directory was not created by the multi-agent pipeline.")

    stored_ir1 = json.loads(required["ir1"].read_text(encoding="utf-8"))
    if stored_ir1.get("schema_version") == "2":
        raw_path = root / "raw_extraction.json"
        if not raw_path.exists():
            raise ValueError("Legacy IR1 requires raw_extraction.json for R03 revalidation; regenerate this run.")
        raw = read_validated_json(raw_path, RawExtraction)
        ir1 = migrate_ir1_v2(stored_ir1, raw)
        ir1.coverage = coverage_ledger(raw, ir1.units, [*ir1.units, *ir1.rejected_units])
        write_validated_json(root / "ir1_r03_adapted.json", ir1)
        if ir1.rejected_units or any(row.status != "COVERED" for row in ir1.coverage):
            raise ValueError("Legacy IR1 failed R03 grounding/coverage; diagnostics are in ir1_r03_adapted.json. Regenerate before editing.")
    else:
        ir1 = ValidatedIR1.model_validate(stored_ir1)
    chunks = _load_chunks(required["chunks"])
    storyboard = read_validated_json(required["storyboard"], Storyboard)
    presentation = read_validated_json(required["ir2"], TargetIR2Presentation)
    if not 1 <= slide_index <= len(presentation.slides) or slide_index > len(storyboard.slides):
        raise ValueError(f"Slide index {slide_index} is outside the deck range.")

    layouts_spec = json.loads(Path(layouts_path).read_text(encoding="utf-8"))
    if manifest.get("layouts_hash") and manifest["layouts_hash"] != sha256_value(layouts_spec):
        raise ValueError("Editing requires the revision's layout catalog; regenerate with the changed theme first")
    plan = storyboard.slides[slide_index - 1]
    for existing_plan, existing_slide in zip(storyboard.slides, presentation.slides):
        existing_context = retrieve_slide_context(existing_plan, ir1, chunks, storyboard)
        validate_slide_grounding(existing_slide, existing_context)
    context = retrieve_slide_context(plan, ir1, chunks, storyboard)
    context["user_edit_instruction"] = instruction.strip()
    client = caller or LLMClient()
    with observe_llm_run(client, manifest_path, operation="slide_edit"):
        progress_report(job_context, "composition", 0, 1)
        replacement = asyncio.run(
            compose_single_slide(
                plan,
                context,
                layouts_spec,
                client,
                max_repairs=max_repairs,
                current_slide=presentation.slides[slide_index - 1],
                job_context=job_context,
            )
        )
        progress_report(job_context, "composition", 1, 1)
        slides = list(presentation.slides)
        slides[slide_index - 1] = replacement
        updated = TargetIR2Presentation(output_filename="op_ppt.pptx", slides=slides)

        # Keep the prior JSON/PPTX until both the replacement and compilation pass.
        pending_pptx = root / "op_ppt.editing.pptx"
        backend = manifest.get("renderer", {}).get("backend", "python")
        # Edits inherit the deck's recorded theme and layout mode so a revised
        # slide renders coherently with the rest of the presentation.
        from domain.rendering.theme_engine import load_theme
        theme_name = manifest.get("options", {}).get("theme")
        edit_theme = load_theme(theme_name) if theme_name else None
        dynamic_layout = bool(manifest.get("options", {}).get("dynamic_layout", False))
        builder = PresentationBuilder(layouts_path, backend=backend, asset_registry=AssetRegistry(ir1.assets, run_root=root, source_item_ids=ir1.source_item_ids, asset_source_items=ir1.asset_source_items,
            min_ppi=manifest.get('options',{}).get('asset_options',{}).get('min_ppi',150)), theme=edit_theme, dynamic_layout=dynamic_layout)
        progress_report(job_context, "build")
        builder.build(updated.model_dump(exclude_none=True), str(pending_pptx))
        options = manifest.get("options", {})
        progress_report(job_context, "quality checks")
        report = assess_final_artifact(pending_pptx, root / "quality_attempts" / artifact_hash(pending_pptx), ir1=ir1, ir2=updated,
                                       caller=client, judge_enabled=options.get("polish", "off") != "off",
                                       deep_verification=options.get("deep_verification", False))
        check(job_context)
        # Scoped visual repair for the edited slide: the generation path has
        # always had this loop; without it, an overflow edit is rejected
        # wholesale on Windows or committed unchecked elsewhere.
        from application.pipeline.orchestrator import collect_visual_repair_feedback
        feedback = collect_visual_repair_feedback(report, builder).get(slide_index, [])
        if feedback and max_repairs > 0:
            progress_report(job_context, "composition", 0, 1)
            retry_context = dict(context)
            retry_context["visual_critic_feedback"] = " ; ".join(feedback)
            try:
                retry_replacement = asyncio.run(compose_single_slide(
                    plan, retry_context, layouts_spec, client, max_repairs=0,
                    current_slide=replacement, job_context=job_context))
                retry_slides = list(presentation.slides)
                retry_slides[slide_index - 1] = retry_replacement
                retry_ir2 = TargetIR2Presentation(output_filename="op_ppt.pptx", slides=retry_slides)
                retry_pptx = root / "op_ppt.editing.retry.pptx"
                progress_report(job_context, "build")
                builder.build(retry_ir2.model_dump(exclude_none=True), str(retry_pptx))
                progress_report(job_context, "quality checks")
                retry_report = assess_final_artifact(retry_pptx, root / "quality_attempts" / artifact_hash(retry_pptx), ir1=ir1, ir2=retry_ir2,
                                                     caller=client, judge_enabled=options.get("polish", "off") != "off",
                                                     deep_verification=options.get("deep_verification", False))
                check(job_context)
                if retry_report.rendered.status != "FAILED_TO_RUN" and retry_report.readiness != "BLOCKED":
                    replacement, updated, pending_pptx, report = retry_replacement, retry_ir2, retry_pptx, retry_report
                progress_report(job_context, "composition", 1, 1)
            except Exception as retry_error:
                # The first attempt stays the candidate; its own gate decides.
                # Cancellation and provider-fatal errors must still surface.
                if isinstance(retry_error, (asyncio.CancelledError, LLMRequestError)) or getattr(retry_error, "error_class", None) == "cancelled":
                    raise
        if report.rendered.status == "FAILED_TO_RUN":
            raise ValueError("Edited artifact could not be rendered; previous artifact retained: " + str(report.rendered.reason))
        if report.readiness == "BLOCKED":
            raise ValueError("Edited PPTX failed quality checks: " + " | ".join(report.hard_failures))
        atomic_json(root / "scene_graph.json", builder.last_scene.model_dump(mode="json"))
        update_manifest(manifest_path, renderer=builder.last_result.metadata(),
                        assessed_scene_hash=sha256_value(portable_value(builder.last_scene.model_dump(mode="json"))))
        write_ir2(updated, root)
        os.replace(pending_pptx, required["pptx"])
        write_quality_report(report, root)
        (root / "vision_audit_report.json").write_text(report.judge.model_dump_json(indent=2), encoding="utf-8")
        update_manifest(manifest_path, readiness=report.readiness, quality_status=report.status,
                        assessed_ir2_hash=sha256_value(portable_value(updated.model_dump(exclude_none=True))),
                        assessed_ir1_hash=sha256_value(portable_value(ir1.model_dump(exclude_none=True))),
                        artifact_hash=report.artifact_hash, revision_id=report.revision_id,
                        vision_status=report.judge.status, vision_reason=report.judge.reason)
        stages = json.loads(manifest_path.read_text(encoding="utf-8")).get("stages", {})
        for stage, path in (("ir2", required["ir2"]), ("pptx", required["pptx"])):
            stages[stage] = {**stages.get(stage, {}), "status": "PASSED", "output": str(path),
                             "output_hash": file_hash(path), "edited_slide": slide_index}
        update_manifest(manifest_path, stages=stages, slide_bindings={str(index + 1): sha256_value(slide.model_dump())
                                                                    for index, slide in enumerate(updated.slides)})

        edit_path = root / "edits.json"
        edits = json.loads(edit_path.read_text(encoding="utf-8")) if edit_path.exists() else []
        edits.append(
            {
                "slide_index": slide_index,
                "instruction": instruction.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_unit_ids": plan.source_unit_ids,
            }
        )
        temporary = edit_path.with_suffix(edit_path.suffix + ".tmp")
        temporary.write_text(json.dumps(edits, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, edit_path)
        return required["pptx"]
