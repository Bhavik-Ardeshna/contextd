"""ContextD ADK BaseAgent definitions for GLM runtime agents."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from contextd.platform.agent_orchestration.prompts import (
    A_AGENT_SYSTEM,
    R_AGENT_SYSTEM,
    get_p_agent_system_prompt,
)
from contextd.platform.agent_orchestration.prompts.forge import FORGE_AGENT_SYSTEM
from contextd.platform.agent_orchestration.types import (
    AAgentCodeOutput,
    ForgeAgentResponse,
    PAgentCodeOutput,
    RAgentResponse,
)

# GLM agents do not use long-term memory (no user_id in API context); disable to avoid MemoryIdentifierError.
_GLM_MEMORY_CONFIG: Any = None


def _default_agent_model(model: Optional[str]) -> str:
    """Return explicit model or the configured ContextD agent model."""
    if model:
        return model

    from contextd.platform.llm.gateway import configured_llm_model

    return configured_llm_model("agent_orchestration")


def _get_glm_memory_config() -> Any:
    global _GLM_MEMORY_CONFIG
    if _GLM_MEMORY_CONFIG is None:
        from contextd_adk.agent.config import AgentMemoryConfig
        _GLM_MEMORY_CONFIG = AgentMemoryConfig(
            search_memories=False,
            store_memories=False,
        )
    return _GLM_MEMORY_CONFIG  # type: ignore[return-value]


def create_r_agent(
    model: Optional[str] = None,
    temperature: float = 0.0,
    instructions: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Create the Reasoning agent (R-Agent). No tools; outputs RAgentResponse (final_answer or research_plan)."""
    from contextd_adk.agent import BaseAgent

    return BaseAgent(
        name="glm-r-agent",
        instructions=instructions if instructions is not None else R_AGENT_SYSTEM,
        description="Reasoning controller: reads Notebook and query, outputs FINAL_ANSWER or RESEARCH_PLAN",
        model=_default_agent_model(model),
        temperature=temperature,
        tools=[],
        output_schema=RAgentResponse,
        enable_json_mode=True,
        memory_config=_get_glm_memory_config(),
        **kwargs,
    )


def create_a_agent(
    model: Optional[str] = None,
    temperature: float = 0.0,
    instructions: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Create the Action agent (A-Agent). No tools; outputs AAgentCodeOutput (code string)."""
    from contextd_adk.agent import BaseAgent

    return BaseAgent(
        name="glm-a-agent",
        instructions=instructions if instructions is not None else A_AGENT_SYSTEM,
        description="Programmer: translates RESEARCH_PLAN into Python code using RetrieveNode, NodeInfo, run_cypher (Cypher only)",
        model=_default_agent_model(model),
        temperature=temperature,
        tools=[],
        output_schema=AAgentCodeOutput,
        enable_json_mode=True,
        memory_config=_get_glm_memory_config(),
        **kwargs,
    )


def create_p_agent(
    model: Optional[str] = None,
    temperature: float = 0.0,
    instructions: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Create the P-Agent (Python analysis agent). No tools; outputs PAgentCodeOutput (code string)."""
    from contextd_adk.agent import BaseAgent

    return BaseAgent(
        name="glm-p-agent",
        instructions=instructions if instructions is not None else get_p_agent_system_prompt(),
        description="Analysis agent: writes Python using df and predefined functions to summarise/plot Cypher results",
        model=_default_agent_model(model),
        temperature=temperature,
        tools=[],
        output_schema=PAgentCodeOutput,
        enable_json_mode=True,
        memory_config=_get_glm_memory_config(),
        **kwargs,
    )


def create_forge_agent(
    model: Optional[str] = None,
    temperature: float = 0.0,
    instructions: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Create the Context Forge schema agent."""
    from contextd_adk.agent import BaseAgent

    from contextd.platform.llm.gateway import configured_llm_model

    return BaseAgent(
        name="context-forge-schema-agent",
        instructions=instructions if instructions is not None else FORGE_AGENT_SYSTEM,
        description="Schema reasoning agent: proposes graph entities, relationships, and facts from database metadata",
        model=model or configured_llm_model("schema_extraction"),
        temperature=temperature,
        tools=[],
        output_schema=ForgeAgentResponse,
        enable_json_mode=True,
        memory_config=_get_glm_memory_config(),
        **kwargs,
    )


def create_glm_run_context(
    run_id: Optional[str] = None,
    organization_id: Optional[UUID] = None,
    collection_id: Optional[UUID] = None,
    max_turns: int = 5,
    **metadata: Any,
) -> Any:
    """Create a RunContext for GLM with organization_id and collection_id in metadata."""
    from contextd_adk.agent.types import generate_run_id
    from contextd_adk.agent.utils.context_utils import create_run_context

    meta = dict(metadata)
    if organization_id is not None:
        meta["organization_id"] = str(organization_id)
    if collection_id is not None:
        meta["collection_id"] = str(collection_id)
    return create_run_context(
        run_id=run_id or generate_run_id(),
        max_turns=max_turns,
        metadata=meta,
    )
