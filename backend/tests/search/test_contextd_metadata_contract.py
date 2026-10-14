"""Tests for the ContextD search metadata payload contract."""

from __future__ import annotations

import importlib.util
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.schemas.search import ContextDTemporalConfig, SearchRequest
from contextd.search.metadata import (
    CONTEXTD_COLLECTION_ID_KEY,
    CONTEXTD_SYSTEM_METADATA_KEY,
    add_contextd_payload_metadata,
    collection_id_match_condition,
    contextd_system_metadata_path,
    normalize_filter_keys_to_contextd,
    system_metadata_match_condition,
)


def test_filter_conditions_use_contextd_payload_keys() -> None:
    """Filter builders use ContextD collection and metadata keys."""
    collection_id = uuid4()

    tenant_condition = collection_id_match_condition(collection_id)
    source_condition = system_metadata_match_condition("source_name", {"value": "gmail"})

    assert tenant_condition == {
        "key": CONTEXTD_COLLECTION_ID_KEY,
        "match": {"value": str(collection_id)},
    }
    assert source_condition == {
        "key": contextd_system_metadata_path("source_name"),
        "match": {"value": "gmail"},
    }


def test_normalizes_short_system_metadata_keys_to_contextd_paths() -> None:
    """Short filter field names are normalized to ContextD metadata paths."""
    normalized = normalize_filter_keys_to_contextd(
        {
            "must": [
                {"key": "source_name", "match": {"value": "github"}},
                {"key": "entity_type", "match": {"value": "IssueEntity"}},
            ]
        }
    )

    assert normalized == {
        "must": [
            {
                "key": contextd_system_metadata_path("source_name"),
                "match": {"value": "github"},
            },
            {
                "key": contextd_system_metadata_path("entity_type"),
                "match": {"value": "IssueEntity"},
            },
        ]
    }


def test_payload_uses_contextd_metadata_shape() -> None:
    """Search payloads contain ContextD metadata and collection-id keys."""
    collection_id = uuid4()
    sync_id = uuid4()
    payload = add_contextd_payload_metadata(
        {"name": "Important entity"},
        collection_id=collection_id,
        system_metadata={
            "source_name": "gmail",
            "entity_type": "EmailEntity",
            "sync_id": str(sync_id),
        },
    )

    assert payload[CONTEXTD_COLLECTION_ID_KEY] == str(collection_id)
    assert payload[CONTEXTD_SYSTEM_METADATA_KEY]["source_name"] == "gmail"
    assert payload[CONTEXTD_SYSTEM_METADATA_KEY]["entity_type"] == "EmailEntity"
    assert [key for key in payload if key.endswith("_collection_id")] == [
        CONTEXTD_COLLECTION_ID_KEY
    ]
    assert [key for key in payload if key.endswith("_system_metadata")] == [
        CONTEXTD_SYSTEM_METADATA_KEY
    ]


def test_search_request_rejects_legacy_parameter_names() -> None:
    """The public search contract rejects old compatibility field names."""
    with pytest.raises(ValidationError) as exc_info:
        SearchRequest.model_validate(
            {
                "query": "customer payment issues",
                "response_type": "raw",
                "search_method": "hybrid",
                "recency_bias": 0.5,
                "expansion_strategy": "llm",
                "enable_reranking": True,
                "enable_query_interpretation": False,
            }
        )

    forbidden_fields = {
        str(error["loc"][0])
        for error in exc_info.value.errors()
        if error["type"] == "extra_forbidden"
    }
    assert forbidden_fields == {
        "response_type",
        "search_method",
        "recency_bias",
        "expansion_strategy",
        "enable_reranking",
        "enable_query_interpretation",
    }


def test_search_contract_has_no_legacy_modules_or_aliases() -> None:
    """Legacy search adapters and aliases are not part of the ContextD contract."""
    assert importlib.util.find_spec("contextd.schemas.search_legacy") is None
    assert importlib.util.find_spec("contextd.search.legacy_adapter") is None
    assert not hasattr(SearchRequest, "response_type")
    assert not hasattr(ContextDTemporalConfig, "decay_scale")
