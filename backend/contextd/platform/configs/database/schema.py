"""Database schema definition classes.

Defines database table and column structures with PostgreSQL type support.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ForeignKeyConfig(BaseModel):
    """Foreign key relationship configuration."""

    column: str = Field(..., description="Column name in this table")
    ref_schema: str = Field(..., description="Referenced schema name")
    ref_table: str = Field(..., description="Referenced table name")
    ref_column: str = Field(..., description="Referenced column name")
    on_delete: str = Field(
        default="RESTRICT", description="ON DELETE action (RESTRICT, CASCADE, SET NULL)"
    )
    on_update: str = Field(
        default="RESTRICT", description="ON UPDATE action (RESTRICT, CASCADE, SET NULL)"
    )


class IndexConfig(BaseModel):
    """Database index configuration."""

    name: str = Field(..., description="Index name")
    columns: List[str] = Field(..., description="List of column names")
    unique: bool = Field(default=False, description="Whether index is unique")
    method: Optional[str] = Field(
        default=None, description="Index method (btree, hash, gin, gist, etc.)"
    )


class DatabaseColumn(BaseModel):
    """Database column definition with type, constraints, and metadata reference.

    Similar to ContextDField but for database columns.
    """

    name: str = Field(..., description="Column name")
    column_type: str = Field(
        ..., description="PostgreSQL column type (VARCHAR, INTEGER, TEXT, JSONB, etc.)"
    )
    nullable: bool = Field(default=True, description="Whether column allows NULL")
    default: Optional[Any] = Field(default=None, description="Default value")
    primary_key: bool = Field(default=False, description="Whether column is primary key")
    foreign_key: Optional[ForeignKeyConfig] = Field(
        default=None, description="Foreign key configuration"
    )
    unique: bool = Field(default=False, description="Whether column has unique constraint")
    indexed: bool = Field(default=False, description="Whether column is indexed")

    # Database-specific attributes
    length: Optional[int] = Field(
        default=None, description="Length for VARCHAR(n) or similar types"
    )
    precision: Optional[int] = Field(
        default=None, description="Precision for NUMERIC(p,s)"
    )
    scale: Optional[int] = Field(default=None, description="Scale for NUMERIC(p,s)")

    # Reference to metadata (set after column creation)
    metadata: Optional[Any] = Field(
        default=None, description="ColumnMetadata reference (set externally)"
    )


class DatabaseTable(BaseModel):
    """Database table definition with schema and metadata.

    Similar to BaseEntity but for database tables.
    """

    table_name: str = Field(..., description="Table name")
    schema_name: Optional[str] = Field(
        default="public", description="Schema name (default: public)"
    )
    description: Optional[str] = Field(
        default=None, description="Table description/documentation"
    )

    # Column definitions
    columns: Dict[str, DatabaseColumn] = Field(
        default_factory=dict, description="Column definitions keyed by column name"
    )

    # Table-level metadata (set externally, similar to _entity_metadata ClassVar)
    table_metadata: Optional[Any] = Field(
        default=None, description="TableMetadata reference (set externally)"
    )

    # Constraints
    primary_keys: List[str] = Field(
        default_factory=list, description="List of primary key column names"
    )
    foreign_keys: List[ForeignKeyConfig] = Field(
        default_factory=list, description="List of foreign key configurations"
    )
    unique_constraints: List[List[str]] = Field(
        default_factory=list, description="List of unique constraint column groups"
    )
    indexes: List[IndexConfig] = Field(
        default_factory=list, description="List of index configurations"
    )

    # Table-level settings
    partition_by: Optional[str] = Field(
        default=None, description="Partition key column (for partitioned tables)"
    )
    table_space: Optional[str] = Field(
        default=None, description="Tablespace name"
    )

    def get_table_key(self) -> str:
        """Get unique table key in format 'schema.table'."""
        return f"{self.schema_name}.{self.table_name}"
