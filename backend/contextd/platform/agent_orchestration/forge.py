"""Context Forge ADK schema-agent runner."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping
from uuid import UUID

from contextd.core.config import settings
from contextd.platform.agent_orchestration.agents import (
    create_forge_agent,
    create_glm_run_context,
)
from contextd.platform.agent_orchestration.prompts.forge import (
    build_forge_agent_user_message,
)
from contextd.platform.agent_orchestration.types import ForgeAgentResponse
from contextd.platform.llm.gateway import get_llm_gateway

logger = logging.getLogger(__name__)


async def run_context_forge_agent(
    *,
    organization_id: UUID,
    collection_readable_id: str | None,
    provider: str,
    source_name: str,
    mapping_schema: Mapping[str, Any],
) -> ForgeAgentResponse | None:
    """Run the ContextD ADK Forge agent when LLM configuration is available."""
    if not settings.CONTEXT_FORGE_AI_ENABLED:
        return None
    if not get_llm_gateway().has_api_key():
        logger.info("Skipping Context Forge ADK agent: LLM API key is not configured")
        return None

    try:
        from contextd_adk.agent import AgentRunner
        from contextd_adk.agent.config import RunnerConfig
        from contextd_adk.core.container import Container, ContainerConfig

        runner = AgentRunner(
            container=Container(ContainerConfig(enable_memory=False, enable_session=False)),
            config=RunnerConfig(persist_state=False),
        )
        agent = create_forge_agent()
        run_context = create_glm_run_context(
            organization_id=organization_id,
            collection_id=None,
            max_turns=1,
            feature="context_forge",
            collection_readable_id=collection_readable_id,
            provider=provider,
        )
        message = build_forge_agent_user_message(
            provider=provider,
            source_name=source_name,
            mapping_schema=mapping_schema,
            max_objects=settings.CONTEXT_FORGE_AI_MAX_OBJECTS,
            max_columns_per_object=settings.CONTEXT_FORGE_AI_MAX_COLUMNS_PER_OBJECT,
        )
        response = await runner.run(
            agent,
            message,
            context=run_context,
            metadata={
                "organization_id": str(organization_id),
                "collection_readable_id": collection_readable_id,
                "provider": provider,
                "feature": "context_forge",
            },
        )
        structured = getattr(response, "structured_output", None)
        if structured is None and getattr(response, "content", None):
            structured = ForgeAgentResponse.model_validate(
                json.loads(response.content or "{}")
            )
        if structured is None:
            return None
        if isinstance(structured, ForgeAgentResponse):
            return structured
        return ForgeAgentResponse.model_validate(
            structured.model_dump() if hasattr(structured, "model_dump") else structured
        )
    except Exception as exc:
        logger.warning("Context Forge ADK agent failed: %s", exc)
        return None
