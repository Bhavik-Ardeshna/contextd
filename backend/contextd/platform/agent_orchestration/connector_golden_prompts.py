"""Connector-specific golden Cypher / RESEARCH_PLAN examples for GLM agents.

Used when a collection has exactly one source whose short_name is in
CONNECTORS_WITH_DYNAMIC_GOLDEN. Examples use **graph** ``node_type`` strings as produced
by sync (``NormalizedEntity.entity_type``, i.e. Pydantic class names such as
``GmailMessageEntity`` — not ``EntityMetadata.default_graph_node_type`` ``*Node`` labels).

Traversals use anonymous :RELATES_TO (no r.relationship_type filters in these blocks).

Structured / warehouse / multi-source collections keep the default golden block in prompts.py.
"""

from __future__ import annotations

from typing import FrozenSet, List, Optional

# Connector short_name values (see contextd.platform.sources.*) that get custom golden text.
CONNECTORS_WITH_DYNAMIC_GOLDEN: FrozenSet[str] = frozenset(
    {"gmail", "notion", "google_calendar", "hubspot"}
)


def resolve_primary_connector(source_types: List[str]) -> Optional[str]:
    """If the collection has a single connector and it is one we specialize, return its short_name."""
    if not source_types:
        return None
    normalized = sorted({(s or "").strip().lower() for s in source_types if (s or "").strip()})
    if len(normalized) != 1:
        return None
    key = normalized[0]
    return key if key in CONNECTORS_WITH_DYNAMIC_GOLDEN else None


# --- A-Agent: compact Cypher golden block (no r.relationship_type filters) ---

_A_GMAIL = """
**Gmail graph examples** (messages: `GmailMessageEntity`; people: `PersonNode`. Thread entities do not create graph nodes—group by `thread_id` in properties if needed.) Traverse with `-[:RELATES_TO]-` or `-[]-`; do not filter `r.relationship_type` unless the research plan explicitly requires disambiguation.

1) List recent messages — synced JSON uses `name` (subject line), `description` (snippet preview), `created_at` (sent time):
   MATCH (m:GraphNode)
   WHERE m.node_type = 'GmailMessageEntity'
   WITH m, apoc.convert.fromJsonMap(m.properties) AS props
   WHERE props IS NOT NULL
   RETURN m.node_id, props.name AS subject_line, props.description AS snippet_preview
   LIMIT 50

2) Count messages linked to people (anonymous edge; node_type only):
   MATCH (m:GraphNode)-[:RELATES_TO]-(p:GraphNode)
   WHERE m.node_type = 'GmailMessageEntity' AND p.node_type = 'PersonNode'
   RETURN count(DISTINCT m) AS message_count
"""

_A_NOTION = """
**Notion graph examples** (pages: `NotionPageEntity`.) Anonymous edges unless the plan requires semantic disambiguation.

1) Pages matching title or rolled-up properties text (`description` holds properties_text-style text from sync):
   MATCH (n:GraphNode)
   WHERE n.node_type = 'NotionPageEntity'
   WITH n, apoc.convert.fromJsonMap(n.properties) AS props
   WHERE props IS NOT NULL AND (
     toLower(coalesce(props.name, '')) CONTAINS 'roadmap'
     OR toLower(coalesce(props.description, '')) CONTAINS 'roadmap'
   )
   RETURN n.node_id, props.name AS title
   LIMIT 40

2) Count Notion pages:
   MATCH (n:GraphNode)
   WHERE n.node_type = 'NotionPageEntity'
   RETURN count(n) AS page_count
"""

_A_CALENDAR = """
**Google Calendar graph examples** (events: `GoogleCalendarEventEntity`; calendars: `GoogleCalendarCalendarEntity` / list entries: `GoogleCalendarListEntity`.)

1) Events — title is stored as `name`; start time uses `start_datetime` and/or all-day `start_date`:
   MATCH (e:GraphNode)
   WHERE e.node_type = 'GoogleCalendarEventEntity'
   WITH e, apoc.convert.fromJsonMap(e.properties) AS props
   WHERE props IS NOT NULL
   RETURN e.node_id, props.name AS title, coalesce(props.start_datetime, props.start_date) AS start_time
   LIMIT 50

2) Count events:
   MATCH (e:GraphNode)
   WHERE e.node_type = 'GoogleCalendarEventEntity'
   RETURN count(e) AS event_count
"""

