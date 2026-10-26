"""One persistent sequential worker: python -m workers.local."""
import asyncio
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from config.service_settings import get_service_settings
from config.model_quotas import declared_models
from config.settings import get_multi_agent_settings, resolve_environment
from infrastructure.utils.artifacts import artifact_lock, file_hash
from application.jobs.job_context import JobContext
from infrastructure.persistence.jobs import JobStore
from infrastructure.llm.llm_client import LLMClient, LLMRequestError, RpmLimiter
from infrastructure.llm.context_budget import ContextBudgetError
from infrastructure.persistence.revisions import StaleRevisionError, RevisionStore
from infrastructure.utils.service_artifacts import revision_view, parsing_summary
from pipeline import service
from application.pipeline.orchestrator import MultiAgentOptions
from contracts.service_schema import GenerationRequest, ParseRequest, EditRequest
from contracts.ingestion_schema import IngestionError

log = logging.getLogger(__name__)


def safe_error(error, stage):
    if isinstance(error, ContextBudgetError):
        if error.code == 'MODEL_QUOTA_EXCEEDED':
            return {'code': error.code, 'stage': error.stage or stage,
                    'message': 'A single call exceeds the declared tokens-per-minute quota of the selected model. '
                               'Choose a model with more headroom, then resubmit with resume enabled.',
                    'required': error.required, 'available': error.available}
        return {'code': error.code, 'stage': error.stage or stage,
                'message': 'Context admission or coverage failed. Adjust the configured capacity or narrow the required scope.',
                'required': error.required, 'available': error.available}
    if isinstance(error, StaleRevisionError):
        return {"code": "STALE_REVISION", "stage": stage,
                "message": "The deck changed since submission. Reload its active revision and resubmit."}
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) or getattr(error, "error_class", None) == "cancelled":
        return {"code": "CANCELLED", "stage": stage, "message": "Job cancelled; completed checkpoints and prior revisions are retained."}
    if isinstance(error, LLMRequestError):
        messages = {"billing": "Provider credits are exhausted. Add credits before resubmitting.",
                    "auth": "Provider authentication failed. Check the server API key and permissions.",
                    "deadline": "Provider deadline exceeded. Adjust server budgets or resubmit with resume enabled.",
                    "transient": "Provider is temporarily unavailable. Resubmit with resume enabled.",
                    "quota": ("The selected model hit its declared request or token quota and the window does not "
                              "clear before this call's deadline: " + str(error) +
                              " Pick a model with more headroom or resubmit with resume enabled."),
                    "invalid_request": "Provider rejected the request. Check the server model and capability settings.",
                    "malformed_response": "Provider returned invalid structured output after bounded retries."}
        return {"code": "LLM_" + error.error_class.upper(), "stage": error.stage or stage,
                "message": messages.get(error.error_class, "Provider call failed. Check the local worker log and server configuration.")}
    if isinstance(error, IngestionError):
        return {**error.public(), 'stage': stage}
    if isinstance(error, (ValueError, RuntimeError)):
        # Pipeline refusals (layout, grounding, quality gates) carry the
        # actionable reason; hiding it behind PIPELINE_FAILED made every
        # failure opaque to the UI.
        detail = ' '.join(str(error).split())
        return {"code": "PIPELINE_REJECTED", "stage": stage,
                "message": (detail[:500] or "The pipeline rejected this stage.")}
    return {"code": "PIPELINE_FAILED", "stage": stage,
            "message": "The pipeline could not complete this stage. Check the local worker log; prior revisions are retained."}


