# F05 — Canonical IR1 with actual document references

Type: **Feature** · Current capability: **Partial** · Implementation: **NOT_STARTED** · Phase: **2**

Workflow references: 7, 8, 16. Dependencies: [F04](F04_multimodal_asset_content.md), [F07](F07_context_budget_progressive_chunking.md), [R03](R03_grounding_validation_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

ValidatedIR1 schema 3, stable units, typed metric/evidence grounding, excerpt/cell bindings, explicit checked/unknown semantic states, and a derived evaluator projection exist after R02/R03. Complete typed cross-format evidence references, source knowledge modeling, and the full F05 workflow remain unimplemented; structured_data is still loose outside typed metric facts.

## Objective and ownership

Make IR1 the source-grounded knowledge layer, not raw Docling output or a presentation summary. Preserve raw DocumentIR separately and keep source-backed knowledge available for every later edit.

## Inputs, outputs, and contracts

IR1 contains typed knowledge units, metric/comparison/formula/figure references, evidence variants, priorities, validation metadata, alias maps, and source coverage. Knowledge IDs are stable across audience/style changes.

## Implementation sequence

1. Extend text-only EvidenceRef to document/block/page, table-cell/range, figure-region, and formula variants.
2. Build typed candidate units from raw content and deterministic table facts, preserving original terminology alongside summaries. Candidates remain NEEDS_REVIEW until the runtime dedup → validator → coverage-critic chain passes; publish canonical IR1 only afterward.
3. Track examined, represented, intentionally excluded, and failed source items in the coverage ledger.
4. Store one canonical IR1; create legacy evaluator projections from it rather than maintaining competing facts.
5. Validate schema/source membership before exposing units to the planner; distinguish basic_checked from deeply_verified.

## File map

- schemas/ir1_schema.py (existing)
- schemas/evidence_schema.py (new)
- pipeline/knowledge_extractor.py (existing)
- pipeline/source_adapter.py (existing)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Retain raw content and rejected/unknown diagnostics. Do not call incomplete extraction complete or change the source truth to match a requested slide.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Every factual unit resolves to actual uploaded-source evidence.
- Table/formula/figure facts can be cited without invented text blocks.
- No audience change destroys source knowledge needed for later edits.
- Legacy projection remains deterministic and evaluable.
- Coverage labels expose parse/extraction gaps.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: actual references from docs are mandatory. Basic verification is always enabled.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
