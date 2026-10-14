# ContextD UI Flow Plan

> **Source of truth:** This plan is anchored to two artifacts.
>
> 1. `/docs/contextd/` — the technical specification for the Context Graph Database (six-layer architecture: Connectors → Forge → Substrate → Engine → RBAC → Integration).
> 2. `/docs/ui/contextd-screens-final.html` — the **production design mockup** for the operator console, demonstrated against the `Lattice Compute` reference tenant. The HTML defines the canonical look, layout, density, and copy; this Markdown is normative for routes, tab structure, and per-surface behavior.
>
> When the HTML and earlier MD diverge, the HTML wins. This file has been re-anchored to that mockup.

## 1. Product Frame

ContextD is a **database**. The UI is a **database console for AI context** — the way Supabase Studio is for Postgres or Neo4j Browser is for Neo4j, but for the *Context Graph Database* category.

The primary noun is the **Context Database**: a tenant-scoped collection that owns sources, Forge mappings, Resolver profiles, schemas, entities, edges, episodes, decisions, time-series, embeddings, cores, queries, lineage, and operational health.

Users do not feel like they are managing connectors. They feel like they are operating a database — calmly, densely, with provenance one click away.

The HTML mockup walks the demo tenant `Lattice Compute · Pro` (org id `org_lattice_2tQv`) through six core screens that together prove the product story end-to-end: discover, connect, build, inspect, query.

## 2. Implementation Status Discipline

The spec describes a system in motion. The console must not lie. Every surface carries one of three states:

| Tag | Meaning | UI treatment |
|---|---|---|
| **V1 (live)** | Backed by today's production stack (Postgres+Neo4j+Milvus+Redis+Temporal, ~45 connectors, hybrid retrieval, EMA feedback). | Full-fidelity views, real data, real actions. |
| **Preview** | Module exists in spec, partial backend support; UI gives a working scaffold + sample-state preview behind a `Preview` badge. | Functional shell, honest empty states, sample data clearly labeled. |
| **Roadmap** | On `/docs/contextd/10-roadmap-and-build-plan.md`, no backend yet. UI shows a one-screen design proposal so the team can iterate, but the route is gated behind a feature flag. | Disabled actions, clear `Roadmap` badge, link to the spec. |

Today's split:

- **V1 (the six core screens in the HTML):** Login, Onboarding, **Dashboard**, Source Catalog, **Source Setup Wizard**, Workbench shell, Workbench **Overview**, Workbench **Schema** (read-only introspection), Workbench Sources, Workbench Entities, Workbench **Graph** (with Entity Inspector), Workbench **Query Console**, Workbench Settings, Cohorts, Auth Providers, Admin, Organization.
- **Preview:** Schema tab annotated for Forge-derived columns, Lineage tab, Temporal tab (limited bitemporal), Drift tab, Decision Lineage browser, MCP server console.
- **Roadmap:** Forge Studio (3-pane mapping review), Resolver Studio (identity-stitching review), Context Cores (build/test/promote/rollback), wire-protocol polyglot console, multi-region/multi-tenant operator views.

## 3. Route Model

| Route | Product surface | Status |
|---|---|---|
| `/login` | Login | V1 |
| `/onboarding` | Provision first context database | V1 |
| `/` | Context databases (dashboard) | V1 |
| `/sources` | Connector catalog | V1 |
| `/sources/:provider/setup` | Source setup (auth → test → discover → scope → schedule) | V1 |
| `/query` | Cross-database query console | V1 |
| `/saved-queries` | Saved query library | V1 |
| `/graph` | Cross-database graph explorer | V1 |
| `/cohorts` (and detail) | Cohort builder | V1 |
| `/databases/:readableId` | Workbench shell (defaults to Overview) | V1 |
| `/databases/:readableId/overview` | Overview tab | V1 |
| `/databases/:readableId/sources` | Sources tab | V1 |
| `/databases/:readableId/schema` | Schema tab | Preview |
| `/databases/:readableId/entities` | Entities tab | V1 |
| `/databases/:readableId/graph` | Graph tab (with Entity Inspector) | V1 |
| `/databases/:readableId/query` | Query Console | V1 |
| `/databases/:readableId/temporal` | Temporal tab | Preview |
| `/databases/:readableId/lineage` | Lineage tab | Preview |
| `/databases/:readableId/decisions` | Decision lineage browser | Preview |
| `/databases/:readableId/drift` | Drift tab | Preview |
| `/databases/:readableId/forge` | Forge Studio | Roadmap |
| `/databases/:readableId/resolver` | Resolver Studio | Roadmap |
| `/databases/:readableId/cores` | Context Cores | Roadmap |
| `/databases/:readableId/settings` | Database settings | V1 |
| `/auth-providers` | OAuth provider management | V1 |
| `/organization/settings` | Members, billing, API keys, config | V1 |
| `/admin` | Operator console | V1 |
| `/mcp` | MCP server tools + transports | Preview |

