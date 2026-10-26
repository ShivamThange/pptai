"""F04 source assets. Interpretation is a derivation, never new evidence."""
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class AssetOptions(AssetModel):
    schema_version: Literal['asset-options-v1'] = 'asset-options-v1'
    mode: Literal['legacy', 'structured'] = 'legacy'
    semantic_understanding: Literal['auto', 'off'] = 'auto'
    describe_assets: bool = False
    description_asset_ids: list[str] = Field(default_factory=list)
    chart_mappings: list['ChartMapping'] = Field(default_factory=list)
    formula_dpi: int = Field(default=200, ge=72, le=600)
    formula_font_size: int = Field(default=20, ge=8, le=72)
    formula_timeout: float = Field(default=20, gt=0, le=60)
    min_ppi: float = Field(default=150, gt=0)
    semantic_input_chars: int = Field(default=24000, ge=2000, le=200000)
    max_image_pixels: int = Field(default=2000000, ge=10000, le=16000000)
    max_insights: int = Field(default=20, ge=1, le=100)

    @model_validator(mode='after')
    def unique_ids(self):
        if len(set(self.description_asset_ids)) != len(self.description_asset_ids):
            raise ValueError('Duplicate description asset IDs')
        return self


class AssetRepresentation(AssetModel):
    representation_id: str
    role: Literal['original', 'source_crop', 'display_png', 'formula_svg', 'table_json', 'chart_data_json', 'preview']
    path: str | None = None
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    media_type: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    editability: Literal['raster', 'native_table', 'native_chart', 'vector_source']
    availability: Literal['available', 'missing', 'unsupported'] = 'available'
    reason: str | None = None

    @model_validator(mode='after')
    def available_bytes(self):
        if self.availability == 'available' and (not self.path or not self.sha256):
            raise ValueError('Available representation needs path and hash')
        return self


class AssetFinding(AssetModel):
    code: str
    severity: Literal['info', 'warning', 'error'] = 'warning'
    asset_id: str
    document_id: str | None = None
    locator: dict[str, Any] | None = None
    message: str
    blocks_required_use: bool = False


class AssetSourceItem(AssetModel):
    source_id: str
    document_id: str
    package_sha256: str
    package_path: str
    part: str
    xml_path: str
    snippet_sha256: str
    relationship_chain: list[str] = Field(default_factory=list)
    embedded_sha256: str | None = None
    embedded_package_part: str | None = None


class AssetEvidenceAnchor(AssetModel):
    asset_id: str
    source_sha256: str
    source_id: str | None = None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    series_index: int | None = Field(default=None, ge=0)
    category_index: int | None = Field(default=None, ge=0)
    region: tuple[float, float, float, float] | None = None
    expression_span: tuple[int, int] | None = None


class AssetInsight(AssetModel):
    insight_id: str = ''
    asset_id: str
    kind: Literal['observation', 'result', 'comparison', 'trend', 'relationship', 'formula_meaning', 'limitation', 'implication']
    statement: str = Field(min_length=1)
    basis: Literal['source_reported', 'source_data', 'calculated', 'visual_observation', 'contextual_interpretation']
    anchors: list[AssetEvidenceAnchor] = Field(min_length=1)
    context_refs: list[str] = Field(default_factory=list)
    qualification: str | None = None
    calculation: dict[str, Any] | None = None
    eligibility: Literal['FACTUAL_TEXT', 'QUALIFIED_TEXT', 'SUGGESTION_ONLY', 'REJECTED'] = 'SUGGESTION_ONLY'
    validation: dict[str, Any] = Field(default_factory=dict)


class AssetInterpretation(AssetModel):
    schema_version: Literal['asset-interpretation-v1'] = 'asset-interpretation-v1'
    asset_id: str
    context_refs: list[str] = Field(default_factory=list)
    context_sha256: str
    input_hashes: list[str] = Field(default_factory=list)
    role: Literal['evidence', 'result', 'comparison', 'method', 'architecture', 'illustration', 'decorative', 'unknown'] = 'unknown'
    summary: str = ''
    insights: list[AssetInsight] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    completeness: Literal['complete', 'partial', 'unavailable'] = 'partial'
    model_fingerprint: dict[str, Any] = Field(default_factory=dict)
    prompt_sha256: str = ''
    budget: dict[str, Any] = Field(default_factory=dict)


class AssetDescription(AssetModel):
    text: str = ''
    origin: Literal['source_caption', 'ocr', 'vlm_observation'] = 'vlm_observation'
    status: Literal['SOURCE_BACKED', 'UNVERIFIED', 'FAILED', 'NOT_REQUESTED'] = 'NOT_REQUESTED'
    source_refs: list[str] = Field(default_factory=list)
    input_hashes: list[str] = Field(default_factory=list)


class AssetSemanticCoverage(AssetModel):
    asset_id: str
    status: Literal['pending', 'processed', 'no_supported_findings', 'decorative', 'unsupported', 'failed', 'disabled'] = 'pending'
    covered_refs: list[str] = Field(default_factory=list)
    unprocessed_refs: list[str] = Field(default_factory=list)
    accepted_insight_ids: list[str] = Field(default_factory=list)
    rejected_insight_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class PixelTransform(AssetModel):
    source_dimensions: tuple[int, int]
    destination_dimensions: tuple[int, int]
    matrix: tuple[float, float, float, float, float, float, float, float, float]
    operations: list[str] = Field(default_factory=list)


