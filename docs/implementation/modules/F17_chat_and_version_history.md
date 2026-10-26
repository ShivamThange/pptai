# F17 — Chat-like interaction and V1/V2 history

Type: **Feature** · Current capability: **Missing / partial edit log** · Implementation: **NOT_STARTED** · Phase: **4**

Workflow references: 27. Dependencies: [F16](F16_prompt_edits_and_layout_changes.md), [R05](R05_cache_resume_revision_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

edits.json records some instructions, but complete immutable deck revisions, chat threading, preview comparison, restoration, and failed-attempt history do not exist.

## Objective and ownership

Provide a durable chat tied to explicit deck versions. Messages describe intent/results; artifact revisions are the source of truth for deck state.

## Inputs, outputs, and contracts

ChatMessage references instruction, edit/job status, base/result revision, scope, and error. DeckRevision stores V label, immutable artifact refs, parent, locks, plan/evidence hashes, and quality/usage metadata.

## Implementation sequence

1. Create V1 for the initial draft and V2+ for each successfully published change.
2. Keep failed attempts in chat/job history without assigning them a misleading completed deck version.
3. Display parent/current version and before/after previews for affected slides.
4. Restore an earlier version as a new revision or active pointer transition with audit history.
5. Record source/brief snapshot changes separately; derive edit context from current artifacts rather than replaying unbounded chat.

## File map

- core/revisions.py (new / shared with R05)
- api/history.py (new)
- frontend/history/ (new)
- frontend/chat/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Recover committed revisions after process failure. Pending messages/jobs reconnect to their real state rather than guessing whether a version was created.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Refreshing preserves chat and version links.
- V labels map to actual immutable exports/previews.
- Restoration does not delete newer history.
- Long chat does not overflow generation context.
- Failed edits remain visible but do not replace the active deck.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Q16: Is per-user saved history beyond the local demo required now? Proposed local persistence first, portable storage later.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