> **Migration note:** today's frontend uses `/collections/:readable_id`. The HTML uses **database** semantics throughout. The route prefix moves from `/collections/...` to `/databases/...` as part of the transition (see `contextd-ui-transition-plan.md`).

## 4. Navigation Model

### 4.1 Sidebar (244 px expanded / 56 px collapsed)

```
ContextD wordmark · collapse toggle             (52 px header)
─────────────────────────────────────────────
[Lattice Compute · Pro]  ▾                      (project / org switcher)

Workspace
  ▸ Databases                       [4]
  ▸ Query console
  ▸ Source catalog                  [9]
  ▸ Graph explorer
  ▸ Saved queries                   [38]
  ▸ Alerts                          [2]   (amber count when warnings exist)

Operations
  ▸ MCP server                       [Preview]
  ▸ Admin

Settings
  ▸ Auth providers
  ▸ Organization

─────────────────────────────────────────────
Help          Feedback                          (utility footer)
─────────────────────────────────────────────
[avatar] Madison Cole                           (user card)
         Owner · lattice.ai
```

- Active item = orange-soft background, orange-700 text, 2 px orange left indicator.
- Counts use `nav-count` (gray) → `nav-count-warn` (amber) → `nav-count-danger` (red).
- The Schema and Query screens collapse the sidebar to 56 px (icon-only) so the workbench gets every pixel of width — a deliberate density move, not a user-only preference.

### 4.2 Topbar (52 px)

- Breadcrumb (`Databases / customer-360-prod / Schema`).
- `⌘K` command palette trigger (databases, sources, entities, queries, recipes, jumps).
- Environment badge (`local`, `staging`, `prod`).
- API health pill: `Operational` with a green pulsing dot, click → status drawer.
- Notifications (bell) with orange unread dot.
- Theme toggle (light / dark / system).
- User avatar.

### 4.3 Persistent footer status (28 px, monospace)

```
org_lattice_2tQv · customer-360-prod · last sync 2m ago · pending 18 · α=0.10 · build 7f2e1a4
```

## 5. End-to-End User Journey

### 5.1 Login

Goal: get into the console quickly.

- Light/dark grid background with subtle orange graph lines (mirroring landing).
- Compact `ContextD` wordmark.
- Email/password, SSO providers, magic-link option when configured.
- `Local development` badge when `AUTH_ENABLED=false`.
- Footer links: docs, GitHub, Discord, status.

States: loading session, auth disabled/local, invalid credentials, workspace unavailable, MFA required.

### 5.2 Onboarding — Provision the first context database

Goal: the user *provisions* a context database. Not "creates a collection."

Three-step provisioning sheet:

1. **Database** — name, readable ID (auto-suggested, mono), region (Roadmap), retention default (90 d / 1 y / 7 y).
2. **Initial source** (optional) — pick from {Postgres, Snowflake, ClickHouse, Gmail, Slack, Salesforce, …, "start empty"}; if a structured DB → mention Forge takes over (link to Forge Studio Roadmap).
3. **Index profile** — read-only in V1 (Lucene BM25 + HNSW cosine + hybrid pipeline); shown for transparency.

Success → workbench in empty-state with a single primary CTA: **Connect source**.

### 5.3 Dashboard — Context Databases (Screen 01 of 06)

Goal: see all databases and their operational health at a glance.

Layout:

- **Page header:** title `Context databases` + counts (`4 databases · 9 sources`) + org id (mono) + actions (`Docs`, `Import`, `New database`).
- **KPI strip — 7 tiles:** `Databases` · `Sources` · `Entities` · `Edges` · `Pending` (graph commit queue) · `Drift` · `Avg feedback (EMA)`. Each cell shows label / value / delta or sub-metric. No decoration — color only when delta carries meaning.
- **Database table** — one row per context database. Columns:
  - Database name + readable id (mono)
  - Sources (logo stack)
  - Entities (right-aligned mono)
  - Edges (right-aligned mono)
  - Graph status badge (`indexed` green / `partial` amber / `indexing` blue pulsing / `failing` red / `empty` gray)
  - Temporal coverage badge (`current` / `partial` / `planned`)
  - Drift badge (`clean` / `warnings` / `failing`)
  - Last sync (mono relative)
  - Quick actions (`Run sync`, `Open workbench`, kebab)
