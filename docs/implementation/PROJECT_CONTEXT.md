# Shared project context

Prepared on 8 October 2026. Repository: `C:/Users/thang/Projects/PPTAI/BTPs5`. Workspace: `C:/Users/thang/Projects/PPTAI`. Implementation base: **multi-agent**. Module specs describe proposed work, not completed capabilities; check CURRENT_STATE for evidence.

## Product objective and confirmed scope

Turn uploaded documents into source-grounded, presentable, editable PowerPoint decks. The UI accepts files, a prompt, audience/mode, and presentation controls; Send starts extraction/generation. Users then review a draft beside relevant suggestions, edit through chat and layout/content controls, retain V1/V2 history, and export PPTX/PDF.

The user confirmed one separate module and one implementation document per feature/improvement. A module can be deterministic code, service, UI, or agent responsibility; it does not require a distinct LLM. The original implementation plan remains the architectural base. Module docs and confirmed decisions add workflow detail rather than discarding its reliability, grounding, rich parsing, dynamic layouts, UI, and evaluation recommendations.

Confirmed first-release inputs: PDF, DOCX, TXT/Markdown, CSV/XLSX, PNG/JPEG. Prioritize document-backed alternatives and label unsupported ideas as gaps. Citation/source-membership and applicable numeric checks always run; deeper verification is optional. First editing UI is chat plus layout/content controls. Exact counts apply to main content; cover, conclusion, and appendix are separate extras with explicit counts. Native flowcharts and architecture graphs are included. Local Windows is the initial demo environment with a portable API. LLM/provider selection remains open; implementation is sequenced by dependencies without timeline estimates. Full canvas editing and full cross-document conflict resolution are deferred.

## Shared architecture and terminology

Confirmed Q22 (13 October 2026): asset understanding includes results, findings and semantic contribution to the original document context. Source-grounded asset knowledge must participate in presentation text/narrative even when the asset is not displayed. F04 owns contextual interpretation and its adapter into current IR1/text composition; F05/F09/F10/F11 extend knowledge/retrieval/planning. Captions and alt text alone do not satisfy this planned requirement; uncertainty and original evidence remain explicit.

1. **Raw DocumentIR**: retained structural content, source bytes/hashes, blocks, assets, hierarchy, and provenance from Docling/adapters.
2. **IR1**: typed, source-grounded knowledge plus an evidence/asset registry. It is audience-independent so later edits can recover unused facts. It is not raw parser JSON and not a second generated summary treated as evidence.
3. **IR2 skeleton / NarrativePlan**: brief-conditioned flow, stable slide IDs, purposes, prerequisites, count/time allocation, selected evidence, and locks.
4. **IR2 bundle**: visible ContentPlans, optional source-backed suggestions/editing reserve references, layout intents, and resolved scene references. Suggestions are never rendered automatically.
5. **SlideSceneGraph / Presentation AST**: data-only native objects with geometry, roles, themes, hierarchy, graph/data/evidence links, and stable object IDs.
6. **Renderer adapters**: PptxGenJS is the intended improved backend after parity; Python remains available during migration. Both consume the same canonical contracts.
7. **Versioned artifacts**: actual PPTX, its rendered previews/PDF, IR snapshots, quality/usage metadata, and chat/edit lineage belong to the same immutable revision.

The IR1 responsibility chain follows the reference deck: extractor → deduplicator → validator → coverage critic → scoped retry → validated IR1. Parsing, arithmetic, exact checks, and geometry are deterministic; specialized LLM calls are used only where they help. Global planning can use one bounded call, while slide composition and edits use scoped retrieval.

## Shared invariants

- Source IDs/evidence are real references to uploaded material. Per-object usage must reflect support, not just inherit all planner IDs.
- Optional deep verification does not disable provenance, asset existence, schema, or numeric binding checks. Unknown semantic support remains unknown.
- Preserve complete raw input. Distinguish retained content, examined/processed source, context sent per call, and facts selected for the presentation. No silent truncation.
- Full-context calls are allowed when useful and within actual stage capacity; progressive chunking/retrieval is the fallback. Include system/schema/tool/image/output overhead in budgeting.
- Audience is collected before planning; presentation geometry is computed after content selection. Source bounding boxes are separate extraction metadata.
- Unsupported suggestions are ideas/questions with explicit labels, not invented factual assertions or numeric data.
- Layout-only changes preserve factual content/evidence. Native tables/charts/diagrams remain editable; images/math assets have accurately described editability.
- Locks, exact-count semantics, source policy, and version concurrency are explicit. Do not change them silently.
- Quality checks refer to the final artifact hash. Missing optional/failed required judging is not a successful complete assessment.
- One application service, fact store, and scene contract serve CLI/UI/export. Do not wholesale-import a second older branch pipeline.

## Common data boundaries

`PresentationBrief`: original/enhanced prompt, explicit/inferred field origins, audience, objective, duration, count semantics, theme/design preferences, must/never topics, notes, hard/soft constraints, source policy, and locks.

`EvidenceRef`: document/source item ID and typed excerpt/cell/range/figure/formula location. `MetricFact`: subject, measure, value, unit, period, precision, and evidence. `AssetRegistry`: kind, actual content/path/hash, dimensions, captions, provenance, and verified data availability.

`ContentPlan`: stable slide/object IDs, atomic visible claims, optional detail/notes, selected data/assets, and per-object evidence. `Suggestion`: source-backed alternative or explicitly unsupported gap idea, scope, evidence, rationale, and acceptance state.

`ToolResult`: bounded typed data, evidence IDs, status, warnings, timing/usage, and cache version. `RunManifest/Revision`: exact input/config/version hashes, stage attempts/status, completeness, artifact references, terminal status, base/parent revision, and locks.

These are contract responsibilities, not completed schemas. Implement them by extending versioned existing contracts and testing Python/TypeScript parity. Avoid arbitrary model-authored executable code as a production slide format.

## Agent reading and update protocol

Read AGENTS.md, this context, CURRENT_STATE, BRANCH_STRATEGY, DECISIONS, MODULE_STATUS, and the selected module doc before implementation. Use WORKFLOW_CROSSCHECK to verify dependencies and product order. Consult BASE_PLAN for deeper examples/research/reproduction.

Respect the current human instruction over historical plans. Confirmed decisions outrank proposed defaults. Pending questions remain explicit; they are not automatic approval requirements for unrelated work. Update CURRENT_STATE/MODULE_STATUS with tested outcomes after actual code changes, and add user answers to DECISIONS. Do not describe documentation-only changes as shipped product features.
