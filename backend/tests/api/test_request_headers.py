"""Tests for ContextD request header extraction."""

from __future__ import annotations

import os

from starlette.requests import Request

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.deps import _extract_headers_from_request  # noqa: E402


def make_request(headers: list[tuple[bytes, bytes]]) -> Request:
    """Build a Starlette request with a stable request id."""
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )
    request.state.request_id = "req_test"
    return request


def test_contextd_session_header_is_preferred() -> None:
    """The ContextD session header is the canonical tracking header."""
    request = make_request([(b"x-contextd-session-id", b"contextd-session")])

    headers = _extract_headers_from_request(request)

    assert headers.session_id == "contextd-session"
    assert headers.request_id == "req_test"


def test_missing_contextd_session_header_has_no_fallback() -> None:
    """Only the ContextD session header is accepted for tracking."""
    request = make_request([])

    headers = _extract_headers_from_request(request)

    assert headers.session_id is None