- **Recent activity** (left, 2-column grid): sync runs, schema changes, failed graph commits, top queries (each row: source icon · time · count · status).
- **Recent queries** (right column): saved queries with star rating, token counts, latency.

No oversized hero, no marketing card. Density first.

### 5.4 Source Catalog

Goal: connect enterprise systems confidently.

- **Filters:** Databases · Communication · Documents · CRM · Project management · Support · Developer tools · Custom (Roadmap).
- **Connector cards** (compact):
  - Logo, name
  - Auth method chip (`OAuth`, `API key`, `Key-pair`, `IAM`)
  - Sync mode chip (`Full + Incremental`, `Streaming`, `Schema-only`)
  - Schema-introspection chip (✓ for relational/SaaS DBs)
  - Temporal cursor chip (✓ if cursor supported)
  - Graph-extraction chip (`Deterministic` / `LLM` / `Hybrid`)
  - Forge-eligibility chip (only on relational + SaaS structured sources)

P0 cards (Snowflake, Postgres, Gmail, Salesforce, Slack, GitHub, Zendesk, HubSpot) are highlighted with a thin orange left border. P1 cards (Airbyte tier) carry a `Quality layer` badge. Roadmap connectors render disabled with a `Roadmap` pill.

### 5.5 Source Setup Wizard (Screen 02 of 06)

Goal: connect a source like a database admin, not a wizard toy.

Five-step wizard with a persistent **right-side preview pane** (60 / 40 split):

1. **Auth** — credentials, OAuth, key-pair, IAM-assume role.
2. **Test** — latency, auth status, permissions list, schema-discovery readiness. The mockup shows the result inline (`SELECT ✓ · USAGE ✓ · 64 tables · 142 dbt models`, latency `28 ms`).
3. **Discover** — for relational DBs: tables, columns, FKs, view count, dbt model count; for SaaS: object types, scopes; for mailboxes: labels, threads.
4. **Scope** — table/object selection, exclude masks, sampling cap, PII heuristic preview.
5. **Schedule + cursor** — initial backfill window, incremental cadence, cursor column, dead-letter behavior.

Step 3 (Discover) — canonical example from the mockup:

- Header chip: green `Connection healthy · 28 ms`.
- Title: `Discover schema & business logic`.
- Subtitle: `Introspecting LATTICE_DW.PROD_CORE — 64 base tables · 142 dbt models`.
- Discovered objects table — columns: `Table` (mono) · `Rows` · `Cols` · `FKs` · `Inferred entity` (orange/green/amber/blue/purple badge) · `PII` (amber chip for emails / names / free-text). Row selection drives the bulk-action footer (`8 of 9 selected · 55 hidden · Show all 64 →`).

**Right preview pane** (sticky):

- **Source identity** — Account · Database · Schema · Role · dbt project (all mono).
- **Target database** — name pill with `primary` badge.
- **Forge callout** (orange-soft band, `Roadmap` pill): `Forge will refine these mappings on first sync — open Forge Studio`.
- **Sync estimate** — Rows · Entities · Embeddings (count · 1024 d) · Storage · First sync (~38 min) · Incremental (every 15 min).

Action bar (sticky bottom): `Back` · summary text (`8 tables · 14 dbt metrics will be ingested`) · `Save draft` · `Continue`.

For Forge-eligible sources (Postgres, Snowflake, ClickHouse, Salesforce, dbt repo attached): once discovery completes, the wizard offers **Open Forge Studio** (Roadmap, behind a feature flag).

### 5.6 Database Workbench (the core screen)

Persistent **database identity sub-header** (52 px, sits below the topbar):

- Database icon (orange-soft tile) + name + readable id (mono, e.g. `customer-360-prod` / `ctxdb_cust_360`).
- Health pill (green `Healthy`, amber `Indexing`, red `Failing`).
- Substrate metadata (mono): `v1.4.2 · 3-node Raft`, current core (`prod:v143`), entity count, source count.
- Primary actions: **Query**, **Connect source**, **Build core** (Roadmap), **Run sync**, kebab (Snapshot to Core (Roadmap), Pause schedules, Settings, Danger zone).

