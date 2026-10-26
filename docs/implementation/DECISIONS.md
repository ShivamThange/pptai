# User decisions and open validation questions

Confirmed answers were received directly in this chat, beginning on 8 October 2026; later confirmations are dated below. Proposed defaults are labeled; elapsed time is not agreement. This file is the authority for answer status across module docs.

| ID | Decision | Status | Applies to |
|---|---|---|---|
| Q01 | Separate feature module with one single implementation document; not one distinct AI model per feature | CONFIRMED | All |
| Q02 | Flag unsupported gaps and offer clearly labeled suggestions | CONFIRMED | F03, F09, F11, F15, F16 |
| Q03 | First UI uses chat edits plus layout/content controls | CONFIRMED | F15–F17 |
| Q04 | Basic citation/numeric checks always; deeper claim/figure verification optional | CONFIRMED | R03, F05, F06 |
| Q05 | First-release formats: PDF, DOCX, TXT/Markdown, CSV/XLSX, PNG/JPEG | CONFIRMED | F02, F04 |
| Q06 | Suggestions prioritize unused source-backed content; unsupported ideas are labeled as gaps | CONFIRMED | F11, F15 |
| Q07 | Keep all six metrics and devise a detailed mathematically sound implementation | CONFIRMED | F19, R04 |
| Q08 | Local Windows demo first; keep the API portable | CONFIRMED | F01, R06, F18 |
| Q09 | Preserve exact main-content slide count and show notes/shorter-content alternatives | CONFIRMED | F03, F10, F13 |
| Q10 | Count main content only; cover/conclusion/appendix are separate extras | CONFIRMED | F03, F10, F13, F19 |
| Q11 | Expected upload scale, pages/files/scans/workbooks | ASKED / PENDING | F02, F07 |
| Q12 | LLM/provider undecided; keep configuration and capability limits provider-agnostic | CONFIRMED | R01, F07, F12 |
| Q14 | First native diagrams: flowcharts and architecture graphs | CONFIRMED | F14 |
| Q15 | Selected-slide plus deck-wide chat edits with explicit scope/locks | ASKED / PENDING | F16 |
| Q16 | Local chat/version history survives closing/reopening | ASKED / PENDING | F17 |
| Q18 | Do not plan or optimize around an implementation timeline | CONFIRMED | ROADMAP, all modules |
| Q19 | Keep F01 simple: one local job worker and a small SQLite queue; avoid production-style pause/restart orchestration, redundant restrictions, and unnecessary abstractions | CONFIRMED (2026-10-12) | F01 |
| Q20 | Unknown model capacity must use an explicitly configurable capacity with a policy switch in `.env`; no implicit hardcoded numeric fallback | CONFIRMED (2026-10-13) | R01, F07 |
| Q21 | Follow efficient API/chunking practices using official OpenAI or Anthropic documentation as references; preserve the provider-agnostic architecture | CONFIRMED (2026-10-13) | R01, F07, F09 |
| Q22 | AI must understand assets in original source context and extract results/findings/semantic meaning so supported asset-derived knowledge influences final PPT text/narrative beyond image-caption linkage | CONFIRMED (2026-10-13) | F04, F05, F09, F10, F11 |
| Q23 | Disable strict verbatim evidence substring matching (`validate_supplied_evidence`) by default via `VALIDATE_SUPPLIED_EVIDENCE=false`; rely on `validate_claim` for claim and numeric grounding | CONFIRMED (2026-10-24) | F07 |
| Q24 | Disable strict localized fragment-level grounding aborts (`FRAGMENT_GROUNDING_FAILED`) by default via `VALIDATE_FRAGMENT_GROUNDING=false`; rely on canonical document-level `validate_knowledge_units` gate | CONFIRMED (2026-10-24) | F07 |
| Q25 | Make 100% section/numeric coverage strictness configurable via `STRICT_SECTION_COVERAGE` (default `true`, configurable to `false` in `.env` or `--no-strict-section-coverage`). When `false`, incomplete sections record warnings and `ir1.completeness="INCOMPLETE"` without halting deck generation | CONFIRMED (2026-10-24) | F07, R03 |

