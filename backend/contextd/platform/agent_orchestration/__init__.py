"""Multi-Agent GLM (Graph Language Model) orchestration.

All chat queries use the non-deterministic path (R-Agent → A-Agent → Executor).
The deterministic path (Seed Search → PPR/MST) is only used for @search.
Path-agnostic synthesis via GraphContextFormatter.
"""

from contextd.platform.agent_orchestration.types import (
    GLMResult,
    NotebookState,
)

__all__ = [
    "run_glm",
    "NotebookState",
    "GLMResult",
]


def __getattr__(name: str):
    if name == "run_glm":
        from contextd.platform.agent_orchestration.orchestrator import run_glm

        return run_glm
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
