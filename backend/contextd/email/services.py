"""Email service for sending emails via SendGrid."""

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from contextd.core.config import settings
from contextd.core.logging import logger

# Rate limiter: Track last request time to respect SendGrid's rate limits
_last_request_time = 0.0
_rate_limit_lock = asyncio.Lock()


async def _wait_for_rate_limit() -> None:
    """Ensure we don't exceed SendGrid's rate limit.

    SendGrid allows ~100 req/sec. We use a conservative 0.01s interval.
    """
    global _last_request_time

    async with _rate_limit_lock:
        now = time.monotonic()
        time_since_last_request = now - _last_request_time
        min_interval = 0.01

        if time_since_last_request < min_interval:
            sleep_time = min_interval - time_since_last_request
            await asyncio.sleep(sleep_time)

        _last_request_time = time.monotonic()


def _send_email_sync(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None,
    send_at: Optional[int] = None,
) -> None:
    """Synchronous email sending function via SendGrid to be run in a thread pool.

    Args:
    ----
        to_email: Recipient email address
        subject: Email subject line
        html_body: HTML email body
        from_email: Sender email (defaults to settings.SENDGRID_FROM_EMAIL)
        send_at: Unix timestamp for scheduled delivery (max 72 hours ahead)

    """
    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)

    message = Mail(
        from_email=from_email or settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )

    if send_at:
        message.send_at = send_at

    response = sg.send(message)

    if response.status_code >= 400:
        raise Exception(
            f"SendGrid error: {response.status_code} {response.body}"
        )


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None,
    send_at: Optional[int] = None,
    max_retries: int = 3,
) -> bool:
    """Send an email via SendGrid asynchronously with rate limiting and retry logic.

    Args:
    ----
        to_email: Recipient email address
        subject: Email subject line
        html_body: HTML email body
        from_email: Sender email (defaults to settings.SENDGRID_FROM_EMAIL)
        send_at: Unix timestamp for scheduled delivery (max 72 hours ahead)
        max_retries: Maximum number of retry attempts for rate limit errors (default: 3)

    Returns:
    -------
        bool: True if email was sent successfully, False otherwise

    """
    if not settings.SENDGRID_API_KEY or not settings.SENDGRID_FROM_EMAIL:
        logger.debug("SENDGRID_API_KEY or SENDGRID_FROM_EMAIL not configured - skipping email")
        return False

    for attempt in range(max_retries + 1):
        await _wait_for_rate_limit()

        try:
            await asyncio.to_thread(
                _send_email_sync,
                to_email,
                subject,
                html_body,
                from_email,
                send_at,
            )
            logger.info(f"Email sent to {to_email}: {subject}")
            return True
        except Exception as e:
            error_msg = str(e)

            is_rate_limit = "429" in error_msg or "rate limit" in error_msg.lower()

            if is_rate_limit and attempt < max_retries:
                backoff_time = 2**attempt
                logger.warning(
                    f"Rate limit hit sending email to {to_email}. "
                    f"Retrying in {backoff_time}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(backoff_time)
                continue

            logger.error(f"Failed to send email to {to_email} after {attempt + 1} attempts: {e}")
            return False

    return False


def _send_welcome_email_sync(to_email: str, user_name: str) -> None:
    """Synchronous welcome email sending function to be run in a thread pool."""
    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)

    # Generate random delay between 10 and 40 minutes
    delay_minutes = random.randint(10, 40)

    # Calculate scheduled time as Unix timestamp
    scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    send_at = int(scheduled_time.timestamp())

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject="Welcome to ContextD",
        html_content="""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey,
    </p>

    <p style="margin: 0 0 15px 0;">
        Thanks for signing up, this is Lennert (ContextD team).
    </p>

    <p style="margin: 0 0 15px 0;">
        Here's some useful stuff to get you started:
    </p>

    <p style="margin: 0 0 8px 0;">
        &bull; Our docs: <a href="https://docs.contextd.local/welcome"
          style="color: #0000EE; text-decoration: underline;">https://docs.contextd.local/welcome</a>
    </p>
    <p style="margin: 0 0 8px 0;">
        &bull; Our repo: <a href="https://github.com/contextd/contextd"
          style="color: #0000EE; text-decoration: underline;">https://github.com/contextd/contextd</a>
    </p>
    <p style="margin: 0 0 15px 0;">
        &bull; Our discord: <a href="https://discord.com/invite/6wDWUhhuu2"
          style="color: #0000EE; text-decoration: underline;">https://discord.com/invite/6wDWUhhuu2</a>
    </p>

    <p style="margin: 15px 0;">
        Let me know if you need anything or have any questions.
    </p>

    <p style="margin: 15px 0 0 0;">
        Btw, if you want to see ContextD in action or just chat about what you're building,
        feel free to book some time with me here:
        <a href="https://cal.com/contextd/demo"
          style="color: #0000EE; text-decoration: underline;">https://cal.com/contextd/demo</a>
    </p>

    <p style="margin: 15px 0 0 0;">
        Lennert<br>
    </p>
</div>
        """,
    )

    message.send_at = send_at
    response = sg.send(message)

    if response.status_code >= 400:
        raise Exception(
            f"SendGrid error: {response.status_code} {response.body}"
        )


