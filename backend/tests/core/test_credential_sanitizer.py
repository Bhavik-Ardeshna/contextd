"""Tests for credential log redaction helpers."""

from contextd.core.credential_sanitizer import (
    safe_log_token_info,
    sanitize_credential_value,
    sanitize_credentials_dict,
)


def test_sanitize_credential_value_does_not_preview_secret() -> None:
    """Redaction must not leak prefix or suffix characters."""
    secret = "provider-secret-value-for-redaction"

    redacted = sanitize_credential_value(secret)
    redacted_without_length = sanitize_credential_value(secret, show_length=False)

    assert redacted == f"<redacted:{len(secret)} chars>"
    assert redacted_without_length == "<redacted>"
    assert "provider" not in redacted
    assert "ken" not in redacted
    assert "provider" not in redacted_without_length


def test_sanitize_credentials_dict_does_not_preview_values() -> None:
    """Dictionary sanitizer must redact values without previews."""
    redacted = sanitize_credentials_dict(
        {"access_token": "tok-secret-value", "client_secret": "client-secret-value"},
        show_lengths=False,
    )

    assert redacted == {"access_token": "<redacted>", "client_secret": "<redacted>"}


def test_safe_log_token_info_does_not_preview_token() -> None:
    """Token log helper may report length but never token characters."""
    messages: list[str] = []
    token = "tok-secret-value"

    safe_log_token_info(token, messages.append, "Token")

    assert messages == [f"Token Length: {len(token)}"]
    assert "tok" not in messages[0]
    assert "value" not in messages[0]
