"""Response assembly helpers for graph chat endpoints."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from contextd.api.v1.endpoints.graph_chat_schemas import (
    EntityReference,
    Subgraph,
    SubgraphEdge,
    SubgraphNode,
)
from contextd.platform.graph.traversal.formatter import (
    _infer_type_from_name,
    _node_type_for_grouping,
)


def _chart_value_to_native(value: Any) -> Any:
    """Convert numpy/pandas scalars to native Python for JSON serialization."""
    if value is None:
        return None
    try:
        import numpy as np

        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass
    if isinstance(value, (int, float, str, bool)):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    return str(value)


def _sanitize_chart_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure chart data is JSON-serializable."""
    return [
        {str(key): _chart_value_to_native(value) for key, value in row.items()}
        for row in data
        if isinstance(row, dict)
    ]


def _chart_data_snippet_for_llm_prompt(charts: List[Dict[str, Any]]) -> str:
    """One JSON object per chart so the final model can cite series totals and breakdowns."""
    lines: List[str] = []
    for chart in charts:
        if not isinstance(chart, dict) or chart.get("type") != "chart":
            continue
        title = chart.get("title") or "Chart"
        chart_type = chart.get("chart_type") or "bar"
        raw_data = chart.get("data")
        data = _sanitize_chart_data(raw_data) if isinstance(raw_data, list) else []
        lines.append(
            json.dumps(
                {"title": title, "chart_type": chart_type, "data": data},
                default=str,
            )
        )
    return "\n".join(lines)


def _extract_source_from_entity_type(entity_type: str) -> str:
    """Extract source name from entity type (e.g., AsanaTaskEntity -> asana)."""
    if not entity_type:
        return ""

    name = entity_type
    for suffix in ["Entity", "Node", "Type"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]

    source_mappings = {
        "asana": ["asana"],
        "jira": ["jira"],
        "github": ["github", "git"],
        "gitlab": ["gitlab"],
        "slack": ["slack"],
        "notion": ["notion"],
        "confluence": ["confluence"],
        "google": ["google", "gdrive", "gmail", "gcalendar"],
        "microsoft": ["outlook", "onedrive", "sharepoint", "teams"],
    }

    name_lower = name.lower()
    for source, patterns in source_mappings.items():
        for pattern in patterns:
            if pattern in name_lower:
                return source

    return name_lower


def _build_entity_references(
    search_results: List[Dict[str, Any]],
    traversal_nodes: List[Any],
    organization_id: Optional[Any] = None,
) -> List[EntityReference]:
    """Build standardized entity references from search results and traversal."""
    references = []
    seen_ids = set()
    org_id_str = str(organization_id) if organization_id is not None else None

    for result in search_results:
        entity_id = result.get("entity_id") or result.get("node_id", "")
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)

        payload = result.get("payload", {})
        entity_type = result.get("node_type", "Unknown")
        if entity_type == "Unknown":
            raw_name = result.get("name") or payload.get("name")
            entity_type = (
                _infer_type_from_name(str(raw_name) if raw_name is not None else None)
                or entity_type
            )

        references.append(
            EntityReference(
                entity_id=entity_id,
                node_id=result.get("node_id", entity_id),
                organization_id=result.get("organization_id")
                if isinstance(result.get("organization_id"), str)
                else org_id_str,
                name=result.get("name") or payload.get("name") or entity_id,
                entity_type=entity_type,
                source=_extract_source_from_entity_type(entity_type),
                url=payload.get("url") or payload.get("permalink_url") or payload.get("html_url"),
                score=result.get("score"),
                properties={
                    key: value
                    for key, value in payload.items()
                    if key
                    in ["status", "assignee", "due_date", "priority", "description", "created_at"]
                    and value is not None
                },
            )
        )

    for node in traversal_nodes:
        node_id = node.node_id if hasattr(node, "node_id") else node.get("node_id", "")
        if not node_id or node_id in seen_ids:
            continue
        if node_id.startswith("row_"):
            continue
        seen_ids.add(node_id)

        raw_type = (
            node.node_type if hasattr(node, "node_type") else node.get("node_type", "Unknown")
        )
        try:
            if not isinstance(node, dict) and hasattr(node, "node_id"):
                node_type = _node_type_for_grouping(node)
            else:
                name_val = node.name if hasattr(node, "name") else node.get("name")
                props = (
                    node.properties if hasattr(node, "properties") else node.get("properties") or {}
                )
                name_val = name_val or (props.get("name") if isinstance(props, dict) else None)
                node_type = (
                    raw_type
                    if raw_type != "Unknown"
                    else (
                        _infer_type_from_name(str(name_val) if name_val is not None else None)
                        or raw_type
                    )
                )
        except Exception:
            node_type = raw_type if raw_type != "Unknown" else "Unknown"
        properties = node.properties if hasattr(node, "properties") else node.get("properties", {})
        name = node.name if hasattr(node, "name") else node.get("name")

        references.append(
            EntityReference(
                entity_id=node_id,
                node_id=node_id,
                organization_id=org_id_str,
                name=name or properties.get("name") or node_id,
                entity_type=node_type,
                source=_extract_source_from_entity_type(node_type),
                url=properties.get("url") or properties.get("permalink_url"),
                score=None,
                properties={
                    key: value
                    for key, value in properties.items()
                    if key in ["status", "assignee", "due_date", "priority"] and value is not None
                },
            )
        )

    return references


