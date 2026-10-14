from abc import ABC, abstractmethod
from typing import Any, Callable, List, TypeVar

from contextd.api.context import ApiContext
from contextd.search.context import SearchContext
from contextd.search.providers._base import BaseProvider

T = TypeVar("T")


class SearchOperation(ABC):
    """Base class for all search operations."""

    @abstractmethod
    def depends_on(self) -> List[str]:
        """List of operation names this operation depends on."""
        pass

    @abstractmethod
    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Execute the operation."""
        pass

    def _report_metrics(self, state: dict[str, Any], **metrics: Any) -> None:
        """Report operation-specific metrics for analytics tracking.

        This helper allows operations to report custom metrics that will be
        automatically collected by the orchestrator and sent to PostHog.

        Args:
            state: Shared state dictionary
            **metrics: Key-value pairs of metrics to report

        Example:
            self._report_metrics(state,
                input_count=1000,
                output_count=25,
                search_method="hybrid"
            )
        """
        op_name = self.__class__.__name__
        if "_operation_metrics" not in state:
            state["_operation_metrics"] = {}
        if op_name not in state["_operation_metrics"]:
            state["_operation_metrics"][op_name] = {}

        state["_operation_metrics"][op_name].update(metrics)

    async def _execute_with_provider_fallback(
        self,
        providers: List[BaseProvider],
        operation_call: Callable[[BaseProvider], Any],
        operation_name: str,
        ctx: ApiContext,
        state: dict[str, Any] | None = None,
    ) -> T:
        """Execute an operation with provider fallback on retryable errors.

        This is a generic fallback handler that tries providers in preference order.
        If a provider fails with a retryable error (429, 5xx), it tries the next one.
        Automatically tracks which provider succeeded for analytics.

        Args:
            providers: List of providers to try in order
            operation_call: Async callable that takes a provider and returns the result
            operation_name: Name of the operation for logging
            ctx: API context for logging
            state: Optional state dict to track provider usage for analytics

        Returns:
            Result from the provider call

        Raises:
            RuntimeError: If all providers fail with retryable errors
            Exception: If a non-retryable error occurs
        """
        last_error = None
        for i, provider in enumerate(providers):
            try:
                ctx.logger.debug(
                    f"[{operation_name}] Attempting with provider {provider.__class__.__name__} "
                    f"({i + 1}/{len(providers)})"
                )
                result = await operation_call(provider)

                # Track successful provider for analytics
                if state is not None:
                    if "_provider_usage" not in state:
                        state["_provider_usage"] = {}
                    state["_provider_usage"][operation_name] = provider.__class__.__name__

                if i > 0:
                    ctx.logger.info(
                        f"[{operation_name}] ✓ Succeeded with fallback provider "
                        f"{provider.__class__.__name__}"
                    )
                return result
            except Exception as e:
                last_error = e
                if BaseProvider.is_retryable_error(e) and i < len(providers) - 1:
                    ctx.logger.error(
                        f"[{operation_name}] Provider {provider.__class__.__name__} failed "
                        f"with retryable error: {e}. Trying next provider...",
                        extra={
                            "operation": operation_name,
                            "provider": provider.__class__.__name__,
                            "error_type": type(e).__name__,
                            "fallback_available": True,
                        },
                    )
                    continue
                else:
                    # Non-retryable error or last provider - raise immediately
                    raise

        # All providers failed with retryable errors
        raise RuntimeError(
            f"All {len(providers)} providers failed for {operation_name}. Last error: {last_error}"
        )
