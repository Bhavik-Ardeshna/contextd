"""
Schema normalization utilities for LLM-agnostic MCP tool integration.

This module provides functions to transform MCP tool schemas into a format
that works reliably across all LLM providers (OpenAI, Gemini, Anthropic, etc.).

The normalization ensures:
1. All array types have 'items' field (required by OpenAI, Gemini)
2. All object types have 'properties' field (required by OpenAI)
3. Strict mode support with 'required' and 'additionalProperties'
4. Recursive handling of nested schemas, anyOf, oneOf, allOf
"""

from copy import deepcopy
from typing import Any

from contextd_adk.logging import get_logger

logger = get_logger(__name__)

# JSON Schema keywords that contain nested schemas
SCHEMA_KEYWORDS_WITH_SUBSCHEMAS = frozenset(
    ["anyOf", "oneOf", "allOf", "not", "if", "then", "else"]
)

# Default schema for arrays without items (must be valid for OpenAI/Gemini)
# An empty {} schema is rejected by LLM providers as "missing items"
# Using anyOf with all types preserves the "any type" semantics of empty schema
# This ensures LLM can generate any type of value, matching the original intent
DEFAULT_ARRAY_ITEMS: dict[str, Any] = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "object"},
        {"type": "array", "items": {"type": "string"}},  # Nested array needs items
        {"type": "null"},
    ]
}

# Default type when type is missing
DEFAULT_TYPE = "object"


def normalize_schema_for_llm(
    schema: dict[str, Any],
    strict: bool = False,
    _path: str = "root",
) -> dict[str, Any]:
    """
    Normalize an MCP tool schema for LLM provider compatibility.

    This function transforms MCP schemas to work reliably across all major
    LLM providers (OpenAI, Gemini, Anthropic, Mistral, etc.).

    Transformations applied:
    1. Arrays without 'items' get 'items': {} added
    2. Objects without 'properties' get 'properties': {} added
    3. Missing 'type' is inferred or defaulted to 'object'
    4. Nested schemas (in anyOf, oneOf, etc.) are recursively normalized
    5. If strict=True: adds 'required' and 'additionalProperties: false'

    Args:
        schema: The JSON schema to normalize (from MCP tool inputSchema).
        strict: If True, enable strict mode (all props required, no additional).
        _path: Internal parameter for debug logging (tracks schema path).

    Returns:
        A new normalized schema dict (original is not modified).

    Example:
        >>> schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        >>> normalized = normalize_schema_for_llm(schema, strict=True)
        >>> # Result: items array now has 'items': {}, object has 'required' and 'additionalProperties'
    """
    if not isinstance(schema, dict):
        return schema

    # Deep copy to avoid mutating original
    result = deepcopy(schema)

    # Normalize this schema node
    result = _normalize_schema_node(result, strict, _path)

    return result


def _normalize_schema_node(
    schema: dict[str, Any],
    strict: bool,
    path: str,
) -> dict[str, Any]:
    """
    Normalize a single schema node and recursively process children.

    Args:
        schema: The schema node to normalize.
        strict: Whether to apply strict mode transformations.
        path: Current path in schema for logging.

    Returns:
        Normalized schema node.
    """
    schema_type = schema.get("type")

    # Handle missing type - infer from context
    if schema_type is None:
        schema_type = _infer_type(schema)
        if schema_type:
            schema["type"] = schema_type
            logger.debug(f"Inferred type '{schema_type}' at {path}")

    # Normalize based on type
    if schema_type == "array":
        schema = _normalize_array_schema(schema, strict, path)
    elif schema_type == "object":
        schema = _normalize_object_schema(schema, strict, path)

    # Handle composite schemas (anyOf, oneOf, allOf, etc.)
    for keyword in SCHEMA_KEYWORDS_WITH_SUBSCHEMAS:
        if keyword in schema:
            value = schema[keyword]
            if isinstance(value, list):
                # anyOf, oneOf, allOf contain arrays of schemas
                schema[keyword] = [
                    _normalize_schema_node(
                        sub_schema if isinstance(sub_schema, dict) else sub_schema,
                        strict,
                        f"{path}.{keyword}[{i}]",
                    )
                    if isinstance(sub_schema, dict)
                    else sub_schema
                    for i, sub_schema in enumerate(value)
                ]
            elif isinstance(value, dict):
                # 'not', 'if', 'then', 'else' contain single schema
                schema[keyword] = _normalize_schema_node(value, strict, f"{path}.{keyword}")

    return schema


