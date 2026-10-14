"""Models for entity relations."""

from sqlalchemy import Column, ForeignKey, String

from contextd.models._base import Base


class EntityRelation(Base):
    """Relation between two entity types."""

    __tablename__ = "entity_relation"

    name = Column(String, nullable=False)
    description = Column(String)
    from_entity_definition_id = Column(ForeignKey("entity_definition.id"), nullable=False)
    to_entity_definition_id = Column(ForeignKey("entity_definition.id"), nullable=False)
    organization_id = Column(ForeignKey("organization.id"), nullable=True)
