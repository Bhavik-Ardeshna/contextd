"""Test PostgreSQL schema definitions.

Simple test schemas for validation and testing purposes.
"""

from typing import ClassVar

from contextd.platform.configs.database.metadata import ColumnMetadata, TableMetadata
from contextd.platform.configs.database.schema import (
    DatabaseColumn,
    DatabaseTable,
)
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    LLMExtractionConfig,
    SearchConfig,
)


class SimpleTable(DatabaseTable):
    """Simple test table with embeddable field."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="SimpleNode",
        create_entity_node=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
        ),
        columns={
            "id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "name": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "description": ColumnMetadata(
                search=SearchConfig(embeddable=True),
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="simple_table",
            schema_name="public",
            description="Simple test table",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="UUID",
                    nullable=False,
                    primary_key=True,
                ),
                "name": DatabaseColumn(
                    name="name",
                    column_type="VARCHAR",
                    length=255,
                    nullable=False,
                ),
                "description": DatabaseColumn(
                    name="description",
                    column_type="TEXT",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


class LLMTestTable(DatabaseTable):
    """Test table with LLM extraction enabled."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="LLMTestNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        columns={
            "id": ColumnMetadata(is_entity_id=True),
            "content": ColumnMetadata(
                search=SearchConfig(embeddable=True),
                llm=LLMExtractionConfig(
                    enabled=True,
                    extract_people=True,
                    extract_companies=True,
                    extract_topics=True,
                ),
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="llm_test_table",
            schema_name="public",
            description="Test table with LLM extraction",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="UUID",
                    nullable=False,
                    primary_key=True,
                ),
                "content": DatabaseColumn(
                    name="content",
                    column_type="TEXT",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


# Test schema definitions
TEST_POSTGRES_SCHEMA_DEFINITIONS: dict[str, DatabaseTable] = {
    "public.simple_table": SimpleTable(),
    "public.llm_test_table": LLMTestTable(),
}
