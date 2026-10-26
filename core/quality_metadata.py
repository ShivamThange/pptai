"""Versioned, data-only native object roles and declared relationships."""
import json

PREFIX = "pptai-quality-v1:"


def read_metadata(shape):
    nodes = shape._element.xpath(".//p:cNvPr")
    value = nodes[0].get("descr", "") if nodes else ""
    if value.startswith(PREFIX):
        try:
            result = json.loads(value[len(PREFIX):])
            return result if isinstance(result, dict) else {}
        except (ValueError, TypeError):
            pass
    return {}


def declare_metadata(shape, **metadata):
    nodes = shape._element.xpath(".//p:cNvPr")
    if nodes:
        nodes[0].set("descr", PREFIX + json.dumps(metadata, ensure_ascii=False))
