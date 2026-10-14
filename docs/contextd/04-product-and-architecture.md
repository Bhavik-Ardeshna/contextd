# 04 — Product & Architecture

## What ContextD is, in one paragraph

ContextD is a database. It ingests enterprise data via a 10-step pipeline, transforms raw episodes (emails, messages, tickets, CRM rows) into a structured knowledge graph with bitemporal state and decision lineage, learns from feedback what matters, and serves AI agents structured context windows via an SDK, REST API, MCP server, or any of six wire protocols (Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP). Every fact carries provenance, every retrieval is feedback-weighted, every snapshot is versioned.

## What ContextD IS / IS NOT

| ContextD IS | ContextD IS NOT |
|-------------|-----------------|
| A **database** — stores entities, relationships, facts, decisions, temporal state with ACID transactions | An AI agent — it serves context *to* agents |
| A **context construction engine** — 10-step pipeline transforms raw data into structured knowledge | A workflow tool — it doesn't take actions or automate processes |
| An **AI-native query system** — hybrid retrieval (BM25 + vectors + graph) | A vector database — vectors are 1 of 6 data models |
| A **temporal knowledge system** — bitemporal model | An analytics platform — serves context windows, not dashboards |
| A **learning system** — feedback-weighted graph that gets smarter | A general-purpose DB — opinionated for context assembly |
| **Versionable** — Context Cores = CI/CD for knowledge | A RAG framework — it's the data layer RAG frameworks lack |

---

