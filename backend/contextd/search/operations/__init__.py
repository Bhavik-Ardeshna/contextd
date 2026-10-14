# Rebuild SearchContext so all forward refs (EventEmitter, QueryExpansion, etc.) resolve.
# Required when SearchContext is built outside the search factory (e.g. orchestrator, graph_chat).
from contextd.search.context import SearchContext
from contextd.search.emitter import EventEmitter

from .embed_query import EmbedQuery
from .federated_search import FederatedSearch
from .generate_answer import GenerateAnswer
from .graph_search import GraphSearch, GraphSearchRequest, GraphSearchResponse
from .query_expansion import QueryExpansion
from .query_interpretation import QueryInterpretation
from .reranking import Reranking
from .retrieval import Retrieval
from .temporal_relevance import TemporalRelevance
from .user_filter import UserFilter

SearchContext.model_rebuild(
    _types_namespace={
        "EventEmitter": EventEmitter,
        "EmbedQuery": EmbedQuery,
        "FederatedSearch": FederatedSearch,
        "GenerateAnswer": GenerateAnswer,
        "QueryExpansion": QueryExpansion,
        "QueryInterpretation": QueryInterpretation,
        "Reranking": Reranking,
        "Retrieval": Retrieval,
        "TemporalRelevance": TemporalRelevance,
        "UserFilter": UserFilter,
    }
)

__all__ = [
    "EmbedQuery",
    "FederatedSearch",
    "GenerateAnswer",
    "GraphSearch",
    "GraphSearchRequest",
    "GraphSearchResponse",
    "QueryExpansion",
    "QueryInterpretation",
    "Reranking",
    "Retrieval",
    "TemporalRelevance",
    "UserFilter",
]
