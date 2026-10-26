# Implementation roadmap

The user requested no implementation timeline planning. Work is organized by dependencies and demonstrable outcomes, without week estimates or a deadline. The LLM/provider is undecided; interfaces and budgets stay capability-driven/configurable. Measure runtime/cost as evaluation diagnostics rather than assuming a chosen provider or delivery schedule.

| Phase | Modules / work | Demonstrable exit |
|---|---|---|
| 0 — Reliable foundation | R01–R05; independent baseline claims/render fixtures; metric calibration preparation | Counterexamples rejected, failures honest, edits/cache/revisions safe, current test failure fixed |
| 1 — Service, brief, intake, budgets | R06, F01–F03, F07 | Confirmed file types upload, enhanced prompt/audience controls work, complete-source coverage is tracked, renderer table fixture opens |
| 2 — Rich evidence and IR1 chain | F04–F06, F08–F09, F12 | Multimodal evidence, dedup/validator/critic, structured retrieval and scoped retries preserve source truth |
| 3 — Dynamic presentation construction | F10–F14 | Source produces audience-specific flows, editing reserve, dynamic bento/figure/chart layouts, editable native diagrams |
| 4 — Product editing/export/evaluation | F15–F19 | Draft + suggestions, chat/layout edits, V history, PPTX/PDF, six mathematically defined metric reports |
| 5 — Later conflict handling / further scope | F20 | Conflicts shown with both sources and explicit decisions; full resolution remains deferred initially |

Phases express dependency order, not calendar duration. Benchmark/reference preparation starts alongside the foundation; final study execution uses the resulting checked artifacts.

## First vertical slice

Use the supplied paper and a small DOCX/table fixture. Demonstrate upload + prompt/audience → evidence-linked IR1 → two audience-specific storyboards → one draft → bento/figure-led alternatives → scoped chat edit → V2 → matching PPTX/PDF. Show source-backed suggestions, known gaps, context coverage, and truthful evaluation completeness. Start with a small tested layout grammar and expand after it works.

## Integration boundaries

- Implement one selected module at a time with shared contract changes reviewed against dependents.
- Preserve current behavior through explicit legacy adapters where compatible; do not preserve known false-success checks.
- Import renderer/reference ideas from other branches through R06/F12/F14/F19 ownership.
- Keep actual branch promotion/push/merge decisions separate from this documentation task.
- Capture same-input before/after renders and relevant metric results for every visual/factual change. Avoid claiming general improvement from one showcase case.
