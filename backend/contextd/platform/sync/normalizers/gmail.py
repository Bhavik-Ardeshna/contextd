"""Gmail entity normalizer for canonical data model transformation.

This module normalizes Gmail entities (threads, messages, attachments) into
the canonical NormalizedEntity format for consistent pipeline processing.

Gmail Entity Types:
- GmailThreadEntity: Email threads (container for messages)
- GmailMessageEntity: Individual email messages
- GmailAttachmentEntity: File attachments
- GmailMessageDeletionEntity: Deletion signals for messages
"""

from typing import List

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    NormalizedEntity,
    NormalizedFileEntity,
    PersonRef,
    PersonRole,
    RelationRef,
    RelationType,
    TagRef,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)


@register_normalizer(r"Gmail.*Entity", source_type="gmail")
class GmailNormalizer(BaseEntityNormalizer):
    """Normalizer for Gmail entities.

    Gmail entity structure:
    - Threads contain messages
    - Messages have sender, recipients (to, cc, bcc)
    - Messages can have attachments
    - Label IDs represent Gmail labels (inbox, sent, custom labels)
    """

    source_type = "gmail"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform Gmail entity to NormalizedEntity.

        Route to specific handler based on entity type.
        """
        entity_class_name = entity.__class__.__name__

        if "Thread" in entity_class_name:
            return self._normalize_thread(entity)
        elif "Message" in entity_class_name and "Deletion" not in entity_class_name:
            return self._normalize_message(entity)
        elif "Attachment" in entity_class_name:
            return self._normalize_attachment(entity)
        elif "Deletion" in entity_class_name:
            return self._normalize_deletion(entity)
        else:
            return self._normalize_generic(entity)

    def _normalize_thread(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Gmail thread entity.

        Threads are containers for messages with metadata like:
        - snippet: Brief text preview
        - label_ids: Gmail labels applied
        - message_count: Number of messages
        - owner_email: The Gmail account owner
        """
        # Extract tags from label IDs
        tags = self._extract_labels_as_tags(getattr(entity, "label_ids", []) or [])

        # Add owner as a person reference
        people: List[PersonRef] = []
        owner_email = getattr(entity, "owner_email", None)
        if owner_email:
            people.append(self._create_person_from_email(owner_email, PersonRole.OWNER))

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "title", None) or entity.name,
            description=getattr(entity, "snippet", None),
            content=getattr(entity, "snippet", None),
            tags=tags,
            people=people,
            # Map timestamp fields
            updated_at_field="last_message_at",
            properties={
                "gmail_thread_id": getattr(entity, "gmail_thread_id", None),
                "thread_key": getattr(entity, "thread_key", None),
                "history_id": getattr(entity, "history_id", None),
                "message_count": getattr(entity, "message_count", None),
                "owner_email": owner_email,
            },
        )

    def _normalize_message(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Gmail message entity.

        Messages have:
        - sender: From address
        - recipients: To, CC, BCC addresses
        - subject: Email subject line
        - snippet: Brief preview
        - label_ids: Gmail labels
        - owner_email: The Gmail account owner

        Graph Structure:
        - PersonNodes created for sender, recipients (to, cc, bcc), and owner
        - Each person is connected with appropriate edges (SENT_BY, SENT_TO, CC_TO, etc.)
        - LLM extractions can create additional entities (ActionItems, Projects, etc.)
          with edges to related PersonNodes

        Thread Handling:
        - thread_id is stored in properties for grouping/filtering
        - Emails in the same thread share the same thread_id
        - Thread-based email connections (REPLY_TO) can be created by querying
          the graph for other emails with the same thread_id
        """
        # Extract people from sender and recipients
        people: List[PersonRef] = []

        # Add sender as author
        sender = getattr(entity, "sender", None)
        if sender:
            people.append(self._create_person_from_email(sender, PersonRole.AUTHOR))

        # Add TO recipients as assignees (primary recipients)
        for email in getattr(entity, "to", []) or []:
            people.append(self._create_person_from_email(email, PersonRole.ASSIGNEE))

        # Add CC recipients as watchers
        for email in getattr(entity, "cc", []) or []:
            people.append(self._create_person_from_email(email, PersonRole.WATCHER))

        # Add BCC recipients
        for email in getattr(entity, "bcc", []) or []:
            people.append(self._create_person_from_email(email, PersonRole.OTHER))

        # Add owner as a person reference
        owner_email = getattr(entity, "owner_email", None)
        if owner_email:
            people.append(self._create_person_from_email(owner_email, PersonRole.OWNER))

        # Extract tags from label IDs
        tags = self._extract_labels_as_tags(getattr(entity, "label_ids", []) or [])

        # NOTE: We don't create a relation to GmailThreadEntity because:
        # 1. GmailThreadEntity has create_entity_node=False (no thread nodes exist)
        # 2. Thread-based email connections should be email-to-email (REPLY_TO edges)
        # 3. The thread_id is stored in properties for filtering/grouping
        relations: List[RelationRef] = []
        thread_id = getattr(entity, "thread_id", None)

        # Store thread_id in properties for thread-based queries
        # This enables finding all emails in a thread without creating
        # broken edges to non-existent thread nodes

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "subject", None) or entity.name,
            description=getattr(entity, "snippet", None),
            content=getattr(entity, "snippet", None),
            people=people,
            tags=tags,
            relations=relations,
            # Map timestamp fields
            created_at_field="sent_at",
            updated_at_field="internal_timestamp",
            properties={
                "message_id": getattr(entity, "message_id", None),
                "message_key": getattr(entity, "message_key", None),
                "thread_id": thread_id,
                "owner_email": owner_email,
            },
        )

    def _normalize_attachment(self, entity: BaseEntity) -> NormalizedFileEntity:
        """Normalize Gmail attachment entity.

        Attachments are files attached to messages with:
        - filename: Original filename
        - mime_type: File MIME type
        - message_id: Parent message ID
        """
        # Build relations - attachment belongs to message and thread
        relations: List[RelationRef] = []

        message_id = getattr(entity, "message_id", None)
        if message_id:
            relations.append(
                RelationRef(
                    entity_id=f"msg_{message_id}",
                    entity_type="GmailMessageEntity",
                    relation_type=RelationType.ATTACHMENT_OF,
                    name=f"Message {message_id}",
                )
            )

        thread_id = getattr(entity, "thread_id", None)
        if thread_id:
            relations.append(
                RelationRef(
                    entity_id=f"thread_{thread_id}",
                    entity_type="GmailThreadEntity",
                    relation_type=RelationType.PART_OF,
                    name=f"Thread {thread_id}",
                )
            )

        return self.create_base_file_entity(
            entity,
            file_url=getattr(entity, "url", "") or "",
            name=getattr(entity, "filename", None) or entity.name,
            relations=relations,
            properties={
                "attachment_key": getattr(entity, "attachment_key", None),
                "attachment_id": getattr(entity, "attachment_id", None),
                "message_id": message_id,
                "thread_id": thread_id,
            },
        )

    def _normalize_deletion(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Gmail deletion entity.

        Deletion entities signal that a message was deleted.
        """
        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "label", None) or entity.name,
            properties={
                "message_key": getattr(entity, "message_key", None),
                "message_id": getattr(entity, "message_id", None),
                "thread_id": getattr(entity, "thread_id", None),
                "deletion_status": getattr(entity, "deletion_status", None),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic fallback for unknown Gmail entity types."""
        return self.create_base_normalized_entity(entity)

    def _create_person_from_email(
        self,
        email_string: str,
        role: PersonRole,
    ) -> PersonRef:
        """Create a PersonRef from an email string.

        Email strings can be in formats:
        - "user@example.com"
        - "John Doe <user@example.com>"
        - "\"John Doe\" <user@example.com>"
        """
        email = email_string
        name = None

        # Parse "Name <email>" format
        if "<" in email_string and ">" in email_string:
            parts = email_string.rsplit("<", 1)
            name = parts[0].strip().strip('"').strip()
            email = parts[1].rstrip(">").strip()

        # Use email as ID for deduplication
        return PersonRef(
            id=email.lower(),  # Normalize email as ID
            name=name,
            email=email,
            role=role,
            properties={},
        )

    def _extract_labels_as_tags(
        self,
        label_ids: List[str],
    ) -> List[TagRef]:
        """Convert Gmail label IDs to TagRef objects.

        Gmail labels are identifiers like:
        - INBOX, SENT, DRAFT, SPAM, TRASH (system labels)
        - CATEGORY_PROMOTIONS, CATEGORY_SOCIAL (category labels)
        - Custom label IDs (user-created labels)
        """
        if not label_ids:
            return []

        tags = []
        for label_id in label_ids:
            # Determine tag type based on label ID pattern
            if label_id.startswith("CATEGORY_"):
                tag_type = "category"
                tag_name = label_id.replace("CATEGORY_", "").lower().title()
            elif label_id in ("INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "STARRED", "IMPORTANT"):
                tag_type = "system"
                tag_name = label_id.lower().title()
            else:
                tag_type = "label"
                tag_name = label_id  # Custom labels use their ID as name

            tags.append(
                TagRef(
                    id=label_id,
                    name=tag_name,
                    tag_type=tag_type,
                    properties={},
                )
            )

        return tags
