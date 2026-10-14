"""Main module of the FastAPI application.

This module sets up the FastAPI application and the middleware to log incoming requests
and unhandled exceptions.
"""

import os
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from contextd.api.errors import (
    contextd_exception_handler,
    http_exception_handler,
    invalid_state_exception_handler,
    not_found_exception_handler,
    payment_required_exception_handler,
    permission_exception_handler,
    rate_limit_exception_handler,
    usage_limit_exceeded_exception_handler,
    validation_exception_handler,
)
from contextd.api.middleware import (
    DynamicCORSMiddleware,
    add_request_id,
    analytics_middleware,
    exception_logging_middleware,
    log_requests,
    rate_limit_headers_middleware,
    request_body_size_middleware,
    request_timeout_middleware,
)
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.api import api_router
from contextd.core.config import settings
from contextd.core.exceptions import (
    ContextDException,
    InvalidStateError,
    NotFoundException,
    PaymentRequiredException,
    PermissionException,
    RateLimitExceededException,
    UsageLimitExceededException,
)
from contextd.core.logging import logger
from contextd.db.init_db import init_db
from contextd.db.session import AsyncSessionLocal
from contextd.platform.db_sync import sync_platform_components


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events.

    Runs alembic migrations and syncs platform components.
    """
    async with AsyncSessionLocal() as db:
        if settings.RUN_ALEMBIC_MIGRATIONS:
            logger.info("Running alembic migrations...")
            env = os.environ.copy()
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env["PYTHONPATH"] = backend_dir
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                cwd=backend_dir,
                env=env,
            )
        if settings.RUN_DB_SYNC:
            await sync_platform_components("contextd/platform", db)
        await init_db(db)

    # Log OAuth callback URL for local dev so it can be registered in provider consoles
    if settings.ENVIRONMENT == "local":
        oauth_callback = f"{settings.api_url}/source-connections/callback"
        logger.info(
            "OAuth redirect URI for connectors (add this in each provider's console): %s",
            oauth_callback,
        )

    # Initialize cleanup schedule for stuck sync jobs (if Temporal is enabled)
    if settings.TEMPORAL_ENABLED:
        try:
            from contextd.platform.temporal.schedule_service import temporal_schedule_service

            logger.info("Initializing cleanup schedule for stuck sync jobs...")
            await temporal_schedule_service.create_cleanup_schedule()
            logger.info("Cleanup schedule initialized successfully")
        except Exception as e:
            logger.warning(
                f"Failed to initialize cleanup schedule (Temporal may not be available): {e}"
            )

        # Initialize API key expiration notification schedule
        try:
            logger.info("Initializing API key expiration notification schedule...")
            await temporal_schedule_service.create_api_key_notification_schedule()
            logger.info("API key notification schedule initialized successfully")
        except Exception as e:
            logger.warning(
                f"Failed to initialize API key notification schedule "
                f"(Temporal may not be available): {e}"
            )

    yield


# Create FastAPI app with our custom router and disable FastAPI's built-in redirects
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url="/openapi.json",
    lifespan=lifespan,
    router=TrailingSlashRouter(),
    redirect_slashes=False,  # Critical: disable FastAPI's built-in slash redirects
)

app.include_router(api_router)

# Register middleware directly in the correct order
# Order matters: first registered = outermost middleware (processes request first)
app.middleware("http")(add_request_id)
app.middleware("http")(request_body_size_middleware)
app.middleware("http")(request_timeout_middleware)
app.middleware("http")(rate_limit_headers_middleware)
app.middleware("http")(log_requests)
app.middleware("http")(analytics_middleware)
app.middleware("http")(exception_logging_middleware)

# Register exception handlers
app.exception_handler(StarletteHTTPException)(http_exception_handler)
app.exception_handler(RequestValidationError)(validation_exception_handler)
app.exception_handler(ValidationError)(validation_exception_handler)
app.exception_handler(PermissionException)(permission_exception_handler)
app.exception_handler(NotFoundException)(not_found_exception_handler)
app.exception_handler(PaymentRequiredException)(payment_required_exception_handler)
app.exception_handler(UsageLimitExceededException)(usage_limit_exceeded_exception_handler)
app.exception_handler(RateLimitExceededException)(rate_limit_exception_handler)
app.exception_handler(InvalidStateError)(invalid_state_exception_handler)

# Register custom ContextD exception handlers
app.exception_handler(ContextDException)(contextd_exception_handler)

# Default CORS origins - white labels and environment variables can extend this
CORS_ORIGINS = [
    "http://localhost:5173",
    "localhost:8001",
    "http://localhost:8080",
    "http://localhost:8082",
    "https://app.dev.contextd.local",
    "https://app.stg.contextd.local",
    "https://app.contextd.local",
    "https://docs.contextd.local",
    "localhost:3000",
]

# In local env, allow any origin (e.g. http://192.168.1.165:8082) so frontend and backend can talk over LAN
if settings.ENVIRONMENT == "local":
    CORS_ORIGINS.append("*")

if settings.ADDITIONAL_CORS_ORIGINS:
    CORS_ORIGINS.extend(settings.ADDITIONAL_CORS_ORIGINS)

# Add the dynamic CORS middleware that handles both default origins and white label specific origins
app.add_middleware(
    DynamicCORSMiddleware,
    default_origins=CORS_ORIGINS,
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def show_docs_reference() -> HTMLResponse:
    """Root endpoint to display the API documentation.

    Returns:
    -------
        HTMLResponse: The HTML content to display the API documentation.

    """
    html_content = """
<!DOCTYPE html>
<html>
    <head>
        <title>ContextD API</title>
    </head>
    <body>
        <h1>Welcome to the ContextD API</h1>
        <p>Please visit the <a href="https://docs.contextd.local">docs</a> for more information.</p>
    </body>
</html>
    """
    return HTMLResponse(content=html_content)
