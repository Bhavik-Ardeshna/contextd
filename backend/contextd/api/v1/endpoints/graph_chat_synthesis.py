"""Prompt and synthesis helpers for graph chat endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from contextd.api.v1.endpoints.graph_chat_presenters import (
    _chart_data_snippet_for_llm_prompt,
    _sanitize_chart_data,
)
from contextd.api.v1.endpoints.graph_chat_schemas import ChartSpecResponse


def _notebook_items(glm_notebook_state: Any) -> List[Dict[str, Any]]:
    current_knowledge = getattr(glm_notebook_state, "current_knowledge", None)
    if not current_knowledge:
        return []
    return [item for item in current_knowledge if isinstance(item, dict)]


def append_notebook_context_sections(
    context_for_prompt: str,
    glm_notebook_state: Any,
) -> Tuple[str, bool]:
    """Append Cypher manifests and P-Agent summaries to the final prompt context."""
    items = _notebook_items(glm_notebook_state)
    if not items:
        return context_for_prompt, False

    cypher_items = [
        item for item in items if item.get("cypher") and item.get("type") != "execution_note"
    ]
    if cypher_items:
        parts = []
        for idx, item in enumerate(cypher_items):
            cypher = item.get("cypher", "")
            row_count = item.get("row_count") or (len(item["rows"]) if item.get("rows") else 0)
            parts.append(f"Query {idx + 1} (returned {row_count} rows):\n{cypher}")
        context_for_prompt += "\n\n## How the data was obtained (Cypher queries)\n" + "\n\n".join(
            parts
        )

    p_agent_items = [item for item in items if item.get("source") == "p_agent"]
    has_p_agent_charts = False
    if p_agent_items:
        parts = []
        chart_dicts_for_llm: List[Dict[str, Any]] = []
        for item in p_agent_items:
            summary = item.get("summary", "").strip()
            if summary:
                parts.append(summary)
            charts_raw = item.get("charts") or []
            if charts_raw:
                has_p_agent_charts = True
            for chart in charts_raw:
                if isinstance(chart, dict) and chart.get("title"):
                    parts.append(f"Chart: {chart['title']}")
            for chart in charts_raw:
                if isinstance(chart, dict) and chart.get("type") == "chart":
                    chart_dicts_for_llm.append(chart)

        if parts:
            analysis_section = "\n\n## Analysis\n" + "\n\n".join(parts)
            if chart_dicts_for_llm:
                series_text = _chart_data_snippet_for_llm_prompt(chart_dicts_for_llm)
                if series_text:
                    analysis_section += (
                        "\n\n### Chart data (series - use for totals and breakdowns)\n"
                        + series_text
                    )
            context_for_prompt += analysis_section
            context_for_prompt += (
                "\n\n## Data scope\n"
                "When **Analysis** and **Chart data** above are present, they reflect the **full** Cypher/query result tables. "
                "The entity list in KNOWLEDGE GRAPH CONTEXT may be a subgraph excerpt for display; it can differ from aggregate totals in charts."
            )

    return context_for_prompt, has_p_agent_charts


def append_count_hint(
    context_for_prompt: str,
    entity_count_for_hint: int,
    *,
    has_p_agent_charts: bool = False,
) -> str:
    """Append count-answering guidance when graph context is available."""
    if (
        entity_count_for_hint <= 0
        or not context_for_prompt
        or "No relevant information" in context_for_prompt
    ):
        return context_for_prompt

    if has_p_agent_charts:
        count_hint = (
            "\n\n## USE FOR COUNT QUESTIONS\n"
            "The **Analysis** section may include chart series and aggregates from the **full** query result. "
            "Prefer those numbers for totals and per-category counts when they answer the question. "
            f"The subgraph lists about {entity_count_for_hint} entities as context (not necessarily the same as chart aggregates). "
            "Do NOT say the knowledge graph returned no information when Analysis or chart data is present."
        )
    else:
        count_hint = (
            "\n\n## USE FOR COUNT QUESTIONS\n"
            f"The context above lists exactly {entity_count_for_hint} entities (see DATA OVERVIEW and DETAILED ENTITY DATA). "
            "These entities (e.g. Task 1, Task 2, Project X, Workspace Y) ARE the items; they are the tasks, projects, or workspaces themselves. "
            f'When the user asks "how many tasks remaining", "how many tasks", "how many projects", or "how many X", the answer is {entity_count_for_hint} (or the count for the matching type in the overview). '
            "Do NOT say the knowledge graph did not return any information when this context clearly lists entities."
        )
    return context_for_prompt + count_hint


def build_tool_errors_section(glm_notebook_state: Any) -> str:
    """Build prompt guidance for failed notebook tool executions."""
    errors: List[str] = []
    for item in _notebook_items(glm_notebook_state):
        if item.get("type") == "execution_note":
            errors.extend(item.get("errors") or [])
        elif item.get("error"):
            errors.append(item.get("error"))
    if not errors:
        return ""
    return (
        "\n\n## TOOL EXECUTION NOTES (use this when answering)\n"
        "One or more Cypher executions failed. Inform the user and suggest rephrasing or retrying "
        "(e.g. use `variable.property IS NOT NULL` instead of `exists(variable.property)` in Cypher).\n\n"
        "Errors:\n" + "\n".join(f"- {error}" for error in errors[:10])
    )


def build_chart_specs_from_notebook(
    glm_notebook_state: Any,
) -> Tuple[List[ChartSpecResponse], int]:
    """Collect frontend chart specs from P-Agent notebook artifacts."""
    chart_specs: List[ChartSpecResponse] = []
    p_agent_count = 0
    for item in _notebook_items(glm_notebook_state):
        if item.get("source") != "p_agent":
            continue
        p_agent_count += 1
        charts_raw = item.get("charts") or []
        for chart in charts_raw:
            if isinstance(chart, dict):
                if chart.get("type") != "chart":
                    continue
                chart_type = chart.get("chart_type") or "bar"
                title = chart.get("title") or ""
                data = chart.get("data") or []
                config = chart.get("config")
            else:
                if getattr(chart, "type", None) != "chart":
                    continue
                chart_type = getattr(chart, "chart_type", None) or "bar"
                title = getattr(chart, "title", None) or ""
                data = getattr(chart, "data", None) or []
                config = getattr(chart, "config", None)
            safe_data = _sanitize_chart_data(data) if isinstance(data, list) else []
            chart_specs.append(
                ChartSpecResponse(
                    type="chart",
                    chart_type=chart_type,
                    title=title,
                    data=safe_data,
                    config=config,
                )
            )
    return chart_specs, p_agent_count


def build_queries_trace(glm_notebook_state: Any) -> List[Dict[str, Any]]:
    """Build UI-safe query trace metadata from notebook artifacts."""
    queries_trace: List[Dict[str, Any]] = []
    for item in _notebook_items(glm_notebook_state):
        cypher = item.get("cypher")
        if not cypher or item.get("type") == "execution_note":
            continue
        row_count = item.get("row_count")
        if row_count is None:
            rows = item.get("rows")
            row_count = len(rows) if isinstance(rows, list) else 0
        queries_trace.append(
            {
                "cypher": cypher,
                "row_count": row_count,
                "error": item.get("error") or None,
            }
        )
    return queries_trace


def build_graph_chat_system_prompt(
    *,
    context_for_prompt: str,
    entity_count: int,
    relationship_count: int,
    tool_errors_section: str = "",
) -> str:
    """Build the full graph-chat answer synthesis prompt."""
    return _build_system_prompt(
        context_for_prompt=context_for_prompt,
        entity_count=entity_count,
        relationship_count=relationship_count,
        tool_errors_section=tool_errors_section,
        include_full_query_guidance=True,
        include_null_category_guidance=True,
        include_chart_guidance=True,
    )


def build_graph_chat_search_system_prompt(
    *,
    context_for_prompt: str,
    entity_count: int,
    relationship_count: int,
) -> str:
    """Build the deterministic graph-search answer synthesis prompt."""
    return _build_system_prompt(
        context_for_prompt=context_for_prompt,
        entity_count=entity_count,
        relationship_count=relationship_count,
        tool_errors_section="",
        include_full_query_guidance=False,
        include_null_category_guidance=False,
        include_chart_guidance=False,
    )


def _build_system_prompt(
    *,
    context_for_prompt: str,
    entity_count: int,
    relationship_count: int,
    tool_errors_section: str,
    include_full_query_guidance: bool,
    include_null_category_guidance: bool,
    include_chart_guidance: bool,
) -> str:
    full_query_guidance = (
        """
