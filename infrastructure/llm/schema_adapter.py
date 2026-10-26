"""Provider-specific JSON-schema adaptation (Gemini structured output).

Pydantic v2 emits full JSON Schema 2020-12 ($defs/$ref, anyOf with null,
type arrays, additionalProperties). The Gemini API accepts a restricted
subset: no $ref/$defs, no type arrays, no additionalProperties, and
nullability expressed via `nullable: true`. Passing the raw Pydantic schema
made Gemini silently drop referenced definitions, so models received a
skeleton schema and returned invalid slides.

The adapter inlines every $ref, folds `anyOf: [T, {type: null}]` into
`nullable`, drops unsupported keywords, and validates the result still
describes every property. OpenRouter receives the untouched original.
"""
from __future__ import annotations

import copy
from typing import Any

# JSON Schema keywords the Gemini Schema proto understands (directly or via
# the SDK's dict conversion). Everything else is dropped with a note.
_SUPPORTED_KEYS = {
    "type", "format", "description", "nullable", "enum", "items",
    "properties", "required", "minimum", "maximum", "anyOf", "title",
    "minLength", "maxLength", "pattern", "additionalProperties", "const",
}
_TYPE_ORDER = ["object", "string", "integer", "number", "boolean", "array", "null"]


class SchemaAdaptationError(ValueError):
    pass


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaAdaptationError(f"Only local schema references are supported, got {ref!r}")
    target: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise SchemaAdaptationError(f"Unresolvable schema reference {ref!r}")
        target = target[part]
    if not isinstance(target, dict):
        raise SchemaAdaptationError(f"Reference {ref!r} does not point at a schema object")
    return target


