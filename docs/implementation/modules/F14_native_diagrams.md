# F14 — Mermaid graph to editable PowerPoint diagrams

Type: **Feature** · Current capability: **Partial native shapes; missing Mermaid path** · Implementation: **NOT_STARTED** · Phase: **3**

Workflow references: 6, 17, 21, 28. Dependencies: [F13](F13_dynamic_geometry_and_layout.md), [R06](R06_renderer_branch_integration.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

R06 provides native node/edge/process shapes and attached connectors on both Python and PptxGenJS adapters through the shared scene contract. Mermaid parsing, graph validation beyond the current contract, Dagre layout, and the full F14 workflow remain unimplemented. The reference decks propose Mermaid → graph → Dagre layout → native PPTX shapes.

## Objective and ownership

Implement that graph-first diagram path as its own module. Preserve native nodes/connectors so layout or label edits can avoid an LLM call. Do not claim academic novelty without a separate literature study.

## Inputs, outputs, and contracts

DiagramGraph contains stable node/edge IDs, labels, source-linked assertions, direction, groups, and layout hints. A bounded Mermaid subset parses into this graph; Dagre produces geometry translated into scene objects.

## Implementation sequence

1. Define supported Mermaid flowchart/architecture graph syntax, including bounded groups/subgraphs and reject unsupported directives explicitly.
2. Prefer structured graph output from the model; accept Mermaid via a validated parser/adapter.
3. Validate node/edge references and source-backed relationship labels.
4. Use Dagre for initial layout; generate native shapes/connectors and preserve graph IDs in revision metadata.
5. Allow deterministic relabel/recolor/reposition and rerun geometry checks without regenerating source facts.

## File map

- schemas/diagram_schema.py (new)
- tools/diagram_graph.py (new)
- renderers/pptxgenjs/diagram_layout.ts (new)
- renderers/pptxgenjs/native_diagram.ts (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Use the existing structured process/nodes renderer for a supported fallback. A source figure can remain a figure when reconstruction would be unreliable; label editability accurately.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- A source-backed flowchart exports as editable shapes/connectors.
- Unsupported syntax returns an actionable limitation.
- No edge references a missing node.
- Small native edits require no LLM call.
- Long labels and crossing connectors are checked in final rendering.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q14: native flowcharts and architecture graphs. Sequence diagrams and mind maps are later scope.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