## The six-layer architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: INTEGRATION                                                     │
│ Python SDK · MCP Server (stdio/SSE/HTTP) · REST API (FastAPI) · GraphQL  │
│ Wire Protocols: Bolt · PostgreSQL · MongoDB · Redis · gRPC · HTTP        │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: RBAC & AUTH                                                     │
│ API Keys (SHA-256) · OAuth 2.0 · Role Scoping · Append-Only Audit Logs   │
│ 6 Roles: Owner · Admin · Editor · Viewer · Agent · Connector             │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: CONTEXTD ENGINE                                                 │
│ 10-Step Ingestion · Hybrid Query Engine · 7-Step Context Assembly       │
│ Feedback EMA · Ontology Engine · Context Cores · Context Resolver        │
│ (cross-source identity stitching with bitemporal Identity Graph)         │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: UNIFIED MULTI-MODEL STORAGE SUBSTRATE                           │
│ Graph + Document + KV + Vector (HNSW/PQ) + Full-Text (BM25)              │
│ + Time-Series (Gorilla XOR) · 70+ SIMD Algorithms · ACID Transactions    │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1.5: CONTEXT FORGE — pre-pipeline mapping layer                     │
│ Source Introspector · Data Profiler · Business Logic Ingester (dbt,     │
│ LookML, SQL views, MetricFlow YAML, Cube.dev, plain-language)            │
│ · Mapping Inference Engine (7 inference passes, confidence-scored)      │
│ · Forge Studio (3-pane review/edit UI) · Forge Mapping (versioned       │
│ msgpack/SHA-256 artifact) · Forge Profiles · Forge-to-Pipeline Bridge   │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: CONNECTOR LAYER                                                 │
│ Airbyte Engine (600+ sources) · Custom SDK Connectors (6 P0 + SDK)       │
│ OAuth2 Service (30+ providers) · Incremental Sync                        │
└──────────────────────────────────────────────────────────────────────────┘
```

> **Layer 1.5 is critical.** Without Context Forge, the 10-step ingestion pipeline treats every source as raw text and falls back on LLM extraction for everything — expensive for structured data, unreliable for enterprise schemas, and disrespectful of the years of dbt models, LookML measures, calculated metrics, and SQL view definitions the customer's analytics team has already written. Context Forge consumes those existing artifacts (introspecting schemas, parsing dbt manifests, ingesting LookML, etc.), proposes a mapping into ContextD primitives, surfaces it in **Forge Studio** for the customer to review and edit, and emits a versioned **Forge Mapping** that configures the pipeline for deterministic extraction on known structures — reserving LLM extraction for genuinely unstructured fields. Detailed in `06-context-forge.md`.

### Layer 1.5 — Context Forge

The pre-pipeline mapping layer. Runs **once per source connection at onboarding** (then incrementally on schema/business-logic changes). Eight components:

1. **Source Introspector** — connects to relational DBs (Postgres, MySQL, SQL Server, Oracle, Snowflake, BigQuery, Databricks, ClickHouse) and SaaS APIs (Salesforce, HubSpot, etc.). Extracts DDL, FK graph, indexes, views, stored procedures, comments.
2. **Data Profiler** — samples actual data; computes cardinality estimates (HyperLogLog), top-K values, null rates, length distributions, regex pattern fits, PII heuristics, cross-column correlations.
3. **Business Logic Ingester** — parses **dbt** projects (manifest.json + sources.yml + schema.yml), **LookML** views/explores/measures, **MetricFlow / Cube.dev** YAML, SQL view definitions, stored procedures, Tableau / Power BI calculated fields, custom YAML/JSON business rules, and plain-language metric definitions (LLM-assisted).
4. **Mapping Inference Engine** — seven inference passes (table→entity-type, FK→relationship, junction-table detection, column→fact-predicate, time-series/audit recognition, derived-metric translation, confidence scoring). Combines schema graph + data profiles + business logic + ontology hints.
5. **Forge Studio** — three-pane review/edit UI (source schema | proposed mapping | graph preview). Inline edits, bulk operations, validation warnings, sample-data trace, smoke-test queries, diff against previous version. The customer **reviews and approves** rather than the system silently committing.
6. **Forge Mapping** — the versioned artifact. msgpack-serialized, SHA-256 content-addressed, immutable once applied (consistent with Context Cores machinery). Diffable, rollbackable.
7. **Forge Profiles** — pre-built mappings for common schemas (Salesforce CRM, HubSpot, Stripe, Shopify, Zendesk, Jira/Linear, dbt+Fivetran-modeled Snowflake, generic OLTP Postgres). Customers fork and customize.
8. **Forge-to-Pipeline Bridge** — the integration point. The 10-step ingestion pipeline reads the Forge Mapping at runtime; Step 3 (Extract Nodes) and Step 6 (Extract Edges) become deterministic for Forge-covered structures, with LLM extraction reserved for unstructured fields. Derived facts are computed using customer-supplied formulas. **LLM cost typically drops 60-80% for enterprise sources with significant structured data.**

Net effect: enterprise-data-warehouse onboarding goes from "30-day proof-of-concept with engineering hand-holding" to "afternoon demo with the customer's actual schema." Detailed in `06-context-forge.md`.

### Layer 1 — Connectors

Two tiers:

- **P0 — Custom-built (high quality):** Gmail, Salesforce, Slack, GitHub, Zendesk, HubSpot. Deep extraction logic — they understand the *semantics* of each source, not just forward raw data. (Gmail extracts thread structure, headers, body, commitments, decisions; creates `person→emailed→person`, `person→committed_to→commitment`, `email→part_of→thread` relationships.)
- **P1 — Airbyte + Quality Layer:** 600+ connectors via Airbyte's open-source catalog with ContextD's quality layer (LLM extraction, ontology constraints, MinHash + cosine dedup, full provenance metadata). Highlighted P1: Notion, Jira, Linear, Google Drive, PostgreSQL, Snowflake, Microsoft Teams, Outlook.

The current repo already has ~40 source connectors live: Airtable, Asana, Attio, Bitbucket, Box, ClickHouse, ClickUp, Confluence, Dropbox, GitHub, GitLab, Gmail, Google Calendar/Docs/Drive/Slides, HubSpot, Jira, Linear, Monday, Notion, OneDrive, OneNote, Outlook Calendar/Mail, Pipedrive, PostgreSQL, Salesforce, SharePoint, Shopify, Slack, Stripe, Teams, Todoist, Trello, Word, Zendesk, Zoho CRM.

**OAuth2** is built once — 30+ providers reuse it. Tokens encrypted at rest, rotated automatically.

### Layer 2 — Unified Multi-Model Storage Substrate

This is the technical bet. Instead of stitching Neo4j + Pinecone + Postgres + Redis, we run a **single ACID engine** with all six data models native:

| Data model | What it powers | Implementation |
|------------|----------------|----------------|
| **Graph** | Cypher / Gremlin / SQL traversals; 70+ SIMD-accelerated algorithms (PageRank, Louvain, Label Propagation, shortest path, betweenness) | ArcadeDB graph engine, Java 21 Vector API |
| **Vector** | HNSW nearest-neighbor with Product Quantization (~4× memory compression); cosine / Euclidean / Manhattan | LSMVector (jvector), Apache 2.0 |
| **Full-Text** | BM25 keyword search alongside cosine; powers BM25 leg of hybrid retrieval | Lucene |
| **Document** | JSON storage for entity attributes, episode metadata, ontology schemas | Schema-flexible |
| **Key-Value** | Session data, API key caches, configuration; O(1) lookups | LSM-tree |
| **Time-Series** | Bitemporal evolution tracking; InfluxDB line protocol, Prometheus remote_write/read, PromQL | Gorilla XOR compression |

ACID transactions span all models. **A single transaction can update an entity, write its embedding to the HNSW index, append a fact to the time-series, and update the audit log atomically.** No incumbent can do this.

### Layer 3 — ContextD Engine (the intelligence layer)

This is what we build on top of the substrate. Each subsystem is detailed in `08-core-technology.md`:

- **10-step ingestion pipeline**: create episode → retrieve context → extract nodes → resolve deterministic → resolve semantic + LLM → extract edges → dedup/supersede edges → embed → save → community detect.
- **Context Resolver** : productized cross-source identity stitching. Two paths sharing one Identity Graph artifact. **Path 1 (deterministic)** — for structured sources with stable IDs (Snowflake PKs, Salesforce IDs, Stripe `cus_*`), Context Forge handles resolution as a join. **Path 2 (probabilistic)** — for heterogeneous and unstructured sources where the same person appears as an email, Slack ID, GitHub author, and a free-text mention, the Resolver Engine runs a six-stage pipeline: HNSW + LSH blocking → Fellegi-Sunter probabilistic record linkage with EM-learned m/u-probabilities → cross-encoder transformer matching (DITTO-style, fine-tuned per domain) → cross-document coreference resolution for free-text mentions (e2e-coref / CDCR with NER via GLiNER / RoBERTa) → Probabilistic Soft Logic transitive closure on a bitemporal Identity Graph → active-learning + LLM adjudication for the hardest residual ~1-2%. Outputs a confidence-weighted, audit-traceable Identity Graph linking canonical entities to source-record-IDs across every connected source. Components: Resolver Engine, Identity Graph, Resolver Studio (review surface), Resolver Profiles (per entity type), Resolver-to-Pipeline Bridge. Detailed in `07-context-resolver.md`.
- **Hybrid query engine** (BUILDING on substrate): BM25 + cosine + BFS in parallel, 5 reranker strategies, 15 composable strategies.
- **7-step context assembly**: parse intent → seed selection → hybrid search → rerank → feedback weights → budget-aware temporal pruning → serialize.
- **Streaming EMA feedback engine**: every node and edge carries a feedback weight, updated via streaming exponential moving average (α=0.1).
- **Ontology engine**: embed ontology elements, vector-route per chunk, inject into LLM prompts at extraction time. Validate output against class filters, domain/range, cardinality, disjoint classes.
- **Context Cores**: content-addressed (SHA-256), msgpack-serialized, immutable graph snapshots. Build / test / promote / rollback. CI/CD for knowledge.

### Layer 4 — RBAC & Auth

Six roles (Owner, Admin, Editor, Viewer, Agent, Connector) with three scoping dimensions (sources, entity types, tags). Multi-tenant isolation via separate substrate database per tenant. SHA-256 hashed API keys, never plaintext, revocable. Append-only immutable audit log retained 1 year (free) → 7 years (enterprise). Detailed in `13-integration-deployment-security.md`.

### Layer 5 — Integration

Multiple ways for an agent or app to plug in:

- **Python SDK** — embedded (`pip install contextd`) or server / cloud client.
- **MCP Server** — two-layer: substrate built-ins + ContextD context tools. stdio (Claude Code, Cursor, Windsurf), SSE (web frameworks), HTTP (serverless).
- **REST API** — FastAPI, auto-generated OpenAPI.
- **Wire Protocols** — Bolt (existing Neo4j drivers in 5+ languages), PostgreSQL (psql, BI tools, JDBC, SQLAlchemy), MongoDB (PyMongo, Mongoose), Redis (KV), gRPC (high-perf inter-service), HTTP/REST. **One instance speaks all six simultaneously.**

---

## Today's stack vs tomorrow's stack

The current production stack has shipped product and proven the use case. The future stack is the strategic bet that makes the moat compound.

### Today (LIVE in this repo)

```
Frontend         React + TypeScript + ShadCN
Backend          FastAPI (Python 3.13)
Metadata         PostgreSQL
Graph + FTS      Neo4j (Lucene-backed full-text + Cypher graph)
Vectors          Milvus
Cache / sessions Redis
Workers          Temporal (durable orchestration)
Connectors       ~40 live sources, P0 + Airbyte-style
LLMs             OpenAI (gpt-4o, embed-text-3-small) + Anthropic (Claude)
Observability    OpenTelemetry + Prometheus + PostHog
Deployment       Docker Compose (dev), K8s (planned for prod)
```

This stack ships features today: ingestion pipelines, entity resolution, feedback EMA, OAuth, chat/RAG with streaming, and a search service that orchestrates BM25 (Neo4j) + vector (Milvus) + graph traversal (Neo4j Cypher). Multi-tenant. Multi-source.

### Tomorrow (the unified ContextD on a multi-model substrate)

```
Frontend         (unchanged — React + ShadCN)
Backend          (unchanged — FastAPI)

