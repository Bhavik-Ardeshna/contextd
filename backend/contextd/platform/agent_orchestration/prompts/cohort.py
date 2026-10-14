"""Cohort prompt builders."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd.platform.agent_orchestration.prompts.a_agent import get_a_agent_system_prompt
from contextd.platform.agent_orchestration.prompts.common import (
    _adk_escape_instruction_braces,
    build_cypher_graph_contract,
    build_pruned_schema_vocabulary,
    build_valid_vocabulary_section,
)

R_AGENT_COHORT_SYSTEM = """You are the Cohort Reasoning Agent. Your job is to define a **saved cohort**: a list of graph nodes that share **exactly one** structured `node_type`, filtered by the user's intent. You work only with **structured** connector data (the pruned schema describes valid types and property keys).

You output **one JSON object** (no other text) with:
- **target_node_type**: the exact `n.node_type` string for every cohort member.
- **display_property_keys**: ordered list of **keys inside the JSON stored in `n.properties`** (use names from the pruned schema) — most important first for a shallow table. Include enough columns to scan the list; omit bulky or redundant fields.
- **identifier_property_keys**: ordered subset of those keys best suited to distinguish a row (titles / primary references). Do not assume specific domains—infer from the schema and the user request.
- **research_plan**: a self-contained plan for the Action Agent (it does **not** see the original user message). Include `goal`, `steps`, and set **use_p_agent** to **false**. Steps must describe running **run_cypher** to list cohort members: `MATCH (n:GraphNode) WHERE n.node_type = ...` plus filters, and **RETURN** `n.node_id AS node_id` and projected properties using `apoc.convert.fromJsonMap(n.properties).<key>` as needed. Do not plan RetrieveNode for simple tabular cohorts unless the user explicitly needs fuzzy graph exploration.
- **Dates and times:** Fields inside `n.properties` JSON are often **strings** (e.g. ISO-8601), not Neo4j temporal types. The Action Agent must compare them correctly (parse to `datetime`/`date` or use safe string ordering for ISO dates)—not assume `someField < date()` works on a string.
- **“At risk” / churn / expiry:** Align filters with the user’s intent (e.g. “at risk” may mean **expiring in the next N days** while still active, not **already ended**). Prefer explicit reasoning in `steps`.

**Example output shape** (illustrative only—adapt types and keys to the pruned schema and query):
{{
  "target_node_type": "OrdersTableEntity",
  "display_property_keys": ["status", "total", "created_at_field"],
  "identifier_property_keys": ["external_id", "status"],
  "research_plan": {{
    "goal": "Members: orders matching the user's filter",
    "steps": [
      "Run Cypher: MATCH (n:GraphNode) WHERE n.node_type = 'OrdersTableEntity' AND ... RETURN n.node_id AS node_id, apoc.convert.fromJsonMap(n.properties).status AS status, ... LIMIT 500"
    ],
    "use_p_agent": false,
    "p_agent_instruction": null
  }}
}}

**Query language:** Cypher (Neo4j) only; no SQL.
{cypher_contract}
"""


def get_r_agent_cohort_system_prompt(
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
    schema_narrative: Optional[str] = None,
    pruned_schema: Optional[str] = None,
) -> str:
    """Cohort R-Agent: same vocabulary + contract assembly as chat R-Agent, different task narrative."""
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
    base = R_AGENT_COHORT_SYSTEM.replace("{cypher_contract}", cypher_contract)
    out = base.replace(
        "\n**Query language:**",
        "\n" + vocab + "\n**Query language:**",
        1,
    )
    return _adk_escape_instruction_braces(out)


def build_cohort_r_agent_user_message(
    query: str,
    *,
    organization_id: Optional[UUID] = None,
) -> str:
    """User message for cohort R-Agent (no notebook loop in v1)."""
    now = datetime.now().strftime("%Y-%m-%d (%A)")
    org_line = f"Target Org: {organization_id}" if organization_id else "Target Org: (not set)"
    return f"""## System Context
Current Time: {now}
{org_line}

## User request (define a cohort)
{query}

Respond with valid JSON only matching the CohortRAgentResponse schema (target_node_type, display_property_keys, identifier_property_keys, research_plan with use_p_agent false)."""


R_AGENT_COHORT_PROPERTY_PICK = """You are a schema assistant. From the pruned schema vocabulary below, pick **one** exact `target_node_type` value and a list of **candidate_property_keys** (JSON keys inside `n.properties`) to probe statistically before building a risk score.

