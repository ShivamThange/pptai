"""Typed projection of the existing Docling structural IR."""

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator
from schemas.ingestion_schema import DocumentDescriptor
from schemas.asset_schema import AssetContent, AssetSourceItem, AssetSemanticCoverage


class SourceLocation(BaseModel):
    """Actual Docling item location; absent geometry remains unknown."""

    model_config = ConfigDict(extra="forbid")
    document_id: str
    source_id: str
    page: Optional[int] = Field(default=None, ge=1)
    bbox: Optional[Tuple[float, float, float, float]] = None
    coord_origin: Optional[str] = None
    charspan: Optional[Tuple[int, int]] = None
    kind: Literal['docling_item', 'text_span', 'csv_cell', 'xlsx_cell', 'image', 'ooxml_item'] = 'docling_item'
    package_part: Optional[str] = None
    xml_path: Optional[str] = None
    relationship_id: Optional[str] = None
    line_start: Optional[int] = Field(default=None, ge=1)
    line_end: Optional[int] = Field(default=None, ge=1)
    record_index: Optional[int] = Field(default=None, ge=1)
    column_index: Optional[int] = Field(default=None, ge=1)
    sheet_name: Optional[str] = None
    sheet_index: Optional[int] = Field(default=None, ge=1)
    cell_range: Optional[str] = None
    geometry_unit: Optional[str] = None


class TableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str
    column_header: bool = False
    row_header: bool = False
    source_refs: List[str] = Field(default_factory=list)
    locations: List[SourceLocation] = Field(default_factory=list)
    lexical_value: Optional[str] = None
    raw_value: Any = None
    value_type: Optional[str] = None
    formula: Optional[str] = None
    cached_value: Any = None
    cached_state: Optional[Literal['unknown', 'cached_unverified']] = None
    number_format: Optional[str] = None
    display_text: Optional[str] = None
    display_origin: Optional[Literal['source_text','source_lexeme','formatted']] = None
    normalized_value: Optional[str] = None
    normalized_type: Optional[Literal['number','text','boolean','date','blank','error','unknown']] = None
    numeric_state: Optional[Literal['SOURCE_LITERAL','CACHED_UNVERIFIED','UNKNOWN','NOT_NUMERIC']] = None
    unit_refs: List[str] = Field(default_factory=list)
    footnote_refs: List[str] = Field(default_factory=list)
    merge_anchor: Optional[Tuple[int,int]] = None
    merge_continuation: bool = False
    present: bool = True


class TableAssetData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    cells: List[TableCell] = Field(default_factory=list)


class SourceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    kind: str = "text"
    text: str = Field(min_length=1)
    section_path: List[str] = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    bbox: Optional[Tuple[float, float, float, float]] = None
    document_id: Optional[str] = None
    source_item_id: Optional[str] = None
    locations: List[SourceLocation] = Field(default_factory=list)
    content_sha256: Optional[str] = None


class SourceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    kind: Literal["image", "table", "formula", "chart"]
    content: Optional[AssetContent] = None
    section_path: List[str] = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    file_path: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    caption: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    document_id: Optional[str] = None
    locations: List[SourceLocation] = Field(default_factory=list)
    # SAME_PAGE_GEOMETRY records the conservative nearby-caption inference in
    # stage1 (_same_page_caption); the vocabulary must accept what the parser
    # can legitimately emit or valid parses get rejected at validation time.
    caption_binding: Literal["DIRECT", "SHARED_PANEL_GEOMETRY", "SAME_PAGE_GEOMETRY", "UNKNOWN"] = "UNKNOWN"
    caption_refs: List[str] = Field(default_factory=list)
    caption_locations: List[SourceLocation] = Field(default_factory=list)
    content_sha256: Optional[str] = None
    width: Optional[int] = Field(default=None, gt=0)
    height: Optional[int] = Field(default=None, gt=0)
    availability: Literal["AVAILABLE", "MISSING"] = "AVAILABLE"
    findings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_table_shape(self):
        if self.kind == "table" and self.data is not None:
            self.data = TableAssetData.model_validate(self.data).model_dump(mode="json")
        return self


class RawExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1", "2", "3", "4"] = "2"
    asset_source_items: List[AssetSourceItem] = Field(default_factory=list)
    asset_semantic_coverage: List[AssetSemanticCoverage] = Field(default_factory=list)
    semantic_completeness: Literal['complete', 'partial', 'unavailable', 'disabled'] = 'disabled'
    document_name: str = Field(min_length=1)
    document_id: Optional[str] = None
    source_sha256: Optional[str] = None
    documents: List[DocumentDescriptor] = Field(default_factory=list)
    collection_id: Optional[str] = None
    source_item_ids: List[str] = Field(default_factory=list)
    adapter_version: str = "docling-v2"
    findings: List[str] = Field(default_factory=list)
    blocks: List[SourceBlock] = Field(default_factory=list)
    assets: List[SourceAsset] = Field(default_factory=list)
