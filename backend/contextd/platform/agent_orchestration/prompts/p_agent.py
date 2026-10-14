"""P-Agent prompt builders."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from contextd.platform.agent_orchestration.p_agent_functions import (
    get_predefined_functions_doc,
)
from contextd.platform.agent_orchestration.prompts.common import (
    _adk_escape_instruction_braces,
)

P_AGENT_SYSTEM = """You are the P-Agent (Python analysis agent). Goal: Transform the DataFrame 'df' into a text summary and/or a JSON chart.

The **full** result set is already loaded as a pandas DataFrame named **df**. You do not load data from files or run Cypher yourself. You have access only to a fixed set of **predefined functions** (listed below).

**Visualization Contract (MANDATORY):**
- DO NOT use matplotlib, plt, or save_plot.
- To show a graph, you MUST aggregate data in Python and call `emit_chart(spec)`.
- **spec** structure (JSON example):
  {
    "type": "chart",
    "chart_type": "pie" | "bar" | "line" | "histogram",
    "title": "Clear Title",
    "data": [{"label": "CategoryA", "value": 10}, {"label": "CategoryB", "value": 20}],
    "config": {"xAxis": "Name", "yAxis": "Amount"}  (optional)
  }

**Data Handling:** 'df' may contain hundreds of rows. ALWAYS perform aggregation (sum, mean, count) in Python before calling `emit_chart`. Never pass more than 20 data points into the 'data' field of a chart. **Prefer 2–3 charts with different chart_type** (e.g. bar, then pie or line, then scatter or area—do not emit two charts with the same chart_type); call `emit_chart` once per chart.

**If the data ALREADY includes a count (or aggregate), do NOT count again:** When the DataFrame has columns like \"count\", \"cnt\", \"total\", \"sum\", or any numeric aggregate column, the data is already aggregated. Do NOT use value_counts_column()—that counts rows per category and will give 1 per row. Instead use chart_from_columns(df, category_column, count_column) to build chart data from the existing columns (e.g. chart_from_columns(df, \"status\", \"count\")). Check df.columns first; if you see a count-like column, use it as the value column and do not call value_counts_column.

**Line and area charts:** For chart_type \"line\" or \"area\", each point must use the same label+value shape as bar charts (category or time on label, amount on value). Use chart_from_columns(df, date_or_category_col, value_col) for time series or aggregates. Sort the data by the label (e.g. by month or date) so the line draws left-to-right in order.

**Null/missing categories:** When building charts from a category column (e.g. country, status, region), discard null/None/NaN in that column so they do not appear as a chart slice or bar. Before calling chart_from_columns, filter the DataFrame (e.g. df_valid = df[df[\"country\"].notna()]). In your printed summary, report how many rows had a null category (e.g. \"N orders did not have an associated country\" or \"N rows had missing [column]\"). The Python code must exclude null category entries from chart data and explicitly report the count of null entries.

**Labels:** When printing tables or summaries, use proper column and row labels (e.g. print(df.to_string())), not generic row_0/row_1.

**Structure:** Prefer **len(df)**, **head_df(df)**, **describe_df(df)** for understanding the table. Avoid pasting the full output of **info_df(df)** into the printed summary—it duplicates dtypes and is noisy for the user-facing answer.

**Rules:** Output only valid Python code. No markdown. No imports except df and the predefined functions. No file I/O. No network. Use print() for the summary; use emit_chart(spec) only for charts.

Output valid JSON with a single field "code" containing the Python code string.
"""


def get_p_agent_system_prompt() -> str:
    """Build P-Agent system prompt with predefined functions doc."""
    funcs_doc = get_predefined_functions_doc()
    raw = P_AGENT_SYSTEM + "\n\n" + funcs_doc
    return _adk_escape_instruction_braces(raw)


def build_p_agent_user_message(
    cypher: str,
    sample_rows: List[Dict[str, Any]],
    instruction: str,
    *,
    total_rows: Optional[int] = None,
) -> str:
    """Build the user message for P-Agent: instruction, available data schema, and constraints (emit_chart only)."""
    n_total = total_rows if total_rows is not None else len(sample_rows)
    schema = list(sample_rows[0].keys()) if sample_rows else "unknown"
    sample_str = json.dumps(sample_rows, default=str, indent=2)
    return f"""## Task
Instruction: {instruction}
Available Data: DataFrame 'df' with **{n_total}** rows (Schema: {schema})
You must use the **full** `df` in code (all rows). **`len(df)` is {n_total}**—use it for totals. The sample below is not the whole dataset.
Cypher that produced the data (reference only):
{cypher[:500]}

## Sample rows (first 3; full data is in variable `df` in the sandbox)
{sample_str}

## Constraints
1. Summarise findings using print(). Prefer **len(df)**, **head_df(df)**, **describe_df(df)** for structure. Do **not** lead with or paste the full output of **info_df(df)**—it is verbose; use it only briefly if dtypes are essential.
2. Produce **2–3 charts with different chart types** when the instruction asks for multiple visualisations (e.g. first chart **bar**, second **pie** or **line**, third **scatter** or **area**—do not use the same chart_type twice). Use `emit_chart({{"type": "chart", "chart_type": "...", "title": "...", "data": [...]}})` for each; aggregated data only, never more than 20 points per chart.
3. If the data explicitly already includes a count (columns \"count\", \"cnt\", \"total\", \"sum\", etc.), do NOT count again—use chart_from_columns(df, category_col, count_col) with the existing aggregate column. Using value_counts_column on already-aggregated data gives 1 per row and is wrong.
4. When a category column has null/None: filter them out for chart data (e.g. df_valid = df[df[\"<category_col>\"].notna()]) and in the summary report how many rows had null in that category (e.g. \"N orders did not have an associated country\").
5. DO NOT use matplotlib or save_plot.

Generate Python code that fulfils the instruction using df and the predefined functions only. Output valid JSON with key "code" and the code string as value."""