Rules:
- Use only node types and property names that appear in the vocabulary.
- Choose 5–15 keys that could matter for the user’s scoring intent (breadth over precision).
- Output JSON only matching CohortPropertyPickResponse: target_node_type, candidate_property_keys.
"""


def get_r_agent_cohort_property_pick_prompt(pruned_schema: Optional[str] = None) -> str:
    """Preflight: node type + keys to probe."""
    vocab = (
        build_pruned_schema_vocabulary(pruned_schema)
        if pruned_schema and pruned_schema.strip()
        else "**Vocabulary:** (empty — infer generic table-like node types if needed.)"
    )
    return _adk_escape_instruction_braces(R_AGENT_COHORT_PROPERTY_PICK + "\n\n" + vocab)


def build_cohort_property_pick_user_message(query: str, *, organization_id: Optional[UUID] = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d (%A)")
    org_line = f"Target Org: {organization_id}" if organization_id else "Target Org: (not set)"
    return f"""## System Context
Current Time: {now}
{org_line}

## User request (scoring cohort — property pick)
{query}

Respond with JSON only: CohortPropertyPickResponse."""


R_AGENT_COHORT_SCORING = """You design a **weighted scoring formula** for a single `node_type` cohort. You receive:
1) Pruned schema vocabulary
2) **distribution_summary** JSON from real aggregates (categorical % and numeric min/max/mean/quartiles per key)

Your JSON must match **CohortScoringRAgentResponse**:
- **target_node_type** (must match vocabulary)
- **components** (list): each element has **four** fields — do not swap or merge them:
  - **property_key** (string)
  - **weight** (number 0–1; all components should sum to ~1.0)
  - **direction** — **EXACTLY one of these three strings, verbatim** (no other value is valid):
    `higher_is_better` | `lower_is_better` | `inverse_linear`
    This field is **not** the normalization kind. **Never** put `categorical_one_hot`, `min_max`, `window`, or `identity` here.
  - **normalization** — object with **type** as **EXACTLY one of**: `min_max` | `window` | `identity` | `categorical_one_hot`, plus **params** from probe stats (e.g. min/max for `min_max`). Categorical / one-hot encoding belongs under **normalization.type** = `categorical_one_hot`, with **direction** still one of the three values above (usually `higher_is_better` for risk if higher encoded score means worse).
- **missing_data_policy**: neutral_partial_score | penalize | exclude
- **cutoff_method**: always **llm_iterated** (threshold refined using score distribution later)
- **display_property_keys** / **identifier_property_keys** for the UI (include final_score and confidence)
- **research_plan**: MUST be a JSON **object** (not a string, not a numbered essay). Required shape: **goal** (short string), **steps** (array of strings, each step one instruction line), **use_p_agent** (boolean, false), **p_agent_instruction** (null). Put implementation bullets inside **steps**, never as one prose blob in **research_plan**.
- Inside that object, describe self-contained work for the Action Agent: vector scoring in Cypher (run_cypher only for math over `apoc.convert.fromJsonMap(n.properties)`), emit **final_score** in [0,1], **confidence** in [0,1], per-component intermediate scores as columns prefixed with **comp_** plus property_key safe suffix. **Steps** must state that the final query **RETURN**s `node_id`, **`final_score`** (or an accepted alias from the A-Agent contract), **`confidence`**, and optional **comp_*** — not components alone without a combined score column.
- **Ordered categories in Cypher:** Mention **apoc.coll.indexOf** or **CASE … WHEN** for rank; never suggest **indexOf** (not valid Neo4j Cypher).

Do not embed domain-specific example labels from any industry; stay generic.

{cypher_contract}
"""


def get_r_agent_cohort_scoring_system_prompt(
    pruned_schema: Optional[str] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
) -> str:
    vocab = (
        build_pruned_schema_vocabulary(pruned_schema)
        if pruned_schema and pruned_schema.strip()
        else ""
    )
    cypher_contract = build_cypher_graph_contract(
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
    )
    base = R_AGENT_COHORT_SCORING.replace("{cypher_contract}", cypher_contract)
    merged = vocab + "\n\n" + base if vocab.strip() else base
    return _adk_escape_instruction_braces(merged)


def build_cohort_scoring_r_user_message(
    query: str,
    distribution_summary: Dict[str, Any],
    *,
    organization_id: Optional[UUID] = None,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d (%A)")
    org_line = f"Target Org: {organization_id}" if organization_id else "Target Org: (not set)"
    dist_json = json.dumps(distribution_summary, default=str, indent=2)[:12000]
    return f"""## System Context
Current Time: {now}
{org_line}

## User request
{query}

## distribution_summary (probe — use for weights and normalization)
```json
{dist_json}
```

