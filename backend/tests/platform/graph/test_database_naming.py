from uuid import UUID

from contextd.platform.graph.database import neo4j_collection_database_name


def test_neo4j_collection_database_name_is_safe_and_deterministic():
    org_id = UUID("b55f1d09-2c9d-4caa-8ff8-38724887614d")

    first = neo4j_collection_database_name(org_id, "Customer 360 / Production")
    second = neo4j_collection_database_name(str(org_id), "Customer 360 / Production")

    assert first == second
    assert first.startswith("ctxd-b55f1d09-customer-360-production-")
    assert len(first) <= 63
    assert "_" not in first
    assert "/" not in first


def test_neo4j_collection_database_name_separates_tenants():
    readable_id = "customer-360"

    first = neo4j_collection_database_name(
        UUID("b55f1d09-2c9d-4caa-8ff8-38724887614d"),
        readable_id,
    )
    second = neo4j_collection_database_name(
        UUID("11111111-2c9d-4caa-8ff8-38724887614d"),
        readable_id,
    )

    assert first != second
