"""F01 queue, service, cancellation and revision concurrency acceptance."""
import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import pytest
from config.service_settings import ServiceSettings
from config.settings import get_multi_agent_settings
from infrastructure.utils.artifacts import atomic_json, file_hash
from application.jobs.job_context import JobContext
from infrastructure.persistence.jobs import JobStore
from infrastructure.llm.llm_client import LLMClient, LLMCancelledError, LLMBudgetError, RpmLimiter
from infrastructure.persistence.revisions import RevisionStore, StaleRevisionError
from pipeline import service
from application.pipeline.orchestrator import MultiAgentOptions, run_multi_agent_pipeline
from workers.local import LocalWorker
from test_cache_resume_revision_repair import FixtureCaller, fixture_source, render_fixture

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def queued(tmp_path, monkeypatch):
    settings = ServiceSettings(root=tmp_path / "service", poll_interval=.01)
    store = JobStore(settings.database)
    source = tmp_path / "source.md"
    source.write_text("Attention combines values using learned weights.", encoding="utf-8")
    store.add_document("doc", source.name, source, file_hash(source), source.stat().st_size)
    def parser(source, output, **kwargs):
        fixture_source(Path(output))
    monkeypatch.setattr("pipeline.stage1_docling_parser.run_docling_extraction", parser)
    monkeypatch.setattr("pipeline.quality_controller.render_pptx_slides", render_fixture)
    callers = []
    def factory(context):
        caller = FixtureCaller(count=4)
        callers.append(caller)
        return caller
    worker = LocalWorker(settings, store=store, caller_factory=factory,
                         provider_settings=get_multi_agent_settings({}))
    return settings, store, worker, callers


def submit(settings, store, **options):
    from infrastructure.persistence.jobs import new_id
    deck_id = new_id()
    return store.create_deck("doc", settings.root / "decks" / deck_id,
                              {"min_slides": 4, "max_slides": 4, "max_repairs_per_slide": 0,
                               "max_concurrency": 1, **options}, deck_id=deck_id)


