"""Core PostHog analytics service for ContextD."""

from typing import Any, Dict, Optional

import posthog

from contextd.core.config import settings
from contextd.core.logging import logger


class AnalyticsService:
    """Centralized analytics service for PostHog integration.

    Handles all PostHog interactions and provides a clean interface
    for tracking events throughout the ContextD application.
    """

    def __init__(self):
        """Initialize the analytics service with PostHog configuration."""
        # Analytics is explicitly opt-in and remains off for local/test profiles.
        self.enabled = (
            settings.ANALYTICS_ENABLED and settings.ENVIRONMENT not in settings.LOCAL_ENVIRONMENTS
        )
        self.logger = logger.with_context(component="analytics")

        if self.enabled:
            posthog.api_key = settings.POSTHOG_API_KEY
            posthog.host = settings.POSTHOG_HOST
            self.logger.info(f"PostHog analytics initialized (environment: {settings.ENVIRONMENT})")
        else:
            self.logger.info(
                f"PostHog analytics disabled (environment: {settings.ENVIRONMENT}, "
                f"enabled: {settings.ANALYTICS_ENABLED})"
            )

    def _get_deployment_type(self) -> str:
        """Determine if this is hosted platform or self-hosted deployment.

        Returns:
            str: "hosted" for app.contextd.local, "self_hosted" for other deployments
        """
        if settings.ENVIRONMENT == "prd" and settings.APP_FULL_URL is None:
            return "hosted"  # Production ContextD hosted platform
        return "self_hosted"  # All other deployments (local, dev, test, custom)

    def _get_deployment_identifier(self) -> str:
        """Get a unique identifier for this deployment.

        Returns:
            str: Unique identifier for the deployment
        """
        if settings.ENVIRONMENT == "prd" and settings.APP_FULL_URL is None:
            return "contextd-hosted"  # Official hosted platform
        elif settings.API_FULL_URL:
            return f"custom-{settings.API_FULL_URL}"  # Custom deployment
        else:
            return f"{settings.ENVIRONMENT}-{settings.API_FULL_URL or 'default'}"

    def identify_user(self, user_id: str, properties: Dict[str, Any]) -> None:
        """Identify a user with properties.

        Args:
        ----
            user_id: Unique identifier for the user
            properties: User properties to set
        """
        if not self.enabled:
            return

        try:
            # Create a copy to avoid mutating the caller's properties dict
            user_properties = dict(properties) if properties else {}
            user_properties.update(
                {
                    "environment": settings.ENVIRONMENT,
                    "deployment_type": self._get_deployment_type(),
                    "deployment_id": self._get_deployment_identifier(),
                    "is_hosted_platform": self._get_deployment_type() == "hosted",
                    "api_url": settings.api_url,
                    "app_url": settings.app_url,
                }
            )

            posthog.capture(
                distinct_id=user_id, event="$identify", properties={"$set": user_properties}
            )
            self.logger.debug(f"User identified: {user_id}")
        except Exception as e:
            self.logger.error(f"Failed to identify user {user_id}: {e}")

    def track_event(
        self,
        event_name: str,
        distinct_id: str,
        properties: Optional[Dict[str, Any]] = None,
        groups: Optional[Dict[str, str]] = None,
    ) -> None:
        """Track an event with optional properties and groups.

        Args:
        ----
            event_name: Name of the event to track
            distinct_id: Unique identifier for the user/entity
            properties: Event properties
            groups: Group associations (e.g., organization)
        """
        if not self.enabled:
            return

        try:
            # Create a copy to avoid mutating the caller's properties dict
            event_properties = dict(properties) if properties else {}
            event_properties.update(
                {
                    "environment": settings.ENVIRONMENT,
                    "deployment_type": self._get_deployment_type(),
                    "deployment_id": self._get_deployment_identifier(),
                    "is_hosted_platform": self._get_deployment_type() == "hosted",
                    "api_url": settings.api_url,
                    "app_url": settings.app_url,
                }
            )

            posthog.capture(
                distinct_id=distinct_id,
                event=event_name,
                properties=event_properties,
                groups=groups or {},
            )
            self.logger.debug(f"Event tracked: {event_name} for {distinct_id}")
        except Exception as e:
            self.logger.error(f"Failed to track event {event_name}: {e}")

    def set_group_properties(
        self, group_type: str, group_key: str, properties: Dict[str, Any]
    ) -> None:
        """Set properties for a group (e.g., organization).

        Args:
        ----
            group_type: Type of group (e.g., 'organization')
            group_key: Unique identifier for the group
            properties: Properties to set for the group
        """
        if not self.enabled:
            return

        try:
            # Create a copy to avoid mutating the caller's properties dict
            group_properties = dict(properties) if properties else {}
            group_properties.update(
                {
                    "environment": settings.ENVIRONMENT,
                    "deployment_type": self._get_deployment_type(),
                    "deployment_id": self._get_deployment_identifier(),
                    "is_hosted_platform": self._get_deployment_type() == "hosted",
                    "api_url": settings.api_url,
                    "app_url": settings.app_url,
                }
            )

            posthog.capture(
                distinct_id=group_key,
                event="$groupidentify",
                properties={
                    "$group_type": group_type,
                    "$group_key": group_key,
                    "$group_set": group_properties,
                },
            )
            self.logger.debug(f"Group properties set: {group_type}:{group_key}")
        except Exception as e:
            self.logger.error(f"Failed to set group properties for {group_type}:{group_key}: {e}")


# Global analytics service instance
analytics = AnalyticsService()
