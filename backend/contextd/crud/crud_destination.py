"""CRUD operations for destinations."""

from contextd.crud._base_public import CRUDPublic
from contextd.models.destination import Destination
from contextd.schemas.destination import DestinationCreate, DestinationUpdate


class CRUDDestination(CRUDPublic[Destination, DestinationCreate, DestinationUpdate]):
    """CRUD operations for destinations."""

    pass


destination = CRUDDestination(Destination)