★★★ Unified substrate ★★★
  ArcadeDB (Apache 2.0)
    ├── Graph + Cypher                  (replaces Neo4j)
    ├── HNSW + PQ vectors               (replaces Milvus)
    ├── Lucene BM25 full-text           (replaces Neo4j FTS)
    ├── JSON document storage           (alongside metadata in Postgres)
    ├── Key-Value                       (alongside Redis)
    └── Gorilla XOR time-series         (new capability)
  + ContextD intelligence layer
    ├── Bitemporal schema (event time + transaction time)
    ├── 10-step ingestion pipeline (with full provenance)
    ├── 5-phase entity resolution (cascade)
    ├── 7-step context assembly (with token budgeting)
    ├── Streaming EMA feedback engine (α=0.1)
    ├── Ontology engine
    └── Context Cores (CI/CD for knowledge)

Workers          Temporal (kept — durable orchestration is orthogonal)
Cache            Redis (kept — substrate read-cache for hot paths)
Postgres         (kept — tenant metadata, billing, account info)
```

### Why migrate

| Driver | Quantified impact |
|--------|-------------------|
| **ACID across data models** | Eliminates an entire class of consistency bugs. Today: write to Milvus succeeds, Neo4j fails. Tomorrow: atomic. |
| **Operational consolidation** | One database to patch, monitor, back up. Headcount allocation shifts from infra to product. |
| **Bitemporal at schema level** | Today: bolted on via columns; complex to query. Tomorrow: native — every retrieval is bitemporal-aware. |
| **Wire-protocol polyglot** | Today: customers must use our SDK. Tomorrow: any existing Neo4j / pgsql / Mongo client just works. |
| **License cost** | No Neo4j Enterprise, no Pinecone usage tier, no Milvus support contract. All Apache 2.0. |
| **Latency** | Today: 3-5 network hops per query. Tomorrow: in-process traversal across data models. |
| **Substrate-native graph algorithms** | 70+ SIMD-accelerated (PageRank, Louvain, etc.) without ETL into a separate analytics tool. |

### Why we kept the multi-DB stack first

Pragmatism. Building the unified substrate from day zero would have meant 18 months before anyone could *use* ContextD. Instead we:

1. Stitched battle-tested components (Neo4j + Milvus + Postgres + Redis + Temporal) → shipping product in months
2. Validated the demand (connectors used, queries served, customers paying)
3. Benchmarked the substrate candidate (ArcadeDB) under our actual workload to know exactly what we're getting into (see `09-benchmarks-and-validation.md`)
4. Now consolidate the stack on a substrate we have empirical data on, *not* an assumption

This is how Snowflake, Databricks, and Confluent built infrastructure. Validate the use case first; rebuild the substrate when the customer pull is undeniable.

---

## The closed loop — how data actually flows

```
CONNECTOR        CONTEXT FORGE              INGESTION PIPELINE                    QUERY ENGINE
Snowflake ─┐                                                                     Natural Language Query
Postgres  ─┤   ┌─ Introspect ─┐                                                         │
SFDC      ─┼─►├─ Profile ─────┼─► Atlas        ┌─ Step 1: Episode                      ▼
HubSpot   ─┤   ├─ Ingest BL ──┤   Mapping ───►├─ Step 2: Retrieve Context         1. Parse Intent
Gmail*    ─┤   ├─ Infer (7) ──┤  (versioned    ├─ Step 3: Extract ◄── Atlas+Onto  2. Hybrid Search ◄── feedback
Slack*    ─┘   └─ Studio  ────┘   msgpack +     │   (deterministic for Atlas-      3. Rerank ◄── feedback
                       ↑          SHA-256)       │    covered sources, LLM for      4. Apply Feedback Weights
                  Customer review                │    free-text fields)             5. Budget-Aware Pruning
                  / edit / approve               ├─ Step 4: Resolve (det.)          6. Temporal Enrichment
                                                  ├─ Step 5: Resolve (sem.+LLM)     7. Assemble Context Window
                                                  ├─ Step 6: Edges ◄── Atlas+Onto         │
                                                  ├─ Step 7: Dedup/Invalidate              │
                                                  ├─ Step 8: Generate Embeddings           ▼
                                                  ├─ Step 9: Save ──────────────► ASSEMBLED CONTEXT
                                                  ├─ Forge-derived facts (formulas)       │
                                                  └─ Step 10: Community Detection         ▼
                                                                                   Agent rates (1-5)
              CONTEXT CORES                                                              │
              Build  ◄── Snapshot ◄── Graph Storage                                      ▼
              Test   ◄── Query Suite                                              EMA Weight Update
              Promote ──► Production                                              per node & edge
              Rollback ◄── Previous Version                                              │
                                                                                          ▼
                                                                                  Graph Storage