def _send_welcome_followup_email_sync(to_email: str, user_name: str) -> None:
    """Synchronous follow-up email sending function to be run in a thread pool."""
    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject="how's your ContextD setup going?",
        html_content="""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey, just checking in.
    </p>

    <p style="margin: 0 0 15px 0;">
        Saw you signed up and wanted to see how things are going with ContextD.
        Have you had the chance to run a query yet?
    </p>

      <p style="margin: 0 0 15px 0;">
        Would love to hear what you're building, and let me know if there's
        anything I can do to help.
    </p>

    <p style="margin: 15px 0 0 0;">
        Lennert (ContextD team)
    </p>

    <p style="margin: 15px 0 0 0;">

    </p>
</div>
        """,
    )

    response = sg.send(message)

    if response.status_code >= 400:
        raise Exception(
            f"SendGrid error: {response.status_code} {response.body}"
        )


async def send_welcome_followup_email(to_email: str, user_name: str) -> None:
    """Send a follow-up welcome email to a user.

    Only works when both SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are configured.
    Uses asyncio.to_thread() to avoid blocking the event loop.
    """
    if not settings.SENDGRID_API_KEY or not settings.SENDGRID_FROM_EMAIL:
        logger.debug(
            "SENDGRID_API_KEY or SENDGRID_FROM_EMAIL not configured - skipping follow-up email"
        )
        return

    try:
        await asyncio.to_thread(_send_welcome_followup_email_sync, to_email, user_name)
        logger.info(f"Follow-up welcome email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send follow-up welcome email for {to_email}: {e}")


async def send_welcome_email(to_email: str, user_name: str) -> None:
    """Send a welcome email to a new user with random scheduling between 10-40 minutes.

    Also sends a follow-up email.

    Only works when both SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are configured.
    Uses asyncio.to_thread() to avoid blocking the event loop.
    The email will be scheduled for delivery between 10 and 40 minutes from now.
    """
    if not settings.SENDGRID_API_KEY or not settings.SENDGRID_FROM_EMAIL:
        logger.debug(
            "SENDGRID_API_KEY or SENDGRID_FROM_EMAIL not configured - skipping welcome email"
        )
        return

    try:
        await asyncio.to_thread(_send_welcome_email_sync, to_email, user_name)
        logger.info(f"Welcome email scheduled for {to_email}")

        # Also send the follow-up email
        await send_welcome_followup_email(to_email, user_name)
    except Exception as e:
        logger.error(f"Failed to schedule welcome email for {to_email}: {e}")


async def send_invite_email(
    to_email: str,
    invitation_url: str,
    inviter_name: str,
    org_name: str,
) -> bool:
    """Send an invitation email via SendGrid.

    Args:
    ----
        to_email: Recipient email address
        invitation_url: Auth0 invitation acceptance URL
        inviter_name: Name of the person sending the invite
        org_name: Name of the organization

    Returns:
    -------
        bool: True if email was sent successfully, False otherwise

    """
    from contextd.email.templates import get_invite_email

    subject, html_body = get_invite_email(invitation_url, inviter_name, org_name)
    return await send_email(to_email=to_email, subject=subject, html_body=html_body)
