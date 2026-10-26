"""Optional progress/cancellation shared by synchronous CLI and queued jobs."""
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Callable
from core.llm_client import LLMCancelledError


@dataclass
class JobContext:
    job_id: str | None = None
    progress_callback: Callable[[str, dict], None] | None = None
    cancel_event: Event = field(default_factory=Event)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _details: dict = field(default_factory=dict, init=False, repr=False)

    def check(self):
        if self.cancel_event.is_set():
            raise LLMCancelledError()

    def report(self, stage, completed=0, total=None, details=None):
        self.check()
        with self._lock:
            self._details.update(details or {})
            if self.progress_callback:
                self.progress_callback(stage, {"completed": completed, "total": total, **self._details})


def check(context):
    if context:
        context.check()


def report(context, stage, completed=0, total=None, details=None):
    if context:
        context.report(stage, completed, total, details)
