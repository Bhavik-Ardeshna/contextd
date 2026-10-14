# 06 — Context Forge: The Pre-Pipeline Mapping Module

> **What this file is.** The deep-dive on Context Forge — the layer that sits between raw enterprise data sources and the ContextD ingestion pipeline. Context Forge is **how an enterprise DB, data warehouse, or SaaS schema becomes a ContextD-shaped knowledge graph without throwing away the work the customer's analyst team has already done.**
>
> **Why this matters.** Without Context Forge, the 10-step pipeline (`08-core-technology.md`) treats every source as raw text and relies on LLM extraction for everything — expensive for structured data, unreliable for enterprise schemas, and disrespectful of years of dbt models, LookML files, calculated metrics, and SQL view definitions the customer's analytics team already wrote. Context Forge is the missing middle layer that consumes those existing artifacts and produces a deterministic, customer-reviewable, versionable mapping into ContextD primitives.
>
> **One-line summary.** Context Forge turns *"here's my Snowflake / Postgres / Salesforce / dbt project"* into *"here's a graph schema that respects every FK, formula, calculated field, and business rule you've already defined — and you can edit it before we ingest a single row."*

---

## Why Context Forge exists (the gap in the original flow)

The original architecture documented in `04-product-and-architecture.md` and `08-core-technology.md` describes a 10-step ingestion pipeline that goes:

```
Raw Episode → LLM Extract Nodes → Resolve → LLM Extract Edges → Embed → Save
```

This works beautifully for **unstructured sources** (Gmail threads, Slack messages, support ticket bodies). It fails for **structured enterprise sources** in three ways:

### Failure 1 — It ignores schema knowledge that already exists

A typical enterprise customer arrives with:

- **A Postgres OLTP** with 40 tables, 200 foreign keys, dozens of indexes, business-critical views and stored procedures that took years to design.
- **A Snowflake data warehouse** with a 150-model dbt project. The dbt project has manifest.json with full lineage, sources.yml describing source freshness, schema.yml with column-level tests, and ~30 metric definitions in dbt Semantic Layer / MetricFlow YAML.
- **A LookML model** with 20 explores, 100+ measures, 200+ dimensions encoding business definitions of "active customer", "monthly recurring revenue", "churn", etc.
- **A Salesforce schema** with custom objects, custom fields, and validation rules describing the company's specific deal stages, opportunity types, and approval workflows.

If we ignore all of this and let an LLM re-derive entity types and relationships from scratch, three things go wrong:

1. **Wasted analyst work.** The customer's team spent quarters encoding business rules into dbt and LookML. Re-deriving via LLM means we discard that work and probably get it wrong.
2. **Inconsistent extraction.** The LLM might call a row in `dim_customers` a `Customer` entity in one ingestion and a `Person` entity in the next. The customer's own definitions are stable; ours wouldn't be.
3. **Wrong relationships.** A junction table `account_contacts` is a many-to-many between `accounts` and `contacts`. An LLM looking at a single row of this table sees a record with two foreign keys — it doesn't know this is a relationship table, not an entity. It might create a `AccountContact` entity instead of recognizing `Account ↔ Contact`.

### Failure 2 — Business logic isn't passive metadata, it's active derivation

Most of the value in an enterprise's analytics stack lives in **derived metrics**, not raw columns:

```sql
-- A typical dbt model, simplified
SELECT
  customer_id,
  SUM(monthly_revenue) AS lifetime_revenue,
  CASE
    WHEN MAX(last_login) < CURRENT_DATE - INTERVAL '90 days' THEN 'churned'
    WHEN AVG(usage_score) > 0.7 THEN 'power_user'
    ELSE 'active'
  END AS health_status,
  -- LTV = expected_monthly_revenue * (1 / (1 - retention_rate))
  AVG(monthly_revenue) / NULLIF(1 - retention_rate, 0) AS ltv,
  STRING_AGG(DISTINCT product_name, ', ') AS products_used
FROM raw_events
GROUP BY customer_id
```

The columns `lifetime_revenue`, `health_status`, `ltv`, `products_used` are not in any source table — they are **computed from formulas** that the analytics team wrote. An LLM extracting from a row of source data has no way to reproduce these. The graph would be missing the most useful facts.

### Failure 3 — Enterprise customers don't trust black-box ingestion

Regulated industries (finance, healthcare, legal) require an auditable mapping from source data to derived data. "Trust me, the LLM figured it out" is not an acceptable answer. Customers need to **see**, **edit**, and **sign off on** the mapping before any data flows into the graph — and to know that the mapping is versioned and rollbackable.

---

## What Context Forge does (the four-stage flow)

Context Forge runs **once per source connection at onboarding**, then re-runs incrementally when the source schema changes. It does not run per-episode (the 10-step pipeline does that). The four stages:

