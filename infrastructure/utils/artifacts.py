"""Validated, atomic JSON artifact helpers and run-manifest utilities."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)
_manifest_lock = threading.RLock()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def artifact_lock(path: str | Path, *, blocking: bool = True):
    """OS-owned lock: automatically released even if the owning process crashes."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def dependency_fingerprint(*paths: str) -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {path: file_hash(root / path) for path in paths}


def portable_value(value: Any) -> Any:
    """Artifact locations aren't content; their declared content hashes are."""
    if isinstance(value, dict):
        return {key: portable_value(item) for key, item in value.items() if key not in {"file_path", "path", "json_path", "package_path"}}
    if isinstance(value, list):
        return [portable_value(item) for item in value]
    return value


def caller_fingerprint(caller: Any) -> dict[str, Any]:
    from config.settings import get_multi_agent_settings
    settings = getattr(caller, "settings", None) or get_multi_agent_settings()
    capabilities = getattr(caller, "capabilities", None)
    return {"provider": getattr(caller, "provider", "external-caller"),
            "model": getattr(caller, "model", "external-caller"),
            "caller_version": getattr(caller, "cache_version", type(caller).__qualname__),
            "ir1_batch_input_char_budget": settings.ir1_batch_input_char_budget,
            "context_policy": settings.context_snapshot(),
            "token_counter_version": getattr(getattr(caller, 'token_counter', None), 'cache_version', None),
            "max_attempts": getattr(caller, "max_retries", settings.max_attempts),
            "capabilities": asdict(capabilities) if is_dataclass(capabilities) else str(capabilities),
            "budgets": {stage: asdict(settings.task_budget(stage)) for stage in
                        ("knowledge_extraction", "storyboard_planning", "slide_composition", "slide_repair", "claim_verification", "vision_audit", "faithfulness_judging")}}


class CheckpointCache:
    """Content-addressed payloads with integrity checks; damaged entries are misses."""
    def __init__(self, root: str | Path, *, reuse: bool):
        self.root, self.reuse = Path(root), reuse

    def get(self, key: str) -> Any | None:
        if not self.reuse:
            return None
        try:
            entry = json.loads((self.root / (key + ".json")).read_text(encoding="utf-8"))
            if entry["key"] == key and entry["payload_hash"] == sha256_value(entry["payload"]):
                return entry["payload"]
        except (OSError, ValueError, KeyError):
            pass
        return None

    def put(self, key: str, payload: Any) -> None:
        atomic_json(self.root / (key + ".json"), {"schema_version": 1, "key": key,
                    "payload_hash": sha256_value(payload), "payload": payload})


def _candidate_directory(parent: Path) -> Path:
    """Create our own staging directory instead of ``tempfile.mkdtemp``.

    ``mkdtemp`` requests mode 0700, which on Windows can leave a directory whose
    ACL denies writes to the very process that created it (this breaks the parse
    cache under the Windows sandbox). A normally-created directory inherits the
    parent ACLs and is writable everywhere.
    """
    for _ in range(100):
        candidate = parent / ('.candidate-' + uuid.uuid4().hex[:8])
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise OSError('Could not allocate a unique parsing candidate directory')


