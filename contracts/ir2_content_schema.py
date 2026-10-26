from typing import Annotated, List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, model_validator
from contracts.ir1_schema import ValidationResult
from contracts.asset_schema import TableSelection


class HeadingContent(BaseModel):
    type: Literal["heading"] = "heading"
    text: str
    style: Optional[Dict[str, Any]] = None


class TextGroupContent(BaseModel):
    type: Literal["text_group"] = "text_group"
    text: Optional[str] = None
    lines: Optional[List[str]] = None
    style: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def requires_text(self):
        if not self.text and not self.lines:
            raise ValueError("text_group requires either text or lines")
        return self


class BulletItem(BaseModel):
    text: str
    level: int = 0


class BulletsContent(BaseModel):
    type: Literal["bullets", "numbered_list"] = "bullets"
    items: List[Union[str, BulletItem]] = Field(min_length=1)
    style: Optional[Dict[str, Any]] = None


class StatItem(BaseModel):
    value: str
    label: str
    style: Optional[Dict[str, Any]] = None


class StatContent(BaseModel):
    type: Literal["stat"] = "stat"
    items: Optional[List[StatItem]] = None
    value: Optional[str] = None
    label: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class ImageContent(BaseModel):
    type: Literal["image"] = "image"
    source_asset_id: Optional[str] = Field(None, description="Exact image ID from the retrieved run asset registry")
    path: Optional[str] = Field(None, description="Direct file path to the image")
    caption: Optional[str] = None
    alt: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class TableContent(BaseModel):
    type: Literal["table"] = "table"
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    source_asset_id: Optional[str] = None
    selection: Optional[TableSelection] = None
    style: Optional[Dict[str, Any]] = None


class ChartSeries(BaseModel):
    name: str
    values: List[float] = Field(min_length=1)


class ChartContent(BaseModel):
    type: Literal["chart"] = "chart"
    source_asset_id: Optional[str] = None
    chart_type: Literal["bar", "column", "line", "pie", "area"] = "column"
    categories: List[str] = Field(min_length=1)
    series: List[ChartSeries] = Field(min_length=1)
    title: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class DiagramStep(BaseModel):
    title: str
    description: Optional[str] = None


class DiagramNode(BaseModel):
    id: str
    label: str
    subtext: Optional[str] = None


class DiagramEdge(BaseModel):
    from_id: str
    to_id: str
    label: Optional[str] = None


class DiagramContent(BaseModel):
    type: Literal["diagram"] = "diagram"
    diagram_type: Literal["process_flow", "nodes_edges", "linear_steps"] = Field("process_flow", description="Type of structured diagram")
    caption: Optional[str] = None
    steps: Optional[List[DiagramStep]] = Field(None, description="Used for sequential process or step diagrams")
    nodes: Optional[List[DiagramNode]] = Field(None, description="Used for graph/network or flowcharts")
    edges: Optional[List[DiagramEdge]] = Field(None, description="Connectors for node/edge diagrams")
    style: Optional[Dict[str, Any]] = None


class FormulaContent(BaseModel):
    type: Literal["formula"] = "formula"
    formula_id: Optional[str] = None
    latex: Optional[str] = None
    source_asset_id: Optional[str] = Field(None, description="Exact formula ID from the retrieved run asset registry")
    caption: Optional[str] = None


# ---------------------------------------------------------------------------
# Predefined visual objects (F13 object library).
#
# These are first-class IR2 content types so the composer can choose a fitting
# object instead of a plain text box. ``renderers/base.py`` expands each object
# into ordinary scene primitives (rounded rectangles + text), so both renderer
# backends keep working without a new scene contract.
# ---------------------------------------------------------------------------


class CardMetric(BaseModel):
    value: str
    label: Optional[str] = None
    context: Optional[str] = None


class CardContent(BaseModel):
    type: Literal["card"] = "card"
    title: Optional[str] = None
    text: Optional[str] = None
    metric: Optional[CardMetric] = None
    style: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def requires_visible_content(self):
        if not (self.title or self.text or self.metric):
            raise ValueError("card requires a title, text or metric")
        return self


class MetricCardContent(BaseModel):
    type: Literal["metric_card"] = "metric_card"
    value: str
    label: Optional[str] = None
    context: Optional[str] = None
    trend: Optional[str] = Field(None, description="Short change note, e.g. '+2.4 pts' or 'down 12%'")
    style: Optional[Dict[str, Any]] = None


class CalloutContent(BaseModel):
    type: Literal["callout"] = "callout"
    title: Optional[str] = None
    text: str
    style: Optional[Dict[str, Any]] = None


class QuoteContent(BaseModel):
    type: Literal["quote"] = "quote"
    text: str
    attribution: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class ChipsContent(BaseModel):
    type: Literal["chips"] = "chips"
    labels: List[str] = Field(min_length=1)
    style: Optional[Dict[str, Any]] = None


class ComparisonSide(BaseModel):
    heading: str
    items: List[str] = Field(min_length=1)


class CompareContent(BaseModel):
    type: Literal["compare"] = "compare"
    left: ComparisonSide
    right: ComparisonSide
    style: Optional[Dict[str, Any]] = None


ContentItem = Annotated[Union[
    HeadingContent,
    TextGroupContent,
    BulletsContent,
    StatContent,
    ImageContent,
    TableContent,
    ChartContent,
    DiagramContent,
    FormulaContent,
    CardContent,
    MetricCardContent,
    CalloutContent,
    QuoteContent,
    ChipsContent,
    CompareContent,
], Field(discriminator="type")]


class SlideDraft(BaseModel):
    """Only model-authored presentation fields; validation metadata is local."""
    layout: str
    background_color: Optional[str] = "#FFFFFF"
    # The value type must stay explicit.  Dict[str, Any] becomes an untyped
    # JSON object in Gemini's response schema, which permits `content: {}`.
    content: Dict[str, ContentItem] = Field(min_length=1)
    notes: Optional[str] = None
    # Ignored by the renderer, but required by the multi-agent provenance gate.
    # Keeping a default preserves compatibility with the legacy planner.
    source_unit_ids: List[str] = Field(default_factory=list)


class SlideSpec(SlideDraft):
    grounding: Dict[str, ValidationResult] = Field(default_factory=dict)
    asset_usage: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class TargetIR2Presentation(BaseModel):
    output_filename: str = "presentation_deck.pptx"
    slides: List[SlideSpec] = Field(min_length=1)
