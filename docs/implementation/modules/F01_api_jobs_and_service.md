# F01 — Shared API, simple jobs, and local worker

Type: **Feature** · Current capability: **Local API, SQLite queue, shared service and sequential worker** · Implementation: **VERIFIED (F01 local scope)** · Phase: **1**

Workflow references: 1, 3, 4, 23a, 27. Dependencies: [R01](R01_llm_gateway_reliability.md), [R05](R05_cache_resume_revision_repair.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), [decisions](../DECISIONS.md), and the two dependency documents first. This is the single implementation document for F01. Paths below resolve under `C:/Users/thang/Projects/PPTAI/BTPs5`.

**Design revision: 12 October 2026; implementation verified 13 October 2026.** The user requested simple local job workers and a smaller SQLite database, with less emphasis on restartability and production infrastructure. This replaces the earlier service design. The design below is implemented within the evidence scope here; unavailable checks and later modules remain explicit.

## Implemented evidence

The shared synchronous service now serves the CLI and one OS-locked sequential worker. FastAPI only stores uploads/requests and reads SQLite or R05 artifacts. PDF/Markdown uploads, document/deck/job endpoints, polling/current-state SSE, cancellation, safe failures, captured-base regeneration, single-slide edits, published ancestry, pinned PPTX and existing previews are wired. API decks reuse the document parsing cache independently of generation resume; CLI parsing follows its existing resume flag. Settings are injected without environment mutation; fresh job callers share the worker limiter while keeping separate usage. Native rendering uses the shared service-root lock. R05 commit remains unchanged, and cancellation during publication can correctly produce completed with the published revision.

On base `965815bc662335f73dea87d2047fa434cd7ea1eb`, **270 baseline / 299 final full-suite tests passed**, with **9 additional final CLI checks** after preserving evaluator YAML precedence. Actual uploaded PDF extraction runs through installed Docling; two distinct deck roots complete sequentially, and Python/PptxGenJS generation/editing/download/preview/zero-call resume pass real PowerPoint COM gates. Typed source-grounded callers supply model answers; no parser/renderer/validator/publication success is mocked in the native run. Readiness is BASIC_CHECKED, optional deep/visual judging off. The final JS edited preview was inspected.

Evidence: `C:/Users/thang/Projects/PPTAI/audit-artifacts/f01/verification.json`, `source_hashes.json`, `pytest-final.log/xml`, `cli-final.log`, `native-final.log` and `native-final/native_acceptance.json`. Source bundle SHA-256 `2ff397cee2ca9c5ef0fe7d82faef88ea564bc25b883a93b3c32bcd84abc65ef2`; edited Python PPTX `b2dc8e84abb2f3b6debbeaf00862fd4b5de9f63b9d792cee0e5cef41ae014193`, JS `d32164ff5bcd86e1cb92fa21681e3131bf042687d1b454b6020bdfccb482e08a`. Run `scripts/verify_f01_native.py` to reproduce; README includes the two-process demo and requests.

No new live-provider/full/scanned-document benchmark, POSIX/LibreOffice/other Office matrix or external-process HTTP soak/load test is claimed. HTTP checks use TestClient and the actual worker implementation. Later input formats, canonical briefs, frontend/chat and validated PDF export remain with F02/F03/F15–F18. The local-disk/cancellation/crash limits in section 10 still apply. No branch change, commit, push, merge or deployment was performed.

## 1. Goal and boundaries

Put the existing pipeline behind one application service. The CLI calls it directly; FastAPI submits jobs to SQLite, and a separate worker executes them sequentially. Requests return promptly, refresh retrieves current progress, and each deck has its own output directory.

Deliver upload storage, existing parsing/generation/single-slide editing, current progress and errors, cooperative cancellation, published revision metadata, previews, and PPTX downloads. F02 still owns expanded format routing, F03 canonical briefs/prompt enhancement, F15–F17 review/edit/chat UI, and F18 validated PDF export. Initially enable PDF and Markdown parsing based on recorded extraction evidence; F02 extends the format list with fixtures. Other confirmed first-release formats remain planned.

Do not add a frontend, distributed queue, authentication system, worker supervisor, per-job process launcher, pause/resume protocol, or automatic crash replay. Provider/model selection stays in server configuration.

