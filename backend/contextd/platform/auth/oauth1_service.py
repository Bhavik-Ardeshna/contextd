"""OAuth1 authentication service for integrations that use OAuth 1.0 protocol.

This service handles the 3-legged OAuth1 flow:
1. Obtain temporary credentials (request token)
2. Redirect user for authorization
3. Exchange for access token

Reference: RFC 5849 - The OAuth 1.0 Protocol
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode

import httpx
from fastapi import HTTPException

from contextd.core.logging import ContextualLogger


class OAuth1TokenResponse:
    """Response from OAuth1 token exchange."""

    def __init__(self, oauth_token: str, oauth_token_secret: str, **kwargs):
        """Initialize OAuth1 token response.

        Args:
            oauth_token: The OAuth token (access token or request token)
            oauth_token_secret: The OAuth token secret
            **kwargs: Additional parameters from the response
        """
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret
        self.additional_params = kwargs


class OAuth1Service:
    """Service for handling OAuth1 authentication flows."""

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a unique nonce for OAuth1 requests.

        Returns:
            A cryptographically secure random string
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def _get_timestamp() -> str:
        """Get current timestamp for OAuth1 requests.

        Returns:
            Current Unix timestamp as string
        """
        return str(int(time.time()))

    @staticmethod
    def _percent_encode(value: str) -> str:
        """Percent-encode a value according to RFC 3986.

        OAuth1 requires specific encoding: encode all characters except
        unreserved characters (A-Z, a-z, 0-9, -, ., _, ~).

        Args:
            value: The string to encode

        Returns:
            Percent-encoded string
        """
        return quote(str(value), safe="~")

    @staticmethod
    def _build_signature_base_string(method: str, url: str, params: dict) -> str:
        """Build the signature base string for OAuth1 signature.

        Format: HTTP_METHOD&URL&NORMALIZED_PARAMS

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Base URL without query parameters
            params: All OAuth and request parameters

        Returns:
            Signature base string
        """
        # Normalize parameters: sort by key, then by value
        sorted_params = sorted(params.items())
        param_str = "&".join(
            f"{OAuth1Service._percent_encode(k)}={OAuth1Service._percent_encode(v)}"
            for k, v in sorted_params
        )

        # Build base string: METHOD&URL&PARAMS (all percent-encoded)
        parts = [
            method.upper(),
            OAuth1Service._percent_encode(url),
            OAuth1Service._percent_encode(param_str),
        ]
        return "&".join(parts)

    @staticmethod
    def _sign_hmac_sha1(base_string: str, consumer_secret: str, token_secret: str = "") -> str:
        """Sign the base string using HMAC-SHA1.

        Args:
            base_string: The signature base string
            consumer_secret: Client/consumer secret
            token_secret: Token secret (empty for request token step)

        Returns:
            Base64-encoded signature
        """
        # Build signing key: consumer_secret&token_secret
        encoded_consumer = OAuth1Service._percent_encode(consumer_secret)
        encoded_token = OAuth1Service._percent_encode(token_secret)
        key = f"{encoded_consumer}&{encoded_token}"
        key_bytes = key.encode("utf-8")
        base_bytes = base_string.encode("utf-8")

        # Compute HMAC-SHA1
        signature_bytes = hmac.new(key_bytes, base_bytes, hashlib.sha1).digest()

        # Base64 encode
        import base64

        return base64.b64encode(signature_bytes).decode("utf-8")

    @staticmethod
    def _build_authorization_header(params: dict) -> str:
        """Build OAuth1 Authorization header.

        Format: OAuth oauth_consumer_key="...", oauth_nonce="...", ...

        Args:
            params: OAuth parameters to include in header

        Returns:
            Authorization header value
        """
        # Sort parameters for consistent ordering
        sorted_items = sorted(params.items())
        param_strings = [
            f'{OAuth1Service._percent_encode(k)}="{OAuth1Service._percent_encode(v)}"'
            for k, v in sorted_items
        ]
        return "OAuth " + ", ".join(param_strings)

    @staticmethod
    async def get_request_token(
        *,
        request_token_url: str,
        consumer_key: str,
        consumer_secret: str,
        callback_url: str,
        logger: ContextualLogger,
    ) -> OAuth1TokenResponse:
        """Obtain temporary credentials (request token) from OAuth1 provider.

        This is step 1 of the OAuth1 flow.

        Args:
            request_token_url: Provider's request token endpoint
            consumer_key: Client identifier (API key)
            consumer_secret: Client secret
            callback_url: Callback URL for OAuth flow
            logger: Logger for debugging

        Returns:
            OAuth1TokenResponse with temporary credentials

        Raises:
            HTTPException: If request token retrieval fails
        """
        # Build OAuth parameters
        oauth_params = {
            "oauth_consumer_key": consumer_key,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": OAuth1Service._get_timestamp(),
            "oauth_nonce": OAuth1Service._generate_nonce(),
            "oauth_version": "1.0",
            "oauth_callback": callback_url,
        }

        # Build signature base string
        base_string = OAuth1Service._build_signature_base_string(
            "POST", request_token_url, oauth_params
        )

        # Sign the request (no token secret for request token step)
        signature = OAuth1Service._sign_hmac_sha1(base_string, consumer_secret, "")
        oauth_params["oauth_signature"] = signature

        # Build Authorization header
        auth_header = OAuth1Service._build_authorization_header(oauth_params)

        logger.info(f"Requesting OAuth1 temporary credentials from {request_token_url}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    request_token_url,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                response.raise_for_status()

            # Parse response (form-encoded)
            response_params = dict(parse_qsl(response.text))

            if "oauth_token" not in response_params or "oauth_token_secret" not in response_params:
                logger.error(f"Invalid response from OAuth1 provider: {response.text}")
                raise HTTPException(status_code=400, detail="Invalid response from OAuth1 provider")

            logger.info("Successfully obtained OAuth1 temporary credentials")

            return OAuth1TokenResponse(
                oauth_token=response_params["oauth_token"],
                oauth_token_secret=response_params["oauth_token_secret"],
                **{
                    k: v
                    for k, v in response_params.items()
                    if k not in ["oauth_token", "oauth_token_secret"]
                },
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error obtaining request token: {e.response.status_code} - {e.response.text}"
            )
            raise HTTPException(
                status_code=400, detail=f"Failed to obtain request token: {e.response.text}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error obtaining request token: {str(e)}")
            raise HTTPException(
                status_code=400, detail=f"Failed to obtain request token: {str(e)}"
            ) from e

    @staticmethod
    async def exchange_token(
        *,
        access_token_url: str,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
        oauth_verifier: str,
        logger: ContextualLogger,
    ) -> OAuth1TokenResponse:
        """Exchange temporary credentials for access token credentials.

        This is step 3 of the OAuth1 flow (after user authorization).

        Args:
            access_token_url: Provider's access token endpoint
            consumer_key: Client identifier (API key)
            consumer_secret: Client secret
            oauth_token: Temporary token from step 1
            oauth_token_secret: Temporary token secret from step 1
            oauth_verifier: Verification code from user authorization
            logger: Logger for debugging

        Returns:
            OAuth1TokenResponse with access token credentials

        Raises:
            HTTPException: If token exchange fails
        """
        # Build OAuth parameters
        oauth_params = {
            "oauth_consumer_key": consumer_key,
            "oauth_token": oauth_token,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": OAuth1Service._get_timestamp(),
            "oauth_nonce": OAuth1Service._generate_nonce(),
            "oauth_version": "1.0",
            "oauth_verifier": oauth_verifier,
        }

        # Build signature base string
        base_string = OAuth1Service._build_signature_base_string(
            "POST", access_token_url, oauth_params
        )

        # Sign with both consumer secret and token secret
        signature = OAuth1Service._sign_hmac_sha1(base_string, consumer_secret, oauth_token_secret)
        oauth_params["oauth_signature"] = signature

        # Build Authorization header
        auth_header = OAuth1Service._build_authorization_header(oauth_params)

        logger.info(
            f"Exchanging OAuth1 temporary credentials for access token at {access_token_url}"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    access_token_url,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                response.raise_for_status()

            # Parse response (form-encoded)
            response_params = dict(parse_qsl(response.text))

            if "oauth_token" not in response_params or "oauth_token_secret" not in response_params:
                logger.error("Invalid OAuth1 access token response")
                raise HTTPException(status_code=400, detail="Invalid access token response")

            logger.info("Successfully obtained OAuth1 access token")

            return OAuth1TokenResponse(
                oauth_token=response_params["oauth_token"],
                oauth_token_secret=response_params["oauth_token_secret"],
                **{
                    k: v
                    for k, v in response_params.items()
                    if k not in ["oauth_token", "oauth_token_secret"]
                },
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error exchanging OAuth1 token: {e.response.status_code}"
            )
            raise HTTPException(
                status_code=400, detail="Failed to exchange OAuth1 token"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error exchanging token: {str(e)}")
            raise HTTPException(
                status_code=400, detail=f"Failed to exchange OAuth1 token: {str(e)}"
            ) from e

    @staticmethod
    def build_authorization_url(
        *,
        authorization_url: str,
        oauth_token: str,
        app_name: Optional[str] = None,
        scope: Optional[str] = None,
        expiration: Optional[str] = None,
    ) -> str:
        """Build the authorization URL for user consent.

        This is step 2 of the OAuth1 flow.

        Args:
            authorization_url: Provider's authorization endpoint
            oauth_token: Temporary token from step 1
            app_name: Optional app name to display
            scope: Optional scope (read, write, account, etc.)
            expiration: Optional expiration (1hour, 1day, 30days, never)

        Returns:
            Complete authorization URL for user redirect
        """
        params = {"oauth_token": oauth_token}

        if app_name:
            params["name"] = app_name
        if scope:
            params["scope"] = scope
        if expiration:
            params["expiration"] = expiration

        return f"{authorization_url}?{urlencode(params)}"


# Singleton instance
oauth1_service = OAuth1Service()
