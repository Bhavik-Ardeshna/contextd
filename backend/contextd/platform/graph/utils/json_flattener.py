"""JSON flattening utilities for Neo4j compatibility.

Neo4j node/edge properties only support primitive types:
- String, Integer, Float, Boolean
- Arrays of primitives (homogeneous)

This module provides utilities to flatten nested JSON structures
for Neo4j storage and unflatten them when retrieved.

Example:
    >>> data = {"user": {"name": "John", "roles": ["admin", "user"]}}
    >>> flattened = flatten_for_neo4j(data)
    >>> # {"user": '{"name": "John", "roles": ["admin", "user"]}'}
    >>> original = unflatten_from_neo4j(flattened)
    >>> # {"user": {"name": "John", "roles": ["admin", "user"]}}
"""

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID

logger = logging.getLogger(__name__)


# Fields that should always be serialized as JSON strings
ALWAYS_SERIALIZE_FIELDS: Set[str] = {
    "custom_fields",
    "attributes",
    "metadata",
    "properties",
    "extra",
    "config",
    "settings",
}

# Fields that should preserve as primitive arrays if possible
PRESERVE_ARRAY_FIELDS: Set[str] = {
    "tags",
    "labels",
    "categories",
    "email_domains",
}


def _is_primitive(value: Any) -> bool:
    """Check if value is a Neo4j-compatible primitive.

    Args:
        value: Value to check

    Returns:
        True if value is a primitive type
    """
    return isinstance(value, (str, int, float, bool, type(None)))


def _is_primitive_array(value: List) -> bool:
    """Check if list contains only homogeneous primitives.

    Neo4j only supports arrays of the same primitive type.

    Args:
        value: List to check

    Returns:
        True if list is a valid Neo4j array
    """
    if not value:
        return True  # Empty list is valid

    first_type = type(value[0])
    if first_type not in (str, int, float, bool):
        return False

    return all(isinstance(v, first_type) for v in value)


def _serialize_value(value: Any) -> str:
    """Serialize a value to JSON string.

    Handles special types like datetime, UUID, etc.

    Args:
        value: Value to serialize

    Returns:
        JSON string representation
    """
    def json_encoder(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, UUID):
            return str(obj)
        elif hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        elif hasattr(obj, "__dict__"):
            return obj.__dict__
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(value, default=json_encoder, ensure_ascii=False)


def flatten_value(value: Any, field_name: Optional[str] = None) -> Any:
    """Flatten a single value for Neo4j storage.

    Args:
        value: Value to flatten
        field_name: Optional field name for context-aware handling

    Returns:
        Neo4j-compatible value
    """
    if value is None:
        return None

    # Handle primitives
    if _is_primitive(value):
        return value

    # Handle datetime types
    if isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, date):
        return value.isoformat()

    # Handle UUID
    if isinstance(value, UUID):
        return str(value)

    # Handle lists
    if isinstance(value, list):
        # Check if it's a list of primitives we can preserve
        if field_name in PRESERVE_ARRAY_FIELDS:
            # Try to convert to string array
            try:
                str_array = [str(v) if not isinstance(v, str) else v for v in value]
                return str_array
            except Exception:
                pass

        # Check if it's already a valid Neo4j array
        if _is_primitive_array(value):
            return value

        # Serialize to JSON string
        return _serialize_value(value)

    # Handle dicts - always serialize
    if isinstance(value, dict):
        return _serialize_value(value)

    # Handle Pydantic models
    if hasattr(value, "model_dump"):
        return _serialize_value(value.model_dump(mode="json"))

    # Fallback: convert to string
    try:
        return str(value)
    except Exception:
        return _serialize_value(value)