def test_atomic_queue_cancel_claim_and_restart(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    cancelled = store.enqueue("parse", {})
    assert store.cancel(cancelled.id).status == "cancelled"
    assert store.cancel(cancelled.id).status == "cancelled"
    jobs = [store.enqueue("parse", {}) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=6) as executor:
        claimed = list(executor.map(lambda _: store.claim(), range(12)))
    assert len({j.id for j in claimed}) == 12
    assert all(j.status == "running" and j.started_at for j in claimed)
    waiting = store.enqueue("parse", {})
    assert store.fail_interrupted() == 12
    assert store.get(jobs[0].id).error["code"] == "WORKER_INTERRUPTED"
    assert store.claim().id == waiting.id
    with store.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert len(list(db.execute("SELECT name FROM sqlite_master WHERE type='table'"))) == 4
    with pytest.raises(ValueError):
        store.enqueue("invalid", {})


def test_worker_serial_decks_shared_parser_and_singleton(queued, monkeypatch):
    settings, store, worker, callers = queued
    parses = []
    actual_parses = []
    from pipeline import stage1_docling_parser
    extraction = stage1_docling_parser.run_docling_extraction
    def counted_extraction(*args, **kwargs):
        actual_parses.append(args[0])
        return extraction(*args, **kwargs)
    monkeypatch.setattr(stage1_docling_parser, "run_docling_extraction", counted_extraction)
    parser = service.parse_document_cached
    def counted(*args, **kwargs):
        parses.append(args[1])
        return parser(*args, **kwargs)
    monkeypatch.setattr(service, "parse_document_cached", counted)
    first, second = submit(settings, store), submit(settings, store)
    with worker.lifetime():
        with pytest.raises(OSError):
            with LocalWorker(settings, store=store).lifetime():
                pass
        assert worker.process_next()
        assert store.get(first.id).status == "completed" and store.get(second.id).status == "queued"
        assert worker.process_next()
        # Every completed generation auto-queues one evaluation job (F19);
        # drain them before asserting the queue is empty.
        assert worker.process_next() and worker.process_next()
        assert not worker.process_next()
    assert store.get(second.id).status == "completed"
    assert parses[0] == parses[1] == settings.root / "documents" / "doc"
    assert len(actual_parses) == 1
    assert store.deck(first.deck_id)["output_dir"] != store.deck(second.deck_id)["output_dir"]
    assert store.document("doc")["structural_ir_path"]
    for job in (first, second):
        result = store.get(job.id).result
        assert result["readiness"] == "BASIC_CHECKED" and "judge" in result["missing_checks"]
        record = RevisionStore(store.deck(job.deck_id)["output_dir"]).verify(
            Path(store.deck(job.deck_id)["output_dir"]) / "revisions" / result["revision_id"])
        assert record["job_id"] == job.id
        # The auto-queued evaluation completed and wrote its report next to the deck.
        evaluation = [entry for entry in store.deck_jobs(job.deck_id) if entry.kind == "evaluate"]
        assert len(evaluation) == 1 and evaluation[0].status == "completed"
        assert evaluation[0].result["revision_id"] == result["revision_id"]
        assert evaluation[0].result["evaluation"]["metrics"]
        assert (Path(store.deck(job.deck_id)["output_dir"]) / "evaluation"
                / result["revision_id"] / "report.json").is_file()


def test_queued_cancel_executes_nothing_and_running_watcher(queued, monkeypatch):
    settings, store, worker, callers = queued
    cancelled = submit(settings, store)
    store.cancel(cancelled.id)
    live = store.enqueue("parse", {}, document_id="doc")
    entered = threading.Event()
    def parsing(*args, context, **kwargs):
        entered.set()
        assert context.cancel_event.wait(3)
        context.check()
    monkeypatch.setattr(service, "parse_source", parsing)
    with worker.lifetime(), ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(worker.process_next)
        assert entered.wait(3)
        assert store.cancel(live.id).status == "running"
        assert task.result(timeout=5)
    assert store.get(live.id).status == "cancelled" and not callers
    assert store.get(cancelled.id).started_at is None


@pytest.mark.parametrize("cancel", [False, True])
def test_failure_or_cancelled_slide_retains_checkpoints_and_resume(queued, cancel):
    settings, store, worker, callers = queued
    job = submit(settings, store)
    failing = FixtureCaller()
    if cancel:
        failing.cancel_slide = 4
    else:
        failing.fail_slide = 4
    worker.caller_factory = lambda context: failing
    with worker.lifetime():
        worker.process_next()
        assert store.get(job.id).status == ("cancelled" if cancel else "failed")
        deck = store.deck(job.deck_id)
        assert len(list((Path(deck["output_dir"]) / ".cache/slides").glob("*.json"))) == 3
        assert store.document("doc")["structural_ir_path"]
        assert RevisionStore(deck["output_dir"]).active_id() is None
        failing.fail_slide = failing.cancel_slide = None
        resumed = store.enqueue("generate", {**job.request, "resume": True}, document_id="doc", deck_id=job.deck_id)
        before = len(failing.calls)
        worker.process_next()
    assert store.get(resumed.id).status == "completed" and failing.calls[before:] == [4]


def test_stale_generation_edit_and_cancelled_regeneration_preserve_old_revision(queued, monkeypatch):
    settings, store, worker, callers = queued
    initial = submit(settings, store)
    with worker.lifetime():
        worker.process_next()
        base = store.get(initial.id).result["revision_id"]
        deck = store.deck(initial.deck_id)
        edit_request = {"instruction": "Use learned weights", "base_revision": base, "slide_index": 2}
        edit = store.enqueue("edit_slide", edit_request, deck_id=deck["id"], document_id="doc")
        stale_generate = store.enqueue("generate", {**initial.request, "base_revision": base}, deck_id=deck["id"], document_id="doc")
        stale_edit = store.enqueue("edit_slide", edit_request, deck_id=deck["id"], document_id="doc")
        worker.process_next()  # auto-evaluation of the initial revision
        worker.process_next()  # edit
        edited = store.get(edit.id).result["revision_id"]
        worker.process_next()  # stale_generate
        worker.process_next()  # stale_edit
        assert store.get(stale_generate.id).error["code"] == "STALE_REVISION"
        assert store.get(stale_edit.id).error["code"] == "STALE_REVISION"
        assert callers[-1].calls == callers[-2].calls == []
        cancelled = store.enqueue("generate", {**initial.request, "base_revision": edited, "polish": "auto"}, deck_id=deck["id"], document_id="doc")
        original_progress = store.progress
        def progress(job_id, stage, counters):
            original_progress(job_id, stage, counters)
            if stage == "composition":
                store.cancel(job_id)
        monkeypatch.setattr(store, "progress", progress)
        caller = FixtureCaller()
        async def cancel_call(**kwargs):
            raise LLMCancelledError()
        caller.generate_structured_async = cancel_call
        worker.caller_factory = lambda context: caller
        worker.process_next()
        assert store.get(cancelled.id).status == "cancelled"
    assert RevisionStore(deck["output_dir"]).active_id() == edited


def test_cancellation_during_commit_is_completed_with_actual_revision(queued, monkeypatch):
    settings, store, worker, callers = queued
    job = submit(settings, store)
    commit = RevisionStore.commit
    def cancelling_commit(self, *args, **kwargs):
        store.cancel(job.id)
        return commit(self, *args, **kwargs)
    monkeypatch.setattr(RevisionStore, "commit", cancelling_commit)
    with worker.lifetime():
        worker.process_next()
    finished = store.get(job.id)
    assert finished.status == "completed" and finished.cancel_requested
    assert finished.result["revision_id"] == RevisionStore(store.deck(job.deck_id)["output_dir"]).active_id()


def test_billing_safe_error_no_worker_retry_and_next_job_runs(queued, monkeypatch):
    settings, store, worker, callers = queued
    first, second = submit(settings, store), submit(settings, store)
    original = service.generate_deck
    executions = []
    def generate(*args, context, **kwargs):
        executions.append(context.job_id)
        if len(executions) == 1:
            raise LLMBudgetError("secret provider body", error_class="billing", stage="storyboard_planning")
        return original(*args, context=context, **kwargs)
    monkeypatch.setattr(service, "generate_deck", generate)
    with worker.lifetime():
        worker.process_next()
        worker.process_next()
    failure = store.get(first.id)
    assert failure.error["code"] == "LLM_BILLING" and failure.error["stage"] == "storyboard_planning"
    assert "secret" not in json.dumps(failure.public()) and "credits" in failure.error["message"]
    assert executions == [first.id, second.id] and store.get(second.id).status == "completed"


def test_database_failure_aborts_tracking(queued, monkeypatch):
    settings, store, worker, callers = queued
    first, second = submit(settings, store), submit(settings, store)
    def broken(*args):
        raise sqlite3.OperationalError("injected write error")
    monkeypatch.setattr(store, "progress", broken)
    with worker.lifetime(), pytest.raises(sqlite3.OperationalError):
        worker.process_next()
    assert store.get(first.id).status == "running" and store.get(second.id).status == "queued"


def test_injected_settings_and_limiter_history_do_not_share_usage(monkeypatch):
    settings = get_multi_agent_settings({"OPENROUTER_MODEL": "configured", "LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS": "333"})
    limiter = RpmLimiter(10)
    one, two = LLMClient(settings=settings, limiter=limiter), LLMClient(settings=settings, limiter=limiter)
    limiter.acquire()
    monkeypatch.setenv("LLM_KNOWLEDGE_EXTRACTION_OUTPUT_TOKENS", "999")
    assert one.model == two.model == "configured"
    assert two.task_budget("knowledge_extraction").max_output_tokens == 333
    assert one.limiter is two.limiter and len(two.limiter._timestamps) == 1
    assert one.usage is not two.usage


def test_semaphore_rechecks_cancel_before_starting_queued_slide(queued):
    settings, store, worker, callers = queued
    source = fixture_source(settings.root)
    caller = FixtureCaller()
    context = JobContext()
    original = caller.generate_structured_async
    async def cancel_after_first(**kwargs):
        slide = await original(**kwargs)
        context.cancel_event.set()
        return slide
    caller.generate_structured_async = cancel_after_first
    options = MultiAgentOptions(str(ROOT / "config/ppt_default_layouts.json"), str(settings.root / "direct"),
                                min_slides=4, max_slides=4, max_concurrency=1)
    with pytest.raises(LLMCancelledError):
        run_multi_agent_pipeline(source, options, caller=caller, context=context)
    assert [call for call in caller.calls if isinstance(call, int)] == [1]


def test_cancellation_caught_by_optional_judge_still_stops_publication(queued, monkeypatch):
    settings, store, worker, callers = queued
    source = fixture_source(settings.root)
    context = JobContext()
    from pipeline import orchestrator
    assess = orchestrator.assess_final_artifact
    def swallowed(*args, **kwargs):
        result = assess(*args, **kwargs)
        context.cancel_event.set()
        return result
    monkeypatch.setattr(orchestrator, "assess_final_artifact", swallowed)
    options = MultiAgentOptions(str(ROOT / "config/ppt_default_layouts.json"), str(settings.root / "direct"),
                                min_slides=4, max_slides=4, max_concurrency=1)
    with pytest.raises(LLMCancelledError):
        run_multi_agent_pipeline(source, options, caller=FixtureCaller(), context=context)
    assert RevisionStore(options.output_dir).active_id() is None
