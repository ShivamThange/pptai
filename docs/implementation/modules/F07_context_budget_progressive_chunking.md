# F07 — Context budgets, complete coverage, and progressive chunking

Type: **Feature / repair** · Current capability: **Implemented within recorded local scope** · Implementation: **VERIFIED (F07 local scope)** · Phase: **1**

Workflow references: 12, 13, 14, 19. Dependencies: [R01](R01_llm_gateway_reliability.md), [R02](R02_provenance_and_assets_repair.md), [F02](F02_uploads_and_docling_routing.md). Integration also uses implemented R03 grounding, R05 checkpoints/revisions, and the F01 service; later F05/F09/F10 schemas are not prerequisites for the initial F07 implementation.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), [decisions](../DECISIONS.md), and [workflow cross-check](../WORKFLOW_CROSSCHECK.md) first. This is the single implementation document for this module. Contracts, algorithms and tests below describe the module requirements; shipped scope and verification limits are recorded in the runtime evidence below and CURRENT_STATE. Unknown-capacity configuration and use of official API practices were confirmed by the user on 13 October 2026; other numeric defaults remain engineering proposals.

## Runtime implementation — 13 October 2026

Prepared-request admission, explicit capacities, progressive source/topic projections, separate context accounting, bounded stage calls, checkpoints and immutable revision integration are implemented on `multi-agent` base `6c9c8c1d81fb35591ac810b73f73dd5bcf845c65` with uncommitted changes. **404 full-suite tests and 42 focused F07 cases pass**. Real mixed-source parsing and native PowerPoint generation/edit/resume pass on Python and PptxGenJS, using typed model fixtures and BASIC_CHECKED readiness. Configured live generation probes returned OpenRouter 404 and Gemini 503; usage calibration and live source/media certification are unavailable. See [CURRENT_STATE](../CURRENT_STATE.md) for exact scope/limits and `C:/Users/thang/Projects/PPTAI/audit-artifacts/f07/verification.json` for commands, source/native/coverage hashes and reproduction evidence. The audited baseline below is historical; it describes the pre-implementation gaps.

## 1. Audited implementation baseline

Audited on **13 October 2026** against the current `multi-agent` working tree, HEAD `2fa462dbc775ebba6868e1df5fc08196783549cb`, including uncommitted F02 changes. Preserve those changes. Paths resolve under `C:/Users/thang/Projects/PPTAI/BTPs5`.

| Current extension point | Observed behavior | Required change |
|---|---|---|
| `knowledge_extractor.py::_section_batches` | Counts `len(block.text) + 80` against a 24,000-character default. A single oversized block is still admitted. | Fragment source against complete requests and subdivide oversized blocks. |
| `_assets_for_section` / `_extract_section_batch` | Sends all section assets, including table data, with every block batch; these are outside the text budget. | Schedule related asset projections and asset-only batches, accounting for their size. |
| `chunker.py::build_chunks` | Estimates unit JSON as characters/4, groups by first section component, merges sparse groups without checking the merged size, and attaches assets using the surviving section label. F02 prevents some cross-document merges. | Preserve document/full-section membership, union refs, and remeasure each merge. |
| `llm_client.py::_generate_structured_contents` | Estimates text/system/schema using UTF-8 bytes plus 64, or accepts a caller estimate; multimodal counts otherwise remain unknown. Capacity checks run only when capacity is configured. Envelopes are assembled later. | Count and dispatch one prepared request; explicitly handle unknown limits/media counts. |
| `config/settings.py` | Already owns `ProviderCapabilities`, `TaskBudget`, output reserves, deadlines, retries and optional `LLM_CONTEXT_TOKENS`. | Extend those contracts; keep one provider client and limiter. |
| `knowledge_extractor.coverage_ledger` / `ValidatedIR1.coverage` | R03 tracks factual/numeric gaps for non-heading blocks and numeric table cells, without recording per-request spans or asset representations. | Retain semantic coverage and add separate context accounting. |
| Planning/composition/edit/judge calls | Construct context independently; repairs add previous answers/feedback. Topic estimates do not guarantee final-request fit. | Preflight initial calls, repairs, judges and model overrides at the gateway. |
| `CheckpointCache`, `observe_llm_run`, `RevisionStore` | Already provide integrity-checked batch/slide caches, attempt records and immutable publication. | Extend fingerprints and include context sidecars in the same revision. |

F02 retains uploaded bytes, parser artifacts, raw-v3 collections, lexical cells and document-scoped provenance. F07 accounts for these inputs; it cannot prove that OCR/parser output captured every source fact. Textless image generation remains blocked until F04 supplies a usable interpretation path.

## 2. Objective and ownership

Preserve complete retained source while sending each stage a useful request that fits its resolved capacity. Prefer full-source extraction when input **and output** policy permit it; otherwise split progressively. Planning may use recoverable digests. Composition/edits use selected evidence. Retaining bytes, dispatching their representation and understanding their facts remain separate outcomes.

F07 owns measurement/admission, deterministic source/topic fragmentation, safe packing/merging, context coverage and checkpoints. F04 owns richer image/chart interpretation, F08 semantic deduplication, F09 retrieval ranking/search, F10 dynamic narrative/count allocation, and later modules the editing UI. Add no second fact store, pipeline, worker scheduler or mandatory approval step.

Completion requires every source obligation to be accounted for without silent truncation and every dispatched request to pass its budget. R03/F05 still own semantic completeness. F07 cannot upgrade `BASIC_CHECKED` to `VERIFIED` by counting coverage alone.

## 3. Typed contracts and interfaces

Add strict Pydantic sidecar contracts in `schemas/context_schema.py`: `extra="forbid"`, finite/nonnegative count validation and `schema_version="f07-v1"` on artifact roots. Raw-v3/IR1-v3 remain the authorities; sidecars hold refs/hashes, not another source database.

