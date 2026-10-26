# F12 — Hybrid agent roles, tools, and scoped retry

Type: **Feature** · Current capability: **Partial** · Implementation: **NOT_STARTED** · Phase: **2**

Workflow references: 21, 24. Dependencies: [R01](R01_llm_gateway_reliability.md), [F09](F09_structured_retrieval.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

The current pipeline provides extraction, planning, parallel composition, and vision review. The reference PPT adds explicit deduplicator, validator, coverage critic, and a max-two scoped retry; tools are not yet a role-scoped registry.

## Objective and ownership

Follow the reference architecture without requiring a distinct model or expensive call for every role. IR1 uses extractor → deduplicator → validator → coverage critic; global planning and per-slide composition use bounded structured calls.

## Inputs, outputs, and contracts

ToolResult has SUCCESS/NO_EVIDENCE/INVALID_INPUT/FAILED, typed data, evidence IDs, warnings, usage, and version/hash. AgentTask declares permitted tools, deadlines, max attempts, context/output budget, and artifact targets.

## Implementation sequence

1. Keep parsing, arithmetic, exact dedup, source/asset membership, and geometry deterministic.
2. Add evidence lookup, table query, safe calculation AST, asset inspection, claim verification, and layout/render tools with role permissions.
3. Implement coverage critic feedback against independently tracked important items, not merely the presence of one unit per section.
4. Use scoped extraction retries capped at two when the task budget allows; do not retry terminal provider failures.
5. Persist successful role/batch/slide work, cap tool recursion/calls, and log cost/latency including failures.

## File map

- pipeline/orchestrator.py (existing)
- pipeline/knowledge_extractor.py (existing)
- tools/registry.py (new)
- pipeline/coverage_critic.py (new)
- prompts/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Degraded capabilities are explicit. Exhausted critic/repair budgets produce a reviewable incomplete artifact with exact missing items, never synthetic fallback facts.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- Roles match the reference IR1 diagram.
- A failed section does not trigger whole-document regeneration.
- A terminal provider failure cannot consume two critic retries.
- Tool results cannot fabricate source evidence or calculation values.
- Simple tasks can bypass unnecessary model calls.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- The reference slide’s max-two retry is a default proposal, configurable downward by total budget. Confirmed Q12 leaves provider selection open; configure practical capability/run budgets without assuming one model.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