* Gmail, Slack, and other unstructured sources don't typically have schemas to introspect.
  They bypass Context Forge and use LLM extraction directly. Atlas is for structured sources
  (data warehouses, OLTP DBs, SaaS APIs with schema endpoints).
```

The feedback loop closes the system. The Context Forge loop ensures the customer's analyst-team work is honored at ingestion time. Every retrieval informs the next.

---

## Walking an enterprise data warehouse through the entire system

Concrete end-to-end trace. The customer is a B2B SaaS company connecting their **Snowflake** production data warehouse — 47 tables, 1.2 B rows, 218 declared FKs, governed by a 150-model **dbt** project with 30 dbt-Semantic-Layer metrics. Their analytics team has spent two years encoding business definitions of *active customer*, *MRR*, *NPS*, *health score*, *LTV*, etc. They are not going to re-derive any of that.

This walkthrough shows what happens from the moment they hit "Connect" to the moment a Customer Success Manager opens a renewal call brief.

### Step 1 — Source connection

The customer creates a read-only Snowflake service account and connects it to ContextD. They also point ContextD at their dbt repo:

```python
db.sources.connect(
    name="acme-prod",
    kind="snowflake",
    account="acme.us-east-1.snowflakecomputing.com",
    warehouse="ANALYTICS_WH",
    database="PROD",
    schema="ANALYTICS",
    role="CONTEXTD_READER",
    auth=KeyPairAuth(...),
    business_logic=DbtProject(repo="github.com/acme/analytics-dbt", branch="main"),
)
```

### Step 2 — Context Forge introspects + profiles + parses dbt (the pre-pipeline layer)

The **Source Introspector** reads `INFORMATION_SCHEMA`: 47 tables, 218 FKs, 12 views, 8 stored procedures. The **Data Profiler** samples 10 K rows per table — HyperLogLog cardinality, top-K values, regex pattern fits, PII heuristics. The **Business Logic Ingester** parses the dbt project: `manifest.json` + `sources.yml` + `schema.yml` + 30 metric definitions in MetricFlow YAML.

### Step 3 — Mapping Inference Engine produces a candidate Forge Mapping

Seven inference passes run on the schema graph + data profiles + business logic. Output:

```
12 entities      — customer, account, contact, deal, subscription, product, invoice,
                   payment, ticket, address, campaign, tag