#### 5.6.1 Vertical tab rail (180 – 200 px)

Three groups, each with a small caps eyebrow. Active tab = orange left indicator + orange-soft background.

```
Operate
  Overview          (V1)
  Sources           (V1)             [count]
  Schema            (Preview)
  Entities          (V1)             [count]
  Graph             (V1)             [count]
  Query             (V1)

Inspect
  Temporal          (Preview)
  Lineage           (Preview)
  Decisions         (Preview)
  Drift             (Preview)        [warn count]

Build
  Forge             (Roadmap)
  Resolver          (Roadmap)
  Cores             (Roadmap)
```

A right inspector panel (320 px desktop default, 360 px on the Graph and Query screens, dismissable on tablet) is contextual to the selected source / table / column / entity / node / edge / episode / event / query result / drift warning / decision.

#### 5.6.2 Overview tab (Screen 03 of 06)

Operational dashboard for one database.

- **KPI strip — 6 tiles:** `Entities` (4.04 M, +12.4 K / 24 h) · `Edges` (11.2 M, +48 K / 24 h) · `Episodes` (412 K — orders / returns / emails) · `Pending` (graph commits) · `Avg feedback` (EMA) · `Tokens saved vs chunk-RAG` (e.g. `84 %`).
- **Entities by type** panel — gauge list with color-coded dot per type (Customer orange, Product green, Order blue, Episode amber, Decision red, Review purple); count + delta per type.
- **Sync pipeline** panel — 10 ordered steps with per-step status (`done` green, `running` orange pulsing with `n/m` progress, `queued` blue, `pending` amber count, `not started` gray). The 10 steps mirror the production ingestion pipeline (extract → normalize → enrich → graph events → resolve semantic + LLM → embed → temporal commit → community detect → feedback rebalance → publish).
- **Active source** mini-table (1 row, selected highlight) — connector icon · name · cursor · progress bar · `in progress` badge · errors. Footer link: `8 other sources synced · 0 errors · View all →`.
- (Optional sub-bands when relevant) Recent queries · Recent changes (schema, supersessions, new decisions) · Temporal coverage summary · Drift summary (top 3 warnings) · Feedback weight histogram (mean / p50 / p95).

**Inspector** on this tab follows the active source: progress (panel with orange-soft band, e.g. `~24 min remaining · 6.9 M / 18.2 M rows · 14 min elapsed`), Connection (Account / Database / Role / Warehouse / dbt version — all mono), Schedule (`incremental · every 15 min · cursor=_dbt_loaded_at`), Estimated impact (Entities · Edges · Storage · First sync), action buttons (`Schema`, `Lineage`).

#### 5.6.3 Sources tab

- Connection table: source · connector · auth state · schedule · last sync · cursor · records synced · graph events emitted · errors.
- Inline actions: `Run sync` · `Edit` · `View jobs` · `Pause` · `Open lineage`.
- Inspector on row select: connector config, sync history (chart), last-error trace, OAuth scope list.

#### 5.6.4 Schema tab — **Preview** (Screen 04 of 06)

Rendered from Forge-emitted schema artifacts when present, falls back to runtime introspection.

Layout (sidebar collapsed for width):

- **Object tree** (240 px) — search filter (`Filter 64 tables · 142 dbt`), folder header (`LATTICE_DW.PROD_CORE`), scrollable list of tables with column count + iconography (`zap` amber for fact tables, `link` purple for bridge tables, dimmed gray for staged tables that need review). `+ 55 more tables · 142 dbt models · Load all →` link at bottom.
- **Center schema viewer**:
  - Header — table name (mono), inferred-entity badge (e.g. `→ Customer · entity`), `PII detected` badge, hint (col count · FK count · row count · last modified), buttons (`Preview`, `Copy DDL`).
  - **Columns table** — columns: `Column` (mono) · `Type` · `Null %` · `Inferred predicate` (blue/orange chip) · `Extraction` (`from PK` green, `inferred` blue, `enum` blue, `regex` blue, `temporal` green, `Forge · view` purple, `Forge · dbt metric` purple, `LLM-extracted` purple) · `PII` (amber chip with reason).
  - **Foreign-key graph** (SVG mini-map, 720 × 210, low-opacity grid background) — table nodes with type-coded headers, declared FKs as solid lines, inferred FKs as blue dashed lines with confidence labels (`0.94`).
