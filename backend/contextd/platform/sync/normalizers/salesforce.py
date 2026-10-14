"""Salesforce entity normalizer.

Transforms Salesforce-specific entity structures into the canonical
NormalizedEntity format, extracting:
- People from owner_id (and OwnerId in metadata for Account)
- Relations: Contact/Opportunity -> Account (PART_OF), Account -> Parent Account (PARENT)
- Status from stage_name (Opportunity), type/rating (Account)
- Web URLs and key properties for graph and LLM context
"""

from typing import List

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    NormalizedEntity,
    PersonRef,
    PersonRole,
    RelationRef,
    RelationType,
    StatusRef,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)


@register_normalizer(r"Salesforce.*Entity", source_type="salesforce")
class SalesforceNormalizer(BaseEntityNormalizer):
    """Normalizer for Salesforce entities.

    Handles extraction of:
    - owner_id / OwnerId (metadata) -> PersonRef with role OWNER
    - account_id -> PART_OF SalesforceAccountEntity
    - parent_id (Account) -> PARENT SalesforceAccountEntity
    - stage_name (Opportunity) -> StatusRef
    """

    source_type = "salesforce"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform Salesforce entity to NormalizedEntity.

        Args:
            entity: Salesforce entity instance

        Returns:
            NormalizedEntity with extracted people, relations, status
        """
        entity_class_name = entity.__class__.__name__

        if "Account" in entity_class_name:
            return self._normalize_account(entity)
        if "Contact" in entity_class_name:
            return self._normalize_contact(entity)
        if "Opportunity" in entity_class_name:
            return self._normalize_opportunity(entity)
        return self._normalize_generic(entity)

    def _extract_owner_person(self, entity: BaseEntity) -> List[PersonRef]:
        """Extract owner as PersonRef from owner_id or metadata OwnerId."""
        people: List[PersonRef] = []
        owner_id = getattr(entity, "owner_id", None)
        if not owner_id and getattr(entity, "metadata", None):
            meta = entity.metadata or {}
            owner_id = meta.get("OwnerId")
        if owner_id:
            people.append(
                PersonRef(
                    id=str(owner_id),
                    name=None,
                    email=None,
                    role=PersonRole.OWNER,
                    properties={"source": "salesforce"},
                )
            )
        return people

    def _normalize_account(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Salesforce Account entity."""
        people = self._extract_owner_person(entity)
        relations: List[RelationRef] = []
        self.add_relation_if_exists(
            relations,
            entity,
            "parent_id",
            "SalesforceAccountEntity",
            RelationType.PARENT,
        )

        status = None
        rating = getattr(entity, "rating", None)
        type_val = getattr(entity, "type", None)
        if rating or type_val:
            status = StatusRef(
                name=rating or type_val or "Account",
                category="account",
                properties={"type": type_val, "rating": rating},
            )

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            web_url=self.extract_web_url(entity, ["web_url_value"]),
            people=people,
            relations=relations,
            status=status,
            updated_at_field="updated_time",
            created_at_field="created_time",
            properties={
                "account_id": getattr(entity, "account_id", None),
                "account_number": getattr(entity, "account_number", None),
                "industry": getattr(entity, "industry", None),
                "type": type_val,
                "rating": rating,
            },
        )

    def _normalize_contact(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Salesforce Contact entity."""
        people = self._extract_owner_person(entity)
        relations: List[RelationRef] = []
        account_name = None
        if entity.breadcrumbs:
            for b in entity.breadcrumbs:
                if b.entity_type == "SalesforceAccountEntity":
                    account_name = b.name
                    break
        self.add_relation_if_exists(
            relations,
            entity,
            "account_id",
            "SalesforceAccountEntity",
            RelationType.PART_OF,
            name_field=None,
        )
        if relations and account_name:
            relations[-1].name = account_name

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            web_url=self.extract_web_url(entity, ["web_url_value"]),
            people=people,
            relations=relations,
            updated_at_field="updated_time",
            created_at_field="created_time",
            properties={
                "contact_id": getattr(entity, "contact_id", None),
                "email": getattr(entity, "email", None),
                "title": getattr(entity, "title", None),
                "account_id": getattr(entity, "account_id", None),
            },
        )

    def _normalize_opportunity(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Salesforce Opportunity entity."""
        people = self._extract_owner_person(entity)
        relations: List[RelationRef] = []
        account_name = None
        if entity.breadcrumbs:
            for b in entity.breadcrumbs:
                if b.entity_type == "SalesforceAccountEntity":
                    account_name = b.name
                    break
        self.add_relation_if_exists(
            relations,
            entity,
            "account_id",
            "SalesforceAccountEntity",
            RelationType.PART_OF,
            name_field=None,
        )
        if relations and account_name:
            relations[-1].name = account_name

        stage_name = getattr(entity, "stage_name", None)
        status = (
            StatusRef(
                name=stage_name,
                category="opportunity_stage",
                properties={
                    "probability": getattr(entity, "probability", None),
                    "is_won": getattr(entity, "is_won", False),
                    "is_closed": getattr(entity, "is_closed", False),
                },
            )
            if stage_name
            else None
        )

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            web_url=self.extract_web_url(entity, ["web_url_value"]),
            people=people,
            relations=relations,
            status=status,
            updated_at_field="updated_time",
            created_at_field="created_time",
            properties={
                "opportunity_id": getattr(entity, "opportunity_id", None),
                "amount": getattr(entity, "amount", None),
                "close_date": getattr(entity, "close_date", None),
                "stage_name": stage_name,
                "probability": getattr(entity, "probability", None),
                "account_id": getattr(entity, "account_id", None),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic normalization for unknown Salesforce entity types."""
        return self.create_base_normalized_entity(
            entity,
            updated_at_field="updated_time",
            created_at_field="created_time",
        )
