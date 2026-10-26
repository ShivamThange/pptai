# F09 — Structured IR1 retrieval and usage references

Type: **Feature** · Current capability: **Partial** · Implementation: **NOT_STARTED** · Phase: **2**

Workflow references: 16, 17, 19, 24. Dependencies: [F08](F08_deduplication.md), [F06](F06_optional_deep_source_verification.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Scoped retrieval by plan/chunk/unit/asset IDs exists; layout/composition receive limited context. A full structured query API and per-object usage trace are missing.

## Objective and ownership

Retrieve exactly the source-backed units/assets needed for planning, composition, verification, and edits, while recording what was actually used.

## Inputs, outputs, and contracts

retrieve(query, document_ids, unit_ids, asset_ids, kinds, budget) returns typed evidence/data and truncation/omission reasons. ObjectUsageTrace binds each claim/cell/series/formula/diagram assertion to unit/evidence IDs.

## Implementation sequence

1. Prefer explicit ID lookup and typed table/metric filters before approximate semantic search.
2. Add bounded lexical/embedding fallback for concept queries and record selected evidence/ranks.
3. Retrieve asset content, dimensions, captions, verified data, and adjacent explanatory passages.
4. Budget each result and retain source pointers for later expansion.
5. Collect actual per-object usage at composition and validate it instead of copying all plan IDs onto a slide.

## File map

- pipeline/retrieval.py (new)
- pipeline/slide_composer.py (existing)
- schemas/retrieval_schema.py (new)
- tools/source_lookup.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

NO_EVIDENCE is a valid result, not an invitation to invent facts. Preserve the requested query and explain the gap to the suggestion layer.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Table-only facts are retrievable with cell evidence.
- Selected assets include explanatory context.
- A slide usage trace cannot claim evidence for unsupported text.
- Edits can fetch previously unused source content without reparsing.
- Omitted retrieval items have explicit budget/relevance reasons.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: gaps are flagged and suggestions prioritize document-backed alternatives.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
