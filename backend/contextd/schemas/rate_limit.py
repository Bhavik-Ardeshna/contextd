"""Rate limit schemas."""

from pydantic import BaseModel, Field


class RateLimitResult(BaseModel):
    """Result of a rate limit check."""

    allowed: bool = Field(..., description="Whether the request should be allowed")
    retry_after: float = Field(..., description="Seconds until rate limit resets (0.0 if allowed)")
    limit: int = Field(
        ...,
        description=(
            "Maximum requests per window "
            "(9999 indicates unlimited/not applicable, e.g., for Auth0 or system auth)"
        ),
    )
    remaining: int = Field(
        ...,
        description="Requests remaining in current window (9999 for unlimited/not applicable)",
    )
