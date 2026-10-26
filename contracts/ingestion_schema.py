"""Versioned intake contracts; source content is data, never instructions."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

InputType = Literal['pdf', 'docx', 'txt', 'markdown', 'csv', 'xlsx', 'png', 'jpeg']
SelectedType = Literal['auto', 'pdf', 'docx', 'txt', 'markdown', 'csv', 'xlsx', 'png', 'jpeg']


class IngestionModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ParseOptions(IngestionModel):
    schema_version: Literal['parse-options-v1'] = 'parse-options-v1'
    ocr: Literal['auto', 'off', 'force'] = 'auto'
    encoding: str = 'auto'
    csv_delimiter: Literal['auto', ',', ';', '\t', '|'] = 'auto'
    csv_has_header: bool = True

    def for_type(self, kind):
        invalid = []
        if kind not in {'pdf', 'png', 'jpeg'} and self.ocr != 'auto':
            invalid.append('ocr')
        if kind not in {'txt', 'markdown', 'csv'} and self.encoding != 'auto':
            invalid.append('encoding')
        if kind != 'csv' and (self.csv_delimiter != 'auto' or not self.csv_has_header):
            invalid.append('csv options')
        if invalid:
            raise ValueError('Inapplicable options for ' + kind + ': ' + ', '.join(invalid))
        return self


class SourceSelection(IngestionModel):
    document_id: str = Field(min_length=1)
    selected_type: SelectedType | None = None
    parse_options: ParseOptions = Field(default_factory=ParseOptions)


class ParseFinding(IngestionModel):
    code: str
    severity: Literal['info', 'warning', 'error'] = 'warning'
    message: str
    document_id: str | None = None
    item_id: str | None = None
    location: dict[str, Any] | None = None
    blocks_generation: bool = False


class UploadSpec(IngestionModel):
    schema_version: Literal['upload-v1'] = 'upload-v1'
    upload_id: str
    original_filename: str
    display_filename: str
    storage_filename: str
    original_extension: str
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0)
    detected_type: InputType
    selected_type: SelectedType = 'auto'
    resolved_type: InputType
    detection_basis: str
    text_encoding: str | None = None
    client_mime: str | None = None
    findings: list[ParseFinding] = Field(default_factory=list)
    created_at: str


class ResolvedParseOptions(IngestionModel):
    resolved_type: InputType
    requested: ParseOptions = Field(default_factory=ParseOptions)
    encoding: str | None = None
    csv_delimiter: str | None = None
    csv_has_header: bool | None = None
    requested_ocr: str = 'auto'
    effective_ocr: str = 'off'
    ocr_engine: str | None = None
    ocr_languages: list[str] = Field(default_factory=list)
    requested_device: str = 'cpu'
    effective_device: str = 'cpu'
    table_structure: bool = False
    image_scale: float | None = None
    adapter: str
    versions: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class DocumentDescriptor(IngestionModel):
    document_id: str
    source_sha256: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    upload_ids: list[str] = Field(default_factory=list)
    resolved_type: InputType
    parse_key: str | None = None
    parser_version: str = 'ingestion-v3'
    completeness: Literal['complete', 'partial', 'unknown'] = 'complete'
    counts: dict[str, int] = Field(default_factory=dict)


class ParseResult(IngestionModel):
    schema_version: Literal['parse-result-v1'] = 'parse-result-v1'
    upload_id: str | None = None
    document_id: str
    parse_key: str
    status: Literal['complete', 'partial', 'failed']
    completeness: Literal['complete', 'partial', 'unknown']
    structural_artifact: str | None = None
    structural_sha256: str | None = None
    raw_artifacts: dict[str, str] = Field(default_factory=dict)
    resolved_options: ResolvedParseOptions
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[ParseFinding] = Field(default_factory=list)

    def public(self):
        from pathlib import Path
        value = self.model_dump(mode='json', exclude={'structural_artifact', 'raw_artifacts'})
        value['resolved_options']['models'] = {Path(k).name: v for k, v in self.resolved_options.models.items()}
        value['resolved_options']['configuration'].pop('artifacts_path', None)
        return value


class IngestionError(ValueError):
    def __init__(self, code, message, *, status=422, details=None, result=None):
        super().__init__(message)
        self.code, self.status, self.details, self.result = code, status, details or {}, result

    def public(self):
        return {'code': self.code, 'message': str(self), **self.details}
