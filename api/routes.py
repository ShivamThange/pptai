"""Upload, queue, progress and pinned published-artifact endpoints."""
import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, Form, Path as RoutePath
from fastapi.responses import FileResponse, StreamingResponse
from infrastructure.persistence.jobs import new_id, now
from contracts.ingestion_schema import UploadSpec, SourceSelection, IngestionError
from infrastructure.ingestion.detection import detect, EXTENSIONS
from infrastructure.persistence.revisions import RevisionStore, StaleRevisionError
from infrastructure.utils.service_artifacts import published_ancestry, published_revision, revision_view, parsing_summary
from contracts.service_schema import DeckRequest, EditRequest, GenerationRequest, ParseRequest, TERMINAL_STATUSES

router = APIRouter()
SUPPORTED_EXTENSIONS = set(EXTENSIONS)


def safe_filename(filename):
    name = re.split(r"[/\\]", filename or "upload")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem.strip(" .") or "upload"
    if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", stem, re.I):
        stem = "_" + stem
    return stem[:120] + suffix


def resource(request, kind, identifier):
    value = getattr(request.app.state.store, kind)(identifier)
    if value is None:
        raise HTTPException(404, f"{kind.capitalize()} not found")
    return value


def submission(job):
    return {"job_id": job.id, "document_id": job.document_id, "deck_id": job.deck_id,
            "status_url": f"/api/jobs/{job.id}",
            "sources": public_sources(job.request.get("sources", []))}


def public_sources(sources):
    return [{key: source[key] for key in ('document_id', 'filename', 'source_sha256', 'selected_type',
        'resolved_type', 'parse_options', 'upload_ids', 'aliases') if key in source} for source in sources]


def document_view(document):
    summary = parsing_summary(document['structural_ir_path'])
    spec = json.loads(document['upload_spec_json']) if document.get('upload_spec_json') else None
    result = json.loads(document['last_parse_result_json']) if document.get('last_parse_result_json') else None
    return {key: document[key] for key in ('id', 'filename', 'source_sha256', 'size_bytes', 'created_at')} | {
        'parsed': bool(summary and summary['available']), 'parse_summary': summary, 'upload': spec,
        'latest_parse': result, 'completeness': result.get('completeness') if result else 'unknown',
        'readiness': 'PARSED' if result and result['status'] == 'complete' else 'UNPARSED'}


@router.get('/jobs')
def list_jobs(request: Request, limit: int = 50):
    return [job.public() for job in request.app.state.store.recent_jobs(limit)]


@router.get('/decks')
def list_decks(request: Request, limit: int = 100):
    """Lightweight deck listing: no per-deck hash verification (details do that)."""
    store = request.app.state.store
    result = []
    for deck in store.decks(limit):
        active = None
        try:
            active = RevisionStore(deck["output_dir"]).active_id()
        except (ValueError, OSError):
            pass
        document = store.document(deck["document_id"]) or {}
        result.append({"id": deck["id"], "document_id": deck["document_id"],
                       "filename": document.get("filename"), "created_at": deck["created_at"],
                       "active_revision": active})
    return result


@router.get('/worker/status')
def worker_status(request: Request):
    """Heartbeat-based worker liveness for the Studio UI."""
    import time as _time
    settings = request.app.state.settings
    data, age = None, None
    try:
        data = json.loads((settings.root / "worker_heartbeat.json").read_text(encoding="utf-8"))
        age = max(0.0, _time.time() - float(data.get("timestamp", 0)))
    except (OSError, ValueError, TypeError):
        pass
    fresh = age is not None and age < max(30.0, settings.poll_interval * 5)
    busy = any(job.status == "running" for job in request.app.state.store.recent_jobs(200))
    state = "alive" if fresh else ("busy" if busy else "offline")
    if busy and not fresh:
        state = "stale"  # worker died mid-job; restart will fail_interrupted()
    return {"state": state, "pid": (data or {}).get("pid"),
            "age_seconds": round(age, 1) if age is not None else None, "job_running": busy}


