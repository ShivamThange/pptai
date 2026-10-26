# F02 — Uploads, file-type dropdown, and Docling routing

Type: **Feature** · Current capability: **eight structural formats, ordered multi-source intake, raw-v3/cache/API/CLI/intake page** · Implementation: **VERIFIED (local F02 scope)** · Phase: **1**

Workflow references: 1, 3, 4, 5. Dependencies: [F01](F01_api_jobs_and_service.md), [R02](R02_provenance_and_assets_repair.md). Follow [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), [branch strategy](../BRANCH_STRATEGY.md), [decisions](../DECISIONS.md), [module status](../MODULE_STATUS.md), and [workflow cross-check](../WORKFLOW_CROSSCHECK.md).

**Plan revision: 13 October 2026.** The implementation contract below is preserved; verified runtime evidence is now recorded at the end and in CURRENT_STATE/MODULE_STATUS. Code inspection used clean `multi-agent` HEAD `2fa462dbc775ebba6868e1df5fc08196783549cb`. Q05 confirms the formats; Q11 upload scale remains pending. Engineering defaults here are proposed choices, not new human-confirmed decisions. Paths resolve under `C:/Users/thang/Projects/PPTAI/BTPs5`.

## 1. Observed code and concrete changes

| Existing extension point | Observed behavior | F02 change |
|---|---|---|
| `api/routes.py` | Stores one immutable upload, sanitizes its name, streams SHA-256, accepts PDF/Markdown by extension only; parse/deck requests enqueue work. | Reuse routes/storage; add content detection, selection, metadata and a format endpoint. |
| `schemas/service_schema.py`, `core/jobs.py` | `DeckRequest.document_id`; three SQLite tables; parse options are GPU/resume. | Typed source selections and one ordered deck/source mapping table. |
| `workers/local.py`, `pipeline/service.py` | One sequential worker checks source hash, parses/generates through the shared service; document cache serves multiple decks. | Parse ordered members, retain individual outcomes, generate from one collection projection. |
| `pipeline/stage1_docling_parser.py` | Lazy Docling import, PDF options, OCR/table extraction, CPU/CUDA fallback, retained JSON/captions/assets. Other converter defaults are not tested support. | Explicit per-format options, conversion status, effective configuration and diagnostics; retain R02 exporter. |
| `core/artifacts.py` | Cache key covers source/name/extension/GPU/Docling version/parser-file hash; retains original bytes and hashes outputs. | Add adapter/options/dependency identity and complete-only staged cache publication. |
| `pipeline/source_adapter.py`, `schemas/raw_extraction_schema.py` | Structural v1/v2 → raw v2; one top-level namespace scopes every item; locations are Docling-oriented. | Raw/structural v3 with member registry and non-page locations; preserve each member namespace. |
| `pipeline/stage2_quality_gate.py` | Checks image paths/table CSV paths, not all hashes/source membership/formulas. | Shared typed ingestion validator with completeness and asset availability. |
| `main.py` | One `--input`; help already says source document, internal parser parameter still says `pdf_path`. | Repeated inputs with matching type/options; preserve single-source commands. |
| Frontend | No frontend application/directory. | Minimal same-origin intake page; F15 later owns draft/review UI. |

API upload IDs are random 32-character IDs; evidence document IDs are `doc_<full source SHA-256>`. Preserve both identities. The previous F02 wording about missing uploads and PDF-only CLI help is superseded by this audit.

## 2. Scope and ownership

Deliver multi-file intake, Auto-detect/validated overrides, explicit routing, retained original bytes/raw content, real locations, per-file errors, and integration with the existing jobs/CLI/cache/revisions. One `RawExtraction` → current IR1 → storyboard → scene → renderer path serves all clients.

F02 owns structural extraction. F04 owns image/chart/formula interpretation and reconstructable chart data; F05 owns richer knowledge contracts; F07 owns model budgeting/progressive extraction. OCR text is not semantic verification. Basic source/numeric checks remain mandatory.

PPTX, HTML, `.doc`, `.xls`, `.xlsm`, archives, standalone LaTeX, and additional image formats remain outside Q05, even if Docling supports them. Do not add a second fact store, independent planner, remote research, or automatic partial-source generation. No calendar estimates or production orchestration are required.

## 3. Exact detection and routing

Type tokens: `pdf`, `docx`, `txt`, `markdown`, `csv`, `xlsx`, `png`, `jpeg`; dropdown also has `auto`. `.md`/`.markdown` map to Markdown, `.jpg`/`.jpeg` to JPEG. Client MIME is advisory.

