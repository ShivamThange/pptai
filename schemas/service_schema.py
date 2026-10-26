"""Public submission contracts. Provider configuration belongs to the server."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from contracts.ingestion_schema import SourceSelection, ParseOptions, SelectedType
from contracts.asset_schema import AssetOptions

JobKind = Literal["parse", "generate", "edit_slide"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParseRequest(RequestModel):
    use_gpu: bool = False
    resume: bool = True
    selected_type: SelectedType | None = None
    parse_options: ParseOptions = Field(default_factory=ParseOptions)


class GenerationRequest(RequestModel):
    asset_options: AssetOptions = Field(default_factory=AssetOptions)
    lens: Literal["executive", "technical", "pitch", "academic"] = "executive"
    min_slides: int = Field(default=5, gt=0)
    max_slides: int = Field(default=10, gt=0)
    max_section_retries: int = Field(default=1, ge=0)
    max_repairs_per_slide: int = Field(default=1, ge=0)
    max_concurrency: int = Field(default=2, gt=0)
    polish: Literal["off", "auto", "all"] = "off"
    deep_verification: bool = False
    semantic_batch_size: int = Field(default=8, gt=0)
    renderer: Literal["python", "pptxgenjs"] = "python"
    extraction_mode: Literal["llm", "source-passages"] = "llm"
    theme: str = "auto"
    dynamic_layout: bool = True
    resume: bool = False
    use_gpu: bool = False
    instruction: str = ""

    @model_validator(mode="after")
    def slide_range(self):
        if self.min_slides > self.max_slides:
            raise ValueError("min_slides must not exceed max_slides")
        if self.theme != "auto":
            from domain.rendering.theme_engine import available_themes
            if self.theme not in available_themes():
                raise ValueError(f"Unknown theme '{self.theme}'. Available: auto, {', '.join(sorted(available_themes()))}")
        return self


class DeckRequest(GenerationRequest):
    document_id: str | None = None
    sources: list[SourceSelection] | None = Field(default=None, min_length=1)

    @model_validator(mode='after')
    def source_set(self):
        if (self.document_id is None) == (self.sources is None):
            raise ValueError('Provide either document_id or sources, never both')
        ids = [s.document_id for s in self.sources or []]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate upload IDs are not allowed')
        return self


class EditRequest(RequestModel):
    instruction: str = Field(min_length=1)
    base_revision: str = Field(pattern=r"^[0-9a-f]{32}$")
    max_repairs: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.instruction.strip():
            raise ValueError("instruction must not be blank")
        return self


class JobRecord(BaseModel):
    id: str
    kind: JobKind
    status: JobStatus
    document_id: str | None
    deck_id: str | None
    request: dict
    stage: str | None
    progress: dict | None
    result: dict | None
    error: dict | None
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None

    def public(self):
        return self.model_dump(exclude={"request"})