- **Right inspector** (320 px) — when a column is selected:
  - Column title (mono), badges (`Forge · view`, `has_churn_risk`).
  - **View definition** panel — SQL code block (dark background, syntax highlighted) for Forge-derived views (`CREATE VIEW vw_customer_churn_risk AS …`).
  - **Distribution** panel — 8-bar histogram (green / amber / red), `0.0 low → 1.0 high` scale.
  - **Profile** panel — `P50` · `P95` · `Cardinality` · `Refresh` (e.g. `daily 04:00 UTC`).
  - Info callout — `Why Forge-derived?` (orange-soft band) explaining preservation of dbt metric semantics.

Empty state when no Forge mapping committed and no introspection is available: links to Forge Studio (Roadmap).

#### 5.6.5 Entities tab

Database table view of normalized entities:

- Filters: entity type · source · valid-at range · feedback-weight slider · search.
- Columns: ID (mono) · type · canonical name · source(s) · facts count · edges count · feedback weight · valid_at · last seen.
- Row click → inspector (Details / Lineage / Temporal / Feedback / Raw tabs) with full fact list (provenance + extraction method + valid_at/invalid_at), edges (in/out), episodes, supersession history.
- Bulk actions: open neighborhood in graph, export, mark for resolver review.

#### 5.6.6 Graph tab + Entity Inspector (Screen 05 of 06)

Full-bleed graph workbench (not boxed inside a card):

- Left tool rail — `select`, `pan`, `path`, `filter`, `layout`, `temporal mode` (current / as-of / replay).
- Top filter chips — source · node type · edge type · date range · confidence · extraction method · current-only.
- Bottom command bar — `@graph find path Sarah → Acme`, `@graph show neighborhood acme_uuid 2hops` (mono input with autocomplete on entities, sources, predicates).
- Right **Entity Inspector** (320 – 360 px) — on node selection (e.g. `Sarah Mitchell`):
  - Title + canonical id (mono), type badge, top-line facts (LTV, churn risk, etc.).
  - **Supersession chain** — vertical timeline of fact versions (`v3 churn=0.62 · superseded v2 churn=0.41 on 2026-04-14`).
  - **Top edges** — incoming and outgoing relationships with counts.
  - **Provenance** — source tables (mono) + extraction method per fact.
  - **Cohorts** — chip stack of cohorts the entity belongs to.
  - Footer actions: `Open in entities`, `Open lineage`, `Mark for resolver review`, `Copy id`.

V1 modes: neighborhood-from-search, source-scoped graph, entity-detail neighborhood.

#### 5.6.7 Query tab — Context Query Console (Screen 06 of 06)

This must not look like a generic chat app. It is a **database query console for AI context**. Layout (sidebar collapsed; 1 fr main + 360 px trace panel):

**Sub-header copy:** `recipe · RRF · p50 138 ms · p99 412 ms · tokens saved 84 %`. Buttons: `History`, `Lineage`, `Save query` (primary).

**Main column:**

- **Scope row** — source chips (e.g. `Snowflake`), temporal chip (`now` / `as_of …`), filter chips (`type · customer`, `cohort · VIP`). Right-side: `Recipe · RRF` selector, `Save` button.
- **Input panel** (code-editor style):
  - Prompt line: `> @search @graph VIP customers with elevated churn risk after recent returns this quarter — context + retention playbook`.
  - Mention bar — chips for `@search`, `@graph`, `@temporal as_of:…`, `@core …`, `@cohort …`, `@decision …`.
  - Token budget bar (`1,020 / 2,000 · 51 %`).
  - `⌘↵` kbd hint, primary `Run` button.
- **Answer panel** (sparkles icon header) — header badges: `★ 5` (rating), `138 ms` (latency), `−7,810 tok` (savings vs baseline). Markdown answer with mention chips for entities/decisions/playbooks.
- **What was retrieved** panel (2-column band) — `Top entities` chip stack (with feedback / churn scores) on the left; `Sources used` list on the right (`dim_customers · 8`, `fct_orders dbt · 6`, …, `all from snowflake-warehouse · LATTICE_DW`).
- **Context packet** panel (collapsible, open by default) — `JSON · 1,840 tokens` meta; dark code block showing the assembled context (cohort · primary_entities with facts · orders array · decisions array · playbook · metadata). This is the JSON output of the assembly pipeline (see `04-product-and-architecture.md` §closed loop).
- **Feedback** panel — `Rate this answer` thumbs-up + 5 stars; submission updates the EMA via `db.feedback()`.