| Type / extensions | Intake validation | Adapter | Required retention/location |
|---|---|---|---|
| PDF / `.pdf` | PDF header; worker checks readability/encryption. | Docling `InputFormat.PDF`, `PdfFormatOption`, existing exporter. | Docling JSON, parsed blocks/assets; genuine page/bbox/origin/item/charspan. |
| DOCX / `.docx` | OOXML ZIP with `[Content_Types].xml`, Word main-part content type and `word/document.xml`. | Docling `InputFormat.DOCX`, `WordFormatOption`. | Headings/lists/tables/available embedded pixels; exact item references. Unknown pagination stays null. |
| TXT / `.txt` | Strict text decoding; reject binary. | Deterministic text adapter. | Raw decoded text, paragraph blocks, half-open character spans, inclusive lines. |
| Markdown / `.md`, `.markdown` | Strict text decoding; extension/selection distinguishes TXT. | Docling `InputFormat.MD`, `MarkdownFormatOption`, retained text. | Items/sections/tables; original Markdown; line mappings only when exact. Linked-asset findings. |
| CSV / `.csv` | Strict text decoding; worker parses actual records. | Python `csv`, no pandas type inference. | Every lexical record/cell; table JSON/CSV; record/column and physical line span. |
| XLSX / `.xlsx` | OOXML workbook main-part content type and `xl/workbook.xml`. | `openpyxl` read-only plus package metadata. | Sheets/cells/types/formulas/caches/number formats/merged ranges; A1 coordinates. |
| PNG / `.png` | PNG signature and Pillow verification; full decode in worker. | Original image plus Docling `InputFormat.IMAGE`, `ImageFormatOption`. | Original pixels/hash/dimensions, OCR items/geometry, original-image location. |
| JPEG / `.jpg`, `.jpeg` | JPEG signature and Pillow verification; full decode in worker. | Same image adapter. | Same, including orientation/preprocessing transform when used. |

`pipeline/ingestion/detection.py` executes this order:

1. Reuse streamed temporary upload/count/hash logic; reject empty input; enforce configured bytes before publication.
2. Inspect binary signatures first. Inspect OOXML members/content types without unrestricted ZIP extraction; a ZIP signature alone cannot distinguish DOCX/XLSX. Verify actual image format. Decode text strictly using BOM/encoding policy.
3. Use allowed extension for TXT/Markdown/CSV; none has reliable magic bytes. Do not infer Markdown from `#` or CSV from commas in prose.
4. Compare signature, extension, dropdown. A clear binary signature determines detection; incompatible extension/selection returns `TYPE_MISMATCH` and correction. Explicit TXT/Markdown/CSV selection can resolve text ambiguity, recording `TEXT_TYPE_OVERRIDE`. Unsupported extensions fail; `.exe` is not accepted merely because content resembles a document.
5. Persist original name/extension, sanitized name, detected/selected/resolved type, detection basis, detected text encoding, client MIME and findings. Pass resolved type to adapters. Publish source/document row only after successful intake; clean rejected temporary data. If text decoding needs a non-BOM encoding, return `TEXT_ENCODING_REQUIRED`; the upload route accepts an explicit encoding on retry.

No Docling/OCR/LLM calls run in HTTP intake. Corruption detectable only through full conversion becomes a worker error. Example: `.pdf` containing PNG returns HTTP 422 with `TYPE_MISMATCH`, `detected_type: "png"`, and a rename/select-PNG-or-Auto correction. PDF bytes with a DOCX dropdown instead ask for PDF/Auto.

## 4. Shared contracts and identities

Add `schemas/ingestion_schema.py`; forbid unknown request fields. Converter configuration is server-owned, not arbitrary client dictionaries.

| Model/version | Fields and invariant |
|---|---|
| `UploadSpec` / `upload-v1` | `upload_id`, original/display/storage filename, source SHA-256, size, detected/selected/resolved type, detection basis, detected text encoding, findings, creation time. No public server path. |
| `SourceSelection` | `document_id` (API upload ID), optional selected type, parse options. Null selection inherits upload selection; explicit `auto` re-detects. |
| `ParseOptions` / `parse-options-v1` | `ocr: auto/off/force` default auto; `encoding` default auto; `csv_delimiter` default auto; `csv_has_header` default true. Auto encoding uses the upload's validated encoding or BOM/UTF-8 for CLI sources. Nondefault inapplicable options fail validation. GPU/resume retain existing service fields. |
| `ResolvedParseOptions` | Actual format/encoding/delimiter/header policy, requested/effective OCR mode/engine/languages/device, table/image options, adapter/package/model versions. Requested and actual values are separate. |
| `ParseFinding` | Code, severity info/warning/error, safe message, document ID, optional item/location, `blocks_generation`. Full exceptions stay in local logs. |
| `DocumentDescriptor` | Evidence document ID/hash/name/aliases, upload IDs where applicable, resolved format, parse key/version, completeness and extraction counts. |
| `ParseResult` / `parse-result-v1` | Upload/evidence IDs, parse key, status complete/partial/failed, completeness, structural artifact/hash, raw artifacts, resolved options, counts/findings. Public view omits paths. |

Identity rules:

