"""Database entity normalizer.

Handles normalization of database entities (PolymorphicEntity) with support for:
- Foreign key relationships via GraphEdgeConfig
- Automatic relation extraction from entity metadata
"""

import logging
from typing import Any, List

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._metadata import GraphEdgeConfig
from contextd.platform.entities._normalized import (
    NormalizedEntity,
    RelationRef,
    RelationType,
)
from contextd.platform.sync.pii_masking import (
    MASKED_FIELDS_PROPERTY,
    MASKING_POLICY_PROPERTY,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)

logger = logging.getLogger(__name__)


@register_normalizer(r".*TableEntity$", source_type="database")
class DatabaseEntityNormalizer(BaseEntityNormalizer):
    """Normalizer for database entities (PolymorphicEntity).

    Extracts relations from fields with GraphEdgeConfig metadata,
    converting foreign keys into RelationRef objects for graph edge creation.
    """

    source_type = "database"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize a database entity to NormalizedEntity format.

        Args:
            entity: Database entity (PolymorphicEntity)

        Returns:
            NormalizedEntity with relations extracted from foreign keys
        """
        # Get entity metadata
        entity_metadata = getattr(entity.__class__, "_entity_metadata", None)
        if not entity_metadata:
            # Fall back to DefaultEntityNormalizer (super().normalize returns None)
            logger.debug(
                f"No _entity_metadata on {entity.__class__.__name__}, "
                f"falling back to DefaultEntityNormalizer"
            )
            from contextd.platform.sync.normalizers._base import DefaultEntityNormalizer
            return DefaultEntityNormalizer().normalize(entity)

        # Extract basic fields
        entity_id = getattr(entity, "entity_id", None) or str(id(entity))

        # Extract name from entity metadata (field marked as is_name=True)
        name = None
        if entity_metadata and entity_metadata.fields:
            for field_name, field_meta in entity_metadata.fields.items():
                if field_meta.is_name:
                    name = getattr(entity, field_name, None)
                    if name:
                        break

        # Fallback to entity.name or table_name
        if not name:
            name = getattr(entity, "name", None) or getattr(entity, "table_name", "Unknown")

        # Try to get source type
        source_type = "database"
        if hasattr(entity, "contextd_system_metadata") and entity.contextd_system_metadata:
            source_type = entity.contextd_system_metadata.source_name or "database"

        # Extract timestamps
        created_at = self.parse_datetime(getattr(entity, "created_at", None))
        updated_at = self.parse_datetime(getattr(entity, "updated_at", None))

        # Extract breadcrumbs
        breadcrumb_ids, breadcrumb_names = self.extract_breadcrumbs(entity)

        # Extract description/content
        description = getattr(entity, "description", None)
        content = getattr(entity, "content", None) or getattr(entity, "summary", None)

        # Extract web_url
        web_url = self.extract_web_url(entity)

        # Extract relations from fields with GraphEdgeConfig
        relations = self._extract_relations_from_metadata(entity, entity_metadata)
        if relations:
            logger.debug(
                f"{entity.__class__.__name__} entity_id={entity_id}: "
                f"{len(relations)} relation(s) extracted"
            )

        # Collect all other fields as properties
        # Use display_name from metadata when available
        _skip = {
            "entity_id", "name", "breadcrumbs",
            "created_at", "updated_at", "description",
            "summary", "content", "textual_representation",
            "contextd_system_metadata",
            "table_name", "schema_name", "primary_key_columns",
        }
        # Build display_name lookup
        _display = {}
        if entity_metadata and entity_metadata.fields:
            for fn, fm in entity_metadata.fields.items():
                if fm.display_name:
                    _display[fn] = fm.display_name
        properties = {}
        for field_name in entity.model_fields.keys():
            if field_name not in _skip:
                value = getattr(entity, field_name, None)
                if value is not None:
                    # Use display_name as key if available
                    key = _display.get(field_name, field_name)
                    properties[key] = (
                        self._serialize_for_json(value)
                    )

        table_name = getattr(entity, "table_name", None)
        schema_name = getattr(entity, "schema_name", None)
        if table_name:
            properties["source_object"] = table_name
        if schema_name:
            properties["source_schema"] = schema_name
        masked_fields = (
            getattr(getattr(entity, "contextd_system_metadata", None), "masked_fields", None)
            or {}
        )
        if masked_fields:
            properties[MASKED_FIELDS_PROPERTY] = masked_fields
            properties[MASKING_POLICY_PROPERTY] = {
                "strategy": "redact",
                "source": "scope",
            }

        # Convert LLM extractions if present
        llm_extractions = self.convert_llm_extractions_to_refs(entity)

        # Prefer semantic node type from metadata (LLM-inferred),
        # fall back to class name for backward compatibility
        entity_type = entity.__class__.__name__
        if (
            entity_metadata
            and entity_metadata.default_graph_node_type
        ):
            entity_type = entity_metadata.default_graph_node_type

        return NormalizedEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            source_type=source_type,
            name=name,
            description=description,
            content=content,
            web_url=web_url,
            people=[],
            tags=[],
            relations=relations,
            status=None,
            priority=None,
            custom_fields=[],
            llm_extractions=llm_extractions,
            created_at=created_at,
            updated_at=updated_at,
            properties=properties,
            breadcrumb_ids=breadcrumb_ids,
            breadcrumb_names=breadcrumb_names,
        )

    def _extract_relations_from_metadata(
        self,
        entity: BaseEntity,
        entity_metadata,
    ) -> List[RelationRef]:
        """Extract relations from fields with GraphEdgeConfig metadata.

        Args:
            entity: Database entity
            entity_metadata: EntityMetadata instance

        Returns:
            List of RelationRef objects for foreign key relationships
        """
        relations = []

        if not entity_metadata or not entity_metadata.fields:
            return relations

        # Iterate through fields with metadata
        for field_name, field_meta in entity_metadata.fields.items():
            # Check if field has GraphEdgeConfig
            if not field_meta.graph or not isinstance(field_meta.graph, GraphEdgeConfig):
                continue

            # Get the foreign key value from the entity
            fk_value = getattr(entity, field_name, None)
            if not fk_value:
                continue

            # Get graph edge config
            edge_config: GraphEdgeConfig = field_meta.graph

            # Target entity_type must match the graph node type generated by
            # schema discovery and Context Forge. Older code converted
            # DatabaseTableNode_* back into dynamic class names, which made the
            # committed graph topology correct but left edge metadata out of
            # sync with the Forge schema.
            target_entity_type = self._node_type_to_entity_type(edge_config.to_node_type)

            # Construct target entity ID in format: {schema}.{table}:{primary_key_value}
            # We need to infer the table name from the entity type or node type
            target_table_key = self._get_target_table_key(entity, field_name, edge_config.to_node_type)
            target_entity_id = f"{target_table_key}:{fk_value}"

            # Create relation ref
            relation = RelationRef(
                entity_id=target_entity_id,
                entity_type=target_entity_type,
                relation_type=RelationType.RELATED_TO,  # Default relation type
                name=None,  # We don't have the target name at this point
                properties={
                    "source_column": field_name,
                    "target_table": target_table_key,
                    "target_node_type": target_entity_type,
                    "edge_type": edge_config.edge_type,
                    "reverse_edge_type": edge_config.reverse_edge_type,
                },
            )
            relations.append(relation)

        return relations

    def _get_target_table_key(
        self,
        entity: BaseEntity,
        field_name: str,
        node_type: str,
    ) -> str:
        """Get target table key for foreign key relationship.

        Uses the DatabaseSchemaRegistry to look up table keys
        by node type, falling back to heuristics.
        """
        # Introspected schema: DatabaseTableNode_{schema}_{table}
        if (
            node_type.startswith("DatabaseTableNode_")
            and "_" in node_type[18:]
        ):
            prefix = "DatabaseTableNode_"
            rest = node_type[len(prefix):]
            parts = rest.split("_", 1)
            if len(parts) == 2:
                return f"{parts[0]}.{parts[1]}"

        schema_name = getattr(entity, "schema_name", "public")

        # Look up registry for node_type -> table mapping
        try:
            from contextd.platform.configs.database.registry import (
                DatabaseSchemaRegistry,
            )
            for db_type in ("clickhouse", "postgres"):
                all_schemas = (
                    DatabaseSchemaRegistry.get_all_schemas(db_type)
                )
                for tkey, tdef in all_schemas.items():
                    if (
                        tdef.table_metadata
                        and tdef.table_metadata
                        .default_graph_node_type
                        == node_type
                    ):
                        return tkey
        except Exception:
            pass

        # Infer from field name: person_id -> persons
        if field_name.endswith("_id"):
            table_name = field_name[:-3]
            if not table_name.endswith("s"):
                table_name = table_name + "s"
            return f"{schema_name}.{table_name}"

        # Infer from node type: PersonNode -> persons
        if node_type.endswith("Node"):
            base_name = node_type[:-4].lower()
            if base_name.endswith("y"):
                table_name = base_name[:-1] + "ies"
            elif not base_name.endswith("s"):
                table_name = base_name + "s"
            else:
                table_name = base_name
            return f"{schema_name}.{table_name}"

        return f"{schema_name}.{field_name}"

    def _node_type_to_entity_type(self, node_type: str) -> str:
        """Convert graph node type to entity type for relation targets.

        After the normalizer uses default_graph_node_type as entity_type,
        relation targets must use the same semantic graph type. This keeps
        EDGE_CREATE payloads, Neo4j properties, and Context Forge mapping rows
        speaking the same schema vocabulary.
        """
        return node_type

    def _serialize_for_json(self, value: Any) -> Any:
        """Recursively serialize datetime objects for JSON.

        Args:
            value: Value to serialize

        Returns:
            JSON-serializable value
        """
        from datetime import date, datetime, time

        if isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, date):
            return value.isoformat()
        elif isinstance(value, time):
            return value.isoformat()
        elif isinstance(value, dict):
            return {k: self._serialize_for_json(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._serialize_for_json(item) for item in value]
        else:
            return value