## 2. Existing implementation to reuse

Inspected baseline: `multi-agent`, commit `965815bc662335f73dea87d2047fa434cd7ea1eb`; working tree clean before this documentation change. Historical status evidence predates that commit.

| Component | Responsibility retained |
|---|---|
| `core/artifacts.py::parse_document_cached` | Parsing and integrity-checked parser reuse |
| `pipeline/orchestrator.py::run_multi_agent_pipeline` | Generation stages, checkpoints, repairs, and publication |
| `pipeline/slide_editor.py::edit_multi_agent_slide` | Existing 1-based single-slide edit with required base revision |
| `core/revisions.py::RevisionStore` | Immutable bundles, active pointer, integrity, and stale-write checks |
| `core/llm_client.py::LLMClient` | Provider calls, budgets, bounded transport retries, and cancellation |
| `pipeline/slide_renderer.py::render_pptx_slides` | Existing isolated, timeout-bounded native rendering |

Preserve grounding, asset-binding, quality, and revision safeguards. Do not repeat them in API routes or create a second fact/artifact store. Each existing validator keeps its current ownership.

A planning-time targeted run had 68 passes and two failures: a Windows manifest replacement denial and a task-budget assertion affected by configuration carried between CLI tests. Both passed in isolation. This is not a green combined baseline; verify configuration isolation and investigate reproducible filesystem failures during implementation.

## 3. Simple runtime architecture

```text
CLI --------------------> Application service ---> Existing pipeline
                               ^
FastAPI ---> SQLite jobs ---> Local worker
   |
   +-- Current job status / progress / published artifacts
```

Run the demo as two processes:

```powershell
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
python -m workers.local
```

One persistent worker executes one job at a time, calling the synchronous service directly. Parallel slide composition inside a job remains available. Multiple submissions queue without needing parallel workers.

Use the existing OS-owned `artifact_lock` around the worker lifetime to prevent accidentally starting a second worker against the same database. No heartbeat, lease, attempt token, or worker table is required. API startup does not start/recover workers; when the worker is offline, jobs simply remain queued.

`config/service_settings.py` contains the shared data root, upload limit, poll interval, and layout catalog path. Default root: repository `output/service/`, already ignored by Git; allow `PPTAI_SERVICE_ROOT` to override it. API and worker must resolve the same root.

```text
output/service/
  jobs.sqlite3
  documents/<document_id>/source/<safe_filename>
  documents/<document_id>/.cache/parsing/...
  decks/<deck_id>/active.json
  decks/<deck_id>/revisions/...
  decks/<deck_id>/.cache/...
  decks/<deck_id>/.work/...
  decks/<deck_id>/jobs/...
  .locks/worker.lock
  .locks/native-render.lock
```

Retain R05's work/cache layout, including signature-based generation workspaces. Separate deck roots, one worker, and existing generation/publication locks already prevent collisions; per-attempt directory machinery is unnecessary.

## 4. SQLite: three tables

Use standard-library `sqlite3`, WAL mode, foreign keys, and a five-second connection timeout. Open short-lived connections. Never hold a transaction during parsing, provider calls, rendering, or progress streaming. Initialize with `CREATE TABLE IF NOT EXISTS`; no migration framework is needed for the first schema.

```sql
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    structural_ir_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    output_dir TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    document_id TEXT REFERENCES documents(id),
    deck_id TEXT REFERENCES decks(id),
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    stage TEXT,
    progress_json TEXT,
    result_json TEXT,
    error_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at, id);
```

Generate UUID hex IDs and UTC ISO timestamps. Pydantic models/job-store methods validate kinds and statuses; do not duplicate those rules across SQL, routes, and worker code.

- Kinds: `parse`, `generate`, `edit_slide`.
- Statuses: `queued`, `running`, `completed`, `failed`, `cancelled`.
- `request_json`: operation options, captured base revision, and edit instruction/slide where applicable. Sources are immutable uploads referenced through document IDs/hashes. F03 adds canonical brief references when implemented.
- `progress_json`: current counters, e.g. `{ "completed": 3, "total": 4 }`; total may be null.
- `result_json`: parsing summary or published revision ID, readiness, and artifact URLs.
- `error_json`: `code`, `stage`, and a safe message.

