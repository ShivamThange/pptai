#!/bin/bash
# Run from the root of the pptai repository

# 1. Create new architectural boundaries
mkdir -p application/pipeline application/services application/jobs
mkdir -p domain/extraction domain/composition domain/rendering domain/evaluation
mkdir -p infrastructure/llm infrastructure/persistence infrastructure/ingestion infrastructure/utils
mkdir -p interfaces/api interfaces/cli interfaces/workers
mkdir -p contracts

# 2. Move Infrastructure (External Integrations & I/O)
mv core/llm_client.py core/llm_run.py core/context_budget.py core/schema_adapter.py infrastructure/llm/
mv core/jobs.py core/revisions.py infrastructure/persistence/
mv core/artifacts.py infrastructure/utils/

# 3. Move Domain (Pure Business Logic)
mv core/theme_engine.py core/layout_engine.py core/text_metrics.py core/formula_renderer.py core/chart_content.py domain/rendering/
mv core/context_selection.py core/asset_registry.py domain/extraction/
mv core/quality_metadata.py tools/claim_verification.py tools/asset_inspection.py tools/asset_description.py tools/chart_binding.py domain/evaluation/

# 4. Move Application (Orchestrators & Services)
mv pipeline/orchestrator.py application/pipeline/
mv pipeline/service.py application/services/deck_service.py
mv core/job_context.py core/builder.py application/jobs/

# 5. Move Interfaces (Entry Points)
mv api/* interfaces/api/
mv main.py interfaces/cli/
mv workers/* interfaces/workers/

# 6. Move Contracts (Schemas)
mv schemas/* contracts/
rm -r schemas

# 7. Fix Typo & Clean up
mv evalute evaluation
rm -r core tools pipeline