**Right Query Trace panel (360 px):**

- **Pipeline** — 7 numbered steps, each with status dot and millisecond cost:
  1. `parse intent` — 4 ms
  2. `seed (BM25 + cosine)` — 18 ms
  3. `BFS · 2 hops` — 38 ms
  4. `rerank · RRF` — 14 ms
  5. `feedback · EMA` — 5 ms
  6. `temporal prune` — 7 ms
  7. `assemble · budget 2k` — 52 ms
- **Latency breakdown** — three bars (Retrieval 60 ms blue 43 % · Rerank + feedback 19 ms purple 14 % · Assemble 59 ms orange 43 %), totaling `138 ms`.
- **Token budget** — full bar (`92 %`), `used 1,840 / budget 2,000`.
- **Caller** — shield-check icon, avatar, name, role, audit id (mono).

#### 5.6.8 Temporal tab — **Preview**

V1 visual:

- Timeline of sync runs and graph events.
- Current vs historical toggle.
- Entity change stream.
- Source cursor positions.
- `As of` selector (placeholder until full bitemporal queries land).

Roadmap (clearly labeled placeholders): bitemporal validity matrix, supersession-chain visualizer, time-travel graph replay, `@temporal` query replay.

#### 5.6.9 Lineage tab — **Preview**

V1 visual:

- Trace: source record → sync job → normalized entity → graph event → graph node/edge → query result.
- Click any step to inspect payload.
- Failed/skipped graph events visible.

Roadmap placeholders: decision lineage path, policy reference, context-packet provenance, feedback weighting attribution.

#### 5.6.10 Decisions tab — **Preview**

A first-class entity browser scoped to `Decision` entities:

- Table: decision id · subject · outcome · decided_by · policy · effective_at · superseded_at.
- Inspector: full decision card — inputs (entity refs), policy reference, exception, justification, affected entities, supersession chain.

Empty state when no decision-emitting source connected: `No decisions ingested yet. Connect a CRM, a pricing_decisions table, or define a decision-extraction rule in Forge.`

#### 5.6.11 Drift tab — **Preview**

Five drift categories on inner tabs:

1. **Source schema drift** — new/removed columns, type changes.
2. **Entity drift** — stale or conflicting facts.
3. **Relationship drift** — disappearing or new edges.
4. **Context drift** — query answers changed because the underlying graph changed.
5. **Sync drift** — cursor lag, failed jobs, missing schedule.

V1 implements (1) and (5) where catalog exists; (2)–(4) are placeholder cards with honest empty states.

#### 5.6.12 Forge — **Roadmap**

3-pane Studio (left: source schema · center: proposed mapping · right: graph preview):

- Inferred entities, relationships, fact predicates, derived facts (formulas), episode types.
- Inline edits, bulk operations, validation warnings, sample-data trace.
- Diff against previous Forge Mapping version.
- Three smoke-test queries with response preview.
- Apply → emits versioned, content-addressed (SHA-256) Forge Mapping artifact.

UI is built; backend is Roadmap. Navigating here from a Forge-eligible source loads sample data labeled `Sample / preview` with a banner linking to `/docs/contextd/06-context-forge.md`.

#### 5.6.13 Resolver — **Roadmap**

Identity-stitching review surface backed by the Identity Graph:

- **Resolver Profiles** (per entity type — person, account, contact, deal …).
- **Stage timeline:** HNSW + LSH blocking → Fellegi–Sunter → cross-encoder → cross-doc coreference → PSL transitive closure → active-learning adjudication.
- **Adjudication queue:** residual hard cases (each with side-by-side records, candidate match score, accept / reject / merge actions).
- **Identity Graph viewer:** canonical entity → source-record-IDs across sources, with confidence + audit trail.

`Roadmap` badge; sample mode loads a labeled fixture.

#### 5.6.14 Cores — **Roadmap**

Context Cores = CI / CD for knowledge.

- **Snapshot list:** version (mono SHA-256 short hash) · created · size · entities · edges · embeddings · weights · status (`draft` / `testing` / `promoted` / `archived`).
- **Workflow rail:** Build → Test → Promote → Rollback (mirrors a CI pipeline).
- **Diff view:** entity / edge / fact / weight diff between two cores.
- **Test panel:** query suite results across cores.

