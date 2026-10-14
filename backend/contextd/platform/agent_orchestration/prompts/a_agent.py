"""A-Agent prompt builders."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd.platform.agent_orchestration.prompts.common import (
    CYPHER_GOLDEN_EXAMPLES,
    CYPHER_GRAPH_CONTRACT,
    _adk_escape_instruction_braces,
    _build_system_context_block,
    build_cypher_graph_contract,
    build_pruned_schema_vocabulary,
    build_relevant_node_types_and_ppr_block,
    build_valid_vocabulary_section,
)
from contextd.platform.agent_orchestration.types import ResearchPlan

A_AGENT_SYSTEM_TEMPLATE = """You are the Action Agent (Programmer). You receive **only** the RESEARCH_PLAN (what data is needed), not the original user query. Your job is to translate that plan into Python code that fetches the specified data.

You have exactly three functions available in the execution environment:
1. **RetrieveNode(text: str)** – **Use for full-text traversal.** Pass a natural language or keyword string; it runs seed search with fuzzy matching and then PPR/MST graph expansion. Returns node IDs and summaries. Do not use Cypher fulltext for "find by text + explore graph"—use RetrieveNode.
2. **NodeInfo(node_ids: List[str])** – Fetches the **full** vertex-chunk (all properties + 1-hop neighbors) for the given node IDs. **Use this whenever you have node_ids and need complete node content** (e.g. after run_cypher returns node_id columns, or when the plan says "get full details for these nodes"). Pass a list of node ID strings.
3. **run_cypher(cypher: str, params: dict | None = None)** – Runs a read-only **Cypher** query on Neo4j. **Cypher only; do not use SQL.** Use `params` whenever your Cypher contains placeholders like `$email` or `$user_id`. `organization_id` is injected automatically; do not pass it yourself. Returns a list of row dicts. If run_cypher returns an error (e.g. in current knowledge), the next plan/code should fix the query/tool usage and retry.
__CYPHER_GRAPH_CONTRACT__
""" + CYPHER_GOLDEN_EXAMPLES + """
**Rules:**
- If the user message includes **Tool errors from last run**, your code MUST fix the Cypher/tool usage (e.g. correct syntax, use `variable.property IS NOT NULL` instead of `exists()`; when returning a count use `count(identifier)` e.g. count(node) not count(*); guard props/key IS NOT NULL before apoc.text.levenshteinDistance; do not repeat the same failing call unchanged).
- Output only valid Python code. No markdown, no explanation outside comments.
- No imports. No file I/O. No network calls other than through these three functions.
- The code will run in a restricted sandbox; only these three names exist.
- You may use built-ins: list, dict, str, int, len, range, etc.
- Prefer clear variable names. Results of RetrieveNode/NodeInfo/run_cypher will be captured and merged into the Notebook automatically.
- **When run_cypher or RetrieveNode returns node_ids:** Call **NodeInfo(list_of_node_ids)** to fetch full properties and neighbors for those nodes so the notebook has complete content. Do not assume Cypher result rows contain all properties—NodeInfo is the way to get the full vertex-chunk.
- **Full-text traversal:** For "find by text + explore graph", use **RetrieveNode(text)** (fuzzy + PPR/MST). Do not write Cypher with CALL db.index.fulltext.queryNodes for traversal. Use run_cypher for aggregates, counts, and complex filters only.
- **Full-data analysis:** If the task requires looking at all or a large portion of the graph (e.g. sort, count, top N, aggregates), use run_cypher to do the work in the database. Do not pull all data into the notebook (RetrieveNode/NodeInfo are limited and cannot stream the full dataset).
- **If a Cypher query returns 0 rows:** Do not assume the absence is correct. Usually your next code should validate the query by checking broader counts, sampling likely node types/properties, or relaxing an exact filter before concluding there is no data. A zero-row retry is allowed when it explicitly fixes or validates the prior query.

