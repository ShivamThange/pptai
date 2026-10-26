# R04 — Geometry and final-artifact quality gate repair

Type: **Repair** · Current capability: **Repaired geometry and artifact-bound gates** · Implementation: **VERIFIED (R04 scope)** · Phase: **0**

Workflow references: 11, 23a, 25, 26, 28. Dependencies: None.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Historical baseline before R04

The overlap expression suppresses nearly all text-pair overlaps. Native extraction misses table fonts/chart data/grouped objects. Repaired content is not rerendered for the final visual judgment, and PASSED can coexist with an earlier failed/unavailable audit.

## Verified implementation — 9 October 2026

The selected `--pipeline multi-agent` path now uses QualityReport schema 2 with SHA-256/revision binding, independent deterministic/factual/rendered/optional-judge check states, and BLOCKED/DRAFT_INCOMPLETE/BASIC_CHECKED/VERIFIED readiness. A legacy quality report is explicitly rechecked; it cannot grant bound approval. Native extraction recurses through scaled/nested groups, keeps line/list boundaries, cell fonts/styles, category labels and chart values. Unknown inherited fonts are recorded. Rotated/flipped group transforms are explicitly incomplete rather than silently certified.

Overlaps use declared container membership, backgrounds behind content, and actual connector endpoints/segments. Identical text boxes fail. Renderer-owned text roles have floors: title/stat 24pt, body 14pt, table/chart labels/diagram 12pt, caption/labels 10pt; evaluator visual configuration can override role floors. Required small fonts, out-of-bounds objects, suspicious overlaps, measured text overflow and rejected/contradicted facts block readiness independently of average scores.

Every final candidate, accepted repair and edit receives a new native render. A bounded worker isolates COM failures and exports from short temporary paths to accommodate Windows Office limits. PPTX/image hashes, slide counts and image validity are checked; partial exports and stale render hashes fail to run. PowerPoint text-bound measurements are separate from approximate native geometry and optional visual judgments. Accepted final reports/manifests use the final artifact; failed repair/edit leaves the previous PPTX/IR2/quality report intact. Full atomic revision publication remains R05.

Basic source checks always apply; deep verification being off cannot produce VERIFIED. Failed/disabled factual judging does not yield a complete evaluator aggregate; available-metric diagnostics remain separately labeled. A failed judge retains completed independent findings, including a contradiction discovered before a later failure.

- Final automated suite: **177 passed**, including **33 R04 cases**. CLI help, compilation and `git diff --check` pass.
- A golden source fixture uses real validation/build/repair routing/PowerPoint COM: a 90pt overflowing heading is repaired to 32pt without changing its words, rerendered, and reported as BASIC_CHECKED with optional judging off. A separate visibly clipped required-content deck is BLOCKED. Final artifact SHA-256: `a4580ea9039a8b6b0bb702ff2be66c6b09ac2f5f7d50b1fd6fa4debd068d9332`.
- Earlier actual OpenRouter audits passed on initial/repaired image sets; native bounds still blocked the oversized initial heading. The final live recheck returned terminal HTTP 402 billing; it correctly records FAILED_TO_RUN/DRAFT_INCOMPLETE rather than success. No fully verified final live deck is claimed.
- Base commit: `24e8a3a1d8e9a2684348194ae4149a2c8c263107`, uncommitted `multi-agent` changes. Source bundle SHA-256: `3bb38da464ea03eb8320c2e99085412aff8d663a0c819159ab2ebb2761884ef5`. Per-file/artifact hashes, reproduction scripts, successful/failed live evidence and limits are in `C:/Users/thang/Projects/PPTAI/audit-artifacts/r04/verification.json`.

Limits: axis-aligned geometry is approximate; some inherited fonts remain unknown; COM measures overflow outside allocated boxes and is not a complete pixel/OCR detector. Optional judges are probabilistic. LibreOffice fallback, live Gemini, the full uploaded-document benchmark and full F19 metric redesign remain unrun. Golden extraction/composition content is a fixture, not a live content-generation benchmark.

## Objective and ownership

Make quality results correspond to the exact final file. Own detection and readiness policy, while R05 owns atomic revision publication and F13 owns proactive layout solving.

## Inputs, outputs, and contracts

QualityReport contains artifact_hash, revision_id, deterministic findings, factual completeness, rendered checks, optional judge status, and readiness. Separate FAILED_TO_RUN, NOT_EVALUATED, EVALUATED_FAIL, and EVALUATED_PASS.

## Implementation sequence

1. Replace width-based overlap exclusions with explicit container/background/connector relationships.
2. Recursively inspect native objects, cell styles, chart data, and text roles; preserve line/list boundaries.
3. Render after every accepted repair and associate judgments with that artifact hash.
4. Apply role-specific readability floors and distinguish approximate geometry checks from rendered clipping/legibility checks.
5. Do not average critical factual or geometric failures away; optional verification being off yields basic-checked status, not fully verified status.

## File map

- evalute/metrics/visual.py (existing)
- evalute/extract/pptx_extractor.py (existing)
- pipeline/quality_controller.py (existing)
- pipeline/orchestrator.py (existing)
- pipeline/slide_renderer.py (existing)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Publish a draft with specific incomplete checks when permitted. Preserve the previous valid revision if repair/render fails. Never export a structurally broken file as successful.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Identical text boxes are detected; declared text-inside-card containment is allowed.
- Small table cell fonts are included in findings.
- A repaired deck receives a new render and final audit hash.
- Unavailable judging cannot masquerade as a completed factual assessment.
- Critical contradictions and clipped required content fail readiness.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q07: keep the six metrics with detailed corrected mathematical definitions in F19.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
