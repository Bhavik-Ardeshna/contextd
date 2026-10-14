"""Authentication module for the API."""

import logging

from fastapi_auth0 import Auth0, Auth0User
from jose import jwt

from contextd.core.config import settings


# Add a method to auth0 instance to verify tokens directly
async def get_user_from_token(token: str):
    """Verify a token and return the Auth0User.

    Args:
        token: The JWT token to verify.

    Returns:
        Auth0User if token is valid, None otherwise
    """
    try:
        if not token:
            return None

        if not settings.AUTH_ENABLED:
            # Auth0 is not configured; token verification not possible
            return None

        # Validate the token using the same logic as in the auth0.get_user method
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}

        # Find the correct key
        for key in auth0.jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if not rsa_key:
            logging.warning("Invalid kid header (wrong tenant or rotated public key)")
            return None

        # Decode and verify the token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=auth0.algorithms,
            audience=auth0.audience,
            issuer=f"https://{auth0.domain}/",
        )

        # Create an Auth0User from the payload
        return auth0.auth0_user_model(**payload)
    except Exception as e:
        logging.error(f"Error verifying token: {e}")
        return None


# Initialize Auth0 only if authentication is enabled
if settings.AUTH_ENABLED:
    auth0 = Auth0(
        domain=settings.AUTH0_DOMAIN,
        api_audience=settings.AUTH0_AUDIENCE,
        auto_error=False,
    )
else:
    # When Auth0 is not configured, create a stub that always returns None
    # (dev auth or API key auth must be used instead)
    class StubAuth0:
        """A stub Auth0 class that rejects all tokens when Auth0 is not configured."""

        def __init__(self):
            """Initialize the stub Auth0 instance."""
            self.domain = ""
            self.audience = ""
            self.algorithms = ["RS256"]
            self.jwks = {"keys": []}
            self.auth0_user_model = Auth0User

        async def get_user(self):
            """Return None — Auth0 is not configured."""
            return None

    auth0 = StubAuth0()
    logging.info("Auth0 not configured — dev auth or API key authentication required")
