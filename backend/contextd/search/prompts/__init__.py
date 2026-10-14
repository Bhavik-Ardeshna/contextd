"""System prompts for search operations."""

from .generate_answer import GENERATE_ANSWER_SYSTEM_PROMPT
from .query_expansion import QUERY_EXPANSION_SYSTEM_PROMPT
from .query_interpretation import QUERY_INTERPRETATION_SYSTEM_PROMPT
from .reranking import RERANKING_SYSTEM_PROMPT

__all__ = [
    "GENERATE_ANSWER_SYSTEM_PROMPT",
    "QUERY_EXPANSION_SYSTEM_PROMPT",
    "QUERY_INTERPRETATION_SYSTEM_PROMPT",
    "RERANKING_SYSTEM_PROMPT",
]
