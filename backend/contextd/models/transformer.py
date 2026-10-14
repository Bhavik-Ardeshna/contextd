"""Models for transformers."""

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.types import TypeDecorator

from contextd.models._base import Base


class StringListJSON(TypeDecorator):
    """Custom type for JSON array of strings."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Convert list to JSON array."""
        if value is not None:
            return [str(x) for x in value]
        return None


class Transformer(Base):
    """Definition of a transformer that can transform entities."""

    __tablename__ = "transformer"

    name = Column(String, nullable=False)
    description = Column(String)
    method_name = Column(String, nullable=False)
    module_name = Column(String, nullable=False)

    # List of entity definition IDs this transformer can input/output
    input_entity_definition_ids = Column(StringListJSON, nullable=False)
    output_entity_definition_ids = Column(StringListJSON, nullable=False)

    config_schema = Column(JSON, nullable=False)  # JSON Schema for configuration
    organization_id = Column(UUID, ForeignKey("organization.id"), nullable=True)