def _build_subgraph(
    traversal_result: Any,
    search_results: List[Dict[str, Any]],
) -> Subgraph:
    """Build subgraph for UI visualization."""
    primary_node_ids = {result.get("node_id") for result in search_results if result.get("node_id")}

    nodes = []
    for node in traversal_result.nodes:
        node_id = node.node_id if hasattr(node, "node_id") else node.get("node_id", "")
        raw_type = node.node_type if hasattr(node, "node_type") else node.get("node_type", "")
        try:
            if not isinstance(node, dict) and hasattr(node, "node_id"):
                node_type = _node_type_for_grouping(node)
            else:
                name_val = node.name if hasattr(node, "name") else node.get("name", "")
                props = (
                    node.properties if hasattr(node, "properties") else node.get("properties") or {}
                )
                name_val = name_val or (props.get("name") if isinstance(props, dict) else None)
                node_type = (
                    raw_type
                    or _infer_type_from_name(str(name_val) if name_val is not None else None)
                    or "Unknown"
                )
        except Exception:
            node_type = raw_type or "Unknown"
        name = node.name if hasattr(node, "name") else node.get("name", "")
        depth = node.depth if hasattr(node, "depth") else node.get("depth", 0)
        properties = node.properties if hasattr(node, "properties") else node.get("properties", {})
        props_source = properties if isinstance(properties, dict) else {}

        nodes.append(
            SubgraphNode(
                node_id=node_id,
                node_type=node_type,
                name=name or props_source.get("name") or node_id,
                source=_extract_source_from_entity_type(node_type),
                depth=depth,
                properties={
                    key: value
                    for key, value in props_source.items()
                    if _keep_node_property(key, value)
                },
                is_primary=node_id in primary_node_ids,
            )
        )

    edges = []
    for edge in traversal_result.edges:
        from_id = (
            edge.from_node_id if hasattr(edge, "from_node_id") else edge.get("from_node_id", "")
        )
        to_id = edge.to_node_id if hasattr(edge, "to_node_id") else edge.get("to_node_id", "")
        rel_type = (
            edge.relationship_type
            if hasattr(edge, "relationship_type")
            else edge.get("relationship_type", "")
        )
        edges.append(
            SubgraphEdge(
                from_node_id=from_id,
                to_node_id=to_id,
                relationship_type=rel_type,
                label=rel_type.replace("_", " ").lower(),
            )
        )

    return Subgraph(
        nodes=nodes,
        edges=edges,
        center_node_ids=list(primary_node_ids),
    )


def _keep_node_property(key: str, value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(key, str) and key.startswith("_"):
        return False
    try:
        if isinstance(value, str) and len(value) > 2000:
            return False
        if isinstance(value, (list, dict)) and len(json.dumps(value, default=str)) > 2000:
            return False
    except Exception:
        pass
    return True
