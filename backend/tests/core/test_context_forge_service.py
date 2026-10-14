import os
from uuid import uuid4

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core.context_forge_service import ContextForgeService
from contextd.platform.agent_orchestration.types import (
    ForgeAgentResponse,
    ForgeFactPredicateProposal,
    ForgeRelationshipProposal,
)


def test_build_mapping_uses_foreign_key_details_for_graph_preview() -> None:
    service = ContextForgeService()

    payload = service.build_mapping_artifact_payload(
        provider="postgresql",
        source_name="postgres-prod",
        target_collection_id="customer-360",
        status="draft",
        generated_by="test",
        discovery_snapshot={
            "source_identity": {"Database": "app"},
            "objects": [
                {
                    "name": "customers",
                    "rows": 10,
                    "columns": 3,
                    "foreign_keys": 0,
                    "inferred_entity": "Customer",
                    "selected": True,
                    "fields": [
                        {"name": "id", "primary_key": True},
                        {"name": "email"},
                    ],
                    "primary_keys": ["id"],
                },
                {
                    "name": "orders",
                    "rows": 20,
                    "columns": 4,
                    "foreign_keys": 1,
                    "inferred_entity": "Order",
                    "selected": True,
                    "fields": [
                        {"name": "id", "primary_key": True},
                        {
                            "name": "customer_id",
                            "foreign_key": True,
                            "ref_table": "customers",
                            "ref_column": "id",
                        },
                        {"name": "total_amount", "data_type": "numeric"},
                    ],
                    "primary_keys": ["id"],
                },
            ],
        },
    )

    relationships = payload["mapping_schema"]["relationships"]
    preview = payload["graph_preview"]

    assert relationships
    assert relationships[0]["source_object"] == "orders"
    assert relationships[0]["target"].startswith("entity_customers")
    assert any(node["kind"] == "fact" for node in preview["nodes"])
    assert preview["summary"]["entity_types"] == 2


def test_agent_proposals_are_merged_with_provenance() -> None:
    service = ContextForgeService()
    payload = service.build_mapping_artifact_payload(
        provider="postgresql",
        source_name="postgres-prod",
        target_collection_id=str(uuid4()),
        status="draft",
        generated_by="test",
        discovery_snapshot={
            "objects": [
                {
                    "name": "accounts",
                    "rows": 1,
                    "columns": 2,
                    "foreign_keys": 0,
                    "inferred_entity": "Account",
                    "selected": True,
                    "fields": [{"name": "id", "primary_key": True}],
                    "primary_keys": ["id"],
                },
                {
                    "name": "contacts",
                    "rows": 1,
                    "columns": 2,
                    "foreign_keys": 0,
                    "inferred_entity": "Contact",
                    "selected": True,
                    "fields": [{"name": "email"}, {"name": "account_ref"}],
                },
            ],
        },
    )

    merged = service._merge_agent_response(
        payload["mapping_schema"],
        ForgeAgentResponse(
            relationships=[
                ForgeRelationshipProposal(
                    source_object="contacts",
                    target_object="accounts",
                    source_column="account_ref",
                    label="belongs_to",
                    confidence=0.81,
                    rationale="Column name references account ownership.",
                )
            ],
            fact_predicates=[
                ForgeFactPredicateProposal(
                    source_object="contacts",
                    source_column="email",
                    predicate="has_email",
                    label="Email",
                    confidence=0.79,
                )
            ],
        ),
    )

    assert merged["relationships"][0]["provenance"] == "contextd-adk"
    assert merged["relationships"][0]["label"] == "belongs_to"
    assert any(fact["predicate"] == "has_email" for fact in merged["fact_predicates"])


def test_entity_label_handles_common_plural_table_names() -> None:
    service = ContextForgeService()

    assert service._entity_label("classes", "") == "Class"
    assert service._entity_label("classes", "Clas") == "Class"
    assert service._entity_label("businesses", "") == "Business"
    assert service._entity_label("companies", "") == "Company"
    assert service._entity_label("analysis", "") == "Analysis"
    assert service._entity_label("news", "") == "News"
    assert service._entity_label("people", "") == "Person"