def _adapt_node(node: Any, root: dict[str, Any], depth: int = 0) -> dict[str, Any] | None:
    """Recursively adapt one schema node; returns None for dropped branches."""
    if depth > 64:
        raise SchemaAdaptationError("Schema nesting exceeds 64 levels (possible cycle)")
    if node is True or node == {}:
        return {"type": "string"}  # permissive fallback for empty schemas
    if not isinstance(node, dict):
        if isinstance(node, bool):
            return None if node is False else {"type": "string"}
        raise SchemaAdaptationError(f"Unexpected schema node {node!r}")

    # $ref: inline the target (with local overrides merged on top).
    if "$ref" in node:
        resolved = copy.deepcopy(_resolve_ref(node["$ref"], root))
        overrides = {key: value for key, value in node.items() if key != "$ref"}
        resolved.update(overrides)
        return _adapt_node(resolved, root, depth + 1)

    # anyOf/oneOf: fold null-alternatives into nullable, otherwise keep a
    # union of the adapted alternatives; a single survivor collapses to
    # itself. `oneOf` (pydantic discriminators) becomes `anyOf`, which Gemini
    # accepts; the discriminator keyword itself is dropped because each branch
    # carries its own `type` enum after adaptation.
    for union_key in ("anyOf", "oneOf"):
        if union_key in node:
            alternatives = [_adapt_node(alt, root, depth + 1) for alt in node[union_key]]
            alternatives = [alt for alt in alternatives if alt is not None]
            nullable = any(alt.get("type") == "null" or alt.get("nullable") for alt in alternatives)
            concrete = [alt for alt in alternatives if alt.get("type") != "null"]
            if not concrete:
                return {"type": "string", "nullable": True}
            if len(concrete) == 1:
                merged = dict(concrete[0])
            else:
                # Multiple distinct types: keep the union (Gemini supports it)
                # but normalize each branch first.
                merged = {"anyOf": concrete}
            for key in ("description", "title"):
                if key in node:
                    merged.setdefault(key, node[key])
            if nullable:
                merged["nullable"] = True
            return merged

    result: dict[str, Any] = {}
    if "type" in node:
        types = node["type"]
        if isinstance(types, list):
            nullable = "null" in types
            concrete = [t for t in types if t != "null"]
            if not concrete:
                return {"type": "string", "nullable": True}
            # Prefer the most permissive single type when several are listed.
            for candidate in _TYPE_ORDER:
                if candidate in concrete:
                    result["type"] = candidate
                    break
            if nullable:
                result["nullable"] = True
        else:
            result["type"] = types
    if node.get("nullable"):
        result["nullable"] = True
    for key in ("format", "description", "title", "minimum", "maximum",
                "minItems", "maxItems", "minLength", "maxLength", "pattern"):
        if key in node:
            result[key] = node[key]
    if "const" in node:
        value = node["const"]
        result["enum"] = [value]
        result.setdefault("type", "string" if isinstance(value, str) else
                          "integer" if isinstance(value, int) and not isinstance(value, bool) else
                          "number" if isinstance(value, float) else
                          "boolean" if isinstance(value, bool) else "string")
    if "enum" in node and node["enum"] is not None:
        enum = [value for value in node["enum"] if value is not None]
        if enum:
            result["enum"] = enum
            result.setdefault("type", "string" if isinstance(enum[0], str) else
                              "integer" if isinstance(enum[0], int) and not isinstance(enum[0], bool) else
                              "number" if isinstance(enum[0], float) else "boolean" if isinstance(enum[0], bool) else "string")
        if any(value is None for value in node["enum"]):
            result["nullable"] = True
    if result.get("type") == "array":
        if "items" in node:
            adapted_items = _adapt_node(node["items"], root, depth + 1)
            result["items"] = adapted_items or {"type": "string"}
        elif "prefixItems" in node and isinstance(node["prefixItems"], list) and node["prefixItems"]:
            adapted_items = _adapt_node(node["prefixItems"][0], root, depth + 1)
            result["items"] = adapted_items or {"type": "number"}
        else:
            result["items"] = {"type": "string"}
    if result.get("type") == "object":
        properties = node.get("properties") or {}
        adapted_properties = {name: (_adapt_node(sub, root, depth + 1) or {"type": "string"})
                              for name, sub in properties.items()}
        if adapted_properties:
            result["properties"] = adapted_properties
        required = [name for name in (node.get("required") or []) if name in adapted_properties]
        # Nullable properties must not be required by Gemini's validator.
        result["required"] = [name for name in required if not adapted_properties[name].get("nullable")]
        if not result["required"]:
            result.pop("required")
        # Free-form maps (e.g. IR2 `content`: region name -> content object) are
        # expressible on Gemini only through additionalProperties; dropping it
        # reduced the map to a bare object and every model returned `{}`.
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            adapted_extra = _adapt_node(extra, root, depth + 1)
            if adapted_extra:
                result["additionalProperties"] = adapted_extra
    if not result:
        return {"type": "string"}
    return result


def adapt_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt a JSON Schema (pydantic output) for Gemini's response schema."""
    if not isinstance(schema, dict):
        raise SchemaAdaptationError("Schema must be an object")
    root = copy.deepcopy(schema)
    adapted = _adapt_node(root, root)
    if not isinstance(adapted, dict) or not adapted.get("properties") and adapted.get("type") == "object":
        raise SchemaAdaptationError("Adapted schema lost its properties")
    return adapted


def adapt_schema_for_provider(schema: dict[str, Any], provider: str) -> tuple[dict[str, Any], list[str]]:
    """Return (schema, notes) adapted for the provider's structured-output API.

    OpenRouter consumes standard JSON Schema (with $defs/$ref) unchanged.
    """
    if provider != "gemini":
        return schema, []
    try:
        adapted = adapt_schema_for_gemini(schema)
    except SchemaAdaptationError as error:
        # Never hard-fail a run on adaptation; fall back to a permissive map
        # schema and let downstream validation catch bad output. The note
        # keeps the failure diagnosable in run manifests.
        return {"type": "object"}, [f"schema adaptation fallback: {error}"]
    notes = []
    if "$defs" in schema:
        notes.append(f"inlined {len(schema['$defs'])} $defs definitions for gemini")
    return adapted, notes