```
┌──────────────────────────────────────────────────────────────────┐
│  Stage 1: INTROSPECTION                                          │
│  Source Introspector + Data Profiler + Business Logic Ingester   │
│  ─ Reads DDL, FKs, indexes, views, stored procedures             │
│  ─ Samples data; detects cardinalities, distributions, patterns  │
│  ─ Parses dbt manifest, LookML, MetricFlow YAML, etc.            │
│  ─ Output: canonical Source Profile (schema graph + data stats   │
│            + business logic DAG)                                 │
├──────────────────────────────────────────────────────────────────┤
│  Stage 2: INFERENCE                                              │
│  Mapping Inference Engine                                        │
│  ─ Table → Entity Type classifier                                │
│  ─ FK → Relationship Type classifier                             │
│  ─ Column → Fact Predicate mapper                                │
│  ─ Junction Table Detector                                       │
│  ─ Time-Series / Audit-Table Recognizer                          │
│  ─ Derived-Metric Translator (formulas → derived facts)          │
│  ─ Confidence Scorer                                             │
│  ─ Output: Candidate Forge Mapping (proposal, not committed)     │
├──────────────────────────────────────────────────────────────────┤
│  Stage 3: CURATION                                               │
│  Forge Studio (user-facing review/edit UI)                       │
│  ─ Schema-side, mapping-middle, graph-side three-pane view       │
│  ─ Inline edits, bulk ops, validation warnings                   │
│  ─ Sample data preview end-to-end                                │
│  ─ Smoke-test queries                                            │
│  ─ Output: Approved Forge Mapping                                │
├──────────────────────────────────────────────────────────────────┤
│  Stage 4: COMMIT                                                 │
│  ─ Forge Mapping serialized as msgpack, SHA-256 hashed           │
│  ─ Versioned (v1, v2, ...), content-addressed, immutable         │
│  ─ Forge-to-Pipeline Bridge configures the 10-step pipeline      │
│  ─ Subsequent ingestions use deterministic mapping for known     │
│    structures; LLM extraction only for unstructured fields       │
└──────────────────────────────────────────────────────────────────┘
```

---

## Component 1 — Source Introspector

The Introspector connects to source systems and extracts everything that's already structurally known.

### Supported sources (introspection adapters)

| Source family | What we read | Adapter |
|---------------|--------------|---------|
| **PostgreSQL** | `pg_catalog.pg_tables`, `pg_constraint` (FKs/PKs), `pg_index`, `pg_views`, `pg_proc` (stored procs), table-level comments | Native |
| **MySQL / MariaDB** | `information_schema.{tables, columns, key_column_usage, statistics, views, routines}` | Native |
| **SQL Server** | `sys.tables`, `sys.foreign_keys`, `sys.indexes`, `sys.views`, `sys.procedures`, extended properties | Native |
| **Oracle** | `ALL_TABLES`, `ALL_CONSTRAINTS`, `ALL_VIEWS`, `ALL_PROCEDURES`, comments | Native |
| **Snowflake** | `INFORMATION_SCHEMA`, `ACCOUNT_USAGE.OBJECT_DEPENDENCIES`, tagging | Native |
| **BigQuery** | `INFORMATION_SCHEMA.{TABLES, COLUMNS, COLUMN_FIELD_PATHS, KEY_COLUMN_USAGE}`, table descriptions | Native |
| **Databricks / Spark SQL** | Unity Catalog tables, info_schema, lineage | Native |
| **ClickHouse** | `system.tables`, `system.columns`, MergeTree partition keys | Native |
| **Salesforce** | Object Describe API (custom objects, custom fields, lookup relationships, validation rules, formula fields) | API |
| **HubSpot** | Object schema + property API + association API | API |
| **NetSuite, Workday, Dynamics, Zuora** | Schema discovery via SOAP/REST | API |

### Output: Canonical Schema Graph

For every introspected source, the Introspector emits a normalized representation:

```yaml
source: snowflake://acme.snowflakecomputing.com/PROD/ANALYTICS
introspected_at: 2026-04-27T10:15:00Z
schemas:
  - name: ANALYTICS
    tables:
      - name: dim_customers
        primary_key: [customer_id]
        columns:
          - name: customer_id
            type: VARCHAR(36)
            nullable: false
            comment: "UUID primary key"
          - name: account_id
            type: VARCHAR(36)
            nullable: false
            comment: "FK to dim_accounts"
          - name: created_at
            type: TIMESTAMP_NTZ
            nullable: false
          - name: lifetime_value
            type: NUMBER(18,2)
            nullable: true
            comment: "Computed in dbt model fct_customer_metrics"
        foreign_keys:
          - columns: [account_id]
            references_table: dim_accounts
            references_columns: [id]
            on_delete: RESTRICT
        indexes:
          - name: idx_customers_email
            columns: [email]
            unique: true
        row_count_estimate: 245_192
        last_modified: 2026-04-26T18:30:00Z
      - name: account_contacts  # Junction table — Atlas will detect this
        primary_key: [account_id, contact_id]
        ...
    views:
      - name: vw_active_customers
        definition: "SELECT * FROM dim_customers WHERE health_status = 'active'"
        depends_on: [dim_customers, fct_customer_metrics]
    stored_procedures:
      - name: sp_archive_inactive_customers
        ...
```

This canonical schema graph is **the input** to the Profiler and Inference Engine.

---

## Component 2 — Data Profiler

Schema alone isn't enough. To map well, Context Forge needs to understand **what's actually in the columns** — value distributions, naming patterns, nullability, cardinality, semantic content.

### What the Profiler computes per column