| Contract | Required fields/invariants |
|---|---|
| `StageBudget` | Stage, provider/model, profile/version, declared context/input limits if known, effective context limit and origin (`declared` / `configured_unknown`), input ceiling, output reserve, margin, optional stage cap and counter policy/version. Model overrides resolve their own profile; unknown capacity requires explicit configuration. |
| `TokenMeasurement` | Input tokens; method (`provider_count`, `local_tokenizer`, `byte_estimate`, `hybrid_estimate`); certainty (`counted`, `estimated`); counter/version; included/estimated components; request fingerprint; media/tool contribution; count latency/warnings. Unknown required contributions cannot be zero. |
| `ContextRef` | Original document/source/block/asset/item identity, full section path, representation (`text`, `cell`, `caption`, `formula_text`, `asset_metadata`, `pixels`, `digest`, `inventory`), source hash, optional original-text `[start,end)` span or original asset-cell coordinates, source locations and projection hash. Text spans use Python Unicode code-point offsets; do not reinterpret Docling `SourceLocation.charspan`. |
| `ContextChunk` | Stable ID and purpose (`extraction`, `retrieval`); ordered document/section membership; primary/context-only refs; unit/source/asset ID unions; parent/child/merge lineage; neighbor IDs; bounded digest and recoverable refs; projection hash; preparation measurement; state (`PLANNED`, `SUPERSEDED`, `COMPLETE`, `FAILED`, `CANCELLED`). Extraction chunks may be asset-only. |
| `PreparedContext` | Stage/scope, request hash, chunk IDs/refs, selected refs, omitted optional refs/reasons, resolved budget/measurement and projection version. Provider-ready contents/schema/media remain in memory; no base64 in this artifact. |
| `ContextCallRecord` | Call/attempt IDs, stage/scope, preparation hash, cache key, refs, dispatch state (`NOT_SENT`, `DISPATCH_STARTED`, `RESPONSE_RECEIVED`, `DELIVERY_UNKNOWN`), outcome (`PASSED`, `FAILED`, `CANCELLED`, `CACHE_REUSED`), observed usage if available, result hash/error code and reuse origin. |
| `CoverageLedger` | Source/collection hash, inventory, per-ref retained/processed/selected/dispatched/excluded/failed events, mapped units, historical/current-run distinction, stage totals, separate parser/context/semantic completeness. These dimensions are not mutually exclusive statuses. |

Keep `TopicChunk` and list-shaped `chunks.json` compatible initially. Rich topic membership belongs in `context_chunks.json`, keyed by the same stable chunk IDs. Existing fields (`label`, `unit_ids`, `asset_ids`, `digest`, `token_estimate`) stay available; `token_estimate` is display metadata, not admission authority. Raw extraction chunks belong in `extraction_chunks.json`, not `TopicChunk`.

Asset-only extraction does not relax `TopicChunk.unit_ids`. Assets without related validated units remain in the raw/context inventory with an explicit disposition. Attach relevant assets to same-document topic chunks only with their real section refs and measured projections; never invent a unit to satisfy a schema. F04/F05 own richer semantic handling.

```python
# core/context_budget.py — resolution, counting, admission
resolve_stage_budget(settings, capabilities, stage, model, task_budget) -> StageBudget
measure_request(prepared_request, counter) -> TokenMeasurement
assert_fits(prepared_request, stage_budget, measurement) -> None

# pipeline/chunker.py — retain build_chunks/write_chunks compatibility
plan_extraction_chunks(raw, request_factory, budget, policy) -> list[ContextChunk]
pack_context_chunks(chunks, request_factory, budget) -> list[ContextChunk]
build_chunks(ir1, *, max_tokens=1800, min_units=2, context_policy=None)

# pipeline/coverage_ledger.py — accounting, not semantic judging
initialize_ledger(raw, source_manifest) -> CoverageLedger
record_preparation(ledger, prepared_context) -> None
record_call_outcome(ledger, call_record) -> None
validate_context_coverage(raw, chunks, ledger) -> list[CoverageFinding]
```

Gateway additions: `prepare_structured_request(...)`, `prepare_multimodal_request(...)`, `generate_prepared(...)`. Existing structured/async/multimodal methods wrap them. Extend the extraction caller protocol and test callers deliberately; pure planning tests require neither live keys nor undocumented caller attributes.

## 4. Complete-request budget calculation

```text
C = effective combined context limit (declared or explicitly configured for unknown capacity)
O = TaskBudget.max_output_tokens, including profile-required reasoning allowance
S = max(512, ceil(C * margin_ratio))
I = min(C - O - S, declared_input_limit_if_present, stage_input_cap_if_present)

admit iff complete_request_input <= I
          and O <= declared_provider_output_limit and I > 0
```

Omit absent optional limits from `min`. Margin ratio: **5%** for a completely counted request, **10%** for estimated/hybrid input. Recompute after counting fallback. Preserve existing stage/batch output reserves and overrides; never lower output silently to fit more source. Profiles must state how reasoning consumes the output/context reserve; an unmodeled allowance is estimated or unsupported, never exact.

Example using a **fixture** combined limit 32,768 and output 4,096: counted margin is 1,639, so input ceiling is 27,033. Input 27,034 fails before generation transport. An explicit stage cap of 12,000 lowers that ceiling to 12,000. This is not a chosen model's capacity.

Preparation and dispatch:

1. Resolve provider, actual model, stage/output budget, capabilities, cancellation/deadline and source projection.
2. Apply `_validated_schema` once. Prepare the exact system/user content, transformed response schema, tool definitions/results/history if used, media content/dimensions/detail and generation settings that will be sent.
3. Fingerprint those model-visible inputs, settings, profile/counter versions and media hashes. Exclude credentials/auth headers, incidental paths and timestamps; preserve array order. Count and dispatch the same schema/contents object.
4. Measure and admit. Recheck fingerprint/media integrity at dispatch. Changed feedback/schema/media needs a new preparation. `TaskBudget.estimated_input_tokens` is at most a compatibility hint; it cannot bypass measured admission or override a larger count.
5. Use existing R01 limiter/deadline/retry rules. Preflight failures have `transport_started=false`. Identical transport retries reuse counts; changed application repairs are new preparations.