18 relationships — 15 derived from declared FKs, 3 from junction-table detection
                   (e.g., account_contacts → bidirectional has_contact)
94 fact predicates — has_email (PII), has_industry, has_arr, has_seat_count,
                     has_contract_start, has_renewal_date, has_nps, ...
30 derived facts  — has_ltv, has_mrr, has_health_status, has_churn_risk, ...
                    (formulas preserved verbatim from dbt models)
3 episode types   — login_events, subscription_events, support_messages
1 warning         — table legacy_orders has no PK
2 needs-review    — self-referencing FK on dim_users.manager_id (ambiguous direction)
```

### Step 4 — Customer reviews in Forge Studio

The customer's data lead opens **Forge Studio** (three-pane UI: source schema | proposed mapping | graph preview). Spends ~90 minutes:

- Accepts most inferences as-is.
- Edits the two `manager_id` self-references → confirms direction is `reports_to` (not `manages`).
- Bulk-applies a rule: *"all `*_log` tables → episodes."*
- Adds a custom override for the internal `pricing_decisions` table → maps to `Decision` entities (with the bitemporal columns `effective_from` / `superseded_at` driving `valid_at` / `invalid_at`).
- Runs three smoke-test queries directly in Studio. Validates that `LTV` comes from the dbt formula (not LLM-guessed).
- Hits **Apply**.

### Step 5 — Forge Mapping v1 saved

```
forge_mapping:acme-prod:v1
sha256: e8a91f2c4d7b...
size: 184 KB (msgpack)
entities: 12, relationships: 18, facts: 94, derived_facts: 30, episodes: 3
ontology_baseline: crm-ontology-v3
```

The artifact is content-addressed, immutable, diffable against future versions, and rollback-capable — same machinery as Context Cores.

### Step 6 — Pipeline ingests using the Forge Mapping

The 10-step pipeline kicks off the initial backfill. For Forge-covered tables, extraction is **deterministic** (no LLM call). For free-text columns (`notes`, `ticket_body`), LLM extraction still runs.

A single row from `dim_customers`:

```sql
customer_id   = "a3f4b1c2-..."
account_id    = "e8a91f2c-..."           -- FK to dim_accounts
email         = "alice.chen@acme.com"
created_at    = 2025-06-15 09:14:00
last_login    = 2026-04-25 11:32:00
monthly_revenue = 4_800.00
retention_rate  = 0.92
product_tier    = "enterprise"
health_status   = "active"               -- dbt-derived
ltv             = 60_000.00              -- dbt-derived (formula preserved)
notes           = "Migrated from Beta Corp on 2025-06; champion: Sarah Park (CTO)"
```

becomes (deterministically, via the Forge Mapping):

```
Customer entity {
  id: "a3f4b1c2-...",
  entity_type: "customer",
  source: "snowflake.dim_customers",
  source_pipeline: "forge_v1",
  extraction_method: "forge_deterministic",
  feedback_weight: 0.5,
  valid_at:  2025-06-15        -- from created_at
  invalid_at: null
}

