"""Schemas for the source setup wizard draft flow."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .context_forge import ContextForgeGraphPreview

SourceSetupStep = Literal["auth", "test", "discover", "scope", "schedule"]
SourceSetupStatus = Literal["draft", "tested", "discovered", "ready", "finalized"]


class SourceConnectionSetupDraftCreate(BaseModel):
    """Create a source setup draft."""

    provider_short_name: str = Field(..., min_length=2)
    target_collection_id: Optional[str] = None
    connection_name: Optional[str] = Field(None, max_length=80)
    description: Optional[str] = Field(None, max_length=255)
    current_step: SourceSetupStep = "auth"
    auth_method: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class SourceConnectionSetupDraftUpdate(BaseModel):
    """Update source setup draft metadata."""

    target_collection_id: Optional[str] = None
    connection_name: Optional[str] = Field(None, max_length=80)
    description: Optional[str] = Field(None, max_length=255)
    current_step: Optional[SourceSetupStep] = None
    status: Optional[SourceSetupStatus] = None
    auth_method: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    scope: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None


class SourceSetupTestRequest(BaseModel):
    """Credentials/config used to test a setup draft.

    Credentials are used for the test operation but raw secret fields are not persisted.
    """

    auth_method: str = "direct"
    credentials: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    target_collection_id: Optional[str] = None
    connection_name: Optional[str] = None


class SourceSetupTestResult(BaseModel):
    """Result of setup test step."""

    status: Literal["passed", "warning", "failed"]
    latency_ms: int
    permissions: List[str]
    object_count: int
    dbt_model_count: int = 0
    message: str
    checked_at: datetime


class DiscoveredField(BaseModel):
    """Column-level schema detail captured during source discovery."""

    name: str
    data_type: Optional[str] = None
    nullable: bool = True
    primary_key: bool = False
    foreign_key: bool = False
    ref_schema: Optional[str] = None
    ref_table: Optional[str] = None
    ref_column: Optional[str] = None
    pii: List[str] = Field(default_factory=list)


class DiscoveredObject(BaseModel):
    """Discovered source object for scope selection."""

    name: str
    type: str = "table"
    rows: int
    columns: int
    foreign_keys: int = 0
    inferred_entity: str
    pii: List[str] = Field(default_factory=list)
    selected: bool = True
    fields: List[DiscoveredField] = Field(default_factory=list)
    primary_keys: List[str] = Field(default_factory=list)
    foreign_key_details: List[Dict[str, Any]] = Field(default_factory=list)


class SourceSetupDiscoverRequest(BaseModel):
    """Discovery request for a setup draft."""

    config: Dict[str, Any] = Field(default_factory=dict)
    credentials: Dict[str, Any] = Field(default_factory=dict)


class SourceSetupDiscovery(BaseModel):
    """Discovery snapshot stored on the draft."""

    source_identity: Dict[str, Any]
    objects: List[DiscoveredObject]
    totals: Dict[str, Any]
    sync_estimate: Dict[str, Any]
    generated_at: datetime
    forge_mapping_id: Optional[UUID] = None
    graph_preview: Optional[ContextForgeGraphPreview] = None


class SourceSetupScopeRequest(BaseModel):
    """Scope selection request."""

    selected_objects: List[str]
    exclude_masks: List[str] = Field(default_factory=list)
    masked_fields: Dict[str, List[str]] = Field(default_factory=dict)
    sample_cap: Optional[int] = None
    pii_acknowledged: bool = False


class SourceSetupScheduleRequest(BaseModel):
    """Schedule/cursor settings request."""

    cadence: str = "every_15_min"
    cursor_field: Optional[str] = None
    backfill_window: str = "all_history"
    dead_letter_behavior: str = "retain_and_alert"


class SourceSetupFinalizeRequest(BaseModel):
    """Finalize a setup draft into a real source connection.

    Credentials are used to create encrypted integration credentials and are not
    stored on the setup draft.
    """

    auth_method: str = "direct"
    credentials: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    scope: Optional[SourceSetupScopeRequest] = None
    schedule: Optional[SourceSetupScheduleRequest] = None
    target_collection_id: Optional[str] = None
    connection_name: Optional[str] = None
    sync_immediately: bool = True


class SourceConnectionSetupDraft(BaseModel):
    """Source setup draft response."""

    id: UUID
    provider_short_name: str
    target_collection_id: Optional[str]
    connection_name: Optional[str]
    description: Optional[str]
    current_step: SourceSetupStep
    status: SourceSetupStatus
    auth_method: Optional[str]
    auth_summary: Optional[Dict[str, Any]]
    config: Optional[Dict[str, Any]]
    test_result: Optional[Dict[str, Any]]
    discovery_snapshot: Optional[Dict[str, Any]]
    scope: Optional[Dict[str, Any]]
    schedule: Optional[Dict[str, Any]]
    finalized_source_connection_id: Optional[UUID]
    created_at: datetime
    modified_at: datetime

    model_config = ConfigDict(from_attributes=True)
