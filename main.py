import argparse
import sys
from datetime import datetime
from pathlib import Path
from config.settings import resolve_environment, get_multi_agent_settings, get_provider_model
from core.llm_client import LLMClient
from pipeline.orchestrator import MultiAgentOptions
from pipeline.slide_editor import import_legacy_revision
from pipeline.service import generate_deck, generate_deck_from_sources, edit_slide
from schemas.ingestion_schema import ParseOptions, IngestionError
import json
from renderers.factory import validate_renderer_runtime

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description="End-to-End Document to PPTX Generator Engine")
    parser.add_argument("--input", "-i", type=str, action="append", help="Path to source document; repeat for multiple sources (required for generation)")
    parser.add_argument('--input-type', action='append', choices=['auto','pdf','docx','txt','markdown','csv','xlsx','png','jpeg'], help='Repeat once per input, in the same order; omitted means Auto for all')
    parser.add_argument('--parse-options-file', help='JSON list of ParseOptions, one per input')
    parser.add_argument("--layouts", "-l", type=str, default=str(ROOT / "config" / "ppt_default_layouts.json"), help="Path to layout catalog")
    parser.add_argument("--output-dir", "-o", type=str, default="output", help="Output directory")
    parser.add_argument("--pipeline", choices=["multi-agent"], default="multi-agent",
                        help="Supported generation path (default: multi-agent); retained for existing commands")
    parser.add_argument("--renderer", choices=["python", "pptxgenjs"],
                        help="Explicit renderer backend; generation defaults to python and edits retain their revision backend")
    parser.add_argument("--llm-provider", choices=["openrouter", "gemini"], help="Multi-agent provider; otherwise LLM_PROVIDER (default openrouter)")
    parser.add_argument("--llm-model", help="Multi-agent model; otherwise the configured provider model")
    parser.add_argument("--llm-max-output-tokens", type=int, help="Provider output ceiling; each task uses its own smaller budget")
    parser.add_argument("--llm-context-tokens", type=int, help="Declared provider context capacity, when verified")
    parser.add_argument('--context-policy', choices=['progressive', 'legacy'])
    parser.add_argument('--context-count-mode', choices=['auto', 'estimate', 'provider_required'])
    parser.add_argument('--unknown-context-tokens', type=int, help='Explicit capacity for an undeclared model')
    parser.add_argument("--ir1-batch-char-budget", type=int, help="Conservative source-text budget per extraction batch")
    parser.add_argument("--ir1-output-tokens", type=int, help="Extraction output reserve, capped by --llm-max-output-tokens")
    parser.add_argument("--extraction-mode", choices=["llm", "source-passages"], default="llm",
                        help="IR1 ingestion: model extraction or exact source passages/cells; both use mandatory grounding checks")
    parser.add_argument("--llm-max-attempts", type=int, help="Total transport attempts per call (default 3)")
    parser.add_argument("--llm-deadline-seconds", type=int, help="Per-call deadline including quota waits and retries (default 120)")
    parser.add_argument("--eval-llm-provider", choices=["openrouter", "gemini"], help="Evaluator provider; otherwise inherits generation configuration")
    parser.add_argument("--eval-llm-model", help="Evaluator model override")
    parser.add_argument("--lens", choices=["executive", "technical", "pitch", "academic"], default="executive",
                        help="Narrative lens used by the multi-agent storyboard")
    parser.add_argument("--slides-min", type=int, default=5, help="Minimum slides for multi-agent storyboarding")
    parser.add_argument("--slides-max", type=int, default=10, help="Maximum slides for multi-agent storyboarding")
    parser.add_argument("--resume", action="store_true", help="Reuse matching validated multi-agent stage artifacts")
    parser.add_argument("--max-section-retries", type=int, default=1, help="Bounded retry count for failed source sections")
    parser.add_argument("--deep-verification", action="store_true", help="Optional evidence-scoped semantic judging; basic citation/numeric checks always run")
    parser.add_argument('--asset-mode', choices=['legacy','structured'], default='structured',
                        help="structured (default) enriches and LLM-interprets every usable asset; legacy keeps raw-v3 assets only")
    parser.add_argument('--asset-understanding', choices=['auto','off'], default='auto')
    parser.add_argument('--describe-assets', action='store_true')
    parser.add_argument('--description-asset-id', action='append', default=[])
    parser.add_argument('--formula-dpi', type=int, default=200)
    parser.add_argument('--asset-min-ppi', type=float, default=150)
    parser.add_argument("--semantic-batch-size", type=int, default=8, help="Units per optional semantic evidence batch")
    parser.add_argument("--max-repairs-per-slide", type=int, default=1, help="Bounded IR2 repair count per invalid slide")
    parser.add_argument("--max-concurrency", type=int, default=2, help="Maximum concurrent multi-agent slide requests")
    parser.add_argument("--theme", default="auto",
                        help="Deck theme: auto (resolve from lens) or an id from config/themes (academic_slate, corporate_blue, warm_editorial, dark_tech, minimal_mono)")
    parser.add_argument("--dynamic-layout", dest="dynamic_layout", action="store_true", default=True,
                        help="Measure content and re-solve per-slide geometry dynamically (default)")
    parser.add_argument("--no-dynamic-layout", dest="dynamic_layout", action="store_false",
                        help="Use the fixed layout catalog geometry only")
    parser.add_argument("--polish", choices=["off", "auto", "all"], default="off",
                        help="Optional deterministic plus rendered-slide quality audit for multi-agent decks")
    parser.add_argument("--gpu", action="store_true", help="Use CUDA for Docling only when PyTorch/CUDA are configured")
    parser.add_argument("--edit-slide", type=int, help="Edit one existing slide from a completed multi-agent run")
    parser.add_argument("--instruction", "--prompt", dest="instruction", default="", help="Natural-language instruction for generation or --edit-slide")
    parser.add_argument("--base-revision", help="Required active.json revision ID for --edit-slide; stale edits are rejected")
    parser.add_argument("--import-legacy-run", action="store_true", help="Explicitly validate/rebuild an existing multi-agent run into immutable revisions; preserves originals")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate the generated PPTX after compilation")
    parser.add_argument("--eval-config", default="evalute/config.yaml", help="Evaluator YAML configuration")
    parser.add_argument("--eval-tool-name", default="btps5", help="Tool name recorded in the evaluation report")
    parser.add_argument("--eval-run-id", help="Evaluation run ID; defaults to a timestamped source name")
    parser.add_argument("--eval-out", help="Root directory for evaluation artifacts; defaults to <output-dir>/evaluation")
    parser.add_argument("--eval-no-ai-judging", action="store_true", help="Disable LLM claim fact-checking")
    parser.add_argument("--strict-section-coverage", dest="strict_section_coverage", action="store_true", default=None,
                        help="Require complete section/numeric coverage (error if incomplete)")
    parser.add_argument("--no-strict-section-coverage", dest="strict_section_coverage", action="store_false",
                        help="Allow generation to proceed with accepted units even if some sections are incomplete")
    args = parser.parse_args()
    overrides = {}
    for value, name in ((args.llm_provider, "LLM_PROVIDER"), (args.llm_max_output_tokens, "LLM_MAX_OUTPUT_TOKENS"),
                        (args.llm_context_tokens, "LLM_CONTEXT_TOKENS"), (args.ir1_batch_char_budget, "IR1_BATCH_INPUT_CHAR_BUDGET"),
                        (args.context_policy, 'LLM_CONTEXT_POLICY'), (args.context_count_mode, 'LLM_CONTEXT_COUNT_MODE'),
                        (args.unknown_context_tokens, 'LLM_UNKNOWN_CONTEXT_TOKENS'),
                        (args.ir1_output_tokens, "LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS"),
                        (args.llm_max_attempts, "LLM_MAX_ATTEMPTS"), (args.llm_deadline_seconds, "LLM_DEADLINE_SECONDS"),
                        (args.eval_llm_provider, "EVAL_LLM_PROVIDER"), (args.eval_llm_model, "EVAL_LLM_MODEL")):
        if value is not None:
            if isinstance(value, int) and value < 1:
                parser.error(f"{name} must be positive")
            overrides[name] = str(value)
    if args.strict_section_coverage is not None:
        overrides["STRICT_SECTION_COVERAGE"] = "true" if args.strict_section_coverage else "false"
    environment = resolve_environment(ROOT / ".env", overrides)
    if args.llm_model:
        provider = environment.get("LLM_PROVIDER", "openrouter").strip().lower()
        environment["OPENROUTER_MODEL" if provider == "openrouter" else "GEMINI_MODEL"] = args.llm_model
    settings = get_multi_agent_settings(environment)
    api_key = environment.get("OPENROUTER_API_KEY" if settings.provider == "openrouter" else "GEMINI_API_KEY", "")

    if args.import_legacy_run:
        validate_renderer_runtime(args.renderer or "python")
        result = import_legacy_revision(output_dir=args.output_dir, layouts_path=args.layouts, renderer=args.renderer or "python",
                                        caller=LLMClient(settings=settings, api_key=api_key))
        print(f"[DONE] Imported legacy artifacts at '{result}'.")
        return

    if args.edit_slide is not None:
        if not args.instruction.strip():
            parser.error("--instruction is required with --edit-slide")
        if not args.base_revision:
            parser.error("--base-revision is required with --edit-slide (read <output-dir>/active.json)")
        updated = edit_slide(
            output_dir=args.output_dir,
            layouts_path=args.layouts,
            slide_index=args.edit_slide,
            instruction=args.instruction,
            base_revision=args.base_revision,
            max_repairs=args.max_repairs_per_slide,
            renderer=args.renderer,
            settings=settings, api_key=api_key,
        )
        print(f"[DONE] Updated slide {args.edit_slide} at '{updated}'.")
        return

    if not args.input:
        parser.error("--input is required for generation")
    for source in args.input:
        if not Path(source).is_file():
            parser.error(f'Input document does not exist: {source}')
    if args.input_type is not None and len(args.input_type) != len(args.input):
        parser.error('--input-type must appear once per --input')
    input_types = args.input_type or ['auto'] * len(args.input)
    try:
        parse_options = json.loads(Path(args.parse_options_file).read_text(encoding='utf-8')) if args.parse_options_file else [{} for _ in args.input]
        if not isinstance(parse_options, list) or len(parse_options) != len(args.input):
            raise ValueError('parse options must be a list with one entry per input')
        parse_options = [ParseOptions.model_validate(item).model_dump(mode='json') for item in parse_options]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.slides_min < 1 or args.slides_max < args.slides_min or args.max_concurrency < 1 or args.semantic_batch_size < 1:
        parser.error("Slide bounds and concurrency/batch size must be positive; min must not exceed max")
    if args.max_section_retries < 0 or args.max_repairs_per_slide < 0:
        parser.error("Repair/retry counts must be non-negative")
    from config.service_settings import get_service_settings
    limits = get_service_settings(environment)
    if limits.max_source_files and len(args.input) > limits.max_source_files:
        parser.error('Configured maximum source file count exceeded')
    if limits.max_source_bytes and sum(Path(p).stat().st_size for p in args.input) > limits.max_source_bytes:
        parser.error('Configured aggregate source byte limit exceeded')
    if any(Path(p).stat().st_size > limits.upload_limit_bytes for p in args.input):
        parser.error('A source exceeds the configured upload byte limit')
    parsed_paths = []
    if len(args.input) == 1:
        operation, source_argument = generate_deck, args.input[0]
        ingestion_args = {'selected_type': input_types[0], 'parse_options': parse_options[0]} if args.input_type or args.parse_options_file else {}
    else:
        from core.artifacts import file_hash
        unique = {}
        from pipeline.ingestion.detection import detect
        for source, kind, opts in zip(args.input, input_types, parse_options):
            try:
                detection = detect(source, selected_type=kind, encoding=opts['encoding'])
                kind = detection['resolved_type']
                opts = ParseOptions.model_validate(opts).for_type(kind).model_dump(mode='json')
                if detection['text_encoding']:
                    opts['encoding'] = detection['text_encoding']
            except (IngestionError, ValueError) as error:
                parser.error(str(error))
            digest = file_hash(source)
            if digest in unique:
                prior = unique[digest]
                if (prior['selected_type'], prior['parse_options']) != (kind, opts):
                    parser.error('Identical source bytes have conflicting parse options')
                prior['aliases'].append(Path(source).name)
                continue
            unique[digest] = {'source_path': source, 'source_sha256': digest, 'selected_type': kind,
                             'parse_options': opts, 'aliases': [Path(source).name]}
        operation, source_argument = generate_deck_from_sources, list(unique.values())
        ingestion_args = {'parse_resume': args.resume}
    ingestion_args['limits'] = limits
    pptx_out_path = operation(
        source_argument, args.output_dir,
        MultiAgentOptions(
            asset_options={'mode':args.asset_mode, 'semantic_understanding':args.asset_understanding,
                'describe_assets':args.describe_assets, 'description_asset_ids':args.description_asset_id,
                'formula_dpi':args.formula_dpi, 'min_ppi':args.asset_min_ppi},
            layouts_path=args.layouts,
            output_dir=args.output_dir,
            lens=args.lens,
            instruction=args.instruction,
            min_slides=args.slides_min,
            max_slides=args.slides_max,
            resume=args.resume,
            max_section_retries=args.max_section_retries,
            max_repairs_per_slide=args.max_repairs_per_slide,
            max_concurrency=args.max_concurrency,
            polish=args.polish,
            deep_verification=args.deep_verification,
            semantic_batch_size=args.semantic_batch_size,
            renderer=args.renderer or "python",
            extraction_mode=args.extraction_mode,
            use_gpu=args.gpu,
            theme=args.theme,
            dynamic_layout=args.dynamic_layout,
        ),
        settings=settings, api_key=api_key, on_parsed=parsed_paths.append, **ingestion_args,
    )
    print(f"[DONE] Revision {pptx_out_path.parent.name}: '{pptx_out_path}'.")

    if args.evaluate:
        try:
            from evalute.config import load
            from evalute.reference.build_reference import build
            from evalute.runner import evaluate_presentation

            run_id = args.eval_run_id or f"{Path(args.input[0]).stem}_{datetime.now():%Y%m%d_%H%M%S}"
            eval_root = Path(args.eval_out or Path(args.output_dir) / "evaluation")
            reference_path = eval_root / "reference.json"
            print("\n=== STEP 6: EVALUATING GENERATED PPTX ===")
            artifacts = pptx_out_path.parent
            build(str(parsed_paths[0]), str(artifacts / "content_analysis.json"), reference_path)
            eval_config = load(args.eval_config)
            judge_provider = args.eval_llm_provider or eval_config["faithfulness"].get("judge_provider") or settings.evaluator_provider
            judge_model = args.eval_llm_model or eval_config["faithfulness"].get("judge_model") or (
                settings.evaluator_model if judge_provider == settings.evaluator_provider else get_provider_model(judge_provider, environment))
            eval_config["faithfulness"].update(judge_provider=judge_provider, judge_model=judge_model)
            report = evaluate_presentation(reference_path, str(pptx_out_path), args.eval_tool_name, run_id,
                                           eval_root / run_id, eval_config, not args.eval_no_ai_judging,
                                           judge_caller=LLMClient.for_evaluation(settings=settings, provider=judge_provider, model=judge_model,
                                               api_key=environment.get("OPENROUTER_API_KEY" if judge_provider == "openrouter" else "GEMINI_API_KEY", "")))
            from core.artifacts import update_manifest
            update_manifest(Path(args.output_dir) / "run_manifest.json", evaluation={
                "report": str(eval_root / run_id / "report.json"),
                "faithfulness": report["metrics"]["faithfulness"],
            })
            overall = report["metrics"]["automated_overall"]
            if overall is None:
                print("[DONE] Evaluation report written; overall score is unavailable because required checks are incomplete.")
            else:
                print(f"[DONE] Evaluation score: {overall:.3f}")
        except Exception as exc:
            print(f"[WARN] PPT generated successfully, but evaluation failed: {exc}")

if __name__ == "__main__":
    main()
