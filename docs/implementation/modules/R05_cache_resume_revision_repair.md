# R05 — Cache, resume, and atomic revision repair

Type: **Repair** · Current capability: **Repaired current CLI cache/resume and revision publication** · Implementation: **VERIFIED (R05 scope)** · Phase: **0**

Workflow references: 14, 24, 27. Dependencies: None.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

The repaired opt-in multi-agent path caches Docling parsing by source bytes, filename, parser/configuration source and installed version. Parser artifacts/assets and original source bytes are integrity checked. Completed extraction batches, validated slides and scoped visual repairs are persisted independently. Actual source/schema/prompt code, model/provider/capabilities/budgets, layout/theme and asset hashes determine reuse; invalid checkpoint payloads are misses. Stage output hashes are checked too.

`core/revisions.py` stages complete bundles under `revisions/<id>/`, validates the deck/assessment and assessed IR hashes, hashes every file, and publishes exactly one `active.json` pointer using an OS-owned publication lock and compare-and-swap base check. Readers use `active_artifacts(output_dir)` to resolve once. Original parser projections remain byte-preserved; assets/preview references in runtime snapshots resolve inside the revision. Suggestions have an explicit NOT_IMPLEMENTED state until F11. Accepted revisions are never mutated by generation, editing, evaluation or restore.

An unchanged resume returns the committed PPTX without parsing, generation, rebuilding or rendering. Accepted edits update IR2/PPTX/quality stage hashes and per-slide bindings, and refresh derived slide checkpoints only after successful publication. Quality-option changes also invalidate older composition bindings against the active edit. Edit attempts use isolated workspaces and require `base_revision`; stale bases are rejected before calls, and concurrent candidates are checked again at publication. Failed/cancelled jobs retain checkpoints and terminal journal records. Recovery marks abandoned jobs INTERRUPTED or recovers COMPLETED from committed ancestry while excluding live edit locks.

CLI: `--pipeline multi-agent --resume`; `--edit-slide N --instruction "..." --base-revision <active-id>`; `--import-legacy-run` explicitly adapts compatible legacy runs, revalidates source claims, rebuilds and renders without overwriting originals. Older incompatible contracts require regeneration. `RevisionStore.restore(revision_id, base_revision=...)` changes only the active pointer. Root-level pre-R05 deck/JSON files remain historical; the root run manifest is a mutable job summary. The committed directory's manifest/report is artifact authority and `jobs/*.json` records operation termination.

Verification: **201 passing tests**, including **24 R05 cases**, plus real Docling parsing, slide-4 checkpoint recovery, native PowerPoint COM rendering, source-backed editing and unchanged resume. Final native PPTX SHA-256 `673748402e078c04c0bd3bdd34d7bc1a12d6da74b4438825a0e9973175d044ec`; source bundle SHA-256 `550b6e8d939c9ee87e61c7bcd506fed06fc78e76284df4f34347ae4a0c536864`, on base `24e8a3a1d8e9a2684348194ae4149a2c8c263107`. Exact evidence and unrun checks: `C:/Users/thang/Projects/PPTAI/audit-artifacts/r05/verification.json` and CURRENT_STATE. Native readiness is BASIC_CHECKED; generation uses a typed source fixture. No new live-provider/full-upload benchmark, POSIX/fallback renderer, hardware power-loss/network-filesystem certification, chat/history UI, suggestion generator, cache GC, renderer default promotion, commit, push or deployment is included.

## Objective and ownership

Make cached work and edits durable before adding chat/history. Own content-addressed artifacts, resumability, revision concurrency, and crash recovery; F17 owns user-facing history.

## Inputs, outputs, and contracts

Revision records parent_id, input/source/brief hashes, IR hashes, artifact hashes, quality state, and active pointer. Cache keys include actual prompt/schema/model/parser/theme/asset versions. CommitRevision publishes a complete staged revision.

## Implementation sequence

1. Cache parsing independently of presentation preferences; persist each completed extraction batch and slide.
2. Compute cache keys from actual inputs and versioned dependencies rather than static prompt labels.
3. Stage JSON, deck, previews, suggestions, and checks under one revision; switch the active pointer only after successful publication.
4. Require base_revision for edits and reject stale writes. Update caches/manifests when a user edit changes a slide.
5. Recover interrupted jobs from committed artifacts and record terminal failures/cancellation.

## File map

- core/artifacts.py (existing)
- pipeline/orchestrator.py (existing)
- pipeline/slide_editor.py (existing)
- main.py (existing)
- core/revisions.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Keep previous immutable revisions. Rollback changes the active pointer or creates a restoration revision; it does not delete history or mutate evidence.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Unchanged resume makes no parsing/generation calls.
- A failure on slide 4 preserves completed slides 1–3.
- Edits survive resume.
- A simulated interruption cannot expose mismatched JSON/deck files.
- Two stale edits cannot overwrite each other.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: chat edits and layout/content controls are the first editing UI.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
