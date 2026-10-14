"""Tests for connector business logic module boundaries."""

from types import SimpleNamespace

from contextd.platform.agent_orchestration import business_logic
from contextd.platform.agent_orchestration.business_logic_mentions import (
    get_source_types_in_collection_from_syncs,
    parse_collection_mention_from_message,
    parse_connector_filter_from_message,
)
from contextd.platform.agent_orchestration.business_logic_models import (
    ConnectorBusinessLogic,
)
from contextd.platform.agent_orchestration.business_logic_schema import (
    format_pruned_schema,
)


def test_business_logic_module_keeps_public_import_surface() -> None:
    assert business_logic.ConnectorBusinessLogic is ConnectorBusinessLogic
    assert business_logic.format_pruned_schema is format_pruned_schema
    assert business_logic.parse_connector_filter_from_message is parse_connector_filter_from_message


def test_connector_business_logic_merge_deduplicates_types_and_shapes() -> None:
    base = ConnectorBusinessLogic(
        source_type="gmail",
        node_types=["Message", "User"],
        rel_types=["SENT_BY"],
        entity_property_shapes={"Message": ["subject", "sender"]},
        schema_narrative="mail narrative",
    )
    other = ConnectorBusinessLogic(
        source_type="calendar",
        node_types=["Event", "User"],
        rel_types=["SENT_BY", "INVITES"],
        entity_property_shapes={"Message": ["sender", "date"], "Event": ["title"]},
        schema_narrative="calendar narrative",
        node_id_prefix_to_type={"event": "Event"},
    )

    merged = base.merge_with(other)

    assert merged.source_type == "gmail"
    assert merged.node_types == ["Message", "User", "Event"]
    assert merged.rel_types == ["SENT_BY", "INVITES"]
    assert merged.entity_property_shapes == {
        "Message": ["subject", "sender", "date"],
        "Event": ["title"],
    }
    assert merged.schema_narrative == "mail narrative\n\ncalendar narrative"
    assert merged.node_id_prefix_to_type == {"event": "Event"}


def test_format_pruned_schema_merges_table_and_entity_variants() -> None:
    schema = format_pruned_schema(
        [
            {
                "node_type": "CustomersTableEntity",
                "properties": ["email"],
                "explanation": "Properties: email.",
            },
            {
                "node_type": "Customer",
                "properties": ["name"],
                "explanation": "Customer profile",
            },
            {
                "node_type": "Ignored",
                "properties": [],
                "explanation": "Filter or search by status or owner.",
            },
        ]
    )

    assert "Node: Customer | Properties: email, name | Expl: Customer profile" in schema
    assert "Node: Ignored | Properties: status, owner" in schema


def test_mention_parsing_and_source_type_extraction() -> None:
    syncs = [
        SimpleNamespace(
            source_connection=SimpleNamespace(source=SimpleNamespace(short_name="gmail"))
        ),
        SimpleNamespace(
            source_connection=SimpleNamespace(source=SimpleNamespace(short_name="notion"))
        ),
        SimpleNamespace(
            source_connection=SimpleNamespace(source=SimpleNamespace(short_name="gmail"))
        ),
        SimpleNamespace(source_connection=None),
    ]

    assert parse_collection_mention_from_message("show @Sales") == "Sales"
    assert parse_connector_filter_from_message("show @Sales") == "sales"
    assert parse_collection_mention_from_message("@search @graph show @e2e-flow-main") == "e2e-flow-main"
    assert parse_connector_filter_from_message("@search @graph show @postgresql lineage") == "postgresql"
    assert parse_connector_filter_from_message("@temporal @core show graph") is None
    assert parse_collection_mention_from_message("show everything") is None
    assert get_source_types_in_collection_from_syncs(syncs) == ["gmail", "notion"]
