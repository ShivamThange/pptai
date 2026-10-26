"""Public views over R05 artifacts, never a second revision index."""
import json
from pathlib import Path
from infrastructure.utils.artifacts import file_hash
from infrastructure.persistence.revisions import RevisionStore


def published_ancestry(output_dir):
    store = RevisionStore(output_dir)
    if store.active_id() is None:
        return []
    path = store.resolve()
    record = json.loads((path / "revision.json").read_text(encoding="utf-8"))
    rows, seen = [], set()
    while record:
        revision_id = record["revision_id"]
        if revision_id in seen:
            raise ValueError("Cyclic revision ancestry")
        seen.add(revision_id)
        rows.append((path, record))
        parent = record.get("parent_id")
        if not parent:
            break
        path = store.path(parent)
        record = store.verify(path)
    return rows


def published_revision(output_dir, revision_id):
    # A staged (but never committed) directory is deliberately unreachable.
    for path, record in published_ancestry(output_dir):
        if record["revision_id"] == revision_id:
            return path, record
    raise KeyError(revision_id)


def revision_view(deck_id, path, record):
    quality = json.loads((path / "quality_report.json").read_text(encoding="utf-8"))
    base = f"/api/decks/{deck_id}/revisions/{record['revision_id']}"
    previews = []
    for index, image in enumerate(quality["rendered"].get("details", {}).get("images", []), 1):
        candidate = Path(image).resolve()
        if candidate.is_relative_to(path.resolve()) and candidate.is_file():
            previews.append({"slide": index, "url": f"{base}/previews/{index}"})
    checks = {name: quality.get(name, {}).get("status", "NOT_EVALUATED")
              for name in ("deterministic", "factual", "rendered", "judge")}
    sources = []
    manifest_path = path / 'source_manifest.json'
    if manifest_path.is_file():
        from contracts.ingestion_schema import ParseResult
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for member in manifest.get('members', []):
            result_path = (path / member['bundle_directory'] / 'parse_result.json').resolve()
            if not result_path.is_relative_to(path.resolve()):
                raise ValueError('Source result escaped the revision')
            if result_path.is_file():
                result = ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public()
                result['upload_id'] = next(iter(member['document'].get('upload_ids', [])), None)
                sources.append(result)
    context_summary = {'legacy_context_unknown': True}
    if (path / 'context_coverage.json').is_file():
        coverage = json.loads((path / 'context_coverage.json').read_text(encoding='utf-8'))
        context_summary = {key: coverage.get(key) for key in ('parser_completeness', 'context_completeness',
            'semantic_completeness', 'totals', 'legacy_context_unknown')}
    return {"revision_id": record["revision_id"], "parent_id": record.get("parent_id"), 'sources': sources,
            'context_coverage': context_summary,
            "operation": record["operation"], "created_at": record["created_at"],
            "readiness": record["quality_state"], "artifact_sha256": record["artifacts"]["op_ppt.pptx"],
            "checks": checks, "missing_checks": [key for key, status in checks.items()
                                                   if status in {"NOT_EVALUATED", "FAILED_TO_RUN"}],
            "pptx_url": base + "/pptx", "previews": previews}


def parsing_summary(path):
    if not path:
        return None
    path = Path(path)
    try:
        record = json.loads((path.parent / "parse_record.json").read_text(encoding="utf-8"))
        if record["artifacts"].get(path.name) != file_hash(path):
            return {"available": False}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"available": True, "document_name": data.get("document_name"),
                "block_count": len(data.get("blocks", [])), "asset_count": len(data.get("assets", []))}
    except (ValueError, OSError, KeyError):
        return {"available": False}
