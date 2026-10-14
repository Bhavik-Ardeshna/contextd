"""Tests for the parameterized cohort agent factory."""

from __future__ import annotations

import sys
import types


class FakeBaseAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAgentMemoryConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_create_cohort_agent_builds_each_stage(monkeypatch):
    agent_mod = types.ModuleType("contextd_adk.agent")
    agent_mod.__path__ = []
    agent_mod.BaseAgent = FakeBaseAgent

    config_mod = types.ModuleType("contextd_adk.agent.config")
    config_mod.AgentMemoryConfig = FakeAgentMemoryConfig

    monkeypatch.setitem(sys.modules, "contextd_adk.agent", agent_mod)
    monkeypatch.setitem(sys.modules, "contextd_adk.agent.config", config_mod)

    from contextd.platform.agent_orchestration.cohort.agents import (
        COHORT_AGENT_SPECS,
        CohortAgentStage,
        create_cohort_agent,
    )

    for stage in CohortAgentStage:
        agent = create_cohort_agent(
            stage,
            model="test-agent-model",
            temperature=0.25,
            instructions=f"{stage.value} instructions",
        )
        spec = COHORT_AGENT_SPECS[stage]

        assert agent.kwargs["name"] == spec.name
        assert agent.kwargs["description"] == spec.description
        assert agent.kwargs["output_schema"] is spec.output_schema
        assert agent.kwargs["instructions"] == f"{stage.value} instructions"
        assert agent.kwargs["model"] == "test-agent-model"
        assert agent.kwargs["temperature"] == 0.25
        assert agent.kwargs["tools"] == []
        assert agent.kwargs["enable_json_mode"] is True
        assert agent.kwargs["memory_config"].kwargs == {
            "search_memories": False,
            "store_memories": False,
        }
