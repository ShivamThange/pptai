# R03 — Numeric and claim grounding repair

Type: **Repair** · Current capability: **Repaired within R03 scope** · Implementation: **VERIFIED (grounding repair scope)** · Phase: **0**

Workflow references: 8, 9, 16, 26. Dependencies: [R02](R02_provenance_and_assets_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Implemented on 9 October 2026 in the existing opt-in multi-agent path. Mandatory checks resolve exact excerpts/cells/captions, validate source identity, bind numeric values to clause labels/units/periods, recompute derived values from validated operands, and reject unaligned/false comparisons. Titles, captions, stats, charts, text, diagrams and unbound tables receive visible-claim numeric checks during composition, bounded repair, editing and resume compilation. Source-bound tables continue through the R02 registry gate.

IR1 schema 3 stores separate citation/numeric/semantic results, MetricFact precision and calculation traces, source coverage, important rejected units, and completeness. The old `validation_status=VALIDATED` eligibility marker remains for consumers; `validation.status=BASIC_CHECKED` does **not** mean full entailment. Confidence is unset rather than invented. Diagnostics remain in `knowledge_validation_report.json`; rejected units stay outside the factual pool. Coverage tracks source blocks, source numeric mentions, table cells and extracted important rejected units. Scoped retries retain successful units and receive validation feedback. Exhaustive semantic concept coverage remains F05/F07 scope.

`--pipeline multi-agent` explicitly selects the repaired path. Basic checks always run. `--deep-verification` optionally enables evidence-scoped IR1 batches and per-slide claim judging; `--semantic-batch-size` controls IR1 batches. Missing judge capacity remains UNKNOWN/BASIC_CHECKED, completed independent judgments survive another batch failure, and terminal provider failures stop further IR1 judging. Visible judgments survive revalidation only when claim/evidence hashes match. LLM output uses SlideDraft; grounding metadata is assigned locally.

Existing schema-2 artifacts require the explicit `migrate_ir1_v2(value, raw)` adapter and revalidation. Editing writes a separate `ir1_r03_adapted.json`, preserves the original IR1, and refuses incomplete/rejected legacy knowledge. Generation cache fingerprints include the new contract, prompts, verification configuration and retry policy. No second fact store or pipeline was introduced.

## Verification evidence — 9 October 2026

- `python -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp .pytest_tmp/r03-release-verification-final`: **144 passed** (59 R03 cases plus 85 existing regressions). CLI help and `git diff --check` pass.
- Actual source-fixture validation rejects the profit/revenue swap. Its checked facts build a native PPTX, reopen with python-pptx, preserve value/unit/period text, and render through PowerPoint COM. The rendered page was inspected. PPTX SHA-256: `16ba25f9e1cbf66d5bfcda0f5155115d0f53f889862d8f5adf45da7a60cfc8b4`.
- Actual OpenRouter probes distinguish supported versus contradicted offline-operation claims; unsupported evaluative performance remains UNKNOWN. The final live generation completes IR1 validation and storyboard, then correctly blocks an invented 20% margin without validated operands and an incompletely bound repair. This is rejection evidence, **not** a successful final live LLM deck. Earlier schema/ID failures are preserved.
- Base commit: `24e8a3a1d8e9a2684348194ae4149a2c8c263107`; uncommitted changes. Final source bundle SHA-256: `739fea541fe8bd5916d64b4f22b79cf38a973c8d866054039a42ecc68f96a27b`. Per-file source/artifact hashes, test logs, reproduction scripts, live attempts and limitations: `C:/Users/thang/Projects/PPTAI/audit-artifacts/r03/verification.json`.
- Numeric matching is conservative: ambiguous labels, implicit units/periods, rounding and noncanonical notation can require clearer evidence/review. Semantic judging is probabilistic; an exploratory judge incorrectly accepted an evaluative title before prompt calibration. Neither baseline success nor optional judging certifies exhaustive semantic coverage. Live Gemini, the full uploaded-document benchmark, expanded formats and F19 evaluator integration were not run for R03.

## Objective and ownership

Reject demonstrated hallucination cases and distinguish evidence existence from factual entailment. This repair is the mandatory foundation of optional deeper verification in F06.

## Inputs, outputs, and contracts

MetricFact = subject + measure + value + unit + period + source precision + EvidenceRef; ValidationResult separates citation_exists, numeric_binding, semantic_support, status, and reason. Derived values store operand refs and a calculation trace.

## Implementation sequence

1. Validate source excerpt/cell identity and bind metric values to their subject/unit/period.
2. Check comparisons and calculations against aligned source metrics; include title/caption claims.
3. Replace blanket confidence 1.0 with explicit checked/unknown states.
4. Track rejected/missing important items per unit rather than treating one accepted unit as complete section coverage.
5. Batch evidence-scoped semantic checks when enabled; preserve completed judgments if another batch fails.

## File map

- pipeline/knowledge_extractor.py (existing)
- pipeline/slide_composer.py (existing)
- schemas/ir1_schema.py (existing)
- tools/claim_verification.py (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Keep rejected findings available for diagnostics but outside the factual content pool. Missing judge capacity produces unknown judgments and an honest completeness status.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Profit=10 against Revenue=10, Profit=2 is rejected.
- A cross-period or wrong-unit comparison is rejected.
- Table-only facts have valid cell evidence.
- Unknown semantic support is never labeled fully verified.
- Missing critical units trigger scoped coverage repair.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: basic citation/numeric checks always run; deeper verification is optional.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