@router.get('/config')
def effective_config(request: Request):
    """Non-secret effective provider configuration for the Studio UI."""
    from domain.rendering.theme_engine import available_themes, LENS_THEME_MAP
    from config.settings import resolve_environment
    provider = request.app.state.provider_settings
    return {"provider": provider.provider, "model": provider.model,
            "evaluator": {"provider": provider.evaluator_provider, "model": provider.evaluator_model},
            "max_calls_per_minute": provider.max_calls_per_minute,
            "max_concurrency": provider.max_concurrency,
            "max_output_tokens": provider.capabilities.max_output_tokens,
            "context_tokens": provider.capabilities.context_tokens,
            "strict_section_coverage": provider.strict_section_coverage,
            "max_repairs_per_slide": provider.max_repairs_per_slide,
            "themes": available_themes(),
            "lens_theme_map": LENS_THEME_MAP,
            "api_key_present": bool(resolve_environment().get(
                "OPENROUTER_API_KEY" if provider.provider == "openrouter" else "GEMINI_API_KEY"))}


@router.get('/input-formats')
def input_formats(request: Request):
    import importlib.metadata as metadata
    settings = request.app.state.settings
    def installed(package):
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return None
    formats = []
    for token in dict.fromkeys(EXTENSIONS.values()):
        packages = ['openpyxl'] if token == 'xlsx' else ['docling'] if token in {'pdf', 'docx', 'markdown', 'png', 'jpeg'} else []
        if token in {'png', 'jpeg'}:
            packages += ['Pillow', 'rapidocr']
        if token == 'markdown':
            packages += ['marko']
        versions = {p: installed(p) for p in packages}
        formats.append({'type': token, 'extensions': [e for e, t in EXTENSIONS.items() if t == token],
            'options': ['encoding', 'csv_delimiter', 'csv_has_header'] if token == 'csv' else
                       ['encoding'] if token in {'txt', 'markdown'} else ['ocr'] if token in {'pdf', 'png', 'jpeg'} else [],
            'adapter_available': all(versions.values()), 'versions': versions})
    return {'schema_version': 'input-formats-v1', 'dropdown': ['auto', *dict.fromkeys(EXTENSIONS.values())],
        'formats': formats, 'limits': {name: getattr(settings, name) for name in ('upload_limit_bytes',
            'max_source_files', 'max_source_bytes', 'max_source_pages', 'max_workbook_cells')}}


@router.post('/documents', status_code=201)
def upload_document(request: Request, file: UploadFile = File(...), selected_type: str = Form('auto'), encoding: str = Form('auto')):
    settings, store = request.app.state.settings, request.app.state.store
    filename = safe_filename(file.filename)
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise IngestionError('UNSUPPORTED_TYPE', 'Choose PDF, DOCX, TXT, Markdown, CSV, XLSX, PNG or JPEG.', status=415)
    document_id = new_id()
    directory = settings.root / 'documents' / document_id / 'source'
    directory.mkdir(parents=True)
    temporary, destination = directory / 'upload.tmp', directory / filename
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open('xb') as stream:
            while data := file.file.read(1024 * 1024):
                size += len(data)
                if size > settings.upload_limit_bytes:
                    raise IngestionError('UPLOAD_TOO_LARGE', 'Upload exceeds the configured size limit.', status=413,
                                         details={'limit_bytes': settings.upload_limit_bytes})
                stream.write(data)
                digest.update(data)
        detection = detect(temporary, filename=filename, selected_type=selected_type, encoding=encoding)
        spec = UploadSpec(upload_id=document_id, original_filename=file.filename or filename, display_filename=filename,
            storage_filename=filename, original_extension=Path(file.filename or filename).suffix.lower(),
            source_sha256=digest.hexdigest(), size_bytes=size, client_mime=file.content_type, created_at=now(), **detection)
        os.replace(temporary, destination)
        return document_view(store.add_document(document_id, filename, destination, digest.hexdigest(), size, spec.model_dump(mode='json')))
    except BaseException:
        cleanup = directory.parent.resolve()
        if cleanup.parent == (settings.root / 'documents').resolve() and cleanup.name == document_id:
            shutil.rmtree(cleanup)
        raise
    finally:
        file.file.close()


@router.get("/documents/{document_id}")
def get_document(document_id: str, request: Request):
    return document_view(resource(request, "document", document_id))


@router.post("/documents/{document_id}/parse", status_code=202)
def parse_document(document_id: str, request: Request, options: ParseRequest = ParseRequest()):
    resource(request, "document", document_id)
    return submission(request.app.state.store.enqueue("parse", options.model_dump(), document_id=document_id))


