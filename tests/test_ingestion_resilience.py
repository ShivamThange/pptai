"""Small Docling-output errors must degrade to recorded findings, never stall.

Regression coverage for the rejected-job class where a single asset field the
parser legitimately emits (SAME_PAGE_GEOMETRY) or a malformed payload used to
raise a pydantic ValidationError inside validate_ingestion and reject the whole
document at the parsing stage.
"""

import json
from pathlib import Path

import pytest

from infrastructure.ingestion.source_adapter import adapt_structural_ir, _CAPTION_BINDINGS
from infrastructure.ingestion.stage1_docling_parser import export_docling_document
from contracts.ingestion_schema import ParseFinding


def _ir(tmp_path, *, blocks=None, assets=None):
    return {
        "schema_version": "2",
        "document_name": "attention.pdf",
        "document_id": "doc_test",
        "source_sha256": "testhash",
        "source_item_ids": ["doc_test:text_1"],
        "blocks": blocks if blocks is not None else [_text_block()],
        "assets": assets if assets is not None else [],
    }


def _text_block(**overrides):
    block = {
        "block_id": "text_1",
        "source_item_id": "text_1",
        "type": "text",
        "text": "Attention combines values using learned weights.",
        "section": "Introduction",
    }
    block.update(overrides)
    return block


def _image_asset(tmp_path, asset_id="image_1", **overrides):
    image = tmp_path / f"{asset_id}.png"
    image.write_bytes(b"image-bytes")
    asset = {
        "asset_id": asset_id,
        "type": "image",
        "source_refs": ["texts/1"],
        "locations": [
            {"document_id": "doc_test", "source_id": "doc_test:texts/1", "page": 1}
        ],
        "file_path": str(image),
        "caption": "Figure 1: the model.",
        "caption_binding": "DIRECT",
    }
    asset.update(overrides)
    return asset


def test_same_page_geometry_binding_is_valid(tmp_path):
    """The exact production failure: stage1 emits SAME_PAGE_GEOMETRY."""
    raw = adapt_structural_ir(
        _ir(
            tmp_path,
            assets=[
                _image_asset(tmp_path, caption_binding="SAME_PAGE_GEOMETRY")
            ],
        ),
        base_dir=tmp_path,
    )

    assert raw.assets[0].caption_binding == "SAME_PAGE_GEOMETRY"
    assert "SAME_PAGE_GEOMETRY" in _CAPTION_BINDINGS
    # The nearby-caption inference must validate without any repair note.
    assert not [
        f for f in raw.assets[0].findings if "caption binding" in f.lower()
    ]


def test_unknown_caption_binding_value_is_repaired(tmp_path):
    """A future producer emitting an unseen binding degrades, not rejects."""
    raw = adapt_structural_ir(
        _ir(
            tmp_path,
            assets=[_image_asset(tmp_path, caption_binding="TOTALLY_BOGUS")],
        ),
        base_dir=tmp_path,
    )

    assert raw.assets[0].caption_binding == "UNKNOWN"
    assert any("TOTALLY_BOGUS" in f for f in raw.assets[0].findings)


def test_malformed_asset_locations_drop_per_entry(tmp_path):
    locations = [
        {"document_id": "doc_test", "source_id": "doc_test:texts/1", "page": 1},
        {"document_id": "doc_test", "source_id": "doc_test:texts/1", "page": "one"},
        {"document_id": "doc_test", "source_id": "doc_test:texts/1", "spurious": True},
    ]
    raw = adapt_structural_ir(
        _ir(tmp_path, assets=[_image_asset(tmp_path, locations=locations)]),
        base_dir=tmp_path,
    )

    # One invalid location entry must not reject the asset.
    assert len(raw.assets) == 1
    assert len(raw.assets[0].locations) == 1
    assert raw.assets[0].locations[0].page == 1
    assert any("invalid location" in f for f in raw.assets[0].findings)


def test_malformed_block_locations_drop_per_entry(tmp_path):
    locations = [
        {"document_id": "doc_test", "source_id": "doc_test:text_1", "page": "two"},
        {"document_id": "doc_test", "source_id": "doc_test:text_1", "page": 3},
    ]
    raw = adapt_structural_ir(
        _ir(tmp_path, blocks=[_text_block(locations=locations)]), base_dir=tmp_path
    )

    assert len(raw.blocks) == 1
    assert [loc.page for loc in raw.blocks[0].locations] == [3]
    assert raw.blocks[0].page == 3
    assert any("invalid location" in f for f in raw.findings)