No event-history, revision-index, idempotency, provider-quota, lease, or worker tables. Active revisions/readiness come from R05 files rather than a second SQLite copy. No event replay, execution-profile, or retry-lineage schema is needed.

## 5. Shared service and queue flow

Add synchronous operations in `pipeline/service.py`:

```python
parse_source(source_path, parse_root, *, use_gpu=False, resume=True, context=None)
generate_deck(source_path, parse_root, options, *, context=None)
edit_slide(output_dir, layouts_path, slide_index, instruction,
           base_revision, *, max_repairs=1, context=None)
```

Generation owns the CLI's existing sequence: renderer preflight, cached parsing, structural checkpoint, then the current orchestrator. API parsing uses the document root so multiple decks reuse that source's parser output. CLI retains its current output directory as the parsing root. Update `documents.structural_ir_path` after successful parsing, including when generation later fails; this pointer is convenience metadata, not a replacement for parser cache validation.

The optional context contains only a job ID, progress callback, and `threading.Event` cancellation token. Direct CLI callers can supply a console callback or no callback. Retain existing caller injection for tests; do not introduce a dependency container or new orchestration framework.

The worker maps database requests into service operations. HTTP routes only store requests/read results; they never execute the pipeline.

### Worker loop

1. Acquire the worker lifetime lock.
2. At startup, mark leftover `running` rows `failed` with `WORKER_INTERRUPTED` and a finished timestamp. Leave queued rows intact. This is stale-row cleanup, not automatic recovery.
3. In a short `BEGIN IMMEDIATE` transaction, select the oldest queued row and mark it running. Cancellation and claim cannot race that transaction.
4. If no job exists, sleep one second and poll again.
5. Start a cancellation watcher thread for the current job. Poll its flag once per second and set the event when requested; stop/join the watcher when the operation ends.
6. Execute the service operation, persisting stage/progress through its callback.
7. Persist completed, failed, or cancelled status and the result/error, then process the next row.

Ordinary exceptions fail the current job without stopping the worker. If database writes fail, exit with a diagnostic rather than executing additional untracked jobs. No worker-level automatic retry is added. R01 retains transport retries; a user can resubmit generation with `resume=true`, letting R05 reuse matching work. No retry endpoint is required.

### Requests and existing revision behavior

Use request models mirroring current `MultiAgentOptions`: lens, min/max slides, repair counts, concurrency, polish, deep verification, semantic batch size, renderer, extraction mode, and resume. Retain defaults; validate positive counts, `min <= max`, and non-negative repair counts. API callers use the server layout catalog rather than supplying arbitrary file paths. Current min/max bounds remain legacy storyboard semantics, not F03/F10 exact main-content/extras semantics.

`POST /api/decks` creates a new deck and queues first generation in one transaction. Generation includes parsing, so Send does not require a separate parse request.

Regeneration captures the current base revision at submission. Add an optional expected-base argument to the orchestrator and check it inside its existing generation lock, before provider calls. Preserve the default behavior of direct callers that omit it. Edits require the client's explicit base revision and retain existing editor stale checks. An earlier queued mutation changing the base causes `STALE_REVISION`, not silent rebasing. No deck-reservation table or blanket rejection of queued operations is needed.

Pass the service job ID into generation/edit journals through an optional keyword. Direct existing calls still generate their own ID. Retain R05 journals for diagnostics without copying their whole contract into SQLite.

## 6. Current progress and cancellation

Instrument stage boundaries and validated extraction-batch/slide completions. Labels: parsing, structural validation, knowledge extraction, chunking, storyboard, composition, build, quality checks, publication. Cached stages can immediately complete. Quality repair may update the label again; no stage-attempt protocol is needed.

Persist progress on meaningful changes, not per model token. No invented overall percentage is necessary for stages with unknown totals.

Support status polling and a small SSE endpoint. SSE polls the same row once per second, emits a `progress` event when the public snapshot changes, sends a comment heartbeat every 15 seconds, and closes after a terminal snapshot. Start every connection with current state. Reconnect/refresh retrieves the latest snapshot; no event IDs, cursors, replay log, or `Last-Event-ID` support is required. Browser disconnect never cancels a job.

Cancellation is cooperative:

