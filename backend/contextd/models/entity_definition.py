"""Models for entity definitions."""

from enum import Enum

from sqlalchemy import JSON, Column, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum

from contextd.models._base import Base


class EntityType(str, Enum):
    """Type of entity."""

    FILE = "file"
    JSON = "json"


class EntityDefinition(Base):
    """An entity type that can be produced or consumed."""

    __tablename__ = "entity_definition"

    name = Column(String, nullable=False)
    description = Column(String)
    type = Column(SQLEnum(EntityType), nullable=False)
    # For files: list of extensions, for JSON: JSON schema
    entity_schema = Column(JSON, nullable=False)
    parent_id = Column(ForeignKey("entity_definition.id"), nullable=True)
    module_name = Column(String, nullable=False)
    class_name = Column(String, nullable=False)
    organization_id = Column(ForeignKey("organization.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("name", "organization_id", name="uq_entity_definition_name_org"),
    )