Edge: Customer ─belongs_to_account→ Account(e8a91f2c-...)

Facts (deterministic, from Forge Mapping):
  has_email         = "alice.chen@acme.com"   (PII)
  has_monthly_revenue = 4800
  has_product_tier  = "enterprise"
  has_health_status = "active"               (Forge-derived from dbt)
  has_ltv           = 60_000.00              (Forge-derived from dbt formula
                                              AVG(monthly_revenue) / NULLIF(1 - retention_rate, 0))

Fact (LLM extracted, from free-text notes column):
  acquired_via      = "migration_from_beta_corp"  (extraction_method: llm_extraction)

Edge (LLM extracted, mentions another entity):
  Customer ─championed_by→ Contact(Sarah Park)
```

A row from the junction table `account_contacts(account_id, contact_id, role, since_date)`:

```
Account ─has_contact→ Contact (properties: { role: "primary_technical", since_date: 2025-06-15 })
```

A row from `customer_login_events(event_id, customer_id, timestamp, device, ip, success)` becomes:

```
Episode {
  id: <event_id>,
  source: "snowflake.customer_login_events",
  episode_type: "json",
  affected_entity: Customer(a3f4b1c2-...),
  valid_at: 2026-04-25 11:32:00,
  metadata: { device, ip, success }
}
```

Across the full backfill: **1.2 B rows → 38 M entities + 142 M facts + 8 M episodes**, with provenance on every element. **Embeddings** are computed for entity names + relationship facts + community summaries (substrate HNSW index).

### Step 7 — Bitemporal supersession in flight

Two months later, `dim_customers` updates:

```sql
UPDATE dim_customers
   SET monthly_revenue = 5_400.00,
       retention_rate  = 0.94,
       health_status   = 'expansion_ready'
 WHERE customer_id = 'a3f4b1c2-...';