- Keep `doc_<64-character source SHA-256>` for evidence. Upload ID represents a stored submission; filename is a display label, never evidence identity.
- Preserve existing Docling item/block/asset IDs. New source items: TXT `<doc_id>:text:<start>-<end>`; CSV `<doc_id>:csv:record:<one-based record>:column:<one-based column>`; XLSX `<doc_id>:xlsx:sheet:<one-based ordinal>:cell:<A1>`; original image `<doc_id>:image:original`.
- Hash IDs for artifact directory/filenames, reusing `build_raw_extraction`; never use unchecked sheet names/source IDs as filesystem paths.
- Different bytes with local `block_0001` have distinct namespaces. Identical bytes share content identity, retain upload/name aliases, and become one collection member when parse settings match. Conflicting settings fail `DUPLICATE_SOURCE_OPTIONS`; do not create colliding variants.
- Do not semantically deduplicate different documents or resolve contradictions here; F08/F20 own that work.

### Raw DocumentIR v3

Extend existing structural `ir.json` and typed `RawExtraction` to schema `3`. These are the raw DocumentIR boundary, not a new fact model. Add `documents: list[DocumentDescriptor]` and optional `collection_id`. Retain single-document name/ID/hash fields for v1/v2 readers; collection top-level document ID/hash are null, with actual member ID on every retained item.

Add optional `SourceLocation` fields: `kind` (`docling_item/text_span/csv_cell/xlsx_cell/image`), `line_start/end`, `record_index`, `column_index`, `sheet_name/index`, `cell_range`, `geometry_unit`. Preserve document/source/page/bbox/origin/charspan. Lines/records/sheets are one-based; `TableCell.row/column` remain zero-based within each table. Character spans refer to retained decoded text. CSV logical records differ from physical lines for quoted newlines.

Extend `TableCell` with optional lexical/raw-value/type metadata, formula, cached value/state and number format. Encode decimals/dates/errors using explicit string/type tags; no NaN/Infinity JSON. Existing `text` stays evidence/display text, and `headers/rows/cells` remain renderer-compatible. Complete workbook metadata also lives in `adapter_raw.json`; never replace source values with formatting or inferred units.

Validators must enforce:

1. Unique document/block/asset/item IDs and real membership for every block/asset.
2. Real source/caption/cell refs in the owning member; no dangling refs or collection-prefix rewriting.
3. Genuine coordinates, declared units/origin, explicit image transforms; unknown non-page geometry stays null.
4. Available asset files/hashes match; unavailable crops are `MISSING` with findings, and required-use missing assets block generation.
5. Valid table dimensions/spans and original coordinates across partitions; headers remain source evidence.
6. Parser completeness is separate from IR1 coverage/deep verification; success does not by itself prove complete examination. Complete means all supported structural units were processed and all unsupported units/raw bytes retained or inventoried, with no configured limit or conversion failure omitting expected content. Unknown pagination is not itself an extraction failure; unknown/unprocessed source coverage is blocking.

`pipeline/source_adapter.py` owns v1/v2/v3 compatibility. Preserve legacy handling/unknown metadata; for v3 validate member IDs without applying today's top-level `scoped()` to collection items. Preserve hierarchy and prefix the first section grouping key with member identity, preventing current `_section_name()`/chunk grouping from mixing unrelated `Root`/`Introduction` sections. This grouping label must not become invented source text.

## 5. Adapter behavior

### Docling, OCR, and images

Introduce `run_docling_extraction_for_type(source_path, output_dir, resolved_options)`; keep `run_docling_extraction(..., use_gpu=False)` as a compatibility wrapper for existing callers/tests. Constrain `DocumentConverter.allowed_formats`; installed extra formats do not enlarge product support.

PDF/image `PdfPipelineOptions`: table structure on, page/picture images on, image scale 2.0, remote services off, optional picture description/classification/formula enrichment off. OCR auto uses normal selective OCR; off disables it; force uses installed `OcrMode.FULL_PAGE`. DOCX/Markdown use simple pipelines; explicit OCR is invalid for these formats. Embedded DOCX picture OCR belongs to F04. Server config selects installed engine/languages/model directory; retain actual engine/model identity. Required runtime/model failure is `OCR_UNAVAILABLE`, not a successful empty extraction. Requested GPU retains CPU fallback with a finding.

Call `convert(..., raises_on_error=False)` and inspect conversion status/errors before export. Failure produces failed ParseResult. `PARTIAL_SUCCESS` retains output/diagnostics but blocks generation. Keep unmodified original bytes and complete `docling_document.json`; missing optional crops are availability warnings, missing/unprocessed pages are blocking. Retain page accounting when available; unknown coverage is not asserted complete.

Images always register original pixels, including when OCR yields no text/picture item. Filename does not become a caption. Orientation/scale preprocessing produces a distinct derived asset and mapping to original geometry. Decodable textless images may have complete raw intake; current text-based knowledge extraction returns `SOURCE_CONTENT_UNAVAILABLE` if no supported units exist. F04 later owns interpretation; never manufacture a description just to pass generation.

Markdown links do not become implicit sources. Configure/wrap its backend to prevent remote fetching and reads outside uploaded material. Unavailable links become `UNRESOLVED_LINKED_ASSET`; text remains usable unless a required asset is missing. Original bytes/text remain retained despite Docling normalization. DOCX/Markdown support does not promise exhaustive layout/visual fidelity.

