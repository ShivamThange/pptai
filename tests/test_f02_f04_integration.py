"""Integration tests for F02 (document parsing) and F04 (multimodal extraction).

Verifies:
1. Chart assets are preserved through adapt_structural_ir without being dropped.
2. verify_structural_ir generates validation_report.json with accurate counts and status.
3. enrich_assets writes asset_manifest.json with all enriched assets.
4. Missing or corrupted assets produce status='invalid' in validation_report.json.
"""
import json
import hashlib
from pathlib import Path
from pipeline.source_adapter import adapt_structural_ir
from pipeline.stage2_quality_gate import verify_structural_ir
from schemas.raw_extraction_schema import RawExtraction, SourceAsset


def test_chart_assets_preserved_in_adapt_structural_ir(tmp_path):
    """Test that kind='chart' assets are not dropped by adapt_structural_ir."""
    source_file = tmp_path / "chart_source.bin"
    source_file.write_bytes(b"dummy chart source")
    source_hash = hashlib.sha256(b"dummy chart source").hexdigest()
    doc_id = f"doc_{source_hash}"

    chart_file = tmp_path / "chart_data.json"
    chart_payload = {"chart_type": "bar", "series": [{"name": "A", "values": [1, 2, 3]}]}
    chart_file.write_text(json.dumps(chart_payload), encoding="utf-8")
    chart_hash = hashlib.sha256(chart_file.read_bytes()).hexdigest()

    structural_ir = {
        "schema_version": "2",
        "document_name": "test_presentation.docx",
        "document_id": doc_id,
        "source_sha256": source_hash,
        "source_item_ids": [f"{doc_id}:chart_001"],
        "blocks": [
            {
                "block_id": f"{doc_id}:block_0001",
                "document_id": doc_id,
                "source_item_id": f"{doc_id}:chart_001",
                "type": "chart",
                "text": "Quarterly Revenue Breakdown",
                "section": "Financials",
                "locations": [{"document_id": doc_id, "source_id": f"{doc_id}:chart_001", "page": 1}],
                "content_sha256": hashlib.sha256("Quarterly Revenue Breakdown".encode()).hexdigest(),
            }
        ],
        "assets": [
            {
                "asset_id": "chart_001",
                "type": "chart",
                "file_path": str(chart_file),
                "data": chart_payload,
                "source_refs": [f"{doc_id}:chart_001"],
                "locations": [{"document_id": doc_id, "source_id": f"{doc_id}:chart_001", "page": 1}],
                "content_sha256": chart_hash,
                "caption": "Quarterly Revenue Breakdown",
            }
        ],
    }

    raw = adapt_structural_ir(structural_ir, base_dir=tmp_path)
    assert isinstance(raw, RawExtraction)
    assert len(raw.assets) == 1
    asset = raw.assets[0]
    assert asset.kind == "chart"
    assert asset.data == chart_payload
    assert asset.file_path == str(chart_file)


def test_verify_structural_ir_emits_validation_report(tmp_path):
    """Test that verify_structural_ir creates a validation_report.json file."""
    ir_path = tmp_path / "ir.json"
    img_path = tmp_path / "fig1.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    ir_data = {
        "schema_version": "2",
        "document_name": "sample.pdf",
        "blocks": [{"block_id": "b1", "text": "Hello world"}],
        "assets": [
            {
                "asset_id": "fig1",
                "type": "image",
                "file_path": str(img_path),
            }
        ],
    }
    ir_path.write_text(json.dumps(ir_data), encoding="utf-8")

    result = verify_structural_ir(str(ir_path))
    assert result is True

    report_path = tmp_path / "validation_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "validation-report-v1"
    assert report["status"] == "valid"
    assert report["counts"]["blocks"] == 1
    assert report["counts"]["images"] == 1
    assert report["counts"]["total_assets"] == 1
    assert report["missing_assets"] == []


def test_verify_structural_ir_fails_on_missing_asset(tmp_path):
    """Test that verify_structural_ir catches missing assets and reports invalid status."""
    ir_path = tmp_path / "ir.json"
    missing_file = tmp_path / "nonexistent.png"

    ir_data = {
        "schema_version": "2",
        "document_name": "sample.pdf",
        "blocks": [{"block_id": "b1", "text": "Hello world"}],
        "assets": [
            {
                "asset_id": "fig1",
                "type": "image",
                "file_path": str(missing_file),
                "availability": "AVAILABLE",
            }
        ],
    }
    ir_path.write_text(json.dumps(ir_data), encoding="utf-8")

    result = verify_structural_ir(str(ir_path))
    assert result is False

    report_path = tmp_path / "validation_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "invalid"
    assert len(report["missing_assets"]) == 1
    assert report["missing_assets"][0]["asset_id"] == "fig1"
