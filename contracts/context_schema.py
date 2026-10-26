"""F07 accounting sidecars. Original raw/IR1 evidence remains authoritative."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class StageBudget(ContextModel):
    stage: str
    provider: str
    model: str
    profile_version: str
    declared_context_limit: int | None = Field(default=None, gt=0)
    declared_input_limit: int | None = Field(default=None, gt=0)
    effective_context_limit: int = Field(gt=0)
    capacity_origin: Literal['declared', 'configured_unknown']
    input_ceiling: int = Field(gt=0)
    output_reserve: int = Field(gt=0)
    margin: int = Field(ge=0)
    stage_input_cap: int | None = Field(default=None, gt=0)
    counter_policy: str
    counter_version: str = 'f07-bytes-v1'


class TokenMeasurement(ContextModel):
    input_tokens: int = Field(ge=0)
    method: Literal['provider_count', 'local_tokenizer', 'byte_estimate', 'char_estimate', 'hybrid_estimate']
    certainty: Literal['counted', 'estimated']
    counter_version: str
    included_components: list[str]
    estimated_components: list[str] = Field(default_factory=list)
    request_fingerprint: str
    media_tokens: int | None = Field(default=0, ge=0)
    tool_tokens: int = Field(default=0, ge=0)
    latency_seconds: float = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def certainty_matches_method(self):
        if self.method in {'byte_estimate', 'char_estimate', 'hybrid_estimate'} and self.certainty != 'estimated':
            raise ValueError('Estimated contributions cannot be labeled counted')
        if self.certainty == 'counted' and self.estimated_components:
            raise ValueError('A counted request cannot contain estimated contributions')
        return self


class ContextRef(ContextModel):
    ref_id: str
    document_id: str
    source_id: str
    section_path: list[str]
    representation: Literal['text', 'cell', 'caption', 'formula_text', 'asset_metadata', 'pixels', 'digest', 'inventory']
    source_hash: str
    span: tuple[int, int] | None = None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    projection_hash: str

    @model_validator(mode='after')
    def bounds(self):
        if self.span is not None and not 0 <= self.span[0] <= self.span[1]:
            raise ValueError('Invalid code-point span')
        if self.representation == 'cell' and (self.row is None or self.column is None):
            raise ValueError('Cells require original coordinates')
        return self


class ContextChunk(ContextModel):
    chunk_id: str
    purpose: Literal['extraction', 'retrieval']
    document_ids: list[str]
    section_paths: list[list[str]]
    primary_refs: list[ContextRef]
    context_only_refs: list[ContextRef] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    neighbor_ids: list[str] = Field(default_factory=list)
    digest: str = ''
    projection_hash: str
    measurement: TokenMeasurement | None = None
    state: Literal['PLANNED', 'SUPERSEDED', 'COMPLETE', 'FAILED', 'CANCELLED'] = 'PLANNED'
    findings: list[str] = Field(default_factory=list)


class PreparedContext(ContextModel):
    schema_version: Literal['f07-v1'] = 'f07-v1'
    stage: str
    scope: str = ''
    request_hash: str
    chunk_ids: list[str] = Field(default_factory=list)
    refs: list[ContextRef] = Field(default_factory=list)
    omitted_optional_refs: list[dict[str, str]] = Field(default_factory=list)
    budget: StageBudget
    measurement: TokenMeasurement
    projection_version: str = 'f07-v1'


class ContextCallRecord(ContextModel):
    call_id: str
    attempt: int = Field(ge=1)
    stage: str
    scope: str = ''
    preparation_hash: str
    cache_key: str | None = None
    refs: list[ContextRef] = Field(default_factory=list)
    dispatch_state: Literal['NOT_SENT', 'DISPATCH_STARTED', 'RESPONSE_RECEIVED', 'DELIVERY_UNKNOWN']
    outcome: Literal['PASSED', 'FAILED', 'CANCELLED', 'CACHE_REUSED']
    observed_input_tokens: int | None = Field(default=None, ge=0)
    observed_output_tokens: int | None = Field(default=None, ge=0)
    result_hash: str | None = None
    error_code: str | None = None
    reuse_origin: str | None = None


class CoverageEvent(ContextModel):
    dimension: Literal['retained', 'processed', 'selected', 'dispatched', 'excluded', 'failed']
    refs: list[ContextRef]
    stage: str
    scope: str = ''
    historical: bool = False
    reason: str | None = None
    unit_ids: list[str] = Field(default_factory=list)


class CoverageLedger(ContextModel):
    schema_version: Literal['f07-v1'] = 'f07-v1'
    source_hash: str
    inventory: list[ContextRef]
    events: list[CoverageEvent] = Field(default_factory=list)
    calls: list[ContextCallRecord] = Field(default_factory=list)
    parser_completeness: str = 'unknown'
    context_completeness: str = 'incomplete'
    semantic_completeness: str = 'unknown'
    totals: dict[str, Any] = Field(default_factory=dict)
    legacy_context_unknown: bool = False
    source_integrity: Literal['verified', 'unknown'] = 'unknown'


class CoverageFinding(ContextModel):
    code: str
    source_id: str | None = None
    chunk_id: str | None = None
    message: str


class ContextChunksArtifact(ContextModel):
    schema_version: Literal['f07-v1'] = 'f07-v1'
    chunks: list[ContextChunk]
    lineage: list[ContextChunk] = Field(default_factory=list)
