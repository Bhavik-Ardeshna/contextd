"""Shared prompt vocabulary, Cypher contract, and message helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

# Hardcoded default vocabulary – only these entities are used (no dynamic fetch from graph)
DEFAULT_NODE_TYPES: List[str] = [
    "ProductsTableEntity",
    "OrdersTableEntity",
    "PersonNode",
    "LeadsTableEntity",
    "SupportTicketsTableEntity",
]
DEFAULT_REL_TYPES: List[str] = ["RELATED_TO"]

# Template for dynamic vocabulary (node_type and relationship_type from graph)
VALID_VOCABULARY_TEMPLATE = """
**Valid Vocabulary (STRICT ENFORCEMENT):**
You MUST ONLY use the following values for node_type and relationship_type. If a user asks for something not in this list, find the closest semantic match.

- **Valid node_type values:** {node_types_list}
- **Valid relationship_type values:** {rel_types_list}
"""


# When using pruned schema from RAG, do not specify relationship types in Cypher
CYPHER_ANONYMOUS_RELATIONSHIPS_RULE = """
**Anonymous relationships (when using pruned schema):** Do NOT specify relationship types in Cypher. Use anonymous relationships only, e.g. (m:GmailMessage)-[]-(t:GmailThread). Rely on the node type explanations above to understand how entities logically connect.
"""


def build_pruned_schema_vocabulary(pruned_schema: str) -> str:
    """Build vocabulary section from RAG-pruned schema and anonymous-relationship rule."""
    if not pruned_schema or not pruned_schema.strip():
        return ""
    return (
        "**Pruned schema (relevant node types for this query):**\n"
        + pruned_schema.strip()
        + "\n\n"
        + "**How to use this in Cypher:** The `Node:` value is the exact `n.node_type` value you may filter on in Cypher. "
        + "The `Properties:` values are keys inside the JSON string `n.properties`, so access them with "
        + "`apoc.convert.fromJsonMap(n.properties).<property_name>`."
        + "\n"
        + CYPHER_ANONYMOUS_RELATIONSHIPS_RULE
    )


def build_valid_vocabulary_section(
    node_types: List[str],
    rel_types: List[str],
    schema_narrative: Optional[str] = None,
) -> str:
    """Format VALID_VOCABULARY with current graph types and optional schema narrative."""
    node_list = ", ".join(repr(t) for t in node_types) if node_types else "(none – run MATCH (n:GraphNode) RETURN DISTINCT n.node_type)"
    rel_list = ", ".join(repr(t) for t in rel_types) if rel_types else "(none – run MATCH ()-[r:RELATES_TO]->() RETURN DISTINCT r.relationship_type)"
    vocab = VALID_VOCABULARY_TEMPLATE.format(
        node_types_list=node_list,
        rel_types_list=rel_list,
    )
    if schema_narrative and schema_narrative.strip():
        vocab = (
            "**Schema (how things connect and what they mean):**\n"
            + schema_narrative.strip()
            + "\n\n"
            + vocab
        )
    return vocab

# Graph Data Contract: Neo4j generic schema. Used in R-Agent and A-Agent Cypher instructions.
# Base contract (no entity-specific property list); dynamic shapes injected via build_cypher_graph_contract.
CYPHER_GRAPH_CONTRACT_BASE = """
**Graph schema (Neo4j – Generic Schema):**
- ALL nodes have the label :GraphNode.
- ALL relationships have the type :RELATES_TO.
- **Node Identification:** To distinguish entities, you MUST filter by the **node_type** property. **node_id format** is `public.<table>:<id>` (e.g. `public.persons:20`, `public.orders:10`). Use this when matching by node_id or returning node_id for resolution.
- **Relationship Identification:** Relationships are generic. You do not need to filter by relationship_type unless specifically asked for metadata; focus on the source and target node_types.
- **Property Reference:** Use `node_id` for names/identifiers. The **`n.properties`** field is stored as a **JSON string** in Neo4j, not a map. Do NOT use `n.properties.someKey` — that causes "Type mismatch: expected a map but was String". To access a key inside it use **`apoc.convert.fromJsonMap(n.properties).someKey`** (e.g. `apoc.convert.fromJsonMap(t.properties).category`). To return full attributes, use `n.properties AS details` and parse in code if needed.
- **Return Format:** Always return node properties (e.g., `n.node_id`, `n.properties`) or the node object itself (`n`) so the system can parse the attributes. For referenced entities, return `node_id` so the system can resolve the node in the graph.
- **Syntax Rules:** Use `variable.property IS NOT NULL` instead of `exists()`.
- **CASE / WHEN (no stray WHEN):** Every **`WHEN`** belongs **inside** one expression: **`CASE WHEN ... THEN ... [WHEN ... THEN ...] [ELSE ...] END`**. Do not start a new line with **`WHEN`** after `RETURN ... ,` (not a valid clause). Build the full **`CASE` ... `END`** in one projection, or one **`CASE`** with many **`WHEN`** branches.
- **List length (no .size()):** Cypher is not Java/JavaScript. Use **`size(listexpr)`** as a function. **Never** write **`expr.size()`** (invalid). Example: **`size(apoc.text.regexGroups(props.phone, '\\\\d+')) > 0`**, not `regexGroups(...).size()`.
- **Lists / ordinals (no indexOf):** Cypher has **no** `indexOf()` function (that is a JavaScript name). To get a value's index in a literal list use **`apoc.coll.indexOf(collection, item)`** (0-based; **-1** if absent), or map order with **`CASE value WHEN 'a' THEN 0 WHEN 'b' THEN 1 ... END`**. Never write `indexOf([...], x)`.
- **Division (Cypher):** Never divide by **`(max - min)`** when they may be equal, or by any value that can be **0**. Use **`CASE WHEN max = min OR max IS NULL OR min IS NULL THEN 0.0 ELSE (v - min) / (max - min) END`** (or skip normalization when the range is zero).
- **Counting:** When returning a single count (e.g. after fulltext + filters), use **count(identifier)** (e.g. `count(node)`), not `count(*)`. Carry the node variable through WITH so you can `RETURN count(node) AS total`.
- **Type discipline (avoid `Can't coerce Long(...) to String`):** Values from `apoc.convert.fromJsonMap(n.properties)` may be **Long, Double, Boolean, or String** — never assume. Before any **string** op (`substring`, `CONTAINS`, `STARTS WITH`, `ENDS WITH`, `apoc.text.*`, regex `=~`), wrap the value with **`toString(...)`**. Before any **numeric** compare or arithmetic, wrap with **`toFloat(...)`** / **`toInteger(...)`**. For **epoch-millis timestamps** (Long, usually ≥10 digits) compare numerically (`props.ends_at < <epoch_ms>`) — do **not** call `date()` / `datetime()` on a Long. For **ISO-8601 date strings** use string compare or `apoc.date.parse(toString(props.ts), 'ms', 'iso_date')`.
- **WITH passthrough (avoid `Variable X not defined`):** After each `WITH`, **only variables listed in that WITH are available downstream**. If you compute an alias like `toFloat(props.x) AS comp_x` in one stage, **carry it forward** in every subsequent `WITH` you want to keep using it: `WITH n, comp_x, comp_y, props ...`. Do **not** re-wrap an alias that isn't forwarded (e.g. `toFloat(comp_x) AS comp_x` fails if `comp_x` was dropped). Define the alias once, then pass it through — don't reference `props.<key>` after `props` is dropped.
- **levenshteinDistance / APOC on properties:** Before using `apoc.text.levenshteinDistance(props.key, "term")`, ensure the property exists: add **`WHERE props IS NOT NULL AND props.key IS NOT NULL`** (or the key you use) so null does not cause a runtime error.
- **Full-text traversal:** For finding nodes by text/keywords and exploring the graph (full-text traversal), use **RetrieveNode(text)**. It does seed search with fuzzy matching and then PPR/MST graph expansion—do not write Cypher that uses `CALL db.index.fulltext.queryNodes` for traversal. Use **run_cypher** only for aggregates, counts, and filters that require Cypher (e.g. count by type, group by, complex WHERE). For text-based search + graph exploration, always prefer RetrieveNode.
- **Text/name in Cypher (when not traversal):** When you do use Cypher for a text filter (e.g. counting matches), use fuzzy: fulltext with **`~`** on terms and/or **`apoc.text.levenshteinDistance(prop, "term")`**; guard with `props IS NOT NULL AND props.key IS NOT NULL` before levenshteinDistance.
{entity_property_shapes_block}
- **Inspect node layout:** `MATCH (n:GraphNode) RETURN n.node_type AS type, keys(n) AS base_attributes, n.properties AS properties_sample LIMIT 5`
"""

# Legacy hardcoded contract (fallback when no business logic).
CYPHER_GRAPH_CONTRACT = CYPHER_GRAPH_CONTRACT_BASE.format(
    entity_property_shapes_block="""
