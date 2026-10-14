"""API error envelopes and FastAPI exception handlers."""

import time
import traceback
from http import HTTPStatus
from typing import Any, Mapping, Union

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from contextd.core.config import settings
from contextd.core.exceptions import (
    CollectionNotFoundException,
    ContextDException,
    ImmutableFieldError,
    InvalidScheduleOperationException,
    InvalidStateError,
    MinuteLevelScheduleException,
    NotFoundException,
    PaymentRequiredException,
    PermissionException,
    RateLimitExceededException,
    ScheduleNotExistsException,
    ScheduleOperationException,
    SyncJobNotFoundException,
    SyncNotFoundException,
    TokenRefreshError,
    UsageLimitExceededException,
    unpack_validation_error,
)
from contextd.core.logging import logger


def _request_id(request: Request) -> str | None:
    """Return the request id assigned by middleware, if present."""
    return getattr(request.state, "request_id", None)


def _http_status_message(status_code: int) -> str:
    """Return the standard HTTP reason phrase for a status code."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def _detail_message(detail: Any, fallback: str) -> str:
    """Extract a user-safe message from common FastAPI detail payloads."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("message", "detail", "error"):
            value = detail.get(key)
            if isinstance(value, str):
                return value
    return fallback


def _detail_code(detail: Any, fallback: str) -> str:
    """Extract a stable error code from common FastAPI detail payloads."""
    if isinstance(detail, dict):
        for key in ("code", "error"):
            value = detail.get(key)
            if isinstance(value, str):
                return value
    return fallback


def error_payload(
    request: Request,
    *,
    code: str,
    message: str,
    details: Any | None = None,
    legacy_detail: Any | None = None,
) -> dict[str, Any]:
    """Build the canonical API error envelope with a compatibility detail field."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    request_id = _request_id(request)
    if request_id:
        error["request_id"] = request_id
    if details is not None:
        error["details"] = jsonable_encoder(details)

    return {
        "error": error,
        "detail": jsonable_encoder(message if legacy_detail is None else legacy_detail),
    }


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: Mapping[str, str] | None = None,
    legacy_detail: Any | None = None,
) -> JSONResponse:
    """Build a JSON error response using the canonical API error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            request,
            code=code,
            message=message,
            details=details,
            legacy_detail=legacy_detail,
        ),
        headers=dict(headers) if headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: Union[RequestValidationError, ValidationError]
) -> JSONResponse:
    """Exception handler for validation errors that occur during request processing."""
    error_messages = unpack_validation_error(exc)
    logger.error(f"Validation error: {error_messages}")

    if settings.LOCAL_CURSOR_DEVELOPMENT:
        exception_type = exc.__class__.__name__
        exception_str = str(exc)
        class_name = exception_str.split("\n")[0].split(" ")[-1]
        stack_trace = []
        if hasattr(exc, "__traceback__") and exc.__traceback__ is not None:
            stack_frames = traceback.extract_tb(exc.__traceback__)
            for frame in stack_frames:
                if "site-packages" not in frame.filename and "/contextd" in frame.filename:
                    context = f"{frame.filename.split('/')[-1]}:{frame.name}:{frame.lineno}"
                    stack_trace.append(context)

        details = {
            "errors": error_messages["errors"],
            "class_name": class_name,
            "stack_trace": stack_trace,
            "type": exception_type,
        }
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=details,
            legacy_detail=error_messages,
        )

    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=error_messages,
        legacy_detail=error_messages,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Exception handler for FastAPI and Starlette HTTP errors."""
    fallback_code = f"http_{exc.status_code}"
    fallback_message = _http_status_message(exc.status_code)
    message = _detail_message(exc.detail, fallback_message)
    code = _detail_code(exc.detail, fallback_code)
    details = exc.detail if isinstance(exc.detail, (dict, list)) else None

    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details,
        headers=exc.headers,
        legacy_detail=exc.detail,
    )


async def permission_exception_handler(request: Request, exc: PermissionException) -> JSONResponse:
    """Exception handler for PermissionException."""
    return error_response(
        request,
        status_code=403,
        code="permission_denied",
        message=str(exc),
    )


async def not_found_exception_handler(request: Request, exc: NotFoundException) -> JSONResponse:
    """Exception handler for NotFoundException."""
    return error_response(
        request,
        status_code=404,
        code="not_found",
        message=str(exc),
    )


async def contextd_exception_handler(request: Request, exc: ContextDException) -> JSONResponse:
    """Generic exception handler for all ContextD domain exceptions."""
    status_code_map = {
        SyncNotFoundException: 404,
        SyncJobNotFoundException: 404,
        CollectionNotFoundException: 404,
        InvalidScheduleOperationException: 400,
        ScheduleNotExistsException: 400,
        ImmutableFieldError: 400,
        TokenRefreshError: 401,
        PermissionException: 403,
        MinuteLevelScheduleException: 500,
        ScheduleOperationException: 500,
    }

    status_code = 500
    for exc_type, code in status_code_map.items():
        if isinstance(exc, exc_type):
            status_code = code
            break

    return error_response(
        request,
        status_code=status_code,
        code=exc.__class__.__name__,
        message=str(exc),
    )


async def payment_required_exception_handler(
    request: Request, exc: PaymentRequiredException
) -> JSONResponse:
    """Exception handler for PaymentRequiredException."""
    return error_response(
        request,
        status_code=400,
        code="payment_required",
        message=str(exc),
        details={
            "action_type": exc.action_type,
            "payment_status": exc.payment_status,
        },
    )


async def usage_limit_exceeded_exception_handler(
    request: Request, exc: UsageLimitExceededException
) -> JSONResponse:
    """Exception handler for UsageLimitExceededException."""
    return error_response(
        request,
        status_code=400,
        code="usage_limit_exceeded",
        message=str(exc),
        details={
            "action_type": exc.action_type,
            "limit": exc.limit,
            "current_usage": exc.current_usage,
        },
    )


async def invalid_state_exception_handler(request: Request, exc: InvalidStateError) -> JSONResponse:
    """Exception handler for InvalidStateError."""
    return error_response(
        request,
        status_code=400,
        code="invalid_state",
        message=str(exc),
    )


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceededException
) -> JSONResponse:
    """Exception handler for RateLimitExceededException."""
    reset_timestamp = int(time.time() + exc.retry_after)

    return error_response(
        request,
        status_code=429,
        code="rate_limit_exceeded",
        message=str(exc),
        details={
            "retry_after": exc.retry_after,
            "limit": exc.limit,
            "remaining": exc.remaining,
        },
        headers={
            "Retry-After": str(int(exc.retry_after) + 1),
            "RateLimit-Limit": str(exc.limit),
            "RateLimit-Remaining": str(exc.remaining),
            "RateLimit-Reset": str(reset_timestamp),
        },
    )
