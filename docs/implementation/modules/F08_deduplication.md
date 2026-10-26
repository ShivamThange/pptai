# F08 — Evidence-preserving deduplicator

Type: **Feature** · Current capability: **Partial** · Implementation: **NOT_STARTED** · Phase: **2**

Workflow references: 15, 21. Dependencies: [F05](F05_ir1_source_knowledge.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Current deduplication merges identical stable IDs and unions evidence. It does not implement the near-duplicate semantic deduplicator shown in the reference PPT.

## Objective and ownership

Merge repeated equivalent statements while retaining all source references and keeping contradictory or differently scoped claims distinct.

## Inputs, outputs, and contracts

DedupResult has canonical_units, aliases, merged_evidence, candidate similarities, and nonmerged/conflict reasons. Metric identity includes subject/measure/unit/period, not just similar wording.

## Implementation sequence

1. Use deterministic normalization/exact matching first.
2. Generate bounded semantic candidates with a fixed embedding model only when needed.
3. Check entity/unit/period/negation and structured fact compatibility before merging candidates.
4. Retain every evidence link and alias old IDs to a canonical ID; rewrite downstream references deterministically.
5. Expose ambiguous/opposed candidate pairs without resolving them as duplicates.

## File map

- pipeline/deduplicator.py (new)
- pipeline/knowledge_extractor.py (existing)
- schemas/ir1_schema.py (existing)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

When equivalence is uncertain, keep both units. Semantic service failure falls back to exact dedup with recorded reduced capability.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Paraphrases can merge without losing either source.
- Revenue and profit do not merge because a value matches.
- Different periods/units/negation remain distinct.
- Existing references continue resolving through aliases.
- Duplicate passages do not multiply coverage credit.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed module structure; Q13: Should ambiguous duplicate pairs be shown in an advanced review view? Proposed yes, outside the main flow.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