- **Entity property shapes (keys inside the `n.properties` JSON string):**
  - **ProductsTableEntity:** name, name_field, entity_type, source_type
  - **OrdersTableEntity:** total, status, currency, subtotal, person_id, attributes, created_at_field
  - **PersonNode:** name, first_name, last_name, city, region, country, primary_email, primary_phone, attributes, created_at_field, updated_at_field
  - **LeadsTableEntity:** name, email, phone, source, status, person_id, utm_medium, utm_source, utm_campaign, attributes, created_at_field
  - **SupportTicketsTableEntity:** name, status, category, priority, person_id, product_id, attributes, closed_at, sentiment_score, created_at_field
  Use **`apoc.convert.fromJsonMap(n.properties).key`** to read a key (e.g. `.category` for tickets, `.status` for orders).
"""
).strip()


def build_entity_property_shapes_block(
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
) -> str:
    """Build the entity property shapes section for the Cypher contract.

    Args:
        entity_property_shapes: Node type -> list of useful property keys.
        source_type_filter: If set, add a note to filter by source_type in Cypher.

    Returns:
        Multiline string to inject into the graph contract.
    """
    if not entity_property_shapes:
        return """
- **Entity property shapes:** Run `MATCH (n:GraphNode) RETURN DISTINCT n.node_type, keys(apoc.convert.fromJsonMap(n.properties)) LIMIT 20` to discover node types and property keys. Use **`apoc.convert.fromJsonMap(n.properties).key`** to read a key.
"""
    lines = [
        "- **Entity property shapes (keys inside the `n.properties` JSON string):**"
    ]
    for node_type, keys in sorted(entity_property_shapes.items()):
        if not keys:
            continue
        lines.append(f"  - **{node_type}:** {', '.join(keys)}")
    lines.append(
        "  Use **`apoc.convert.fromJsonMap(n.properties).key`** to read a key."
    )
    lines.append(
        "  For node types not listed above, return **`n.node_id`** (and optionally `n.node_type`) so full content can be resolved via **NodeInfo** when needed."
    )
    if source_type_filter:
        lines.append(
            f"- **Connector filter:** When the user scoped to a connector (e.g. @{source_type_filter}), add: "
            "`WHERE apoc.convert.fromJsonMap(n.properties).source_type = $source_type` (or the appropriate source_type value) to restrict results."
        )
    return "\n".join(lines)


def build_cypher_graph_contract(
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
) -> str:
    """Build the full Cypher graph contract with optional dynamic property shapes."""
    block = build_entity_property_shapes_block(
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
    )
    return CYPHER_GRAPH_CONTRACT_BASE.format(
        entity_property_shapes_block=block,
    ).strip()

CYPHER_GOLDEN_EXAMPLES = """
**Reference examples (golden queries). Use fuzzy matching for any text/name search; set levenshtein distance based on text length (e.g. < 5 for short names).**

