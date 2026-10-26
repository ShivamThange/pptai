# F06 — Optional deep source verification

Type: **Feature** · Current capability: **Partial / unreliable** · Implementation: **NOT_STARTED** · Phase: **2**

Workflow references: 9. Dependencies: [F05](F05_ir1_source_knowledge.md), [R03](R03_grounding_validation_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Existing validators check evidence strings/numbers and the evaluator has a separate model judge. There is no unified user-visible verification profile or honest shared result cache.

## Objective and ownership

Offer optional deeper factual/figure verification without making provenance or basic numeric checks optional.

## Inputs, outputs, and contracts

VerificationProfile = basic or deep. ClaimCheck contains source/cell checks, semantic/figure assessment, assessed evidence, confidence/reason, verifier version, and unknown/fail states.

## Implementation sequence

1. Always run source-membership, asset existence, schema, and applicable numeric binding checks.
2. For deep mode, batch evidence-scoped entailment and selected visual/table consistency checks via the common gateway.
3. Cache results by claim/evidence/verifier version and share them between generation and evaluation.
4. Show verification completeness and unresolved claims in review; scope repairs to the failed evidence/slide.
5. Keep disabled, unavailable, failed-to-run, and factual-fail statuses distinct.

## File map

- tools/claim_verification.py (new / shared with R03)
- pipeline/verification.py (new)
- schemas/verification_schema.py (new)
- frontend/review/VerificationPanel.tsx (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Basic-checked drafts remain reviewable. Deep verification failures do not fabricate neutral scores or silently relabel the run as fully verified.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Turning deep mode off cannot bypass citations/numeric checks.
- A failed judge preserves earlier results and yields unknowns.
- Deep mode identifies a supported excerpt that does not entail the displayed claim.
- Verification settings/results are recorded per revision.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q04: Basic checks always; deeper verification optional.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
