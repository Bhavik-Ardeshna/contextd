"""Temporal client configuration and utilities."""

from typing import Optional

from temporalio.client import Client

from contextd.core.config import settings
from contextd.core.logging import logger


class TemporalClient:
    """Temporal client wrapper."""

    _client: Optional[Client] = None

    @classmethod
    async def get_client(cls) -> Client:
        """Get or create the Temporal client."""
        if cls._client is None:
            logger.info(
                f"Connecting to Temporal at {settings.temporal_address}, "
                f"namespace: {settings.TEMPORAL_NAMESPACE}"
            )

            cls._client = await Client.connect(
                target_host=settings.temporal_address,
                namespace=settings.TEMPORAL_NAMESPACE,
            )

        return cls._client

    @classmethod
    async def close(cls) -> None:
        """Close the Temporal client."""
        if cls._client is not None:
            # Temporal Python SDK Client doesn't have a close method
            # Just reset the client reference
            cls._client = None


# Singleton instance
temporal_client = TemporalClient()
