"""Credential sanitization utilities for safe logging.

This module provides functions to safely log credential information without
exposing sensitive data like API keys, tokens, passwords, etc.
"""

import re
from typing import Any, Callable, Dict


def sanitize_credential_value(value: Any, show_length: bool = True) -> str:
    """Sanitize a credential value for safe logging.

    Args:
        value: The credential value to sanitize
        show_length: Whether to show the length of the value

    Returns:
        A sanitized string representation of the value
    """
    if isinstance(value, str):
        if len(value) <= 8:
            return f"<redacted:{len(value)} chars>"
        if show_length:
            return f"<redacted:{len(value)} chars>"
        return "<redacted>"
    elif isinstance(value, (int, float)):
        return f"<redacted {type(value).__name__}>"
    elif isinstance(value, bool):
        return f"<redacted bool:{value}>"
    elif value is None:
        return "<redacted:null>"
    else:
        return f"<redacted {type(value).__name__}>"


def sanitize_credentials_dict(
    credentials: Dict[str, Any], show_lengths: bool = True
) -> Dict[str, str]:
    """Sanitize a dictionary of credentials for safe logging.

    Args:
        credentials: Dictionary containing credential data
        show_lengths: Whether to show lengths of string values

    Returns:
        Dictionary with sanitized values
    """
    sanitized = {}
    for key, value in credentials.items():
        sanitized[key] = sanitize_credential_value(value, show_lengths)
    return sanitized


def get_safe_credential_summary(credentials: Dict[str, Any]) -> str:
    """Get a safe summary of credentials without exposing sensitive data.

    Args:
        credentials: Dictionary containing credential data

    Returns:
        A safe string summary of the credentials
    """
    if not credentials:
        return "No credentials found"

    # Count sensitive vs non-sensitive fields
    sensitive_fields = []
    non_sensitive_fields = []

    for key in credentials.keys():
        if _is_sensitive_field(key):
            sensitive_fields.append(key)
        else:
            non_sensitive_fields.append(key)

    summary_parts = [
        f"Total fields: {len(credentials)}",
        f"Sensitive fields: {len(sensitive_fields)}",
        f"Non-sensitive fields: {len(non_sensitive_fields)}",
    ]

    if non_sensitive_fields:
        summary_parts.append(f"Non-sensitive: {non_sensitive_fields}")

    if sensitive_fields:
        summary_parts.append(f"Sensitive: {sensitive_fields}")

    return " | ".join(summary_parts)


def _is_sensitive_field(field_name: str) -> bool:
    """Check if a field name indicates sensitive data.

    Args:
        field_name: The name of the field to check

    Returns:
        True if the field likely contains sensitive data
    """
    sensitive_patterns = [
        r"token",
        r"key",
        r"secret",
        r"password",
        r"credential",
        r"auth",
        r"access",
        r"refresh",
        r"bearer",
        r"api_key",
        r"client_secret",
        r"private",
        r"session",
        r"cookie",
    ]

    field_lower = field_name.lower()
    return any(re.search(pattern, field_lower) for pattern in sensitive_patterns)


def safe_log_credentials(
    credentials: Dict[str, Any],
    logger_func: Callable[[str], None],
    message_prefix: str = "",
) -> None:
    """Safely log credentials using the provided logger function.

    Args:
        credentials: Dictionary containing credential data
        logger_func: Logger function to use (e.g., logger.info, logger.debug)
        message_prefix: Optional prefix for the log message
    """
    summary = get_safe_credential_summary(credentials)
    if message_prefix:
        logger_func(f"{message_prefix} {summary}")
    else:
        logger_func(summary)


def safe_log_credential_fields(
    credentials: Dict[str, Any],
    logger_func: Callable[[str], None],
    message_prefix: str = "",
) -> None:
    """Safely log credential field names and types without values.

    Args:
        credentials: Dictionary containing credential data
        logger_func: Logger function to use
        message_prefix: Optional prefix for the log message
    """
    if not credentials:
        logger_func(f"{message_prefix} No credential fields")
        return

    field_info = []
    for key, value in credentials.items():
        field_type = type(value).__name__
        if isinstance(value, str):
            field_info.append(f"{key}({field_type}:{len(value)} chars)")
        else:
            field_info.append(f"{key}({field_type})")

    fields_str = ", ".join(field_info)
    if message_prefix:
        logger_func(f"{message_prefix} Fields: {fields_str}")
    else:
        logger_func(f"Credential fields: {fields_str}")


def safe_log_token_info(
    token: str, logger_func: Callable[[str], None], message_prefix: str = ""
) -> None:
    """Safely log token information without exposing the actual token.

    Args:
        token: The token to log information about
        logger_func: Logger function to use
        message_prefix: Optional prefix for the log message
    """
    if not token:
        logger_func(f"{message_prefix} No token provided")
        return

    token_info = f"Length: {len(token)}"

    if message_prefix:
        logger_func(f"{message_prefix} {token_info}")
    else:
        logger_func(f"Token info: {token_info}")


def safe_log_auth_values(
    auth_values: Dict[str, Any],
    logger_func: Callable[[str], None],
    message_prefix: str = "",
) -> None:
    """Safely log auth values without exposing sensitive data.

    Args:
        auth_values: Dictionary containing auth values
        logger_func: Logger function to use
        message_prefix: Optional prefix for the log message
    """
    if not auth_values:
        logger_func(f"{message_prefix} No auth values")
        return

    # Separate sensitive and non-sensitive fields
    sensitive_fields = []
    non_sensitive_fields = []

    for key in auth_values.keys():
        if _is_sensitive_field(key):
            sensitive_fields.append(key)
        else:
            non_sensitive_fields.append(key)

    info_parts = [
        f"Total: {len(auth_values)}",
        f"Sensitive: {len(sensitive_fields)}",
        f"Non-sensitive: {len(non_sensitive_fields)}",
    ]

    if non_sensitive_fields:
        info_parts.append(f"Non-sensitive fields: {non_sensitive_fields}")

    if sensitive_fields:
        info_parts.append(f"Sensitive fields: {sensitive_fields}")

    info_str = " | ".join(info_parts)
    if message_prefix:
        logger_func(f"{message_prefix} {info_str}")
    else:
        logger_func(f"Auth values: {info_str}")