| Statistic | Algorithm | Why it matters |
|-----------|-----------|----------------|
| Cardinality estimate | HyperLogLog | Distinguishes high-cardinality (e.g., `email`) from categorical (e.g., `status`) |
| Top-K values + frequency | Count-Min Sketch | Identifies enums and reference values |
| Null rate | Sample-based | Distinguishes optional from required attributes |
| String length distribution | Sampled histogram | Pattern fingerprint (e.g., 36-char strings → UUIDs) |
| Regex pattern fit | Pattern-library match | Detects emails, phones, IPs, URLs, ISO dates, ZIP codes, currency |
| PII / PHI heuristics | Presidio + custom rules | Auto-flags sensitive columns (configurable handling) |
| Min / max / quantiles (numeric) | Sampled histogram | Distinguishes IDs from amounts |
| Cross-column correlation | Mutual information | Detects undeclared FKs (column X always equals column Y in another table) |
| Time-pattern analysis | (timestamp columns) | Detects monotonic timestamps (`created_at` semantics) vs occasional (`last_login`) |

### Output: column profiles attached to each schema element

```yaml
table: dim_customers
column_profiles:
  customer_id:
    cardinality_estimate: 245_192
    null_rate: 0.000
    pattern_fit: "uuid_v4 (96%)"
    inferred_role: "primary_key"
    confidence: 0.99
  email:
    cardinality_estimate: 244_188
    null_rate: 0.004
    pattern_fit: "email_rfc5322 (99.7%)"
    pii: true
    inferred_role: "natural_identifier"
    confidence: 0.97
  health_status:
    cardinality_estimate: 4
    null_rate: 0.000
    top_k: [{value: "active", freq: 0.71}, {value: "churned", freq: 0.18}, ...]
    inferred_role: "categorical_status"
    confidence: 0.99
  lifetime_value:
    cardinality_estimate: 198_447
    null_rate: 0.12
    distribution: {min: 0, p50: 4823, p95: 38_220, max: 1_204_500}
    inferred_role: "monetary_metric"
    confidence: 0.93
```

The Profiler runs against samples (not full tables) — typically 10K-100K rows per table, with stratified sampling for skewed distributions. Samples are stored ephemerally and **not retained** after the mapping is committed (privacy commitment).

---

## Component 3 — Business Logic Ingester

This is the piece that respects the analyst team's prior work. Context Forge accepts business logic from **all the formats enterprises actually use**:

### Supported business-logic formats

| Format | What it provides | Parser |
|--------|------------------|--------|
| **dbt project** (`manifest.json` + `sources.yml` + `schema.yml`) | Models, sources, tests, exposures, lineage | Native dbt-graph parser |
| **dbt Semantic Layer / MetricFlow** (YAML) | Metric definitions, dimensions, time grains | YAML parser |
| **LookML** (Looker model + view files) | Views, explores, measures, dimensions, derived tables, parameters | LookML parser |
| **Cube.dev** (`cube.js` schema files) | Cubes, measures, dimensions, joins | JS schema parser |
| **OpenLineage / DataHub** (lineage events) | Cross-tool lineage, tags, glossary terms | OpenLineage spec |
| **Tableau workbooks** (`.tds`/`.twb` XML) | Calculated fields, parameters | XML parser |
| **Power BI / DAX** (model.bim, .pbix) | DAX measures, calculated columns | DAX parser |
| **SQL views & stored procedures** | Derivation logic | SQLGlot parser → AST → derivation DAG |
| **Custom YAML / JSON business rules** | Customer-specific schemas | Schema-validated YAML/JSON |
| **Plain language metric definitions** | "LTV = monthly_revenue / churn_rate" | LLM-assisted structured-form extraction (one-shot) |

Most enterprise customers will provide at least one of these (dbt is by far the most common). Customers without any formal business logic still get a usable mapping — the Inference Engine falls back on schema + data profiles.

### Output: business logic DAG

The Ingester produces a unified graph of derived-metric definitions:

```yaml
metrics:
  - name: ltv
    description: "Customer Lifetime Value"
    formula: "AVG(monthly_revenue) / NULLIF(1 - retention_rate, 0)"
    depends_on:
      - dim_customers.monthly_revenue
      - dim_customers.retention_rate
    source: dbt_model:fct_customer_metrics
    business_owner: "analytics@acme.com"
  - name: health_status
    description: "Customer health categorization"
    formula: |
      CASE
        WHEN MAX(last_login) < CURRENT_DATE - INTERVAL '90 days' THEN 'churned'
        WHEN AVG(usage_score) > 0.7 THEN 'power_user'
        ELSE 'active'
      END
    depends_on:
      - dim_customers.last_login
      - dim_customers.usage_score
    source: dbt_model:fct_customer_metrics
  - name: products_used
    description: "Comma-separated list of products the customer uses"
    formula: "STRING_AGG(DISTINCT product_name, ', ')"
    depends_on:
      - fct_subscriptions.product_name
    source: dbt_model:fct_customer_metrics
```

These metrics become **derived facts** in the ContextD graph — facts that are recomputed on ingestion using the customer's own formulas, not LLM-derived approximations.

---

## Component 4 — Mapping Inference Engine

This is the brain of Context Forge. It combines the Schema Graph + Data Profiles + Business Logic DAG + (optional) Ontology hints into a candidate Forge Mapping.

### Inference passes (each independently scored)

