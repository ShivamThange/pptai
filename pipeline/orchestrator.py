"""Multi-agent document-to-PPTX orchestrator."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
import shutil
from dataclasses import dataclass, replace, asdict, field
from pathlib import Path
from typing import Any

from infrastructure.utils.artifacts import read_validated_json, sha256_value, update_manifest, file_hash, portable_value, dependency_fingerprint, caller_fingerprint, CheckpointCache, artifact_lock, atomic_json
from infrastructure.persistence.revisions import RevisionStore, StaleRevisionError
from application.jobs.job_context import check, report
from application.jobs.builder import PresentationBuilder
from domain.extraction.asset_registry import AssetRegistry
from infrastructure.llm.llm_client import LLMClient, LLMRequestError
from infrastructure.llm.llm_run import observe_llm_run
from infrastructure.ingestion.chunker import build_chunks, write_chunks
from infrastructure.ingestion.knowledge_extractor import generate_validated_ir1
from infrastructure.ingestion.quality_controller import assess_final_artifact, write_quality_report, artifact_hash
from infrastructure.ingestion.slide_composer import compose_presentation_parallel, compose_single_slide, retrieve_slide_context, write_ir2, validate_slide_grounding, validate_slide_spec, slide_cache_key
from infrastructure.ingestion.source_adapter import build_raw_extraction
from infrastructure.ingestion.storyboard_planner import plan_storyboard, write_storyboard
from contracts.ir1_schema import ValidatedIR1
from contracts.ir2_content_schema import TargetIR2Presentation
from contracts.raw_extraction_schema import RawExtraction
from contracts.asset_schema import AssetOptions
from contracts.storyboard_schema import Storyboard, TopicChunk

UNSPECIFIED_BASE = object()


@dataclass(frozen=True)
class MultiAgentOptions:
    asset_options: AssetOptions = field(default_factory=AssetOptions, kw_only=True)
    layouts_path: str
    output_dir: str
    lens: str = "executive"
    min_slides: int = 5
    max_slides: int = 10
    resume: bool = False
    max_section_retries: int = 1
    max_repairs_per_slide: int = 1
    max_concurrency: int = 2
    polish: str = "off"
    deep_verification: bool = False
    semantic_batch_size: int = 8
    renderer: str = "python"
    extraction_mode: str = "llm"
    use_gpu: bool = False
    instruction: str = ""
    theme: str = "auto"
    dynamic_layout: bool = True

    def __post_init__(self):
        if not isinstance(self.asset_options, AssetOptions):
            object.__setattr__(self, 'asset_options', AssetOptions.model_validate(self.asset_options))
        from domain.rendering.theme_engine import available_themes
        if self.theme != "auto" and self.theme not in available_themes():
            raise ValueError(f"Unknown theme '{self.theme}'. Available: auto, {', '.join(sorted(available_themes()))}")


def _load_chunks(path: Path) -> list[TopicChunk]:
    return [TopicChunk.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _stage_matches(manifest: dict[str, Any], stage: str, input_hash: str, output: Path) -> bool:
    entry = manifest.get("stages", {}).get(stage, {})
    return bool(entry.get("status") == "PASSED" and entry.get("input_hash") == input_hash and output.is_file()
                and entry.get("output_hash") == file_hash(output))


def _record_stage(manifest_path: Path, stage: str, *, input_hash: str, output: Path, status: str = "PASSED") -> None:
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stages = dict(manifest.get("stages", {}))
    stages[stage] = {"status": status, "input_hash": input_hash, "output": str(output), "output_hash": file_hash(output)}
    update_manifest(manifest_path, stages=stages)


def run_multi_agent_pipeline(
    structural_ir_path: str | Path, options: MultiAgentOptions, *, caller: Any | None = None,
    context=None, job_id: str | None = None, expected_base_revision=UNSPECIFIED_BASE,
) -> Path:
    from renderers.factory import validate_renderer_runtime, renderer_fingerprint
    validate_renderer_runtime(options.renderer)
    check(context)
    client = caller or LLMClient(cancel_event=context.cancel_event if context else None)
    store = RevisionStore(options.output_dir)
    structural_hash = structural_fingerprint(structural_ir_path)
    preference = {key: value for key, value in asdict(options).items() if key not in {"output_dir", "resume", "layouts_path", "max_concurrency"}}
    preference['asset_options'] = options.asset_options.model_dump(mode='json')
    from domain.rendering.formula_renderer import formula_identity
    from domain.rendering.theme_engine import load_theme, theme_signature
    resolved_theme = load_theme(options.theme, options.lens)
    signature = sha256_value({"source": structural_hash, "preferences": preference,
                              'asset_runtime': formula_identity() if options.asset_options.mode=='structured' else None,
                              "layouts": file_hash(options.layouts_path), "caller": caller_fingerprint(client),
                              "theme": {"id": resolved_theme.id, "hash": theme_signature(options.theme, options.lens)},
                              "dynamic_layout": options.dynamic_layout,
                              "dependencies": runtime_dependencies(), "renderer": renderer_fingerprint(options.renderer)})
    with artifact_lock(store.root / ".locks" / "generation.lock"):
        store.recover_jobs()
        base_revision = store.active_id()
        check(context)
        if expected_base_revision is not UNSPECIFIED_BASE and base_revision != expected_base_revision:
            raise StaleRevisionError("Stale base_revision; reload the deck before regenerating")
        edit_binding = None
        if options.resume and base_revision:
            active = store.resolve()
            record = store.verify(active)
            if record.get("generation_signature") == signature:
                return active / "op_ppt.pptx"
            if record.get("operation") == "slide_edit" and record.get("source_hash") == structural_hash:
                edit_binding = record["ir_hashes"]["ppt_content.json"]
        work = store.root / ".work" / signature
        work.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(structural_ir_path, work / "structural_ir_snapshot.json")
        from infrastructure.ingestion.collection import retain_sources
        retain_sources(structural_ir_path, work)
        job_id = job_id or uuid.uuid4().hex
        job = {"schema_version": 1, "job_id": job_id, "operation": "generation", "status": "RUNNING",
               "work": str(work), "generation_signature": signature, "base_revision": base_revision}
        atomic_json(store.job_path(job_id), job)
        update_manifest(work / "run_manifest.json", structural_hash=structural_hash, job_id=job_id)
        try:
            with observe_llm_run(client, work / "run_manifest.json"):
                _run_multi_agent_pipeline(structural_ir_path, replace(options, output_dir=str(work)), caller=client,
                                          cache_root=store.root / ".cache", edit_binding=edit_binding, context=context)
            report(context, "publication")
            committed = store.commit(work, base_revision=base_revision, operation="generation", generation_signature=signature)
            job.update(status="COMPLETED", revision_id=committed.name)
            return committed / "op_ppt.pptx"
        except BaseException as error:
            job.update(status="CANCELLED" if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)) or
                       getattr(error, "error_class", None) == "cancelled" else "FAILED", error=type(error).__name__)
            raise
        finally:
            atomic_json(store.job_path(job_id), job)
            if (work / "run_manifest.json").exists():
                # Mutable job summary; deck/IR readers use active.json exclusively.
                atomic_json(store.root / "run_manifest.json", json.loads((work / "run_manifest.json").read_text(encoding="utf-8")))


def runtime_dependencies():
    # evalute/ and scripts/ are offline analysis tools; hashing them would
    # invalidate every resume cache on each unrelated code touch.
    return dependency_fingerprint(*[p.relative_to(Path(__file__).resolve().parents[1]).as_posix()
                                   for folder in ("core", "pipeline", "schemas", "tools", "config", "renderers")
                                   for p in (Path(__file__).resolve().parents[1] / folder).rglob("*.py")
                                   if "tests" not in p.parts], "renderers/pptxgenjs/builder.js", "renderers/pptxgenjs/package.json",
                                   "renderers/pptxgenjs/package-lock.json")


def _scene_geometry_summary(builder, slide_number: int) -> str:
    """Human-readable region sizes/fonts so repair prompts carry real numbers."""
    scene = getattr(builder, "last_scene", None)
    if scene is None or slide_number > len(scene.slides):
        return ""
    parts = []
    for obj in scene.slides[slide_number - 1].objects:
        if obj.kind in {"heading", "text_group", "bullets", "numbered_list", "table", "shape"}:
            size = (obj.style or {}).get("font_size", "?")
            name = obj.object_id.split("/", 1)[-1]
            if obj.kind == "table":
                rows = len(obj.content.get("rows", []))
                parts.append(f"{name}: {obj.box.w:.1f}x{obj.box.h:.1f}in table with {rows} rows")
            else:
                parts.append(f"{name}: {obj.box.w:.1f}x{obj.box.h:.1f}in @ {size}pt")
    return "; ".join(parts)


def _fitting_feedback(fitting_report: dict, slide_number: int) -> list[str]:
    """Surface deterministic-fitting warnings as repair motivation with numbers."""
    result = []
    for entry in (fitting_report or {}).get("adjustments", []):
        try:
            entry_slide = int(str(entry.get("slide_id", "")).rsplit("-", 1)[-1])
        except ValueError:
            continue
        if entry_slide == slide_number and entry.get("severity") == "warning":
            result.append(f"Deterministic fitting report: {entry.get('action')} - {entry.get('detail')}")
    return result


def collect_visual_repair_feedback(final_report, builder) -> dict[int, list[str]]:
    """Quantitative, geometry-aware feedback that never orders destructive edits.

    Source-bound tables are never removed or truncated: the renderer scales
    their fonts. The model is told to shorten surrounding prose or pick a
    roomier layout instead.
    """
    feedback_by_slide: dict[int, list[str]] = {}
    for row in final_report.slides:
        if row["out_of_bounds_count"] or row["suspicious_overlap_count"] or any(f["required"] for f in row["font_findings"]):
            feedback_by_slide.setdefault(row["slide_no"], []).extend(row["warnings"])
    for finding in final_report.rendered.details.get("findings", []):
        if not finding.get("required", True):
            continue
        slide_no = finding["slide_no"]
        check = finding.get("check")
        if check in {"POWERPOINT_MEASURED_OUT_OF_BOUNDS", "POWERPOINT_MEASURED_GEOMETRY_CHANGE"}:
            box = finding.get("actual_box_pt") or ()
            size = (f" (measured box {box[0]:.0f}x{box[1]:.0f}pt at {box[2]:.0f},{box[3]:.0f}pt)"
                    if len(box) == 4 else "")
            feedback_by_slide.setdefault(slide_no, []).append(
                "PowerPoint expanded an object beyond its resolved box" + size +
                ". If it is a source-bound table, KEEP the table with every row; the renderer already scales its font - "
                "do not remove or truncate it. Instead shorten surrounding text, drop whole low-value bullets, or "
                "switch to a layout with a larger region for that content.")
        elif check == "POWERPOINT_MEASURED_TEXT_OVERFLOW":
            needed, available = finding.get("bound_height_pt"), finding.get("available_height_pt")
            ratio = (f" (text needs {needed:.0f}pt of height in a {available:.0f}pt box, {needed / max(available, 1):.0%} filled)"
                     if isinstance(needed, (int, float)) and isinstance(available, (int, float)) else "")
            feedback_by_slide.setdefault(slide_no, []).append(
                "Rendered text exceeds its region" + ratio +
                ". Reduce the amount of text in that region: fewer bullets or shorter sentences, or a layout with a "
                "larger text region. Preserve every source number exactly; shorten wording instead of dropping facts.")
        else:
            feedback_by_slide.setdefault(slide_no, []).append(
                "Rendered text clips its box; reduce content or use a suitable layout.")
    for audit in final_report.judge.details.get("audits", []):
        if not audit["passed"]:
            feedback_by_slide.setdefault(audit["slide_id"], []).append(audit.get("actionable_feedback") or audit["critique_summary"])
    fitting_report = getattr(builder, "fitting_report", {}) or {}
    for slide_no, feedback in list(feedback_by_slide.items()):
        feedback.extend(_fitting_feedback(fitting_report, slide_no))
        geometry = _scene_geometry_summary(builder, slide_no)
        if geometry:
            feedback.append("Current scene geometry (width x height, font): " + geometry +
                            ". Compose within these sizes; the capacity contract in the layout catalog lists exact limits.")
    return feedback_by_slide


def structural_fingerprint(path):
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    files = {}
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"file_path", "path", "json_path", "csv_path", "source_manifest_path"} and isinstance(item, str):
                    asset = Path(item)
                    if not asset.is_absolute():
                        asset = source.parent / asset
                    files[item] = file_hash(asset) if asset.is_file() else "MISSING"
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    manifest_path = source.parent / 'source_manifest.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for member in manifest.get('members', []):
            directory = Path(member['parse_directory'])
            for name in [*member['artifacts'], 'parse_record.json']:
                retained = directory / name
                files[str(retained)] = file_hash(retained) if retained.is_file() else 'MISSING'
    elif (source.parent / 'parse_record.json').is_file():
        record = json.loads((source.parent / 'parse_record.json').read_text(encoding='utf-8'))
        for name in [*record['artifacts'], 'parse_record.json']:
            retained = source.parent / name
            files[str(retained)] = file_hash(retained) if retained.is_file() else 'MISSING'
    return sha256_value({"structural": data, "actual_assets": files})


def _run_multi_agent_pipeline(
    structural_ir_path: str | Path, options: MultiAgentOptions, *, caller: Any, cache_root: Path | None = None,
    edit_binding: str | None = None,
    context=None,
) -> Path:
    """Create and validate a deck while preserving all resumable stage artifacts."""

    output_dir = Path(options.output_dir)
    if options.polish not in {"off", "auto", "all"}:
        raise ValueError("polish must be one of: off, auto, all")
    output_dir.mkdir(parents=True, exist_ok=True)
    layouts_path = Path(options.layouts_path)
    layouts_spec = json.loads(layouts_path.read_text(encoding="utf-8"))
    from domain.rendering.theme_engine import load_theme
    resolved_theme = load_theme(options.theme, options.lens)
    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    update_manifest(
        manifest_path,
        pipeline="multi-agent-v1",
        structural_ir_path=str(structural_ir_path),
        layouts_hash=sha256_value(layouts_spec),
        options={
            "asset_options": options.asset_options.model_dump(mode='json'),
            "lens": options.lens,
            "min_slides": options.min_slides,
            "max_slides": options.max_slides,
            "max_section_retries": options.max_section_retries,
            "max_repairs_per_slide": options.max_repairs_per_slide,
            "polish": options.polish,
            "deep_verification": options.deep_verification,
            "renderer": options.renderer,
            "extraction_mode": options.extraction_mode,
            "theme": resolved_theme.id,
            "dynamic_layout": options.dynamic_layout,
        },
    )

    check(context)
    raw_path = output_dir / "raw_extraction.json"
    base_raw_path = output_dir / 'raw_extraction_base.json' if options.asset_options.mode=='structured' else raw_path
    structural_hash = sha256_value({"structural_ir": structural_fingerprint(structural_ir_path),
                                   "adapter": dependency_fingerprint("pipeline/source_adapter.py", "schemas/raw_extraction_schema.py")})
    if options.resume and _stage_matches(manifest, "raw_extraction", structural_hash, base_raw_path):
        raw = read_validated_json(base_raw_path, RawExtraction)
    else:
        raw = build_raw_extraction(structural_ir_path, output_dir)
        if base_raw_path!=raw_path:
            atomic_json(base_raw_path,raw.model_dump(mode='json'))
        _record_stage(manifest_path, "raw_extraction", input_hash=structural_hash, output=base_raw_path)

    client = caller or LLMClient()
    if options.asset_options.mode == 'structured':
        from infrastructure.ingestion.asset_adapters import enrich_assets
        from domain.rendering.formula_renderer import formula_identity
        base_path = output_dir / 'raw_extraction_base.json'
        if raw.schema_version == '4' and base_path.is_file():
            raw = read_validated_json(base_path, RawExtraction)
        key = sha256_value({'raw': portable_value(raw.model_dump()), 'options': options.asset_options.model_dump(),
                            'dependencies': runtime_dependencies(), 'model': caller_fingerprint(client),
                            'math': formula_identity()})
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        from infrastructure.ingestion.asset_adapters import load_source_bundles
        load_source_bundles(structural_ir_path,output_dir)
        cache_valid = options.resume and _stage_matches(manifest, 'asset_enrichment', key, output_dir / 'asset_enrichment.json')
        if cache_valid:
            try:
                cached_raw = read_validated_json(raw_path,RawExtraction)
                registry = AssetRegistry(cached_raw.assets,run_root=output_dir,source_item_ids=cached_raw.source_item_ids,
                                         asset_source_items=cached_raw.asset_source_items)
                for asset in cached_raw.assets:
                    if asset.content:
                        registry.validate_derivation(asset.asset_id)
            except (ValueError,OSError):
                cache_valid = False
                raw = build_raw_extraction(structural_ir_path,output_dir)
        if not cache_valid:
            atomic_json(output_dir / 'raw_extraction_base.json', raw.model_dump(mode='json'))
            raw = enrich_assets(raw, structural_ir_path, output_dir, options.asset_options, caller=client, context=context)
            atomic_json(raw_path, raw.model_dump(mode='json'))
            _record_stage(manifest_path, 'asset_enrichment', input_hash=key, output=output_dir / 'asset_enrichment.json')
        else:
            raw = cached_raw
    if hasattr(client, 'prepare_structured_request'):
        client.context_source = raw
    report(context, "knowledge extraction")
    ir1_path = output_dir / "ir1_validated.json"
    model_name = getattr(client, "model", "external-caller")
    model_fingerprint = caller_fingerprint(client)
    dependencies = runtime_dependencies()
    update_manifest(manifest_path, generation_model_fingerprint=model_fingerprint, generation_dependencies=dependencies)
    raw_hash = sha256_value({"raw": portable_value(raw.model_dump()), "schema": ValidatedIR1.model_json_schema(), "dependencies": dependencies, "model": model_fingerprint,
                             "deep_verification": options.deep_verification, "semantic_batch_size": options.semantic_batch_size,
                             "max_section_retries": options.max_section_retries, "extraction_mode": options.extraction_mode})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if options.resume and _stage_matches(manifest, "validated_ir1", raw_hash, ir1_path):
        ir1 = read_validated_json(ir1_path, ValidatedIR1)
    else:
        ir1 = generate_validated_ir1(raw, client, output_dir, max_section_retries=options.max_section_retries,
                                     deep_verification=options.deep_verification, semantic_batch_size=options.semantic_batch_size,
                                     extraction_mode=options.extraction_mode, deduplicate=True,
                                     checkpoint_cache=CheckpointCache((cache_root or output_dir / ".cache") / "extraction", reuse=options.resume), context=context)
        _record_stage(manifest_path, "validated_ir1", input_hash=raw_hash, output=ir1_path)

    report(context, "knowledge extraction", 1, 1)
    report(context, "chunking")
    chunks_path = output_dir / "chunks.json"
    ir1_hash = sha256_value({"ir1": portable_value(ir1.model_dump()), "schema": TopicChunk.model_json_schema(), "dependencies": dependencies})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if options.resume and _stage_matches(manifest, "chunks", ir1_hash, chunks_path):
        chunks = _load_chunks(chunks_path)
    else:
        chunks = build_chunks(ir1)
        write_chunks(chunks, output_dir, ir1=ir1)
        _record_stage(manifest_path, "chunks", input_hash=ir1_hash, output=chunks_path)

    report(context, "chunking", 1, 1)
    report(context, "storyboard")
    storyboard_path = output_dir / "storyboard.json"
    storyboard_hash = sha256_value(
        {"ir1": ir1.model_dump(), "chunks": [chunk.model_dump() for chunk in chunks], "layouts": layouts_spec, "lens": options.lens,
         "instruction": options.instruction,
         "min_slides": options.min_slides, "max_slides": options.max_slides, "schema": Storyboard.model_json_schema(), "dependencies": dependencies, "model": model_fingerprint}
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if options.resume and _stage_matches(manifest, "storyboard", storyboard_hash, storyboard_path):
        storyboard = read_validated_json(storyboard_path, Storyboard)
    else:
        storyboard = plan_storyboard(
            ir1, chunks, layouts_spec, client, lens=options.lens, min_slides=options.min_slides, max_slides=options.max_slides,
            instruction=options.instruction,
        )
        write_storyboard(storyboard, output_dir)
        _record_stage(manifest_path, "storyboard", input_hash=storyboard_hash, output=storyboard_path)

    report(context, "storyboard", 1, 1)
    report(context, "composition", 0, len(storyboard.slides))
    ir2_path = output_dir / "ppt_content.json"
    composition_hash = sha256_value(
        {"storyboard": storyboard.model_dump(), "ir1": ir1.model_dump(), "chunks": [chunk.model_dump() for chunk in chunks],
         "layouts": layouts_spec, "max_repairs": options.max_repairs_per_slide, "schema": TargetIR2Presentation.model_json_schema(), "dependencies": dependencies, "model": model_fingerprint,
         "edit_binding": edit_binding}
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if options.resume and _stage_matches(manifest, "ir2", composition_hash, ir2_path):
        ir2 = read_validated_json(ir2_path, TargetIR2Presentation)
    else:
        ir2 = asyncio.run(
            compose_presentation_parallel(
                storyboard,
                ir1,
                chunks,
                layouts_spec,
                client,
                max_concurrency=options.max_concurrency,
                max_repairs_per_slide=options.max_repairs_per_slide,
                checkpoint_cache=CheckpointCache((cache_root or output_dir / ".cache") / "slides", reuse=options.resume),
                context=context,
            )
        )
        write_ir2(ir2, output_dir)
        _record_stage(manifest_path, "ir2", input_hash=composition_hash, output=ir2_path)

    report(context, "composition", len(storyboard.slides), len(storyboard.slides))
    report(context, "build")
    pptx_path = output_dir / "op_ppt.pptx"
    candidate_path = output_dir / "op_ppt.candidate.pptx"
    for plan, slide in zip(storyboard.slides, ir2.slides):
        slide_context = retrieve_slide_context(plan, ir1, chunks, storyboard)
        validate_slide_spec(slide, layouts_spec, allowed_unit_ids={unit["unit_id"] for unit in slide_context["knowledge_units"]}, assets=slide_context["assets"], source_item_ids=slide_context["source_item_ids"], asset_source_items=slide_context.get("asset_source_items", []))
        validate_slide_grounding(slide, slide_context)
    builder = PresentationBuilder(layouts_path, backend=options.renderer, asset_registry=AssetRegistry(ir1.assets, run_root=output_dir, source_item_ids=ir1.source_item_ids, asset_source_items=ir1.asset_source_items, min_ppi=options.asset_options.min_ppi), theme=resolved_theme, dynamic_layout=options.dynamic_layout)
    builder.build(ir2.model_dump(exclude_none=True), str(candidate_path))
    atomic_json(output_dir / "layout_report.json", builder.layout_report)
    report(context, "build", 1, 1)
    report(context, "quality checks")
    attempt_dir = output_dir / "quality_attempts" / artifact_hash(candidate_path)
    final_report = assess_final_artifact(candidate_path, attempt_dir, ir1=ir1, ir2=ir2, caller=client,
                                        judge_enabled=options.polish != "off", deep_verification=options.deep_verification)
    check(context)  # Optional judging may catch provider cancellation internally.
    feedback_by_slide = collect_visual_repair_feedback(final_report, builder)

    if feedback_by_slide and options.max_repairs_per_slide > 0:
        async def repair_flagged_slides() -> TargetIR2Presentation:
            repaired = list(ir2.slides)
            semaphore = asyncio.Semaphore(max(1, options.max_concurrency))

            async def repair(slide_number: int, feedback: list[str]) -> tuple[int, Any]:
                plan = storyboard.slides[slide_number - 1]
                check(context)
                slide_context = retrieve_slide_context(plan, ir1, chunks, storyboard)
                slide_context["visual_critic_feedback"] = " ; ".join(feedback)
                slide_context["current_slide"] = ir2.slides[slide_number - 1].model_dump()
                cache = CheckpointCache((cache_root or output_dir / ".cache") / "quality_repairs", reuse=options.resume)
                key = slide_cache_key(plan, slide_context, layouts_spec, client, 0)
                cached = cache.get(key)
                if cached is not None:
                    from contracts.ir2_content_schema import SlideSpec
                    candidate = SlideSpec.model_validate(cached)
                    validate_slide_spec(candidate, layouts_spec, allowed_unit_ids=set(plan.source_unit_ids),
                                        assets=slide_context["assets"], source_item_ids=slide_context["source_item_ids"], asset_source_items=slide_context.get("asset_source_items", []))
                    validate_slide_grounding(candidate, slide_context)
                    return slide_number, candidate
                async with semaphore:
                    check(context)
                    candidate = await compose_single_slide(
                        plan,
                        slide_context,
                        layouts_spec,
                        client,
                        max_repairs=0,
                        current_slide=ir2.slides[slide_number - 1],
                        job_context=context,
                    )
                    cache.put(key, candidate.model_dump(mode="json"))
                    return slide_number, candidate

            results = await asyncio.gather(
                *(repair(slide_number, feedback) for slide_number, feedback in feedback_by_slide.items()),
                return_exceptions=True,
            )
            errors = [result for result in results if isinstance(result, BaseException)]
            if errors:
                cancellation = next((error for error in errors if isinstance(error, asyncio.CancelledError)), None)
                if cancellation is not None:
                    raise cancellation
                provider_error = next((error for error in errors if isinstance(error, LLMRequestError)), None)
                if provider_error is not None:
                    raise provider_error
                raise ValueError("Scoped visual repair failed: " + " | ".join(str(error) for error in errors))
            for slide_number, repaired_slide in results:
                repaired[slide_number - 1] = repaired_slide
            return TargetIR2Presentation(output_filename="op_ppt.pptx", slides=repaired)

        report(context, "composition")
        repaired_ir2 = asyncio.run(repair_flagged_slides())
        report(context, "build")
        pending_pptx = output_dir / "op_ppt.repaired.pptx"
        builder.build(repaired_ir2.model_dump(exclude_none=True), str(pending_pptx))
        report(context, "quality checks")
        final_report = assess_final_artifact(pending_pptx, output_dir / "quality_attempts" / artifact_hash(pending_pptx),
                                            ir1=ir1, ir2=repaired_ir2, caller=client,
                                            judge_enabled=options.polish != "off", deep_verification=options.deep_verification)
        check(context)
        ir2, candidate_path = repaired_ir2, pending_pptx
        if final_report.rendered.status == "FAILED_TO_RUN":
            raise ValueError("Repaired artifact could not be rendered; previous artifact retained: " + str(final_report.rendered.reason))
    check(context)
    if final_report.readiness == "BLOCKED":
        update_manifest(manifest_path, status="FAILED", quality_status=final_report.status,
                        readiness=final_report.readiness, rejected_artifact_hash=final_report.artifact_hash)
        # Diagnostic attempts stay separate from a previous valid revision's report.
        if not pptx_path.exists():
            write_quality_report(final_report, output_dir)
        raise ValueError("Final PPTX quality gate failed: " + " | ".join(final_report.hard_failures))
    atomic_json(output_dir / "scene_graph.json", builder.last_scene.model_dump(mode="json"))
    update_manifest(manifest_path, renderer=builder.last_result.metadata(),
                    assessed_scene_hash=sha256_value(portable_value(builder.last_scene.model_dump(mode="json"))))
    write_ir2(ir2, output_dir)
    _record_stage(manifest_path, "ir2", input_hash=composition_hash, output=ir2_path)
    os.replace(candidate_path, pptx_path)
    write_quality_report(final_report, output_dir)
    (output_dir / "vision_audit_report.json").write_text(final_report.judge.model_dump_json(indent=2), encoding="utf-8")
    from domain.evaluation.claim_verification import build_verification_report
    atomic_json(output_dir / "verification_report.json", build_verification_report(ir1, ir2, profile="deep" if options.deep_verification else "basic"))
    _record_stage(manifest_path, "pptx", input_hash=sha256_value(ir2.model_dump()), output=pptx_path)
    usage = getattr(client, "usage", None)
    update_manifest(
        manifest_path,
        usage=usage.as_dict() if usage is not None else {"call_count": None, "reason": "external caller"},
        status=final_report.readiness,
        quality_status=final_report.status,
        artifact_hash=final_report.artifact_hash,
        revision_id=final_report.revision_id,
        readiness=final_report.readiness,
        final_pptx=str(pptx_path),
        assessed_ir2_hash=sha256_value(portable_value(ir2.model_dump(exclude_none=True))),
        assessed_ir1_hash=sha256_value(portable_value(ir1.model_dump(exclude_none=True))),
        model=model_name,
        vision_status=final_report.judge.status,
        vision_reason=final_report.judge.reason,
        grounding={"version": "r03-v1", "ir1_completeness": ir1.completeness,
                   "deep_verification": options.deep_verification,
                   "visible_claims": sum(len(slide.grounding) for slide in ir2.slides),
                   "unknown_semantic_claims": sum(row.semantic_support == "UNKNOWN" for slide in ir2.slides for row in slide.grounding.values()),
                   "status": "VERIFIED" if all(row.status == "VERIFIED" for slide in ir2.slides for row in slide.grounding.values()) and any(slide.grounding for slide in ir2.slides) else "BASIC_CHECKED"},
    )
    return pptx_path
