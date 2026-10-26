# F20 — Cross-document conflict detection (deferred)

Type: **Feature** · Current capability: **Missing / deferred** · Implementation: **NOT_STARTED** · Phase: **5**

Workflow references: 22. Dependencies: [F05](F05_ir1_source_knowledge.md), [F08](F08_deduplication.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

No reliable cross-document conflict registry is implemented. The user explicitly said to raise inner conflicts and examine this feature later.

## Objective and ownership

Reserve an extensible conflict representation now; defer dedicated detection/resolution UI to a later module. Do not silently collapse opposite claims during deduplication.

## Inputs, outputs, and contracts

ConflictCandidate stores both claim/evidence IDs, normalized scope/entities/units/period, relation, detection method, status, and user decision. It remains separate from canonical fact acceptance.

## Implementation sequence

1. Preserve potentially opposed claims as distinct units in IR1 and mark obvious typed value/scope disagreements.
2. Add schema hooks and IDs without building a broad expensive conflict agent in the MVP.
3. Later compare aligned subject/measure/period tuples before semantic contradiction checks.
4. Present both evidence excerpts and allow selection, coexistence with explanation, or clarification.
5. Revalidate affected slide claims after any conflict decision; never choose a truth based solely on confident wording.

## File map

- schemas/conflict_schema.py (new later)
- pipeline/conflicts.py (new later)
- frontend/conflicts/ (new later)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Keep both claims and expose the uncertainty. Full automatic contradiction detection is not claimed complete in the first release.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Dedup does not erase conflicting source claims.
- Deferred status is visible in roadmap/current state.
- Later conflict fixtures include same-subject values, dates, scope differences, and genuine contradictions.
- Any chosen resolution records both sources and the user decision.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed by workflow: defer detailed conflict handling. Q17: Which conflict types should the later version prioritize?

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
