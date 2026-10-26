"""Layout/content entry point over the shared scene renderer boundary."""
import json
from pathlib import Path
from renderers.python_primitives import DEFAULT_ASSET_SEARCH_DIRS
from renderers.fitting import fit_scene


class PresentationBuilder:
    def __init__(self, layouts_source, asset_root=None, asset_registry=None, backend="python",
                 theme=None, dynamic_layout=False):
        """``theme`` is a resolved core.theme_engine.ThemeSpec (or None for the
        renderer's built-in neutral defaults). ``dynamic_layout`` enables the
        F13 geometry solver, which re-resolves region boxes from measured
        content and falls back to the catalog on any failure."""
        self.layouts_spec = (json.loads(Path(layouts_source).read_text(encoding="utf-8"))
                             if isinstance(layouts_source, (str, Path)) else layouts_source)
        self.asset_registry = asset_registry
        self.backend = backend
        self.asset_search_dirs = list(DEFAULT_ASSET_SEARCH_DIRS)
        if asset_root is not None:
            root = Path(asset_root)
            self.asset_search_dirs = [root / "images", root / "formulas", root / "tables", root]
        self.theme = theme
        self.dynamic_layout = bool(dynamic_layout)
        self.last_scene = self.last_result = None
        self.warnings = []
        self.fitting_report = {}
        self.layout_report: dict = {}

    def build(self, content_source, output_path=None):
        from renderers.base import legacy_ir2_to_scene
        from renderers.factory import get_renderer
        if isinstance(content_source, (str, Path)):
            content_path = Path(content_source)
            content = json.loads(content_path.read_text(encoding="utf-8"))
            root = content_path.parent / "assets"
            if root.exists():
                self.asset_search_dirs = [root / "images", root / "formulas", root / "tables", root]
        else:
            content = content_source
        # Dynamic theming (F13): inject role-based style tokens at the IR2
        # level; model-authored style keys always win, factual content is
        # untouched, and both renderer backends consume the result.
        theme_flat = {}
        if self.theme is not None:
            from core.theme_engine import apply_theme_to_ir2
            content = apply_theme_to_ir2(content, self.theme)
            theme_flat = self.theme.flat()
        # Dynamic layout (F13): measured per-slide geometry with catalog fallback.
        dynamic_regions = None
        if self.dynamic_layout:
            try:
                from core.layout_engine import DynamicLayoutEngine
                engine = DynamicLayoutEngine(self.layouts_spec, self.asset_search_dirs)
                dynamic_regions, self.layout_report = engine.solve_deck(content)
            except Exception as error:  # Solver defects fall back to the catalog.
                self.layout_report = {"engine": "f13-dynamic-v1", "error": f"{type(error).__name__}: {error}"}
        scene = legacy_ir2_to_scene(content, self.layouts_spec, self.asset_registry, self.asset_search_dirs,
                                     dynamic_regions=dynamic_regions)
        # Deterministic pre-render fitting (F13): scale fonts / prune bullets so
        # text never overflows the resolved layout regions; tables keep every row.
        scene, fit_report = fit_scene(scene)
        self.fitting_report = fit_report.as_dict()
        result = get_renderer(self.backend).render(scene, self.asset_registry, theme_flat,
                                                   output_path or content.get("output_filename", "output.pptx"))
        self.last_scene, self.last_result = scene, result
        self.warnings = [*fit_report.warnings, *result.warnings]
        return self.warnings