class ContentBase(AssetModel):
    schema_version: Literal['asset-content-v1'] = 'asset-content-v1'
    origin: Literal['source', 'derived'] = 'source'
    parent_asset_ids: list[str] = Field(default_factory=list)
    source_sha256: str
    representations: list[AssetRepresentation] = Field(default_factory=list)
    findings: list[AssetFinding] = Field(default_factory=list)
    interpretation: AssetInterpretation | None = None


class TableAssetContent(ContentBase):
    kind: Literal['table'] = 'table'
    row_count: int = Field(ge=1)
    column_count: int = Field(ge=1)
    header_rows: list[int] = Field(default_factory=list)
    cells: list[dict[str, Any]]
    merged_ranges: list[tuple[int, int, int, int]] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    sheet_name: str | None = None
    sheet_index: int | None = None
    worksheet_range: str | None = None
    projection_origin: int = 0

    @model_validator(mode='after')
    def grid(self):
        if len(set(self.header_rows))!=len(self.header_rows) or any(r<0 or r>=self.row_count for r in self.header_rows):
            raise ValueError('TABLE_SPAN_INVALID: header row outside grid')
        occupied = set()
        for cell in self.cells:
            r, c = cell['row'], cell['column']
            rs, cs = cell.get('row_span', 1), cell.get('column_span', 1)
            if r < 0 or c < 0 or rs < 1 or cs < 1 or r + rs > self.row_count or c + cs > self.column_count:
                raise ValueError('TABLE_SPAN_INVALID: cell outside grid')
            coords = {(i, j) for i in range(r, r + rs) for j in range(c, c + cs)}
            if occupied & coords:
                raise ValueError('TABLE_SPAN_INVALID: overlapping cells')
            occupied.update(coords)
        return self


class TableSelection(AssetModel):
    asset_id: str
    rows: list[int] = Field(min_length=1)
    columns: list[int] = Field(min_length=1)
    header_rows: list[int] = Field(default_factory=list)
    annotation_refs: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def indices(self):
        for values in (self.rows, self.columns, self.header_rows):
            if any(v < 0 for v in values) or len(set(values)) != len(values):
                raise ValueError('TABLE_SELECTION_INVALID: duplicate/negative indices')
        if not set(self.header_rows) <= set(self.rows):
            raise ValueError('TABLE_SELECTION_INVALID: headers outside selection')
        return self


class FigureAssetContent(ContentBase):
    kind: Literal['figure'] = 'figure'
    width: int | None = None
    height: int | None = None
    exif_orientation: int = Field(default=1, ge=1, le=8)
    transform: PixelTransform | None = None
    caption_binding: str = 'UNKNOWN'
    figure_class: Literal['figure', 'chart_picture', 'photo', 'diagram', 'unknown'] = 'unknown'
    descriptions: list[AssetDescription] = Field(default_factory=list)


class FormulaAssetContent(ContentBase):
    kind: Literal['formula'] = 'formula'
    expression: str | None = None
    expression_refs: list[str] = Field(default_factory=list)
    expression_format: Literal['latex', 'mathtext', 'plain', 'omml', 'unknown'] = 'unknown'
    transcription_status: Literal['SOURCE_LITERAL', 'UNVERIFIED', 'UNKNOWN'] = 'UNKNOWN'
    render_expression: str | None = None
    render_status: str = 'FORMULA_RENDER_UNAVAILABLE'


class ChartPointBinding(AssetModel):
    series_index: int = Field(ge=0)
    category_index: int = Field(ge=0)
    lexical_value: str
    decimal_value: str
    value_refs: list[str] = Field(min_length=1)


class ChartAssetContent(ContentBase):
    kind: Literal['chart'] = 'chart'
    chart_type: str
    data_origin: Literal['native_cells', 'native_literals', 'selected_table', 'image_only']
    data_state: Literal['VERIFIED_SOURCE_DATA', 'CACHED_UNVERIFIED', 'UNAVAILABLE']
    reconstruction_status: Literal['EDITABLE', 'IMAGE_ONLY', 'UNSUPPORTED']
    categories: list[str] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    points: list[ChartPointBinding] = Field(default_factory=list)
    label_refs: list[str] = Field(default_factory=list)
    unit: str | None = None


class ChartMapping(AssetModel):
    table_asset_id: str
    rows: list[int] = Field(min_length=1)
    category_column: int = Field(ge=0)
    series_columns: list[int] = Field(min_length=1)
    header_row: int = Field(ge=0)
    chart_type: Literal['column','bar','line','area','pie'] = 'column'

    @model_validator(mode='after')
    def exact_selection(self):
        if self.header_row in self.rows or any(r<0 for r in self.rows) or len(set(self.rows))!=len(self.rows):
            raise ValueError('TABLE_SELECTION_INVALID: mapping row indices')
        if self.category_column in self.series_columns or len(set(self.series_columns))!=len(self.series_columns) or any(c<0 for c in self.series_columns):
            raise ValueError('TABLE_SELECTION_INVALID: mapping columns')
        return self


AssetOptions.model_rebuild()


AssetContent = Annotated[TableAssetContent | FigureAssetContent | FormulaAssetContent | ChartAssetContent, Field(discriminator='kind')]
