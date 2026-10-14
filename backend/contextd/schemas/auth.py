"""Authentication schemas for dev auth flow."""

from typing import Optional

from pydantic import BaseModel, EmailStr


class DevAuthLogin(BaseModel):
    """Schema for dev auth login request."""

    email: EmailStr
    password: str


class DevAuthRegister(BaseModel):
    """Schema for dev auth registration request."""

    email: EmailStr
    password: str
    full_name: Optional[str] = "User"


class DevAuthToken(BaseModel):
    """Schema for dev auth token response."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