## Further feature-level questions (not yet answered)

These questions support progressive implementation discussions. Do not repeatedly ask confirmed questions. Raise the next small relevant batch when implementing the affected module, while progressing independent work.

- **Q13 dedup visibility:** Show ambiguous duplicates only in an advanced review view? Proposed yes.
- **Q17 later conflicts:** Prioritize numeric disagreements, factual contradictions, or time/version differences? Full conflict resolution is explicitly deferred.

## Decisions inferred from explicit workflow or engineering ownership

- Human review is after the initial draft; an optional storyboard preview may be offered without introducing a mandatory approval step. This follows workflow 23b and is not a separate required permission.
- Audience input is consumed before selection/planning, rather than only after optional verification.
- Source geometry belongs to extraction; slide sizing belongs to the post-content layout solver.
- Complete raw content is retained. Full context is sent only if useful and within measured limits; chunking/retrieval preserves source coverage.
- Branch decision: multi-agent base with selective PptxGenJS/reference-deck adaptation. This is the requested engineering recommendation; no code merge was performed.

## Change log

- 2026-10-24: Q25 confirmed making section/numeric coverage strictness configurable via `STRICT_SECTION_COVERAGE`. When set to `false`, incomplete sections (e.g. dense hyperparameter sets or partial table-cell extractions) record warnings and mark `completeness="INCOMPLETE"`, allowing presentation generation to proceed with available accepted units rather than raising a terminal `ValueError`.
- 2026-10-24: Q24 confirmed disabling strict localized fragment grounding aborts (`FRAGMENT_GROUNDING_FAILED`) by default via `VALIDATE_FRAGMENT_GROUNDING=false`. Extracted units proceed downstream to the canonical document-level `validate_knowledge_units` gate, where valid units are accepted into the storyboard and ungrounded units are logged as rejected candidates.
- 2026-10-24: Q23 confirmed disabling strict verbatim evidence substring validation (`validate_supplied_evidence`) by default via `VALIDATE_SUPPLIED_EVIDENCE=false` to prevent false-positive `UNSUPPLIED_EVIDENCE` extraction aborts resulting from minor LLM whitespace or quote adjustments. Factual and numeric grounding remain strictly enforced by `tools/claim_verification.py:validate_claim`.

- 2026-10-13: Q22 confirms contextual AI asset understanding and findings affecting final slide text even when the visual is omitted. F04 replaces optional-description-only scope with default structured-mode interpretation, atomic source-grounded insights, eligibility/coverage and required knowledge-to-text acceptance. Numeric provenance and optional deep verification rules remain. Documentation only; implementation statuses unchanged.

- 2026-10-08: recorded Q01–Q06 answers; issued Q07–Q09; created modular docs and workflow cross-check from the preserved base plan and both newly available decks.

- 2026-10-08: Q07–Q09 confirmed; requested detailed six-metric mathematics, Windows-first portable service, and strict exact-count behavior. Q10/Q14 and deadline/provider/budget questions issued next.

- 2026-10-08: Q10 confirmed as main-content-only count; extras separate. Q14 confirmed as flowcharts plus architecture graphs. Provider is undecided and implementation timeline planning is explicitly out of scope. Per-run safety/capability settings remain configurable; runtime/cost is measured. F19 now contains detailed formulas, edge cases, calibration, and property tests.

- 2026-10-08: provider undecided; calendar estimates removed from authoritative roadmap. Q15/Q16/Q11 issued for edit scope, durable local history, and expected input scale.

- 2026-10-13: Q20 confirmed configurable unknown capacity with the switch in `.env`; F07 now requires explicit configuration instead of an implicit 32,768-token fallback. Q21 confirmed official API/chunking references. F07 documents complete-request counting/estimate certainty, token overlap, stable prompt prefixes, cache accounting, grounded long-context structure and bounded quota/retry handling. These are plan refinements, not implemented runtime behavior.
