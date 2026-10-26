# Repository cleanup and remaining development work

9 October 2026. Scope: the BTPs5 Git checkout on multi-agent, preparing for the
user's intended promotion to main. No commit, merge, push, or branch switch was
performed. Existing uncommitted R06 implementation files were preserved.

## Removed and rewired

- Removed replaced generation modules: pipeline/stage3_semantic_ir1.py,
  pipeline/stage4_ir2_planner.py, and their exclusive core/rate_limiter.py.
  main.py now always uses cached parsing and the multi-agent orchestrator.
  Existing --pipeline multi-agent commands work; --pipeline legacy is rejected.
  Editing, pre-revision artifact import, evaluation, and renderer selection are
  wired through the supported contracts. Python remains the renderer default.
- Removed unused hardcoded script1.py and config/default_layouts.py demos,
  the empty config/layouts.json, and two unused build_presentation convenience
  wrappers. Keep config/ppt_default_layouts.json: composition still uses it.
- Simplified Python primitives to receive resolved slide dimensions. Removed
  duplicate table-asset loading, silent chart-format fallback, redundant table
  padding/truncation, unused catalog/registry plumbing, and unused imports.
  Shared scene validation and asset hydration remain in renderers/base.py.
  The layout adapter now imports the asset resolver directly rather than
  through a core.builder re-export.
- Removed all six superseded MULTI_AGENT_MERGE_PLAN documents and the obsolete
  evaluator completion checklist. Updated references and stale current-capability
  paragraphs. Keep BASE_PLAN.md: active plans still reference its architecture,
  research, evidence, and original audit; its registered source hash is preserved.
- Removed generated output/, all 14 tracked output-multi artifacts, .pytest_tmp/
  (24,108 files, about 106 MiB), and 15 Python bytecode cache directories.
  The installed Node dependency tree is removed after verification; manifests
  and the lockfile remain. output-*/ is now ignored to prevent committing runs.
- Tests and native acceptance output from this cleanup are outside the checkout
  in ../audit-artifacts/repository-cleanup/. Historical verification evidence
  outside the repository is retained. Local .env and Git history are retained.

## Tests retained

No source test was found that exclusively tests the removed generation pipeline.
The tests whose names contain legacy exercise required old-artifact migration
and revalidation, rather than the deleted one-shot planner. Generated test
outputs and caches were deleted; the regression tests remain necessary.

R01-R06 tests protect transport failures, asset/provenance integrity, grounding,
quality gates, cancellation, concurrency, revision atomicity, resume, and native
renderer content. Passing them once does not replace protection during later
feature development. test_ir2_contract.py validates the IR2 contract still
emitted by the active composer. Evaluator tests still cover supported tools.

The CLI resume regression now checks both the default command and the explicit
multi-agent flag. New CLI tests reject legacy selection before work starts and
verify evaluation uses the active revision, including an unavailable aggregate.
The latter fixes a formatting error that mislabeled an incomplete evaluation as
an evaluation failure.

## Remaining code: runtime versus optional tools

The audit used source imports, relative imports, CLI references, and targeted
function searches. Import reachability is not proof that every branch executes
on every run. Package __init__.py files are package markers, not unused features.

| Code | Actual use and reason retained | Plan coverage |
|---|---|---|
| renderers/ Python adapters, factory, scene contract, artifact validator and JS builder.js | Active generation/edit/render/publication dependencies. Untracked source is new R06 work, not disposable output. Python serves the default backend; JS is selected explicitly. Keep both until a deliberate renderer-support decision. | R06 verified; F13/F14 extend it. |
| core/chart_content.py | Called by native artifact coverage on rendering and by evaluator extraction. It reads Office-authored literal chart-series names where python-pptx's cached-reference accessor is insufficient. Removing it breaks native edited-chart handling. | R06 implemented and tested; no missing integration. |
| core/builder.py, renderers/base.py layout adapter, config/ppt_default_layouts.json | Active composer output is layout-based IR2. These resolve geometry, assets and object expansion into scene-v1. Direct scene support exists, but the producer still needs this adapter. | F13 plans measured dynamic geometry; removing the catalog adapter requires a producer migration. |
| schemas/ir1_schema.py projection classes and knowledge_extractor.build_legacy_projection | Derive content_analysis.json from canonical IR1 for evaluator compatibility and pre-revision import. They do not run the removed generation pipeline. | F05/F19 plan richer IR1 and independent evaluation references. Final projection retirement is not explicitly scheduled. |
| scripts/verify_r06_native.py | Developer acceptance tool outside normal generation: actual PowerPoint opening/rendering, native edits and JS generation/edit/resume. It depends on typed fixtures in tests/test_cache_resume_revision_repair.py. Keep reproducible native verification; outputs are disposable. | R06 acceptance documented. Moving fixtures into shared test support and automatically running a platform matrix are not explicitly scheduled. |
| tests/ and evalute/tests/ | Development regression coverage, not production execution. Shared fixtures also support native acceptance. No obsolete legacy-generator-only suite identified. | R01-R06 and F19 acceptance coverage. Dedicated fixture/CI restructuring is not explicitly scheduled. |
| generate_ppt.py, renderers/__main__.py, renderers/pptxgenjs/index.js | Standalone entry points outside main generation. The first accepts layout/content JSON; the others accept resolved scenes. They reuse the canonical renderer; they are not duplicate engines. Could be removed only if dropping those supported tool interfaces. | R06 thin CLI requirement already implemented. |
| evalute/cli.py and evalute/compare.py | Standalone reference/evaluation/comparison tools, useful for existing decks and academic runs. --evaluate calls the evaluator runner but does not call its CLI/comparison entry point. | F19 plans academic comparison and repaired metrics. |
| pipeline.slide_editor.import_legacy_revision | Optional --import-legacy-run migration of pre-R05 multi-agent folders. Uses current validation/rendering, preserves originals, and rejects invalid provenance. No replacement migrator exists. | R05 implemented and tested; no sunset decision recorded. |
| RevisionStore.restore() | Tested public revision utility, not exposed by main.py's CLI. Needed for safe version restoration; not automatic generation work. | R05 implemented; F17 plans user-facing version history/restore. |
| Optional deep claim judging, visual review and evaluator modules | Run only when their flags/configuration request them. Basic grounding and final-artifact checks remain active without those options. Optional execution does not establish dead code. | R03/R04 repairs implemented; F06/F19 full workflows remain planned. |