_A_HUBSPOT = """
**HubSpot graph examples** (tickets: `HubspotTicketEntity`. HubSpot CRM fields usually live in the nested map `properties` inside the JSON blob, alongside top-level fields like `subject`.)

1) Tickets — top-level `subject`; stage often at `properties.hs_pipeline_stage` (confirm in pruned schema):
   MATCH (t:GraphNode)
   WHERE t.node_type = 'HubspotTicketEntity'
   WITH t, apoc.convert.fromJsonMap(t.properties) AS props
   WHERE props IS NOT NULL
   WITH t, props, coalesce(props.properties, {}) AS hub
   RETURN t.node_id, hub.hs_pipeline_stage AS stage, props.subject AS subject
   LIMIT 50

2) Count tickets by pipeline stage bucket:
   MATCH (t:GraphNode)
   WHERE t.node_type = 'HubspotTicketEntity'
   WITH t, apoc.convert.fromJsonMap(t.properties) AS props
   WITH coalesce(props.properties, {}) AS hub, t
   WITH coalesce(hub.hs_pipeline_stage, 'unknown') AS bucket, count(t) AS cnt
   RETURN bucket, cnt
   ORDER BY cnt DESC
"""

CONNECTOR_A_GOLDEN: dict[str, str] = {
    "gmail": _A_GMAIL,
    "notion": _A_NOTION,
    "google_calendar": _A_CALENDAR,
    "hubspot": _A_HUBSPOT,
}


def get_connector_a_golden_block(connector_short_name: Optional[str]) -> Optional[str]:
    """Return A-Agent golden Cypher block for this connector, or None to use structured defaults."""
    if not connector_short_name:
        return None
    return CONNECTOR_A_GOLDEN.get(connector_short_name.strip().lower())


# --- R-Agent: one RESEARCH_PLAN JSON line per connector ---

_R_GMAIL = """
**Connector-specific RESEARCH_PLAN example (Gmail):**
User: "How many emails did I get last week?"
{ "response_type": "research_plan", "research_plan": { "goal": "Count Gmail messages in the last 7 days.", "steps": [ "Run Cypher: node_type 'GmailMessageEntity', filter using apoc.convert.fromJsonMap(n.properties).created_at (or date field names from the pruned schema) for the last 7 days.", "Use RetrieveNode(text) only if the user asked by vague topic and seed IDs are needed first." ], "use_p_agent": true, "p_agent_instruction": "Bar chart of message count per day for the last 7 days." } }
"""

_R_NOTION = """
**Connector-specific RESEARCH_PLAN example (Notion):**
User: "What pages mention the roadmap?"
{ "response_type": "research_plan", "research_plan": { "goal": "Find Notion pages whose title or properties text matches the topic.", "steps": [ "Run Cypher on node_type 'NotionPageEntity' with apoc.convert.fromJsonMap(n.properties) (keys like name, description) or use RetrieveNode(text) for exploratory search.", "NodeInfo on returned node_ids for full page properties." ], "use_p_agent": true, "p_agent_instruction": "Bar chart of match counts by parent workspace or tag if columns exist; else a single summary table." } }
"""

_R_CALENDAR = """
**Connector-specific RESEARCH_PLAN example (Google Calendar):**
User: "Show meetings this month by day."
{ "response_type": "research_plan", "research_plan": { "goal": "Aggregate calendar events per day for the current month.", "steps": [ "Run Cypher: node_type 'GoogleCalendarEventEntity', use start_datetime / start_date keys inside apoc.convert.fromJsonMap(n.properties) per pruned schema.", "Filter date range in Cypher parameters (e.g. $start, $end)." ], "use_p_agent": true, "p_agent_instruction": "Line or bar chart of event count by day." } }
"""

_R_HUBSPOT = """
**Connector-specific RESEARCH_PLAN example (HubSpot):**
User: "Open tickets by pipeline stage."
{ "response_type": "research_plan", "research_plan": { "goal": "Break down HubSpot tickets by pipeline or stage field.", "steps": [ "Run Cypher: node_type 'HubspotTicketEntity'; read stage/status from the nested HubSpot properties map (e.g. properties.hs_pipeline_stage) inside apoc.convert.fromJsonMap(n.properties), using exact keys from the pruned schema.", "Return stage/bucket and count." ], "use_p_agent": true, "p_agent_instruction": "Pie or bar chart of ticket count by stage." } }
"""

CONNECTOR_R_EXAMPLE: dict[str, str] = {
    "gmail": _R_GMAIL,
    "notion": _R_NOTION,
    "google_calendar": _R_CALENDAR,
    "hubspot": _R_HUBSPOT,
}


def get_connector_r_example_block(connector_short_name: Optional[str]) -> str:
    """Return extra R-Agent example text, or empty string."""
    if not connector_short_name:
        return ""
    return CONNECTOR_R_EXAMPLE.get(connector_short_name.strip().lower(), "")