### Full query data vs entity list:
When **Analysis** and **Chart data (series)** appear in the context, they come from the full Cypher result tables. The **KNOWLEDGE GRAPH CONTEXT** entity list may be an excerpt for visualization. For counts and breakdowns that depend on aggregates, trust **Analysis** and chart series over a simple node count.
"""
        if include_full_query_guidance
        else ""
    )
    null_category_guidance = (
        """
### Null/missing in category breakdowns:
- If the context shows null, None, or empty values in a breakdown (e.g. a row with \"None\" or null as the category and a count), treat this as missing/unknown data, not as a valid category. Do not present null as if it were a real label (e.g. do not say \"None had the most orders\").
- Inform the user how many items did not have that attribute (e.g. \"X orders did not have an associated country\" or \"X items had no [dimension] specified\"). Use the actual count from the context when available.
"""
        if include_null_category_guidance
        else ""
    )
    chart_guidance = (
        """
- **Charts and visualizations**: Any charts requested by the user are already being generated and displayed by the system. Do NOT say that you cannot create charts, that this is a text-only interface, or suggest the user use Excel, Tableau, Matplotlib, or other external tools. Simply describe or interpret the data; the charts will appear alongside your response.
"""
        if include_chart_guidance
        else ""
    )
    return f"""You are an intelligent knowledge graph analyst with access to organizational data. Your role is to deeply understand the data, identify patterns, and provide actionable insights.
{tool_errors_section}

## YOUR CAPABILITIES
- Analyze entities (tasks, projects, people, documents) and their relationships
- Identify patterns, trends, and anomalies in the data
- Understand project status, team dynamics, and workflow dependencies
- Provide data-driven recommendations and insights

## KNOWLEDGE GRAPH CONTEXT
The following data was retrieved from a knowledge graph containing {entity_count} entities and {relationship_count} relationships relevant to the user's query.

{context_for_prompt}

## ANALYSIS GUIDELINES

### When Analyzing Data:
1. **Understand Entity Types**: Recognize different entities (Tasks, Projects, People, Documents, etc.) and their significance
2. **Analyze Relationships**: Look for connections between entities - who is assigned to what, what belongs to which project, dependencies, etc.
3. **Extract Key Information**: Focus on names, statuses, dates, priorities, and other meaningful attributes
4. **Identify Patterns**: Look for recurring themes, bottlenecks, or notable clusters
{full_query_guidance}
### When the user asks for a count or list (e.g. "how many workspaces", "number of projects"):
1. **Use the context you were given.** The "KNOWLEDGE GRAPH CONTEXT" section above contains the answer. Do NOT say "the knowledge graph did not return any information" when the context clearly lists entities (names, types, or "Entity types: X: N").
2. **Use type counts when present.** If the context says "Entity types: Workspace: 2, Project: 3", use those numbers to answer "how many workspaces" or "how many projects".
3. **Infer from entity names when types are missing or Unknown.** If the context lists entity names (e.g. "Purav Shah's Workspace", "Project 1", "Team Space") and the user asks for a count of workspaces or projects, count the entities that match: names containing "Workspace" or that are clearly workspaces count as workspaces; "Project 1", "Team Space" etc. can be projects/spaces. Give a direct answer (e.g. "There is 1 workspace in the context: Purav Shah's Workspace" or "The context shows 4 referenced entities; based on their names, at least one is a workspace (Purav Shah's Workspace).").
4. **Never refuse to answer when the context contains relevant data.** If the context has entity names or type counts that can answer the question, answer from that data. Only say you cannot provide information when the context is truly empty or has no relevant entities.

### When Generating Insights:
1. **Be Specific**: Reference actual entity names and data points from the context
2. **Provide Context**: Explain why something is significant or noteworthy
3. **Highlight Connections**: Show how different pieces of information relate to each other
4. **Be Actionable**: When appropriate, suggest next steps or areas of focus

### Response Format:
- Start with a direct answer to the user's question
- Support your answer with specific data from the context (entity names, type counts, or detailed entity data)
- If relevant, provide additional insights or observations
- Use clear structure with bullet points or numbered lists for complex information
- Mention entity names in your response so users can identify them

### When Data is Limited or Aggregate-Only:
- If the context contains only summary/aggregate rows (e.g. Row with counts, one aggregate line) or no detailed entities, still provide a short, clear writeup: explain what the data shows (e.g. total count, single bucket), what it means, and any caveats (e.g. "breakdown key was empty; the schema may use a different property").
- Clearly state what information is available vs. missing.
- Provide the best possible answer with available data; never leave the user with no explanation when the graph returned something (even if it is a single count or empty breakdown).
- Suggest what additional information might be helpful when relevant.
{null_category_guidance}
### Important:
- Base ALL responses on the provided context - do not make up information
- If the context contains entity names, type counts, or "DETAILED ENTITY DATA", use them to answer. Do NOT respond with "the knowledge graph did not return any information" or "I cannot provide the exact count" when the context clearly lists relevant entities (e.g. workspaces, projects). Answer from the data given.
- If the context truly has no relevant information, say so honestly
- Be concise but thorough - quality over quantity{chart_guidance}
"""
