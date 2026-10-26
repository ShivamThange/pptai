# F16 — Prompt editing, scoped regeneration, and layout changes

Type: **Feature** · Current capability: **Partial CLI editing** · Implementation: **NOT_STARTED** · Phase: **4**

Workflow references: 24, 28. Dependencies: [F15](F15_draft_and_human_review.md), [F09](F09_structured_retrieval.md), [R05](R05_cache_resume_revision_repair.md), [F13](F13_dynamic_geometry_and_layout.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

The CLI can recompose a single slide with an instruction, but revision/cache consistency, object-level scope, UI controls, and deterministic layout-only edits are missing.

## Objective and ownership

Support chat/content/layout edits with the narrowest valid regeneration scope and preserve source grounding, user locks, and unrelated slides.

## Inputs, outputs, and contracts

EditRequest includes instruction/action, scope, slide/object IDs, base_revision, locks, and allowed changes. EditPlan classifies content/layout/theme/narrative operations and lists affected dependencies.

## Implementation sequence

1. Resolve the user’s scope and return concrete conflicts if locked/count constraints prevent the change.
2. Use deterministic patches for layout swap, color, supported typography, or native diagram movements when facts are unchanged.
3. For content edits, retrieve IR1 plus editing reserve and compose only affected objects/slides.
4. Run applicable evidence/fit/render checks; publish a complete new revision via R05.
5. Support deck-wide audience/theme/flow changes explicitly while retaining locked objects and scoped evidence lineage.

## File map

- pipeline/slide_editor.py (existing)
- pipeline/edit_planner.py (new)
- api/edits.py (new)
- frontend/chat/ (new)
- frontend/layout_controls/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Failed edits leave the base revision active with actionable errors. Do not silently broaden a slide edit into whole-deck regeneration.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Layout-only edit leaves claim/evidence content unchanged.
- A single-slide edit changes no unrelated slide.
- A request for unsupported content flags the gap.
- Stale base revisions are rejected safely.
- Regeneration produces a new checked revision and undo remains possible.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: chat + layout/content controls. Q15: Should chat support entire-deck edits in the first demo? Proposed yes for audience/theme, with visible scope.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
