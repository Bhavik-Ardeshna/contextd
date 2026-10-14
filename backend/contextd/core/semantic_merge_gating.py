"""Pure helpers for semantic-merge connector allowlist (no Settings / env required)."""

from __future__ import annotations


def structured_connector_set(csv_value: str | None) -> set[str]:
    """Parse SEMANTIC_MERGE_STRUCTURED_CONNECTORS into a set of lowercased short names."""
    raw = (csv_value or "").strip()
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def is_semantic_merge_allowed_for_connector(
    short_name: str,
    *,
    merge_enabled: bool,
    structured_connectors_csv: str | None,
) -> bool:
    """True when semantic merge is enabled and connector is not structured-only."""
    if not merge_enabled:
        return False
    return short_name.lower() not in structured_connector_set(structured_connectors_csv)


def use_glm_agents_for_graph_chat(
    connection_short_names: list[str],
    structured_connectors_csv: str | None,
) -> bool:
    """Whether graph chat should run GLM (R/A/P agents) vs deterministic seed search + traversal only.

    Enables agents when the collection has **at least one** structured connector listed in
    ``structured_connectors_csv`` — the A-Agent can still write useful Cypher against the
    structured slice of a mixed collection (Cypher can scope via node_type / source_type).
    Returns False only when every connection is an unstructured source (e.g. gmail+notion),
    in which case the graph contains no queryable tabular data and the deterministic
    graph-search path is the right choice. Empty connection list keeps agents enabled
    (legacy default for new collections).
    """
    structured = structured_connector_set(structured_connectors_csv)
    cleaned = [s.strip().lower() for s in connection_short_names if s and s.strip()]
    if not cleaned:
        return True
    return any(s in structured for s in cleaned)
