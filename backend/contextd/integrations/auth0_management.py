"""Auth0 Management API client for organization management."""

import asyncio
import logging
from typing import Dict, List, Optional

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from contextd import schemas
from contextd.core.config import settings
from contextd.core.logging import logger


class Auth0RateLimitError(Exception):
    """Custom exception for Auth0 rate limit errors."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        """Initialize Auth0 rate limit error.

        Args:
            message: Error message
            retry_after: Number of seconds to wait before retrying
        """
        super().__init__(message)
        self.retry_after = retry_after


class Auth0ManagementClient:
    """Client for Auth0 Management API operations."""

    # Constants
    DEFAULT_TIMEOUT = 20.0
    INVITATION_TIMEOUT = 10.0
    MAX_RETRIES = 5
    MIN_RETRY_WAIT = 1  # seconds
    MAX_RETRY_WAIT = 60  # seconds

    def __init__(self):
        """Initialize the Auth0 Management Client."""
        self.domain = settings.AUTH0_DOMAIN
        self.client_id = settings.AUTH0_M2M_CLIENT_ID
        self.client_secret = settings.AUTH0_M2M_CLIENT_SECRET
        self.audience = f"https://{self.domain}/api/v2/"
        self.base_url = f"https://{self.domain}/api/v2"

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, Auth0RateLimitError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_RETRY_WAIT, max=MAX_RETRY_WAIT),
        before_sleep=before_sleep_log(logger, logging.INFO),
    )
    async def _get_management_token(self) -> str:
        """Get Auth0 Management API access token."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://{self.domain}/oauth/token",
                    json={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "audience": self.audience,
                        "grant_type": "client_credentials",
                    },
                    timeout=self.DEFAULT_TIMEOUT,
                )

                # Check for rate limit
                if response.status_code == 429:
                    retry_after = self._get_retry_after(response)
                    error_msg = "Auth0 token endpoint rate limit exceeded"
                    if retry_after:
                        logger.warning(f"{error_msg}. Retry after {retry_after} seconds.")
                        await asyncio.sleep(retry_after)
                    raise Auth0RateLimitError(error_msg, retry_after)

                response.raise_for_status()
                data = response.json()
                token = data["access_token"]
                logger.info("Successfully obtained Auth0 Management API token")
                return token
        except (httpx.HTTPStatusError, Auth0RateLimitError):
            # Re-raise for retry decorator
            raise
        except Exception as e:
            logger.error(f"Failed to get Auth0 Management API token: {e}")
            raise

    def _get_retry_after(self, response: httpx.Response) -> Optional[int]:
        """Extract retry-after header value from response."""
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return int(retry_after)
            except ValueError:
                logger.warning(f"Invalid retry-after header value: {retry_after}")
        return None

    @retry(
        retry=retry_if_exception_type(Auth0RateLimitError),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(
            multiplier=1,
            min=MIN_RETRY_WAIT,
            max=MAX_RETRY_WAIT,
        ),
        before_sleep=before_sleep_log(logger, logging.INFO),
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        timeout: float = DEFAULT_TIMEOUT,
        return_empty_list_on_error: bool = False,
    ) -> Dict | List[Dict] | None:
        """Make an authenticated request to the Auth0 Management API.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint path
            json_data: JSON payload for POST/PUT requests
            timeout: Request timeout in seconds
            return_empty_list_on_error: Return empty list instead of raising on error

        Returns:
            Response data or None for empty responses
        """
        try:
            token = await self._get_management_token()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{self.base_url}/{endpoint.lstrip('/')}"

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=timeout,
                )

                # Check for rate limit before raising for status
                if response.status_code == 429:
                    retry_after = self._get_retry_after(response)
                    error_msg = f"Auth0 API rate limit exceeded for {method} {endpoint}"
                    if retry_after:
                        logger.warning(f"{error_msg}. Retry after {retry_after} seconds.")
                        # If we have a retry-after header, wait that amount before retrying
                        await asyncio.sleep(retry_after)
                    raise Auth0RateLimitError(error_msg, retry_after)

                response.raise_for_status()

                if not response.content:
                    return None

                return response.json()

        except Auth0RateLimitError:
            # Re-raise rate limit errors for retry decorator
            raise
        except Exception as e:
            if return_empty_list_on_error:
                logger.error(f"Auth0 API request failed for {method} {endpoint}: {e}")
                return []
            raise

    # Organization Management Methods

    async def create_organization(self, name: str, display_name: str) -> Dict:
        """Create a new Auth0 organization."""
        try:
            # Auth0 org names must be lowercase and URL-safe
            org_name = name.lower().replace(" ", "-").replace("_", "-")

            org_data = await self._make_request(
                "POST", "/organizations", json_data={"name": org_name, "display_name": display_name}
            )
            logger.info(f"Successfully created Auth0 organization: {org_data['id']}")
            return org_data
        except Exception as e:
            logger.error(f"Failed to create Auth0 organization: {e}")
            raise

    async def delete_organization(self, org_id: str) -> None:
        """Delete an Auth0 organization."""
        try:
            await self._make_request("DELETE", f"/organizations/{org_id}")
            logger.info(f"Successfully deleted Auth0 organization: {org_id}")
        except Exception as e:
            logger.error(f"Failed to delete Auth0 organization: {e}")
            raise

    # User-Organization Relationship Methods

    async def get_user_organizations(self, auth0_user_id: str) -> List[Dict]:
        """Get organizations a user belongs to."""
        return await self._make_request(
            "GET", f"/users/{auth0_user_id}/organizations", return_empty_list_on_error=True
        )

    async def add_user_to_organization(self, org_id: str, user_id: str) -> None:
        """Add user to Auth0 organization."""
        try:
            await self._make_request(
                "POST", f"/organizations/{org_id}/members", json_data={"members": [user_id]}
            )
            logger.info(f"Successfully added user {user_id} to Auth0 organization {org_id}")
        except Exception as e:
            logger.error(f"Failed to add user to Auth0 organization: {e}")
            raise

    async def remove_user_from_organization(self, org_id: str, user_id: str) -> None:
        """Remove user from Auth0 organization."""
        try:
            await self._make_request(
                "DELETE", f"/organizations/{org_id}/members", json_data={"members": [user_id]}
            )
            logger.info(f"Successfully removed user {user_id} from Auth0 organization {org_id}")
        except Exception as e:
            logger.error(f"Failed to remove user from Auth0 organization: {e}")
            raise

    async def get_organization_members(self, org_id: str) -> List[Dict]:
        """Get all members of an organization."""
        return await self._make_request(
            "GET", f"/organizations/{org_id}/members", return_empty_list_on_error=True
        )

    # Invitation Management Methods

    async def get_roles(self) -> List[Dict]:
        """Get all roles from Auth0."""
        try:
            return await self._make_request("GET", "/roles")
        except Exception as e:
            logger.error(f"Auth0 API error getting roles: {e}")
            raise

    async def invite_user_to_organization(
        self, org_id: str, email: str, role: str = "member", inviter_user: schemas.User = None
    ) -> Dict:
        """Send Auth0 organization invitation."""
        try:
            inviter_name = (
                f"{inviter_user.full_name} ({inviter_user.email})"
                if inviter_user
                else "ContextD Platform"
            )

            # Get all roles and find the ID for the given role name
            all_roles = await self.get_roles()
            role_id = next((r["id"] for r in all_roles if r["name"] == role), None)

            if not role_id:
                logger.error(f"Role '{role}' not found in Auth0. Cannot send invitation.")
                raise ValueError(f"Role '{role}' not found.")

            invitation_data = await self._make_request(
                "POST",
                f"/organizations/{org_id}/invitations",
                json_data={
                    "inviter": {"name": inviter_name},
                    "invitee": {"email": email},
                    "client_id": settings.AUTH0_CLIENT_ID,
                    "roles": [role_id],  # Use roles for proper assignment
                    # "app_metadata": {"role": role}, # Deprecated
                },
                timeout=self.INVITATION_TIMEOUT,
            )

            logger.info(f"Successfully sent Auth0 invitation to {email} for organization {org_id}")
            return invitation_data
        except Exception as e:
            logger.error(f"Failed to send Auth0 invitation: {e}")
            raise

    async def get_pending_invitations(self, org_id: str) -> List[Dict]:
        """Get pending invitations for organization."""
        return await self._make_request(
            "GET",
            f"/organizations/{org_id}/invitations",
            timeout=self.INVITATION_TIMEOUT,
            return_empty_list_on_error=True,
        )

    async def delete_invitation(self, org_id: str, invitation_id: str) -> None:
        """Delete a pending invitation."""
        try:
            await self._make_request(
                "DELETE",
                f"/organizations/{org_id}/invitations/{invitation_id}",
                timeout=self.INVITATION_TIMEOUT,
            )
            logger.info(
                f"Successfully deleted invitation {invitation_id} from organization {org_id}"
            )
        except Exception as e:
            logger.error(f"Failed to delete invitation from Auth0: {e}")
            raise

    async def get_organization_member_roles(self, org_id: str, user_id: str) -> List[Dict]:
        """Get roles for a specific member of an organization."""
        return await self._make_request("GET", f"/organizations/{org_id}/members/{user_id}/roles")

    async def get_all_connections(self) -> List[Dict]:
        """Get all connections from Auth0."""
        try:
            return await self._make_request("GET", "/connections")
        except Exception as e:
            logger.error(f"Auth0 API error getting all connections: {e}")
            raise

    async def add_enabled_connection_to_organization(
        self, auth0_org_id: str, connection_id: str
    ) -> None:
        """Enable a connection for an organization in Auth0."""
        body = {"connection_id": connection_id, "assign_membership_on_login": False}
        try:
            await self._make_request(
                "POST",
                f"/organizations/{auth0_org_id}/enabled_connections",
                json_data=body,
            )
        except Exception as e:
            logger.error(
                f"Auth0 API error adding connection {connection_id} to org {auth0_org_id}: {e}"
            )
            raise


auth0_management_client = None
if settings.AUTH_ENABLED:
    auth0_management_client = Auth0ManagementClient()
