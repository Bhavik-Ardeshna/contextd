"""
Message utilities for agent execution.
"""

from __future__ import annotations

from typing import Any


def message_to_dict(message: Any) -> dict[str, Any]:
    """
    Convert a message to dictionary format.

    Args:
        message: Message in any format (dict, Pydantic model, etc.)

    Returns:
        Dictionary representation of the message
    """
    if isinstance(message, dict):
        return message
    if hasattr(message, "to_dict"):
        return message.to_dict()
    if hasattr(message, "model_dump"):
        return message.model_dump()
    return {"role": "user", "content": str(message)}
