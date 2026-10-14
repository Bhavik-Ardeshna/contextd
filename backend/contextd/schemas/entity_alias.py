"""Pydantic schemas for entity alias mapping and canonical profiles."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntityAliasMappingCreate(BaseModel):
    """Create alias mapping row."""

    organization_id: UUID
    entity_type: str = Field(..., max_length=128)
    alias_key: str = Field(..., max_length=512)
    canonical_node_id: str = Field(..., max_length=255)
    confidence: Optional[float] = None
    match_method: Optional[str] = Field(None, max_length=64)
    last_seen_sync_id: Optional[UUID] = None


class EntityCanonicalProfileUpsert(BaseModel):
    """Upsert canonical profile."""

    organization_id: UUID
    entity_type: str = Field(..., max_length=128)
    canonical_node_id: str = Field(..., max_length=255)
    merged_properties_json: Optional[Dict[str, Any]] = None
    merged_summary: Optional[str] = None
    embedding_text_hash: Optional[str] = Field(None, max_length=64)
    embedding_json: Optional[List[float]] = None


class EntityCanonicalProfileRead(BaseModel):
    """Read model for canonical profile."""

    id: UUID
    organization_id: UUID
    entity_type: str
    canonical_node_id: str
    merged_properties_json: Optional[Dict[str, Any]] = None
    merged_summary: Optional[str] = None
    embedding_text_hash: Optional[str] = None
    embedding_json: Optional[List[float]] = None
    created_at: datetime
    modified_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )
