"""Graph context formatter for LLM consumption.

Converts graph traversal results into pre-formatted text optimized
for LLM context windows. Designed to be efficient and informative.

Supports two serialization modes:
- rule_based_flattening: sections by entity type and relationships
- eulerian_path: linear path NodeA -> Edge -> NodeB -> ... (or random walk fallback)
"""

import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from ._base import TraversalResult, TraversedEdge, TraversedNode

logger = logging.getLogger(__name__)


def _node_display_id(node_id: str) -> str:
    """Return a short, unique display id for an entity (e.g. persons.112, leads.105).
    Uses node_id so entities are distinguishable; avoids generic labels like 'persons' or 'leads'.
    """
    if not node_id:
        return node_id or ""
    s = node_id
    if s.startswith("public."):
        s = s[7:]
    s = s.replace(":", ".")
    return s or node_id


def _derive_table_entity_type(table_name: str) -> str:
    """Derive entity type from a table name.

    Looks up the DatabaseSchemaRegistry for LLM-inferred
    node types first, then falls back to CamelCase conversion.
    """
    try:
        from contextd.platform.configs.database.registry import (
            DatabaseSchemaRegistry,
        )
        # Try public.{table_name} key in registry
        table_key = f"public.{table_name}"
        schema_def = DatabaseSchemaRegistry.get_schema(
            "postgres", table_key
        )
        if schema_def and schema_def.table_metadata:
            node_type = (
                schema_def.table_metadata.default_graph_node_type
            )
            if node_type:
                return node_type
    except Exception:
        pass
    # Fallback: snake_case -> CamelCase + TableEntity
    parts = table_name.split("_")
    camel = "".join(p.capitalize() for p in parts if p)
    return f"{camel}TableEntity"


def _infer_type_from_name(name: Optional[str]) -> Optional[str]:
    """When node_type is Unknown, infer a display type from entity name (e.g. 'Task 1' -> Task)."""
    if not name or not isinstance(name, str):
        return None
    n = name.strip()
    if not n:
        return None
    n_lower = n.lower()
    if n_lower.startswith("task"):
        return "Task"
    if n_lower.startswith("project"):
        return "Project"
    if n_lower.startswith("workspace"):
        return "Workspace"
    if n_lower.startswith("space ") or n == "space":
        return "Space"
    if n_lower.startswith("subtask"):
        return "Subtask"
    return None


def _node_type_for_grouping(node: TraversedNode) -> str:
    """Return node_type to use for grouping/display. Derives from node_id when type is 'Public'; infers from name when Unknown."""
    try:
        t = getattr(node, "node_type", None) or "Unknown"
        node_id = getattr(node, "node_id", None) or ""
        if t == "Public" and node_id and isinstance(node_id, str) and node_id.startswith("public.") and ":" in node_id:
            table = node_id[7:].split(":")[0].strip()
            return _derive_table_entity_type(table)
        if t == "Unknown":
            name = getattr(node, "name", None)
            if not name:
                props = getattr(node, "properties", None)
                if isinstance(props, dict):
                    name = props.get("name")
            inferred = _infer_type_from_name(str(name) if name is not None else None)
            if inferred:
                return inferred
        return t
    except Exception:
        return "Unknown"


def _parse_properties(raw: Any) -> Dict[str, Any]:
    """Return a dict of properties; parse from JSON string if needed (Neo4j / notebook path)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _value_to_display_str(value: Any, max_len: int = 300) -> str:
    """Convert any value (dict, list, object) to a string for display. Avoids '[object]' / '[complex object]'."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        s = str(value)
        return s[:max_len] + ("..." if len(s) > max_len else "")
    if isinstance(value, dict):
        try:
            s = json.dumps(value, default=str, ensure_ascii=True)
        except Exception:
            s = str(value)
        return s[:max_len] + ("..." if len(s) > max_len else "")
    if isinstance(value, list):
        try:
            if all(isinstance(v, (str, int, float, bool)) for v in value):
                s = ", ".join(str(v) for v in value[:20])
                if len(value) > 20:
                    s += f", ... (+{len(value) - 20} more)"
            else:
                s = json.dumps(value, default=str, ensure_ascii=True)
        except Exception:
            s = str(value)
        return s[:max_len] + ("..." if len(s) > max_len else "")
    return str(value)[:max_len]


# Supported subgraph-to-text modes
SUBGRAPH_TEXT_MODE_RULE_BASED = "rule_based_flattening"
SUBGRAPH_TEXT_MODE_EULERIAN = "eulerian_path"


@dataclass
class FormattedContext:
    """Formatted graph context for LLM.

    Attributes:
        text: Pre-formatted text representation
        token_estimate: Rough token count estimate
        node_count: Number of nodes included
        edge_count: Number of edges included
        truncated: Whether context was truncated to fit limits
    """

    text: str
    token_estimate: int
    node_count: int
    edge_count: int
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "token_estimate": self.token_estimate,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "truncated": self.truncated,
        }


class GraphContextFormatter:
    """Formats graph traversal results for LLM context.

    Converts graph structure into readable text that LLMs can
    reason over effectively. Optimized for:
    - Clarity: Human-readable format
    - Efficiency: Minimal tokens while preserving information
    - Structure: Organized by entity type and relationships

    Output format:
    ```
    ## Knowledge Graph Context

    ### Entities

    **Task: Design homepage mockup** (AsanaTaskEntity)
    - Status: completed
    - Assignee: John Smith
    - Due: 2024-01-15

    ### Relationships

    - "Design homepage mockup" → ASSIGNED_TO → "John Smith"
    - "Design homepage mockup" → BELONGS_TO → "Website Redesign"
    ```
    """

    # Approximate tokens per character (conservative estimate)
    TOKENS_PER_CHAR = 0.3

    def __init__(
        self,
        max_tokens: int = 4000,
        include_properties: bool = True,
        property_allowlist: Optional[List[str]] = None,
        property_denylist: Optional[List[str]] = None,
        subgraph_text_mode: str = SUBGRAPH_TEXT_MODE_EULERIAN,
    ):
        """Initialize formatter.

        Args:
            max_tokens: Maximum tokens for formatted output
            include_properties: Whether to include node properties
            property_allowlist: Only include these properties (if set)
            property_denylist: Exclude these properties
            subgraph_text_mode: rule_based_flattening or eulerian_path
        """
        self.max_tokens = max_tokens
        self.include_properties = include_properties
        self.property_allowlist = set(property_allowlist) if property_allowlist else None
        self.property_denylist = set(property_denylist or [
            "entity_id", "node_id", "organization_id", "sync_id",
            "contextd_system_metadata", "textual_representation",
        ])
        self.subgraph_text_mode = (
            subgraph_text_mode
            if subgraph_text_mode in (SUBGRAPH_TEXT_MODE_RULE_BASED, SUBGRAPH_TEXT_MODE_EULERIAN)
            else SUBGRAPH_TEXT_MODE_EULERIAN
        )

    def _get_eulerian_path_string(
        self,
        traversal_result: TraversalResult,
        random_seed: Optional[int] = None,
    ) -> str:
        """Serialize edges as a single path: NodeA -> Edge1 -> NodeB -> Edge2 -> NodeC.

        Uses an Eulerian path when one exists (every edge exactly once);
        otherwise falls back to a random walk. Returns only the path string (no header).

        Args:
            traversal_result: Graph traversal result
            random_seed: Seed for random walk (reproducible in tests)

        Returns:
            Path string only
        """
        nodes = traversal_result.nodes
        edges = traversal_result.edges
        id_to_name = {n.node_id: _node_display_id(n.node_id) for n in nodes}

        if not nodes:
            return "(No nodes in subgraph.)"
        if not edges:
            names = [id_to_name.get(n.node_id, _node_display_id(n.node_id)) for n in nodes]
            return " -> ".join(names) if len(names) <= 1 else ", ".join(names)

        # Directed multigraph: from_id -> list of (to_id, rel_type); dedupe by (from, to) so each edge appears once
        adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        seen_edge: Set[Tuple[str, str]] = set()
        for e in edges:
            key = (e.from_node_id, e.to_node_id)
            if key in seen_edge:
                continue
            seen_edge.add(key)
            adj[e.from_node_id].append((e.to_node_id, e.relationship_type))

        out_deg = {nid: len(adj[nid]) for nid in adj}
        in_deg: Dict[str, int] = defaultdict(int)
        for _from_id, pairs in adj.items():
            for to_id, _ in pairs:
                in_deg[to_id] += 1
        all_nodes = set(out_deg.keys()) | set(in_deg.keys())
        diff = {nid: out_deg.get(nid, 0) - in_deg.get(nid, 0) for nid in all_nodes}

        # Eulerian path (directed): at most one +1, at most one -1, rest 0
        starts = [nid for nid, d in diff.items() if d == 1]
        ends = [nid for nid, d in diff.items() if d == -1]
        balanced = [nid for nid, d in diff.items() if d == 0]
        has_eulerian = (
            len(starts) <= 1
            and len(ends) <= 1
            and len(starts) + len(ends) + len(balanced) == len(all_nodes)
        )

        path_edges: List[Tuple[str, str, str]] = []
        if has_eulerian:
            start_id = (
                starts[0]
                if starts
                else next(
                    (nid for nid in all_nodes if out_deg.get(nid, 0) > 0),
                    next(iter(all_nodes)),
                )
            )
            # Hierholzer: DFS, when no outgoing pop and record edge in reverse; then reverse
            stack = [start_id]
            rev_path: List[Tuple[str, str, str]] = []
            while stack:
                u = stack[-1]
                if adj[u]:
                    v, rel = adj[u].pop()
                    rev_path.append((u, rel, v))
                    stack.append(v)
                else:
                    stack.pop()
            path_edges = list(reversed(rev_path))
        else:
            # Random walk fallback (each edge at most once); use copy so we pop edges
            if random_seed is not None:
                random.seed(random_seed)
            adj_copy: Dict[str, List[Tuple[str, str]]] = {
                nid: list(pairs) for nid, pairs in adj.items()
            }
            start_id = (
                traversal_result.start_node_ids[0]
                if traversal_result.start_node_ids and traversal_result.start_node_ids[0] in all_nodes
                else next(iter(all_nodes))
            )
            current = start_id
            max_steps = len(edges)
            for _ in range(max_steps):
                if current not in adj_copy or not adj_copy[current]:
                    break
                idx = random.randint(0, len(adj_copy[current]) - 1)
                v, rel = adj_copy[current].pop(idx)
                path_edges.append((current, rel, v))
                current = v
            # If disconnected, drain remaining edges from any node that still has outgoing
            while True:
                try:
                    nid = next(n for n in adj_copy if adj_copy[n])
                except StopIteration:
                    break
                current = nid
                while adj_copy.get(current):
                    v, rel = adj_copy[current].pop()
                    path_edges.append((current, rel, v))
                    current = v

        # Build path as node names only (no edge labels). New line when no edge
        # between previous node and current segment (disconnected components).
        line_parts: List[List[str]] = []
        current_line: List[str] = []
        for i, (from_id, _rel_type, to_id) in enumerate(path_edges):
            from_name = id_to_name.get(from_id, _node_display_id(from_id))
            to_name = id_to_name.get(to_id, _node_display_id(to_id))
            if i == 0:
                current_line = [from_name, to_name]
            elif from_id == path_edges[i - 1][2]:
                current_line.append(to_name)
            else:
                line_parts.append(" -> ".join(current_line))
                current_line = [from_name, to_name]
        if current_line:
            line_parts.append(" -> ".join(current_line))
        return "\n".join(line_parts)

    def _get_bundled_relationships_string(self, traversal_result: TraversalResult) -> str:
        """Format edges bundled by from-node: 'from_name → to1, to2, to3'. One line per source node."""
        if not traversal_result.edges or not traversal_result.nodes:
            if traversal_result.nodes and not traversal_result.edges:
                names = [_node_display_id(n.node_id) for n in traversal_result.nodes]
                return ", ".join(names)
            return "(No nodes in subgraph.)"
        id_to_name = {n.node_id: _node_display_id(n.node_id) for n in traversal_result.nodes}
        by_from: Dict[str, List[str]] = defaultdict(list)
        seen: Set[Tuple[str, str]] = set()
        for e in traversal_result.edges:
            key = (e.from_node_id, e.to_node_id)
            if key in seen:
                continue
            seen.add(key)
            to_name = id_to_name.get(e.to_node_id, _node_display_id(e.to_node_id))
            by_from[e.from_node_id].append(to_name)
        lines = []
        for from_id, to_names in sorted(by_from.items(), key=lambda x: id_to_name.get(x[0], x[0])):
            from_name = id_to_name.get(from_id, _node_display_id(from_id))
            lines.append(f"{from_name} → {', '.join(to_names)}")
        return "\n".join(lines)

    def format(
        self,
        traversal_result: TraversalResult,
        query: Optional[str] = None,
    ) -> FormattedContext:
        """Format traversal result for LLM context.

        Args:
            traversal_result: Graph traversal result
            query: Optional original query for context

        Returns:
            FormattedContext with pre-formatted text
        """
        sections = []

        # Header
        sections.append("## Knowledge Graph Context\n")

        if query:
            sections.append(f"*Query: {query}*\n")

        # Group nodes by type
        nodes_by_type = self._group_nodes_by_type(traversal_result.nodes)

        # Format entities section
        entities_section = self._format_entities(nodes_by_type)
        if entities_section:
            sections.append("### Entities\n")
            sections.append(entities_section)

        # Format relationships section (path or rule-based list)
        if self.subgraph_text_mode == SUBGRAPH_TEXT_MODE_EULERIAN:
            relationships_section = self._get_eulerian_path_string(traversal_result)
        else:
            relationships_section = self._format_relationships(
                traversal_result.edges,
                traversal_result.nodes,
            )
        if relationships_section:
            sections.append("\n### Relationships\n")
            sections.append(relationships_section)

        # Combine sections
        full_text = "\n".join(sections)

        # Truncate if needed
        truncated = False
        max_chars = int(self.max_tokens / self.TOKENS_PER_CHAR)

        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n\n[... truncated for context limit ...]"
            truncated = True

        token_estimate = int(len(full_text) * self.TOKENS_PER_CHAR)

        return FormattedContext(
            text=full_text,
            token_estimate=token_estimate,
            node_count=len(traversal_result.nodes),
            edge_count=len(traversal_result.edges),
            truncated=truncated,
        )

    def _group_nodes_by_type(
        self,
        nodes: List[TraversedNode],
    ) -> Dict[str, List[TraversedNode]]:
        """Group nodes by their type. Uses table from node_id when type would be 'Public' (e.g. persons, orders)."""
        grouped: Dict[str, List[TraversedNode]] = {}

        for node in nodes:
            node_type = _node_type_for_grouping(node)
            if node_type not in grouped:
                grouped[node_type] = []
            grouped[node_type].append(node)

        return grouped

    def _format_entities(
        self,
        nodes_by_type: Dict[str, List[TraversedNode]],
    ) -> str:
        """Format entities section."""
        parts = []

        for node_type, nodes in nodes_by_type.items():
            # Clean up type name for display
            display_type = self._clean_type_name(node_type)

            for node in nodes:
                # Entity header (use display id e.g. persons.112 so entities are distinguishable)
                name = _node_display_id(node.node_id)
                parts.append(f"\n**{name}** ({display_type})")

                # Properties
                if self.include_properties and node.properties:
                    props_text = self._format_properties(node.properties)
                    if props_text:
                        parts.append(props_text)

        return "\n".join(parts)

    def _format_properties(self, properties: Dict[str, Any]) -> str:
        """Format node properties as bullet list."""
        lines = []

        for key, value in properties.items():
            # Skip denied properties
            if key in self.property_denylist:
                continue

            # Only include allowed properties if allowlist is set
            if self.property_allowlist and key not in self.property_allowlist:
                continue

            # Skip empty values
            if value is None or value == "" or value == []:
                continue

            # Format value
            formatted_value = self._format_value(value)
            if formatted_value:
                # Clean up key name
                display_key = key.replace("_", " ").replace("ft ", "").title()
                lines.append(f"  - {display_key}: {formatted_value}")

        return "\n".join(lines)

    def _format_value(self, value: Any) -> str:
        """Format a property value for display."""
        if isinstance(value, str):
            # Truncate long strings
            if len(value) > 200:
                return value[:200] + "..."
            return value
        elif isinstance(value, bool):
            return "Yes" if value else "No"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, list):
            if len(value) == 0:
                return ""
            if len(value) <= 3 and all(isinstance(v, (str, int, float, bool)) for v in value):
                return ", ".join(str(v) for v in value)
            if len(value) <= 3:
                return ", ".join(_value_to_display_str(v, 80) for v in value)
            return _value_to_display_str(value, max_len=200)
        elif isinstance(value, dict):
            return _value_to_display_str(value, max_len=200)
        else:
            return _value_to_display_str(value, max_len=100)

    def _format_relationships(
        self,
        edges: List[TraversedEdge],
        nodes: List[TraversedNode],
    ) -> str:
        """Format relationships section."""
        if not edges:
            return ""

        # Build node ID to display id mapping (e.g. persons.112, leads.105)
        id_to_name = {n.node_id: _node_display_id(n.node_id) for n in nodes}

        lines = []
        for edge in edges:
            from_name = id_to_name.get(edge.from_node_id, _node_display_id(edge.from_node_id))
            to_name = id_to_name.get(edge.to_node_id, _node_display_id(edge.to_node_id))
            rel_type = edge.relationship_type.replace("_", " ").lower()

            lines.append(f'- "{from_name}" → {rel_type} → "{to_name}"')

        return "\n".join(lines)

    def _clean_type_name(self, type_name: str) -> str:
        """Clean up entity type name for display."""
        # Remove common suffixes
        name = type_name
        for suffix in ["Entity", "Node", "Type"]:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[:-len(suffix)]

        # Convert CamelCase to spaces
        result = []
        for char in name:
            if char.isupper() and result:
                result.append(" ")
            result.append(char)

        return "".join(result)

    def _toon_safe_value(self, value: Any) -> Any:
        """Return a TOON-safe primitive (str, int, float, bool) for key amortization.

        Converts dict/list/object to string so we never show '[object]' or '[complex object]'.
        """
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and len(value) > 300:
                return value[:300] + "..."
            return value
        if isinstance(value, list):
            if not value:
                return ""
            if len(value) <= 5 and all(isinstance(v, (str, int, float, bool)) for v in value):
                return ",".join(str(v) for v in value)
            return _value_to_display_str(value, max_len=200)
        if isinstance(value, dict):
            return _value_to_display_str(value, max_len=200)
        return _value_to_display_str(value, max_len=200)

    def format_for_chat_hybrid_toon(
        self,
        traversal_result: TraversalResult,
        query: str,
        search_results: Optional[List[Dict]] = None,
    ) -> str:
        """Format context as hybrid text with TOON tables only for uniform tabular blocks.

        - Overview (query, counts): plain text
        - Most relevant entities: single TOON table (keys written once)
        - Detailed entities: one TOON table per entity type (keys written once per type)
        - Relationships: plain path string

        Ensures key amortization: no repeated property keys per record.
        """
        try:
            from py_toon_format import encode as toon_encode
        except ImportError:
            return self.format_for_chat(
                traversal_result=traversal_result,
                query=query,
                search_results=search_results,
            )

        sections: List[str] = []
        nodes = traversal_result.nodes or []
        edges = traversal_result.edges or []

        # Overview: plain text (no TOON); use table-derived type so we show Persons, Orders, etc., not "Public"
        type_counts: Dict[str, int] = {}
        for node in nodes:
            t = self._clean_type_name(_node_type_for_grouping(node))
            type_counts[t] = type_counts.get(t, 0) + 1
        rel_counts: Dict[str, int] = {}
        for edge in edges:
            rel_type = edge.relationship_type.replace("_", " ").title()
            rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1

        sections.append("## DATA OVERVIEW")
        sections.append(f"Query: {query}")
        if type_counts:
            sections.append("Entity types: " + ", ".join(f"{t}: {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])))
        if rel_counts:
            sections.append("Relationship types: " + ", ".join(f"{t}: {c}" for t, c in sorted(rel_counts.items(), key=lambda x: -x[1])))
        sections.append("")

        # Most relevant entities: single TOON table (uniform structure)
        if search_results:
            most_relevant: List[Dict[str, Any]] = []
            for result in search_results[:10]:
                payload = result.get("payload", {})
                desc = payload.get("description") or payload.get("notes")
                desc_str = (str(desc)[:200] + "...") if desc and len(str(desc)) > 200 else (str(desc) if desc else "")
                most_relevant.append({
                    "name": _node_display_id(result.get("node_id", "")),
                    "type": self._clean_type_name(result.get("node_type", "Unknown")),
                    "score": round(float(result.get("score", 0)), 2),
                    "status": str(payload.get("status") or ""),
                    "assignee": str(payload.get("assignee") or ""),
                    "due_date": str(payload.get("due_date", "")) if payload.get("due_date") else "",
                    "priority": str(payload.get("priority") or ""),
                    "description": desc_str,
                })
            if most_relevant:
                sections.append("## MOST RELEVANT ENTITIES (by search relevance)")
                sections.append(toon_encode(most_relevant))
                sections.append("")

        # Detailed entities: one TOON table per type with actual property data (persons, orders, leads, products, support_tickets)
        nodes_by_type = self._group_nodes_by_type(nodes)
        # Preferred keys to show first when present for all entity types (persons, orders, leads, products, support_tickets)
        preferred_keys = (
            "name", "first_name", "last_name", "primary_email", "email", "name_field",
            "subject", "description", "title", "status", "priority", "category",
            "city", "country", "region", "primary_phone", "language", "source_type",
            "total", "subtotal", "currency", "tax", "person_id", "product_id",
            "created_at_field", "updated_at_field", "closed_at", "sentiment_score",
            "utm_source", "utm_medium", "utm_campaign", "source",
        )
        if nodes_by_type:
            sections.append("## DETAILED ENTITY DATA")
            for node_type, nodes in nodes_by_type.items():
                display_type = self._clean_type_name(node_type)
                prop_keys_set: Set[str] = set()
                for node in nodes[:15]:
                    props = _parse_properties(node.properties)
                    if self.include_properties and props:
                        for key in props:
                            if key in self.property_denylist:
                                continue
                            if key.startswith("id_") or key.startswith("node_"):
                                continue
                            if self.property_allowlist and key not in self.property_allowlist:
                                continue
                            prop_keys_set.add(key)
                # Order: name (id), then preferred keys that exist, then rest sorted
                ordered = ["name"] + [k for k in preferred_keys if k in prop_keys_set and k != "name"]
                ordered += sorted(prop_keys_set - set(ordered))
                all_keys = ordered
                rows: List[Dict[str, Any]] = []
                for node in nodes[:15]:
                    props = _parse_properties(node.properties)
                    row: Dict[str, Any] = {}
                    row["name"] = _node_display_id(node.node_id)
                    for key in all_keys:
                        if key == "name":
                            continue
                        value = props.get(key) if props else None
                        row[key] = self._toon_safe_value(value)
                    rows.append(row)
                if rows:
                    sections.append(f"### {display_type} ({len(rows)} entities)")
                    sections.append(toon_encode(rows))
                    sections.append("")

        # Relationships: bundled by from-node (same as deterministic path; no duplicate edges)
        if edges:
            sections.append("## RELATIONSHIPS & CONNECTIONS")
            sections.append(self._get_bundled_relationships_string(traversal_result))
            sections.append("")

        full_text = "\n".join(sections)
        max_chars = int(self.max_tokens / self.TOKENS_PER_CHAR)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n\n[... context truncated for token limit ...]"
        return full_text

    def format_for_chat(
        self,
        traversal_result: TraversalResult,
        query: str,
        search_results: Optional[List[Dict]] = None,
    ) -> str:
        """Format context specifically for chat/conversation.

        Combines search results with graph context for comprehensive
        LLM context in conversational scenarios. Optimized for insight generation.

        Args:
            traversal_result: Graph traversal result
            query: User's query
            search_results: Optional search results to include

        Returns:
            Formatted text for chat context
        """
        sections = []

        # Data overview
        sections.append("## DATA OVERVIEW\n")

        # Analyze entity types (use table-derived type so we show Persons, Orders, etc., not "Public")
        type_counts: Dict[str, int] = {}
        for node in traversal_result.nodes:
            t = self._clean_type_name(_node_type_for_grouping(node))
            type_counts[t] = type_counts.get(t, 0) + 1

        if type_counts:
            sections.append("### Entity Types Found:")
            for node_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                sections.append(f"- {node_type}: {count}")
            sections.append("")

        # Analyze relationship types
        rel_counts: Dict[str, int] = {}
        for edge in traversal_result.edges:
            rel_type = edge.relationship_type.replace("_", " ").title()
            rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1

        if rel_counts:
            sections.append("### Relationship Types:")
            for rel_type, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
                sections.append(f"- {rel_type}: {count}")
            sections.append("")

        # Most relevant entities (from search)
        if search_results:
            sections.append("## MOST RELEVANT ENTITIES (by search relevance)\n")
            for i, result in enumerate(search_results[:10], 1):
                name = _node_display_id(result.get("node_id", "")) or f"Entity {i}"
                score = result.get("score", 0)
                node_type = self._clean_type_name(result.get("node_type", "Unknown"))

                # Get additional details from payload
                payload = result.get("payload", {})
                status = payload.get("status")
                assignee = payload.get("assignee")
                due_date = payload.get("due_date")
                priority = payload.get("priority")

                sections.append(f"### {i}. {name}")
                sections.append(f"   Type: {node_type} | Relevance: {score:.2f}")

                # Add key attributes inline
                details = []
                if status:
                    details.append(f"Status: {status}")
                if assignee:
                    details.append(f"Assignee: {assignee}")
                if priority:
                    details.append(f"Priority: {priority}")
                if due_date:
                    details.append(f"Due: {due_date}")

                if details:
                    sections.append(f"   {' | '.join(details)}")

                # Add description if available
                description = payload.get("description") or payload.get("notes")
                if description and len(str(description)) > 10:
                    desc_text = str(description)[:200]
                    if len(str(description)) > 200:
                        desc_text += "..."
                    sections.append(f"   Description: {desc_text}")

                sections.append("")

        # Detailed entity information
        sections.append("## DETAILED ENTITY DATA\n")

        # Group and format entities
        nodes_by_type = self._group_nodes_by_type(traversal_result.nodes)

        for node_type, nodes in nodes_by_type.items():
            display_type = self._clean_type_name(node_type)
            sections.append(f"### {display_type} ({len(nodes)} entities)\n")

            for node in nodes[:15]:  # Limit per type
                name = _node_display_id(node.node_id)
                sections.append(f"**{name}**")
                props = _parse_properties(node.properties)
                if self.include_properties and props:
                    props_text = self._format_properties(props)
                    if props_text:
                        sections.append(props_text)
                sections.append("")

        # Relationship details (bundled by from-node: "from → to1, to2, ...")
        if traversal_result.edges:
            sections.append("## RELATIONSHIPS & CONNECTIONS\n")
            sections.append("The following connections exist between entities:\n")
            sections.append(self._get_bundled_relationships_string(traversal_result))

        # Combine all sections
        full_text = "\n".join(sections)

        # Truncate if needed
        max_chars = int(self.max_tokens / self.TOKENS_PER_CHAR)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n\n[... context truncated for token limit ...]"

        return full_text

    def format_for_chat_as_dict(
        self,
        traversal_result: TraversalResult,
        query: str,
        search_results: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Return the same context as format_for_chat as a dict for TOON encoding.

        Structure is optimized for TOON (uniform arrays, primitive values).
        """
        type_counts = {}
        for node in traversal_result.nodes:
            t = self._clean_type_name(_node_type_for_grouping(node))
            type_counts[t] = type_counts.get(t, 0) + 1
        rel_counts: Dict[str, int] = {}
        for edge in traversal_result.edges:
            rel_type = edge.relationship_type.replace("_", " ").title()
            rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1

        most_relevant: List[Dict[str, Any]] = []
        if search_results:
            for result in search_results[:10]:
                payload = result.get("payload", {})
                desc = payload.get("description") or payload.get("notes")
                desc_str = str(desc)[:200] if desc and len(str(desc)) > 10 else ""
                if desc and len(str(desc)) > 200:
                    desc_str += "..."
                most_relevant.append({
                    "name": _node_display_id(result.get("node_id", "")),
                    "type": self._clean_type_name(result.get("node_type", "Unknown")),
                    "score": round(float(result.get("score", 0)), 2),
                    "status": payload.get("status") or "",
                    "assignee": payload.get("assignee") or "",
                    "due_date": str(payload.get("due_date", "")) if payload.get("due_date") else "",
                    "priority": payload.get("priority") or "",
                    "description": desc_str,
                })

        detailed: Dict[str, List[Dict[str, Any]]] = {}
        nodes_by_type = self._group_nodes_by_type(traversal_result.nodes)
        for node_type, nodes in nodes_by_type.items():
            display_type = self._clean_type_name(node_type)
            rows = []
            for node in nodes[:15]:
                name = _node_display_id(node.node_id)
                props = {}
                node_props = _parse_properties(node.properties)
                if self.include_properties and node_props:
                    for key, value in node_props.items():
                        if key in self.property_denylist:
                            continue
                        if self.property_allowlist and key not in self.property_allowlist:
                            continue
                        if value is None or value == "" or value == []:
                            continue
                        props[key] = value
                rows.append({"name": name, "properties": props})
            detailed[display_type] = rows

        relationships_str = self._get_bundled_relationships_string(traversal_result) if traversal_result.edges else ""

        return {
            "query": query,
            "entity_types": type_counts,
            "relationship_types": rel_counts,
            "most_relevant_entities": most_relevant,
            "detailed_entities": detailed,
            "relationships": relationships_str,
        }
