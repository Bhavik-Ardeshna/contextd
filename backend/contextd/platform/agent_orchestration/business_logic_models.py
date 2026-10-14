"""Typed models and constants for connector business logic."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class NodeTypeSchemaPayload(BaseModel):
    """Payload for one node-type document derived from the live graph schema.

    Relationship semantics live only in the explanation text; no rel_type in payload.
    """

    node_type: str = Field(..., description="Node type name (e.g. GmailMessage)")
    source_type: str = Field(..., description="Connector short_name (e.g. gmail)")
    organization_id: str = Field(..., description="Organization UUID as string")
    properties: List[str] = Field(
        default_factory=list,
        description="Useful property keys for this node type",
    )
    explanation: str = Field(
        ...,
        description="Rich semantic explanation (includes how it connects to other types)",
    )


class ConnectorBusinessLogic(BaseModel):
    """Per-connector business logic: node types, rel types, useful property keys.

    One record per source_type (e.g. gmail, notion). Used to build dynamic
    vocabulary and Cypher contract for agent prompts.
    """

    source_type: str = Field(..., description="Connector short_name (e.g. gmail, notion)")
    node_types: List[str] = Field(
        default_factory=list,
        description="Entity/node type names (e.g. GmailMessageEntity)",
    )
    rel_types: List[str] = Field(
        default_factory=lambda: ["RELATES_TO"],
        description="Relationship types used in the graph",
    )
    entity_property_shapes: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Node type -> list of useful property keys (noise filtered out)",
    )
    schema_narrative: Optional[str] = Field(
        default=None,
        description="Text describing how entity types connect and what they mean (for prompts)",
    )
    node_id_prefix_to_type: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional mapping from node_id prefix to node_type for display",
    )

    def merge_with(self, other: "ConnectorBusinessLogic") -> "ConnectorBusinessLogic":
        """Merge another connector's logic into this one (union of types and shapes)."""
        node_types = list(dict.fromkeys(self.node_types + other.node_types))
        rel_types = list(dict.fromkeys(self.rel_types + other.rel_types))
        shapes = dict(self.entity_property_shapes)
        for key, values in other.entity_property_shapes.items():
            shapes[key] = list(dict.fromkeys(shapes.get(key, []) + values))
        narratives = [text for text in (self.schema_narrative, other.schema_narrative) if text]
        schema_narrative = "\n\n".join(narratives) if narratives else None
        return ConnectorBusinessLogic(
            source_type=self.source_type,
            node_types=node_types,
            rel_types=rel_types,
            entity_property_shapes=shapes,
            schema_narrative=schema_narrative,
            node_id_prefix_to_type=self.node_id_prefix_to_type or other.node_id_prefix_to_type,
        )
