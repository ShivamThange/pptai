# F03 — User prompt, enhancement, and audience mode

Type: **Feature** · Current capability: **Missing / partial** · Implementation: **NOT_STARTED** · Phase: **1**

Workflow references: 2, 3, 10. Dependencies: [R01](R01_llm_gateway_reliability.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Lens/count flags exist for the new pipeline, but initial free-form instructions are absent; instruction is used only for edits. No editable enhanced prompt or full PresentationBrief exists.

## Objective and ownership

Give users explicit control over goals, audience, density, narrative, count, theme/layout preferences, required topics, notes, and locks. Collect audience before planning; retain an audience-independent source knowledge store.

## Inputs, outputs, and contracts

PresentationBrief stores original_prompt, enhanced_prompt, audience/mode, duration, main-content count and separate extra-slide policy, hard/soft constraints, source policy, defaults with origin, and locks. PromptCompiler returns the brief, changes/assumptions, and conflicts.

## Implementation sequence

1. Extract explicit constraints first and preserve exact numbers/quoted requirements.
2. Return editable enhancement plus structured controls without adding unsupported source claims.
3. Use separate stage system instructions and user/source payloads through R01.
4. Add initial-generation --prompt/--prompt-file/--brief; invalidate only brief-dependent caches.
5. Show count/content conflicts with concrete alternatives and keep user locks authoritative.

## File map

- schemas/brief_schema.py (new)
- pipeline/prompt_enhancer.py (new)
- prompts/ (new versioned prompts)
- frontend/brief/ (new)
- main.py (existing)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

If enhancement fails, retain the original prompt and usable structured controls, with the failure recorded. Infeasible hard constraints return choices rather than hidden changes.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Explicit constraints survive enhancement.
- User can edit the enhanced prompt or controls before Send.
- Audience changes create different suitable flows without reparsing documents.
- Document text cannot override system grounding rules.
- Defaults and the exact used prompt version are visible and recorded.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed: gaps are flagged, not filled as facts. Confirmed Q09/Q10: Preserve exact main-content count; cover/conclusion/appendix are separate extras. Show main and total counts explicitly.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
