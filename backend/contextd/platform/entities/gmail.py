"""Gmail entity schemas.

Defines entity schemas for Gmail resources:
  - Thread
  - Message
  - Attachment

Each entity includes:
- Graph configuration for building knowledge graph relationships
- Index configuration for vector and fulltext search
- LLM enrichment configuration for extracting entities from email content
"""

from datetime import datetime
from typing import ClassVar, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, DeletionEntity, EmailEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    EntityMetadata,
    EntityRelationConfig,
    FieldMetadata,
    GraphEdgeConfig,
    LLMExtractionConfig,
    SearchConfig,
)


class GmailThreadEntity(BaseEntity):
    """Schema for Gmail thread entities.

    Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.threads

    NOTE: Thread entities are used for tracking/metadata purposes only.
    Threads do NOT create separate graph nodes. Instead, emails in the same
    thread are connected directly to each other via IN_THREAD edges on
    the GmailMessageEntity.

    This entity is kept for:
    - Tracking thread metadata (message count, last message time)
    - Label aggregation across thread
    - Providing thread-level search/filtering

    Graph Configuration:
    - create_entity_node=False: No separate thread nodes in graph
    - Emails connect directly via IN_THREAD edge
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GmailThreadNode",
        create_entity_node=False,  # DO NOT create thread nodes - emails connect directly
        enable_llm_enrichment=False,  # No LLM for threads
        index=EntityIndexConfig(
            enabled=True,  # Still index for search
            fulltext_enabled=True,
            priority_fields=["title", "snippet"],
        ),
        fields={
            "title": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "snippet": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                # No graph edge - thread doesn't create nodes
            ),
            "label_ids": FieldMetadata(
                search=SearchConfig(embeddable=True),
                # No graph edge - thread doesn't create nodes
            ),
        },
    )

    thread_key: str = ContextDField(
        ...,
        description="Stable ContextD thread key (thread_<gmail_id>)",
        is_entity_id=True,
    )
    gmail_thread_id: str = ContextDField(
        ..., description="Native Gmail thread ID", embeddable=False
    )
    title: str = ContextDField(
        ...,
        description="Display title derived from snippet",
        is_name=True,
        embeddable=True,
    )
    last_message_at: Optional[datetime] = ContextDField(
        None,
        description="Timestamp of the most recent message in the thread",
        is_updated_at=True,
    )
    snippet: Optional[str] = ContextDField(
        None, description="A short snippet from the thread", embeddable=True
    )
    history_id: Optional[str] = ContextDField(
        None, description="The thread's history ID", embeddable=False
    )
    message_count: Optional[int] = ContextDField(
        0, description="Number of messages in the thread", embeddable=False
    )
    label_ids: List[str] = ContextDField(
        default_factory=list, description="Labels applied to this thread", embeddable=True
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the Gmail account owner (authenticated user)",
        embeddable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Direct link to open the thread in Gmail."""
        return f"https://mail.google.com/mail/u/0/#inbox/{self.gmail_thread_id}"


class GmailMessageEntity(EmailEntity):
    """Schema for Gmail message entities.

    Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.messages

    Graph Configuration:
    - Creates GmailMessageNode in the knowledge graph
    - Sender connected as PersonNode with SENT_BY edge (static)
    - Recipients connected as PersonNode with SENT_TO edge (static)
    - Labels connected as GmailLabelNode (static)
    - Thread relationship: emails in same thread connected via IN_THREAD edge

    LLM Enrichment (Curated Mode):
    - Combines subject, sender, recipients, and body into one content block
    - LLM may only emit a fixed set of 10 EmailExtract node types
    - Times/dates should be properties on richer nodes, not standalone graph nodes
    - Keeps the knowledge graph focused on reusable business concepts from email

    Index Configuration:
    - Subject and snippet are embeddable for semantic search
    - Sender and recipients indexed for filtering
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GmailMessageNode",
        create_entity_node=True,
        enable_llm_enrichment=True,  # Enable curated LLM extraction
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["subject", "snippet", "sender"],
        ),
        fields={
            "subject": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "snippet": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
                # Curated LLM extraction - combines multiple fields
                llm=LLMExtractionConfig(
                    enabled=True,
                    base_node_type="EmailExtract",
                    custom_entity_types=[
                        "Person",
                        "Task",
                        "Meeting",
                        "Project",
                        "Decision",
                        "Question",
                        "Deadline",
                        "Document",
                        "Company",
                        "Team",
                        "Product",
                    ],
                    content_template="""Subject: {subject}
