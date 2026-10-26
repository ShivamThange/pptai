"""Bounded Node worker behind the shared scene contract, without fallback."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from core.artifacts import file_hash
from renderers.base import PresentationScene, RenderArtifact, validate_scene_assets
from renderers.artifact import seal_native_metadata, verify_native_coverage

ROOT = Path(__file__).parent / "pptxgenjs"
BASELINE = "3.12.0"


class PptxGenJSRenderer:
    backend = "pptxgenjs"

    def render(self, scene_graph, asset_registry, theme, output_path):
        scene = PresentationScene.model_validate(scene_graph.model_dump() if isinstance(scene_graph, PresentationScene) else scene_graph)
        validate_scene_assets(scene, asset_registry)
        node = shutil.which("node")
        if not node:
            raise RuntimeError("PptxGenJS requires Node.js; select --renderer python explicitly to use Python")
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pptai-node-", dir=target.parent) as directory:
            request, artifact = Path(directory)/"scene.json", Path(directory)/"candidate.pptx"
            request.write_text(json.dumps({"scene": scene.model_dump(mode="json"), "theme": theme or {}}, ensure_ascii=False), encoding="utf-8")
            try:
                process = subprocess.run([node, str(ROOT/"builder.js"), str(request), str(artifact)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("PptxGenJS renderer exceeded its 60 second deadline") from error
            if process.returncode:
                raise RuntimeError("PptxGenJS worker failed: " + process.stderr[-2000:])
            result = json.loads(process.stdout)
            if result.get("version") != BASELINE:
                raise RuntimeError("PptxGenJS version differs from the locked acceptance baseline")
            seal_native_metadata(artifact, scene)
            capabilities = verify_native_coverage(artifact, scene)
            os.replace(artifact, target)
        return RenderArtifact(target, self.backend, BASELINE, file_hash(target), tuple(result.get("warnings", [])), capabilities)
