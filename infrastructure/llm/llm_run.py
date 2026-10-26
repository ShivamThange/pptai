"""Persist LLM attempts and terminal state while retaining completed stage artifacts."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from infrastructure.utils.artifacts import sha256_value, update_manifest, atomic_json
from infrastructure.llm.llm_client import CallAttempt, LLMUsageLedger


def upgrade_manifest_observability(path: Path) -> None:
    """Version-1 success-only usage cannot reconstruct failed attempts. Preserve it verbatim."""
    if not path.exists():
        return
    original = json.loads(path.read_text(encoding="utf-8"))
    old_usage = original.get("usage", {})
    if old_usage.get("calls") is not None and old_usage.get("schema_version", 1) == 1:
        snapshot = path.with_name(f"{path.stem}.pre-llm-v2.{sha256_value(original)[:12]}.json")
        if not snapshot.exists():
            snapshot.write_bytes(path.read_bytes())
        update_manifest(path, llm_migration={"from": 1, "to": 2, "original_manifest": str(snapshot),
                                            "historical_failed_attempts": "unavailable"})


@contextmanager
def observe_llm_run(client: Any, path: str | Path, *, operation: str = "generation") -> Iterator[None]:
    target = Path(path)
    upgrade_manifest_observability(target)
    usage = getattr(client, "usage", None)
    previous_callback = usage.on_attempt if isinstance(usage, LLMUsageLedger) else None

    def persist(record: CallAttempt) -> None:
        manifest = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        llm_stages = manifest.get("llm_stages", {})
        llm_stages[record.stage] = {"status": record.status, "error_class": record.error_class,
                                  "status_code": record.status_code}
        update_manifest(target, usage=usage.as_dict(), llm_stages=llm_stages)
        for digest, prepared in getattr(client, 'prepared_contexts', {}).copy().items():
            if digest == prepared.request_hash:
                preparation_path = target.parent / 'prepared_contexts' / (digest + '.json')
                if not preparation_path.exists():
                    atomic_json(preparation_path, prepared.model_dump(mode='json'))
        all_calls = {row['call_id']: row for row in prior_context_calls + usage.as_dict()['calls'] if row.get('call_id')}
        atomic_json(target.parent / 'context_calls.json', {'schema_version': 'f07-v1',
            'calls': list(all_calls.values()), 'count_operations': getattr(client, 'count_records', [])})
        coverage_path = target.parent / 'context_coverage.json'
        prepared = getattr(client, 'prepared_contexts', {}).get(record.preparation_hash)
        if coverage_path.exists() and prepared is not None and record.stage != 'knowledge_extraction':
            from contracts.context_schema import CoverageLedger, ContextCallRecord, ContextChunk
            from domain.evaluation.coverage_ledger import record_preparation, record_call_outcome, validate_context_coverage
            from contracts.raw_extraction_schema import RawExtraction
            # Usage callbacks are serialized by LLMUsageLedger's existing lock.
            ledger = CoverageLedger.model_validate_json(coverage_path.read_text(encoding='utf-8'))
            if not any(row.call_id == record.call_id for row in ledger.calls):
                record_preparation(ledger, prepared)
                record_call_outcome(ledger, ContextCallRecord(call_id=record.call_id, attempt=record.attempt,
                    stage=record.stage, scope=prepared.scope, preparation_hash=record.preparation_hash, refs=prepared.refs,
                    dispatch_state='RESPONSE_RECEIVED' if record.response_received else 'DELIVERY_UNKNOWN' if record.transport_started else 'NOT_SENT',
                    outcome=record.status, observed_input_tokens=record.input_tokens, observed_output_tokens=record.output_tokens,
                    error_code=record.error_class))
                if not ledger.legacy_context_unknown:
                    raw = RawExtraction.model_validate_json((target.parent / 'raw_extraction.json').read_text(encoding='utf-8'))
                    chunks = [ContextChunk.model_validate(c) for c in json.loads((target.parent / 'extraction_chunks.json').read_text(encoding='utf-8'))['chunks']]
                    validate_context_coverage(raw, chunks, ledger)
                atomic_json(coverage_path, ledger.model_dump(mode='json'))
        if previous_callback is not None:
            previous_callback(record)

    if isinstance(usage, LLMUsageLedger):
        usage.on_attempt = persist
    metadata = {"provider": getattr(client, "provider", "external-caller"),
                "model": getattr(client, "model", "external-caller")}
    capabilities = getattr(client, "capabilities", None)
    if capabilities is not None:
        metadata["capabilities"] = asdict(capabilities)
    update_manifest(target, status="RUNNING", readiness=None, operation=operation, llm=metadata, terminal_error=None)
    prior_calls_path = target.parent / 'context_calls.json'
    prior_context_calls = json.loads(prior_calls_path.read_text(encoding='utf-8')).get('calls', []) if prior_calls_path.exists() else []
    try:
        yield
    except BaseException as error:
        stage = getattr(error, "stage", None)
        category = getattr(error, "error_class", type(error).__name__)
        status = "CANCELLED" if category == "cancelled" or type(error).__name__ in {"CancelledError", "KeyboardInterrupt"} else "FAILED"
        if status == "CANCELLED" and not stage and isinstance(usage, LLMUsageLedger):
            stage = next((record.stage for record in reversed(usage.records) if record.status == "CANCELLED"), None)
        manifest = json.loads(target.read_text(encoding="utf-8"))
        stages = manifest.get("stages", {})
        aliases = {"knowledge_extraction": "validated_ir1", "storyboard_planning": "storyboard",
                   "slide_composition": "ir2", "slide_repair": "ir2", "vision_audit": "vision_audit"}
        if stage:
            key = "slide_edit" if operation == "slide_edit" else aliases.get(stage, stage)
            # Existing completed artifacts remain on disk; this run's terminal state is separate.
            stages[key] = {**stages.get(key, {}), "status": status, "error_class": category}
        update_manifest(target, status=status, stages=stages,
                        terminal_error={"stage": stage, "error_class": category,
                                        "status_code": getattr(error, "status_code", None)})
        raise
    else:
        manifest = json.loads(target.read_text(encoding="utf-8"))
        update_manifest(target, status=manifest.get("readiness") or "PASSED", terminal_error=None)
    finally:
        if usage is not None:
            update_manifest(target, usage=usage.as_dict())
        if isinstance(usage, LLMUsageLedger):
            usage.on_attempt = previous_callback
