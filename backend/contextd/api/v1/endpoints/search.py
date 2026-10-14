"""Collections search endpoints.

These endpoints are mounted under the `/collections` prefix in `api/v1/api.py`.
Search is now provided by POST /collections/{readable_id}/graph-search (see graph_chat.py).
This module keeps only GET /collections/internal/filter-schema for filter validation.
"""

from typing import Any, Dict

from contextd.api.router import TrailingSlashRouter

router = TrailingSlashRouter()


@router.get("/internal/filter-schema")
async def get_filter_schema() -> Dict[str, Any]:
    """Get the JSON schema for ContextD filter validation.

    This endpoint returns the JSON schema that can be used to validate
    filter objects in the frontend.
    """
    condition_schema: Dict[str, Any] = {
        "type": "object",
        "required": ["key"],
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string", "minLength": 1},
            "match": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "value": {},
                    "any": {"type": "array", "items": {}},
                },
                "minProperties": 1,
            },
            "range": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "gt": {},
                    "gte": {},
                    "lt": {},
                    "lte": {},
                },
                "minProperties": 1,
            },
        },
        "anyOf": [
            {"required": ["match"]},
            {"required": ["range"]},
        ],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ContextDFilter",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "must": {"type": "array", "items": condition_schema},
            "should": {"type": "array", "items": condition_schema},
            "must_not": {"type": "array", "items": condition_schema},
            "minimum_should_match": {"type": "integer", "minimum": 0},
        },
    }
