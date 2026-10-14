"""Email module for ContextD."""

from contextd.email.services import send_email, send_invite_email, send_welcome_email
from contextd.email.templates import get_api_key_expiration_email, get_invite_email

__all__ = [
    "send_email",
    "send_invite_email",
    "send_welcome_email",
    "get_api_key_expiration_email",
    "get_invite_email",
]