### TXT and CSV

Auto-decode UTF-8/UTF-8 BOM/UTF-16 BOM. Otherwise return `TEXT_ENCODING_REQUIRED` for an explicit encoding; never ignore/replace invalid bytes. Keep newline/Unicode raw content and exact spans. TXT emits nonempty paragraph blocks; blank spans are preserved/counted in raw text.

CSV uses `csv.reader`, `newline=""`, strings only: retain leading zeros, precision, dates and empty fields. Delimiter auto samples comma/semicolon/tab/pipe; ambiguity requires explicit choice. Explicit delimiter is one supported character. Use quote `"`, double quoting, no whitespace stripping and strict malformed-record failure. Header true takes first logical record as headers, preserving duplicate/blank labels and original cell identities; false retains it as data. This is a proposed default, not inferred semantics.

Raw ragged/blank records remain in `adapter_raw.json`. Ragged width yields partial `CSV_ROW_WIDTH`, blocks generation and asks for correction; never silently drop/pad records. Valid tables partition at 200 data rows with original coordinates. Repeated projection headers reference the original header cells. Partitioning is storage, not F07 budgeting. Empty/header-only inputs get `NO_USABLE_CONTENT`, not invalid empty assets accepted by `normalize_table_data`.

### XLSX

Declare openpyxl directly. Load read-only twice, `data_only=False` for formulas and `data_only=True` for stored results. Retain sheet order/state, populated coordinates/types, formula/cached state, number format and merged ranges from package metadata. Check stale dimension hints against worksheet XML; do not silently omit populated cells. Never save/recalculate uploaded workbooks or launch Excel to manufacture values.

Literal values retain raw type/value and deterministic evidence text. Formula with stored result retains formula/result and labels `cached_unverified`; absent result is `FORMULA_VALUE_UNKNOWN`, never zero. Formula text must not be scanned as measured numeric data. Source-passage/metric extraction uses usable literals or explicitly labeled cached results; unresolved formula constants cannot drive numeric claims/charts. Date/percentage/currency formats remain metadata without silent value/unit conversion.

Read every worksheet, including hidden content, recording visibility. Preserve merged anchors/ranges without fake repeated values. Use consecutive 200-row table projections over populated bounds with A1 locations; preserve sparse/blank coordinate metadata. No automatic first-row header for XLSX. Inventory chart sheets/drawings/pivots/unsupported objects with `UNINTERPRETED_WORKBOOK_OBJECT`; F04 owns interpretation. Cell extraction is not full Excel feature support. Configured limits yield partial output with exact unprocessed sheet/range.

## 6. API, SQLite, and multi-source service

Extend existing routes, application, queue and worker. The previously proposed separate `api/documents.py` is unnecessary.

| Route | Request/response change |
|---|---|
| New `GET /api/input-formats` | Allowed formats/extensions/dropdown, applicable options, effective limits and configured adapter availability; no heavy runtime import/loading. |
| Existing `POST /api/documents` | One multipart `file`, optional `selected_type=auto`, `encoding=auto`; 201 public upload metadata. Explicit encoding corrects failed strict text decoding and is recorded. UI uploads each chosen file independently. |
| Existing `GET /api/documents/{id}` | Metadata and latest parse key/outcome/findings; preserve `parsed`/`parse_summary` and add readiness/completeness. |
| Existing `POST /api/documents/{id}/parse` | Existing GPU/resume plus selected type/options; 202 job; freeze effective request. |
| Existing `POST /api/decks` | Either legacy `document_id` or new ordered nonempty `sources: list[SourceSelection]`, never both. Existing generation fields; 202 submission plus normalized source IDs. |
| Existing `POST /api/decks/{id}/generate` | Generation options with pinned deck sources; never use arbitrary latest document parse settings. |
| Existing deck/job polling/SSE | Ordered source metadata/per-file outcomes; legacy document ID denotes the first/primary upload. |

Example (upload IDs are illustrative):

```json
{
  "sources": [
    {"document_id": "11111111111111111111111111111111", "selected_type": "auto", "parse_options": {}},
    {"document_id": "22222222222222222222222222222222", "selected_type": "csv", "parse_options": {"csv_delimiter": ",", "csv_has_header": true}}
  ],
  "min_slides": 5,
  "max_slides": 8,
  "renderer": "python"
}
```

`core/jobs.py` uses `PRAGMA user_version` and one additive transactional migration:

