from types import SimpleNamespace

from contextd.platform.entities._metadata import LLMExtractionConfig
from contextd.platform.sync.graph.llm_enrichment_service import LLMEnrichmentService


def _service() -> LLMEnrichmentService:
    sync_context = SimpleNamespace(logger=SimpleNamespace(debug=lambda *a, **k: None))
    provider = SimpleNamespace()
    return LLMEnrichmentService(provider=provider, sync_context=sync_context)


def test_service_reads_model_name_from_provider_metadata():
    sync_context = SimpleNamespace(logger=SimpleNamespace(debug=lambda *a, **k: None))
    provider = SimpleNamespace(
        model_spec=SimpleNamespace(llm_model=SimpleNamespace(name="extract-configured-model"))
    )

    service = LLMEnrichmentService(provider=provider, sync_context=sync_context)

    assert service.model_name == "extract-configured-model"


def test_parse_llm_response_filters_unknown_predefined_types():
    service = _service()
    llm_config = LLMExtractionConfig(
        enabled=True,
        base_node_type="EmailExtract",
        custom_entity_types=["Task", "Meeting"],
    )

    llm_response = SimpleNamespace(
        entities=[
            SimpleNamespace(
                type="Task",
                name="Send proposal",
                email=None,
                role=None,
                title=None,
                industry=None,
                domain=None,
                description="Follow up with the customer",
                date_value=None,
                context=None,
                address=None,
                city=None,
                country=None,
                category=None,
                status="open",
                due_date="2026-04-03",
                meeting_date=None,
                assigned_to="owner@example.com",
                owner=None,
                related_to=None,
                attendees=[],
                confidence=0.95,
            ),
            SimpleNamespace(
                type="Time",
                name="3 PM",
                email=None,
                role=None,
                title=None,
                industry=None,
                domain=None,
                description="Standalone time mention",
                date_value=None,
                context=None,
                address=None,
                city=None,
                country=None,
                category=None,
                status=None,
                due_date=None,
                meeting_date=None,
                assigned_to=None,
                owner=None,
                related_to=None,
                attendees=[],
                confidence=0.99,
            ),
        ]
    )

    result = service._parse_llm_response(
        llm_response=llm_response,
        field_name="snippet",
        model_used="extract-configured-model",
        duration_ms=123,
        confidence_threshold=0.6,
        allowed_entity_types={"EmailExtract:Task", "EmailExtract:Meeting"},
        llm_config=llm_config,
    )

    assert len(result.entities) == 1
    assert result.entities[0].type == "EmailExtract:Task"
    assert result.entities[0].properties["_edge_type"] == "CONTAINS_TASK"
    assert result.entities[0].properties["assigned_to"] == "owner@example.com"