**Full-text traversal:** Do not use Cypher fulltext for "find by text + explore graph". Use **RetrieveNode(text)** — it runs seed search with fuzzy matching and PPR/MST. Use run_cypher only for aggregates/counts/filters.

1) Entity lookup by text in Cypher (only when you need a count or aggregate, not traversal) – Guard against null before levenshteinDistance; use count(node):
   CALL db.index.fulltext.queryNodes("graphnode_fulltext", "Danielle~") YIELD node, score
   WHERE node.node_type = 'PersonNode'
   WITH node, score, apoc.convert.fromJsonMap(node.properties) AS props
   WHERE props IS NOT NULL AND props.name IS NOT NULL AND apoc.text.levenshteinDistance(props.name, "Danielle Jonson") < 5
   RETURN node.node_id AS node_id, props.name AS matched_name, props.primary_email AS email, score
   ORDER BY score DESC LIMIT 1
   (For traversal by text, use RetrieveNode(text) instead.)

2) Traversal from a known type (no free-text search) – When the plan is "traverse from product/lead" with a filter that is not free-text, use MATCH + pattern. For free-text search + traversal use RetrieveNode(text).
   MATCH (target:GraphNode)
   WHERE target.node_type = 'ProductsTableEntity'
   AND apoc.convert.fromJsonMap(target.properties).name =~ '(?i).*graphic.*'
   MATCH (target)<-[:RELATES_TO]-(ticket:GraphNode)
   WHERE ticket.node_type = 'SupportTicketsTableEntity'
   RETURN target.node_id AS product_id, apoc.convert.fromJsonMap(target.properties).name AS product_name, count(ticket) AS ticket_count