- Add nullable `upload_spec_json`, `last_parse_result_json` to documents; keep `structural_ir_path` as last successful parse pointer. Replace positional INSERTs with explicit columns.
- Add only `deck_documents(deck_id FK, document_id FK, ordinal, selection_json)`, primary key `(deck_id, document_id)`, unique `(deck_id, ordinal)`. This models the many-source relationship, not a workflow engine.
- Backfill existing decks with ordinal 0/default selection. Old jobs remain readable. Lazy detection of old uploads does not imply historical verification.
- Validate every member/capture its hash/name/type/options in job request; insert deck/members/job in one short transaction without parser/provider calls.
- Keep decks/jobs primary `document_id` for compatibility; captured ordered membership is worker authority. Reject duplicate upload IDs; identical bytes/settings collapse to one member with aliases.
- Latest parse summaries are convenience state. Actual job/revision artifacts are pinned by parse keys; later parsing cannot alter queued options or a deck's evidence.

Add `parse_sources(...)`, `generate_deck_from_sources(...)` in `pipeline/service.py`; single-source wrappers preserve current behavior. Worker verifies each immutable upload hash and parses sequentially. Check cancellation before/after files/partitions; collect ordinary file failures and continue evaluating other members. Propagate database/cancellation errors immediately.

Persist completed member outcomes through document state and an optional per-file progress payload. Extend `core/job_context.py` report methods with optional details while preserving current calls; use existing `progress_json` for `files_completed/files_total/current_document_id` and member outcomes. Maintain existing stage counters for generation. Failed/partial members stay visible. A blocked set ends failed `SOURCE_SET_INCOMPLETE`, retaining a result with all per-file outcomes/successful caches; extend the worker failure path to pass this typed result to `JobStore.finish`, whose existing schema already permits it. Users remove/replace failed sources explicitly and submit a new set. No auto-continue-with-successes. Single-file parse jobs keep their normal completed/failed states, with completeness explicit.

`pipeline/ingestion/collection.py` assembles usable members into one structural v3 `ir.json`, ordered registry/item catalog and unchanged member-local block/asset refs. `collection_id = collection_<SHA-256 of ordered unique document IDs and parse keys>`. Preserve upload/name aliases. Do not concatenate Markdown/reparse/reset counters. Existing orchestrator consumes this aggregate, without a second planner. Edits/regeneration use pinned source/raw snapshots; removing a UI row only affects the next submission, never deletes or mutates an existing deck.

## 7. Cache, source bundles, and compatibility

Retain document-local `.cache/parsing/<parse_key>/` and OS lock. Extend `parse_document_cached` with normalized options/router, preserving injected parser hook for regressions. Key includes source bytes/name/alias policy, resolved type/options, adapter/code/schema versions and relevant dependency/model/device identity; excludes prompt/audience/provider/renderer/slide count. Unused Docling/GPU settings must not invalidate TXT/CSV. Use `canonical_json`/`sha256_value`. Resolve source-set aliases to the first selected member's preserved name for parse identity; retain other aliases in the collection manifest rather than overwriting a cached document name.

Resolve engine/device identity before lookup and verify actual configuration after conversion. A fallback publishes under its actual key with requested→effective metadata, never a misleading GPU/model key.

```text
source_snapshot.bin          # exact bytes, all adapters
decoded_source.txt           # text adapters/Markdown when applicable
docling_document.json        # Docling adapters
adapter_raw.json             # complete deterministic raw data
ir.json                     # structural v3
parse_result.json           # options, completeness, findings/counts
assets/...                  # hashed images/formulas/table JSON/CSV
parse_record.json            # v2 cache record, all hashes; written last
```

Stage output in a sibling candidate, validate, then publish under lock. Fail/cancel preserves diagnostics/original bytes without making reusable cache entries or replacing prior valid output. Partial results are inspectable but never complete hits. Verify all paths/hashes before reuse; missing/tampered assets/source snapshots invalidate reuse. Keep previous complete artifact and latest incomplete outcome separately.

Collection revisions retain `source_manifest.json` and `sources/<hashed-member-directory>/` containing each exact source/parser export/result/record and relevant assets. Extend the orchestrator's current fixed single-source copy loop and edit/import handling. Reuse R05 bundle hashing/rebasing; usable asset paths point within the revision. Exact parser/source snapshots remain reproduction evidence and are not rewritten during rebasing.

Extend `structural_fingerprint()` to bind member manifest/parse hashes/all retained inputs, including table CSV. Preserve generation-signature, stale-base/CAS, native gate and cancellation-during-publication behavior. Unchanged resume returns the same revision without reparsing; changed bytes/type/options/schema/code/model/membership/order invalidates relevant identity. Only changed members reparse; rebuild aggregate/downstream artifacts conservatively under current R05 rules.

Read v1/v2 structural/raw and v1 parse records. Old complete caches are reusable only when recorded effective configuration/dependencies/artifact checks match; otherwise reparse. Historical revisions remain readable/editable with unchanged evidence IDs; do not rewrite old records as v3 or assert new coverage. Old queued jobs normalize to one source. Back up SQLite before migration; no automatic downgrade. Rollback uses prior code/database backup and retained revisions, never deletes uploads.

## 8. Intake page and CLI

Add `frontend/upload/index.html`, `upload.js`, `upload.css`, mounted same-origin at `/upload` by FastAPI. Use fetch and existing APIs, no separate Node/frontend service. This is an intake screen; later F03/F15 add brief/review capabilities.

