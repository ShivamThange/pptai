# PPTAI modular implementation package

This is the feature-by-feature rewrite of the preserved implementation plan, cross-checked against the user’s complete workflow and both newly added reference PPTs. **One module has one single implementation document.** A feature module is not automatically a separate AI model.

## Start here

- [Shared project and agent context](PROJECT_CONTEXT.md)
- [Current implementation state and audit evidence](CURRENT_STATE.md)
- [Repository cleanup, retained tools, and remaining work](REPOSITORY_CLEANUP.md)
- [Branch decision and selective integration](BRANCH_STRATEGY.md)
- [Every workflow point cross-checked](WORKFLOW_CROSSCHECK.md)
- [Confirmed decisions and pending questions](DECISIONS.md)
- [Module status / dependencies](MODULE_STATUS.md)
- [Implementation roadmap](ROADMAP.md)
- [Preserved original base plan](BASE_PLAN.md)
- [References and source authority](REFERENCES_AND_EVIDENCE.md)

Continue from **multi-agent**. Port the useful PptxGenJS renderer/reference ideas through adapters; retain inherited evaluator scaffolding and repair it in place. The latest hardik branch head is e534ff1, with renderer code unchanged from f9a50e4.

The user confirmed source-backed suggestions with labeled gaps, basic checks on every run, optional deep verification, first-release PDF/DOCX/TXT/Markdown/CSV/XLSX/PNG/JPEG, and chat plus layout/content editing. Exact main-content count is preserved with extras separate; native flowcharts/architecture graphs and a Windows-first portable API are confirmed. The six metrics have detailed mathematical definitions in F19. LLM/provider selection remains open and the roadmap uses dependency phases without calendar estimates. See DECISIONS for outstanding scope choices.

## Single-document module index

| Module | Implementation document | Type |
|---|---|---|
| [R01](modules/R01_llm_gateway_reliability.md) | LLM gateway and provider failure repair | Repair |
| [R02](modules/R02_provenance_and_assets_repair.md) | Existing provenance, captions, and asset binding repair | Repair |
| [R03](modules/R03_grounding_validation_repair.md) | Numeric and claim grounding repair | Repair |
| [R04](modules/R04_quality_gate_repair.md) | Geometry and final-artifact quality gate repair | Repair |
| [R05](modules/R05_cache_resume_revision_repair.md) | Cache, resume, and atomic revision repair | Repair |
| [R06](modules/R06_renderer_branch_integration.md) | PptxGenJS branch adaptation and renderer parity | Repair / integration |
| [F01](modules/F01_api_jobs_and_service.md) | Shared API, jobs, and progress service | Feature |
| [F02](modules/F02_uploads_and_docling_routing.md) | Uploads, file-type dropdown, and Docling routing | Feature |
| [F03](modules/F03_prompt_enhancement_and_audience.md) | User prompt, enhancement, and audience mode | Feature |
| [F04](modules/F04_multimodal_asset_content.md) | Images, tables, charts, formulas, and asset content | Feature |
| [F05](modules/F05_ir1_source_knowledge.md) | Canonical IR1 with actual document references | Feature |
| [F06](modules/F06_optional_deep_source_verification.md) | Optional deep source verification | Feature |
| [F07](modules/F07_context_budget_progressive_chunking.md) | Context budgets, complete coverage, and progressive chunking | Feature / repair |
| [F08](modules/F08_deduplication.md) | Evidence-preserving deduplicator | Feature |
| [F09](modules/F09_structured_retrieval.md) | Structured IR1 retrieval and usage references | Feature |
| [F10](modules/F10_dynamic_narrative.md) | Dynamic deck flow and IR1-to-IR2 skeleton | Feature |
| [F11](modules/F11_ir2_content_and_suggestions.md) | IR2 visible content and editing reserve | Feature |
| [F12](modules/F12_hybrid_agents_and_tools.md) | Hybrid agent roles, tools, and scoped retry | Feature |
| [F13](modules/F13_dynamic_geometry_and_layout.md) | Dynamic geometry, sizing, and slide layouts | Feature |
| [F14](modules/F14_native_diagrams.md) | Mermaid graph to editable PowerPoint diagrams | Feature |
| [F15](modules/F15_draft_and_human_review.md) | Draft PPT, suggestions, and human review UI | Feature |
| [F16](modules/F16_prompt_edits_and_layout_changes.md) | Prompt editing, scoped regeneration, and layout changes | Feature |
| [F17](modules/F17_chat_and_version_history.md) | Chat-like interaction and V1/V2 history | Feature |
| [F18](modules/F18_pptx_pdf_export.md) | PPTX and PDF export | Feature |
| [F19](modules/F19_evaluation_and_academic_study.md) | Six core evaluation metrics and academic study | Feature / repair |
| [F20](modules/F20_cross_document_conflicts.md) | Cross-document conflict detection (deferred) | Feature |

## Completion meaning

The initial restructuring added documentation and an agent entry point. R01, R02, R03, R04, R05 and R06 have since been implemented and verified within their gateway, provenance/asset-binding, grounding-repair, final-artifact quality-gate and current CLI cache/resume/revision and shared renderer/native parity scopes; see CURRENT_STATE and MODULE_STATUS for exact evidence and unrun checks. R03 does not claim a successful final live LLM deck: the final live attempt correctly blocked unsupported claims, while source-fixture native rendering passed. R04 includes real PowerPoint repair/rerender checks; the final optional live vision recheck is billing-limited and correctly incomplete. R05 has 201 passing tests and real Docling/PowerPoint COM checkpoint/edit/resume evidence; its native generation is a fixture and readiness BASIC_CHECKED. R06 has 242 passing tests and real PowerPoint table/parity/native-edit evidence on both adapters; JS generation/edit/resume also passes. F01 now implements the shared synchronous service, local SQLite queue, sequential worker, FastAPI uploads/jobs/SSE/cancellation and published artifact routes. It has 299 passing tests and real uploaded-PDF Docling/PowerPoint generation/edit/download/resume evidence on both backends; native model answers are typed fixtures and readiness BASIC_CHECKED. F02 now implements the eight Q05 structural formats, validated multi-file intake/dropdown, raw-v3 collections, staged caching and shared API/CLI/intake page. It has 362 passing tests, 13 DOM checks and real mixed-source native-table generation/edit/download/resume evidence on both backends; model answers are fixtures and readiness BASIC_CHECKED. F07 now implements prepared-request admission, explicit capacities, progressive source/topic projections, context accounting, bounded stage calls and checkpoint/revision integration. It has 404 passing tests, 42 focused F07 cases and real mixed-source native generation/edit/resume evidence on both backends; model answers are fixtures and readiness BASIC_CHECKED. Live generation probes returned OpenRouter 404 and Gemini 503, leaving live usage/source/media certification unavailable. F04 is integrated with local/native evidence; configured-provider Q22 acceptance is unavailable and its overall status is IMPLEMENTED_UNVERIFIED. The other 16 module documents remain plans. Each module documents current gaps, objective/ownership, contracts, implementation steps, file map, failures/migration, acceptance checks, and user questions. CURRENT_STATE and MODULE_STATUS prevent future agents from mistaking a plan for completed work.
