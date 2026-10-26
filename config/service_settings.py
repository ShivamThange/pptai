"""Shared local API/worker storage settings; no pipeline runs on API startup."""
from dataclasses import dataclass
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ServiceSettings:
    root: Path = ROOT / "output" / "service"
    upload_limit_bytes: int = 100 * 1024 * 1024
    poll_interval: float = 1.0
    layouts_path: Path = ROOT / "config" / "ppt_default_layouts.json"
    max_source_files: int | None = None
    max_source_bytes: int | None = None
    max_source_pages: int | None = None
    max_workbook_cells: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "layouts_path", Path(self.layouts_path).resolve())
        if self.upload_limit_bytes < 1 or not math.isfinite(self.poll_interval) or self.poll_interval <= 0:
            raise ValueError("Upload limit and poll interval must be positive")
        for name in ('max_source_files', 'max_source_bytes', 'max_source_pages', 'max_workbook_cells'):
            if getattr(self, name) is not None and getattr(self, name) < 1:
                raise ValueError(name + ' must be positive when configured')

    @property
    def database(self):
        return self.root / "jobs.sqlite3"


def get_service_settings(environ=None):
    from config.settings import resolve_environment
    env = resolve_environment() if environ is None else environ
    return ServiceSettings(
        root=Path(env.get("PPTAI_SERVICE_ROOT", ROOT / "output" / "service")),
        upload_limit_bytes=int(env.get("PPTAI_UPLOAD_LIMIT_BYTES", 100 * 1024 * 1024)),
        poll_interval=float(env.get("PPTAI_POLL_INTERVAL", 1)),
        layouts_path=Path(env.get("PPTAI_LAYOUTS_PATH", ROOT / "config" / "ppt_default_layouts.json")),
        **{name: int(env[key]) if env.get(key) else None for name, key in (
            ('max_source_files', 'PPTAI_MAX_SOURCE_FILES'), ('max_source_bytes', 'PPTAI_MAX_SOURCE_BYTES'),
            ('max_source_pages', 'PPTAI_MAX_SOURCE_PAGES'), ('max_workbook_cells', 'PPTAI_MAX_WORKBOOK_CELLS'))},
    )