From: {sender}
To: {to}
CC: {cc}
Body:
{snippet}""",
                    content_fields=["subject", "sender", "to", "cc", "snippet"],
                    extraction_hint="""Analyze this email and extract only these graph-worthy entity types:
- Person: a person who is important enough to track across messages as their own reusable node
- Task: a concrete task or follow-up worth tracking across emails
- Meeting: a meeting, call, or appointment that can recur across messages
- Project: a named initiative, workstream, or program
- Decision: an explicit decision or approval outcome
- Question: an open question that still needs an answer
- Deadline: a due date or milestone with clear context
- Document: a referenced spec, doc, file, deck, or artifact
- Company: an external or internal company/organization worth linking across emails
- Team: a named team, org unit, or working group
- Product: a named product, service, platform, or system

Do not invent any other node types.
Do not create standalone time/date nodes. Time should only appear as a property on a richer node such as a Meeting, Deadline, or Task.
Only extract things that deserve their own reusable node in the knowledge graph rather than remaining as plain text inside the email.
For Person entities, include email when available.
If an extracted entity relates to a specific person, include that person's email in fields like assigned_to, owner, related_to, or attendees.
Person must be a real human being—never a meeting/calendar product (e.g. Google Meet, Zoom), bot, or noreply sender; classify those as Product or Company when appropriate. Every type (Task, Company, Product, …) must refer to a concrete real-world thing, not boilerplate or mis-tagged categories.""",
                    confidence_threshold=0.6,
                ),
            ),
            "sender": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
                graph=GraphEdgeConfig(
                    edge_type="SENT_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="SENT",
                    is_list=False,
                ),
            ),
            "to": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="SENT_TO",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="RECEIVED",
                    is_list=True,
                ),
            ),
            "cc": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="CC_TO",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="CC_ON",
                    is_list=True,
                ),
            ),
            "bcc": FieldMetadata(
                search=SearchConfig(embeddable=False),
                graph=GraphEdgeConfig(
                    edge_type="BCC_TO",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="BCC_ON",
                    is_list=True,
                ),
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="OWNED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="OWNS",
                    is_list=False,
                ),
            ),
            "label_ids": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="LABELED_WITH",
                    to_node_type="GmailLabelNode",
                    create_reverse_edge=True,
                    reverse_edge_type="LABELS",
                    is_list=True,
                ),
            ),
            # NOTE: thread_id is NOT used for graph edges here.
            # Thread-based email connections (REPLY_TO, IN_THREAD_WITH) are created
            # in the normalizer by tracking emails with the same thread_id.
            "thread_id": FieldMetadata(
                search=SearchConfig(embeddable=False),
                # No graph config - handled by normalizer for email-to-email connections
            ),
        },
    )

    message_key: str = ContextDField(
        ...,
        description="Stable ContextD message key (msg_<gmail_id>)",
        is_entity_id=True,
    )
    message_id: str = ContextDField(..., description="Native Gmail message ID", embeddable=False)
    subject: str = ContextDField(
        ...,
        description="Subject line (fallback applied if missing)",
        is_name=True,
        embeddable=True,
    )
    sent_at: datetime = ContextDField(
        ...,
        description="Timestamp from the Date header (or internal date fallback)",
        is_created_at=True,
    )
    internal_timestamp: datetime = ContextDField(
        ...,
        description="Gmail internal timestamp representing last modification",
        is_updated_at=True,
    )
    thread_id: str = ContextDField(
        ..., description="ID of the thread this message belongs to", embeddable=False
    )
    sender: Optional[str] = ContextDField(
        None, description="Email address of the sender", embeddable=True
    )
    to: List[str] = ContextDField(
        default_factory=list, description="Recipients of the message", embeddable=True
    )
    cc: List[str] = ContextDField(
        default_factory=list, description="CC recipients", embeddable=True
    )
    bcc: List[str] = ContextDField(
        default_factory=list, description="BCC recipients", embeddable=True
    )
    date: Optional[datetime] = ContextDField(
        None, description="Date the message was sent", embeddable=True
    )
    snippet: Optional[str] = ContextDField(
        None, description="Brief snippet of the message content", embeddable=True
    )
    label_ids: List[str] = ContextDField(
        default_factory=list, description="Labels applied to this message", embeddable=True
    )
    internal_date: Optional[datetime] = ContextDField(
        None, description="Internal Gmail timestamp", embeddable=False
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the Gmail account owner (authenticated user)",
        embeddable=True,
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Direct Gmail URL for the message",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Direct link to open the message in Gmail."""
        return self.web_url_value or f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"