- Queued: mark cancelled immediately and execute nothing.
- Running: set `cancel_requested`; status remains running until the operation exits.
- Check the token before stages, between extraction batches, around slide composition, before rendering, and before publication. A cancelled queued slide task must check again after acquiring its semaphore before starting a call.
- Pass the event into gateway calls so quota/retry waits can stop. Add an optional default cancellation event to `LLMClient`, including multimodal calls, instead of changing every call site's kwargs.
- Retain completed checkpoints and previous committed revisions.
- Docling/rendering may finish the current operation before cancellation takes effect. Do not force-kill them or promise immediate cancellation.

Keep `RevisionStore.commit()` unchanged. Check cancellation immediately before calling it; once commit starts, let atomic publication finish. Cancellation arriving during commit may produce a completed job with the actual published revision. Never label that publication cancelled. Check the token after optional judge calls that catch exceptions so cancellation cannot become a successful incomplete draft.

No pause endpoint, force-stop deadline, `COMMITTING` database state, or SQL/filesystem publication handshake is needed.

## 7. HTTP API

| Endpoint | Behavior |
|---|---|
| `POST /api/documents` | Multipart upload/storage; return 201 |
| `GET /api/documents/{id}` | Source metadata and available parsing summary |
| `POST /api/documents/{id}/parse` | Optional parse-only job; return 202 |
| `POST /api/decks` | Create deck and queue generation; return 202 |
| `POST /api/decks/{id}/generate` | Regenerate/resubmit, optionally with resume; return 202 |
| `POST /api/decks/{id}/slides/{n}/edit` | Current single-slide edit with instruction/base revision; return 202 |
| `GET /api/jobs/{id}` | Current status, stage, counters, result, error |
| `GET /api/jobs/{id}/events` | Current-state SSE stream |
| `POST /api/jobs/{id}/cancel` | Request cancellation and return current job; repeated calls harmless |
| `GET /api/decks/{id}` | Active revision/readiness and related jobs |
| `GET /api/decks/{id}/revisions` | Published active ancestry from R05 |
| `GET /api/decks/{id}/revisions/{rev}` | Published revision metadata/preview URLs |
| `GET /api/decks/{id}/revisions/{rev}/pptx` | Download the pinned published PPTX |
| `GET /api/decks/{id}/revisions/{rev}/previews/{n}` | Existing rendered preview by slide number |

No stub brief/PDF endpoints or capability registry. Add those routes when their modules implement them; unsupported request fields fail normal validation. Submissions return `job_id`, resource IDs, and `status_url`. Completed generation returns the actual revision/readiness; completed execution does not imply `VERIFIED` quality.

Use 404 for missing resources, 409 for stale/not-ready resources, 413 for upload size, 415 for unsupported format, and 422 for invalid options. Provider failures are failed jobs retrieved through a normal 200 status response. Map known gateway errors to actionable billing/auth/deadline messages; omit provider bodies, keys, and stack traces. Log detailed unexpected exceptions locally.

Upload to a generated document directory with a sanitized basename/original extension: strip path components, replace Windows-invalid characters/reserved names, and enforce a configurable default 100 MiB limit while copying. Hash during copying. Rename the temporary file only after upload completion and register it afterward. Failed uploads must not create usable records. No resumable uploads, idempotency keys, or content-addressed upload infrastructure.

Artifact routes derive paths from known published revisions; no client file paths. Resolve/verify the revision once per request using existing helpers. List published ancestry rather than all revision directories, which may include staged candidates. Missing previews remain unavailable. Do not render on download or infer PDF support from preview intermediates. No signed URLs/custom artifact tokens.

## 8. Configuration, CLI, and rendering

The worker uses server provider settings loaded once. API jobs do not mutate environment variables or supply credentials/models. Reuse one worker-local existing `RpmLimiter` across fresh job callers through an optional limiter constructor argument, preserving rate history between sequential jobs. Each caller keeps its own usage ledger. No SQLite provider-quota ledger or execution profiles.

Convert `main.py` to call the service synchronously. Preserve flags, defaults, `--resume`, output paths, and explicit legacy import. CLI does not require HTTP/worker processes. Resolve settings explicitly and inject them rather than mutating shared environment state; retain CLI > existing environment > repository `.env` > defaults precedence. Extraction budgets use injected caller settings when available.

