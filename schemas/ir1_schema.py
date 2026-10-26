from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from contracts.raw_extraction_schema import SourceAsset, SourceLocation, SourceBlock
from contracts.asset_schema import AssetSourceItem, AssetSemanticCoverage
from contracts.ingestion_schema import DocumentDescriptor

class KeyMetric(BaseModel):
    value: str = Field(description="Numerical metric or value (e.g. '$12M', '45%')")
    label: str = Field(description="Short concise description of the metric")
    context: Optional[str] = Field(None, description="Supporting details")

class ExtractedConcept(BaseModel):
    title: str = Field(description="Concept header")
    summary: str = Field(description="Detailed explanation")
    source_block_ids: List[str] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)

class TableData(BaseModel):
    title: str
    headers: List[str]
    rows: List[List[str]]
    source_asset_id: Optional[str] = None

class VisualOpportunity(BaseModel):
    visual_id: str
    recommended_type: str = Field(description="'chart', 'diagram', 'image', 'table'")
    chart_type: Optional[str] = Field(None, description="'bar', 'column', 'line', 'pie', 'area'")
    title: str
    categories: Optional[List[str]] = None
    series: Optional[List[Dict[str, Any]]] = None
    source_asset_id: Optional[str] = None

class IR1KnowledgeBase(BaseModel):
    document_title: str
    executive_summary: str
    metrics: List[KeyMetric] = Field(default_factory=list)
    concepts: List[ExtractedConcept] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    visual_opportunities: List[VisualOpportunity] = Field(default_factory=list)
    # Lossless source metadata retained alongside the evaluator's old fields.
    evidence_assets: List[SourceAsset] = Field(default_factory=list)
    source_evidence: Dict[str, Any] = Field(default_factory=dict)
    source_item_ids: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical multi-agent IR1 contracts.  The legacy classes above are retained
# as the derived content_analysis.json evaluator projection, not a generation path.
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """A source excerpt tied to the exact structural-IR block that supports it."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    document_id: Optional[str] = None
    locations: List[SourceLocation] = Field(default_factory=list)
    content_sha256: Optional[str] = None
    kind: Literal["excerpt", "cell", "caption", "representation", "expression"] = "excerpt"
    row: Optional[int] = Field(default=None, ge=0)
    column: Optional[int] = Field(default=None, ge=0)


class CalculationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["sum", "difference", "ratio", "percent_change"]
    operand_ids: List[str] = Field(min_length=2, max_length=2)
    operand_refs: List[EvidenceRef] = Field(default_factory=list)
    expression: str = ""
    result: Optional[str] = None


class MetricFact(BaseModel):
    """An asserted metric; source identity and calculation traces are checked locally."""
    model_config = ConfigDict(extra="forbid")
    metric_id: str
    subject: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    value: str
    unit: Optional[str] = None
    period: Optional[str] = None
    source_precision: Optional[int] = Field(default=None, ge=0)
    evidence: List[EvidenceRef] = Field(min_length=1)
    calculation: Optional[CalculationTrace] = None


class MetricComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_id: str
    right_id: str
    operator: Literal["gt", "lt", "eq", "ge", "le"]


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation_exists: Literal["CHECKED", "FAILED", "UNKNOWN"] = "UNKNOWN"
    numeric_binding: Literal["CHECKED", "FAILED", "UNKNOWN", "NOT_APPLICABLE"] = "UNKNOWN"
    semantic_support: Literal["CHECKED", "FAILED", "UNKNOWN"] = "UNKNOWN"
    status: Literal["BASIC_CHECKED", "VERIFIED", "REJECTED", "UNKNOWN"] = "UNKNOWN"
    reason: List[str] = Field(default_factory=list)
    claim_sha256: Optional[str] = None
    evidence_sha256: Optional[str] = None


class CoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    section: str
    accepted_unit_ids: List[str] = Field(default_factory=list)
    rejected_unit_ids: List[str] = Field(default_factory=list)
    missing_unit_ids: List[str] = Field(default_factory=list)
    status: Literal["COVERED", "MISSING", "INCOMPLETE"] = "MISSING"


KnowledgeKind = Literal["metric", "concept", "workflow", "comparison", "example", "finding", "limitation"]
KnowledgePriority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class KnowledgeUnit(BaseModel):
    """An atomic, source-grounded item available to later presentation stages."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(min_length=1)
    origin_asset_ids: List[str] = Field(default_factory=list)
    origin_insight_ids: List[str] = Field(default_factory=list)
    kind: KnowledgeKind
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    structured_data: Dict[str, Any] = Field(default_factory=dict)
    section_path: List[str] = Field(min_length=1)
    evidence: List[EvidenceRef] = Field(min_length=1)
    priority: KnowledgePriority = "MEDIUM"
    metric_facts: List[MetricFact] = Field(default_factory=list)
    comparisons: List[MetricComparison] = Field(default_factory=list)
    validation: ValidationResult = Field(default_factory=ValidationResult)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    validation_status: Literal["VALIDATED", "REJECTED", "NEEDS_REVIEW"] = "NEEDS_REVIEW"


class VisualAsset(SourceAsset):
    """A visual/table/formula extracted from the structural document IR."""



class ValidatedIR1(BaseModel):
    """The sole source of truth for the multi-agent presentation pipeline."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["3", "4"] = "3"
    documents: List[DocumentDescriptor] = Field(default_factory=list)
    source_blocks: List[SourceBlock] = Field(default_factory=list)
    asset_source_items: List[AssetSourceItem] = Field(default_factory=list)
    asset_semantic_coverage: List[AssetSemanticCoverage] = Field(default_factory=list)
    source_item_ids: List[str] = Field(default_factory=list)
    document_title: str = Field(min_length=1)
    executive_summary: str = ""
    units: List[KnowledgeUnit] = Field(default_factory=list)
    assets: List[VisualAsset] = Field(default_factory=list)
    coverage: List[CoverageItem] = Field(default_factory=list)
    rejected_units: List[KnowledgeUnit] = Field(default_factory=list)
    completeness: Literal["BASIC_CHECKED", "VERIFIED", "INCOMPLETE"] = "INCOMPLETE"
    deep_verification_requested: bool = False
    aliases: Dict[str, str] = Field(default_factory=dict)
