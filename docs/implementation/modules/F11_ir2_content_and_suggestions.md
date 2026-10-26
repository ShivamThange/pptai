# F11 — IR2 visible content and editing reserve

Type: **Feature** · Current capability: **Partial / missing reserve** · Implementation: **NOT_STARTED** · Phase: **3**

Workflow references: 18, 19, 20, 23a. Dependencies: [F10](F10_dynamic_narrative.md), [F09](F09_structured_retrieval.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

TargetIR2Presentation contains renderer-ready slides with source_unit_ids. It has no separate editing reserve, suggestion pool, per-claim links, or explicit distinction between visible and optional content.

## Objective and ownership

Retain useful extra content for editing without placing all source material into every prompt or accidentally exporting suggestions.

## Inputs, outputs, and contracts

IR2Bundle contains narrative_plan, ContentPlans, layout intent/scene refs, and SuggestionRefs. ContentPlan stores atomic claims, data bindings, required/optional items, notes, and evidence. Suggestion has scope, source-backed/gap-idea label, evidence refs, rationale, and status.

## Implementation sequence

1. Compose each slide from its plan and scoped retrieved evidence.
2. Keep visible content and optional source-backed alternatives in separate typed fields.
3. Store unused-content index/reference pointers to IR1 rather than duplicating the full source in IR2; retrieve fuller alternatives on demand.
4. Generate a small relevant suggestion set for the selected slide and flag unsupported ideas as questions/gaps, not assertions.
5. Project only visible objects and chosen notes into the renderer. Accepted suggestions pass evidence/fit checks before becoming visible.

## File map

- schemas/ir2_content_schema.py (existing)
- schemas/content_plan_schema.py (new)
- schemas/suggestion_schema.py (new)
- pipeline/slide_composer.py (existing)
- pipeline/suggestions.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

If suggestion generation fails, the draft remains usable. Keep source-backed alternatives retrievable and record suggestion failure separately.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Extra content remains available for edits but does not appear in export automatically.
- Every factual alternative resolves to IR1 evidence.
- Unsupported suggestions are clearly labeled and contain no invented statistics.
- Accepting a suggestion updates only the chosen scope and revision.
- Large reserves are references, not unbounded prompt payloads.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q06: Source-backed alternatives first; gaps labeled.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
