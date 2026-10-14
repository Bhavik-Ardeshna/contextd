"""Schemas for LLM-powered entity extraction from unstructured content.

NOTE: LLM extraction configuration is now defined in contextd.platform.entities._metadata.LLMExtractionConfig.
This file contains result schemas used by the LLMEnrichmentService.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeTypeEnum(str, Enum):
    """Supported node types for extraction."""
    PERSON_NODE = "PersonNode"
    COMPANY_NODE = "CompanyNode"
    PROJECT_NODE = "ProjectNode"
    TASK_NODE = "TaskNode"
    TOPIC_NODE = "TopicNode"
    TAG_NODE = "TagNode"
    TEAM_NODE = "TeamNode"


class EdgeTypeEnum(str, Enum):
    """Supported edge types."""
    MENTIONS = "MENTIONS"
    DISCUSSES = "DISCUSSES"
    REFERENCES = "REFERENCES"
    ASSIGNS = "ASSIGNS"
    COLLABORATES_WITH = "COLLABORATES_WITH"


class ExtractedEntity(BaseModel):
    """An entity extracted by LLM.

    The edge_type is stored in properties["_edge_type"] and will be used
    by normalizers to create LLMExtractionRef with proper graph edges.
    """
    type: str
    properties: Dict[str, Any]  # Includes _edge_type for graph edge creation
    confidence: float
    source_field: str
    source_text_snippet: Optional[str] = None


class ExtractionResult(BaseModel):
    """Result of LLM extraction for a single entity.

    Note: relationships field is kept for backward compatibility but is no longer used.
    Edge information is now stored in each entity's _edge_type property, and
    normalizers convert entities to LLMExtractionRef for proper graph event generation.
    """
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relationships: List[Any] = Field(default_factory=list)  # Deprecated, kept for compatibility
    extraction_duration_ms: int
    model_used: str
    tokens_used: Optional[int] = None