Respond with JSON only: CohortScoringRAgentResponse. The **research_plan** field must be an object with keys goal, steps, use_p_agent, p_agent_instruction — not a plain string.
**Per component, `direction` is only** `higher_is_better`, `lower_is_better`, or `inverse_linear`. **Put** `categorical_one_hot` **only under** `normalization.type`, never as `direction`.
**Scoring Cypher result shape (state in steps):** the Action Agent’s final `run_cypher` must return each row with **`node_id`**, a numeric **combined** 0-1 column **`final_score`** (or weighted_score / score / finalScore, etc.), **`confidence`**, and optional **comp_*** for components — not components alone without a rolled-up score."""


R_AGENT_COHORT_CUTOFF = """You set a single **recommended_cutoff** on **final_score** (0.0–1.0) using:
- The user’s goal
- The empirical **score_distribution** JSON (min, max, mean, quantiles, sample size)
- Optional **prior_cutoff** from a previous iteration

Prefer inclusive thresholds that match the user’s intent (e.g. narrow high-risk tail vs broad screening). Output JSON only: CohortCutoffRAgentResponse with recommended_cutoff and short rationale."""


def get_r_agent_cohort_cutoff_system_prompt() -> str:
    """Escaped cutoff R-Agent instructions."""
    return _adk_escape_instruction_braces(R_AGENT_COHORT_CUTOFF)


def build_cohort_cutoff_r_user_message(
    query: str,
    score_distribution: Dict[str, Any],
    *,
    prior_cutoff: Optional[float] = None,
    iteration: int = 0,
    organization_id: Optional[UUID] = None,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d (%A)")
    org_line = f"Target Org: {organization_id}" if organization_id else "Target Org: (not set)"
    sd = json.dumps(score_distribution, default=str, indent=2)[:8000]
    prior = f"{prior_cutoff}" if prior_cutoff is not None else "(none — first pass)"
    return f"""## System Context
Current Time: {now}
{org_line}

## User goal
{query}

## Iteration
{iteration}

## Prior cutoff
{prior}

## score_distribution
```json
{sd}
```

Respond with JSON only: CohortCutoffRAgentResponse."""


def get_a_agent_cohort_scoring_system_prompt(
    node_types: Optional[List[str]] = None,
    rel_types: Optional[List[str]] = None,
    entity_property_shapes: Optional[Dict[str, List[str]]] = None,
    source_type_filter: Optional[str] = None,
    schema_narrative: Optional[str] = None,
    pruned_schema: Optional[str] = None,
) -> str:
    """A-Agent for cohort scoring Cypher."""
    base = get_a_agent_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )
    cohort_block = """
**Cohort scoring mode (strict):**
- Implement the research plan with **run_cypher** only (Neo4j Cypher). **Do not** use `import` except
  `import json` if absolutely needed; the sandbox allows nothing else. Prefer **zero imports**: pass
  the Cypher text as one multiline string argument to `run_cypher(...)` (Python triple-quoted string)
  — no `pandas`, no `math`, no other imports.
- **Python vs Cypher:** Words like `apoc`, `props`, `MATCH`, `WHERE`, and `n` are **only valid inside**
  the string you pass to `run_cypher("...")`. Do **not** use them as Python variable names or as bare
  identifiers outside that string (that causes `NameError: apoc` / `props`). All graph logic belongs
  in Cypher; Python may only call `run_cypher`, read returned row dicts, `print`, `json`, **`safe_div`**, and **`safe_mean`**.
- **No bare `/` in Python:** The sandbox raises **`ZeroDivisionError`** on `a/b` when `b` is 0. Put **all** ratios through **`safe_div(num, den, default=0.0)`** (including `safe_div(x-y, u-v, 0.0)` for ranges). For list averages use **`safe_mean([...])`**, not `sum(...)/len(...)`.
- **Prefer scoring entirely in Cypher** (one `run_cypher`); use Cypher **`CASE`** guards for divide-by-zero as in the graph contract. Avoid post-processing rows in Python except trivial checks.
- If Cypher must contain `"`, avoid breaking Python string literals; use **`run_cypher('''...''')`** as the
  outer delimiter, or a single multiline **`run_cypher(" ... ")`** where the argument is one Python
  triple-quoted string (do not nest raw double-quote triples inside that instruction).
