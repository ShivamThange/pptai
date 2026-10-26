# F13 — Dynamic geometry, sizing, and slide layouts

Type: **Feature** · Current capability: **Dynamic geometry, theming and object library** · Implementation: **VERIFIED (sandbox scope)** · Phase: **3**

Workflow references: 11, 18, 28. Dependencies: [F11](F11_ir2_content_and_suggestions.md), [R04](R04_quality_gate_repair.md), [R06](R06_renderer_branch_integration.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

F13 is implemented in the working tree: five validated themes (`core/theme_engine.py`), a deterministic per-slide geometry re-solver over already-filled catalog regions (`core/layout_engine.py`), and a pre-render fitting pass (`renderers/fitting.py`). The solver never invents a composition: it re-solves boxes for the regions IR2 filled and falls back to catalog geometry on any failure.

The 26 October working-tree extension adds six predefined IR2 objects — `card`, `metric_card`, `callout`, `quote`, `chips`, `compare` — expanded into native scene primitives by `renderers/base.py` and allowed by the card/grid/metric/process/comparison/quote/closing layouts. It also adds deterministic placement of planned figure/formula assets (`pipeline/visual_placement.py`) and caps stretched object boxes at their measured need. These changes are recorded in CURRENT_STATE; no live structured-mode deck has been published with them yet.

## Objective and ownership

Generate varied but coherent layouts, including bento grids, with deterministic sizing and native editable objects. Source bounding boxes remain extraction metadata; presentation geometry is resolved after content planning.

## Inputs, outputs, and contracts

LayoutIntent describes grid/row/column/stack hierarchy and content IDs. SlideSceneGraph resolves native objects with inches/points, text roles, theme tokens, z-order/containment, aspect behavior, and evidence/data refs.

## Implementation sequence

1. Create theme tokens and constrained primitives; keep proven recipes as fallbacks.
2. Let the designer propose semantic spans/hierarchy with bounded candidates, rather than unrestricted code or random coordinates.
3. Measure actual-font text wrapping, table content/padding, and figure ratios; solve boxes analytically first.
4. Enforce title/footer space, font floors, bounds, intentional containment, and image label legibility; rank only feasible candidates.
5. For overflow, change composition/shorten supported text/use notes; split only if count permits. Render actual PPTX and repair scoped objects.

## File map

- schemas/layout_intent_schema.py (new)
- schemas/scene_schema.py (new)
- core/layout_engine.py (new)
- core/text_measurement.py (new)
- config/themes/ (new)
- renderers/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Use a tested feasible fallback when a proposed layout fails. If user locks/count prevent any feasible layout, show concrete conflict choices and retain the prior revision.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Same ContentPlan supports several valid bento/figure/chart-led compositions.
- Bento cell counts/spans vary with content while theme stays coherent.
- Dense tables/equations do not fall below font floors silently.
- Layout-only edits preserve factual content/evidence hashes.
- Final PowerPoint renders pass fit and required-asset legibility checks.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed first UI has layout controls. Confirmed Q09/Q10: do not expand exact main-content count; propose notes/shortening/layout alternatives. Extras are tracked separately. No requirement for full drag-and-drop canvas in MVP.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
