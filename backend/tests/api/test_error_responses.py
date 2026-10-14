"""Tests for the ContextD API error envelope."""

from __future__ import annotations

import json
import os

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.errors import (  # noqa: E402
    error_response,
    http_exception_handler,
)
from contextd.api.middleware import exception_logging_middleware  # noqa: E402
from contextd.core.config import settings  # noqa: E402


def make_request() -> Request:
    """Build a Starlette request with a stable request id."""
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/collections/missing",
            "headers": [],
        }
    )
    request.state.request_id = "req_error_test"
    return request


def response_json(response) -> dict:
    """Decode a JSONResponse body."""
    return json.loads(response.body.decode("utf-8"))


def test_error_response_has_canonical_envelope_and_legacy_detail() -> None:
    """API errors expose a typed envelope without breaking old detail readers."""
    response = error_response(
        make_request(),
        status_code=404,
        code="not_found",
        message="Collection not found",
    )

    payload = response_json(response)

    assert payload["error"] == {
        "code": "not_found",
        "message": "Collection not found",
        "request_id": "req_error_test",
    }
    assert payload["detail"] == "Collection not found"


@pytest.mark.asyncio
async def test_http_exception_handler_preserves_structured_detail() -> None:
    """HTTPException detail remains available while the envelope is canonical."""
    response = await http_exception_handler(
        make_request(),
        StarletteHTTPException(
            status_code=409,
            detail={
                "error": "auth0_id_conflict",
                "message": "Account already exists",
                "existing_auth0_id": "existing",
            },
        ),
    )

    payload = response_json(response)

    assert payload["error"]["code"] == "auth0_id_conflict"
    assert payload["error"]["message"] == "Account already exists"
    assert payload["error"]["request_id"] == "req_error_test"
    assert payload["error"]["details"]["existing_auth0_id"] == "existing"
    assert payload["detail"]["error"] == "auth0_id_conflict"


@pytest.mark.asyncio
async def test_unhandled_exception_response_does_not_leak_exception_text(monkeypatch) -> None:
    """Unexpected production errors are logged but returned as a generic envelope."""
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "LOCAL_CURSOR_DEVELOPMENT", False)

    async def raise_secret_error(request: Request):
        raise RuntimeError("secret token from provider")

    response = await exception_logging_middleware(make_request(), raise_secret_error)
    payload = response_json(response)

    assert response.status_code == 500
    assert payload["error"]["code"] == "internal_server_error"
    assert payload["error"]["message"] == "Internal server error"
    assert "secret token from provider" not in json.dumps(payload)
