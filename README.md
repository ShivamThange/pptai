# PPTAI multi-agent document-to-PowerPoint pipeline

The supported generation path is the multi-agent pipeline: Docling extraction,
source-grounded knowledge, storyboard planning, parallel slide composition,
shared scene rendering, final-artifact checks, and immutable revisions.
The replaced one-shot semantic/planner pipeline has been removed.

Run commands from the repository root. Current verified repair scopes and
remaining feature work are recorded in [the implementation package](docs/implementation/README.md).
See [the cleanup and remaining-work report](docs/implementation/REPOSITORY_CLEANUP.md).

## PPTAI Studio — the web UI

The fastest way to run the pipeline is the local Studio UI: upload documents,
configure lens/extraction/polish/repairs, watch live job progress, and preview
or download the rendered deck. It needs two terminals (API and worker):

```powershell
python -m uvicorn api.app:app --port 8000     # terminal 1: the API + Studio UI
python -m workers.local                        # terminal 2: the pipeline worker
```

Open <http://127.0.0.1:8000/> (redirects to `/studio/`). The header shows
worker liveness and the effective model; jobs stream progress over SSE; each
finished deck shows rendered slide previews, quality-check pills, and a
`.pptx` download. A minimal legacy uploader remains at `/upload/`.

The worker writes a heartbeat the UI reads, so an offline or stale worker is
visible before you submit anything. Jobs survive page reloads: the Studio
re-attaches to any queued/running jobs on load.

## Setup

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-polish.txt
```

Native quality checks require Microsoft PowerPoint with pywin32 on Windows,
or the LibreOffice/PyMuPDF fallback. Configure generation with
`OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, or explicitly use
`LLM_PROVIDER=gemini` with `GEMINI_API_KEY` and `GEMINI_MODEL`.
Provider fallback is disabled by default. Do not commit local `.env` files.

Python is the default renderer. To enable the locked PptxGenJS backend:

```powershell
npm.cmd ci --prefix renderers/pptxgenjs --ignore-scripts --no-fund --no-audit
```

## Generate, resume, and edit

```powershell
python main.py --input "..\paper.pdf" --output-dir output --lens technical --slides-min 6 --slides-max 10
python main.py --input "..\paper.pdf" --output-dir output --lens technical --slides-min 6 --slides-max 10 --resume
python main.py --input "..\paper.pdf" --renderer pptxgenjs --output-dir output-js
```

`--pipeline multi-agent` remains accepted for existing commands; omitting it has
exactly the same behavior. `--pipeline legacy` is rejected before generation.
Use `python main.py --help` for provider, concurrency, repair, optional deep
verification, visual audit, and evaluator options.

### Dynamic theming and layout (F13)

Decks are themed and laid out at build time without touching factual content:

