# Branch strategy and incorporation decision

## Decision

Continue implementation from **multi-agent**, originally selected at 24e8a3a. The 9 October 2026 cleanup prepares this branch for the user's intended promotion to main and subsequent feature development. Multi-agent is now the only supported CLI generation path; the replaced one-shot planners and limiter are removed. The checkout remains on multi-agent; no commit, merge, push, or branch switch was performed by the cleanup. See REPOSITORY_CLEANUP.md for retained tools, pending work, and verification.

Reasons: this branch already owns typed canonical IR1, strict IR2 unions, retrieval scopes, storyboard, parallel slide composition, resume/editing artifacts, native Python objects, and the inherited evaluator. Its defects are concrete repair targets rather than a reason to replace its architecture.

## Incorporate other work

| Source | Incorporate | Exclude / rebuild | Owner module |
|---|---|---|---|
| evalute-pipeline | Existing evaluator/report/test scaffold, already inherited | Weak reference/metric extraction, silent backend substitution, missing-evaluation aggregation | F19, R03, R04 |
| main | Extractor/dedup/validator/critic responsibilities and graph-index/retrieval concepts where measurable | Truncated source extraction, unused graph plumbing, invented topic statistics, double throttling, blanket critic success | F08, F09, F12 |
| hardik-pptxgenjs e534ff1 | JS renderer adapter, theme/master/native object support, reference-deck workflow, Mermaid graph-first intent | Older semantic/planner pipeline, hardcoded output/model choices, fixed-only geometry, placeholder assets, dense-content requirements | R06, F13, F14 |

PptxGenJS is the intended improved renderer, conditional on compatibility and native editability acceptance. Keep Python behind the same renderer contract during migration; it is not a parallel generation/fact pipeline.

## Git and implementation sequence

1. Repair reliability/provenance/grounding/gates/revisions on the chosen base, with focused changes and evidence.
2. Define shared contracts and adapt the JS renderer with a passing PowerPoint table fixture.
3. Implement brief/context/IR1/retrieval/narrative/content/scene modules incrementally using the dependency table.
4. Wire the shared service/UI/edit/history/export; expand academic evaluation alongside these stages.

hardik-pptxgenjs has no merge base with multi-agent. Port selected files with recorded source commit instead of an unrelated-history merge. Do not overwrite schemas/orchestration/requirements wholesale. Existing evalute-pipeline is already an ancestor and needs no new merge. Review main changes by functional responsibility rather than copying its full runtime.

Future implementation branches should be based on the selected multi-agent commit/current agreed integration branch and named for the module being worked on. Determine the actual branch workflow from current user/repository instructions when code work starts; this document does not authorize pushing or merging changes.

## Promotion checks

Before making a renderer/pipeline default, require passing contract/counterexample tests, actual native opening/rendering, evidence-preserving edits/resume, dependency install checks, benchmark completeness, and a final-artifact quality report. Refetch and compare commits before importing additional branch work; CURRENT_STATE is a snapshot, not a permanently current remote inventory.