1. Fetch format endpoint; multi-select files and show ordered rows with name/bytes/dropdown/detected type/status/findings. Browser `accept` is convenience; server is authoritative.
2. Upload independently; keep successful IDs on another row's failure. Allow retry/replacement/removal. Changing selection after upload updates SourceSelection, not immutable bytes.
3. Expose relevant OCR/CSV options and encoding correction; show detected-type fix. An intake decoding failure offers an encoding field and retries upload with it. Hide arbitrary backend/provider settings and private paths.
4. Optional `Parse files` queues individual parse jobs. `Send` captures included rows/options and queues deck generation, including needed parsing; pre-parse/review is not mandatory. Disable for unresolved upload/type errors and duplicate submission.
5. Existing polling/SSE drives file progress/reconnect; existing cancel endpoint; show returned job/deck information. Post-queue row changes affect only future requests.
6. Render extracted content/findings as plain text. Document instructions are source data, never executable HTML or application directives.

CLI keeps existing `--input file.pdf`. Make input repeatable; repeatable `--input-type` is paired by position, omitted entirely means all auto, provided means one per input. `--parse-options-file` accepts a JSON ParseOptions list of matching length. Preserve GPU/resume/renderer/edit/evaluation flags and common schemas/router. Multi-source evaluation receives the aggregate structural path instead of one member's `parsed_paths[0]`; retain evaluator YAML precedence and artifact-pinned assessment.

## 9. Implementation order and file ownership

| Step | Files | Deliverable/checkpoint |
|---|---|---|
| 1. Contracts/fixtures | New `schemas/ingestion_schema.py`, `tests/fixtures/ingestion/`; extend raw/service schemas | Versioned models, coordinate conventions, compatibility/fixture expectations. |
| 2. Detection/storage | New `pipeline/ingestion/detection.py`; extend routes/service settings | Content/OOXML/text detection, overrides/limits/metadata; zero parser work on intake. |
| 3. Adapters | New `pipeline/ingestion/router.py`, `adapters/docling.py`, `text.py`, `csv.py`, `xlsx.py`, `image.py`; extend stage1 exporter | Fixed dispatch map, explicit options/status, raw retention/locations; no plugin framework. |
| 4. Validation/cache | New `pipeline/ingestion/validation.py`; extend artifacts/source adapter/stage2 gate/service artifact views | Complete-only publication/hits, v3 namespaces, all-asset/source checks. |
| 5. Sources/service | New `pipeline/ingestion/collection.py`; extend jobs/job context/service/worker/routes | Additive migration, captured membership, outcomes, one aggregate, block incomplete generation. |
| 6. Runtime compatibility | Orchestrator/editor/revisions as needed; scoped changes to knowledge extractor/claim verification/chunker/evaluator reference adapter | Whole source bundles, isolated section grouping, no formula-number leakage; retain gates/CAS/resume. No new F05/F07 algorithm. |
| 7. Clients | New `frontend/upload/`; extend app/main/README | Functional multi-file dropdown page, matching CLI and demo commands. |
| 8. Evidence | New routing/adapter/collection tests, `scripts/verify_f02_native.py`; extend API/service/cache/provenance/CLI tests | Real-format support, counterexamples, worker/native edit/resume, recorded hashes. |

Inspected environment: Docling `2.139.0`, docling-core `2.101.1`, openpyxl `3.1.5`, FastAPI `0.115.6`, Pydantic `2.10.4`. Parsing baseline uses these Docling/core/openpyxl versions (updated from 2.121.0 to support rapidocr >=3.10.0), pinned after compatibility tests. Declare openpyxl in requirements; record resolved OCR/Pillow/parser dependencies/model hashes. A transitive installation is not a declared requirement. Do not upgrade unrelated renderer/provider packages.

## 10. Failures, limits, and acceptance

| Condition | Outcome | Required behavior |
|---|---|---|
| Empty/unsupported/too large | 422 `EMPTY_UPLOAD`, 415 `UNSUPPORTED_TYPE`, 413 `UPLOAD_TOO_LARGE` | No document row; clean temp; identify correction/limit. |
| Mismatch/invalid options | 422 `TYPE_MISMATCH` / `INVALID_PARSE_OPTIONS` | Detected format/applicable control correction. |
| Text decoding ambiguous/invalid | 422 `TEXT_ENCODING_REQUIRED` at intake or per-file failure in CLI/worker | Retry with explicit valid encoding; never discard undecodable bytes. |
| Missing submission source | 404 | No half-created deck. |
| Changed stored source | Failed `SOURCE_INTEGRITY_ERROR` | No parsing/provider/revision. |
| Corrupt/encrypted/unavailable OCR | Per-file `CORRUPT_SOURCE` / `ENCRYPTED_SOURCE` / `OCR_UNAVAILABLE` | Retain source/diagnostics; safe correction. |
| Partial parse/CSV width/configured limit | Blocking partial ParseResult | Preserve output; list missing pages/sheets/ranges when known; never claim complete. |
| Empty source/textless unsupported knowledge | `NO_USABLE_CONTENT` / `SOURCE_CONTENT_UNAVAILABLE` | Original/raw asset retained; no invented claims. |
| Blocking member | Failed `SOURCE_SET_INCOMPLETE` | All per-file outcomes and successful caches; explicitly revise selection. |
| Cancellation | Existing cancelled job, no reusable incomplete candidate | Check between operations/after Docling returns; no promise of interrupting native conversion. |

