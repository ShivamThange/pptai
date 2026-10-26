# F18 — PPTX and PDF export

Type: **Feature** · Current capability: **PPTX partial; PDF missing** · Implementation: **NOT_STARTED** · Phase: **4**

Workflow references: 25. Dependencies: [F15](F15_draft_and_human_review.md), [R06](R06_renderer_branch_integration.md), [R04](R04_quality_gate_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

PPTX compilation and render helpers exist. Exported-file compatibility fails in the JS table case; PDF export is not a validated shared service.

## Objective and ownership

Export the selected current revision as editable PPTX and a PDF rendered from that same checked artifact, with backend capability/status recorded.

## Inputs, outputs, and contracts

ExportRequest specifies deck/revision and format; ExportResult includes artifact hash, renderer/version, completeness/readiness, download path, and errors. PDF conversion is derived from the checked PPTX, not a separate slide generator.

## Implementation sequence

1. Validate native opening/rendering for PPTX fixtures and reject structurally broken exports.
2. Use the selected supported desktop/headless renderer for PDF conversion in an isolated worker.
3. Check PDF page count, missing required objects, and representative visual parity against slide previews.
4. Bind preview/PPTX/PDF to one revision and expose format-specific availability.
5. Preserve native editability claims accurately: figures/math assets differ from native text/tables/charts/diagram shapes.

## File map

- workers/render_export.py (new)
- pipeline/slide_renderer.py (existing)
- api/exports.py (new)
- frontend/export/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Return format-specific errors and keep other valid artifacts downloadable. Never convert an invalid deck and call it a successful export.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- PPTX opens in the target PowerPoint environment.
- PDF has the expected pages and required content.
- Export matches the revision the user selected.
- PDF converter failure does not destroy a valid PPTX.
- No claim that generating a PPTX in-browser is equivalent to rendering its preview/PDF.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q08: Windows/PowerPoint-first demo; hosted Linux parity is later work.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