Keep optional evaluation after generation, pinned to the returned revision. Evaluation failure still warns without invalidating a published deck.

One worker serializes API native rendering. Add a shared existing `artifact_lock` around the native-render wrapper so a separate CLI also cannot render concurrently. Use the same service-root setting for the lock. Retain existing subprocess timeouts/cleanup; no Job Objects, PID ownership database, or new process supervisor.

## 9. Implementation sequence

| Step | Files | Work |
|---|---|---|
| 1 | `config/service_settings.py`, `schemas/service_schema.py`, `core/jobs.py` | Settings/models, three tables, CRUD/claim/progress/status |
| 2 | `pipeline/service.py`, `main.py` | Shared operations and compatible CLI wrapper |
| 3 | `pipeline/orchestrator.py`, `pipeline/slide_editor.py`, `pipeline/knowledge_extractor.py`, `pipeline/slide_composer.py` | Optional progress/cancellation/job ID; expected-base check; retain algorithms/caches |
| 4 | `core/llm_client.py`, `config/settings.py`, `pipeline/slide_renderer.py` | Settings/default cancellation/limiter injection; shared render lock |
| 5 | `workers/local.py` | Sequential loop, stale-row cleanup, current-job cancellation watcher |
| 6 | `api/app.py`, `api/routes.py` | Upload/submission/status/SSE/revision/artifact routes |
| 7 | `tests/test_service_jobs.py`, `tests/test_api_jobs.py`, requirements and README | Focused tests, dependencies, demo instructions |

Add FastAPI, Uvicorn, `python-multipart`, and HTTPX test dependencies in service requirements. Multipart was absent from the inspected environment. Retain existing optional native-render dependencies. No broker, ORM, or frontend dependencies.

The implementation followed store/worker, then the uploaded PDF path, then editing/cancellation/SSE. CURRENT_STATE, MODULE_STATUS, and modules.json now record real code/test/native-artifact evidence; future documentation alone must not advance implementation status. No branch switch/commit/push/deployment is implied.

## 10. Verification and deliberate limits

Focused acceptance checks:

1. Upload/generation submission returns before parser/model work completes.
2. Two decks use separate roots and complete through the sequential worker.
3. Refresh/SSE reconnect shows current persisted state; disconnect does not cancel.
4. Queued cancellation executes nothing; running cancellation preserves caches/old revision.
5. Cancellation during publication can correctly produce completed with a published revision.
6. Billing/auth failure reports the stage and actionable error without worker retry.
7. Slide-four failure retains earlier work; explicit resume uses R05 checkpoints.
8. Stale edit/regeneration fails before provider calls and cannot overwrite newer work.
9. Worker restart fails leftover running rows and processes queued rows without replay.
10. CLI/API use the same service; unchanged CLI resume retains zero-work behavior.
11. Settings/usage do not leak between jobs; job callers share limiter history.
12. Unsafe/oversized uploads and arbitrary artifact paths cannot escape resource roots.
13. Published artifact downloads retain visible readiness/missing-check information.

Run existing R01–R06/evaluator regressions with deterministic configuration. Exercise real Docling PDF extraction and real Python-renderer/PowerPoint opening through the worker; a typed caller fixture is acceptable when provider access is unavailable. Exercise JS when locked dependencies are available. Record exact tested commit/source/artifact hashes and real, mocked, or unavailable checks. Fixture success is not live-provider certification.

Do not add an exhaustive crash/power-loss test matrix for this demo. Explicit limits:

- A worker crash can leave a failed job even if a revision was published immediately beforehand. R05 remains artifact authority; inspect the active deck before resubmitting. No SQL/filesystem crash reconciliation.
- Cancellation latency depends on the current operation; no pause or force-stop guarantee.
- Duplicate submissions can create separate jobs. The UI should disable Send while submitting; no exactly-once/idempotency promise.
- One worker/local disk only. Parallel workers and public hosting require a separate design when needed.

**Readiness:** implemented and verified for the simple local service within the evidence above. Multipart is installed, the combined baseline and final suite pass, and the three-table store/sequential worker/native PDF paths are exercised. This status comes from runtime evidence, with the deliberate limits above retained.
