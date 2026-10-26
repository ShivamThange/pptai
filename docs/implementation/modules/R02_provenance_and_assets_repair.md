# R02 — Existing provenance, captions, and asset binding repair

Type: **Repair** · Current capability: **Repaired provenance and bindings** · Implementation: **VERIFIED (R02 scope)** · Phase: **0**

Workflow references: 6, 8, 16, 17. Dependencies: None.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

The original audit found all seven sample assets without source references, all three image captions empty, unknown image IDs accepted, and table fallback dependent on global directories and mismatched shapes. These defects are repaired in the current uncommitted multi-agent implementation.

Verified on 8 October 2026: **85 tests passed**; the actual PDF now retains 4 tables, 3 captioned figure assets, and 6 formula crops with source/hash/location metadata. A nondefault run registry compiled a 13-slide deck that reopened with native cell values/units intact and rendered all slides in PowerPoint COM. The left Figure 2 panel uses a recorded shared-panel geometry inference over the genuine source caption; ambiguous associations remain unknown. See CURRENT_STATE and `C:/Users/thang/Projects/PPTAI/audit-artifacts/r02/verification.json` for exact source/artifact hashes and limitations. This verifies provenance and binding, not visual polish, OCR/semantic correctness, native formula reconstruction, or expanded input formats.

## Objective and ownership

Repair the existing source chain without waiting for rich format expansion. Own accurate provenance and asset resolution on the current parser/composer/builder interfaces.

## Inputs, outputs, and contracts

AssetRegistry entries contain document_id, asset_id, kind, source references, path/hash, dimensions, caption references, and typed table data. EvidenceRef identifies actual source items; paths resolve within the active run.

## Implementation sequence

1. Read captions and image data using the installed Docling item APIs; preserve every usable source location rather than only a first provenance entry.
2. Normalize existing table files to one headers/rows/cells format and populate source-cell references.
3. Validate asset IDs, kind, existence, and source membership during composition and preflight, including formulas.
4. Resolve all assets from the run registry; replace swallowed required-asset failures with explicit findings.
5. Retain original evidence hashes/captions through the legacy evaluator projection.

## File map

- pipeline/stage1_docling_parser.py (existing)
- pipeline/source_adapter.py (existing)
- pipeline/slide_composer.py (existing)
- core/builder.py (existing)
- schemas/raw_extraction_schema.py (existing)
- core/asset_registry.py (new shared binding/preflight owner)
- schemas/ir1_schema.py and schemas/ir2_content_schema.py (metadata projection and registry-ID contract)
- pipeline/knowledge_extractor.py, pipeline/orchestrator.py, pipeline/slide_editor.py (preservation and registry wiring)
- config/ppt_default_layouts.json (verified formula images in existing image regions)
- tests/test_provenance_assets.py (installed-Docling fixtures and binding counterexamples)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

An optional decorative asset may be omitted with a recorded reason; missing required evidence remains a failure. Existing artifacts use a versioned adapter, not guessed source references.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- The sample figures have correct captions and document/page provenance.
- Unknown and wrong-kind assets fail preflight.
- Tables load from a nondefault output directory and preserve cell values/units.
- Cross-document block IDs cannot collide.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: document-backed suggestions and mandatory baseline provenance. No source references may be fabricated to satisfy a schema.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
