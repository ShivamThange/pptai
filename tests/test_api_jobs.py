"""F01 HTTP submission, current-state SSE and artifact access acceptance."""
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from api.routes import events, safe_filename
from core.artifacts import file_hash
from core.revisions import RevisionStore
from test_service_jobs import queued


@pytest.fixture
def api(queued):
    settings, store, worker, callers = queued
    with TestClient(create_app(settings)) as client:
        yield client, settings, store, worker, callers


def create(client):
    response = client.post("/api/decks", json={"document_id": "doc", "min_slides": 4, "max_slides": 4,
                                               "max_repairs_per_slide": 0, "max_concurrency": 1})
    assert response.status_code == 202
    return response.json()


def test_upload_storage_safe_names_hash_limits_and_no_pipeline_work(api, monkeypatch):
    client, settings, store, worker, callers = api
    def forbidden(*args, **kwargs):
        raise AssertionError("An HTTP submission must not execute the pipeline")
    monkeypatch.setattr("pipeline.service.parse_source", forbidden)
    monkeypatch.setattr("pipeline.service.generate_deck", forbidden)
    content = b"# Attention\nAttention combines values using learned weights."
    uploaded = client.post("/api/documents", files={"file": (r"C:\fakepath\CON.md", content, "text/markdown")})
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["filename"] == "_CON.md" and document["source_sha256"] == hashlib.sha256(content).hexdigest()
    record = store.document(document["id"])
    assert Path(record["source_path"]).is_relative_to(settings.root / "documents" / document["id"])
    assert Path(record["source_path"]).read_bytes() == content
    parse = client.post(f"/api/documents/{document['id']}/parse", json={})
    deck = create(client)
    assert parse.status_code == 202 and store.get(deck["job_id"]).status == "queued" and not callers
    assert client.get(f"/api/documents/{document['id']}").json()["parsed"] is False
    for name in ("file.exe", "bad.md.exe"):
        assert client.post("/api/documents", files={"file": (name, b"data")}).status_code == 415
    small = replace(settings, upload_limit_bytes=4, root=settings.root / "small")
    with TestClient(create_app(small)) as limited:
        assert limited.post("/api/documents", files={"file": ("ok.md", b"1234")}).status_code == 201
        assert limited.post("/api/documents", files={"file": ("large.md", b"12345")}).status_code == 413
        with limited.app.state.store.connection() as db:
            assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert len(list((small.root / "documents").iterdir())) == 1


@pytest.mark.parametrize("options", [{"min_slides": 0}, {"min_slides": 5, "max_slides": 2},
                                        {"max_concurrency": 0}, {"max_repairs_per_slide": -1},
                                        {"model": "client-model"}, {"layouts_path": "C:/arbitrary"},
                                        {"brief": {}}, {"renderer": "unknown"}, {"semantic_batch_size": 0}])
def test_invalid_unsupported_request_fields_fail_validation(api, options):
    client, *_ = api
    assert client.post("/api/decks", json={"document_id": "doc", **options}).status_code == 422


