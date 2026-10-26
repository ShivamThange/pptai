# References, authority, and evidence locations

## Planning authority

1. Current human instructions and confirmed answers in DECISIONS.
2. PROJECT_CONTEXT and WORKFLOW_CROSSCHECK for shared product/contract meaning.
3. The selected single module document for implementation details.
4. CURRENT_STATE/MODULE_STATUS for observed capabilities and verified progress.
5. BASE_PLAN for the preserved audit, original roadmap, sample deck findings, and deeper architecture/research rationale.

Existing plan files are references, not independent current-state guarantees. Resolve conflicts explicitly; do not use an older note to override confirmed workflow decisions.

## Local sources

- Original base plan: `C:/Users/thang/Projects/PPTAI/docs/PPTAI_Implementation_Plan_2026-10-08.md` (copied byte-for-byte to BASE_PLAN.md; hash recorded in modules.json).
- Superseded `MULTI_AGENT_MERGE_PLAN/` guides were removed during the 9 October 2026 repository cleanup. Their historical versions remain in Git; the current module package and preserved BASE_PLAN provide development context.
- Earlier evaluator specification: `C:/Users/thang/Projects/PPTAI/docs/PPT_Evaluator_Addon_Implementation_Plan/`, especially docs/04_METRICS_SPECIFICATION.md and docs/10_HUMAN_EVALUATION_PROTOCOL.md. Their silent weight-renormalization/source-derived-reference suggestions require the corrections in F19.
- Reference decks read from origin/hardik-pptxgenjs e534ff1: `BTP Sem 5.pptx`, `Hardik BTP.pptx`. Audit copies/extracted text/images live under `C:/Users/thang/Projects/PPTAI/audit-artifacts/reference-decks/`.
- Code/test/render evidence: `C:/Users/thang/Projects/PPTAI/audit-artifacts/`, detailed in CURRENT_STATE and BASE_PLAN.

## Primary technical/research references carried from the base plan

- [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/) and [enrichments](https://docling-project.github.io/docling/usage/enrichments/).
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs).
- [PptxGenJS tables](https://gitbrent.github.io/PptxGenJS/docs/api-tables.html) and [images](https://gitbrent.github.io/PptxGenJS/docs/api-images/).
- [MathJax SVG math output](https://docs.mathjax.org/en/latest/output/svg.html).
- [PPTAgent/PPTEval](https://arxiv.org/abs/2501.03936), [PresentBench](https://arxiv.org/abs/2603.07244), [PPTBench](https://arxiv.org/abs/2512.02624), [RAGAs](https://aclanthology.org/2024.eacl-demo.16/), [AlignScore](https://aclanthology.org/2023.acl-long.634/).

Capabilities mentioned in external references need local version/fixture checks. The six formal metric definitions and product-specific release targets are proposed engineering specifications; do not attribute a custom formula/threshold to a paper unless that paper actually defines it.