def flatten_for_neo4j(
    properties: Dict[str, Any],
    exclude_fields: Optional[Set[str]] = None,
    include_only: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Flatten a dictionary for Neo4j node/edge storage.

    Converts nested JSON structures to JSON strings while preserving
    primitives and valid arrays.

    Args:
        properties: Dictionary of properties to flatten
        exclude_fields: Fields to exclude from output
        include_only: If provided, only include these fields

    Returns:
        Flattened dictionary safe for Neo4j storage

    Example:
        >>> data = {
        ...     "name": "John",
        ...     "age": 30,
        ...     "tags": ["admin", "user"],
        ...     "profile": {"bio": "Developer", "skills": ["Python", "Neo4j"]}
        ... }
        >>> flatten_for_neo4j(data)
        {
            "name": "John",
            "age": 30,
            "tags": ["admin", "user"],
            "profile": '{"bio": "Developer", "skills": ["Python", "Neo4j"]}'
        }
    """
    if not properties:
        return {}

    exclude_fields = exclude_fields or set()
    flattened = {}

    for key, value in properties.items():
        # Skip excluded fields
        if key in exclude_fields:
            continue

        # Apply include filter if provided
        if include_only and key not in include_only:
            continue

        # Skip None values
        if value is None:
            continue

        # Always serialize certain fields
        if key in ALWAYS_SERIALIZE_FIELDS and isinstance(value, (dict, list)):
            flattened[key] = _serialize_value(value)
            continue

        # Flatten the value
        flattened[key] = flatten_value(value, field_name=key)

    return flattened


def _try_parse_json(value: str) -> Union[Dict, List, str]:
    """Try to parse a string as JSON.

    Args:
        value: String that might be JSON

    Returns:
        Parsed JSON or original string if not valid JSON
    """
    if not value or not isinstance(value, str):
        return value

    # Quick check for JSON-like strings
    stripped = value.strip()
    if not (stripped.startswith(("{", "[")) and stripped.endswith(("}", "]"))):
        return value

    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def unflatten_from_neo4j(
    properties: Dict[str, Any],
    json_fields: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Unflatten Neo4j properties back to nested structures.

    Parses JSON string fields back to their original dict/list forms.

    Args:
        properties: Dictionary of properties from Neo4j
        json_fields: Known fields that should be parsed as JSON
                    (if None, attempts auto-detection)

    Returns:
        Dictionary with nested structures restored

    Example:
        >>> data = {
        ...     "name": "John",
        ...     "profile": '{"bio": "Developer"}'
        ... }
        >>> unflatten_from_neo4j(data)
        {"name": "John", "profile": {"bio": "Developer"}}
    """
    if not properties:
        return {}

    json_fields = json_fields or ALWAYS_SERIALIZE_FIELDS
    unflattened = {}

    for key, value in properties.items():
        if value is None:
            unflattened[key] = None
            continue

        # Check if this is a known JSON field
        if key in json_fields and isinstance(value, str):
            unflattened[key] = _try_parse_json(value)
            continue

        # Auto-detect JSON strings
        if isinstance(value, str):
            unflattened[key] = _try_parse_json(value)
        else:
            unflattened[key] = value

    return unflattened


def build_indexable_text(
    properties: Dict[str, Any],
    fields: List[str],
    separator: str = "\n",
    include_field_names: bool = True,
) -> str:
    """Build indexable text from entity properties.

    Creates a text representation of entity data suitable for
    embedding and fulltext indexing.

    Args:
        properties: Entity properties dictionary
        fields: List of field names to include (in order)
        separator: Separator between field values
        include_field_names: Whether to prefix values with field names

    Returns:
        Combined text representation

    Example:
        >>> props = {"name": "Fix bug", "description": "Critical issue"}
        >>> build_indexable_text(props, ["name", "description"])
        "name: Fix bug\\ndescription: Critical issue"
    """
    parts = []

    for field in fields:
        value = properties.get(field)
        if value is None:
            continue

        # Convert value to text
        if isinstance(value, str):
            text = value
        elif isinstance(value, (list, dict)):
            # For complex types, use JSON but make it more readable
            text = json.dumps(value, ensure_ascii=False, indent=None)
        else:
            text = str(value)

        # Skip empty text
        if not text.strip():
            continue

        # Format with or without field name
        if include_field_names:
            parts.append(f"{field}: {text}")
        else:
            parts.append(text)

    return separator.join(parts)