def test_non_text_caption_payload_is_discarded(tmp_path):
    raw = adapt_structural_ir(
        _ir(tmp_path, assets=[_image_asset(tmp_path, caption=12345)]),
        base_dir=tmp_path,
    )

    # The asset survives; only its bogus caption payload is dropped.
    assert len(raw.assets) == 1
    assert raw.assets[0].caption is None
    assert any("caption payload" in f for f in raw.assets[0].findings)


def test_nonsense_dimensions_are_recorded_as_unknown(tmp_path):
    raw = adapt_structural_ir(
        _ir(
            tmp_path,
            assets=[_image_asset(tmp_path, width="big", height=-4)],
        ),
        base_dir=tmp_path,
    )

    assert raw.assets[0].width is None
    assert raw.assets[0].height is None


def test_retained_asset_integrity_stays_fatal(tmp_path):
    """Integrity gates are deliberately strict; resilience never masks them."""
    missing = tmp_path / "missing.png"
    ir = _ir(
        tmp_path,
        assets=[
            _image_asset(
                tmp_path,
                asset_id="image_missing",
                file_path=str(missing),
                locations=[],
                source_refs=[],
            )
        ],
    )
    with pytest.raises(FileNotFoundError):
        adapt_structural_ir(ir, base_dir=tmp_path)

    tampered = _ir(
        tmp_path,
        assets=[
            _image_asset(
                tmp_path, asset_id="image_tampered", content_sha256="deadbeef"
            )
        ],
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        adapt_structural_ir(tampered, base_dir=tmp_path)


class _FakeLabel:
    def __init__(self, value):
        self.value = value


class _FakeItem:
    def __init__(self, kind, text, self_ref):
        self.label = _FakeLabel(kind)
        self.self_ref = self_ref
        self.prov = []
        self.text = text


class _ExplodingItem:
    def __init__(self, self_ref):
        self.label = _FakeLabel("text")
        self.self_ref = self_ref
        self.prov = []

    @property
    def text(self):
        raise RuntimeError("docling could not decode this item")


class _FakeDoc:
    def __init__(self, items):
        self._items = items
        self.texts = items
        self.pictures = []
        self.tables = []

    def iterate_items(self):
        return iter([(item, 1) for item in self._items])

    def save_as_json(self, path):
        Path(path).write_text("{}", encoding="utf-8")


def _write_source(tmp_path):
    source = tmp_path / "attention.pdf"
    source.write_bytes(b"pdf-bytes")
    return source


def test_stage1_skips_a_broken_item_instead_of_failing(tmp_path):
    doc = _FakeDoc(
        [
            _FakeItem("text", "First usable paragraph.", "texts/1"),
            _ExplodingItem("texts/2"),
            _FakeItem("text", "Second usable paragraph.", "texts/3"),
        ]
    )
    out = tmp_path / "parse"

    result = export_docling_document(doc, str(_write_source(tmp_path)), str(out))

    assert [block["text"] for block in result["blocks"]] == [
        "First usable paragraph.",
        "Second usable paragraph.",
    ]
    (finding,) = result["findings"]
    assert finding["code"] == "EXTRACTION_ITEM_SKIPPED"
    assert finding["severity"] == "warning"
    assert finding["blocks_generation"] is False
    assert finding["item_id"].endswith("block_0002")
    # The finding must survive the ParseFinding contract used by the job record.
    assert ParseFinding.model_validate(finding).blocks_generation is False
    # And it must be persisted into the structural IR the worker validates.
    persisted = json.loads((out / "ir.json").read_text(encoding="utf-8"))
    assert persisted["findings"] == [finding]


def test_stage1_keeps_partial_output_when_iteration_dies(tmp_path):
    class _DyingDoc(_FakeDoc):
        def iterate_items(self):
            yield (self._items[0], 1)
            raise RuntimeError("iterator died mid-document")

    doc = _DyingDoc([_FakeItem("text", "Only usable paragraph.", "texts/1")])
    out = tmp_path / "parse"

    result = export_docling_document(doc, str(_write_source(tmp_path)), str(out))

    assert [block["text"] for block in result["blocks"]] == [
        "Only usable paragraph."
    ]
    (finding,) = result["findings"]
    assert finding["code"] == "EXTRACTION_INTERRUPTED"
    assert finding["blocks_generation"] is False
    assert ParseFinding.model_validate(finding).severity == "warning"


def test_stage1_clean_document_records_no_findings(tmp_path):
    doc = _FakeDoc(
        [
            _FakeItem("text", "One paragraph.", "texts/1"),
            _FakeItem("text", "Another paragraph.", "texts/2"),
        ]
    )
    out = tmp_path / "parse"

    result = export_docling_document(doc, str(_write_source(tmp_path)), str(out))

    assert len(result["blocks"]) == 2
    assert result["findings"] == []