def test_status_terminal_sse_reconnect_cancel_and_missing_resources(api):
    client, settings, store, worker, callers = api
    submitted = create(client)
    status_url = submitted["status_url"]
    assert client.get(status_url).json()["status"] == "queued"
    assert client.post(status_url + "/cancel").json()["status"] == "cancelled"
    assert client.post(status_url + "/cancel").json()["status"] == "cancelled"
    for _ in range(2):
        response = client.get(status_url + "/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert 'event: progress\ndata:' in response.text and '"status": "cancelled"' in response.text
        assert "id:" not in response.text
    assert not worker.process_next() and not callers
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/missing/events").status_code == 404
    assert client.post("/api/jobs/missing/cancel").status_code == 404
    assert client.get("/api/decks/missing").status_code == 404
    assert client.post("/api/decks", json={"document_id": "missing"}).status_code == 404


def test_sse_change_disconnect_and_reconnect_keep_job_running(api):
    client, settings, store, worker, callers = api
    submitted = create(client)
    job = store.claim()
    class Request:
        app = SimpleNamespace(state=SimpleNamespace(store=store, settings=settings))
        async def is_disconnected(self):
            return False
    async def scenario():
        response = await events(job.id, Request())
        iterator = response.body_iterator
        first = await anext(iterator)
        assert '"status": "running"' in first
        store.progress(job.id, "composition", {"completed": 2, "total": 4})
        update = await anext(iterator)
        assert '"completed": 2' in update
        await iterator.aclose()
        assert store.get(job.id).status == "running" and not store.get(job.id).cancel_requested
        reconnect = await events(job.id, Request())
        snapshot = await anext(reconnect.body_iterator)
        assert '"completed": 2' in snapshot
        await reconnect.body_iterator.aclose()
    asyncio.run(scenario())


def test_artifacts_readiness_edits_pinned_history_and_unpublished_rejection(api):
    client, settings, store, worker, callers = api
    submitted = create(client)
    deck_url = f"/api/decks/{submitted['deck_id']}"
    assert client.get(deck_url).json()["active_revision"] is None
    assert client.get(deck_url + "/revisions").json() == []
    with worker.lifetime():
        worker.process_next()
        completed = client.get(submitted["status_url"]).json()
        assert completed["status"] == "completed"
        result = completed["result"]
        metadata_url = deck_url + "/revisions/" + result["revision_id"]
        metadata = client.get(metadata_url).json()
        assert metadata["readiness"] == "BASIC_CHECKED" and "judge" in metadata["missing_checks"]
        download = client.get(result["pptx_url"])
        assert download.status_code == 200 and download.headers["x-pptai-readiness"] == "BASIC_CHECKED"
        assert hashlib.sha256(download.content).hexdigest() == metadata["artifact_sha256"]
        assert "judge" in download.headers["x-pptai-missing-checks"]
        assert len(metadata["previews"]) == 4
        assert client.get(metadata["previews"][0]["url"]).content.startswith(b"\x89PNG")
        assert client.get(metadata_url + "/previews/5").status_code == 404
        assert client.post(deck_url + "/slides/5/edit", json={"instruction": "Change", "base_revision": result["revision_id"]}).status_code == 422
        edit = client.post(deck_url + "/slides/2/edit", json={"instruction": "Use learned weights", "base_revision": result["revision_id"]})
        assert edit.status_code == 202
        # Regeneration captures this older revision and must fail after the queued edit.
        regeneration = client.post(deck_url + "/generate", json={"min_slides": 4, "max_slides": 4})
        worker.process_next()
        worker.process_next()
    edited = client.get(edit.json()["status_url"]).json()
    assert edited["status"] == "completed"
    stale = client.get(regeneration.json()["status_url"]).json()
    assert stale["status"] == "failed" and stale["error"]["code"] == "STALE_REVISION"
    assert client.post(deck_url + "/slides/2/edit", json={"instruction": "Change", "base_revision": result["revision_id"]}).status_code == 409
    ancestry = client.get(deck_url + "/revisions").json()
    assert [row["revision_id"] for row in ancestry] == [edited["result"]["revision_id"], result["revision_id"]]
    assert client.get(result["pptx_url"]).content == download.content
    assert client.get(metadata_url + "/pptx?path=C:/Windows/win.ini").content == download.content
    # A failed/staged candidate directory must never become a downloadable revision.
    candidate = Path(store.deck(submitted["deck_id"])["output_dir"]) / "revisions" / ("a" * 32)
    candidate.mkdir()
    (candidate / "op_ppt.pptx").write_bytes(b"unpublished")
    assert client.get(deck_url + "/revisions/" + "a" * 32 + "/pptx").status_code == 404
    active = RevisionStore(store.deck(submitted["deck_id"])["output_dir"]).resolve()
    (active / "op_ppt.pptx").write_bytes(b"tampered")
    assert client.get(edited["result"]["pptx_url"]).status_code == 409


def test_missing_preview_does_not_render_on_download(api, monkeypatch):
    client, settings, store, worker, callers = api
    from pipeline.slide_renderer import RenderResult
    def unavailable(path, output):
        return RenderResult("FAILED_TO_RUN", [], artifact_hash=file_hash(path), reason="fixture render unavailable")
    monkeypatch.setattr("pipeline.quality_controller.render_pptx_slides", unavailable)
    submitted = create(client)
    with worker.lifetime():
        worker.process_next()
    result = client.get(submitted["status_url"]).json()["result"]
    assert result["readiness"] == "DRAFT_INCOMPLETE" and result["previews"] == []
    assert client.get(result["pptx_url"]).status_code == 200
    assert client.get(result["pptx_url"].replace("/pptx", "/previews/1")).status_code == 404
