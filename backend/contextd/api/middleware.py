"""Middleware for the FastAPI application.

This module contains middleware that process requests and responses.
"""

import asyncio
import time
import traceback
import uuid
from typing import List

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from contextd.api.context import ApiContext
from contextd.api.errors import error_response
from contextd.core.config import settings
from contextd.core.logging import logger


async def add_request_id(request: Request, call_next: callable) -> Response:
    """Middleware to generate and add a request ID to the request for tracing.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response to the incoming request.

    """
    request.state.request_id = str(uuid.uuid4())
    return await call_next(request)


async def log_requests(request: Request, call_next: callable) -> Response:
    """Middleware to log incoming requests.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response to the incoming request.

    """
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Handled request {request.method} {request.url} in {duration:.2f} seconds. "
        f"Response code: {response.status_code}"
    )
    return response


async def exception_logging_middleware(request: Request, call_next: callable) -> Response:
    """Middleware to log unhandled exceptions.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response to the incoming request.

    """
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.error(
            "Unhandled exception while handling %s %s",
            request.method,
            request.url.path,
            exc_info=True,
        )
        details = None
        if settings.LOCAL_CURSOR_DEVELOPMENT or settings.DEBUG:
            details = {
                "exception_type": exc.__class__.__name__,
                "trace": traceback.format_exc(),
            }

        return error_response(
            request,
            status_code=500,
            code="internal_server_error",
            message="Internal server error",
            details=details,
        )


async def request_timeout_middleware(request: Request, call_next: callable) -> Response:
    """Middleware to enforce request timeout.

    Wraps request processing in asyncio.wait_for() to prevent long-running requests
    from tying up resources.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response to the incoming request or 504 on timeout.

    """
    try:
        response = await asyncio.wait_for(
            call_next(request), timeout=settings.API_REQUEST_TIMEOUT_SECONDS
        )
        return response
    except asyncio.TimeoutError:
        logger.warning(
            f"Request timeout after {settings.API_REQUEST_TIMEOUT_SECONDS}s: "
            f"{request.method} {request.url}"
        )
        return error_response(
            request,
            status_code=504,
            code="request_timeout",
            message=f"Request timeout after {settings.API_REQUEST_TIMEOUT_SECONDS} seconds",
        )


async def request_body_size_middleware(request: Request, call_next: callable) -> Response:
    """Middleware to enforce request body size limit.

    Checks the Content-Length header and rejects requests exceeding the configured limit.
    This prevents large payloads from consuming excessive server resources.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response to the incoming request or 413 if body is too large.

    """
    # Check Content-Length header if present
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            content_length_bytes = int(content_length)
            if content_length_bytes > settings.API_REQUEST_BODY_SIZE_LIMIT:
                max_size_mb = settings.API_REQUEST_BODY_SIZE_LIMIT / (1024 * 1024)
                actual_size_mb = content_length_bytes / (1024 * 1024)
                logger.warning(
                    f"Request body too large: {actual_size_mb:.2f}MB exceeds limit "
                    f"of {max_size_mb:.2f}MB for {request.method} {request.url}"
                )
                message = (
                    f"Request body too large. Maximum size is {max_size_mb:.2f}MB, "
                    f"but request is {actual_size_mb:.2f}MB"
                )
                return error_response(
                    request,
                    status_code=413,
                    code="request_body_too_large",
                    message=message,
                    details={
                        "max_size_mb": round(max_size_mb, 2),
                        "actual_size_mb": round(actual_size_mb, 2),
                    },
                )
        except ValueError:
            logger.warning(f"Invalid Content-Length header: {content_length}")

    return await call_next(request)