```

Forge picks up the change via incremental sync. The pipeline applies bitemporal supersession:

```
Old fact: Customer.has_monthly_revenue = 4800
          → expired_at  = 2026-06-23 (when we picked up the change)
          → invalid_at  = 2026-06-22 (when it stopped being true in the warehouse)

New fact: Customer.has_monthly_revenue = 5400
          → valid_at    = 2026-06-22, created_at = 2026-06-23

Forge-derived has_ltv recomputed: 60_000 → 90_000  (formula re-applied to new inputs)
```

Both old and new facts coexist. Auditors can query *what we knew on a specific date* against either dimension.

### Step 8 — Three months later, a CSM prepares for a renewal call

```python
context = db.get_context(
    query="Prepare me for the Acme renewal call — what's their current health, recent changes, and key stakeholders?",
    max_tokens=2000,
    include_lineage=True,
)
```

The Context Assembly engine parses intent → identifies *Acme Account* as the seed (BM25 hits "Acme", cosine hits "Acme Corp" via embedding) → runs BFS 2 hops → RRF reranks → applies feedback weights → fills the 2000-token budget. Returns:

```json
{
  "primary_entities": [
    {"name": "Acme Corp", "type": "account",
     "facts": {"industry": "Technology", "arr": "$3.6M", "seat_count": 750,
               "nps": 68, "renewal_date": "2026-09-15"}},
    {"name": "Alice Chen", "type": "customer",
     "facts": {"email": "alice.chen@acme.com", "tier": "enterprise",
               "health_status": "expansion_ready", "ltv": 90000}},
    {"name": "Sarah Park", "type": "contact",
     "facts": {"role": "CTO", "primary_technical": true, "since": "2025-06-15"}}
  ],
  "relationships": [
    "Alice Chen ─belongs_to_account→ Acme Corp",
    "Acme Corp ─has_contact→ Sarah Park (primary_technical, since 2025-06-15)",
    "Alice Chen ─championed_by→ Sarah Park"
  ],
  "temporal_context": {
    "as_of": "2026-09-04",
    "recent_changes": [
      "Monthly revenue: $4,800 → $5,400 (2026-06-22)",
      "Health status: active → expansion_ready (2026-06-22)",
      "LTV: $60K → $90K (Forge-derived recompute)"
    ]
  },
  "decision_history": [
    {"subject": "Acme 12% volume discount",
     "outcome": "Approved Q1 2026 + net-60 exception",
     "decided_by": "Jordan Blake (VP Sales)",
     "policy": "volume_discount_v3.2",
     "informed_by": ["fct_account_economics", "competitive_analysis_q1"]}
  ],
  "saga_summary": "Acme migrated from Beta Corp June 2025. 12% renewal discount approved Q1 2026. Health upgraded to expansion_ready Q2 2026 after revenue grew 12.5%. Renewal due 2026-09-15. CTO Sarah Park is technical champion.",
  "sources": ["snowflake.dim_customers", "snowflake.dim_accounts",
              "snowflake.fct_customer_metrics (dbt-derived)",
              "snowflake.account_contacts", "internal.pricing_decisions",
              "salesforce.opportunities", "zendesk.tickets"],
  "metadata": {
    "tokens_used": 1847,
    "tokens_saved_vs_chunk_rag": 7353,
    "entities_traversed": 23,
    "search_recipe": "COMBINED_HYBRID_SEARCH_RRF",
    "query_latency_ms": 142,
    "avg_feedback_weight": 0.71
  }
}
```

The CSM walks into the call with the dbt-derived health status, the bitemporal change history, the decision lineage of last quarter's discount approval, the technical champion's name and tenure — assembled in 142 ms across structured warehouse data and external sources, with the customer's *own* business definitions of LTV and health driving the answer.

### Step 9 — Feedback closes the loop

```python
await db.feedback(
    session_id="sess_csm_8821",
    query_id="q_renewal_acme",
    score=5,
    used_entities=["acme_account_uuid", "alice_chen_uuid", "sarah_park_uuid"],
    used_edges=["alice_belongs_to_acme", "acme_has_contact_sarah"],
)
```

Each entity and edge mentioned gets an EMA update: `weight ← weight + 0.1 × (1.0 − weight)`. After 30 successful renewal calls referencing the same entity patterns, the graph has learned which Snowflake-derived facts matter most for renewal preparation — and prioritizes those in future similar queries.

### Step 10 — Cost line, post-Forge

For Acme's full warehouse backfill + 6 months of incremental ingestion:

| | LLM-only baseline | With Forge | Reduction |
|---|---:|---:|---:|
| Backfill (1.2 B rows) | $47,000 | $4,800 | **89.8 %** |
| Monthly incremental (~30 M rows / month) | $1,170 / mo | $112 / mo | **90.4 %** |
| Annual run-rate | ~$60,000 | ~$6,200 | **89.7 %** |

The savings come from deterministic extraction on Forge-covered structures; LLM cost is preserved only for genuinely unstructured fields (free-text `notes`, `ticket_body`, etc).

### What this end-to-end trace demonstrates

- **Context Forge** consumes the customer's existing analytics investment (dbt + LookML + SQL views) and turns it into a deterministic, customer-reviewable mapping into ContextD primitives — *without re-deriving* business logic via LLM.
- **The 10-step pipeline** runs hybrid: deterministic for Forge-covered structures, LLM for unstructured fields. Provenance on every element distinguishes the two.
- **Bitemporal supersession** keeps the entire history of every fact queryable. Auditors can ask *what we knew when* against both event time and transaction time.
- **Decision lineage** as first-class entities makes regulatory queries trivial. Discount approvals link back to the policy, the inputs, the exception, and the affected accounts.
- **Hybrid retrieval** assembles a structured 1,847-token context window from a multi-source unified graph in 142 ms — replacing the ~9,000-token chunk-RAG output that would otherwise be required.
- **Feedback weights** compound over time. Within 30 successful renewal-prep queries, the graph has learned which Snowflake-derived signals matter most.

This loop — from enterprise warehouse → Forge Mapping → deterministic structured graph → assembled context → feedback → smarter graph — is the entire product in motion at enterprise scale.

---

*Continue to `08-core-technology.md` for the deep-dive on each subsystem, `09-benchmarks-and-validation.md` for measured performance, or `06-context-forge.md` for the Forge architecture in detail.*