3) Count/aggregate after fulltext in Cypher – Only when you need a count or aggregate (not traversal). Fuzzy terms with ~; guard props before levenshteinDistance:
   CALL db.index.fulltext.queryNodes("graphnode_fulltext", "term1~ term2~") YIELD node, score
   WHERE node.node_type = 'SomeEntity'
   WITH node, apoc.convert.fromJsonMap(node.properties) AS props
   WHERE props IS NOT NULL AND props.name IS NOT NULL AND apoc.text.levenshteinDistance(props.name, "search phrase") < 5
   RETURN count(node) AS total

4) Top-N aggregation – "Top n people with the most orders" (return node_id so entities are resolvable):
   MATCH (p:GraphNode)-[:RELATES_TO]->(o:GraphNode)
   WHERE p.node_type = 'PersonNode'
     AND o.node_type = 'OrdersTableEntity'

   WITH p, count(o) AS order_count
   RETURN p.node_id AS node_id, p.node_id AS person_name, p.properties AS person_details, order_count
   ORDER BY order_count DESC
   LIMIT n (replace n with the desired number)

5) Dynamic property grouping (category distribution) – Aggregation by a field inside JSON properties (use apoc.convert.fromJsonMap):
   MATCH (t:GraphNode)
   WHERE t.node_type = 'SupportTicketsTableEntity'
   WITH t, apoc.convert.fromJsonMap(t.properties) AS props
   WITH (CASE WHEN props IS NOT NULL THEN props.category ELSE null END) AS bucket, count(t) AS cnt
   RETURN bucket, cnt
   ORDER BY cnt DESC

6) Temporal trend analysis (line/area chart ready) – Use for "How are we doing over time?"; truncate timestamps to month (or day):
   MATCH (o:GraphNode)
   WHERE o.node_type = 'OrdersTableEntity'
   WITH apoc.convert.fromJsonMap(o.properties) AS props
   WITH substring(props.created_at_field, 0, 7) AS month, sum(props.total) AS revenue
   RETURN month, revenue
   ORDER BY month ASC

7) Shortest path / hidden relationship – Use for "How is Person A connected to Product B?"; pass start_id and end_id as parameters:
   MATCH (start:GraphNode {node_id: $start_id}),
         (end:GraphNode {node_id: $end_id})
   MATCH p = shortestPath((start)-[:RELATES_TO*..5]-(end))
   RETURN p

8) Outlier & anomaly detection (scatter-plot ready) – Use for "Show me unusual activity"; compare two numeric attributes (e.g. sentiment vs spend):
   MATCH (p:GraphNode)-[:RELATES_TO]->(t:GraphNode)
   WHERE p.node_type = 'PersonNode' AND t.node_type = 'SupportTicketsTableEntity'
   MATCH (p)-[:RELATES_TO]->(o:GraphNode)
   WHERE o.node_type = 'OrdersTableEntity'
   WITH p, avg(apoc.convert.fromJsonMap(t.properties).sentiment_score) AS avg_sentiment, sum(apoc.convert.fromJsonMap(o.properties).total) AS total_spend
   RETURN p.node_id AS person, avg_sentiment, total_spend
   ORDER BY total_spend DESC