async def rate_limit_headers_middleware(request: Request, call_next: callable) -> Response:
    """Middleware to add rate limit headers to responses.

    Follows standards defined in RFC 6585.

    Args:
    ----
        request (Request): The incoming request.
        call_next (callable): The next middleware in the chain.

    Returns:
    -------
        Response: The response with rate limit headers added.

    """
    response = await call_next(request)

    # Add rate limit headers if available from request state
    rate_limit_result = getattr(request.state, "rate_limit_result", None)
    if rate_limit_result:
        response.headers["RateLimit-Limit"] = str(rate_limit_result.limit)
        response.headers["RateLimit-Remaining"] = str(rate_limit_result.remaining)
        response.headers["RateLimit-Reset"] = str(int(time.time() + rate_limit_result.retry_after))

    return response


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """Middleware to dynamically update CORS origins based on configuration.

    Simple CORS handling that permits OPTIONS preflight requests and adds appropriate headers.
    """

    def __init__(self, app, default_origins: List[str]):
        """Initialize the middleware.

        Args:
            app: The FastAPI application
            default_origins: Default CORS origins to allow
        """
        super().__init__(app)
        self.default_origins = default_origins

    async def dispatch(self, request: Request, call_next):
        """Process the request and add dynamic CORS headers.

        Args:
            request: The incoming request
            call_next: The next middleware function to call

        Returns:
            The response with appropriate CORS headers
        """
        # Get origin from request headers
        origin = request.headers.get("origin")
        path = request.url.path

        # If no origin, no CORS headers needed
        if not origin:
            return await call_next(request)

        # Handle OPTIONS preflight requests - only if allowed
        if request.method == "OPTIONS":
            # Check if origin is allowed (support wildcard "*")
            is_allowed_origin = "*" in self.default_origins or origin in self.default_origins

            if is_allowed_origin:
                # Create a response with appropriate CORS headers
                response = Response()
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = (
                    "GET,POST,PUT,DELETE,OPTIONS,PATCH"
                )
                response.headers["Access-Control-Allow-Headers"] = "*"
                response.headers["Access-Control-Allow-Credentials"] = "true"
                logger.debug(f"Handled OPTIONS preflight for {path} from origin {origin}")
                return response
            else:
                # Not allowed, return 403
                logger.warning(
                    f"Rejected OPTIONS preflight for {path} from disallowed origin {origin}"
                )
                return Response(status_code=403)

        # For non-OPTIONS requests, process the request
        response = await call_next(request)

        # Add CORS headers to the response for allowed origins (support wildcard "*")
        is_allowed_origin = "*" in self.default_origins or origin in self.default_origins

        if is_allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            logger.debug(f"Added CORS headers for origin {origin}")

        return response

async def analytics_middleware(request: Request, call_next):
    """Track API calls automatically via middleware.

    Extracts context from request.state.api_context (set by deps.py) and tracks
    API calls with PostHog analytics including user_id, org_id, and request_id.
    """
    start_time = time.monotonic()

    if _should_skip_analytics(request):
        return await call_next(request)

    response = await call_next(request)

    duration_ms = (time.monotonic() - start_time) * 1000

    context = getattr(request.state, "api_context", None)
    if context:
        try:
            await _track_api_call_async(context, response, duration_ms, request)
        except Exception as e:
            logger.warning(f"Failed to track API analytics: {e}")

    return response


def _build_endpoint_name(request: Request) -> str:
    """Build endpoint name using FastAPI's route information.

    Uses the matched route path template from FastAPI, which already contains
    parameter placeholders like {uuid}, {readable_id}, etc.

    Returns:
        str: endpoint_path_template like "/collections/{readable_id}/search"
    """
    # Get the matched route from FastAPI
    route = request.scope.get("route")

    if route and hasattr(route, "path"):
        # FastAPI provides the path template with {param} placeholders
        # e.g., "/collections/{readable_id}/sources/{source_short_name}"
        return route.path

    # Fallback to raw path if route not available (shouldn't happen in normal operation)
    return request.url.path.rstrip("/")


def _should_skip_analytics(request: Request) -> bool:
    """Skip analytics for certain paths."""
    skip_paths = {
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
        "/redoc",
    }
    return request.url.path in skip_paths


async def _track_api_call_async(
    context: ApiContext, response: Response, duration_ms: float, request: Request
):
    """Track API call asynchronously.

    Uses the contextual analytics service from ApiContext which already has
    user/org/headers configured. This avoids duplication and ensures consistency.
    """
    # Build endpoint identifier from FastAPI route template
    endpoint = _build_endpoint_name(request)

    # Build properties specific to API calls
    # Note: auth_method, organization_name, and headers are automatically added
    # by the contextual analytics service
    properties = {
        "endpoint": endpoint,
        "request_method": request.method,
        "request_path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    }

    # Flatten all path parameters directly into properties
    # Convert all values to strings to ensure JSON serialization works
    if request.path_params:
        properties.update({k: str(v) for k, v in request.path_params.items()})

    # Determine event name
    event_name = "api_call_error" if response.status_code >= 400 else "api_call"

    # Track event using contextual analytics service
    # This automatically adds: auth_method, organization_name, request_id,
    # user_agent, client_name, sdk_name, session_id, and other headers
    context.analytics.track_event(event_name, properties)
