"""Rewrite legacy module paths to the new DDD layout (Phase 1, Step 1.2).

Applied to every .py file in the repo except vendored dirs. The rewritten
files live in the new top-level packages; the old directories are removed
afterwards by migrate_arch.sh / cleanup.
"""
import os
import re

REPLACEMENTS = [
    # --- Infrastructure: LLM ---
    (r"from core\.llm_client", "from infrastructure.llm.llm_client"),
    (r"from core\.llm_run", "from infrastructure.llm.llm_run"),
    (r"from core\.context_budget", "from infrastructure.llm.context_budget"),
    (r"from core\.schema_adapter", "from infrastructure.llm.schema_adapter"),
    # --- Infrastructure: persistence ---
    (r"from core\.jobs", "from infrastructure.persistence.jobs"),
    (r"from core\.revisions", "from infrastructure.persistence.revisions"),
    # --- Infrastructure: utils ---
    (r"from core\.artifacts", "from infrastructure.utils.artifacts"),
    (r"from core\.service_artifacts", "from infrastructure.utils.service_artifacts"),
    # --- Domain: rendering ---
    (r"from core\.layout_engine", "from domain.rendering.layout_engine"),
    (r"from core\.theme_engine", "from domain.rendering.theme_engine"),
    (r"from core\.text_metrics", "from domain.rendering.text_metrics"),
    (r"from core\.formula_renderer", "from domain.rendering.formula_renderer"),
    (r"from core\.chart_content", "from domain.rendering.chart_content"),
    # --- Domain: extraction ---
    (r"from core\.context_selection", "from domain.extraction.context_selection"),
    (r"from core\.asset_registry", "from domain.extraction.asset_registry"),
    # --- Domain: evaluation ---
    (r"from core\.quality_metadata", "from domain.evaluation.quality_metadata"),
    (r"from tools\.claim_verification", "from domain.evaluation.claim_verification"),
    (r"from tools\.asset_inspection", "from domain.evaluation.asset_inspection"),
    (r"from tools\.asset_description", "from domain.evaluation.asset_description"),
    (r"from tools\.chart_binding", "from domain.evaluation.chart_binding"),
    (r"from pipeline\.coverage_ledger", "from infrastructure.ingestion.coverage_ledger"),
    # --- Application ---
    (r"from pipeline\.orchestrator", "from application.pipeline.orchestrator"),
    (r"from pipeline\.service", "from application.services.deck_service"),
    (r"from pipeline\.slide_editor", "from application.services.slide_editor"),
    (r"from core\.job_context", "from application.jobs.job_context"),
    (r"from core\.builder", "from application.jobs.builder"),
    # --- Infrastructure: ingestion (moved pipeline stages & helpers) ---
    (r"from pipeline\.ingestion\.adapters\.", "from infrastructure.ingestion.adapters."),
    (r"from pipeline\.ingestion\.", "from infrastructure.ingestion."),
    (r"from pipeline\.chunker", "from infrastructure.ingestion.chunker"),
    (r"from pipeline\.context_fragments", "from infrastructure.ingestion.context_fragments"),
    (r"from pipeline\.deduplicator", "from infrastructure.ingestion.deduplicator"),
    (r"from pipeline\.knowledge_extractor", "from infrastructure.ingestion.knowledge_extractor"),
    (r"from pipeline\.quality_controller", "from infrastructure.ingestion.quality_controller"),
    (r"from pipeline\.asset_interpreter", "from infrastructure.ingestion.asset_interpreter"),
    (r"from pipeline\.slide_composer", "from infrastructure.ingestion.slide_composer"),
    (r"from pipeline\.slide_renderer", "from infrastructure.ingestion.slide_renderer"),
    (r"from pipeline\.source_adapter", "from infrastructure.ingestion.source_adapter"),
    (r"from pipeline\.stage1_docling_parser", "from infrastructure.ingestion.stage1_docling_parser"),
    (r"from pipeline\.stage2_quality_gate", "from infrastructure.ingestion.stage2_quality_gate"),
    (r"from pipeline\.storyboard_planner", "from infrastructure.ingestion.storyboard_planner"),
    (r"from pipeline\.visual_placement", "from infrastructure.ingestion.visual_placement"),
    (r"from pipeline\.visual_reviewer", "from infrastructure.ingestion.visual_reviewer"),
    # --- Contracts (schemas renamed) ---
    (r"from schemas\.", "from contracts."),
    (r"import schemas\.", "import contracts."),
    # --- Typo fix: evalute -> evaluation ---
    (r"from evalute\.", "from evaluation."),
    (r"import evalute\.", "import evaluation."),
]

SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", "frontend"}

changed = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
    for name in sorted(files):
        if not name.endswith(".py"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        new = content
        for old, repl in REPLACEMENTS:
            new = re.sub(old, repl, new)
        if new != content:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
            changed.append(path)

print(f"Updated imports in {len(changed)} files")
for p in changed:
    print(" ", p)