class GmailAttachmentEntity(FileEntity):
    """Schema for Gmail attachment entities.

    Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.messages.attachments

    Graph Configuration:
    - Creates GmailAttachmentNode in the knowledge graph
    - Connected to parent message with ATTACHED_TO edge
    - Connected to parent thread with PART_OF edge

    Index Configuration:
    - Filename is embeddable for semantic search
    - File content (if extracted) is indexed
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GmailAttachmentNode",
        create_entity_node=True,
        enable_llm_enrichment=False,  # Attachments use file content extraction instead
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["filename"],
        ),
        fields={
            "filename": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
        },
        entity_relations=[
            EntityRelationConfig(
                edge_type="ATTACHED_TO",
                to_entity_type="GmailMessageEntity",
                to_id_field="message_id",
                create_reverse_edge=True,
                reverse_edge_type="HAS_ATTACHMENT",
            ),
            EntityRelationConfig(
                edge_type="PART_OF",
                to_entity_type="GmailThreadEntity",
                to_id_field="thread_id",
                create_reverse_edge=True,
                reverse_edge_type="CONTAINS",
            ),
        ],
    )

    attachment_key: str = ContextDField(
        ...,
        description="Stable ContextD attachment key (attach_<message>_<filename>)",
        is_entity_id=True,
    )
    filename: str = ContextDField(
        ..., description="Attachment filename", is_name=True, embeddable=True
    )
    message_id: str = ContextDField(
        ..., description="ID of the message this attachment belongs to", embeddable=False
    )
    attachment_id: str = ContextDField(..., description="Gmail's attachment ID", embeddable=False)
    thread_id: str = ContextDField(
        ..., description="ID of the thread containing the message", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to view the parent message in Gmail",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the parent message view in Gmail."""
        return self.web_url_value or f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"


class GmailMessageDeletionEntity(DeletionEntity):
    """Deletion signal for a Gmail message.

    Emitted when the Gmail History API reports a messageDeleted. The entity_id matches the
    message entity's ID format (msg_{message_id}) so downstream deletion removes the
    correct parent/children.
    """

    deletes_entity_class = GmailMessageEntity

    message_key: str = ContextDField(
        ...,
        description="Stable ContextD message key (msg_<gmail_id>)",
        is_entity_id=True,
    )
    label: str = ContextDField(
        ...,
        description="Human-readable deletion label",
        is_name=True,
        embeddable=True,
    )
    message_id: str = ContextDField(
        ..., description="The Gmail message ID that was deleted", embeddable=False
    )
    thread_id: Optional[str] = ContextDField(
        None,
        description="Thread ID (optional if not provided by change record)",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Fallback link to Gmail inbox for the deleted message."""
        return f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"
