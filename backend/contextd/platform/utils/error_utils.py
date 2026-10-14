"""Error handling utilities.

This module provides utilities for extracting meaningful error messages from exceptions,
particularly useful for exceptions that have empty string representations or complex
nested causes.
"""

import traceback


def _get_root_cause(error: Exception) -> Exception:
    """Get the root cause of an exception chain."""
    root_cause = error
    while root_cause.__cause__ is not None:
        root_cause = root_cause.__cause__
    return root_cause


def _strip_application_error_prefix(text: str) -> str:
    """Strip Temporal's ApplicationError prefix if present."""
    if text.startswith("ApplicationError: "):
        return text[len("ApplicationError: ") :]
    return text


def _format_with_type_if_needed(error_str: str, root_cause: Exception) -> str:
    """Add exception type to error string if not already present."""
    error_type = type(root_cause).__name__

    # If the error string doesn't contain the type name, prepend it
    # (unless it's ApplicationError which we already stripped)
    if error_type not in error_str and error_type != "ApplicationError":
        return f"{error_type}: {error_str}"
    return error_str


def _get_message_from_traceback(root_cause: Exception) -> str | None:
    """Try to extract meaningful info from the traceback."""
    error_type = type(root_cause).__name__

    try:
        # Get the exception traceback as a list of strings
        tb_lines = traceback.format_exception(
            type(root_cause), root_cause, root_cause.__traceback__
        )
        if tb_lines:
            # The last line usually contains the most relevant error info
            last_line = tb_lines[-1].strip()
            last_line = _strip_application_error_prefix(last_line)

            if last_line and last_line != f"{error_type}":
                return last_line
    except Exception:
        pass

    return None


def _get_message_from_args(root_cause: Exception) -> str | None:
    """Try to get message from exception args."""
    error_type = type(root_cause).__name__

    if hasattr(root_cause, "args") and root_cause.args:
        args_str = ", ".join(str(arg) for arg in root_cause.args if arg)
        if args_str:
            args_str = _strip_application_error_prefix(args_str)
            return f"{error_type}: {args_str}"

    return None


def _get_fallback_message(root_cause: Exception) -> str:
    """Get fallback message showing exception type with module."""
    error_type = type(root_cause).__name__
    error_module = type(root_cause).__module__

    if error_module and error_module != "builtins":
        return f"{error_module}.{error_type}"
    return error_type


def get_error_message(error: Exception) -> str:
    """Get a meaningful error message from an exception.

    This function extracts the most useful information from an exception, including:
    - The root cause of the error chain
    - The actual error message (not just the type)
    - Handles cases where str(error) is empty or not informative
    - Strips temporal "ApplicationError: " prefix

    Args:
        error: The exception to extract the message from

    Returns:
        A meaningful error message string

    Examples:
        >>> try:
        ...     raise ValueError("Something went wrong")
        ... except Exception as e:
        ...     print(get_error_message(e))
        Something went wrong

        >>> try:
        ...     raise httpx.ReadTimeout()  # Has empty str()
        ... except Exception as e:
        ...     print(get_error_message(e))
        httpx.ReadTimeout: The read operation timed out
    """
    # First, try to get the root cause of the exception chain
    root_cause = _get_root_cause(error)

    # Get the basic string representation
    error_str = str(root_cause)

    # If we have a good error message, check if we need more context
    if error_str and error_str.strip():
        error_str = _strip_application_error_prefix(error_str)
        return _format_with_type_if_needed(error_str, root_cause)

    # If str() is empty or not useful, try other methods
    # Try to extract meaningful info from the traceback
    tb_message = _get_message_from_traceback(root_cause)
    if tb_message:
        return tb_message

    # Try to get args from the exception
    args_message = _get_message_from_args(root_cause)
    if args_message:
        return args_message

    # Last resort: just return the type with module
    return _get_fallback_message(root_cause)


def format_exception_chain(error: Exception, max_depth: int = 3) -> str:
    """Format an exception chain showing the cause hierarchy.

    Args:
        error: The exception to format
        max_depth: Maximum depth of the chain to show

    Returns:
        A formatted string showing the exception chain
    """
    parts = []
    current = error
    depth = 0

    while current and depth < max_depth:
        msg = get_error_message(current)
        if depth == 0:
            parts.append(f"Error: {msg}")
        else:
            parts.append(f"Caused by: {msg}")

        current = getattr(current, "__cause__", None)
        depth += 1

    if current:
        parts.append("... (more causes)")

    return "\n".join(parts)