"""


def _knowledge_manifest_line(idx: int, item: Any) -> str:
    """One line of the Knowledge Manifest: structured summary, no raw repr()."""
    if not isinstance(item, dict):
        return f"Item {idx + 1}: {repr(item)[:400]}"
    if item.get("type") == "execution_note":
        errs = item.get("errors") or []
        err_preview = "; ".join(str(e)[:80] for e in errs[:3])
        if len(errs) > 3:
            err_preview += f" (+{len(errs) - 3} more)"
        return f"Item {idx + 1}: Execution Note. {item.get('note', '')} Errors: {err_preview}"
    if item.get("type") == "cypher_error":
        return f"Item {idx + 1}: Cypher failed. Preview: {(item.get('cypher_preview') or '')[:150]}. Error: {(item.get('error') or '')[:150]}"
    if item.get("source") == "p_agent":
        summary = (item.get("summary") or "")[:300]
        charts = item.get("charts") or []
        return f"Item {idx + 1}: P-Agent. Summary: {summary}. Charts: {len(charts)}."
    if "cypher" in item and (item.get("rows") is not None or item.get("large_data_ref")):
        intent = item.get("intent", "General Query")
        row_count = item.get("row_count") or (len(item["rows"]) if item.get("rows") else 0)
        cols = item.get("columns") or (list(item["rows"][0].keys()) if item.get("rows") and item["rows"] else [])
        query_preview = (item.get("cypher") or "")[:100].replace("\n", " ")
        ref_note = " (Rows in side-car.)" if item.get("large_data_ref") else ""
        empty_note = " WARNING: zero rows; validate query." if item.get("empty_result") else ""
        return f"Item {idx + 1}: Cypher Result [Intent: {intent}]. Rows: {row_count}. Cols: {cols}. Query: {query_preview}...{ref_note}{empty_note}"
    if item.get("node_id") or item.get("tool") in ("NodeInfo", "RetrieveNode"):
        name = item.get("name") or "(no name)"
        return f"Item {idx + 1}: Node(s). node_id: {item.get('node_id')}, type: {item.get('node_type')}, name: {name}"
    return f"Item {idx + 1}: {repr(item)[:400]}"


def build_relevant_node_types_and_ppr_block(
    *,
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    schema_narrative: Optional[str] = None,
    ppr_top_nodes: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build a single block combining relevant node types/info from business logic and optional PPR results.

    Used in the A-Agent user message (schema + vocabulary). PPR instances are optional and normally
    omitted—concrete nodes come from RetrieveNode after the executor runs tool code.
    """
    lines = ["## Relevant node types and information", ""]
    has_any = False
    if node_types:
        has_any = True
        lines.append("**Node types (from business logic):**")
        lines.append(", ".join(node_types[:80]) + (" ..." if len(node_types) > 80 else ""))
        lines.append("")
    if rel_types:
        has_any = True
        lines.append("**Relationship types:** " + ", ".join(rel_types[:20]))
        lines.append("")
    if entity_property_shapes:
        has_any = True
        lines.append("**Property shapes (useful keys per node type):**")
        for nt, keys in sorted(entity_property_shapes.items())[:30]:
            if keys:
                lines.append(f"  - {nt}: {', '.join(keys)}")
        if len(entity_property_shapes) > 30:
            lines.append("  ...")
        lines.append("")
    if schema_narrative:
        has_any = True
        lines.append("**Schema (how types connect):** " + (schema_narrative[:500] + "..." if len(schema_narrative) > 500 else schema_narrative))
        lines.append("")
    if ppr_top_nodes:
        has_any = True
        lines.append("**PPR top nodes (relevant instances from query):**")
        for i, n in enumerate(ppr_top_nodes[:10], 1):
            nid = n.get("node_id") or ""
            ntype = n.get("node_type") or "Unknown"
            name = n.get("name") or nid
            lines.append(f"  {i}. {ntype} | {name!r} | {nid}")
        lines.append("")
    if not has_any:
        return ""
    lines.append("Use the above to see what node types and entities are relevant; plan exact matches or filters accordingly.")
    lines.append("")
    return "\n".join(lines)


def _build_system_context_block(
    *,
    organization_id: Optional[UUID] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> str:
    """Build the '## System Context' block shared by R-Agent and A-Agent user messages.

    Gives the agent today's date, day of week, yesterday's date, and the requesting
    user's identity so relative terms like 'yesterday', 'today', 'my', or 'me' resolve
    to concrete values in generated Cypher.
    """
    now_dt = datetime.now()
    today_iso = now_dt.strftime("%Y-%m-%d")
    yesterday_iso = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    weekday = now_dt.strftime("%A")
    current_time = now_dt.strftime("%H:%M %Z").strip() or now_dt.strftime("%H:%M")
    lines: List[str] = ["## System Context"]
    lines.append(f"Today: {today_iso} ({weekday})")
    lines.append(f"Yesterday: {yesterday_iso}")
    lines.append(f"Current Time: {current_time}")
    if organization_id:
        lines.append(f"Target Org: {organization_id}")
    else:
        lines.append("Target Org: (not set)")
    if user_email:
        lines.append(f"Requesting User Email: {user_email}")
    if user_name:
        lines.append(f"Requesting User Name: {user_name}")
    if user_email or user_name:
        lines.append(
            'When the user says "my", "I", or "me", resolve it to the requesting user '
            "above (match by email where possible). When the user says relative dates "
            '("yesterday", "today", "this week", "last N days"), resolve them using '
            "Today/Yesterday above and emit concrete ISO-8601 dates in Cypher."
        )
    return "\n".join(lines) + "\n\n"


def _adk_escape_instruction_braces(text: str) -> str:
    """ContextD ADK calls str.format_map() on BaseAgent `instructions`. Escape `{`/`}` so JSON in the prompt is not parsed as format fields."""
    return text.replace("{", "{{").replace("}", "}}")