class LocalWorker:
    def __init__(self, settings=None, *, store=None, caller_factory=None, provider_settings=None):
        env = resolve_environment()
        self.settings = settings or get_service_settings(env)
        self.store = store or JobStore(self.settings.database)
        self.provider_settings = provider_settings or get_multi_agent_settings(env)
        self._api_keys = {provider: env.get(name, '') for provider, name in
                         [('openrouter', 'OPENROUTER_API_KEY'), ('gemini', 'GEMINI_API_KEY')]}
        self.limiter = RpmLimiter(self.provider_settings.max_calls_per_minute, max_tokens=self.provider_settings.max_tokens_per_minute,
                                  model_quotas=declared_models(self.provider_settings.provider, env))
        self.caller_factory = caller_factory or self._caller

    def _caller(self, context):
        settings = getattr(context, 'provider_settings', self.provider_settings)
        return LLMClient(settings=settings, api_key=self._api_keys[settings.provider], limiter=self.limiter,
                         cancel_event=context.cancel_event)

    @contextmanager
    def lifetime(self):
        with artifact_lock(self.settings.root / ".locks" / "worker.lock", blocking=False):
            self.store.fail_interrupted()
            yield self

    def _execute(self, job, context):
        from config.settings import MultiAgentSettings, ProviderCapabilities
        captured_config = job.request.get('provider_config')
        if captured_config:
            config = dict(captured_config)
            config['capabilities'] = ProviderCapabilities(**config['capabilities'])
            config['model_profiles'] = {key: ProviderCapabilities(**value) for key, value in config.get('model_profiles', {}).items()}
            context.provider_settings = MultiAgentSettings(**config)
        if job.kind == 'edit_slide':
            deck = self.store.deck(job.deck_id)
            request = EditRequest.model_validate({k: v for k, v in job.request.items() if k not in {'slide_index', 'provider_config'}})
            path = service.edit_slide(deck['output_dir'], self.settings.layouts_path, job.request['slide_index'],
                **request.model_dump(), context=context, caller=self.caller_factory(context))
            record = RevisionStore(deck['output_dir']).verify(path.parent)
            return {'deck_id': deck['id'], **revision_view(deck['id'], path.parent, record)}
        document = self.store.document(job.document_id)
        if document is None:
            raise ValueError("Job source no longer exists")
        source = Path(document["source_path"])
        if job.kind == 'parse' and file_hash(source) != document["source_sha256"]:
            raise IngestionError("SOURCE_INTEGRITY_ERROR", "Stored source bytes changed; replace the upload.")
        parse_root = self.settings.root / "documents" / document["id"]
        captured = job.request.get('sources') or (self.store.deck_sources(job.deck_id) if job.deck_id else None)
        captured = captured or self.store.capture_sources([{'document_id': job.document_id}])
        def outcome(identifier, result):
            self.store.parse_outcome(identifier, result)
        def parsed(identifier, path):
            import json
            from contracts.ingestion_schema import ParseResult
            selection = next((s for s in captured if s['document_id'] == identifier), None)
            for upload_id in (selection.get('upload_ids') if selection else None) or [identifier]:
                self.store.parsed(upload_id, path)
                result_path = Path(path).parent / 'parse_result.json'
                if result_path.is_file():
                    result = ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public()
                    outcome(upload_id, {**result, 'upload_id': upload_id})
        primary = captured[0]
        if job.kind == "parse":
            request = ParseRequest.model_validate({k: v for k, v in job.request.items() if k != 'sources'})
            try:
                path = service.parse_source(source, parse_root, use_gpu=request.use_gpu, resume=request.resume,
                    selected_type=primary['selected_type'], parse_options=primary['parse_options'], upload_spec=primary['upload_spec'],
                    limits=self.settings, context=context, on_parsed=lambda path: parsed(document['id'], path))
                result_path = path.parent / 'parse_result.json'
                if result_path.is_file():
                    from contracts.ingestion_schema import ParseResult
                    result = ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public()
                    result['upload_id'] = document['id']
                    outcome(document['id'], result)
                else:
                    result = None
                return {'document_id': document['id'], 'parse_summary': parsing_summary(path), 'parse_result': result}
            except IngestionError as error:
                if error.result:
                    outcome(document['id'], error.result)
                raise
        deck = self.store.deck(job.deck_id)
        caller = self.caller_factory(context)
        if job.kind == "generate":
            request = GenerationRequest.model_validate({k: v for k, v in job.request.items() if k not in {"base_revision", "sources", 'provider_config'}})
            # `model` is provider configuration, already captured in provider_config;
            # the pipeline options know only about scopes, retries and rendering.
            options = MultiAgentOptions(layouts_path=str(self.settings.layouts_path), output_dir=deck["output_dir"],
                                        **request.model_dump(exclude={"model"}))
            if len(captured) > 1:
                members = [{**s, 'parse_root': self.settings.root / 'documents' / s['document_id']} for s in captured]
                path = service.generate_deck_from_sources(members, self.settings.root / 'documents', options,
                    context=context, caller=caller, expected_base_revision=job.request['base_revision'],
                    on_outcome=outcome, on_member_parsed=parsed, limits=self.settings)
            else:
                try:
                    if file_hash(source) != primary['source_sha256']:
                        raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Stored source bytes changed; replace the upload.')
                    path = service.generate_deck(source, parse_root, options, context=context, caller=caller,
                        expected_base_revision=job.request['base_revision'], parse_resume=True,
                        selected_type=primary['selected_type'], parse_options=primary['parse_options'],
                        upload_spec=primary['upload_spec'], limits=self.settings, source_selection=primary,
                        on_parsed=lambda path: parsed(document['id'], path))
                    result_path = Path(self.store.document(document['id'])['structural_ir_path']).parent / 'parse_result.json'
                    if result_path.is_file():
                        from contracts.ingestion_schema import ParseResult
                        outcome(document['id'], ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public())
                except IngestionError as error:
                    if error.result:
                        outcome(document['id'], error.result)
                    raise
        # Use the returned revision, even when cancellation arrived during commit.
        record = RevisionStore(deck["output_dir"]).verify(path.parent)
        return {"deck_id": deck["id"], **revision_view(deck["id"], path.parent, record)}

    def process_next(self):
        """Caller owns the lifetime lock. Database failures abort the worker."""
        job = self.store.claim()
        if job is None:
            return False
        context = JobContext(job.id, lambda stage, counters: self.store.progress(job.id, stage, counters))
        stop = threading.Event()
        watcher_errors = []

        def watch():
            while not stop.is_set():
                try:
                    current = self.store.get(job.id)
                    if current.cancel_requested:
                        context.cancel_event.set()
                        return
                except Exception as error:
                    watcher_errors.append(error)
                    context.cancel_event.set()
                    return
                stop.wait(self.settings.poll_interval)

        watcher = threading.Thread(target=watch, name="cancel-" + job.id, daemon=True)
        watcher.start()
        result, error, status = None, None, "completed"
        interrupted = None
        try:
            context.check()
            result = self._execute(job, context)
        except sqlite3.Error:
            raise  # Never proceed to another job after a failed DB write.
        except (Exception, asyncio.CancelledError, KeyboardInterrupt) as failure:
            current = self.store.get(job.id)
            error = safe_error(failure, current.stage)
            result = getattr(failure, "result", None)
            status = "cancelled" if error["code"] == "CANCELLED" else "failed"
            log.exception("Job %s failed at %s", job.id, current.stage)
            if isinstance(failure, KeyboardInterrupt):
                interrupted = failure
        finally:
            stop.set()
            watcher.join()
        if watcher_errors:
            raise watcher_errors[0]
        self.store.finish(job.id, status, result=result, error=error)
        if interrupted:
            raise interrupted
        return True

    def run(self, stop_event=None):
        stop = stop_event or threading.Event()
        with self.lifetime():
            while not stop.is_set():
                self._heartbeat()
                if not self.process_next():
                    stop.wait(self.settings.poll_interval)

    def _heartbeat(self):
        """Cheap liveness file the API exposes so the UI can show worker state."""
        import time as _time
        try:
            path = self.settings.root / "worker_heartbeat.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"pid": os.getpid(), "timestamp": _time.time()}), encoding="utf-8")
        except OSError:
            pass


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        LocalWorker().run()
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Worker stopped; no additional jobs will be executed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