**Pass 1 — Table-to-Entity-Type classifier.** For each table, propose `entity_type`. Heuristics:
- Singular vs plural in name (`customer` vs `customers` vs `customer_addresses`)
- Naming conventions (`dim_*`, `fct_*`, `_log`, `_audit`, `_history`)
- Cardinality of PK (very low → reference data, very high → entities or events)
- Presence of `created_at` + `updated_at` (entities) vs immutable timestamp + entity_id (episodes)
- Cross-reference with provided ontology classes
- LLM-assisted naming for ambiguous cases (with the table's columns + sample rows + comments as context)

Output: `dim_customers → entity_type: "customer" (confidence 0.97, reasoning: "naming convention dim_*, has stable PK customer_id with row_count 245K, matches CRM ontology Customer class")`.

**Pass 2 — FK-to-Relationship classifier.** For each FK, propose `relationship_type` and direction:
- Direction: FK column points "from" the table containing the FK "to" the referenced table (default), with override if cardinality + naming suggest otherwise.
- Type naming: combine column name (`account_id` → `belongs_to_account`), table-name semantics, and ontology object_property matches.
- Cardinality: 1:1 (unique FK), 1:N (default FK), N:M (junction-table-detected — see Pass 3).

Output: `dim_customers.account_id → dim_accounts.id` becomes `Customer ─belongs_to→ Account` with confidence 0.95.

**Pass 3 — Junction Table Detector.** Tables that match the junction-table pattern (composite PK over exactly two FKs, no other meaningful columns or only join metadata) are converted to **bidirectional Relationships** between the referenced entities, with the junction-table columns becoming relationship properties.

Output: `account_contacts(account_id, contact_id, role, since_date)` → `Account ↔ has_contact ↔ Contact (properties: {role, since_date})`.

**Pass 4 — Column-to-Fact-Predicate mapper.** Each non-FK column on an entity table becomes a candidate `Fact` predicate:
- Column name → predicate name (with normalization: `email_address` → `has_email`)
- Column type + profile → fact value type
- Functional / cardinality constraints from ontology
- Special handling for status/categorical columns (top-K values become enum)
- PII flagged columns → tagged for redaction policy

Output: `dim_customers.email` → `Customer ─has_email→ <string, PII>` with confidence 0.99.

**Pass 5 — Time-Series / Audit-Table Recognizer.** Tables with high-cardinality + monotonic timestamp + repeated entity FK are mapped as **Episodes** rather than Entities. Audit tables (`*_history`, `*_audit`, `*_log`) inform **bitemporal annotation** — the columns containing `valid_from` / `valid_to` semantics map directly to the bitemporal `valid_at` / `invalid_at`.

Output: `customer_login_events(event_id, customer_id, timestamp, ip)` → `Episode (source=customer_login_events)` with `customer_id` as the affected entity.

**Pass 6 — Derived-Metric Translator.** Each metric from the Business Logic DAG becomes a `Derived Fact`:
- The formula is normalized (parsed via SQLGlot for SQL formulas, LookML evaluator for LookML measures, DAX evaluator for Power BI)
- Dependencies on base columns are resolved to source facts in the graph
- Computation is registered with the runtime — at ingestion time, derived facts are computed and written alongside source facts

Output: dbt metric `ltv` → `Customer ─has_ltv→ <number, derived from formula(...)> (recompute on ingest)`.

**Pass 7 — Confidence Scoring.** Every inference receives a 0-1 confidence based on:
- Ontology-match strength (if ontology provided)
- Naming convention consistency
- Data-profile alignment (cardinality matches expectation)
- LLM agreement (when LLM consulted for ambiguous cases)
- Customer-provided business-logic agreement

Confidences below thresholds (typically <0.7) are flagged as **needs review** in Forge Studio rather than silently committed.

### Output: Candidate Forge Mapping

```yaml
atlas_mapping:
  source: snowflake://acme.snowflakecomputing.com/PROD/ANALYTICS
  inferred_at: 2026-04-27T10:30:00Z
  ontology: crm-ontology-v3
  entities:
    - source_table: dim_customers
      entity_type: customer
      identifier: customer_id
      natural_keys: [email]
      pii_columns: [email, phone, address]
      bitemporal:
        valid_at_column: created_at
        invalid_at_column: deactivated_at
      confidence: 0.97
  relationships:
    - source_fk: dim_customers.account_id → dim_accounts.id
      relationship_type: belongs_to_account
      cardinality: many_to_one
      confidence: 0.95
    - junction_table: account_contacts
      from_entity: account
      to_entity: contact
      relationship_type: has_contact
      properties: [role, since_date]
      confidence: 0.92
  facts:
    - source_column: dim_customers.email
      subject_entity: customer
      predicate: has_email
      value_type: string
      pii: true
      functional: true
      confidence: 0.99
  derived_facts:
    - name: ltv
      subject_entity: customer
      predicate: has_ltv
      formula:
        language: sql
        body: "AVG(monthly_revenue) / NULLIF(1 - retention_rate, 0)"
      dependencies: [monthly_revenue, retention_rate]
      source: dbt_model:fct_customer_metrics
      recompute_on_ingest: true
      confidence: 1.00  # explicit customer formula — no inference
  episodes:
    - source_table: customer_login_events
      affected_entity_column: customer_id
      timestamp_column: event_timestamp
      content_columns: [event_type, ip_address, user_agent]
      confidence: 0.94
  warnings:
    - table: legacy_orders
      severity: medium
      message: "No PK declared. Inferred composite (org_id, order_number) — please verify."
    - column: dim_customers.notes
      severity: low
      message: "Free-text column with high variance. Will be embedded but not parsed."
  needs_review:
    - relationship: dim_users.manager_id → dim_users.id (self-reference)
      reason: "Ambiguous direction. Could be 'reports_to' or 'manages'. Please confirm."
```

---

## Component 5 — Forge Studio (the user-facing view)

Forge Studio is where the customer reviews, edits, and approves the candidate mapping. It's the visible part of Context Forge and the part that builds enterprise trust.

### Three-pane layout

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  FORGE STUDIO — Editing: snowflake://acme.../ANALYTICS  [v3-draft]            │
├──────────────────────────┬─────────────────────────┬──────────────────────────┤
│  SOURCE SCHEMA           │  FORGE MAPPING (edit)   │  CONTEXTD GRAPH PREVIEW  │
│                          │                         │                          │
│  ▸ ANALYTICS             │  Entities (12)          │  Customer  ────┐         │
│    ▸ dim_customers       │   ▸ customer  ◯ 0.97   │      │         │         │
│      • customer_id  PK   │     ─ identifier:       │      ↓         ▼         │
│      • account_id   FK   │       customer_id       │  has_email   Account    │
│      • email             │     ─ pii: [email,phone]│      │         │         │
│      • lifetime_value    │   ▸ account   ◯ 0.99   │      ↓         ↓         │
│      • created_at        │   ▸ contact   ◯ 0.94   │  has_ltv    has_contact  │
│    ▸ dim_accounts        │   ⚠ legacy_orders       │      │         │         │
│    ▸ account_contacts    │                         │      ↓         ↓         │
│      • account_id   PK   │  Relationships (18)     │   199.5      Contact     │
│      • contact_id   PK   │   ▸ belongs_to_account  │                          │
│      • role             │   ▸ has_contact (M:M)   │  ── Sample row preview:  │
│      • since_date       │   ⚠ manager_id (review) │     dim_customers row    │
│    ▸ customer_login_…   │                         │     #41982 maps to       │
│                          │  Facts (94)             │     Customer entity      │
│  Stats: 47 tables,       │   ─ has_email           │     "alice@acme.com"     │
│  3.4M rows total, 218    │   ─ has_phone           │     with 8 facts and     │
│  FKs declared, 30 dbt   │   ─ has_lifetime_value   │     3 outgoing relation- │
│  metrics, 12 LookML     │   ─ has_health_status   │     ships.               │
│  measures.              │                         │                          │
│                          │  Derived Facts (30)     │  [▶ Run smoke tests]     │
│                          │   ─ has_ltv (dbt)       │                          │
│                          │   ─ has_health (dbt)    │                          │
│                          │                         │                          │
│                          │  Episodes (3)           │                          │
│                          │   ─ login_events        │                          │
│                          │   ─ subscription_events│                          │
│                          │   ─ support_messages    │                          │
├──────────────────────────┴─────────────────────────┴──────────────────────────┤
│  ⚠ 1 warning · 2 items need review · Last saved 14m ago     [Save] [Apply]   │
└───────────────────────────────────────────────────────────────────────────────┘
```

### What the user can do

- **Inspect any inference.** Click an entity, relationship, or fact to see the reasoning, confidence, and source data sample.
- **Inline edit.** Change `entity_type`, `predicate name`, `cardinality`, `pii` flags, etc. Context Forge recomputes downstream impacts (e.g., changing an entity type re-validates all relationships pointing to it).
- **Bulk operations.** "Treat all `*_log` tables as episodes." "Mark every column matching `*_email` as PII." "Apply CRM ontology to all entities matching `customer|account|contact`."
- **Override an inference.** Reject the proposed mapping for a table; provide custom mapping. The override is preserved across re-introspections (so a schema change doesn't blow away the customer's edits).
- **Validation panel.** Surfaces warnings: "Table `legacy_orders` has no PK", "Column `dim_users.manager_id` is a self-reference — direction ambiguous", "Column `notes` is high-variance free text — will embed but not parse".
- **Smoke-test queries.** Predefined query templates ("Who are our top-N customers by LTV?", "Show all customers churned in the last 30 days", "List all accounts with no contact") let the user verify the mapping produces sensible results before committing.
- **Sample data trace.** Pick any source row; see the full mapping path: which entity it becomes, what facts get extracted, which relationships fire, what derived facts are computed.
- **Diff against previous version.** v2 vs v3 of the mapping — see exactly what changed (added entities, modified predicates, removed facts).

### Save vs Apply

- **Save** — persist the current mapping as a draft. Multiple drafts can exist; nothing is committed to ingestion yet.
- **Apply** — promote the current draft to the active Forge Mapping for this source. Triggers re-ingestion (or incremental re-mapping if only specific elements changed). Old mappings remain available for rollback.

---

## Component 6 — Forge Mapping (the artifact)

When applied, an Forge Mapping becomes an **immutable, content-addressed artifact** — consistent with Context Cores (`08-core-technology.md` §9).

### Properties of an Forge Mapping

- **Versioned.** v1, v2, ... per source connection. Linear history.
- **Content-addressed.** msgpack-serialized, SHA-256 hashed. Any change produces a new hash → new version.
- **Immutable.** Once applied, an Forge Mapping is not edited in place. Edits create a new draft → applied as a new version.
- **Diffable.** Forge Studio shows the diff between any two versions.
- **Rollbackable.** Reverting to a previous Forge Mapping triggers re-ingestion against the older mapping. Same UX as Context Core rollback.
- **Exportable.** YAML/JSON export for code review, change management, or sharing across tenants in the same org.

### Relationship to Context Cores

Forge Mappings and Context Cores are **complementary**:

| | Forge Mapping | Context Core |
|---|---------------|--------------|
| **What it captures** | Source-schema → ContextD-primitive *configuration* | Snapshot of the *resulting graph state* |
| **When it's built** | At source onboarding + each schema/business-logic change | Periodically + before risky changes |
| **What it contains** | Inference rules, mappings, derived-metric formulas, validation overrides | Actual entities, relationships, facts, embeddings, feedback weights |
| **Lifecycle ops** | Save / Apply / Rollback | Build / Test / Promote / Rollback |
| **Output format** | msgpack + SHA-256 | msgpack + SHA-256 |

The pipeline lifecycle becomes:
```
Forge Mapping (config) ──configures──► 10-step Pipeline (ingest) ──produces──► Graph state ──snapshots──► Context Core
```

A given Context Core implicitly references the Forge Mapping that was active when it was built — full provenance of *both* the data and the rules used to produce it.

---

## Component 7 — Forge Profiles (pre-built mappings)

Most enterprises don't have unique schemas — they have customizations on top of well-known schemas. Context Forge ships with **Forge Profiles** for the common cases:

| Profile | Covers |
|---------|--------|
| **Salesforce CRM** | Standard objects (Account, Contact, Opportunity, Lead, Case) + common custom-field naming patterns |
| **HubSpot** | Standard objects + association API |
| **Stripe** | Customers, Subscriptions, Invoices, Payments, Disputes, Refunds |
| **Shopify** | Orders, Customers, Products, Variants, Fulfillments |
| **Zendesk** | Tickets, Users, Organizations, SLAs, Satisfaction |
| **Jira / Linear / Asana** | Issues, Projects, Cycles, Sprints, Comments, Attachments |
| **dbt + Fivetran-modeled Snowflake** | Common Fivetran-source patterns (raw_*) + dbt model conventions (stg_*, int_*, fct_*, dim_*) |
| **Generic OLTP Postgres** | Heuristic patterns for typical customer/order/product schemas |

Customers can **fork** a profile and customize. Forking is preserved as an Forge Mapping (deltas tracked from the profile baseline). When the underlying profile is updated by ContextD, the customer is offered an opt-in upgrade with a diff preview.

---

## Component 8 — Forge-to-Pipeline Bridge

Once an Forge Mapping is applied, the 10-step ingestion pipeline (`08-core-technology.md` §3) reads it as configuration. The Bridge changes the pipeline's behavior in three ways:

### Change 1 — Step 3 (Extract Nodes) becomes deterministic for known structures

For source tables covered by the Forge Mapping, entities are produced **deterministically from rows** rather than via LLM extraction:

```
Row in dim_customers (customer_id=41982, email='alice@acme.com', ...)
       ↓  (deterministic mapping from Atlas)
Customer entity {
  id: 41982,
  entity_type: "customer",
  source: "snowflake.dim_customers",
  ...
}
```

LLM extraction is reserved for **unstructured fields** (free-text columns like `notes`, `description`, `comments`) and **unstructured sources** (Gmail bodies, Slack message text). This is where the LLM cost reduction comes from (typically 60-80% for enterprise customers with significant structured data).

### Change 2 — Step 6 (Extract Edges) reads FK + junction definitions

Relationships from the Forge Mapping are produced deterministically. LLM relationship extraction runs only on unstructured episode content where the Forge Mapping doesn't already prescribe a relationship.

### Change 3 — Derived facts are computed

After Step 9 (Save to Graph), the Bridge runs the **derived-fact computation pass**:

- For each derived fact in the Forge Mapping, compute the formula against the just-ingested data
- Emit derived facts (e.g., `Customer 41982 ─has_ltv→ 47830.50`)
- Stamp with provenance (`extraction_method = "forge_derived_metric"`, formula source preserved)
- Bitemporal annotation: derived facts inherit the underlying source's `valid_at`; `created_at` is the computation timestamp

### Hybrid pipeline behavior

After the Bridge:

```
For each source episode:
  - Forge Mapping covers this source? → deterministic extraction (cheap, fast)
  - Free-text or unstructured fields? → LLM extraction (selective, expensive)
  - Both can happen on the same episode (e.g., a Salesforce ticket has structured
    fields + a free-text description)

For each ingested row:
  - Forge-derived facts computed via formulas
  - LLM-derived facts (from unstructured fields) added alongside
  - All facts equal-citizens in the graph (provenance distinguishes them)
```

**Net effect.** LLM cost is reduced by 60-80% for enterprises with significant structured sources, while LLM-quality extraction is preserved for unstructured content. The customer's analyst work is honored end-to-end — every dbt metric, LookML measure, and SQL view definition produces a corresponding derived fact in the graph.

---

## Where Context Forge sits in the architecture (Layer 1.5)

Context Forge is **upstream of the ContextD Engine** but **downstream of the Connector layer**. It's a new layer in the architecture:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: INTEGRATION — SDK / MCP / REST / 6 Wire Protocols              │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: RBAC & AUTH                                                    │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: CONTEXTD ENGINE                                                │
│   10-step ingestion (now Forge-aware) · Hybrid retrieval · Cores · ...  │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: UNIFIED MULTI-MODEL STORAGE SUBSTRATE                          │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1.5: CONTEXT FORGE  ◄── NEW                                         │
│   Source Introspector · Data Profiler · Business Logic Ingester         │
│   · Mapping Inference Engine · Forge Studio (UI) · Forge Mapping        │
│   (versioned artifact) · Forge Profiles · Forge-to-Pipeline Bridge      │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: CONNECTOR LAYER                                                │
└──────────────────────────────────────────────────────────────────────────┘
```

The closed loop now reflects this:

```
CONNECTOR              CONTEXT FORGE              INGESTION PIPELINE       QUERY
Snowflake ──┐                                                             Natural Language Query
Postgres  ──┤   ┌─ Introspect ─┐                                                │
SFDC      ──┼─►├─ Profile ─────┼─► Atlas        ┌─ Step 1: Episode             ▼
HubSpot   ──┤   ├─ Ingest BL ──┤   Mapping ────►├─ Step 3: Extract        Hybrid Search
Gmail*    ──┘   └─ Infer ──────┘   (versioned)  │   (deterministic for         │
                       ↑                         │    Forge-covered sources)    ▼
                  Forge Studio                   ├─ Step 6: Edges (det.+LLM)  Reranker + Feedback
                  (review/edit)                  ├─ Step 9: Save              Weights
                                                 ├─ Forge-derived facts        │
                                                 │   computed                  ▼
                                                 └─ Step 10: Communities    Context Window

* Gmail/Slack/etc. don't typically have schemas to introspect — they bypass
  Context Forge and use LLM extraction directly. Atlas is for structured sources.
```

---

## Why Context Forge is hard to replicate

Add this to the differentiator analysis (`11-technical-capabilities.md`).

| Dimension | Score | Reasoning |
|-----------|------:|-----------|
| **Structural depth** | 5/5 | Requires a multi-format business-logic parser (dbt, LookML, MetricFlow, DAX, SQL views), a versioned content-addressed mapping artifact, a three-pane UI for curation, and bidirectional integration with the ingestion pipeline. None of these can be retrofitted onto a generic ETL or ingestion tool — they require the entire substrate-to-graph stack to coordinate. |
| **Compounding effect** | 5/5 | Customer's Forge Mapping accumulates overrides, custom metrics, and validation rules over time. Becomes a critical operational artifact (versioned, audited, signed off). Switching means losing the mapping history and the analyst-team work captured inside it. |
| **Distribution advantage** | 4/5 | Forge Profiles for Salesforce / HubSpot / Stripe / dbt-Snowflake / etc. become a network of pre-built starting points. Each new profile improves time-to-value for the next customer. |

**Total: 14/15.** Same tier as Context Cores and Feedback-Weighted Retrieval. Genuine moat.

The reason no incumbent has this: it requires **simultaneously** owning (a) the ingestion pipeline, (b) the graph schema, and (c) the customer-facing curation UX. Existing players own one or two:
- ETL tools (Airbyte, Fivetran, Hightouch) own ingestion but not graph schema
- Data catalogs (DataHub, Atlan, Collibra) own metadata but not ingestion or graph
- Graph DBs (Neo4j, Neptune) own graph but not ingestion or schema mapping
- LLM-RAG frameworks own orchestration but not persistent data layer

Context Forge requires all three — which is exactly what ContextD is.

---

## Customer onboarding flow: before vs after Context Forge

### Before Context Forge (the failure mode)

```
Day 1:    Customer connects Snowflake/Postgres source
Day 1:    Pipeline starts ingesting; LLM extracts entities row-by-row
Day 3:    Cost report — $4,800 spent on LLM extraction for 1.2M rows
Day 7:    Customer queries "show me top customers by LTV"
Day 7:    Result: missing LTV (formula not reproduced); inconsistent
          entity types ("customer" vs "Customer" vs "Person"); broken
          relationships (junction tables created as entities)
Day 10:   Customer dispatches engineering team to "fix our weird LLM bot"
Day 30:   Team gives up; customer doesn't trust the graph; subscription
          at risk
```

### After Context Forge

```
Hour 1:   Customer connects Snowflake source. Atlas Introspector reads
          schema (47 tables), Profiler samples data (10K rows/table),
          Business Logic Ingester parses dbt project (150 models, 30
          metrics, full lineage)
Hour 2:   Forge Studio opens with candidate mapping: 12 entities,
          18 relationships, 94 facts, 30 derived facts, 3 episodes,
          1 warning, 2 items needing review
Hour 3:   Customer reviews, accepts most inferences, edits 2 ambiguous
          self-references, adds 1 custom override for a table their
          team treats specially
Hour 4:   Customer hits Apply. Forge Mapping v1 saved (sha256:e8a...)
          Pipeline starts ingesting, deterministic for known tables,
          LLM only for free-text fields
Day 1:    Cost report — $480 spent on LLM extraction (90% reduction
          vs LLM-only). Graph is consistent and respects all 30 dbt
          metrics as derived facts.
Day 1:    Customer queries "show me top customers by LTV"
Day 1:    Result: correct LTV from the customer's own dbt formula,
          consistent customer entities, working relationships.
Week 4:   Customer's analytics team adds 3 new dbt metrics. Atlas
          re-introspects the project, surfaces a candidate mapping
          update in Forge Studio. Customer accepts, applies → Atlas
          Mapping v2.
```

The hour-1-to-hour-4 onboarding loop is the success metric for Context Forge. Enterprise sales motion compresses from "30-day proof-of-concept" to "afternoon demo with the customer's actual schema."

---

## What's in scope vs out of scope

### In scope (v1)

- Introspection of relational DBs (Postgres, MySQL, SQL Server, Oracle, Snowflake, BigQuery, Databricks, ClickHouse)
- Introspection of common SaaS APIs (Salesforce, HubSpot, Zendesk, Stripe, Shopify) — these have schema endpoints
- Business logic parsers: dbt, LookML, SQL views/procedures, Cube.dev, MetricFlow YAML, plain-language (LLM-assisted)
- Mapping Inference Engine with the seven passes described above
- Forge Studio with three-pane UI, inline edits, smoke tests, validation panel
- Forge Mapping versioning (msgpack + SHA-256, compatible with Context Core machinery)
- Forge-to-Pipeline Bridge integration with the 10-step pipeline
- Forge Profiles for Salesforce, HubSpot, Stripe, dbt-Snowflake, generic OLTP Postgres

### Out of scope for v1 (deferred to v2)

- Streaming source schema-change detection (v1 is poll-based introspection)
- Advanced PII handling (v1 flags PII; v2 adds per-fact redaction policies, masking-on-read)
- Cross-source mapping reconciliation (v1 maps each source independently; v2 unifies cross-source canonical IDs at the Atlas layer)
- Customer-defined inference plugins (v1 inference engine is fixed; v2 allows custom rules)
- Tableau / Power BI parsers (v1 supports dbt, LookML, MetricFlow, Cube; v2 expands)
- Lineage import from OpenLineage / DataHub (v1 reads dbt/LookML lineage; v2 supports external catalog import)

---

## Roadmap commitment

Context Forge is **a critical pre-pipeline phase** in the engineering roadmap. See `10-roadmap-and-build-plan.md` for the integrated phase plan. Headline:

| Phase | Quarter | Scope |
|-------|---------|-------|
| **Phase 2 (Context Forge)** | Q3-Q4 2026 | Source Introspector (Postgres, MySQL, SQL Server, Snowflake, BigQuery), Data Profiler, Business Logic Ingester (dbt, LookML, SQL views), Mapping Inference Engine, Forge Studio UI v1, Forge Mapping versioning, Forge-to-Pipeline Bridge |
| Phase 3 (Ingestion Pipeline) | Q4 2026 - Q1 2027 | (was Phase 2) — now Forge-aware |

Phase 2 ships before Phase 3 because the Ingestion Pipeline depends on the Forge Mapping format and Bridge interface.

---

## Common technical questions

**What happens when a customer has no dbt, LookML, or other formal business-logic artifacts?**
Inference falls back to the schema graph plus the data-profile signals. The candidate mapping has more `needs_review` items in Forge Studio because confidence is lower, but the mapping is still usable. Most enterprises encode at least some business logic implicitly in SQL views and stored procedures, which the Business Logic Ingester parses.

**Does the customer's analyst team have to redo work in Forge Studio?**
No — the principle is the opposite. Forge Studio surfaces the customer's existing dbt / LookML / SQL definitions as the source of truth and presents the inference engine's proposals as suggestions on top. The customer reviews and approves, not rewrites.

**How are source-schema changes handled after a mapping is committed?**
The Source Introspector re-runs on a configurable schedule per source. Schema diffs are surfaced in Forge Studio as a draft `v(N+1)`. The customer reviews and applies; a per-source policy can auto-apply for low-risk changes (e.g., column additions) without manual review.

**How does graph-schema evolution work as the business changes?**
Forge Mappings are versioned. New entity types, new derived facts, and new relationship types are added in subsequent versions. The pipeline reads the current version at runtime; old graph data references the older Forge Mapping that produced it (preserving extraction lineage end-to-end).

**What is the biggest accuracy risk?**
Inference accuracy on exotic schemas. The seven-pass Inference Engine handles common patterns well; legacy ERP-style schemas with hundreds of tables and hand-rolled inheritance will have lower confidence scores. Mitigation: every inference is surfaced for review with confidence and reasoning, so a wrong inference becomes a Studio UX issue rather than a silently corrupted graph. For exceptionally complex schemas, customer-specific onboarding via professional services bridges the residual gap.

---

*Continue to `04-product-and-architecture.md` for the architectural placement, `10-roadmap-and-build-plan.md` for the build phase, or `11-technical-capabilities.md` for the technical defensibility analysis.*
