"""PostgreSQL schema definitions with graph/LLM/embedding metadata.

Example schema definitions for PostgreSQL tables. These define tables, columns,
and their metadata BEFORE connecting to the database.

Similar to how entity definitions work for connectors like Gmail, Pipedrive, etc.
"""

from typing import ClassVar

from contextd.platform.configs.database.metadata import ColumnMetadata, TableMetadata
from contextd.platform.configs.database.schema import (
    DatabaseColumn,
    DatabaseTable,
    ForeignKeyConfig,
    IndexConfig,
)
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    GraphEdgeConfig,
    SearchConfig,
    # LLMExtractionConfig,  # Will add LLM extraction later when needed
)


class UsersTable(DatabaseTable):
    """Users table schema definition with graph/LLM/embedding config.

    Example table with:
    - Embeddable bio field
    - LLM extraction from bio
    - Graph relationships
    """

    # Table-level metadata (like _entity_metadata ClassVar)
    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="UserNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["full_name", "email"],
        ),
        columns={
            "user_id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "email": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                graph=GraphEdgeConfig(
                    edge_type="HAS_EMAIL",
                    to_node_type="EmailNode",
                ),
            ),
            "full_name": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
                is_name=True,
            ),
            "bio": ColumnMetadata(
                search=SearchConfig(embeddable=True),
                # LLM extraction removed - will add later
            ),
            "created_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_created_at=True,
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="users",
            schema_name="public",
            description="User accounts table",
            columns={
                "user_id": DatabaseColumn(
                    name="user_id",
                    column_type="UUID",
                    nullable=False,
                    primary_key=True,
                ),
                "email": DatabaseColumn(
                    name="email",
                    column_type="VARCHAR",
                    length=255,
                    nullable=False,
                    unique=True,
                    indexed=True,
                ),
                "full_name": DatabaseColumn(
                    name="full_name",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                ),
                "bio": DatabaseColumn(
                    name="bio",
                    column_type="TEXT",
                    nullable=True,
                ),
                "created_at": DatabaseColumn(
                    name="created_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                    default="CURRENT_TIMESTAMP",
                ),
            },
            primary_keys=["user_id"],
            indexes=[
                IndexConfig(name="idx_users_email", columns=["email"]),
            ],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]




