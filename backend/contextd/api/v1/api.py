"""API routes for the FastAPI application."""

from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints import (
    admin,
    api_keys,
    auth_providers,
    billing,
    cohorts,
    collections,
    connections,
    context_forge,
    context_intelligence,
    cursor_dev,
    destinations,
    embedding_models,
    entities,
    entity_counts,
    file_retrieval,
    graph,
    graph_chat,
    graph_events,
    health,
    organizations,
    s3,
    search,
    source_connections,
    source_setup_drafts,
    source_rate_limits,
    sources,
    sync,
    transformers,
    usage,
    users,
)
from contextd.core.config import settings

# Use our custom router that handles trailing slashes
api_router = TrailingSlashRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(usage.router, prefix="/usage", tags=["usage"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(destinations.router, prefix="/destinations", tags=["destinations"])
api_router.include_router(
    embedding_models.router, prefix="/embedding_models", tags=["embedding_models"]
)
api_router.include_router(auth_providers.router, prefix="/auth-providers", tags=["auth-providers"])
api_router.include_router(collections.router, prefix="/collections", tags=["collections"])
api_router.include_router(context_forge.router, prefix="/context-forge", tags=["context-forge"])
api_router.include_router(
    context_intelligence.router, prefix="/context-intelligence", tags=["context-intelligence"]
)
api_router.include_router(search.router, prefix="/collections", tags=["collections"])
api_router.include_router(graph_chat.router, prefix="/collections", tags=["graph-chat"])
api_router.include_router(cohorts.router, prefix="/collections", tags=["cohorts"])
api_router.include_router(connections.router, prefix="/connections", tags=["connections"])
api_router.include_router(
    source_connections.router, prefix="/source-connections", tags=["source-connections"]
)
api_router.include_router(
    source_setup_drafts.router, prefix="/source-setup-drafts", tags=["source-setup-drafts"]
)
api_router.include_router(
    source_rate_limits.router, prefix="/source-rate-limits", tags=["source-rate-limits"]
)
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(graph_events.router, prefix="/graph-events", tags=["graph-events"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(entities.router, prefix="/entities", tags=["entities"])
api_router.include_router(entity_counts.router, prefix="/entity-counts", tags=["entity-counts"])
api_router.include_router(transformers.router, prefix="/transformers", tags=["transformers"])
api_router.include_router(file_retrieval.router, prefix="/files", tags=["files"])
api_router.include_router(s3.router, prefix="/s3", tags=["s3"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])

# Only include cursor development endpoints if LOCAL_CURSOR_DEVELOPMENT is enabled
if settings.LOCAL_CURSOR_DEVELOPMENT:
    api_router.include_router(cursor_dev.router, prefix="/cursor-dev", tags=["Cursor Development"])

# Include dev auth endpoints when DEV_AUTH is enabled
if settings.DEV_AUTH:
    from contextd.api.v1.endpoints import dev_auth

    api_router.include_router(dev_auth.router, prefix="/dev-auth", tags=["dev-auth"])
