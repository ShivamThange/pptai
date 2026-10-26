"""Immutable artifact bundles published by one compare-and-swap pointer.

Consumers resolve active.json once and read the resulting directory. Root-level
pre-R05 files are historical input, never a second authoritative artifact pair.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infrastructure.utils.artifacts import artifact_lock, atomic_json, file_hash, sha256_value, portable_value


class StaleRevisionError(ValueError):
    pass


def _rebase(value: Any, source: Path, destination: Path) -> Any:
    if isinstance(value, dict):
        return {_rebase(key, source, destination): _rebase(item, source, destination) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase(item, source, destination) for item in value]
    if isinstance(value, str):
        for old, new in ((str(source), str(destination)), (source.as_posix(), destination.as_posix())):
            if value == old or value.startswith(old + "/") or value.startswith(old + "\\"):
                return new + value[len(old):]
        return value
    return value


def copy_bundle(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.lock", "*.tmp", "revision.json"))
    for path in destination.rglob("*.json"):
        if "sources" in path.relative_to(destination).parts or path.name in {"docling_document.json", "structural_ir_snapshot.json", "parse_record.json", "adapter_raw.json"}:
            continue  # Exact original parser projections are reproduction evidence.
        data = json.loads(path.read_text(encoding="utf-8"))
        atomic_json(path, _rebase(data, source.resolve(), destination.resolve()))
    manifest = destination / "run_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in data.get("stages", {}).values():
            output = Path(entry.get("output", ""))
            if output.is_file() and output.is_relative_to(destination.resolve()):
                entry["output_hash"] = file_hash(output)
        atomic_json(manifest, data)


class RevisionStore:
    schema_version = 1

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _pointer(self) -> dict[str, Any] | None:
        pointer = self.root / "active.json"
        if not pointer.exists():
            return None
        data = json.loads(pointer.read_text(encoding="utf-8"))
        if data.get("schema_version") != self.schema_version:
            raise ValueError("Unsupported active revision pointer version")
        return data

    def active_id(self) -> str | None:
        data = self._pointer()
        return data["revision_id"] if data else None

    def path(self, revision_id: str) -> Path:
        if not revision_id or any(c not in "0123456789abcdef" for c in revision_id) or len(revision_id) != 32:
            raise ValueError("Invalid revision ID")
        return self.root / "revisions" / revision_id

    def resolve(self) -> Path:
        pointer = self._pointer()
        if pointer is None:
            raise ValueError("No committed R05 revision. Regenerate a legacy run using --pipeline multi-agent; originals are preserved.")
        revision_id = pointer["revision_id"]
        result = self.path(revision_id)
        if file_hash(result / "revision.json") != pointer.get("record_sha256"):
            raise ValueError("Committed revision record integrity failure")
        self.verify(result)
        return result

    def verify(self, directory: Path) -> dict[str, Any]:
        record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
        if record.get("schema_version") != self.schema_version or record.get("revision_id") != directory.name:
            raise ValueError("Invalid revision record")
        required = {"ppt_content.json", "op_ppt.pptx", "ir1_validated.json", "raw_extraction.json",
                    "chunks.json", "storyboard.json", "quality_report.json", "run_manifest.json", "suggestions.json"}
        if not required.issubset(record["artifacts"]):
            raise ValueError("Incomplete revision record")
        for name, digest in record["artifacts"].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or file_hash(path) != digest:
                raise ValueError(f"Committed revision integrity failure: {name}")
        from domain.evaluation.coverage_ledger import validate_sidecars
        validate_sidecars(directory)
        return record

    def require_base(self, base_revision: str | None) -> Path:
        if not base_revision:
            raise ValueError("base_revision is required for edits; read active.json before editing")
        if self.active_id() != base_revision:
            raise StaleRevisionError("Stale base_revision; reload the active revision before editing")
        return self.resolve()

    def commit(self, work: Path, *, base_revision: str | None, operation: str,
               generation_signature: str | None = None, failpoint: Any = None) -> Path:
        """Stage the entire bundle, verify it, then switch exactly one pointer."""
        revision_id = uuid.uuid4().hex
        destination = self.path(revision_id)
        copy_bundle(work, destination)
        required = ("ppt_content.json", "op_ppt.pptx", "ir1_validated.json", "raw_extraction.json",
                    "chunks.json", "storyboard.json", "quality_report.json", "run_manifest.json")
        if any(not (destination / name).is_file() for name in required):
            raise ValueError("Cannot publish an incomplete revision")
        from infrastructure.ingestion.quality_controller import QualityReport
        from contracts.ir1_schema import ValidatedIR1
        from contracts.ir2_content_schema import TargetIR2Presentation
        from contracts.raw_extraction_schema import RawExtraction
        from contracts.storyboard_schema import Storyboard
        for name, model in (("ir1_validated.json", ValidatedIR1), ("ppt_content.json", TargetIR2Presentation),
                            ("raw_extraction.json", RawExtraction), ("storyboard.json", Storyboard)):
            model.model_validate_json((destination / name).read_text(encoding="utf-8"))
        quality = QualityReport.model_validate_json((destination / "quality_report.json").read_text(encoding="utf-8")).model_dump()
        digest = file_hash(destination / "op_ppt.pptx")
        if quality["artifact_hash"] != digest or quality["readiness"] == "BLOCKED":
            raise ValueError("Revision quality report does not match an accepted PPTX")
        quality["revision_id"] = revision_id
        atomic_json(destination / "quality_report.json", quality)
        manifest = json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("renderer"):
            if manifest["renderer"].get("artifact_hash") != digest:
                raise ValueError("Revision renderer metadata does not match PPTX")
            from renderers.base import PresentationScene
            from renderers.artifact import verify_native_coverage
            scene_data = json.loads((destination / "scene_graph.json").read_text(encoding="utf-8"))
            if manifest.get("assessed_scene_hash") != sha256_value(portable_value(scene_data)):
                raise ValueError("Scene changed after artifact assessment")
            verify_native_coverage(destination / "op_ppt.pptx", PresentationScene.model_validate(scene_data))
        if manifest.get("assessed_ir2_hash") != sha256_value(portable_value(json.loads((destination / "ppt_content.json").read_text(encoding="utf-8")))):
            raise ValueError("IR2 changed after artifact assessment")
        ir1 = json.loads((destination / "ir1_validated.json").read_text(encoding="utf-8"))
        if manifest.get("assessed_ir1_hash") != sha256_value(portable_value(ir1)):
            raise ValueError("IR1 changed after artifact assessment")
        if ir1.get('schema_version') == '4':
            from domain.extraction.asset_registry import AssetRegistry
            registry = AssetRegistry(ir1['assets'], run_root=destination, source_item_ids=ir1['source_item_ids'],
                                     asset_source_items=ir1.get('asset_source_items',[]))
            for asset in registry.assets.values():
                if asset.content:
                    registry.validate_derivation(asset.asset_id)
        for asset in ir1.get("assets", []):
            if asset.get("availability") == "AVAILABLE":
                path = Path(asset.get("file_path", "")).resolve()
                if not path.is_relative_to(destination) or not path.is_file() or file_hash(path) != asset.get("content_sha256"):
                    raise ValueError("Revision source asset integrity failure")
        for image in quality["rendered"]["details"].get("images", []):
            path = Path(image).resolve()
            if not path.is_relative_to(destination) or not path.is_file():
                raise ValueError("Revision preview is missing or outside the bundle")
        manifest.update(revision_id=revision_id, parent_id=base_revision, final_pptx=str(destination / "op_ppt.pptx"),
                        artifact_hash=digest, status=quality["readiness"], readiness=quality["readiness"])
        atomic_json(destination / "run_manifest.json", manifest)
        if not (destination / "suggestions.json").exists():
            atomic_json(destination / "suggestions.json", {"schema_version": 1, "status": "NOT_IMPLEMENTED", "items": []})
        artifacts = {p.relative_to(destination).as_posix(): file_hash(p) for p in destination.rglob("*") if p.is_file()}
        record = {"schema_version": self.schema_version, "revision_id": revision_id, "parent_id": base_revision,
                  "operation": operation, "job_id": manifest.get("job_id"), "created_at": datetime.now(timezone.utc).isoformat(),
                  "generation_signature": generation_signature,
                  "source_hash": manifest.get("structural_hash"), "input_hash": generation_signature,
                  "brief_hash": sha256_value(manifest.get("options", {})),
                  "ir_hashes": {name: sha256_value(portable_value(json.loads((destination / name).read_text(encoding="utf-8"))))
                                for name in ("raw_extraction.json", "ir1_validated.json", "ppt_content.json")},
                  "artifacts": artifacts, "quality_state": quality["readiness"],
                  "renderer": manifest.get("renderer", {"backend": "unknown-legacy", "version": "unknown"})}
        atomic_json(destination / "revision.json", record)
        self.verify(destination)
        if failpoint:
            failpoint("staged", destination)
        with artifact_lock(self.root / ".locks" / "publication.lock"):
            if self.active_id() != base_revision:
                raise StaleRevisionError("Active revision changed while the candidate was being prepared")
            atomic_json(self.root / "active.json", {"schema_version": self.schema_version, "revision_id": revision_id,
                        "record_sha256": file_hash(destination / "revision.json")})
        return destination

    def restore(self, revision_id: str, *, base_revision: str) -> Path:
        target = self.path(revision_id)
        self.verify(target)
        with artifact_lock(self.root / ".locks" / "publication.lock"):
            if self.active_id() != base_revision:
                raise StaleRevisionError("Active revision changed before restore")
            atomic_json(self.root / "active.json", {"schema_version": self.schema_version, "revision_id": revision_id,
                        "record_sha256": file_hash(target / "revision.json")})
        return target

    def job_path(self, job_id: str) -> Path:
        return self.root / "jobs" / (job_id + ".json")

    def recover_jobs(self) -> None:
        """Called under the generation lock. Edit locks distinguish live from abandoned jobs."""
        for path in (self.root / "jobs").glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("status") != "RUNNING":
                continue
            if row.get("operation") == "slide_edit":
                try:
                    with artifact_lock(self.root / ".locks" / ("edit-" + row["job_id"] + ".lock"), blocking=False):
                        self._recover_job(path, row)
                except OSError:
                    continue
            else:
                self._recover_job(path, row)

    def _recover_job(self, path, row):
        active = self.active_id()
        row["status"] = "INTERRUPTED"
        seen = set()
        while active and active not in seen:
            seen.add(active)
            committed = self.verify(self.path(active))
            if committed.get("job_id") == row["job_id"]:
                row.update(status="COMPLETED", revision_id=active)
                break
            active = committed.get("parent_id")
        atomic_json(path, row)


def active_artifacts(output_dir: str | Path) -> Path:
    return RevisionStore(output_dir).resolve()