After removing the demos and old planners, no additional standalone runtime
module was identified as safely removable from the supported import/tool paths.
This is a static audit with targeted runtime verification, not an exhaustive
proof that every method or branch is live.

## Partial features that still need attention

All F01-F20 module implementations remain NOT_STARTED in the registry, despite
inherited partial capabilities and verified R01-R06 repair scopes.

| Area and current limitation | Why the current code stays | Current module plan |
|---|---|---|
| No shared API/jobs/upload or review UI; parser CLI has not completed first-release routing across all promised formats. | Parser, source adapter and atomic job/revision internals provide the working generation foundation. | F01, F02, F15. Planned. |
| No typed initial prompt enhancement/audience brief and complete main-content/extras count semantics. Storyboard takes a lens and min/max bounds. | Existing source-bound planning works and is the extension point. | F03, F10. Planned. |
| Source asset extraction is partial across formats; existing formula support embeds source raster crops, not editable equations. Automatic chart-data understanding is incomplete. | Real asset registry, extraction and native rendering are active and verified within R02/R06 scope. | F04, F05. Planned. |
| Character-based extraction budgets and characters/4 token estimates; sparse chunk consolidation can exceed its budget and lose the merged section's asset association. No end-to-end context coverage ledger. | Chunking/retrieval currently supply scoped slide context; removing them would remove context from composition. | F07. Planned and needs priority before large-input expansion. |
| Deduplication is exact stable-ID merging, not semantic near-duplicate resolution. | It currently unions supported evidence without fabricating facts. | F08. Planned. |
| Retrieval uses explicit unit/chunk/asset IDs; a full structured query service and complete per-object usage trace are missing. | Active composition/editing require current retrieval. | F09. Planned. |
| Basic numeric/citation checks and optional scoped semantic judging exist; exhaustive deep figure/claim verification and the full hybrid role/tool workflow are incomplete. | Existing deterministic guards and bounded scoped retries are core runtime safety checks. | F06, F12. Planned. |
| No generated source-backed suggestion reserve or acceptance flow. suggestions.json deliberately records NOT_IMPLEMENTED with an empty list. | The explicit capability marker belongs to the revision contract and prevents an empty file from claiming the feature exists. | F11, F15. Planned. |
| Fixed catalog regions and heuristic font sizing; no measured dynamic layout solver. | The adapter renders today's composer output through the common scene contract. | F13. Planned; R06 already supplies the scene boundary. |
| Both adapters render editable graph primitives, but no Mermaid parser/Dagre graph-layout workflow. | Native cards/connectors are working backend support, not an obsolete diagram placeholder. | F14. Planned. |
| Single-slide CLI editing and immutable revisions exist; full layout/content controls, chat workflow and user-facing durable history are missing. | Current editor and revision store are the verified foundation. | F16, F17. Planned. |
| PPTX generation and quality-preview/PDF intermediates exist, but there is no validated user PDF-export service. | Native render intermediates support quality checks, even without an export UI. | F18. Planned. |
| Approximate six-metric evaluator: source-derived references can inherit IR1 omissions; embedding fallback changes score meaning; functional/structural scoring is heuristic; academic calibration/benchmarking is absent. Complete aggregate is withheld when factual checks are unavailable; available-metrics diagnostics are separate. | Existing evaluator remains optional, inspectable scaffolding for repair rather than a completed academic certification. | F19. Planned. |
| Cross-document conflict resolution is absent. | There is no unused conflict engine to delete. | F20. Explicitly deferred. |

## Cleanup limitation and promotion requirements

Windows denies access to .pytest_cache, including reading its ACL and ownership
recovery without elevation. That directory could not be inspected or removed.
Other scoped cache/output removals succeeded. No process was elevated and no
permissions elsewhere were changed.

The source is prepared for review; the branch has not been promoted. Include
the new renderer source, core/chart_content.py, native acceptance script,
regression tests, and this report in the reviewed change before promotion.
Untracked source is not included in a normal git diff --stat.

The installed node_modules tree is intentionally absent after cleanup. Restore
the exact dependency tree before JS rendering/tests:

```powershell
npm.cmd ci --prefix renderers/pptxgenjs --ignore-scripts --no-fund --no-audit
```

R01-R06 evidence remains historical scoped verification; cleanup does not mark
future F modules complete. Verification details for this change are recorded
in CURRENT_STATE.md and ../audit-artifacts/repository-cleanup/.

## Verification result

Final automated suite: **246 passed**, with all locked JS dependencies installed
for the run. Both backends passed actual PowerPoint acceptance: nine-table
opening/rendering, shared-scene content parity, and native text/table/chart edits.
JS generation/edit/resume passed actual gates and revision publication.
CLI help and git diff --check pass. No new live provider/full-document or
cross-platform acceptance was performed. Logs, native artifacts, source hashes
and verification.json are under ../audit-artifacts/repository-cleanup/.

Native acceptance was run after CLI/primitive rewiring; the final full suite
also includes the subsequent deletion of unused convenience wrappers. No
module completion status is inferred from this cleanup.
