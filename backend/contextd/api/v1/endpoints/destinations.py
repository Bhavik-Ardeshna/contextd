"""The API module that contains the endpoints for destinations."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.platform.configs._base import Fields
from contextd.platform.locator import resource_locator

router = TrailingSlashRouter()


@router.get("/list", response_model=list[schemas.Destination])
async def list_destinations(
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> list[schemas.Destination]:
    """Get all available destinations.

    Args:
    -----
        db: The database session
        ctx: The current authentication context

    Returns:
    --------
        List[schemas.Destination]: A list of destinations
    """
    destinations = await crud.destination.get_all(db)
    return destinations


@router.get("/detail/{short_name}", response_model=schemas.DestinationWithAuthenticationFields)
async def read_destination(
    *,
    db: AsyncSession = Depends(deps.get_db),
    short_name: str,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Destination:
    """Get destination by short name.

    Args:
    -----
        db: The database session
        short_name: The short name of the destination
        ctx: The current authentication context

    Returns:
    --------
        destination (schemas.Destination): The destination
    """
    destination = await crud.destination.get_by_short_name(db, short_name)
    if destination.auth_config_class:
        auth_config_class = resource_locator.get_auth_config(destination.auth_config_class)
        fields = Fields.from_config_class(auth_config_class)
        destination_with_auth_fields = schemas.DestinationWithAuthenticationFields.model_validate(
            destination, from_attributes=True
        )
        destination_with_auth_fields.auth_fields = fields
        return destination_with_auth_fields
    return destination