### Counting policy

| Method | Required behavior |
|---|---|
| Provider counter | Current direct Gemini can use `client.models.count_tokens`; prove included fields against the installed SDK. Reference APIs are OpenAI Responses `POST /v1/responses/input_tokens` and Anthropic `messages.count_tokens`. They are not interchangeable with OpenRouter/Gemini payloads, and reading their docs does not add those providers. Preserve the endpoint's own certainty: Anthropic documents its count as an estimate. Contents-only counting plus estimated schema/system/media omissions is `hybrid_estimate`. |
| Compatible local tokenizer | Require explicit versioned tokenizer/model mapping and tested framing. Unknown schema/tool/media framing leaves the whole request estimated. Never guess from a model name. |
| Text fallback | Use serialized UTF-8 byte length for each included textual component plus framing allowance (proposed default 256). Include schema/system/history/tool content once. This is pessimistic but still a provider-processing estimate; characters/4 is not a safe bound. |
| Images | Count actual media via a supported provider method or versioned model-specific estimator. Base64/URL bytes are transport size, not image tokens. Missing policy fails required media with `IMAGE_TOKEN_COUNT_UNAVAILABLE`. Configured estimates remain labeled. |
| Response usage | Store observed input/output beside preparation counts; absent usage stays unknown. It does not retrospectively make an estimate exact or prove factual use. Record discrepancies for calibration. |

Use cheap local estimation to search packing boundaries. Provider counting occurs for final candidates and is memoized by request hash within the run. A measured oversized candidate is split/repacked and counted again; avoid a network count per paragraph during boundary search. Bound count operations by deadline/cancellation. Safe count failures may fall back for text; auth/billing/cancellation remain terminal. Counting calls have separate records, not generation usage.

