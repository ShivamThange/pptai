"""F01 real upload -> Docling PDF -> sequential worker -> PowerPoint acceptance.

Provider answers are typed fixtures. Parsing, rendering, publication, API
downloads, editing and resume run without success mocks. Run at repository root.
"""
import argparse
import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from api.app import create_app
from config.service_settings import ServiceSettings
from config.settings import get_multi_agent_settings
from infrastructure.utils.artifacts import atomic_json, file_hash
from infrastructure.persistence.revisions import RevisionStore
from infrastructure.persistence.jobs import JobStore
from workers.local import LocalWorker
from test_cache_resume_revision_repair import FixtureCaller


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT.parent / "audit-artifacts/f01/native"))
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "attention.pdf"
    if not source.exists():
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 100), "Attention combines values using learned weights.", fontsize=14)
        pdf.save(source)
        pdf.close()
    settings = ServiceSettings(root=root / "service", poll_interval=.05)
    store = JobStore(settings.database)
    callers = []
    def factory(context):
        caller = FixtureCaller(count=4)
        caller.settings = get_multi_agent_settings({})
        callers.append(caller)
        return caller
    worker = LocalWorker(settings, store=store, caller_factory=factory,
                         provider_settings=get_multi_agent_settings({}))
    outcomes = []
    with TestClient(create_app(settings)) as client, worker.lifetime():
        uploaded = client.post("/api/documents", files={"file": (source.name, source.read_bytes(), "application/pdf")})
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()
        submissions = []
        for backend in ("python", "pptxgenjs"):
            request = {"document_id": document["id"], "min_slides": 4, "max_slides": 4,
                       "max_concurrency": 1, "max_repairs_per_slide": 0, "resume": True,
                       "extraction_mode": "source-passages", "renderer": backend}
            submitted = client.post("/api/decks", json=request)
            assert submitted.status_code == 202, submitted.text
            submissions.append((backend, request, submitted.json()))
        assert all(store.get(row[2]["job_id"]).status == "queued" for row in submissions)
        for _ in submissions:
            assert worker.process_next()
        for backend, request, submitted in submissions:
            job = client.get(submitted["status_url"]).json()
            assert job["status"] == "completed", job
            deck_id, result = submitted["deck_id"], job["result"]
            deck_root = store.deck(deck_id)["output_dir"]
            path = RevisionStore(deck_root).resolve()
            quality = json.loads((path / "quality_report.json").read_text(encoding="utf-8"))
            assert quality["rendered"]["status"] == "EVALUATED_PASS", quality
            assert quality["rendered"]["details"]["backend"] == "powerpoint-com", quality
            assert result["readiness"] == "BASIC_CHECKED"
            downloaded = client.get(result["pptx_url"])
            assert downloaded.status_code == 200 and downloaded.content == (path / "op_ppt.pptx").read_bytes()
            for preview in result["previews"]:
                assert client.get(preview["url"]).status_code == 200
            edit = client.post(f"/api/decks/{deck_id}/slides/2/edit", json={
                "instruction": "Use learned weights", "base_revision": result["revision_id"]})
            assert edit.status_code == 202
            # The second initial generation may precede the edit in the queue.
            while store.get(edit.json()["job_id"]).status == "queued":
                assert worker.process_next()
            edit_job = store.get(edit.json()["job_id"])
            assert edit_job.status == "completed", edit_job.public()
            edited_path = RevisionStore(deck_root).resolve()
            edited_quality = json.loads((edited_path / "quality_report.json").read_text(encoding="utf-8"))
            assert edited_quality["rendered"]["status"] == "EVALUATED_PASS"
            resume_request = {key: value for key, value in request.items() if key != "document_id"}
            resume = client.post(f"/api/decks/{deck_id}/generate", json=resume_request)
            before = sum(len(caller.calls) for caller in callers)
            assert worker.process_next()
            resumed = store.get(resume.json()["job_id"])
            assert resumed.status == "completed", resumed.public()
            assert resumed.result["revision_id"] == edited_path.name
            assert sum(len(caller.calls) for caller in callers) == before
            outcomes.append({"backend": backend, "deck_id": deck_id, "initial_job": job,
                             "edited_job": edit_job.public(), "resume_job": resumed.public(),
                             "edited_pptx": str(edited_path / "op_ppt.pptx"),
                             "edited_pptx_sha256": file_hash(edited_path / "op_ppt.pptx"),
                             "preview_sha256": {p: file_hash(p) for p in edited_quality["rendered"]["details"]["images"]},
                             "zero_generation_calls_on_resume": True})
        assert client.get(f"/api/documents/{document['id']}").json()["parsed"]
    atomic_json(root / "native_acceptance.json", {"source_sha256": file_hash(source), "source_pdf": str(source),
                "source_ir_sha256": file_hash(store.document(document["id"])["structural_ir_path"]),
                "provider": "typed fixture (no live provider calls)", "native_renderer": "powerpoint-com",
                "outcomes": outcomes})
    print(json.dumps({"evidence": str(root / "native_acceptance.json"),
                      "edited_sha256": [row["edited_pptx_sha256"] for row in outcomes]}, indent=2))


if __name__ == "__main__":
    main()