`Roadmap` badge; UI design proposal renders with sample data.

#### 5.6.15 Settings

- **General:** name, readable id, retention, region (Roadmap).
- **Sync policies:** default schedules, dead-letter behavior, rate limits per connector.
- **Indexing:** vector profile (HNSW M / ef), BM25 analyzer, embedding model (read-only V1).
- **Graph:** edge confidence threshold, relationship-extraction policy, ontology profile.
- **Feedback:** EMA α (default 0.10, read-only V1), feedback retention.
- **API access:** API keys (SHA-256, never re-shown), MCP transports enabled, wire-protocol toggles (Bolt / pgsql / mongo / redis / gRPC / HTTP) — Roadmap chips.
- **Danger zone:** archive · delete (typed-confirmation modal — current pattern in code).

### 5.7 Cross-database Query Console (`/query`)

A peer of the workbench Query tab, scoped *across* databases:

- Same scope row, mention chips, input panel, answer / retrieved / context packet panels, query trace panel.
- Scope chip in the header lets the user fan out across databases the user can read.

### 5.8 Saved Queries (`/saved-queries`)

Library of query recipes (count `[38]` in the sidebar of the mockup). Columns: name · scope · recipe · last run · p50 latency · star rating · last edited. Row click → opens the query in the Query Console with scope and mention chips pre-populated.

### 5.9 Cross-database Graph Explorer (`/graph`)

Peer of the workbench Graph tab, scoped across databases. Same canvas + inspector pattern. Useful for org-wide identity neighborhoods.

### 5.10 Cohorts

- Builder: criteria over entity types, facts, edges, time windows, feedback weight.
- Saved cohorts list with row counts and last refresh.
- Cohort detail: members table, change-log, feedback aggregates.

### 5.11 Admin Console

Operator console for the workspace:

- **Sync lifecycle:** queue depth · running · failed · DLQ.
- **Graph event backlog:** committed / pending / failed.
- **Worker health:** Temporal workers, queue health.
- **Source rate limits:** per-connector budgets and current burn.
- **Auth providers:** OAuth scope coverage, expirations.
- **Organizations / users:** members, roles, API key inventory, audit log tail.

High visual density. No spacing waste.

### 5.12 MCP Server Console — **Preview**

Two-layer model from the spec:

- **Substrate built-ins** — `execute_command`, `get_schema`, `query` (Roadmap once substrate migration lands).
- **ContextD context tools** — `query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `get_saga_summary`, `submit_feedback`, `ingest_episode` (Preview today against the V1 stack).

Surface:

- Transports table: `stdio` / `SSE` / `HTTP` (status · port · auth).
- Tool registry: name · status · last invocation · p50 latency · errors.
- Live invocation log (tail).
- "Connect from Claude Code / Cursor / Windsurf" snippet generator.

## 6. UX Invariants

- **Density beats decoration.** Tables, panels, bands, drawers, split panes — not cards inside cards.
- **Provenance everywhere.** Any displayed fact, edge, or answer is one click from its lineage.
- **Honesty about state.** Empty states are operational; preview/roadmap surfaces are clearly labeled. Mention `Lattice Compute` only as the demo tenant — the product itself is tenant-neutral.
- **Mono for IDs / queries / hashes / numbers.** Sans for prose. No exceptions.
- **Orange = action / selection.** Other colors only for semantic system state (green healthy, amber pending, blue indexing/info, red failing, purple LLM/inferred/Forge-derived).
- **Sidebar collapses for the dense screens.** Schema and Query default to a 56 px icon-rail to maximize content width.
- **The trace panel is non-collapsible on Query.** It is part of the surface, not an optional disclosure — surfacing the 7-step pipeline is the product's differentiator.
- **Tab rail is grouped, not flat.** `Operate` / `Inspect` / `Build` headers anchor the user's mental model of running, looking at, and constructing a context database.
- **Keyboard first.** `⌘K` everywhere. Tab navigation through tables. `?` opens a shortcut sheet.

## 7. From-Today Transition

This file describes the target. The phased migration plan from today's `frontend/` (4-item flat sidebar, no tabbed workbench, single `Dashboard` chat page) to the structure above lives in [`contextd-ui-transition-plan.md`](./contextd-ui-transition-plan.md).
