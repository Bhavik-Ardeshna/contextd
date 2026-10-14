"""Security utilities for dev auth: password hashing and JWT token management."""

from datetime import UTC, datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt

from contextd.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_dev_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token for dev auth.

    Args:
        data: Token payload (should include 'sub' and 'email').
        expires_delta: Optional expiration time delta.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.DEV_AUTH_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iss": "dev-auth"})
    return jwt.encode(to_encode, settings.DEV_AUTH_SECRET_KEY, algorithm="HS256")


def decode_dev_access_token(token: str) -> dict:
    """Decode and validate a dev auth JWT token.

    Args:
        token: The JWT token string.

    Returns:
        Decoded token payload.

    Raises:
        jose.JWTError: If token is invalid or expired.
    """
    return jwt.decode(token, settings.DEV_AUTH_SECRET_KEY, algorithms=["HS256"])