@router.post("/decks", status_code=202)
def create_deck(options: DeckRequest, request: Request):
    selections = options.sources or [SourceSelection(document_id=options.document_id)]
    captured = request.app.state.store.capture_sources(selections)
    settings = request.app.state.settings
    if settings.max_source_files and len(selections) > settings.max_source_files:
        raise IngestionError('SOURCE_FILE_LIMIT', 'Too many files selected.', details={'limit': settings.max_source_files})
    if settings.max_source_bytes and sum(s['size_bytes'] for s in captured) > settings.max_source_bytes:
        raise IngestionError('SOURCE_BYTE_LIMIT', 'Selected sources exceed the configured aggregate byte limit.', details={'limit_bytes': settings.max_source_bytes})
    deck_id = new_id()
    output = request.app.state.settings.root / "decks" / deck_id
    from dataclasses import asdict
    job = request.app.state.store.create_deck(options.document_id, output,
        {**options.model_dump(exclude={"document_id", "sources"}),
         'provider_config': asdict(request.app.state.provider_settings)}, deck_id=deck_id, sources=selections)
    return submission(job)


def active_base(deck):
    store = RevisionStore(deck["output_dir"])
    try:
        if store.active_id():
            return store.resolve().name
        return None
    except (ValueError, OSError):
        raise HTTPException(409, "Published deck integrity check failed") from None


@router.post("/decks/{deck_id}/generate", status_code=202)
def regenerate(deck_id: str, request: Request, options: GenerationRequest = GenerationRequest()):
    deck = resource(request, "deck", deck_id)
    from dataclasses import asdict
    return submission(request.app.state.store.enqueue("generate", {**options.model_dump(), 'provider_config': asdict(request.app.state.provider_settings), "base_revision": active_base(deck), "sources": request.app.state.store.deck_sources(deck_id)},
                                                      deck_id=deck_id, document_id=deck["document_id"]))


