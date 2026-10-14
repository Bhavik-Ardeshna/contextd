"""Initialize data from environment variables.

Only creates collections and source connections for services
that have valid tokens/API keys configured in environment variables.
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.config import settings
from contextd.core.logging import LoggerConfigurator
from contextd.core.shared_models import AuthMethod
from contextd.core.source_connection_service import source_connection_service
from contextd.db.init_db import init_db
from contextd.db.session import AsyncSessionLocal
from contextd.schemas.source_connection import (
    DirectAuthentication,
    OAuthTokenAuthentication,
    SourceConnectionCreate,
)

logger = LoggerConfigurator.configure_logger(__name__)


async def _ensure_collection(
    db: AsyncSession, ctx: ApiContext, readable_id: str, name: str
) -> bool:
    """Ensure a collection exists, creating it if necessary. Returns True on success."""
    from contextd.core.collection_service import collection_service
    from contextd.core.exceptions import NotFoundException

    try:
        await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        logger.debug(f"Collection '{name}' already exists.")
        return True
    except NotFoundException:
        logger.info(f"Creating collection: {name}")
        try:
            await collection_service.create(
                db,
                collection_in=schemas.CollectionCreate(name=name, readable_id=readable_id),
                ctx=ctx,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create collection '{name}': {e}")
            return False
    except Exception as e:
        logger.error(f"Error checking collection '{name}': {e}")
        return False


async def init_source_connections(db: AsyncSession) -> None:  # noqa: C901
    """Initialize source connections from environment variables.

    Only services with a valid token/API key in the environment will have
    their collection and source connection created.
    """
    # 1. Get the default superuser to identify the organization
    user = await crud.user.get_by_email(db, email=settings.FIRST_SUPERUSER)
    if not user:
        logger.warning(
            f"Superuser {settings.FIRST_SUPERUSER} not found. Skipping source initialization."
        )
        return

    if not user.user_organizations:
        logger.warning("Superuser has no organizations. Skipping source initialization.")
        return

    # Use the first organization
    organization_id = user.user_organizations[0].organization_id
    logger.info(f"Using organization {organization_id} for initial data.")

    # Fetch organization to construct context
    organization = await crud.organization.get(
        db, id=organization_id, skip_access_validation=True
    )
    if not organization:
        logger.error(f"Organization {organization_id} not found.")
        return

    # Construct ApiContext
    org_schema = schemas.Organization.model_validate(organization)
    user_schema = schemas.User.model_validate(user)

    request_id = str(uuid.uuid4())
    context_logger = LoggerConfigurator.configure_logger(
        __name__,
        dimensions={
            "request_id": request_id,
            "organization_id": str(organization.id),
            "auth_method": AuthMethod.SYSTEM.value,
        },
    )

    ctx = ApiContext(
        request_id=request_id,
        organization=org_schema,
        user=user_schema,
        auth_method=AuthMethod.SYSTEM,
        auth_metadata={"source": "initial_data_script"},
        logger=context_logger,
    )

    # Define sources to configure
    # Format: (token, short_name, collection_readable_id, collection_display_name,
    #          auth_type, token_key, config)
    sources_to_configure = [
        (
            settings.GITHUB_ACCESS_TOKEN,
            "github",
            str(uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")),
            "GitHub",
            "direct",
            "personal_access_token",
            {"repo_name": settings.GITHUB_REPOSITORY_NAME}
            if settings.GITHUB_REPOSITORY_NAME
            else {},
        ),
        (
            settings.SLACK_ACCESS_TOKEN,
            "slack",
            str(uuid.UUID("b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22")),
            "Slack",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.NOTION_ACCESS_TOKEN,
            "notion",
            str(uuid.UUID("c2eebc99-9c0b-4ef8-bb6d-6bb9bd380a33")),
            "Notion",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.LINEAR_API_KEY,
            "linear",
            str(uuid.UUID("d3eebc99-9c0b-4ef8-bb6d-6bb9bd380a44")),
            "Linear",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.ASANA_ACCESS_TOKEN,
            "asana",
            str(uuid.UUID("e4eebc99-9c0b-4ef8-bb6d-6bb9bd380a55")),
            "Asana",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.GOOGLE_ACCESS_TOKEN,
            "google_drive",
            str(uuid.UUID("f5eebc99-9c0b-4ef8-bb6d-6bb9bd380a66")),
            "Google Drive",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.GMAIL_ACCESS_TOKEN,
            "gmail",
            str(uuid.UUID("a1ffbc99-9c0b-4ef8-bb6d-6bb9bd380a77")),
            "Gmail",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.GOOGLE_CALENDAR_ACCESS_TOKEN,
            "google_calendar",
            str(uuid.UUID("b2ffbc99-9c0b-4ef8-bb6d-6bb9bd380a88")),
            "Google Calendar",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.GOOGLE_DOCS_ACCESS_TOKEN,
            "google_docs",
            str(uuid.UUID("c3ffbc99-9c0b-4ef8-bb6d-6bb9bd380a99")),
            "Google Docs",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.OUTLOOK_CALENDAR_ACCESS_TOKEN,
            "outlook_calendar",
            str(uuid.UUID("d4ffbc99-9c0b-4ef8-bb6d-6bb9bd380aaa")),
            "Outlook Calendar",
            "oauth",
            "access_token",
            {},
        ),
        (
            settings.POSTGRES_SOURCE_HOST,  # use host as the "token" gate
            "postgresql",
            str(uuid.UUID("e5ffbc99-9c0b-4ef8-bb6d-6bb9bd380abb")),
            "PostgreSQL",
            "postgres_direct",
            "unused",
            {},
        ),
        (
            settings.CLICKHOUSE_SOURCE_HOST,  # use host as the "token" gate
            "clickhouse",
            str(uuid.UUID("e6ffbc99-9c0b-4ef8-bb6d-6bb9bd380acc")),
            "ClickHouse",
            "clickhouse_direct",
            "unused",
            {},
        ),
    ]

    for (
        token,
        short_name,
        collection_id,
        collection_name,
        auth_type,
        token_key,
        config,
    ) in sources_to_configure:
        # Skip services without a configured token
        if not token:
            logger.info(f"Skipping {short_name} — no token configured.")
            continue

        # 1. Ensure the collection exists before creating the source connection
        collection_ok = await _ensure_collection(
            db, ctx, readable_id=collection_id, name=collection_name
        )
        if not collection_ok:
            logger.error(
                f"Skipping {short_name} — could not ensure collection '{collection_name}'."
            )
            continue

        # 2. Create or recreate the source connection
        connection_name = f"{short_name.title()} Env Connection"
        logger.info(f"Configuring {short_name} from environment variable...")

        try:
            # Check if connection already exists
            existing_conn = await crud.source_connection.get_by_query_and_org(
                db, ctx=ctx, name=connection_name
            )

            # Build auth object
            if auth_type == "direct":
                auth_obj = DirectAuthentication(credentials={token_key: token})
            elif auth_type == "postgres_direct":
                auth_obj = DirectAuthentication(credentials={
                    "host": settings.POSTGRES_SOURCE_HOST,
                    "port": str(settings.POSTGRES_SOURCE_PORT),
                    "database": settings.POSTGRES_SOURCE_DB or "",
                    "user": settings.POSTGRES_SOURCE_USER or "",
                    "password": settings.POSTGRES_SOURCE_PASSWORD or "",
                    "db_schema": settings.POSTGRES_SOURCE_SCHEMA,
                    "tables": settings.POSTGRES_SOURCE_TABLES,
                })
            elif auth_type == "clickhouse_direct":
                auth_obj = DirectAuthentication(credentials={
                    "host": settings.CLICKHOUSE_SOURCE_HOST,
                    "user": settings.CLICKHOUSE_SOURCE_USER or "default",
                    "password": settings.CLICKHOUSE_SOURCE_PASSWORD or "",
                    "secure": getattr(
                        settings, "CLICKHOUSE_SOURCE_SECURE", True
                    ),
                    "database": settings.CLICKHOUSE_SOURCE_DB or "default",
                    "tables": settings.CLICKHOUSE_SOURCE_TABLES,
                })
            else:
                auth_obj = OAuthTokenAuthentication(access_token=token)

            if existing_conn:
                logger.info(f"Removing existing '{connection_name}' to refresh token/config...")
                await source_connection_service.delete(db, id=existing_conn.id, ctx=ctx)

            logger.info(f"Creating source connection: {connection_name}")
            await source_connection_service.create(
                db,
                obj_in=SourceConnectionCreate(
                    name=connection_name,
                    short_name=short_name,
                    readable_collection_id=collection_id,
                    authentication=auth_obj,
                    sync_immediately=True,
                    config=config,
                ),
                ctx=ctx,
            )

        except Exception as e:
            logger.error(f"Failed to configure {short_name}: {e}")


async def main() -> None:
    """Create initial data (first user/org, then collections and source connections) from env."""
    logger.info("Creating initial data")
    async with AsyncSessionLocal() as session:
        # Ensure first superuser and organization exist (creates if missing)
        await init_db(session)
        await init_source_connections(session)



if __name__ == "__main__":
    asyncio.run(main())