def parse_document_cached(source: str | Path, output_dir: str | Path, *, use_gpu=False,
                          resume=False, parser=None, selected_type=None, parse_options=None,
                          upload_spec=None, context=None, limits=None) -> Path:
    """Complete-only staged publication, independent of presentation preferences."""
    from infrastructure.ingestion.router import resolve_options, extract
    from infrastructure.ingestion.validation import validate_ingestion
    from contracts.ingestion_schema import DocumentDescriptor, ParseFinding, ParseResult, IngestionError
    from application.jobs.job_context import check
    from infrastructure.persistence.revisions import _rebase
    source, root = Path(source).resolve(), Path(output_dir).resolve()
    try:
        effective, initial_findings = resolve_options(source, selected_type=selected_type,
            parse_options=parse_options, use_gpu=use_gpu, upload_spec=upload_spec)
    except IngestionError as error:
        from infrastructure.ingestion.detection import EXTENSIONS
        from contracts.ingestion_schema import ResolvedParseOptions, ParseOptions
        kind = EXTENSIONS.get(source.suffix.lower())
        if kind:
            import uuid
            diagnostics = root / 'incomplete' / uuid.uuid4().hex
            diagnostics.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, diagnostics / 'source_snapshot.bin')
            fallback = ResolvedParseOptions(resolved_type=kind, adapter='unresolved',
                requested=ParseOptions.model_validate(parse_options or {}))
            failed = ParseResult(document_id='doc_' + file_hash(source), parse_key=sha256_value({'source':file_hash(source),'request':parse_options,'selected_type':selected_type}),
                status='failed', completeness='unknown', resolved_options=fallback,
                findings=[ParseFinding(code=error.code, severity='error', message=str(error), blocks_generation=True)])
            atomic_json(diagnostics / 'parse_result.json', failed.model_dump(mode='json'))
            error.result = failed.public()
        raise
    adapter = effective.adapter
    code_paths = ['pipeline/ingestion/' + name + '.py' for name in ['detection', 'router', 'validation']]
    code_paths += ['pipeline/ingestion/adapters/common.py', 'pipeline/ingestion/adapters/' + adapter + '.py']
    if adapter == 'image':
        code_paths.append('pipeline/ingestion/adapters/docling.py')
    code_paths += ['pipeline/stage1_docling_parser.py', 'pipeline/source_adapter.py',
                   'schemas/ingestion_schema.py', 'schemas/raw_extraction_schema.py', 'core/artifacts.py']
    code = dependency_fingerprint(*code_paths)
    digest = file_hash(source)
    document_id = 'doc_' + digest
    def identity(options):
        return sha256_value({'source': digest, 'name': source.name, 'options': options.model_dump(mode='json'),
                             'code': code, 'schema': '3', 'limits': {
                                 'pages': getattr(limits, 'max_source_pages', None) if options.resolved_type == 'pdf' else None,
                                 'cells': getattr(limits, 'max_workbook_cells', None) if options.resolved_type == 'xlsx' else None}})
    if parser is not None:
        code['injected_parser'] = getattr(parser, 'cache_version', type(parser).__qualname__)
    key = identity(effective)
    parent = root / '.cache' / 'parsing'
    parent.mkdir(parents=True, exist_ok=True)
    status_path = root / 'parsing_job.json'
    with artifact_lock(root / '.locks' / 'parsing.lock'):
        destination = parent / key
        record = destination / 'parse_record.json'
        if resume and record.is_file():
            try:
                data = json.loads(record.read_text(encoding='utf-8'))
                if data.get('schema_version') == 2 and data.get('input_hash') == key and data.get('status') == 'complete' and all(
                    (destination / name).resolve().is_relative_to(destination) and (destination / name).is_file()
                    and file_hash(destination / name) == h for name, h in data['artifacts'].items()) and {'ir.json', 'source_snapshot.bin', 'parse_result.json'}.issubset(data['artifacts']):
                    validate_ingestion(destination / 'ir.json')
                    check(context)
                    return destination / 'ir.json'
            except (ValueError, KeyError, OSError):
                pass
        candidate = _candidate_directory(parent)
        shutil.copyfile(source, candidate / 'source_snapshot.bin')
        atomic_json(status_path, {'status': 'RUNNING', 'input_hash': key})
        findings = list(initial_findings)
        try:
            check(context)
            if parser is not None:
                parser(str(source), str(candidate), use_gpu=use_gpu)
                ir = json.loads((candidate / 'ir.json').read_text(encoding='utf-8'))
            else:
                ir = extract(source, candidate, effective, context=context, limits=limits)
            check(context)
            # Models downloaded on first conversion become actual cache identity.
            actual, _ = resolve_options(source, selected_type=selected_type, parse_options=parse_options,
                                         use_gpu=use_gpu, upload_spec=upload_spec)
            effective.models = actual.models
            key = identity(effective)
            destination = parent / key
            findings += [ParseFinding.model_validate(f) for f in ir.get('findings', []) if isinstance(f, dict)]
            for finding in findings:
                finding.document_id = document_id
            if str(ir.get('schema_version')) == '3' and not ir.get('blocks') and effective.resolved_type not in {'png', 'jpeg'}:
                findings.append(ParseFinding(code='NO_USABLE_CONTENT', severity='error', document_id=document_id,
                    message='The source contains no usable text or data.', blocks_generation=True))
            partial = any(f.blocks_generation for f in findings)
            counts = {'blocks': len(ir.get('blocks', [])), 'assets': len(ir.get('assets', [])),
                      'source_items': len(ir.get('source_item_ids', []))}
            if str(ir.get('schema_version')) == '3':
                ir['documents'] = [DocumentDescriptor(document_id=document_id, source_sha256=digest, name=source.name,
                    resolved_type=effective.resolved_type, parse_key=key, completeness='partial' if partial else 'complete', counts=counts).model_dump(mode='json')]
                ir['findings'] = [f.model_dump(mode='json') for f in findings]
                atomic_json(candidate / 'ir.json', ir)
                validate_ingestion(candidate / 'ir.json', require_complete=False)
            result = ParseResult(document_id=document_id, parse_key=key, status='partial' if partial else 'complete',
                completeness='partial' if partial else 'complete', structural_artifact=str(candidate / 'ir.json'),
                structural_sha256=file_hash(candidate / 'ir.json'), counts=counts, findings=findings, resolved_options=effective,
                raw_artifacts={p.name: file_hash(p) for p in candidate.iterdir() if p.is_file() and p.name != 'ir.json'})
            atomic_json(candidate / 'parse_result.json', result.model_dump(mode='json'))
            if partial:
                raise IngestionError('SOURCE_SET_INCOMPLETE', 'Source extraction is incomplete; inspect its findings.', result=result.public())
            check(context)
            # Only relocatable projection paths change; exact parser exports stay intact.
            ir = _rebase(ir, candidate, destination)
            atomic_json(candidate / 'ir.json', ir)
            result.structural_artifact = str(destination / 'ir.json')
            result.structural_sha256 = file_hash(candidate / 'ir.json')
            atomic_json(candidate / 'parse_result.json', result.model_dump(mode='json'))
            atomic_json(candidate / 'parse_record.json', {'schema_version': 2, 'input_hash': key, 'status': 'complete',
                'effective_options': effective.model_dump(mode='json'),
                'artifacts': {p.relative_to(candidate).as_posix(): file_hash(p) for p in candidate.rglob('*') if p.is_file()}})
            check(context)
            # Preserve an existing complete entry until the new one is entirely ready.
            import uuid
            prior = parent / ('.previous-' + uuid.uuid4().hex)
            if destination.exists():
                os.replace(destination, prior)
            try:
                os.replace(candidate, destination)
            except BaseException:
                if prior.exists():
                    os.replace(prior, destination)
                raise
            if prior.exists():
                if prior.resolve().parent != parent.resolve():
                    raise ValueError('Parser cache backup escaped the cache directory')
                shutil.rmtree(prior)
            atomic_json(status_path, {'status': 'COMPLETED', 'input_hash': key, 'output': str(destination / 'ir.json')})
            return destination / 'ir.json'
        except BaseException as error:
            if candidate.is_dir():
                if not (candidate / 'parse_result.json').exists():
                    finding = ParseFinding(code='CANCELLED' if getattr(error, 'error_class', None) == 'cancelled' else getattr(error, 'code', 'CORRUPT_SOURCE'), severity='error',
                        message=str(error) if isinstance(error, IngestionError) else 'Source conversion failed; inspect the local parser log.',
                        document_id=document_id, blocks_generation=True)
                    result = ParseResult(document_id=document_id, parse_key=key, status='failed', completeness='unknown',
                        resolved_options=effective, findings=[*findings, finding])
                    atomic_json(candidate / 'parse_result.json', result.model_dump(mode='json'))
                    if isinstance(error, IngestionError):
                        error.result = result.public()
                incomplete = root / 'incomplete' / candidate.name.removeprefix('.candidate-')
                incomplete.parent.mkdir(parents=True, exist_ok=True)
                if (candidate / 'ir.json').is_file():
                    ir = _rebase(json.loads((candidate / 'ir.json').read_text(encoding='utf-8')), candidate, incomplete)
                    atomic_json(candidate / 'ir.json', ir)
                    result = ParseResult.model_validate_json((candidate / 'parse_result.json').read_text(encoding='utf-8'))
                    result.structural_artifact = str(incomplete / 'ir.json')
                    result.structural_sha256 = file_hash(candidate / 'ir.json')
                    atomic_json(candidate / 'parse_result.json', result.model_dump(mode='json'))
                    if isinstance(error, IngestionError):
                        error.result = result.public()
                os.replace(candidate, incomplete)
            atomic_json(status_path, {'status': 'CANCELLED' if getattr(error, 'error_class', None) == 'cancelled' or
                isinstance(error, KeyboardInterrupt) else 'FAILED', 'input_hash': key, 'error': getattr(error, 'code', type(error).__name__)})
            raise


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_validated_json(path: str | Path, model: BaseModel) -> None:
    """Write only a JSON artifact that round-trips through its Pydantic model."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(exclude_none=True)
    type(model).model_validate(payload)
    atomic_json(target, payload)


def read_validated_json(path: str | Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate_json(Path(path).read_text(encoding="utf-8"))


def update_manifest(path: str | Path, **updates: Any) -> dict[str, Any]:
    """Atomically merge run metadata without treating partial files as valid."""

    target = Path(path)
    with _manifest_lock, artifact_lock(target.with_suffix(".lock")):
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        existing.update(updates)
        atomic_json(target, existing)
        return existing