@router.post("/decks/{deck_id}/slides/{slide_index}/edit", status_code=202)
def edit(deck_id: str, options: EditRequest, request: Request, slide_index: int = RoutePath(gt=0)):
    deck = resource(request, "deck", deck_id)
    try:
        path = RevisionStore(deck["output_dir"]).require_base(options.base_revision)
    except (StaleRevisionError, ValueError, OSError):
        raise HTTPException(409, "Deck is not ready or the base revision is stale; reload before editing") from None
    content = json.loads((path / "ppt_content.json").read_text(encoding="utf-8"))
    if slide_index > len(content["slides"]):
        raise HTTPException(422, "Slide number is outside the published deck")
    from dataclasses import asdict
    return submission(request.app.state.store.enqueue("edit_slide", {**options.model_dump(), 'provider_config': asdict(request.app.state.provider_settings), "slide_index": slide_index},
                                                      deck_id=deck_id, document_id=deck["document_id"]))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = request.app.state.store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.public()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    job = request.app.state.store.cancel(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.public()


@router.get("/jobs/{job_id}/events")
async def events(job_id: str, request: Request):
    store = request.app.state.store
    if await asyncio.to_thread(store.get, job_id) is None:
        raise HTTPException(404, "Job not found")

    async def stream():
        previous, heartbeat = None, time.monotonic()
        while not await request.is_disconnected():
            job = await asyncio.to_thread(store.get, job_id)
            snapshot = json.dumps(job.public(), sort_keys=True)
            if snapshot != previous:
                yield "event: progress\ndata: " + snapshot + "\n\n"
                previous = snapshot
            if job.status in TERMINAL_STATUSES:
                return
            if time.monotonic() - heartbeat >= 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(request.app.state.settings.poll_interval)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def ancestry(deck):
    try:
        return published_ancestry(deck["output_dir"])
    except (ValueError, OSError, KeyError):
        raise HTTPException(409, "Published deck integrity check failed") from None


def pinned(request, deck_id, revision_id):
    deck = resource(request, "deck", deck_id)
    try:
        return published_revision(deck["output_dir"], revision_id)
    except KeyError:
        raise HTTPException(404, "Published revision not found") from None
    except (ValueError, OSError):
        raise HTTPException(409, "Published deck integrity check failed") from None


@router.get("/decks/{deck_id}")
def get_deck(deck_id: str, request: Request):
    deck = resource(request, "deck", deck_id)
    rows = ancestry(deck)
    return {"id": deck["id"], "document_id": deck["document_id"], "created_at": deck["created_at"],
            "active_revision": revision_view(deck_id, *rows[0]) if rows else None,
            "sources": public_sources(request.app.state.store.deck_sources(deck_id)),
            "jobs": [job.public() for job in request.app.state.store.deck_jobs(deck_id)]}


@router.get("/decks/{deck_id}/revisions")
def revisions(deck_id: str, request: Request):
    deck = resource(request, "deck", deck_id)
    return [revision_view(deck_id, path, record) for path, record in ancestry(deck)]


@router.get("/decks/{deck_id}/revisions/{revision_id}")
def revision(deck_id: str, revision_id: str, request: Request):
    return revision_view(deck_id, *pinned(request, deck_id, revision_id))


def artifact_headers(record):
    return {"X-PPTAI-Readiness": record["quality_state"], "X-PPTAI-Revision": record["revision_id"]}


def asset_registry(request, deck_id, revision_id):
    path,record=pinned(request,deck_id,revision_id)
    from contracts.ir1_schema import ValidatedIR1
    from domain.extraction.asset_registry import AssetRegistry
    try:
        ir1=ValidatedIR1.model_validate_json((path/'ir1_validated.json').read_text(encoding='utf-8'))
        registry=AssetRegistry(ir1.assets,run_root=path,source_item_ids=ir1.source_item_ids,asset_source_items=ir1.asset_source_items)
        return registry,record
    except (ValueError,OSError):
        raise HTTPException(409,'Published asset integrity check failed') from None


@router.get('/decks/{deck_id}/revisions/{revision_id}/assets')
def assets(deck_id: str, revision_id: str, request: Request, kind: str | None=None,
           offset: int=0,limit: int=50):
    from domain.evaluation.asset_inspection import list_assets
    registry,_=asset_registry(request,deck_id,revision_id)
    if kind not in {None,'image','table','formula','chart'} or offset<0 or not 1<=limit<=100:
        raise HTTPException(422,'Invalid asset page parameters')
    return list_assets(registry,kind=kind,offset=offset,limit=limit)


@router.get('/decks/{deck_id}/revisions/{revision_id}/assets/detail')
def asset_detail(deck_id: str, revision_id: str, request: Request, asset_id: str):
    from domain.evaluation.asset_inspection import inspect_asset
    registry,_=asset_registry(request,deck_id,revision_id)
    try:
        return inspect_asset(registry,asset_id)
    except KeyError:
        raise HTTPException(404,'Asset not found') from None
    except (ValueError,OSError):
        raise HTTPException(409,'Published asset integrity check failed') from None


@router.get('/decks/{deck_id}/revisions/{revision_id}/assets/file')
def asset_download(deck_id: str, revision_id: str, request: Request, asset_id: str, representation_id: str):
    from domain.evaluation.asset_inspection import asset_file
    registry,record=asset_registry(request,deck_id,revision_id)
    try:
        path,media=asset_file(registry,asset_id,representation_id)
        return FileResponse(path,media_type=media,filename=path.name,headers=artifact_headers(record))
    except KeyError:
        raise HTTPException(404,'Asset representation not found') from None
    except (ValueError,OSError):
        raise HTTPException(409,'Published asset integrity check failed') from None


@router.get("/decks/{deck_id}/revisions/{revision_id}/pptx")
def pptx(deck_id: str, revision_id: str, request: Request):
    path, record = pinned(request, deck_id, revision_id)
    view = revision_view(deck_id, path, record)
    return FileResponse(path / "op_ppt.pptx", filename=f"{deck_id}-{revision_id}.pptx",
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        headers={**artifact_headers(record), "X-PPTAI-Missing-Checks": ",".join(view["missing_checks"])})


@router.get("/decks/{deck_id}/revisions/{revision_id}/previews/{slide_index}")
def preview(deck_id: str, revision_id: str, request: Request, slide_index: int = RoutePath(gt=0)):
    path, record = pinned(request, deck_id, revision_id)
    quality = json.loads((path / "quality_report.json").read_text(encoding="utf-8"))
    images = quality["rendered"].get("details", {}).get("images", [])
    if slide_index > len(images):
        raise HTTPException(404, "Preview is unavailable")
    image = Path(images[slide_index - 1]).resolve()
    if not image.is_relative_to(path.resolve()) or not image.is_file():
        raise HTTPException(409, "Published preview integrity check failed")
    return FileResponse(image, media_type="image/png", headers=artifact_headers(record))
