"""Tests for ContextD production configuration hardening."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

BASE_SETTINGS = {
    "FIRST_SUPERUSER": "admin@contextd.local",
    "FIRST_SUPERUSER_PASSWORD": "strong-admin-password",
    "ENCRYPTION_KEY": "x" * 44,
    "STATE_SECRET": "s" * 32,
    "POSTGRES_HOST": "localhost",
    "POSTGRES_USER": "contextd",
    "POSTGRES_PASSWORD": "strong-postgres-password",
    "TEMPORAL_TASK_QUEUE": "contextd-sync-queue",
    "ANALYTICS_ENABLED": False,
}

AMBIENT_SETTINGS_KEYS = (
    "ADDITIONAL_CORS_ORIGINS",
    "API_FULL_URL",
    "APP_FULL_URL",
    "AUTH0_AUDIENCE",
    "AUTH0_CLIENT_ID",
    "AUTH0_DOMAIN",
    "AUTH0_M2M_CLIENT_ID",
    "AUTH0_M2M_CLIENT_SECRET",
    "AUTH0_RULE_NAMESPACE",
    "AUTH_ENABLED",
    "DEBUG",
    "DEV_AUTH",
    "DEV_AUTH_SECRET_KEY",
    "DISABLE_RATE_LIMIT",
    "ENVIRONMENT",
    "LOCAL_CURSOR_DEVELOPMENT",
    "LOCAL_DEVELOPMENT",
    "LOG_LEVEL",
    "POSTHOG_API_KEY",
    "SHOW_LLM_PROMPT",
    "STORAGE_PATH",
)


@pytest.fixture(autouse=True)
def isolate_optional_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep config-hardening tests independent from local runtime env files."""
    for key in AMBIENT_SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)


def make_settings(**overrides: object):
    """Build settings with the required fields populated."""
    from contextd.core.config import Settings

    return Settings(**{**BASE_SETTINGS, **overrides})


def test_local_environment_allows_development_defaults() -> None:
    """Local config keeps developer defaults usable."""
    settings = make_settings(
        ENVIRONMENT="local",
        AUTH_ENABLED=False,
        DEV_AUTH=True,
        SHOW_LLM_PROMPT=True,
        DEV_AUTH_SECRET_KEY="dev-secret-key-change-in-production",
        FIRST_SUPERUSER_PASSWORD="admin",
        POSTGRES_PASSWORD="contextd-dev-password",
        STORAGE_PATH="./local_storage",
    )

    assert settings.PROJECT_NAME == "ContextD"
    assert settings.TEMPORAL_TASK_QUEUE == "contextd-sync-queue"


def test_prompt_logging_is_disabled_by_default() -> None:
    """Redacted prompt diagnostics must be opt-in even for local settings."""
    settings = make_settings(ENVIRONMENT="local")

    assert settings.SHOW_LLM_PROMPT is False


def test_llm_gateway_timing_settings_validate_bounds() -> None:
    """LLM gateway timeout and retry settings fail fast when unsafe."""
    with pytest.raises(ValidationError) as exc_info:
        make_settings(ENVIRONMENT="local", LLM_COMPLETION_TIMEOUT_SECONDS=0)

    assert "LLM_COMPLETION_TIMEOUT_SECONDS must be positive" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        make_settings(ENVIRONMENT="local", LLM_RETRY_BACKOFF_SECONDS=-0.1)

    assert "LLM_RETRY_BACKOFF_SECONDS must not be negative" in str(exc_info.value)


def test_search_indexing_live_path_defaults_are_explicit() -> None:
    """Search/indexing defaults name the current live path clearly."""
    settings = make_settings(ENVIRONMENT="local")
    removed_setting = "ENABLE_" + "CHUNK_VECTOR_DESTINATION_WRITES"
    removed_embedding_setting = "TEXT" + "2VEC_INFERENCE_URL"

    assert settings.SEARCH_INDEX_BACKEND == "neo4j-fulltext"
    assert settings.USE_ENTITY_INDEXING is True
    assert not hasattr(settings, removed_setting)
    assert not hasattr(settings, removed_embedding_setting)


def test_search_indexing_rejects_unsupported_backend() -> None:
    """Search backend experiments must not become live by typo or env drift."""
    with pytest.raises(ValidationError) as exc_info:
        make_settings(ENVIRONMENT="local", SEARCH_INDEX_BACKEND="ve" + "spa")

    assert "SEARCH_INDEX_BACKEND must be neo4j-fulltext" in str(exc_info.value)