def _normalize_array_schema(
    schema: dict[str, Any],
    strict: bool,
    path: str,
) -> dict[str, Any]:
    """
    Normalize an array type schema.

    Ensures 'items' field exists and is valid (required by OpenAI, Gemini).
    An empty items schema {} is rejected by LLM providers.

    Args:
        schema: Array schema to normalize.
        strict: Whether to apply strict mode.
        path: Current path for logging.

    Returns:
        Normalized array schema.
    """
    # Ensure 'items' exists - this is the critical fix for LLM compatibility
    if "items" not in schema:
        schema["items"] = DEFAULT_ARRAY_ITEMS.copy()
        logger.debug(f"Added missing 'items' to array at {path}")
    # Handle empty items schema {} - LLM providers reject this as invalid
    elif isinstance(schema.get("items"), dict) and not schema["items"]:
        schema["items"] = DEFAULT_ARRAY_ITEMS.copy()
        logger.debug(f"Replaced empty 'items' schema with default at {path}")

    # Recursively normalize items schema
    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = _normalize_schema_node(items, strict, f"{path}.items")

    # Handle tuple validation (items as array)
    if isinstance(items, list):
        schema["items"] = [
            _normalize_schema_node(item, strict, f"{path}.items[{i}]")
            if isinstance(item, dict)
            else item
            for i, item in enumerate(items)
        ]

    # Normalize additionalItems if present
    if "additionalItems" in schema and isinstance(schema["additionalItems"], dict):
        schema["additionalItems"] = _normalize_schema_node(
            schema["additionalItems"], strict, f"{path}.additionalItems"
        )

    # Normalize contains if present
    if "contains" in schema and isinstance(schema["contains"], dict):
        schema["contains"] = _normalize_schema_node(schema["contains"], strict, f"{path}.contains")

    return schema


def _normalize_object_schema(
    schema: dict[str, Any],
    strict: bool,
    path: str,
) -> dict[str, Any]:
    """
    Normalize an object type schema.

    Ensures 'properties' field exists (required by OpenAI).
    In strict mode, adds 'required' and 'additionalProperties: false'.

    Args:
        schema: Object schema to normalize.
        strict: Whether to apply strict mode.
        path: Current path for logging.

    Returns:
        Normalized object schema.
    """
    # Ensure 'properties' exists
    if "properties" not in schema:
        schema["properties"] = {}
        logger.debug(f"Added missing 'properties' to object at {path}")

    # Recursively normalize each property
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for prop_name, prop_schema in properties.items():
            if isinstance(prop_schema, dict):
                properties[prop_name] = _normalize_schema_node(
                    prop_schema, strict, f"{path}.properties.{prop_name}"
                )

    # Normalize additionalProperties if it's a schema
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        schema["additionalProperties"] = _normalize_schema_node(
            schema["additionalProperties"], strict, f"{path}.additionalProperties"
        )

    # Normalize patternProperties if present
    if "patternProperties" in schema and isinstance(schema["patternProperties"], dict):
        for pattern, pattern_schema in schema["patternProperties"].items():
            if isinstance(pattern_schema, dict):
                schema["patternProperties"][pattern] = _normalize_schema_node(
                    pattern_schema, strict, f"{path}.patternProperties.{pattern}"
                )

    # Apply strict mode transformations
    if strict:
        schema = _apply_strict_mode(schema, path)

    return schema


def _apply_strict_mode(schema: dict[str, Any], path: str) -> dict[str, Any]:
    """
    Apply strict mode transformations to an object schema.

    Strict mode ensures:
    1. All properties are required
    2. No additional properties allowed

    This enables OpenAI's strict mode which guarantees LLM outputs
    match the schema exactly.

    Args:
        schema: Object schema to make strict.
        path: Current path for logging.

    Returns:
        Schema with strict mode applied.
    """
    properties = schema.get("properties", {})

    # Add all properties to 'required' if not already set
    if "required" not in schema and properties:
        schema["required"] = list(properties.keys())
        logger.debug(f"Added 'required' with all properties at {path}")

    # Disallow additional properties
    if "additionalProperties" not in schema:
        schema["additionalProperties"] = False
        logger.debug(f"Set 'additionalProperties: false' at {path}")

    return schema


def _infer_type(schema: dict[str, Any]) -> str | None:
    """
    Infer the type of a schema from its structure.

    Args:
        schema: Schema to infer type for.

    Returns:
        Inferred type string or None if cannot be determined.
    """
    # If has 'properties', 'additionalProperties', 'patternProperties' -> object
    if any(key in schema for key in ["properties", "additionalProperties", "patternProperties"]):
        return "object"

    # If has 'items', 'additionalItems', 'contains' -> array
    if any(key in schema for key in ["items", "additionalItems", "contains"]):
        return "array"

    # If has 'enum' but no type, don't infer (could be any type)
    if "enum" in schema:
        return None

    # If has anyOf/oneOf/allOf, don't infer type
    if any(key in schema for key in SCHEMA_KEYWORDS_WITH_SUBSCHEMAS):
        return None

    # Default: if schema has keys but no type, default to object
    # This handles cases like {"description": "...", "default": ...}
    if schema and "type" not in schema:
        return DEFAULT_TYPE

    return None


def ensure_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Convenience function to normalize schema with strict mode enabled.

    This is equivalent to normalize_schema_for_llm(schema, strict=True).

    Use this when you want to enable OpenAI's strict mode for guaranteed
    schema compliance in LLM outputs.

    Args:
        schema: The JSON schema to normalize.

    Returns:
        Normalized schema with strict mode applied.
    """
    return normalize_schema_for_llm(schema, strict=True)
