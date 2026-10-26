"""Explicit backend choice. Errors never select another renderer implicitly."""
def get_renderer(backend):
    if backend == "python":
        from renderers.python_adapter import PythonRenderer
        return PythonRenderer()
    if backend == "pptxgenjs":
        from renderers.pptxgenjs_adapter import PptxGenJSRenderer
        return PptxGenJSRenderer()
    raise ValueError(f"Unsupported renderer backend: {backend}")


def renderer_fingerprint(backend):
    """Include installed backend versions in resume identity, not just source."""
    get_renderer(backend)
    if backend == "python":
        from importlib.metadata import version
        actual_version = version("python-pptx")
    else:
        import json
        from renderers.pptxgenjs_adapter import ROOT
        package = ROOT / "node_modules/pptxgenjs/package.json"
        actual_version = json.loads(package.read_text(encoding="utf-8"))["version"] if package.is_file() else "NOT_INSTALLED"
    return {"backend": backend, "version": actual_version, "contract": "scene-v1", 'capabilities':['rich-assets-v1']}


def validate_renderer_runtime(backend):
    """Fail before parsing/generation when the selected renderer cannot run."""
    fingerprint = renderer_fingerprint(backend)
    if backend == "pptxgenjs":
        import shutil
        from renderers.pptxgenjs_adapter import BASELINE
        if not shutil.which("node"):
            raise RuntimeError("PptxGenJS requires Node.js on PATH")
        if fingerprint["version"] != BASELINE:
            raise RuntimeError("Install the locked renderer dependencies with: npm.cmd ci --prefix renderers/pptxgenjs --ignore-scripts --no-fund --no-audit")
    return fingerprint