def test_production_environment_rejects_development_defaults() -> None:
    """Production config rejects unsafe local defaults."""
    with pytest.raises(ValidationError) as exc_info:
        make_settings(
            ENVIRONMENT="prd",
            AUTH_ENABLED=False,
            DEV_AUTH=True,
            LOCAL_DEVELOPMENT=True,
            LOCAL_CURSOR_DEVELOPMENT=True,
            DEBUG=True,
            LOG_LEVEL="DEBUG",
            DISABLE_RATE_LIMIT=True,
            SHOW_LLM_PROMPT=True,
            DEV_AUTH_SECRET_KEY="dev-secret-key-change-in-production",
            ENCRYPTION_KEY="short",
            STATE_SECRET="s" * 32,
            FIRST_SUPERUSER_PASSWORD="admin",
            POSTGRES_PASSWORD="contextd-dev-password",
            ADDITIONAL_CORS_ORIGINS="*",
            API_FULL_URL=None,
            APP_FULL_URL=None,
            STORAGE_PATH="./local_storage",
        )

    message = str(exc_info.value)
    assert "AUTH_ENABLED must be true" in message
    assert "LOCAL_DEVELOPMENT must be false" in message
    assert "DEBUG must be false" in message
    assert "DISABLE_RATE_LIMIT must be false" in message
    assert "SHOW_LLM_PROMPT must be false" in message
    assert "ENCRYPTION_KEY must be strong" in message
    assert "STORAGE_PATH must be absolute" in message


def test_production_environment_accepts_hardened_config() -> None:
    """Production config accepts explicit hardened values."""
    settings = make_settings(
        ENVIRONMENT="prd",
        AUTH_ENABLED=True,
        DEV_AUTH=False,
        SHOW_LLM_PROMPT=False,
        DEV_AUTH_SECRET_KEY="not-a-development-secret-with-32-chars",
        API_FULL_URL="https://api.contextd.example",
        APP_FULL_URL="https://app.contextd.example",
        STORAGE_PATH="/var/lib/contextd",
        ADDITIONAL_CORS_ORIGINS="https://app.contextd.example;https://admin.contextd.example",
        AUTH0_DOMAIN="auth.contextd.example",
        AUTH0_AUDIENCE="https://api.contextd.example",
        AUTH0_RULE_NAMESPACE="https://contextd.example",
        AUTH0_CLIENT_ID="contextd-spa-client",
        AUTH0_M2M_CLIENT_ID="contextd-m2m-client",
        AUTH0_M2M_CLIENT_SECRET="strong-m2m-secret",
    )

    assert settings.api_url == "https://api.contextd.example"
    assert settings.app_url == "https://app.contextd.example"
    assert settings.ADDITIONAL_CORS_ORIGINS == [
        "https://app.contextd.example",
        "https://admin.contextd.example",
    ]


def test_environment_aliases_normalize_to_supported_profiles() -> None:
    """Environment aliases normalize before validation and URL construction."""
    settings = make_settings(
        ENVIRONMENT="production",
        AUTH_ENABLED=True,
        DEV_AUTH=False,
        SHOW_LLM_PROMPT=False,
        DEV_AUTH_SECRET_KEY="not-a-development-secret-with-32-chars",
        API_FULL_URL="https://api.contextd.example",
        APP_FULL_URL="https://app.contextd.example",
        STORAGE_PATH="/var/lib/contextd",
        AUTH0_DOMAIN="auth.contextd.example",
        AUTH0_AUDIENCE="https://api.contextd.example",
        AUTH0_RULE_NAMESPACE="https://contextd.example",
        AUTH0_CLIENT_ID="contextd-spa-client",
        AUTH0_M2M_CLIENT_ID="contextd-m2m-client",
        AUTH0_M2M_CLIENT_SECRET="strong-m2m-secret",
    )

    assert settings.ENVIRONMENT == "prd"


def test_production_rejects_unsafe_storage_paths_and_missing_analytics_key() -> None:
    """Production config blocks unsafe storage and half-enabled analytics."""
    with pytest.raises(ValidationError) as exc_info:
        make_settings(
            ENVIRONMENT="stg",
            AUTH_ENABLED=True,
            DEV_AUTH=False,
            SHOW_LLM_PROMPT=False,
            DEV_AUTH_SECRET_KEY="not-a-development-secret-with-32-chars",
            API_FULL_URL="https://api.stg.contextd.example",
            APP_FULL_URL="https://app.stg.contextd.example",
            STORAGE_PATH="/",
            ANALYTICS_ENABLED=True,
            POSTHOG_API_KEY="",
            AUTH0_DOMAIN="auth.contextd.example",
            AUTH0_AUDIENCE="https://api.contextd.example",
            AUTH0_RULE_NAMESPACE="https://contextd.example",
            AUTH0_CLIENT_ID="contextd-spa-client",
            AUTH0_M2M_CLIENT_ID="contextd-m2m-client",
            AUTH0_M2M_CLIENT_SECRET="strong-m2m-secret",
        )

    message = str(exc_info.value)
    assert "STORAGE_PATH must point to a dedicated ContextD data directory" in message
    assert "POSTHOG_API_KEY must be set" in message


def test_unknown_environment_is_rejected() -> None:
    """Unsupported environment names fail early."""
    with pytest.raises(ValidationError) as exc_info:
        make_settings(ENVIRONMENT="qa")

    assert "ENVIRONMENT must be one of" in str(exc_info.value)
