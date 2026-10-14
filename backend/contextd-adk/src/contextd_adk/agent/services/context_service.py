"""
Context Service - Handles context and state management for agents.

Extracted from AgentRunner to provide clean separation of concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contextd_adk.agent.interfaces.service_interface import IContextService
from contextd_adk.agent.persistence.state import (
    RunStateManager,
    get_global_state_manager,
)
from contextd_adk.agent.types import RunState, RunStatus
from contextd_adk.logging import get_logger

if TYPE_CHECKING:
    from contextd_adk.agent.base import BaseAgent
    from contextd_adk.agent.config import RunnerConfig
    from contextd_adk.agent.types import RunContext

logger = get_logger(__name__)


class ContextService(IContextService):
    """
    Service for context and state management.

    Handles creating, saving, and loading run state.
    """

    def __init__(
        self,
        state_manager: RunStateManager | None = None,
        config: RunnerConfig | None = None,
    ):
        """
        Initialize context service.

        Args:
            state_manager: Run state manager instance
            config: Runner configuration
        """
        self._state_manager = state_manager
        self._config = config

    @property
    def state_manager(self) -> RunStateManager:
        """Get state manager."""
        if self._state_manager is None:
            self._state_manager = get_global_state_manager()
        return self._state_manager

    async def create_run_state(
        self,
        agent: BaseAgent,
        context: RunContext,
    ) -> RunState:
        """
        Create initial run state.

        Args:
            agent: Agent to create state for
            context: Run context

        Returns:
            Initialized RunState
        """
        run_state = RunState(
            run_id=context.run_id,
            session_id=context.session_id,
            user_id=context.user_id,
            current_agent=agent.name,
            entry_agent=agent.name,
            agent_stack=[agent.name],
            max_turns=context.max_turns,
            trace_id=context.trace_id,
            status=RunStatus.RUNNING,
        )

        # Persist initial state
        if self._config and self._config.persist_state:
            await self.state_manager.save(run_state)

        return run_state

    async def save_run_state(self, state: RunState) -> None:
        """
        Save run state.

        Args:
            state: RunState to save
        """
        if self._config and self._config.persist_state:
            await self.state_manager.save(state)

    async def load_run_state(self, run_id: str) -> RunState | None:
        """
        Load run state.

        Args:
            run_id: Run ID to load

        Returns:
            RunState if found, None otherwise
        """
        return await self.state_manager.load(run_id)
