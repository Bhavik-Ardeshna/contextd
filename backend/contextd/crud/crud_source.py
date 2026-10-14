"""CRUD operations for the Source model."""

from contextd.crud._base_public import CRUDPublic
from contextd.models.source import Source
from contextd.schemas.source import SourceCreate, SourceUpdate


class CRUDSource(CRUDPublic[Source, SourceCreate, SourceUpdate]):
    """CRUD operations for the Source model."""

    pass


source = CRUDSource(Source)
