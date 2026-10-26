"""Supported CLI routing after retirement of the one-shot legacy generator."""
import sys

import pytest

import main


def test_removed_legacy_pipeline_rejected_before_parsing_or_generation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy selection must fail before work starts")

    monkeypatch.setattr(main, "generate_deck", forbidden)
    monkeypatch.setattr(sys, "argv", ["main.py", "--pipeline", "legacy"])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 2


@pytest.mark.parametrize("existing,cli,expected", [(None, None, "file-model"), ("env-model", None, "env-model"), ("env-model", "cli-model", "cli-model")])
def test_cli_loads_repository_env_without_overriding_explicit_settings(tmp_path, monkeypatch, existing, cli, expected):
    import os
    for key in ("LLM_PROVIDER", "IR1_BATCH_INPUT_CHAR_BUDGET", "LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS", "LLM_CONTEXT_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text("OPENROUTER_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    if existing is None:
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_MODEL", existing)
    calls = {}
    monkeypatch.setattr(main, "edit_slide", lambda **kwargs: calls.update(kwargs) or tmp_path / "deck.pptx")
    before = dict(os.environ)
    args = ["main.py", "--edit-slide", "1", "--instruction", "Shorten title", "--base-revision", "base", "--llm-provider", "openrouter"]
    if cli:
        args.extend(["--llm-model", cli])
    args.extend(["--ir1-batch-char-budget", "8000", "--ir1-output-tokens", "8192", "--llm-context-tokens", "1048576"])
    monkeypatch.setattr(sys, "argv", args)
    main.main()
    assert dict(os.environ) == before
    assert calls["settings"].model == expected
    assert calls["settings"].ir1_batch_input_char_budget == 8000
    assert calls["settings"].stage_output_tokens["LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS"] == 8192
    assert calls["settings"].capabilities.context_tokens == 1048576


def test_missing_input_rejected_before_parsing(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 2


@pytest.mark.parametrize("version,node", [("NOT_INSTALLED", "node"), ("3.12.0", None)])
def test_missing_renderer_dependencies_fail_before_llm_construction(tmp_path, monkeypatch, version, node):
    from renderers import factory
    from pipeline import orchestrator
    import shutil

    monkeypatch.setattr(factory, "renderer_fingerprint", lambda backend: {"version": version})
    monkeypatch.setattr(shutil, "which", lambda command: node)
    def forbidden():
        raise AssertionError("Missing renderer must fail before LLM construction")
    monkeypatch.setattr(orchestrator, "LLMClient", forbidden)
    options = orchestrator.MultiAgentOptions(layouts_path="unused.json", output_dir=str(tmp_path), renderer="pptxgenjs")
    with pytest.raises(RuntimeError):
        orchestrator.run_multi_agent_pipeline(tmp_path / "unused.json", options)


@pytest.mark.parametrize("overall", [0.75, None])
def test_default_cli_evaluation_uses_active_revision_projection(tmp_path, monkeypatch, capsys, overall):
    from pipeline import service
    from evalute import config, runner
    from evaluation.reference import build_reference
    from core import artifacts

    run = tmp_path / "run"
    structural = run / "ir.json"
    revision = run / "revisions" / "current-revision"
    pptx = revision / "op_ppt.pptx"
    calls = {}
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source fixture")

    def parse(source, output, **kwargs):
        calls["parse"] = (source, output, kwargs)
        return structural

    def generate(path, options, **kwargs):
        assert path == structural
        assert options.renderer == "pptxgenjs"
        assert options.extraction_mode == "source-passages"
        return pptx

    def reference(ir, ir1, output):
        calls["reference"] = (ir, ir1, output)

    def evaluate(reference, deck, tool, run_id, output, settings, ai_judging, **kwargs):
        calls["evaluate"] = (reference, deck, settings, ai_judging)
        return {"metrics": {"automated_overall": overall, "faithfulness": {"status": "NOT_EVALUATED"}}}

    monkeypatch.setattr(service, "parse_document_cached", parse)
    monkeypatch.setattr(service, "verify_structural_ir", lambda path: path == str(structural))
    monkeypatch.setattr(service, "run_multi_agent_pipeline", generate)
    monkeypatch.setattr(build_reference, "build", reference)
    monkeypatch.setattr(config, "load", lambda path: {"faithfulness": {}})
    monkeypatch.setattr(runner, "evaluate_presentation", evaluate)
    monkeypatch.setattr(artifacts, "update_manifest", lambda path, **values: calls.update(manifest=(path, values)))
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(source), "--output-dir", str(run),
                        "--renderer", "pptxgenjs", "--extraction-mode", "source-passages", "--evaluate", "--eval-no-ai-judging", "--eval-run-id", "cleanup"])
    main.main()
    assert calls["reference"][:2] == (str(structural), str(revision / "content_analysis.json"))
    assert calls["evaluate"][1] == str(pptx)
    assert calls["evaluate"][3] is False
    assert calls["manifest"][0] == run / "run_manifest.json"
    assert calls["manifest"][1]["evaluation"]["report"] == str(run / "evaluation" / "cleanup" / "report.json")
    output = capsys.readouterr().out
    assert "evaluation failed" not in output
    assert ("overall score is unavailable" in output) == (overall is None)


@pytest.mark.parametrize("flag", ["--instruction", "--prompt"])
def test_cli_generation_passes_instruction_to_options(tmp_path, monkeypatch, flag):
    from pipeline import service
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source fixture")
    captured = {}

    def generate(path, options, **kwargs):
        captured["instruction"] = options.instruction
        return tmp_path / "rev" / "deck.pptx"

    monkeypatch.setattr(service, "parse_document_cached", lambda *args, **kwargs: tmp_path / "ir.json")
    monkeypatch.setattr(service, "verify_structural_ir", lambda path: True)
    monkeypatch.setattr(service, "run_multi_agent_pipeline", generate)
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(source), "--output-dir", str(tmp_path), flag, "Custom deck instruction"])
    main.main()
    assert captured["instruction"] == "Custom deck instruction"