Output valid JSON with a single field "code" containing the Python code string.
"""

# Default A-Agent prompt (legacy) for backward compatibility.
# Use replace() so Cypher examples with {node_id} etc. are not interpreted as format placeholders.
A_AGENT_SYSTEM = A_AGENT_SYSTEM_TEMPLATE.replace(
    "__CYPHER_GRAPH_CONTRACT__", CYPHER_GRAPH_CONTRACT
)


def get_a_agent_system_prompt(
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
    schema_narrative: Optional[str] = None,
    pruned_schema: Optional[str] = None,
) -> str:
    """Build A-Agent system prompt with optional dynamic vocabulary and Cypher contract.

    When pruned_schema is set, uses it as vocabulary and enforces anonymous relationships in Cypher.
    """
    if pruned_schema and pruned_schema.strip():
        vocab = build_pruned_schema_vocabulary(pruned_schema)
    else:
        ntypes = node_types if node_types else []
        rtypes = rel_types if rel_types else []
        vocab = build_valid_vocabulary_section(
            ntypes, rtypes, schema_narrative=schema_narrative
        )
    cypher_contract = build_cypher_graph_contract(
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
    )
    base = A_AGENT_SYSTEM_TEMPLATE.replace(
        "__CYPHER_GRAPH_CONTRACT__", cypher_contract
    )
    examples = CYPHER_GOLDEN_EXAMPLES
    if pruned_schema and pruned_schema.strip():
        # Use anonymous relationships in examples when using pruned schema
        examples = examples.replace("-[:RELATES_TO*..5]-", "-[*..5]-")
        examples = examples.replace("-[:RELATES_TO]-", "-[]-")
        examples = examples.replace("<-[:RELATES_TO]-", "-[]-")
        examples = examples.replace("-[:RELATES_TO]->", "-[]-")
    out = base.replace(
        CYPHER_GOLDEN_EXAMPLES,
        vocab + "\n\n" + examples,
        1,
    )
    return _adk_escape_instruction_braces(out)


def get_a_agent_cohort_system_prompt(
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
    schema_narrative: Optional[str] = None,
    pruned_schema: Optional[str] = None,
) -> str:
    """A-Agent for cohort creation: same contract as chat, extra mandatory listing rules."""
    base = get_a_agent_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )
    cohort_block = """
**Cohort mode (strict):**
- Implement the research plan using **run_cypher** to produce the cohort **member list** (one row per member).
- Every RETURN row **must** include a column named **node_id** (e.g. `RETURN n.node_id AS node_id, ...`). Without `node_id`, the cohort cannot be saved.
- Project shallow columns with `apoc.convert.fromJsonMap(n.properties).<key> AS <alias>` when needed.
- Use **RetrieveNode** only if the plan explicitly requires fuzzy text traversal; otherwise **prefer a single Cypher** `MATCH (n:GraphNode) WHERE n.node_type = ...`.
- Do **not** rely on P-Agent or charts.
- **JSON date/time fields:** Values from `apoc.convert.fromJsonMap(n.properties)` are often **strings**. Do not compare a string directly to `date()` / `datetime()` without parsing or ISO-safe logic—empty results are a common bug. Sample a few `ends_at`-like values if unsure.
- **Zero rows:** If a filter might exclude everything, run a quick COUNT for the `node_type` and optionally sample raw date fields before concluding there is no data.
"""
    # base is already escaped by get_a_agent_system_prompt; cohort_block has no { }.
    return cohort_block + "\n" + base


def build_a_agent_user_message(
    research_plan: ResearchPlan,
    *,
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    schema_narrative: Optional[str] = None,
    ppr_top_nodes: Optional[List[Dict[str, Any]]] = None,
    organization_id: Optional[UUID] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> str:
    """Build the user message for A-Agent from a research plan.
    When business logic (and optionally ppr_top_nodes) are provided, prepends
    'Relevant node types and information' so the A-Agent can reference schema/vocabulary.
    """
    system_context = _build_system_context_block(
        organization_id=organization_id,
        user_email=user_email,
        user_name=user_name,
    )
    relevant_block = build_relevant_node_types_and_ppr_block(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        schema_narrative=schema_narrative,
        ppr_top_nodes=ppr_top_nodes,
    )
    prefix = system_context + ((relevant_block + "\n\n") if relevant_block else "")
    steps_str = "\n".join(f"- {s}" for s in research_plan.steps)
    return f"""{prefix}## Research Plan
Goal: {research_plan.goal}

Steps:
{steps_str}

Generate Python code that uses only RetrieveNode(text), NodeInfo(node_ids), and run_cypher(cypher, params=None) to execute this plan. For full-text traversal (find by text + explore graph) use RetrieveNode(text)—do not use run_cypher with fulltext for traversal. Use Cypher (Neo4j) only for aggregates, counts, and filters. If your Cypher includes placeholders like `$user_email`, pass them via the `params` dict in `run_cypher`; do not inline unsafe string formatting. `organization_id` is injected automatically. Follow the Graph Data Contract: all nodes :GraphNode, all edges :RELATES_TO; filter by n.node_type and r.relationship_type. Do not use exists(variable.property); use variable.property IS NOT NULL. When returning a single count from a fulltext/filtered pipeline use count(identifier) (e.g. count(node)), not count(*). Before apoc.text.levenshteinDistance(props.key, \"term\") add WHERE props IS NOT NULL AND props.key IS NOT NULL. For aggregation after WITH that drops a variable use count(identifier) in the WITH (e.g. WITH bucket, count(t) AS cnt). For full-data analysis use run_cypher in the database. Output valid JSON with key "code" and the code string as value."""
