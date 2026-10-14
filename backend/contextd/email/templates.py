# noqa: E501

"""Email templates for ContextD notifications."""


def get_api_key_expiration_email(
    days_until_expiration: int,
    api_key_preview: str,
    settings_url: str,
) -> tuple[str, str]:
    """Generate email subject and HTML body for API key expiration notification.

    Args:
    ----
        days_until_expiration (int): Number of days until key expires (0 if expired)
        api_key_preview (str): First 4 characters of the API key
        settings_url (str): URL to the API keys settings page

    Returns:
    -------
        tuple[str, str]: (subject, html_body)

    """
    if days_until_expiration <= 0:
        # Key has expired
        subject = "ContextD API Key Expired"
        html_body = f"""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey,
    </p>

    <p style="margin: 0 0 15px 0;">
        Your ContextD API key (<code>{api_key_preview}...</code>) has expired and is no
        longer valid.
    </p>

    <p style="margin: 0 0 15px 0;">
        To continue using the ContextD API, you'll need to create a new API key.
    </p>

    <p style="margin: 0 0 15px 0;">
        <a href="{settings_url}"
          style="display: inline-block; padding: 10px 20px; background-color: #0066cc;
                 color: white; text-decoration: none; border-radius: 5px;">
          Create New API Key
        </a>
    </p>

    <p style="margin: 15px 0 0 0;">
        If you have any questions, feel free to reach out.<br>
        <br>
        ContextD Team
    </p>
</div>
        """
    elif days_until_expiration <= 3:
        # Urgent: 3 days or less
        plural = "s" if days_until_expiration > 1 else ""
        subject = f"Urgent: ContextD API Key Expires in {days_until_expiration} Day{plural}"
        html_body = f"""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey,
    </p>

    <p style="margin: 0 0 15px 0;">
        <strong>Your ContextD API key (<code>{api_key_preview}...</code>) will expire in
        {days_until_expiration} day{"s" if days_until_expiration > 1 else ""}.</strong>
    </p>

    <p style="margin: 0 0 15px 0;">
        To avoid service disruption, you can:
    </p>

    <ul style="margin: 0 0 15px 20px;">
        <li>Use the "Rotate Key" button to generate a new key</li>
        <li>Or create a new API key and update your applications</li>
    </ul>

    <p style="margin: 0 0 15px 0;">
        <a href="{settings_url}"
          style="display: inline-block; padding: 10px 20px; background-color: #0066cc;
                 color: white; text-decoration: none; border-radius: 5px;">
          Manage API Keys
        </a>
    </p>

    <p style="margin: 15px 0 0 0;">
        If you have any questions, feel free to reach out.<br>
        <br>
        ContextD Team
    </p>
</div>
        """
    else:
        # Standard reminder: 14 days
        subject = f"ContextD API Key Expires in {days_until_expiration} Days"
        html_body = f"""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey,
    </p>

    <p style="margin: 0 0 15px 0;">
        This is a friendly reminder that your ContextD API key
        (<code>{api_key_preview}...</code>) will expire in {days_until_expiration} days.
    </p>

    <p style="margin: 0 0 15px 0;">
        You can rotate your key or create a new one anytime in your settings.
    </p>

    <p style="margin: 0 0 15px 0;">
        <a href="{settings_url}"
          style="display: inline-block; padding: 10px 20px; background-color: #0066cc;
                 color: white; text-decoration: none; border-radius: 5px;">
          Manage API Keys
        </a>
    </p>

    <p style="margin: 15px 0 0 0;">
        ContextD Team
    </p>
</div>
        """

    return subject, html_body


def get_invite_email(
    invitation_url: str,
    inviter_name: str,
    org_name: str,
) -> tuple[str, str]:
    """Generate email subject and HTML body for an organization invitation.

    Args:
    ----
        invitation_url: Auth0 invitation acceptance URL
        inviter_name: Name of the person sending the invite
        org_name: Name of the organization

    Returns:
    -------
        tuple[str, str]: (subject, html_body)

    """
    subject = f"You've been invited to join {org_name} on ContextD"
    html_body = f"""
<div style="font-family: Arial, sans-serif; font-size: 10pt;">
    <p style="margin: 0 0 15px 0;">
        Hey,
    </p>

    <p style="margin: 0 0 15px 0;">
        {inviter_name} has invited you to join <strong>{org_name}</strong> on ContextD.
    </p>

    <p style="margin: 0 0 15px 0;">
        Click the button below to accept the invitation and get started:
    </p>

    <p style="margin: 0 0 15px 0;">
        <a href="{invitation_url}"
          style="display: inline-block; padding: 10px 20px; background-color: #0066cc;
                 color: white; text-decoration: none; border-radius: 5px;">
          Accept Invitation
        </a>
    </p>

    <p style="margin: 0 0 15px 0;">
        Or copy and paste this link into your browser:<br>
        <a href="{invitation_url}"
          style="color: #0000EE; text-decoration: underline;">{invitation_url}</a>
    </p>

    <p style="margin: 15px 0 0 0;">
        If you have any questions, feel free to reach out.<br>
        <br>
        ContextD Team
    </p>
</div>
    """

    return subject, html_body