Keep configurable `PPTAI_UPLOAD_LIMIT_BYTES` default **100 MiB per file** from F01. Q11 has not confirmed expected files/pages/scans/workbooks. Proposed optional settings are `PPTAI_MAX_SOURCE_FILES`, `PPTAI_MAX_SOURCE_BYTES`, `PPTAI_MAX_SOURCE_PAGES`, `PPTAI_MAX_WORKBOOK_CELLS`; absent means no additional product cap, configured values must be positive. Expose effective limits through the format endpoint. Check files/aggregate bytes before enqueue, pages/cells before or during complete parsing. Any cap yields explicit incomplete/error outcome, never first-N-page/row truncation. Adapter/library limits also return explicit findings. One local worker remains sequential; no load/SLA certification follows from these checks.

Fixtures record SHA-256, expected text/coordinates/counts, adapter/version and known limits in `tests/fixtures/ingestion/manifest.json`:

- PDF: text/table/figure, known scanned OCR, corrupt/encrypted and mixed-page partial cases.
- DOCX: heading/list/Unicode, merged/header table and embedded image, no fictitious pagination.
- TXT/Markdown: UTF-8/BOM/UTF-16, blank spans/line mapping, heading/table/unresolved link, invalid encoding/binary.
- CSV: header/no-header, duplicate labels, semicolon/tab, quoted newline/delimiter, zeros/precision/empties, >200 rows, ragged/malformed/ambiguous cases.
- XLSX: overlapping A1 in two sheets, hidden/merged/sparse content, zero/blank/date/percent, formula with/without cache, stale dimensions, drawing/chart inventory.
- PNG/JPEG: known OCR text, oriented JPEG, textless image, wrong signature/extension/corrupt decode. Passing samples do not establish general OCR accuracy.
- Sets: PDF+CSV+DOCX, repeated local IDs/section names, same name/different bytes, identical bytes/aliases/options conflicts, one failed member among valid files.

Acceptance gates:

1. Every promised format runs a real adapter fixture, round-trips strict schemas and resolves every retained item/cell/asset to actual member bytes/locations. Complete/partial/unknown extraction is accurately labeled.
2. Mismatches/corruption/runtime failures are actionable per file; preserve other results without silently changing deck membership.
3. Intake/enqueue executes zero parser/provider calls. Legacy requests/databases/jobs read/migrate; invalid sets fail atomically. Existing one-worker/SSE/cancellation behavior passes.
4. Cache tests cover bytes/options/encoding/delimiter/engine/schema/code changes, tampering/missing files, partial output/cancellation; unchanged hits make zero adapter calls and presentation-only changes do not reparse.
5. Collection grounding rejects foreign-document/cell refs and subject/value swaps. Identical section labels do not mix members/assets. Uncomputed spreadsheet formulas/constants never become metrics.
6. Revisions retain all source snapshots. Real source-grounded fixture generation on Python/PptxGenJS opens/renders in PowerPoint COM; edit/unchanged resume preserve evidence/native editability/hashes/prior revision. Readiness/deep checks retain existing meaning.
7. UI smoke covers selection/dropdown correction, retry, Send capture, reconnect/progress/cancel; backend behavior is automated, not certified by screenshots alone.
8. R01–R06/F01/evaluator regressions pass. Planned command: `python -B -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp ../audit-artifacts/f02/pytest-final --junitxml=../audit-artifacts/f02/pytest-final.xml`; run the new `python scripts/verify_f02_native.py`, CLI help and `git diff --check` after implementation.

Mocks may inject failures/typed model answers; promised-format support needs real parser evidence. Native acceptance must run actual validation/rendering/publication and label model fixtures. Record commit/dirty source-bundle hashes, original/parser/collection/PPTX hashes, runtime/model identity, logs and unrun checks in `C:/Users/thang/Projects/PPTAI/audit-artifacts/f02/`. Update CURRENT_STATE/MODULE_STATUS/modules.json together only after actual runtime evidence, with exact scope. **This was the pre-implementation plan; runtime evidence below now records scoped F02 verification.**

## 11. Pending decision and primary API references

Q11 remains pending: maximum files/pages/scans, workbook rows/cells and upload sizes. Inherited/configurable limits allow implementation to proceed; an agreed workload is still needed before scale/performance claims. Pending preference does not introduce approval requirements.