class LeadsTable(DatabaseTable):
    """Leads table - potential customers and lead tracking."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="LeadNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "email", "source"],
        ),
        columns={
            "id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "person_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "name": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "email": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "phone": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "status": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "source": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "utm_campaign": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "utm_source": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "utm_medium": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "created_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_created_at=True,
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="leads",
            schema_name="public",
            description="Sales leads and potential customers",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="SERIAL",
                    nullable=False,
                    primary_key=True,
                ),
                "person_id": DatabaseColumn(
                    name="person_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="person_id",
                        ref_schema="public",
                        ref_table="persons",
                        ref_column="id",
                    ),
                ),
                "created_at": DatabaseColumn(
                    name="created_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                ),
                "status": DatabaseColumn(
                    name="status",
                    column_type="leadstatus",  # Enum type
                    nullable=False,
                ),
                "source": DatabaseColumn(
                    name="source",
                    column_type="leadsource",  # Enum type
                    nullable=False,
                ),
                "email": DatabaseColumn(
                    name="email",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                    indexed=True,
                ),
                "phone": DatabaseColumn(
                    name="phone",
                    column_type="VARCHAR",
                    length=50,
                    nullable=True,
                ),
                "name": DatabaseColumn(
                    name="name",
                    column_type="VARCHAR",
                    length=200,
                    nullable=True,
                ),
                "utm_campaign": DatabaseColumn(
                    name="utm_campaign",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                ),
                "utm_source": DatabaseColumn(
                    name="utm_source",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                ),
                "utm_medium": DatabaseColumn(
                    name="utm_medium",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                ),
                "attributes": DatabaseColumn(
                    name="attributes",
                    column_type="JSON",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
            foreign_keys=[
                ForeignKeyConfig(
                    column="person_id",
                    ref_schema="public",
                    ref_table="persons",
                    ref_column="id",
                ),
            ],
            indexes=[
                IndexConfig(name="ix_leads_email", columns=["email"]),
                IndexConfig(name="ix_leads_person_id", columns=["person_id"]),
            ],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


class ProductsTable(DatabaseTable):
    """Products table - product catalog."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="ProductNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "category"],
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
            "category": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="products",
            schema_name="public",
            description="Product catalog",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="SERIAL",
                    nullable=False,
                    primary_key=True,
                ),
                "name": DatabaseColumn(
                    name="name",
                    column_type="VARCHAR",
                    length=255,
                    nullable=False,
                ),
                "category": DatabaseColumn(
                    name="category",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "attributes": DatabaseColumn(
                    name="attributes",
                    column_type="JSON",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


class PersonsTable(DatabaseTable):
    """Persons table - customer/contact information."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="PersonNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["first_name", "last_name", "primary_email"],
        ),
        columns={
            "id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "first_name": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
            ),
            "last_name": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
            ),
            "primary_email": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "primary_phone": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "country": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "region": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "city": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=0.5),
            ),
            "created_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_created_at=True,
            ),
            "updated_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_updated_at=True,
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="persons",
            schema_name="public",
            description="Person/customer contact information",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="SERIAL",
                    nullable=False,
                    primary_key=True,
                ),
                "created_at": DatabaseColumn(
                    name="created_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                ),
                "updated_at": DatabaseColumn(
                    name="updated_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                ),
                "primary_email": DatabaseColumn(
                    name="primary_email",
                    column_type="VARCHAR",
                    length=255,
                    nullable=True,
                    indexed=True,
                ),
                "primary_phone": DatabaseColumn(
                    name="primary_phone",
                    column_type="VARCHAR",
                    length=50,
                    nullable=True,
                ),
                "first_name": DatabaseColumn(
                    name="first_name",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "last_name": DatabaseColumn(
                    name="last_name",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "country": DatabaseColumn(
                    name="country",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "region": DatabaseColumn(
                    name="region",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "city": DatabaseColumn(
                    name="city",
                    column_type="VARCHAR",
                    length=100,
                    nullable=True,
                ),
                "language": DatabaseColumn(
                    name="language",
                    column_type="VARCHAR",
                    length=10,
                    nullable=True,
                ),
                "attributes": DatabaseColumn(
                    name="attributes",
                    column_type="JSON",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
            indexes=[
                IndexConfig(name="ix_persons_primary_email", columns=["primary_email"]),
            ],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


class SupportTicketsTable(DatabaseTable):
    """Support tickets table with relationships to persons, leads, and products."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="SupportTicketNode",
        create_entity_node=True,
        enable_llm_enrichment=False,  # LLM extraction disabled for now
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["summary", "status", "category"],
        ),
        columns={
            "id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "person_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "lead_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "product_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "summary": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
                # LLM extraction removed - will add later
            ),
            "status": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "priority": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "category": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "sentiment_score": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
            "created_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_created_at=True,
            ),
            "closed_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="support_tickets",
            schema_name="public",
            description="Customer support tickets",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="SERIAL",
                    nullable=False,
                    primary_key=True,
                ),
                "person_id": DatabaseColumn(
                    name="person_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="person_id",
                        ref_schema="public",
                        ref_table="persons",
                        ref_column="id",
                    ),
                ),
                "lead_id": DatabaseColumn(
                    name="lead_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="lead_id",
                        ref_schema="public",
                        ref_table="leads",
                        ref_column="id",
                    ),
                ),
                "product_id": DatabaseColumn(
                    name="product_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="product_id",
                        ref_schema="public",
                        ref_table="products",
                        ref_column="id",
                    ),
                ),
                "created_at": DatabaseColumn(
                    name="created_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                ),
                "closed_at": DatabaseColumn(
                    name="closed_at",
                    column_type="TIMESTAMP",
                    nullable=True,
                ),
                "status": DatabaseColumn(
                    name="status",
                    column_type="ticketstatus",  # Enum type
                    nullable=False,
                ),
                "priority": DatabaseColumn(
                    name="priority",
                    column_type="priority",  # Enum type
                    nullable=False,
                ),
                "category": DatabaseColumn(
                    name="category",
                    column_type="ticketcategory",  # Enum type
                    nullable=False,
                ),
                "sentiment_score": DatabaseColumn(
                    name="sentiment_score",
                    column_type="DOUBLE PRECISION",
                    nullable=True,
                ),
                "summary": DatabaseColumn(
                    name="summary",
                    column_type="TEXT",
                    nullable=False,
                ),
                "attributes": DatabaseColumn(
                    name="attributes",
                    column_type="JSON",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
            foreign_keys=[
                ForeignKeyConfig(
                    column="person_id",
                    ref_schema="public",
                    ref_table="persons",
                    ref_column="id",
                ),
                ForeignKeyConfig(
                    column="lead_id",
                    ref_schema="public",
                    ref_table="leads",
                    ref_column="id",
                ),
                ForeignKeyConfig(
                    column="product_id",
                    ref_schema="public",
                    ref_table="products",
                    ref_column="id",
                ),
            ],
            indexes=[
                IndexConfig(name="ix_support_tickets_lead_id", columns=["lead_id"]),
                IndexConfig(name="ix_support_tickets_person_id", columns=["person_id"]),
                IndexConfig(name="ix_support_tickets_product_id", columns=["product_id"]),
            ],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


class OrdersTableNeon(DatabaseTable):
    """Orders table with relationships to persons and leads."""

    table_metadata: ClassVar[TableMetadata] = TableMetadata(
        default_graph_node_type="OrderNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["status", "total"],
        ),
        columns={
            "id": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_entity_id=True,
            ),
            "person_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "lead_id": ColumnMetadata(
                # Graph edge auto-generated from FK
                search=SearchConfig(embeddable=False),
            ),
            "status": ColumnMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "currency": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
            "subtotal": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
            "tax": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
            "total": ColumnMetadata(
                search=SearchConfig(embeddable=False),
            ),
            "created_at": ColumnMetadata(
                search=SearchConfig(embeddable=False),
                is_created_at=True,
            ),
        },
    )

    def __init__(self):
        super().__init__(
            table_name="orders",
            schema_name="public",
            description="Customer orders",
            columns={
                "id": DatabaseColumn(
                    name="id",
                    column_type="SERIAL",
                    nullable=False,
                    primary_key=True,
                ),
                "person_id": DatabaseColumn(
                    name="person_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="person_id",
                        ref_schema="public",
                        ref_table="persons",
                        ref_column="id",
                    ),
                ),
                "lead_id": DatabaseColumn(
                    name="lead_id",
                    column_type="INTEGER",
                    nullable=True,
                    foreign_key=ForeignKeyConfig(
                        column="lead_id",
                        ref_schema="public",
                        ref_table="leads",
                        ref_column="id",
                    ),
                ),
                "created_at": DatabaseColumn(
                    name="created_at",
                    column_type="TIMESTAMP",
                    nullable=False,
                ),
                "status": DatabaseColumn(
                    name="status",
                    column_type="orderstatus",  # Enum type
                    nullable=False,
                ),
                "currency": DatabaseColumn(
                    name="currency",
                    column_type="VARCHAR",
                    length=3,
                    nullable=False,
                ),
                "subtotal": DatabaseColumn(
                    name="subtotal",
                    column_type="NUMERIC",
                    precision=10,
                    scale=2,
                    nullable=False,
                ),
                "tax": DatabaseColumn(
                    name="tax",
                    column_type="NUMERIC",
                    precision=10,
                    scale=2,
                    nullable=False,
                ),
                "total": DatabaseColumn(
                    name="total",
                    column_type="NUMERIC",
                    precision=10,
                    scale=2,
                    nullable=False,
                ),
                "attributes": DatabaseColumn(
                    name="attributes",
                    column_type="JSON",
                    nullable=True,
                ),
            },
            primary_keys=["id"],
            foreign_keys=[
                ForeignKeyConfig(
                    column="person_id",
                    ref_schema="public",
                    ref_table="persons",
                    ref_column="id",
                ),
                ForeignKeyConfig(
                    column="lead_id",
                    ref_schema="public",
                    ref_table="leads",
                    ref_column="id",
                ),
            ],
            indexes=[
                IndexConfig(name="ix_orders_lead_id", columns=["lead_id"]),
                IndexConfig(name="ix_orders_person_id", columns=["person_id"]),
            ],
        )
        # Link metadata to columns
        for col_name, col_def in self.columns.items():
            if col_name in self.table_metadata.columns:
                col_def.metadata = self.table_metadata.columns[col_name]


# Schema definitions dictionary: table_key -> DatabaseTable instance
POSTGRES_SCHEMA_DEFINITIONS: dict[str, DatabaseTable] = {
    # Example tables (can be removed if not needed)
    "public.users": UsersTable(),
    # Neon database tables
    "public.leads": LeadsTable(),
    "public.products": ProductsTable(),
    "public.persons": PersonsTable(),
    "public.support_tickets": SupportTicketsTable(),
    "public.orders": OrdersTableNeon(),
}
