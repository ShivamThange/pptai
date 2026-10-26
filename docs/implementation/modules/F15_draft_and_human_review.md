# F15 — Draft PPT, suggestions, and human review UI

Type: **Feature** · Current capability: **Missing** · Implementation: **NOT_STARTED** · Phase: **4**

Workflow references: 23a, 23b. Dependencies: [F01](F01_api_jobs_and_service.md), [F03](F03_prompt_enhancement_and_audience.md), [F11](F11_ir2_content_and_suggestions.md), [F13](F13_dynamic_geometry_and_layout.md), [R04](R04_quality_gate_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

No integrated UI currently shows actual slide previews and suggested content together. The user explicitly places human-in-the-loop review after a draft.

## Objective and ownership

Show the draft and suggestions side by side, with source links and meaningful controls. First generation can proceed after Send; optional storyboard preview is available without a mandatory extra approval step.

## Inputs, outputs, and contracts

DraftReview combines artifact revision, actual previews, visible slide content, suggestions, evidence links, quality findings, brief controls, and selected scope. Suggestion acceptance is an explicit edit request.

## Implementation sequence

1. Build draft preview plus a selected-slide suggestion panel.
2. Show source-backed alternatives and clearly labeled gaps; provide evidence inspection for claims/data.
3. Offer audience/count/theme and layout/content controls with slide/object locks.
4. Show progress, verification completeness, and precise unresolved issues in context.
5. Route accepted suggestions and chat instructions through versioned editing rather than modifying renderer files directly.

## File map

- frontend/review/ (new)
- frontend/suggestions/ (new)
- api/decks.py (new)
- api/revisions.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Retain the previous valid draft on a failed edit. Keep the latest stable revision visible while a new one is processing.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Draft and relevant suggestions are visible together.
- Actual exported-file previews are used.
- Unsupported ideas cannot appear indistinguishable from source facts.
- Accepting one suggestion leaves other locked slides unchanged.
- An unavailable suggestion/verification service does not erase the draft.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q03: Chat edits plus layout/content controls. Drag-and-drop canvas is deferred.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