- **Theme** (`--theme`): `auto` (default, resolved from the lens) or one of the
  five validated themes in `config/themes/` — `academic_slate` (the classic
  neutral look), `corporate_blue`, `warm_editorial` (cream + Georgia),
  `dark_tech` (midnight navy), `minimal_mono`. Themes carry background, text,
  accent, surface/border, table header/banding, and chart palette tokens plus
  optional fonts; model-authored styles always win over theme tokens; unknown
  ids are rejected before generation. The active theme is recorded in the run
  manifest and inherited by `--edit-slide`. Each theme also declares validated
  `chrome` (title underline bars, footer rule with deck title and page number,
  cover/closing accent rails, section numerals, quote marks) and `effects`
  (shadow recipe, corner radius, border weight) consumed by both renderer
  backends. Chrome is a pure, never-fatal decoration pass over the resolved
  scene: every element is anchored to existing geometry, skipped (and recorded
  in the builder's `chrome_report`) whenever it would overlap content or leave
  the slide, so theme data can never stall the pipeline or fail a quality gate.
  A theme file without `chrome`/`effects` blocks renders exactly as before.
- **Dynamic layout** (on by default, `--no-dynamic-layout` to disable): after
  composition, a measured solver re-solves each slide's region geometry from
  bounded archetypes (single, split, table-led, cards, bento variants) using
  real text/table/image measurements, enforces font floors, avoids repeating
  the same composition on consecutive slides, and writes a per-slide
  `layout_report.json`. Any solver failure falls back to the fixed catalog
  geometry, and the deterministic pre-render fitting pass still guarantees no
  text overflow.

```powershell
python main.py --input "..\paper.pdf" --output-dir output --lens academic --theme dark_tech
python main.py --input "..\report.docx" --output-dir output2 --theme warm_editorial --no-dynamic-layout
```

In Studio, pick the theme from the dropdown (it lists what each lens would
auto-select) and toggle "Dynamic layout" in the generation settings card.

The CLI loads this repository's `.env` without overriding existing environment
values; explicit CLI settings take precedence. Settings are injected without
changing the process environment. Renderer dependencies are checked
before parsing or making LLM requests. Extraction batch/output/context budgets
can be set with `--ir1-batch-char-budget`, `--ir1-output-tokens`, and
`--llm-context-tokens` (use a verified provider capacity).

`--extraction-mode source-passages` retains exact source passages and table cells
as IR1 instead of asking a model to rewrite them. It runs the same provenance,
numeric and coverage checks and records the mode in the report and resume
identity. Storyboard and slide composition still use the selected live model.
This mode provides BASIC_CHECKED source retention, not semantic verification or
the full planned F05/F07 extraction system. The default remains `llm` extraction.

```powershell
python main.py --input "..\NIPS-2017-attention-is-all-you-need-Paper.pdf" --renderer pptxgenjs --extraction-mode source-passages --llm-provider gemini --llm-model gemini-3.1-flash-lite --llm-max-output-tokens 8192 --llm-context-tokens 1048576 --lens academic --slides-min 8 --slides-max 8 --max-concurrency 1 --max-repairs-per-slide 2 --output-dir ..\audit-artifacts\research-paper-run\run --resume
```

Each accepted deck is published under
`<output-dir>/revisions/<revision-id>/op_ppt.pptx`. Read `active.json` to select
the complete immutable bundle, including IR, scene, checks, renderer metadata,
previews when available, and edit lineage. The mutable root `run_manifest.json`
is a job summary. Resume validates dependencies and hashes; a changed code,
model, layout, source, or renderer dependency invalidates the matching cache.

```powershell
python main.py --edit-slide 2 --instruction "Make the title more concise" --base-revision <active-revision-id> --output-dir output
```

Edits retain their revision renderer and require the active base revision.
Failed rendering or validation preserves the prior revision. Concurrent edits
have one publication winner. `RevisionStore.restore()` selects a verified prior
bundle without deleting history.

`--import-legacy-run` only migrates pre-revision multi-agent artifact folders;
it does not invoke the removed legacy generation pipeline. It preserves originals
and validates/rebuilds through current contracts before publication.

## Render prepared content

The standalone renderer tools are useful for fixtures and externally prepared
content. They use the same scene contract as generation:

```powershell
python -m renderers scene.json deck.pptx --renderer python
node renderers/pptxgenjs/index.js scene.json deck.pptx
```

The current `ir2-layout-v1` adapter expands the layout catalog into resolved
`scene-v1` objects. Native text, tables, charts, shapes, and connectors remain
editable. Images and formulas require real hashed raster assets. Unsupported
objects, ragged tables, missing assets, invalid graphs, and artifact content
loss fail validation. Dynamic measured layouts and Mermaid/Dagre conversion
remain planned in F13/F14. See [renderer documentation](renderers/README.md).

## Local API and worker

The API uses a small SQLite queue. Start these two processes from the repository
root, in separate terminals:

```powershell
python -m pip install -r requirements-service.txt
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
python -m workers.local
```

Open `http://127.0.0.1:8000/upload/` for multi-file intake, or
`http://127.0.0.1:8000/docs` for request schemas and the interactive API.
API startup never launches a worker. Jobs stay queued when the worker is offline;
one persistent worker processes jobs sequentially. A second worker using the same
root exits because the first owns the lifetime lock.

Upload a supported source and submit a deck:

```powershell
curl.exe -F "file=@source.pdf" http://127.0.0.1:8000/api/documents
$body = @{ document_id = "<returned-document-id>"; min_slides = 5; max_slides = 10 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/decks -Method Post -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/api/jobs/<returned-job-id>
curl.exe -N http://127.0.0.1:8000/api/jobs/<returned-job-id>/events
```

Submission returns `job_id`, resource IDs and `status_url` immediately. Generation
includes parsing; a separate `POST /api/documents/{id}/parse` is optional. The SSE
stream starts with the persisted current state, closes at terminal status, and
can be reconnected without an event cursor. Disconnecting does not cancel work.
`POST /api/jobs/{id}/cancel` cancels queued work immediately and requests
cooperative cancellation for running work. Docling or rendering may finish its
current operation first. Publication that has already begun finishes atomically
and can correctly return a completed job despite a cancellation request.

`GET /api/decks/{id}` returns the active published revision and related jobs.
`GET /api/decks/{id}/revisions` returns its published ancestry. Revision metadata
contains readiness, check statuses, missing checks, pinned PPTX and available
preview URLs. Downloads do not render artifacts. Completed execution can be
`BASIC_CHECKED` or `DRAFT_INCOMPLETE`; it does not imply `VERIFIED`.

Regenerate with `POST /api/decks/{id}/generate` using the generation options.
Use `resume: true` to reuse matching checkpoints after a failure. The submitted
base revision is captured automatically. Edit with
`POST /api/decks/{id}/slides/{n}/edit` and an `instruction`, explicit
`base_revision`, and optional non-negative `max_repairs`. Earlier queued mutations
can make later edits/regenerations stale; such jobs fail with `STALE_REVISION`
instead of overwriting a newer revision.

Both processes resolve `PPTAI_SERVICE_ROOT` (default `output/service/`). Optional
server settings: `PPTAI_UPLOAD_LIMIT_BYTES` (default 100 MiB),
`PPTAI_POLL_INTERVAL` (default one second), and `PPTAI_LAYOUTS_PATH`. Keep API,
worker and independent CLI processes on the same service root so their native
render lock is shared. Each uploaded source has one parsing cache; each deck has
its own work/cache/revisions directory. Models, credentials and provider budgets
come from server settings, never API requests. Briefs, draft review, chat and PDF
export remain separate modules.

On worker startup, leftover running jobs become failed with `WORKER_INTERRUPTED`;
queued jobs are retained. There is no automatic replay, pause protocol, worker
supervisor, authentication or public-hosting setup. After a crash, inspect the
active deck before resubmitting: a revision may have been published just before
the SQLite status write was interrupted. Duplicate submissions create separate
jobs. No commit, push or deployment is needed to run the local demo.

Reproduce the typed-fixture native PDF/PowerPoint acceptance (both renderer
backends, upload/download/edit/resume) with `python scripts/verify_f01_native.py`.
Locked JS dependencies and optional native dependencies must be installed.

## Multi-file intake and source routing (F02)

The same API and CLI accept **PDF, DOCX, TXT, Markdown, CSV, XLSX, PNG and JPEG**.
`GET /api/input-formats` publishes extensions, applicable controls, installed adapter
packages and effective limits without loading converters. Uploads validate actual
signatures/OOXML/image bytes and strict text decoding. MIME is advisory. A wrong
binary extension or dropdown produces `TYPE_MISMATCH` with a correction. Text
selection can explicitly resolve TXT/Markdown/CSV ambiguity. Unsupported extensions
remain rejected even when their bytes resemble a supported format.

The `/upload/` page keeps ordered per-file rows, validated type selections, OCR/CSV
controls, encoding correction, retry/replacement/removal, optional parsing, Send,
progress/reconnect and cancellation. It preserves successful uploads when another
file fails. Changes after Send apply to the next submission. Findings and source
content are plain text. The API and worker are separate processes as shown above.

```powershell
curl.exe -F "file=@source.csv" -F "selected_type=csv" http://127.0.0.1:8000/api/documents
curl.exe -F "file=@legacy.txt" -F "encoding=windows-1252" http://127.0.0.1:8000/api/documents
$body = @{ sources = @(@{document_id="<pdf-upload-id>"; parse_options=@{ocr="off"}}, @{document_id="<csv-upload-id>"; parse_options=@{csv_delimiter=",";csv_has_header=$true}}) } | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8000/api/decks -Method Post -ContentType application/json -Body $body
python main.py --input source.pdf --input data.csv --input-type pdf --input-type csv --output-dir output-multi --resume
python main.py --input source.pdf --input data.csv --parse-options-file source-options.json --output-dir output-multi
```

`source-options.json` contains one strict options object per input, for example
`[{"ocr":"off"},{"csv_delimiter":",","csv_has_header":true}]`. Repeated
`--input-type` must likewise match the input count; omission means Auto for all.
The legacy single `--input` and API `document_id` submissions remain supported.
A deck request provides either `document_id` or ordered nonempty `sources`.
Regeneration retains the deck's captured sources/options. Latest parse summaries
never change queued jobs or an existing revision's evidence.

TXT retains decoded characters/spans/lines. CSV retains lexical cells, duplicate
headers, logical records and physical line spans, with 200-row projections. XLSX
reads all worksheets, including hidden sheets, retains A1 coordinates, types,
formats, merges, formulas and stored results, and does not recalculate. Uncomputed
formulas supply no numeric evidence; stored results are labeled cached/unverified.
Charts/pivots/drawings are inventoried for later F04 interpretation. DOCX has item
references with unknown physical pagination. Markdown links are retained without
remote/local fetching. Images retain original pixels, dimensions, orientation and
OCR geometry mappings; a textless image can parse completely while current
text-based knowledge extraction blocks generation with `SOURCE_CONTENT_UNAVAILABLE`.

Every member's exact source, parser exports, parse result/record and assets are
retained under the published revision's `sources/`, with `source_manifest.json`.
Content identities use original byte hashes; upload IDs and names remain aliases.
Identical bytes with matching options collapse; conflicting options fail explicitly.
Partial/corrupt members remain visible and block the whole set with
`SOURCE_SET_INCOMPLETE`; no successful member is silently removed. Complete parser
caches are staged and hash-validated. Rejected or incomplete work stays inspectable
outside reusable entries and preserves prior complete output.

SQLite migrates additively with a `.pre-f02.bak` database backup. Do not downgrade
that database with older code; use the backup and retain upload/revision folders.
Optional positive settings are `PPTAI_MAX_SOURCE_FILES`, `PPTAI_MAX_SOURCE_BYTES`,
`PPTAI_MAX_SOURCE_PAGES` (per PDF) and `PPTAI_MAX_WORKBOOK_CELLS` (per workbook).
Absent values add no product cap; Q11 workload/scale remains pending. The inherited
per-file limit is 100 MiB. CLI uses the same effective limits. PDF/image OCR modes
are `auto`, `off`, `force`, with explicit RapidOCR/ONNX configuration and recorded
model/dependency hashes. `PPTAI_DOCLING_MODEL_DIR` can select a configured local
Docling artifact directory. General OCR accuracy, CUDA and large-workbook workload
capacity are not certified by the small fixtures.

Reproduce real format and API regressions with the full pytest command below,
and multi-source PowerPoint acceptance with `python scripts/verify_f02_native.py`.
Only model answers are typed fixtures in native acceptance; actual parsing, source
bundles, native tables, rendering, editing, downloads and zero-call resume are real.
The DOM intake smoke script is `scripts/verify_f02_ui.cjs` (jsdom 26 installed in
an audit-only directory); backend behavior is independently exercised by pytest.

## Optional evaluation


```powershell
python main.py --input "..\paper.pdf" --evaluate
```

Evaluation uses the active revision's derived `content_analysis.json` projection.
Reports go under `<output-dir>/evaluation/`. The inherited six-metric evaluator
is a partial implementation requiring F19 work; its aggregate score does not
certify the entire planned evaluation protocol. `--eval-no-ai-judging` disables
optional LLM judging. Evaluator provider/model can be configured separately.

For existing decks, use `python -m evalute.cli --help` to prepare references,
evaluate, and compare runs without regenerating the deck.

## Verification and generated files

Install the JS dependencies before running the complete renderer tests:

```powershell
python -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp ..\audit-artifacts\pytest-current
python scripts/verify_r06_native.py --output-dir ..\audit-artifacts\native-current
```

The native acceptance script exercises actual PowerPoint rendering and editable
text/table/chart round trips using typed generation fixtures, with no live LLM.
Keep the regression tests for further development.

`output/`, `output-*/`, Python/pytest caches, and `node_modules/` are generated
and ignored. Dependency manifests and lockfiles are source. Generated run data
can be deleted when no longer needed; it includes revision history and would
need regeneration. Historical verification evidence is retained outside the
Git checkout in `../audit-artifacts/`.
# F07 context budgets and progressive extraction

The shared gateway admits a prepared request containing its actual system/user
contents, transformed response schema, generation settings and media profile.
It reserves stage output plus a margin of `max(512, ceil(capacity * ratio))`:
5% for fully counted requests, 10% for estimated/hybrid requests. Optional input
limits and stage caps lower the remaining input ceiling. A caller's historical
`estimated_input_tokens` hint cannot override measurement.

Set the context policy in your local `.env`, using [.env.example](.env.example)
as a secret-free reference:

```dotenv
LLM_UNKNOWN_CONTEXT_POLICY=configured
LLM_UNKNOWN_CONTEXT_TOKENS=32768
LLM_CONTEXT_POLICY=progressive
LLM_CONTEXT_COUNT_MODE=auto
IR1_SOURCE_TARGET_TOKENS=6000
CONTEXT_TEXT_OVERLAP_TOKENS=0
CONTEXT_MAX_SPLIT_DEPTH=32
```

`32768` is an editable example, not a code default or verified model capacity.
Declare `LLM_CONTEXT_TOKENS` for a verified deployment limit; it wins over the
unknown-capacity value. Omitted/blank unknown capacity fails before counting or
generation. `LLM_UNKNOWN_CONTEXT_POLICY=error` rejects undeclared capacity even
when a fallback value exists. CLI overrides include `--llm-context-tokens`,
`--unknown-context-tokens`, `--context-policy` and `--context-count-mode`.
Precedence remains CLI > environment > repository `.env` > defaults. API jobs
capture non-secret provider/context configuration on submission.

`LLM_<STAGE>_INPUT_TOKENS` adds a ceiling for knowledge extraction, storyboard
planning, slide composition/repair, claim verification, faithfulness judging or
vision audit. Optional `LLM_RUN_MAX_GENERATION_CALLS`,
`LLM_RUN_MAX_RESERVED_TOKENS` and `LLM_MAX_TOKENS_PER_MINUTE` bound transport
attempts and conservative input-plus-output reservations across threads.
`--ir1-batch-char-budget` is deprecated batching/fingerprint metadata; request
measurement is the admission authority.

OpenRouter text admission uses a conservative UTF-8 byte/framing estimate.
Gemini `auto` counts actual contents with the installed Developer API SDK and
estimates system/schema/framing omissions, explicitly labeled **hybrid/estimated**. `estimate`
avoids network counts. `provider_required` fails when complete counting is
unavailable; neither current adapter is falsely labeled exact. Deployments can
inject a tested, versioned complete tokenizer/counter. Model overrides resolve
their own declared profiles, otherwise the explicit unknown-capacity policy.
OpenRouter media requires a versioned deployment image estimator; there is no
universal image-token constant. Gemini can count actual images in `auto` mode.
Base64 transport length is never treated as image tokens.

Extraction packs fitting projections, subdivides oversized text/rows/cells,
keeps original IDs and exact Unicode code-point spans, and checkpoints inspected
outcomes. Numeric clauses/formulas that cannot fit remain explicit failures.
Repeated headers and optional overlap retain context-only identities. Overlap
uses a labeled byte estimate and cannot inflate primary coverage. Original
tables/assets stay intact for rendering. Full input retention, processed spans,
current/historical dispatch, selected evidence and semantic support are reported
separately; context accounting does not upgrade factual verification.

Immutable revisions include `extraction_chunks.json`, `context_chunks.json`,
`context_coverage.json`, sanitized `prepared_contexts/` and `context_calls.json`.
Legacy external callers without the preparation protocol retain explicit
`legacy_context_unknown` accounting. Production CLI/service callers use F07;
`source-passages` records deterministic processing with zero extraction calls.
Edits preserve historical extraction evidence and append their operation calls.
Mandatory edit/fact context is never removed to fit. Unbudgetable judges remain
incomplete; valid JSON with a token-limit finish is rejected as incomplete.

Stable instruction/schema prefixes and changing request suffixes follow the
[OpenAI prompt-caching guidance](https://developers.openai.com/api/docs/guides/prompt-caching).
Counter uncertainty follows the [Claude counting documentation](https://platform.claude.com/docs/en/build-with-claude/token-counting);
adapter behavior references [Gemini counting](https://ai.google.dev/gemini-api/docs/tokens)
and [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting).
Provider cached-input usage is recorded within total input usage, counted once;
it is separate from a no-call local checkpoint reuse.

```powershell
python -B -m pytest tests/test_context_budget_f07.py tests/test_context_chunking_f07.py tests/test_context_coverage_f07.py -q -p no:cacheprovider
python -B -m pytest tests evalute/tests -q -p no:cacheprovider
# Choose a fresh audit directory. Uses real parsers, both renderers and PowerPoint COM.
python -B scripts/verify_f07_native.py --output-dir ../audit-artifacts/f07/native-new
```

# F04 structured asset content

F04 is integrated into `multi-agent`. Generation now defaults to structured asset mode: every usable figure, formula, chart and table is enriched, interpreted in its original document context, and its accepted findings become IR1 units. Use `--asset-mode legacy` for the old raw-asset-only path, or `--asset-understanding off` to disable interpretation explicitly (it does not satisfy contextual semantic acceptance). Keep the configured provider's structured and image capabilities available for `auto`. The same source-grounding, native-artifact and immutable-revision gates apply.

```powershell
python -B main.py --input tests/fixtures/assets/results.csv --asset-mode structured --extraction-mode source-passages --slides-min 2 --slides-max 3 --output-dir output/f04
```

Optional flags: `--describe-assets`, repeatable `--description-asset-id`, `--formula-dpi` and `--asset-min-ppi`. Alt text stays unverified and is independent of source-backed findings. Source-derived findings carry original asset/insight IDs and may support text-only slides. Visual observations retain qualifications; pixel readings cannot create exact native chart datasets. Rich tables preserve lexical values, original worksheet/Word locations and merge boundaries. Native charts support source-bound simple 2D single-axis column/bar/line/area/pie; external references, formula caches and unsupported encodings remain explicit limitations. Mathtext produces PNG/SVG from supported original expressions; equations export as rasters, with original crops or unavailable status for unsupported input.

API generation accepts `asset_options` using `schemas/asset_schema.py`. `chart_mappings` explicitly selects a source table, data rows, category column, series columns and header row; it never edits values. Source IDs must resolve against the captured input. Edits inherit pinned asset options. Inspection only reads published revisions:

- `GET /api/decks/{deck_id}/revisions/{revision_id}/assets?kind=&offset=0&limit=50` (maximum 100)
- `GET /api/decks/{deck_id}/revisions/{revision_id}/assets/detail?asset_id=...` (bounded previews and explicit truncation)
- `GET /api/decks/{deck_id}/revisions/{revision_id}/assets/file?asset_id=...&representation_id=...` (allowlisted, hash-checked bytes)

GETs never call providers or parsers. Unknown/foreign IDs return 404; damaged published bytes return 409. Parser-v3 evidence stays immutable alongside raw/IR1-v4 enrichment. Reproduce F04's synthetic fixtures with `python -B scripts/build_f04_fixtures.py`, native acceptance with `python -B scripts/verify_f04_native.py --output ../audit-artifacts/f04/native`, and representative configured-provider checks with `scripts/verify_f04_live.py --source <native-output>/enriched --output <live-output>`. See `docs/implementation/CURRENT_STATE.md` for exact verification and unavailable checks.
