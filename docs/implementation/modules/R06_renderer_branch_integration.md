# R06 — PptxGenJS branch adaptation and renderer parity

Type: **Repair / integration** · Current capability: **Repaired shared renderer/native parity** · Implementation: **VERIFIED (R06 scope)** · Phase: **1**

Workflow references: 11, 18, 25, 28. Dependencies: [R02](R02_provenance_and_assets_repair.md), [R04](R04_quality_gate_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Implemented on 9 October 2026. `renderers/base.py` owns `scene-v1`, shared validation and the explicit `ir2-layout-v1` adapter. Python and locked PptxGenJS 3.12.0 consume resolved boxes; legacy builders and Python/Node CLIs delegate to this boundary. Generation/repair/import/editing retain renderer metadata and scene hashes in R05 revisions. **242 tests pass (41 R06 cases)**; actual PowerPoint opens/renders both nine-table fixtures and the identical nine-slide scene, then saves/reopens native text/table/chart edits. Real JS generation/edit/resume passes artifact gates with BASIC_CHECKED readiness. Exact hashes, scope and unrun checks are in CURRENT_STATE and `C:/Users/thang/Projects/PPTAI/audit-artifacts/r06/verification.json`. Setup/reproduction is documented in `renderers/README.md`. Python remains the migration default while broader promotion checks remain unrun. F13/F14 and editable equations remain separate work.

Historical branch observations before this repair:

origin/hardik-pptxgenjs is now e534ff1; source code is unchanged from f9a50e4, with README/reference decks added. Its JS tables use valign=mid and fail native PowerPoint opening. Images/diagrams are placeholders and main.py still calls Python. There is no shared Git ancestor with multi-agent.

## Objective and ownership

Port useful renderer code into the current pipeline, keep one validated presentation contract, and make PptxGenJS the intended renderer once compatibility/editability acceptance passes. Preserve Python as an adapter during migration.

## Inputs, outputs, and contracts

Renderer.render(scene_graph, asset_registry, theme, output_path) -> artifact plus warnings/capabilities; legacy IR2 adapters are versioned. Backend choice is explicit in CLI/service.

## Implementation sequence

1. Port core/builder.js with provenance into renderers/pptxgenjs rather than merging the older pipeline wholesale.
2. Correct table valign to middle; enforce column/series lengths, negative axes, horizontal bar direction, and unsupported-object errors.
3. Wire real images/math and native diagram primitives; consume solver boxes instead of owning fixed layout geometry.
4. Make Python/Node entry points thin wrappers over the shared renderer boundary.
5. Compare identical fixtures and scene graphs in PowerPoint; establish a passing locked-version baseline before a dependency upgrade.

## File map

- renderers/base.py (new)
- renderers/python_adapter.py (new)
- renderers/pptxgenjs/ (new implementation directory)
- core/builder.py (existing)
- main.py (existing)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Keep the Python adapter available until parity passes. Record backend/version in every revision. Renderer fallback must be explicit and must pass that backend’s own artifact checks.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Nine-slide table fixture opens in PowerPoint after the correction.
- Required images are real assets, not placeholders.
- Native text/table/chart editability survives export.
- Same scene graph has equivalent content and required-object coverage on both adapters.
- No renderer silently skips unsupported required objects.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q08: local Windows demo first; retain portable API/render worker boundaries.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