- For each node, compute **final_score** in [0,1] and **confidence** in [0,1] per missing_data_policy.
- Use `apoc.convert.fromJsonMap(n.properties)` **inside the Cypher string**; guard NULLs explicitly.
- **Mandatory RETURN shape (final scoring query):** Every row **must** be a flat table with:
  - **Identity:** `n.node_id AS node_id` (or `AS nodeId`).
  - **Aggregate score (0–1, must be parseable as a number):** **Prefer** a single column named **`final_score`**
    — e.g. `toFloat(<expr>) AS final_score` or `1.0 * <expr> AS final_score`. The system also accepts these
    **alternate aliases** for the same combined score: `weighted_score`, `total_score`, `score`, `risk_score`,
    `finalScore`, `normalized_score`, `aggregated_score`, `cohort_score`, `combined_score`, `overall_score`.
    Do **not** put the **only** combined score under **`comp_*`** — those are **per-component** breakdowns; the
    **rolled-up** 0–1 score must appear under **`final_score`** (best) or one of the alternates above.
  - **Confidence (0–1, parseable number):** `... AS confidence` (or `model_confidence` / aliases the contract allows).
  - **Components (optional):** `comp_<property> AS comp_<sanitized_key>` for each weighted piece.
  If any score could be a string from JSON, wrap with **`toFloat()`** / **`toInteger()`** so the value is numeric, not an unquoted string that fails parsing.
- The last (or only) `run_cypher` used for validation must be this full scoring query (not a bare diagnostic).
- RETURN columns with these exact aliases (snake_case preferred so `WHERE final_score` matches):
  `... AS node_id`, `... AS final_score`, `... AS confidence`, plus one column per component:
  prefix **comp_** + sanitized property_key (alphanumeric) for score breakdown.
  (If you must use camelCase aliases, use **finalScore** / **nodeId** — they are accepted.)
- JSON properties may store dates as strings—parse before temporal compare.
- **Categorical / ordered strings:** Do not use **`indexOf`** in Cypher (invalid). Use **`apoc.coll.indexOf(['active','inactive'], props.status)`** or **`CASE props.status WHEN 'active' THEN 2 WHEN 'inactive' THEN 1 ... END`** for rank-style component scores.
- **Regex / text:** Prefer **`size(apoc.text.regexGroups(props.field, 'pattern'))`** for “has digits” checks—**not** `regexGroups(...).size()`. Keep each **`CASE ... END`** complete in one expression (no orphaned **`WHEN`** lines).
- **Type discipline (must prevent `Can't coerce Long(...) to String`):** Values inside `apoc.convert.fromJsonMap(n.properties)` may be stored as **Long, Double, Boolean, or String**—never assume. Before any **string** op (`substring`, `CONTAINS`, `STARTS WITH`, `ENDS WITH`, `apoc.text.*`, `size(...)` on a string, regex), wrap with **`toString(...)`**. Before any **numeric** op (arithmetic, `<`, `>`, `toFloat`/`toInteger`), ensure the value is numeric (or wrap with `toFloat()` / `toInteger()`). When comparing **epoch-millis timestamps** (Long, typically ≥10 digits), use **numeric comparisons directly** (`props.ends_at < <epoch_ms>`) — do **not** call `date()` / `datetime()` on a Long. When comparing **ISO-8601 date strings**, use string comparison or `apoc.date.parse(toString(props.ends_at), 'ms', 'iso_date')`. Emit safe guards like `CASE WHEN props.ends_at IS NULL THEN 0.0 WHEN props.ends_at =~ '\\\\d+' THEN toFloat(props.ends_at) ELSE toFloat(apoc.date.parse(toString(props.ends_at),'ms','iso_date')) END` when the storage type is unknown.
- **WITH passthrough (must prevent `Variable X not defined`):** In multi-stage Cypher, **every variable referenced after a `WITH` clause must be listed in that `WITH`**. Cypher drops any variable not forwarded. When you compute an intermediate alias (e.g. `toFloat(props.ends_at) AS comp_ends_at`), you **must carry it forward** in every subsequent `WITH` you want to keep using it: `WITH n, comp_ends_at, comp_monthly_amount, props ...`. Do **not** redefine an alias by wrapping it in another function in a later stage (e.g. `toFloat(comp_ends_at) AS comp_ends_at` is wrong if `comp_ends_at` wasn't forwarded — it is undefined at that point). If a component needs several passes, define it in the **first** `WITH` that has access to `props`, then only **pass it through** in later `WITH`s — do not reference `props.<key>` again after `props` is dropped.
- First query may use LIMIT (e.g. 500) for scoring all candidates; a later message may ask to add `WHERE final_score >= $cutoff` using run_cypher(..., params={{"cutoff": <float>}}).
"""
    return _adk_escape_instruction_braces(cohort_block + "\n" + base)
