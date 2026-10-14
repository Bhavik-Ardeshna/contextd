"""Trello entity schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField


class TrelloBoardEntity(BaseEntity):
    """Schema for Trello board entities.

    Reference:
        https://developer.atlassian.com/cloud/trello/rest/api-group-boards/
    """

    trello_id: str = ContextDField(
        ...,
        description="Trello's unique identifier for the board",
        embeddable=False,
        is_entity_id=True,
    )
    board_name: str = ContextDField(
        ..., description="Display name of the board.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When this board snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When this board snapshot was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the board in Trello.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    desc: Optional[str] = ContextDField(
        None, description="Description of the board", embeddable=True
    )
    closed: bool = ContextDField(
        False, description="Whether the board is closed/archived", embeddable=False
    )
    url: Optional[str] = ContextDField(
        None, description="URL to the board", embeddable=False, unhashable=True
    )
    short_url: Optional[str] = ContextDField(
        None, description="Short URL to the board", embeddable=False, unhashable=True
    )
    prefs: Optional[Dict[str, Any]] = ContextDField(
        None, description="Board preferences and settings", embeddable=False
    )
    id_organization: Optional[str] = ContextDField(
        None, description="ID of the organization this board belongs to", embeddable=False
    )
    pinned: bool = ContextDField(False, description="Whether the board is pinned", embeddable=False)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Trello board URL."""
        return self.web_url_value or self.url or self.short_url or ""


class TrelloListEntity(BaseEntity):
    """Schema for Trello list entities (columns on a board).

    Reference:
        https://developer.atlassian.com/cloud/trello/rest/api-group-lists/
    """

    trello_id: str = ContextDField(
        ...,
        description="Trello's unique identifier for the list",
        embeddable=False,
        is_entity_id=True,
    )
    list_name: str = ContextDField(
        ..., description="Display name of the list.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When this list snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When this list snapshot was updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to view this list (falls back to board URL).",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    id_board: str = ContextDField(
        ..., description="ID of the board this list belongs to", embeddable=False
    )
    board_name: str = ContextDField(
        ..., description="Name of the board this list belongs to", embeddable=True
    )
    closed: bool = ContextDField(
        False, description="Whether the list is archived", embeddable=False
    )
    pos: Optional[float] = ContextDField(
        None, description="Position of the list on the board", embeddable=False
    )
    subscribed: Optional[bool] = ContextDField(
        None, description="Whether the user is subscribed to this list", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return URL to open this list (defaults to board URL)."""
        return self.web_url_value or ""


class TrelloCardEntity(BaseEntity):
    """Schema for Trello card entities.

    Reference:
        https://developer.atlassian.com/cloud/trello/rest/api-group-cards/
    """

    trello_id: str = ContextDField(
        ...,
        description="Trello's unique identifier for the card",
        embeddable=False,
        is_entity_id=True,
    )
    card_name: str = ContextDField(
        ..., description="Display name of the card.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the card snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the card snapshot was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the card in Trello.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    desc: Optional[str] = ContextDField(
        None, description="Description/notes on the card", embeddable=True
    )
    id_board: str = ContextDField(
        ..., description="ID of the board this card belongs to", embeddable=False
    )
    board_name: str = ContextDField(..., description="Name of the board", embeddable=True)
    id_list: str = ContextDField(
        ..., description="ID of the list this card belongs to", embeddable=False
    )
    list_name: str = ContextDField(..., description="Name of the list", embeddable=True)
    closed: bool = ContextDField(False, description="Whether the card is archived", embeddable=True)
    due: Optional[str] = ContextDField(None, description="Due date for the card", embeddable=True)
    due_complete: Optional[bool] = ContextDField(
        None, description="Whether the due date is marked complete", embeddable=True
    )
    date_last_activity: Optional[Any] = ContextDField(
        None,
        description="Last activity date on the card",
        embeddable=False,
    )
    id_members: List[str] = ContextDField(
        default_factory=list,
        description="List of member IDs assigned to this card",
        embeddable=False,
    )
    members: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="Members assigned to this card", embeddable=True
    )
    id_labels: List[str] = ContextDField(
        default_factory=list,
        description="List of label IDs attached to this card",
        embeddable=False,
    )
    labels: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="Labels attached to this card", embeddable=True
    )
    id_checklists: List[str] = ContextDField(
        default_factory=list, description="List of checklist IDs on this card", embeddable=False
    )
    badges: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="Badge information (comments, attachments, votes, etc.)",
        embeddable=True,
    )
    pos: Optional[float] = ContextDField(
        None, description="Position of the card in the list", embeddable=False
    )
    short_link: Optional[str] = ContextDField(
        None, description="Short link to the card", embeddable=False
    )
    short_url: Optional[str] = ContextDField(
        None, description="Short URL to the card", embeddable=False, unhashable=True
    )
    url: Optional[str] = ContextDField(
        None, description="Full URL to the card", embeddable=False, unhashable=True
    )
    start: Optional[str] = ContextDField(
        None, description="Start date for the card", embeddable=True
    )
    subscribed: Optional[bool] = ContextDField(
        None, description="Whether the user is subscribed to this card", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Trello card URL."""
        return self.web_url_value or self.url or self.short_url or ""


class TrelloChecklistEntity(BaseEntity):
    """Schema for Trello checklist entities.

    Reference:
        https://developer.atlassian.com/cloud/trello/rest/api-group-checklists/
    """

    trello_id: str = ContextDField(
        ...,
        description="Trello's unique identifier for the checklist",
        embeddable=False,
        is_entity_id=True,
    )
    checklist_name: str = ContextDField(
        ..., description="Display name of the checklist.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the checklist snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the checklist snapshot was updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the checklist in Trello (card URL).",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    id_board: str = ContextDField(
        ..., description="ID of the board this checklist belongs to", embeddable=False
    )
    id_card: str = ContextDField(
        ..., description="ID of the card this checklist belongs to", embeddable=False
    )
    card_name: str = ContextDField(..., description="Name of the card", embeddable=True)
    pos: Optional[float] = ContextDField(
        None, description="Position of the checklist on the card", embeddable=False
    )
    check_items: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="List of checklist items with their states",
        embeddable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Trello checklist URL (falls back to card URL)."""
        return self.web_url_value or ""


class TrelloMemberEntity(BaseEntity):
    """Schema for Trello member (user) entities.

    Reference:
        https://developer.atlassian.com/cloud/trello/rest/api-group-members/
    """

    trello_id: str = ContextDField(
        ...,
        description="Trello's unique identifier for the member",
        embeddable=False,
        is_entity_id=True,
    )
    display_name: str = ContextDField(
        ..., description="Display name of the member.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the member snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the member snapshot was updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the member profile.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    username: str = ContextDField(..., description="The username of the member", embeddable=True)
    full_name: Optional[str] = ContextDField(
        None, description="Full name of the member", embeddable=True
    )
    initials: Optional[str] = ContextDField(None, description="Member's initials", embeddable=False)
    avatar_url: Optional[str] = ContextDField(
        None, description="URL to the member's avatar", embeddable=False
    )
    bio: Optional[str] = ContextDField(None, description="Member's bio", embeddable=True)
    url: Optional[str] = ContextDField(
        None, description="URL to the member's profile", embeddable=False, unhashable=True
    )
    id_boards: List[str] = ContextDField(
        default_factory=list,
        description="List of board IDs the member belongs to",
        embeddable=False,
    )
    member_type: Optional[str] = ContextDField(
        None, description="Type of member (normal, admin, etc.)", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Trello member profile URL."""
        return self.web_url_value or self.url or ""