References checked 13 October 2026: [Gemini token counting](https://ai.google.dev/gemini-api/docs/tokens) and [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting) describe current-adapter capabilities. The official OpenAI/Anthropic practices and their application to F07 are specified in section 5.1. Prove adapter inclusion with captured-request tests.

## 5. Configuration and compatibility defaults

Extend existing settings; retain CLI > environment > repository `.env` > defaults. Capture resolved non-secret context policy in the submitted job/generation signature so subsequent environment changes do not silently alter its budget. Evaluator models resolve their own profiles through the same policy.

| Setting / option | Proposed default and behavior |
|---|---|
| Existing `LLM_CONTEXT_TOKENS` / `--llm-context-tokens` | Declared combined limit. Never infer from model name. |
| `LLM_CONTEXT_POLICY` / `--context-policy` | `progressive` after acceptance; `legacy` during migration only. Legacy still passes gateway admission and cannot claim F07 coverage. |
| `LLM_UNKNOWN_CONTEXT_POLICY` | `configured`: if capacity is undeclared, require `LLM_UNKNOWN_CONTEXT_TOKENS`. Optional `error` mode rejects unknown capacity even when a fallback value is supplied. Keep this policy switch in repository `.env`, with normal environment precedence. Neither mode guesses capacity. |
| `LLM_UNKNOWN_CONTEXT_TOKENS` | **Unset; no hardcoded numeric fallback.** Positive user-configured combined capacity, used only for an undeclared selected-model capacity under `configured` policy. Blank/missing fails `CONTEXT_CAPACITY_REQUIRED`; zero/negative/noninteger fails settings validation. Declared capacity takes precedence; configured unknown capacity is not verified provider capacity. |
| `LLM_CONTEXT_COUNT_MODE` | `auto`: supported provider counter, compatible configured local counter, then estimate. `estimate` avoids network counts. `provider_required` fails when complete supported counting is unavailable. |
| `LLM_<STAGE>_INPUT_TOKENS` | Optional input ceiling for known stage names; absent means available input ceiling. Parse separately from `LLM_<STAGE>_OUTPUT_TOKENS`; reject unknown stage/nonpositive value. |
| `IR1_SOURCE_TARGET_TOKENS` | 6,000 estimated source-projection tokens as a batching/output heuristic, not a request ceiling. Useful full-source calls may exceed it when input/output policy fits. |
| Existing `IR1_BATCH_INPUT_CHAR_BUDGET` / `--ir1-batch-char-budget` | Deprecated secondary batch-size hint; never admission authority. Explicit use enters fingerprints/diagnostics. |
| `CONTEXT_TEXT_OVERLAP_TOKENS` | 0; optional token-sized boundary context, with exact code-point spans retained. Require overlap at most half the configured source chunk target. Derive spans using a compatible tokenizer or labeled local estimate, then measure the whole request again. Remove overlap before shrinking primary coverage. |
| `CONTEXT_MAX_SPLIT_DEPTH` | 32; each split must also strictly reduce primary size. Stop earlier at indivisible evidence. |
| `LLM_RUN_MAX_GENERATION_CALLS`, `LLM_RUN_MAX_RESERVED_TOKENS` | Unset; optional positive run caps. Before each generation transport attempt reserve one call and input estimate + output reserve atomically across slide threads. Cache/preflight failures consume neither. Started attempts retain reservations, including uncertain failures; no automatic refund/replay. Exhaustion preserves checkpoints and stops. |
| `LLM_MAX_TOKENS_PER_MINUTE` | Unset; optional positive provider quota. Extend the existing shared limiter with atomic token reservations, using the profile's rate-accounting rule. Do not add a second limiter. A request too large for the configured rolling quota fails explicitly; waits/retries remain deadline/cancellation bounded. |
| `VALIDATE_SUPPLIED_EVIDENCE` | `false` by default. When `true` or `1`, enforces strict character-by-character substring checks for returned evidence excerpts against supplied fragment text/cells (raising `UNSUPPLIED_EVIDENCE`). Disabled by default to accommodate minor LLM quotation/whitespace variations while relying on `validate_claim` for factual grounding. |
| `VALIDATE_FRAGMENT_GROUNDING` | `false` by default. When `true` or `1`, enforces strict localized fragment-level grounding checks in `_progressive_extract` (raising `FRAGMENT_GROUNDING_FAILED` if any unit in a batch fails). Disabled by default so that all extracted units proceed to canonical document-level validation (`validate_knowledge_units`), where verified units are accepted and ungrounded units are cleanly separated as rejected candidates. |
| `STRICT_SECTION_COVERAGE` / `--strict-section-coverage` / `--no-strict-section-coverage` | `true` by default. When `false` or `0`, allows knowledge extraction to proceed with available accepted units even if some sections have missing numeric values or table cells, logging warnings and marking `ir1.completeness="INCOMPLETE"` without raising a terminal `ValueError`. |

Expose policy/count mode through the existing CLI/settings/service path; no new UI. Provider/model/version profile mappings supply media estimators and additional capability limits, with injectable test profiles. Do not invent a universal image-token constant.

Q11 upload scale remains pending. These tunable defaults do not establish a workload/performance SLA. F02 file/page/cell/byte limits remain independent of LLM limits.

The implementation must document these controls in a secret-free `.env.example` and README. Add an exception for `.env.example` to the existing `.env.*` ignore rule when creating that template. Preserve the user's actual `.env` credentials and existing model settings. This plan update does not modify the live `.env` or claim these future keys are already read by runtime code.

```dotenv
# F07 settings to expose when implemented:
LLM_UNKNOWN_CONTEXT_POLICY=configured
LLM_UNKNOWN_CONTEXT_TOKENS=32768
LLM_CONTEXT_COUNT_MODE=auto
CONTEXT_TEXT_OVERLAP_TOKENS=0
VALIDATE_SUPPLIED_EVIDENCE=false
VALIDATE_FRAGMENT_GROUNDING=false
STRICT_SECTION_COVERAGE=false

# LLM_CONTEXT_TOKENS=<verified selected-model combined capacity>
# takes precedence over the unknown-capacity value.
```

`32768` above is an editable example, not a code default or selected model recommendation. Resolution is declared selected-model capacity → explicit configured unknown capacity → actionable configuration error before any count/generation network call. If `LLM_UNKNOWN_CONTEXT_POLICY=error`, omit the second step. Capacity settings are resolved separately from count certainty: setting a capacity does not make an estimated request exact. Model/evaluator overrides must resolve their profiles again and record use of a shared unknown-capacity setting explicitly.

### 5.1 Official API practices applied to this pipeline

Reviewed on 13 October 2026. These sources inform the design; they do not prescribe PPTAI's coverage ledger, hierarchy, safety margins or 6,000-token extraction target. Keep those as application decisions verified by fixtures. Do not add direct OpenAI/Anthropic transports, hosted file stores or a new SDK merely to follow the practices below.

| Official guidance | F07 implementation requirement |
|---|---|
| [OpenAI input-token counting](https://developers.openai.com/api/docs/guides/token-counting) covers structured request inputs and framing; [Anthropic token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting) accepts supported message/system/tool/media input and explicitly calls its result an estimate. | Count prepared structured requests for the exact provider/model. Preserve count certainty and unsupported-component warnings; retain a margin and compare response usage. Do not reuse another model's counts or call a different vendor's counter for the current adapter. |
| [OpenAI retrieval chunking](https://developers.openai.com/api/docs/guides/retrieval#chunking) uses configurable token chunk size/overlap; its hosted indexing defaults are 800/400 tokens, with overlap no larger than half the chunk size. | Use token-sized configurable targets/overlap, retain semantic boundaries and source spans, and validate overlap. **Do not copy 800/400 into raw extraction**: indexing for search and exhaustive knowledge extraction have different output/coverage requirements. Test overlap against boundary-fact recall and duplicated input cost; F09 owns retrieval tuning. |
| [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) depends on matching rendered prefixes; [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) also reuses stable prompt prefixes with provider-specific controls. | Keep system instructions, schema/tool ordering and shared reference context stable. Put changing chunk content/query/repair feedback after stable content. Do not insert timestamps/random IDs into the reusable prefix or pad prompts just to reach caching thresholds. Enable explicit cache controls only through a supported profile and measure observed hits/latency. |
| [Anthropic long-context prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#long-context-prompting) recommends clearly separated document/source metadata, long source content before the final query, and grounding answers in quotes. | Keep authoritative instructions in the system role. In user content serialize source/document/fragment metadata before the final task/edit/feedback suffix. Existing structured JSON can provide these boundaries; XML is optional and must escape source content. Require verbatim evidence in the same typed extraction response, without adding a separate quote-extraction LLM round trip. |
| [OpenAI rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits) covers request/token quotas and bounded retry with server delay or exponential backoff/jitter. | Extend R01's shared limiter rather than double-throttling. Honor valid `Retry-After` as a minimum plus jitter; stop if it cannot fit the remaining operation deadline. Disable SDK retry multiplication. Quota/billing/auth errors need action, not chunk splitting. |

Provider prompt-cache hits still dispatch a request and consume context-window space. They are different from R05 result-cache hits, which skip generation. Normalize observed usage per adapter: for Anthropic, total input includes ordinary input plus cache-read/cache-creation input; for OpenAI, cache detail counters must not be added again to already-total input. Preserve raw provider usage and unknown fields. No cached token is subtracted from capacity simply because it is cheaper.

Keep the existing interactive F01 worker/concurrency limit; independently process/checkpoint chunk results and combine them deterministically in source order. Small chunks are not automatically efficient: measure call count, repeated-header/overlap tokens, token-counter calls, cache hits and latency. Prefer the largest coherent batches that satisfy input/output/coverage policy. If one final measured candidate needs subdivision, count only its new candidates, not every tested boundary.

Compaction may shorten optional planning/edit-history context with recoverable references. It cannot replace original source evidence, discharge extraction obligations, or enable automatic source truncation. Application source splitting and provider conversation compaction remain separate mechanisms.

## 6. Progressive source and topic chunking

### 6.1 Inventory, full context, and hierarchy

1. Start with validated F02 source/collection metadata and `RawExtraction`. Inventory blocks, assets, source items, cells, caption links and retained parser-only inventories. Keep document identities and source order; matching section titles in different documents never imply shared scope.
2. Link duplicate projections to one source obligation only when actual refs/locations establish identity (CSV cell blocks/table views, for example). Empty cells, headers and unsupported drawing inventories retain explicit entries. Unresolved source IDs become findings, not dropped rows.
3. Prepare the full extraction request with instructions, `KnowledgeUnitBatch` schema, source/asset projections, feedback and output reserve. One full-source call requires both admission and safe extraction output policy; input fit does not imply response fit.
4. Use the existing `1280 + 256 * batch_size` extraction output heuristic as a risk signal before its configured cap. If the uncapped estimate exceeds the reserve, batch smaller. This is a heuristic, not a completeness guarantee; finish metadata and R03 coverage still decide success.
5. Otherwise split document → full section path → block/table/asset → fragments, then pack adjacent fitting fragments. Every rejected candidate records its reason and produces a strictly smaller candidate or terminal finding. Packing uses local estimation; supported provider counting checks final candidates. Stable prefixes and bounded token overlap follow section 5.1.

### 6.2 Text, formulas, and citation identity

Try paragraphs, sentence/line boundaries, whitespace, then code-point slices for otherwise unstructured oversized lexical runs. Preserve exact characters/whitespace. Nonoverlapping primary spans must cover `[0,len(block.text))`; repeated neighbors are `context_only`. Headings can supply section context without being required factual units.

Keep subject/value/unit/period clauses and formulas intact where possible. If an indivisible clause/formula cannot fit with required instructions/schema, retain it and fail `INDIVISIBLE_CONTEXT_TOO_LARGE`. Do not separate numbers from their binding labels or replace source evidence with a generated summary. Code-point fallback cannot authorize numeric inference across missing context.

Fragment ID: `cf_` plus truncated SHA-256 of document ID, original source ID/hash, representation, primary span/cell selection and projection version. Chunk ID also includes ordered member fragment IDs and purpose; IDs do not depend on attempt/list position. Retain full digests to detect truncated-hash collisions. Persist split/merge parents and neighbors.

Requests send original source IDs with fragment/span metadata. Citations still resolve to original blocks/assets. Before R03 validation, require returned excerpts to occur in the exact spans/cells supplied to the call. Citing an unsent passage of a known block fails. Bind accepted unit evidence to supplied occurrences in a sidecar; repeated identical text preserves all matching occurrences or explicit ambiguity, not a guessed offset. Preserve original locations; do not invent physical geometry for a fragment.

> [!NOTE]
> **Supplied Evidence and Fragment Grounding Validation Status (Disabled by Default)**:
> 1. **Supplied Evidence**: Exact substring matching of returned evidence excerpts against supplied fragment text (`validate_supplied_evidence`, raising `UNSUPPLIED_EVIDENCE`) is disabled by default via `VALIDATE_SUPPLIED_EVIDENCE=false` (or unset). This prevents pipeline failures caused by harmless model-introduced whitespace normalization, quotation adjustments, or cross-boundary excerpt boundaries in extraction responses.
> 2. **Fragment Grounding**: Strict localized fragment-level grounding checks in `_progressive_extract` (raising `FRAGMENT_GROUNDING_FAILED`) are disabled by default via `VALIDATE_FRAGMENT_GROUNDING=false` (or unset). This prevents pipeline aborts when individual knowledge units in a multi-unit batch fail localized slice validation (e.g., when a metric's subject spans adjacent blocks or footnote numbering is flagged).
> 
> All extracted units proceed downstream to the canonical document-level `validate_knowledge_units` gate, which deterministically validates each unit against the complete document (`raw`), accepting verified units into the storyboard pipeline and cleanly segregating rejected candidates in the coverage ledger. Strict localized checks remain opt-in via `VALIDATE_SUPPLIED_EVIDENCE=true` and `VALIDATE_FRAGMENT_GROUNDING=true`.

Aggregate R03 coverage by original block/cell identity. One fragment's accepted unit cannot cover missing siblings. Extend the existing full-passage numeric coverage rule to recognize exact supplied-fragment passages with checked original spans/bindings, while still requiring every original numeric obligation across fragments. Never combine fragments from different subjects/documents into new numeric support.

### 6.3 Tables and cell projections

- Project original cells with lexical text, spans, headers, locations and refs. Preserve `001`, `1.2300`, zero, blanks and quoted newlines. XLSX formula/cache status stays explicit; formula constants are not measured evidence.
- Split row groups, repeat required headers as context-only, then divide oversized rows into cell groups with row labels. Keep original **asset-local** row/column coordinates expected by R03. CSV record numbers/XLSX worksheet/A1 identity remain in `SourceLocation`; they are not F02's projection-local table indices.
- Avoid duplicating `rows` and `cells` in model context where one deterministic tested projection suffices; retain both originals in raw data. Repeated headers/block-table projections do not inflate unique-source coverage.
- Oversized textual cells may use cell-local spans plus original coordinates. Indivisible numeric/formula cells fail explicitly. Merged cells retain original anchor/spans; never fabricate independent cells by splitting them.
- Renderer/`AssetRegistry` loads the original full source table. Context fragments never overwrite assets, alter values or change native editability.

### 6.4 Media, sparse merging, and topic units

Keep original pixels/hash/dimensions/caption binding. Metadata/caption sent to a text extractor does not count as pixel examination. Pixel requests require actual media refs and supported counting. F07 does not crop/downsample source images to force a fit; future F04 transformations need explicit lineage.

Schedule asset-only sections with usable textual/table obligations separately. Unsupported interpretation remains `not_interpreted`; missing required content preserves existing blocking behavior. Recoverable pointers do not substitute for needed content.

Pack in source order. Sparse merges stay within one document, union full section paths, primary/context-only refs, unit IDs and assets, then measure the merged request and output policy. Failed merges preserve original chunks. Display labels cannot replace membership. Repeated assets stay reachable but count once in unique coverage.

For topic chunks, first try whole validated units. If one exceeds the topic target, retain its original identity and prepare bounded projections of exact evidence/structured fields; do not split a claim into invented units. A projection can exceed the soft topic target only when its final required stage request fits. Otherwise fail required use explicitly. Bounded digests derive deterministically from validated titles/source metadata with recoverable refs and omissions lists; they are planning abstractions, never replacement evidence.

## 7. Stage-by-stage integration

| Stage / call site | Context policy and overflow response |
|---|---|
| `knowledge_extraction` / `extract_knowledge_units` | Consume extraction fragments and related assets; checkpoint schema-valid results; validate supplied-ref membership and fragment-level grounding (both opt-in, disabled by default via `VALIDATE_SUPPLIED_EVIDENCE` and `VALIDATE_FRAGMENT_GROUNDING`) before canonical document-level R03 grounding (`validate_knowledge_units`). Retry missing/rejected fragments with scoped feedback. R01 still owns transport retries. |
| `storyboard_planning` / `plan_storyboard` | Use complete existing catalog if fitting; otherwise bounded topic digests with recoverable refs and explicit critical/required units. Bundle adjacent same-document topics into parent entries if needed. Expand selected parents locally into real chunk IDs and explicit representative unit IDs; retain omitted alternatives. If mandatory items/smallest complete document catalog cannot fit, fail `GLOBAL_CONTEXT_UNREPRESENTABLE`. No second narrative planner; F09/F10 later improve selection/flow. |
| `slide_composition` / retrieval/composer | Separate full local validation context from measured model projection. Include plan, required units, exact evidence/cells/assets and needed layout catalog. Drop only optional neighbors/redundant metadata with recorded reasons. Required claims/evidence cannot be dropped; narrow the plan or fail `REQUIRED_CONTEXT_TOO_LARGE`. Validate output against actually supplied IDs/refs. |
| `slide_repair` / editor / visual repairs | Recount current slide, edit instruction/locks, context, prior answer and feedback. Retain stale-base/CAS behavior. Compact duplicate feedback, never user instructions/locked facts. Oversized instruction/schema fails before generation. |
| `claim_verification` / semantic and per-slide judges | Pack atomic claim+required-evidence pairs, splitting batches by claim identity. Preserve completed judgments. An indivisible over-limit pair remains unknown/failed-to-run with budget reason, never checked; deterministic basic checks still run. |
| `faithfulness_judging` / evaluator | Shared admission using evaluator model/profile. Missing judgments stay incomplete. F19 owns metric/retrieval redesign. |
| `vision_audit` / `audit_slide_images` | Replace fixed groups-of-four admission with fitting batches preserving slide/image IDs and artifact hash. Try one image; unbudgetable single image yields `FAILED_TO_RUN`, never approval. |
| `source-passages` mode | Account for deterministic processing with zero extraction dispatches. Later stages still budget requests. Locally created units do not mean original source was sent. |

Capture OpenRouter finish reason / Gemini finish metadata in the gateway. Token-limit finish is `output_incomplete` even if JSON parses. Extraction replans unfinished primary obligations within bounded scope; storyboard/slide output fails or uses existing bounded application repair with fresh admission. Do not silently raise output or classify clipping as an ordinary transient retry.

A proven provider context-overflow signal can trigger one smaller-policy replan of splittable context with identical source obligations and recorded reduced ceiling. Generic HTTP 400/schema/auth/billing errors keep R01 terminal behavior. Repeated overflow/indivisible input stops; never retry unchanged oversized bytes.

## 8. Coverage ledger and continuation gate

Write `context_coverage.json` beside `knowledge_validation_report.json`. Existing R03 `CoverageItem` remains factual/numeric coverage authority.

| Dimension | Meaning |
|---|---|
| Retained | Declared source bytes/parser/raw/assets remain retrievable with valid hashes. Parser completeness is separate. |
| Processed | Schema-valid fragment response was inspected by local validation, or a deterministic processor completed. Rejected/unknown semantic outcomes remain visible. Processing is not proof of full understanding. |
| Selected | Scope chose this representation for a prepared request; planning selection and presentation selection have separate scopes. |
| Dispatched | Generation transport started with this representation. Network failure can yield `DELIVERY_UNKNOWN`, not proof of receipt. Digest refs do not mark originals dispatched. |
| Excluded | Scope omission with explicit reason (`not_selected_for_slide`, `optional_context_over_budget`, `heading_context_only`, `unsupported_representation`, etc.). Required primary spans cannot be excluded to evade extraction coverage. |
| Failed | Preparation/transport/validation/cancellation/interpretation failure for this scope/ref. Previous successful chunks stay recorded. |

Use interval unions for text and original cell identities/coordinates for tables. Track assets by representation. Report per-document/stage text characters, processed primary characters, dispatched characters, cell totals and media counts separately; no combined percentage adding text/cells/images. Overlap, retries and duplicate projections cannot inflate unique coverage. Zero denominators are `not_applicable`.

`all_source_retained` requires integrity checks of the declared source set. `all_required_extraction_obligations_accounted` requires completed outcomes or explicit terminal findings; terminal findings still mean extraction incomplete. `all_text_dispatched` uses the relevant text-span denominator. `all_representations_dispatched` requires each designated representation. Neither follows from retained bytes/digest refs. Report historical-cache and actual-current-run dispatch separately.

Before proceeding from extraction:

1. Primary unions exactly cover required original spans/cells, and all assets/items have dispositions. Gaps/foreign refs/hash mismatches/unresolved obligations fail.
2. Every required extraction chunk has an inspected schema-valid outcome. Required interpretation failures remain blocking under current source policy.
3. R03 grounding/coverage passes at its existing required level; accounting success cannot override rejected facts.
4. Every dispatched call has a fitting prepared request linked to its outcome. Estimates, metadata-only assets and unknown delivery remain visible.

Findings expose safe code, stage, document/source/chunk identity, required/available counts and corrective action. Public API errors never contain full prompts/credentials. Codes: `CONTEXT_CAPACITY_REQUIRED`, `CONTEXT_FIXED_OVERHEAD_TOO_LARGE`, `INDIVISIBLE_CONTEXT_TOO_LARGE`, `IMAGE_TOKEN_COUNT_UNAVAILABLE`, `CONTEXT_COVERAGE_GAP`, `REQUIRED_CONTEXT_TOO_LARGE`, `GLOBAL_CONTEXT_UNREPRESENTABLE`, `OUTPUT_INCOMPLETE`, `RUN_CONTEXT_BUDGET_EXHAUSTED`.

## 9. Checkpoints, revision integration, and migration

Use existing atomic artifact helpers and checkpoint cache:

```text
.work/<generation-signature>/
  extraction_chunks.json        # source fragments/lineage
  context_chunks.json           # topic sidecar; chunks.json stays compatible
  prepared_contexts/<hash>.json  # sanitized refs/counts/budget snapshot
  context_coverage.json          # synchronized accounting
  run_manifest.json             # existing stages/usage plus sidecar hashes
.cache/extraction/<key>.json     # existing root; F07 result envelope
```

Cache key includes source/asset hashes, ordered primary/context refs, split/projection versions, exact request hash, schema/prompt hash, selected model/profile/counter versions, input/output policy, feedback, extraction mode and dependencies. Store returned drafts, supplied-ref mapping and validation findings. Schema-valid responses with semantic gaps may be candidate caches for revalidation, never completed-coverage claims.

Resume verifies integrity/source hashes, restores results, reruns required local validation, rebuilds coverage and schedules missing/failed obligations. `CACHE_REUSED` links original preparation/result hashes; current-run dispatch/usage is zero. Changed capacity/policy/model/schema/media/counter invalidates affected requests. Synchronize mutations using existing locks; write snapshots atomically after outcomes, without holding locks across provider calls.

Publish sidecars in the R05 immutable bundle and artifact hashes. F07-enabled revisions validate them. Generation/edit/clone/rebase/resume must preserve refs and history. Edits copy historical extraction evidence and append only new operation records. Policy changes must not produce an accidental matching resume of an older revision.

Explicit `legacy_context_unknown` adaptation preserves existing files/hashes. Reconstruct retained inventory/membership only where provenance supports it; historical processed/dispatched/count certainty stays unknown. Regeneration can produce F07 evidence; new edits budget their calls without retroactively certifying old requests.

Develop behind progressive selection; make it the default after scoped acceptance. Rollback selects legacy planning with shared gateway admission, never rewriting published revisions or disabling grounding/gates. No database migration/new SQLite worker table is needed.

## 10. Ordered implementation and file map

| Step | Files | Work and exit condition |
|---|---|---|
| 1. Contracts/settings | **New** `schemas/context_schema.py`, `core/context_budget.py`, `.env.example`; `config/settings.py`, `.gitignore`, README | Explicit `.env` unknown-capacity policy/value, no numeric code fallback; resolution/formula/certainty/overlap/quota validation. Pure tests without keys; secret-free template is trackable. |
| 2. Gateway preparation | `core/llm_client.py`, `core/llm_run.py`, `core/artifacts.py` | One prepared payload for sync/async/media; call IDs/counts/finish metadata/fingerprints; stable prefixes, normalized cache usage, optional TPM reservation, bounded Retry-After/jitter. Capture tests prove parity and no nested retries. |
| 3. Source fragmentation | `pipeline/chunker.py`; **new** `pipeline/coverage_ledger.py` | Inventory, hierarchy/spans/cells/lineage, safe packing and recovery pointers. Reconstruction/merge tests pass. |
| 4. Extraction/grounding | `pipeline/knowledge_extractor.py`, `tools/claim_verification.py`; narrowly scoped schema changes only if needed | Replace character admission, bind supplied fragments, preserve R03 numeric coverage, scoped retry/checkpoints. Unsupported fragmented numeric claims still reject. |
| 5. Topic/all-call integration | `pipeline/storyboard_planner.py`, `pipeline/slide_composer.py`, `pipeline/slide_editor.py`, `pipeline/visual_reviewer.py`, `evalute/metrics/faithfulness.py` | Compatible topic interface; bounded planning/composition/repairs/judges; local versus supplied evidence separation; mandatory overflow fails. |
| 6. Service/revisions | `pipeline/orchestrator.py`, `pipeline/service.py`, `core/revisions.py`, `core/job_context.py`, `main.py`; API/worker only for needed settings/result metadata | Signatures/sidecars/resume/publication/edit; chunk progress through F01. No frontend pipeline. |
| 7. Acceptance/docs | **New** `tests/test_context_budget_f07.py`, `tests/test_context_chunking_f07.py`, `tests/test_context_coverage_f07.py`, `scripts/verify_f07_native.py`; regression tests/README | Regression/mixed-source/native/resume/failure evidence. Update status registries only after runtime implementation. |

One owner per responsibility: budget module owns math/count policy; gateway provider payload/transport; chunker partitions; F07 ledger context accounting; R03 grounding/semantic coverage; R05 integrity/publication. F09/F10 later enhance selection/narrative. No calendar estimates.

## 11. Acceptance and reproducible verification

| Area | Required fixtures and assertions |
|---|---|
| Budgets | At/one above ceiling; fixed system/schema/tool overflow; separate limits/output reserves/model overrides; Unicode/CJK/emoji; counted/estimated margins; invalid settings. Unknown capacity uses explicit `.env` value; absent/blank/invalid value or error policy stops before counting/generation. Declared capacity wins and CLI/environment/.env precedence remains intact. |
| Payload parity | Captured OpenRouter JSON/injected Gemini contents match counted system/schema/media. Repair/schema/image changes invalidate counts; caller estimate cannot bypass. Missing required media estimator fails; partially counted request stays hybrid. |
| Input/output completeness | Small source one call; large source splits; input-fit/output-risk batches split; empty/partial/clipped output cannot certify coverage or repeat unchanged. |
| Lossless text | Huge block, many small sections, long lexical run, repeated passages, CRLF, headings and indivisible formula. Primary union reconstructs exact text/hash; overlap does not inflate; splits strictly shrink. |
| Assets/tables | Sparse merge keeps both sections' assets and fits; matching section titles across documents; asset-only sections; oversized rows/cells; merged headers; CSV asset-local/source record identity; hidden/sparse XLSX/A1, lexical values/blanks/formula cache status. All projections resolve to original registry. |
| Grounding/accounting | Unsent passage of a known block, foreign document/cell/fragment, swapped subject/period rejects. Success cannot cover failed siblings. Digest/metadata does not mark originals/pixels sent. R03 regressions remain passing. |
| Stages | Initial/repair/edit/semantic/faithfulness/vision preflight; mandatory facts/locks never silently removed; digest hierarchy preserves document membership; adaptive visual batches keep all IDs/hash; missing judge stays incomplete. |
| Failures/caps | Mid-extraction failure retains successes; billing/auth do not split/retry; proven overflow replans once; thread-safe reservations; cancellation produces accurate dispatch/outcome. |
| API efficiency | Stable system/schema/reference prefix across chunks/repairs; request suffix changes without injecting prefix timestamps. Provider count estimates stay estimates. Token overlap has correct spans/bounds and no double coverage; capture call/repeated-token overhead. Count cache usage once, include cached context in admission, distinguish provider cache from no-call result reuse. RPM/TPM reservations and Retry-After/deadline handling do not multiply SDK retries. |
| Resume/revisions | Unchanged resume zero calls; source/capacity/counter/policy changes invalidate; tampered chunks/media/coverage fail; edits preserve history/new scope; legacy dispatch unknown; failed edits leave active revision unchanged. |

Generate deterministic seeded stress fixtures with many documents/sections, at least a 100,000-character block and an over-budget table. Exercise several artificial capacities. Use sufficient fixed-schema capacity for source-splitting tests and separate fixed-overhead failure tests. These are algorithm tests, not Q11 workload/performance certification.

Commands **after implementation**:

```powershell
python -B -m pytest tests/test_context_budget_f07.py tests/test_context_chunking_f07.py tests/test_context_coverage_f07.py -q -p no:cacheprovider --basetemp ../audit-artifacts/f07/focused
python -B -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp ../audit-artifacts/f07/final --junitxml=../audit-artifacts/f07/pytest-final.xml
python -B scripts/verify_f07_native.py --output-dir ../audit-artifacts/f07/native
git diff --check
```

The native script must parse real mixed PDF/DOCX/CSV/XLSX fixtures using F02, force progressive extraction with source-grounded fixture answers, build/edit/render both adapters in real PowerPoint COM, and verify refs/cells/hashes/zero-call resume. Include controlled mid-extraction failure/resume and mandatory over-budget edit preserving the active revision. Fixture answers do not certify live-provider completeness.

Run small live count/structured probes for available providers, recording model/profile, request hash, count versus usage and clipping/overflow behavior. Credential/billing/platform gaps remain explicitly unavailable; injected adapters do not replace live certification. No automatic full-document cost benchmark while Q11/provider choices are pending.

Record tested commit plus working-tree dependency hashes, commands/seeds/fixtures, count methods, coverage/native PPTX/preview hashes and unavailable checks under `C:/Users/thang/Projects/PPTAI/audit-artifacts/f07/verification.json`. Then update CURRENT_STATE/MODULE_STATUS/modules.json with scoped runtime evidence. The historical plan update left F07 NOT_STARTED; the runtime implementation and evidence above supersede that status.

## 12. Decisions and unresolved preferences

- **Q12 confirmed:** provider undecided; stage/run limits configurable and tied to selected-provider capabilities and measured/estimated requests. Full context must fit input/output policy.
- **Q20 confirmed, 13 October 2026:** unknown capacity must use a configurable capacity with the switch in `.env`. Section 5 replaces the earlier proposed hardcoded 32,768 fallback with explicit configured policy/value and no numeric code default.
- **Q21 confirmed, 13 October 2026:** follow efficient API/chunking practices informed by official OpenAI/Anthropic documentation. Section 5.1 maps sources to implementation requirements without selecting a new provider or copying retrieval indexing defaults into extraction.
- **Q11 pending:** expected pages/files/scans/workbook scale. Proceed with configurable defaults/stress fixtures; no invented performance target.
- Complete retention, progressive fallback, separate retained/processed/dispatched/selected accounting, basic checks and optional deeper checks follow shared invariants.

[DECISIONS](../DECISIONS.md) is authoritative. Remaining numeric defaults are engineering proposals to validate during implementation; Q20/Q21 are recorded user instructions. Pending preferences do not block completion of this plan update. This was a documentation-only planning refinement; the subsequent runtime implementation is recorded above.
