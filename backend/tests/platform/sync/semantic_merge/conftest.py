"""Ensure required env vars exist before tests import modules that load ``Settings``."""

from __future__ import annotations

import os


def pytest_configure(config) -> None:  # noqa: ARG001
    defaults = {
        "FIRST_SUPERUSER": "semantic-merge-test@example.com",
        "FIRST_SUPERUSER_PASSWORD": "unused-for-unit-tests",
        "ENCRYPTION_KEY": "0" * 32,
        "STATE_SECRET": "s" * 32,
        "POSTGRES_HOST": "localhost",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
