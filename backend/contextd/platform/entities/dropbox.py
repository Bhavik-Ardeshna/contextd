"""Dropbox entity schemas."""

from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class DropboxAccountEntity(BaseEntity):
    """Schema for Dropbox account-level entities based on the Dropbox API.

    Reference:
        https://www.dropbox.com/developers/documentation/http/documentation#users-get_current_account
    """

    account_id: str = ContextDField(
        ...,
        description="Dropbox account ID",
        is_entity_id=True,
    )
    display_name: str = ContextDField(
        ...,
        description="Display name for the account",
        is_name=True,
        embeddable=True,
    )
    abbreviated_name: Optional[str] = ContextDField(
        None,
        description="Abbreviated form of the person's name (typically initials)",
        embeddable=False,
    )
    familiar_name: Optional[str] = ContextDField(
        None, description="Locale-dependent name (usually given name in US)", embeddable=True
    )
    given_name: Optional[str] = ContextDField(
        None, description="Also known as first name", embeddable=True
    )
    surname: Optional[str] = ContextDField(
        None, description="Also known as last name or family name", embeddable=True
    )
    email: Optional[str] = ContextDField(
        None, description="The user's email address", embeddable=True
    )
    email_verified: bool = ContextDField(
        False, description="Whether the user has verified their email address", embeddable=False
    )
    disabled: bool = ContextDField(
        False, description="Whether the user has been disabled", embeddable=False
    )
    account_type: Optional[str] = ContextDField(
        None, description="Type of account (basic, pro, business, etc.)", embeddable=True
    )
    is_teammate: bool = ContextDField(
        False, description="Whether this user is a teammate of the current user", embeddable=False
    )
    is_paired: bool = ContextDField(
        False,
        description="Whether the user has both personal and work accounts linked",
        embeddable=False,
    )
    team_member_id: Optional[str] = ContextDField(
        None, description="The user's unique team member ID (if part of a team)", embeddable=False
    )
    locale: Optional[str] = ContextDField(
        None,
        description="The language that the user specified (IETF language tag)",
        embeddable=False,
    )
    country: Optional[str] = ContextDField(
        None, description="The user's two-letter country code (ISO 3166-1)", embeddable=False
    )
    profile_photo_url: Optional[str] = ContextDField(
        None, description="URL for the profile photo", embeddable=False
    )
    referral_link: Optional[str] = ContextDField(
        None, description="The user's referral link", embeddable=False
    )
    space_used: Optional[int] = ContextDField(
        None, description="The user's total space usage in bytes", embeddable=False
    )
    space_allocated: Optional[int] = ContextDField(
        None, description="The user's total space allocation in bytes", embeddable=False
    )
    team_info: Optional[Dict] = ContextDField(
        None,
        description="Information about the team if user is a member",
        embeddable=True,
    )
    root_info: Optional[Dict] = ContextDField(
        None, description="Information about the user's root namespace", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to Dropbox home."""
        return "https://www.dropbox.com/home"


class DropboxFolderEntity(BaseEntity):
    """Schema for Dropbox folder entities matching the Dropbox API.

    Reference:
        https://www.dropbox.com/developers/documentation/http/documentation#files-list_folder
    """

    id: str = ContextDField(
        ...,
        description="Dropbox folder ID",
        is_entity_id=True,
    )
    name: str = ContextDField(
        ...,
        description="Folder name",
        is_name=True,
        embeddable=True,
    )
    path_lower: Optional[str] = ContextDField(
        None,
        description="Lowercase full path starting with slash",
        embeddable=False,
    )
    path_display: Optional[str] = ContextDField(
        None, description="Display path with proper casing", embeddable=True
    )
    sharing_info: Optional[Dict] = ContextDField(
        None, description="Sharing information for the folder", embeddable=True
    )
    read_only: bool = ContextDField(
        False, description="Whether the folder is read-only", embeddable=False
    )
    traverse_only: bool = ContextDField(
        False, description="Whether the folder can only be traversed", embeddable=False
    )
    no_access: bool = ContextDField(
        False, description="Whether the folder cannot be accessed", embeddable=False
    )
    property_groups: Optional[List[Dict]] = ContextDField(
        None, description="Custom properties and tags", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Web URL pointing to the folder in Dropbox."""
        path = self.path_display or ""
        return f"https://www.dropbox.com/home{path}"


class DropboxFileEntity(FileEntity):
    """Schema for Dropbox file entities matching the Dropbox API.

    Reference:
        https://www.dropbox.com/developers/documentation/http/documentation#files-list_folder
    """

    id: str = ContextDField(
        ...,
        description="Dropbox file ID",
        is_entity_id=True,
    )
    name: str = ContextDField(
        ...,
        description="File name",
        is_name=True,
        embeddable=True,
    )
    path_lower: Optional[str] = ContextDField(
        None, description="Lowercase full path in Dropbox", embeddable=False
    )
    path_display: Optional[str] = ContextDField(
        None, description="Display path with proper casing", embeddable=True
    )
    rev: Optional[str] = ContextDField(
        None, description="Unique identifier for the file revision", embeddable=False
    )
    client_modified: Optional[Any] = ContextDField(
        None,
        description="When file was modified by client",
        embeddable=False,
        is_created_at=True,
    )
    server_modified: Optional[Any] = ContextDField(
        None,
        description="When file was modified on server",
        embeddable=False,
        is_updated_at=True,
    )
    is_downloadable: bool = ContextDField(
        True, description="Whether file can be downloaded directly", embeddable=False
    )
    content_hash: Optional[str] = ContextDField(
        None, description="Dropbox content hash for integrity checks", embeddable=False
    )
    sharing_info: Optional[Dict] = ContextDField(
        None, description="Sharing information for the file", embeddable=True
    )
    has_explicit_shared_members: Optional[bool] = ContextDField(
        None, description="Whether file has explicit shared members", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Web URL that opens the file in Dropbox."""
        path = self.path_display or ""
        return f"https://www.dropbox.com/home{path}"