API details were checked against installed source and primary documentation on 13 October 2026. Docling's [supported formats](https://docling-project.github.io/docling/usage/supported_formats/) do not expand Q05 scope. Its [pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/) inform OCR configuration; exact version behavior requires fixtures. The [openpyxl reader API](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html) distinguishes formula reads from stored results; these are not fresh recalculation. References inform the plan, not verification evidence.

## F02 runtime evidence — 13 October 2026

F02 is **VERIFIED within local multi-file intake, the eight Q05 structural adapters, raw-v3 provenance/collections, complete-only parser caching, shared API/CLI and the intake DOM workflow**, as uncommitted changes on `multi-agent` base `2fa462dbc775ebba6868e1df5fc08196783549cb`. F01 service/worker and R05 revisions remain the authority. Intake validates actual signatures, OOXML, images and strict decoding without converter/provider calls. Ordered type/options/hash selections are frozen transactionally. A fourth additive SQLite table stores deck membership with a pre-migration database backup. Partial/failed members retain bytes, raw output and diagnostics, block generation, and preserve other member outcomes and successful caches.

- Final full command: `python -B -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp ../audit-artifacts/f02/pytest-final-verified --junitxml=../audit-artifacts/f02/pytest-final-verified.xml` — **362 passed** (299 regressions plus 63 F02 cases). Real adapters run PDF/scanned PDF, DOCX, TXT/BOM, Markdown, CSV, XLSX and PNG/JPEG/textless image fixtures. Counterexamples cover mismatch/encoding correction, malformed/ragged/ambiguous CSV, corrupt/encrypted PDF, missing/tampered source/assets, limits, cancellation, aliases/options conflicts, migration, frozen selections, foreign references and blocked sets. Docling partial/OCR-unavailable failures are injected and labeled. Existing mock JSON CLI inputs now use supported Markdown; four-table and expanded-format expectations reflect the new contract.
- TXT retains decoded text/spans/lines. CSV retains lexical cells, duplicate headers, quoted newline/physical line spans and all records, with 200-row projections. XLSX retains visible/hidden worksheets, actual XML bounds, sparse/merged/A1 locations, numeric lexemes, types/formats, formulas and cached/unverified results; uncomputed formula constants never become evidence. Chart sheets/drawings/pivots remain inventories for F04. DOCX physical pagination stays null. Markdown disables remote/local asset fetching. Images retain original pixels/hash/dimensions, EXIF orientation and OCR page-to-original mappings; the installed backend does not apply EXIF rotation.
- Real **PDF + CSV + DOCX** upload/parse/collection generation, source-bound native table, slide-2 heading edit, pinned downloads and **PowerPoint COM** rendering pass on Python and locked PptxGenJS. Native cells preserve `001`, `1.2300`, zero, blank cells and a quoted newline; the JS edited table preview was inspected. All three exact source/parser/result/record bundles survive editing and prior revision hashes remain valid. Unchanged resume returns the edited revision with **zero generation calls**. Only model answers are typed source-grounded fixtures; parsing, validation, rendering and publication are real. Readiness is **BASIC_CHECKED**, with deep/visual model judging off.
- Python edited PPTX SHA-256: `4d7409c478e4847b6703940b00e18836aa77ac49af84b91c3873dace041193d5`. PptxGenJS: `53fdf07b54f6cf22f97cf2c5e952be2140c0b34325aa4a390b5bef03c056b3fc`. Code/config/test/fixture reproduction bundle SHA-256: `9824697a5b2b4f900b98330c666bebb8eb4d9469df4cd0bbc18e0429a0cf8d0b`. Both native run dependency maps match current runtime source. Evidence: `C:/Users/thang/Projects/PPTAI/audit-artifacts/f02/verification.json`, `source_hashes.json`, `source_bundle.zip`, `pytest-final-verified.log/xml`, `native-final-verified/native_acceptance.json`, `ui-acceptance.json`, `cli-final.log` and `compilation-final.log`.
- The same-origin **`/upload/`** page implements ordered file rows, Auto/validated dropdown, applicable OCR/CSV/encoding controls, retry/replacement/removal, optional parse, Send capture, progress/reconnect and cancel. **13 jsdom DOM checks pass**, separately from actual backend tests; findings render as plain text. CLI help, Python AST compilation and `git diff --check` pass. README has commands/limits; reproduce native acceptance with `scripts/verify_f02_native.py` and DOM checks with `scripts/verify_f02_ui.cjs` (audit-only jsdom 26).
- Limits/unrun checks: Q11 workload remains pending. No large/sparse-workbook capacity, general OCR accuracy/full-document benchmark, CUDA, live-provider, POSIX/LibreOffice/other-Office, external-process HTTP load/soak or cross-browser visual/accessibility certification is claimed. Current text-based generation blocks textless images with `SOURCE_CONTENT_UNAVAILABLE`. F04 richer image/chart/formula interpretation, F03 briefs, F15–F17 draft/review/chat and F18 PDF export remain separate. Existing local-worker/crash-reconciliation limits remain.

No commit, push, merge, branch change or deployment was performed. The user's pre-existing F02 specification edits were preserved.
