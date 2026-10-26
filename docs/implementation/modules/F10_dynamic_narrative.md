# F10 — Dynamic deck flow and IR1-to-IR2 skeleton

Type: **Feature** · Current capability: **Partial** · Implementation: **NOT_STARTED** · Phase: **3**

Workflow references: 10, 18, 21. Dependencies: [F03](F03_prompt_enhancement_and_audience.md), [F09](F09_structured_retrieval.md), [F12](F12_hybrid_agents_and_tools.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Storyboard planning is source/chunk-bound, but capacity context is thin and initial user goals/locks are absent. Fixed assumptions about source order and title style limit dynamic flow.

## Objective and ownership

Create a purpose-driven narrative tailored to audience, objectives, time, and count, using the reference PPT’s global plan/local composition approach.

## Inputs, outputs, and contracts

NarrativePlan contains ordered slide IDs, purpose/role, prerequisites, selected unit/asset IDs, time/count allocation, required/optional content, transitions, and locks. This is the IR2 skeleton; visible content follows in F11.

## Implementation sequence

1. Build brief-conditioned relevance/prerequisite maps from complete IR1 digests and retrievable references.
2. Use one global structured planning call when its digest fits; use hierarchical summaries/retrieval for larger sources.
3. Validate main-content count, separately displayed cover/conclusion/appendix counts, required main-topic coverage, lock preservation, and defined prerequisites.
4. Support reorder/split/merge/add/remove with affected-slide replanning and a recorded plan revision.
5. Offer alternative storylines on request rather than generating several unused plans every run.

## File map

- pipeline/storyboard_planner.py (existing)
- schemas/storyboard_schema.py (existing)
- schemas/narrative_schema.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

If required content cannot fit, return a concrete count/density/notes conflict. Preserve the prior plan until an alternative is selected or the brief changes.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Same source produces suitable technical/teaching/executive flows.
- Requested topics and count semantics are checked.
- A locked slide remains unchanged after replanning.
- Source order is not forced when a different audience flow is justified.
- Missing evidence appears as a gap rather than a fabricated slide claim.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q09/Q10: exact count applies to main content; extras are separate. Core required material cannot be silently moved to extras just to satisfy the count.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
