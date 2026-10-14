# ContextD UI Component Spec

> Composition rules for every primary surface in the console. Every component listed below maps to a shadcn primitive composition (or a small custom assembly) and lives in `frontend/src/components/`.
>
> The canonical visual reference is `/docs/ui/contextd-screens-final.html` — the production mockup of the six core screens. Where this spec and the HTML disagree, the HTML wins.
>
> Status tags use the same vocabulary as `contextd-ui-flow-plan.md`: **V1**, **Preview**, **Roadmap**.

## 1. AppShell (`V1`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Topbar  (breadcrumb · ⌘K · env · API health · bell · theme · user)   │  52 px
├──────────────┬───────────────────────────────────────────────────────┤
│              │                                                        │
│  Sidebar     │   Page slot                                            │
│  244/56 px   │                                                        │
│              │                                                        │
├──────────────┴───────────────────────────────────────────────────────┤
│ Footer status (org · db · last sync · pending · α · build hash)      │  28 px
└──────────────────────────────────────────────────────────────────────┘
```

**Sidebar layout (top → bottom):**

1. ContextD wordmark + collapse toggle (52 px header).
2. Project / org switcher pill (e.g. `Lattice Compute · Pro`).
3. `Workspace` group: `Databases [n]`, `Query console`, `Source catalog [n]`, `Graph explorer`, `Saved queries [n]`, `Alerts [n warn]`.
4. `Operations` group: `MCP server (Preview)`, `Admin`.
5. `Settings` group: `Auth providers`, `Organization`.
6. Utility row: `Help`, `Feedback`.
7. User card (avatar, name, role · domain).

Active item = `bg-orange-soft`, `text-orange`, 2 px orange left indicator. Counts use `nav-count` (gray default, amber `warn`, red `danger`). Schema and Query screens default the sidebar to **collapsed (56 px)** — the user can re-expand, but width is the right default.

**Topbar (52 px):** breadcrumb · `⌘K` palette · environment badge · API health pill (`Operational`, green pulsing dot) · notifications bell · theme toggle · user avatar.

**Footer (28 px, mono):** `org_… · db · last sync · pending n · α=0.10 · build hash`. Always visible on desktop, collapsed on mobile.

shadcn primitives: none directly; uses tailwind + lucide.

## 2. PageHeader (`V1`)

```
[breadcrumb]
Title                                       [primary action] [kebab]
subtitle / status badges / counts / org id
```

Slots: `title`, `subtitle`, `breadcrumb`, `status` (StatusBadge / StatusPill), `actions`, `kebab`. No background gradient. `border-b` separates the header from the body.

## 3. DatabaseSubHeader (`V1`)

The 52 px band immediately below the topbar on every workbench tab.

```
[icon-tile] customer-360-prod   ● Healthy    v1.4.2 · 3-node Raft · core prod:v143    [Query] [Connect source] [Build core] [Run sync] [⋯]
                                ctxdb_cust_360 · 4.04M entities · 9 sources
```

- Icon-tile: orange-soft 28 px square with database glyph.
- Health pill: `StatusPill` with pulsing dot.
- Substrate metadata: mono, single line.
- Action buttons right-aligned. `Build core` is `Roadmap` (disabled with badge).

## 4. StatusBadge / StatusPill (`V1`)

11 px pill. Variants:

- **System state:** `healthy` (green) · `pending` (amber) · `running` (blue, pulse) · `failed` (red) · `inferred` (purple) · `disabled` (gray).
- **Implementation:** `v1` (green) · `preview` (blue) · `roadmap` (purple).
- **PII:** `pii-email` · `pii-name` · `pii-free-text` (all amber with reason text).
- **Extraction:** `from-pk` (green) · `inferred` (blue) · `enum` (blue) · `regex` (blue) · `temporal` (green) · `forge-view` / `forge-dbt-metric` (purple) · `llm-extracted` (purple).

Usage: `bg-{tone}/10 text-{tone} border border-{tone}/22`. The `running` and `Operational` variants animate a 1 s pulsing dot.

## 5. KPIStrip (`V1`)

5 – 7 dense metrics in one row. Each cell:

```
┌──────────────────────┐
│ label (xs subtle)    │
│ value (text-2xl, 600)│
│ delta or sub-metric  │
└──────────────────────┘
```

- Sparkline allowed inline if data exists.
- Cells fully equal-width on desktop; collapse to 2-col grid on mobile.
- Color *only* for semantic deltas (red / green) — never decoration.

Canonical compositions:

- **Dashboard (7 tiles):** `Databases` · `Sources` · `Entities` · `Edges` · `Pending` · `Drift` · `Avg feedback`.
- **Workbench Overview (6 tiles):** `Entities` · `Edges` · `Episodes` · `Pending` · `Avg feedback` · `Tokens saved`.

## 6. DatabaseCard / DatabaseTable (`V1`)

`DatabaseCard` — used in onboarding empty state and the dashboard's right rail:

- Title (database name) + readable id (mono).
- Sources stack icon row.
- Health · Temporal · Drift badges.
- Last sync (relative).
- One primary action: **Open workbench**.

`DatabaseTable` — primary list on the dashboard:

| Column | Type | Notes |
|---|---|---|
| Database | name + readable id (mono) | Click → `/databases/:readableId` |
| Sources | logo stack + count | Hover shows full list |
| Entities | mono right-aligned | Includes `+ delta / 24 h` on hover |
| Edges | mono right-aligned | |
| Graph | StatusBadge | `indexed` / `partial` / `indexing` (pulse) / `failing` / `empty` |
| Temporal | StatusBadge | `current` / `partial` / `planned` |
| Drift | StatusBadge | `clean` / `warnings` / `failing` |
| Last sync | mono relative | |
| Actions | inline buttons + kebab | `Run sync`, `Open workbench`, more |

Empty databases render an inline `Connect source` action where the metrics would otherwise sit.

shadcn primitives: `Card`, `Table`, `Badge`, `DropdownMenu`.

## 7. SourceConnectorCard (`V1`)

```
┌──────────────────────────────────────────────────┐
│ [logo] Source name                               │
│        [auth] [sync] [introspection]             │
│        [temporal-cursor] [extraction] [forge]    │
│                                                   │
│        Description (1 line)                       │
│                                                   │
│ [Connect]  [Docs]                                │
└──────────────────────────────────────────────────┘
```

- Chips defined in `contextd-ui-flow-plan.md` §5.4. Forge-eligibility chip (`Forge`) only on relational + SaaS structured sources.
- P0 cards: thin orange left border.
- Roadmap connectors render disabled with `Roadmap` badge.

## 8. SourceSetupWizard (`V1`)

Layout: split pane, **60 % left form / 40 % right preview** (sticky). Step indicator across the top.

- 5 steps: `Auth` → `Test` → `Discover` → `Scope` → `Schedule`.
- Step indicator: green check for done, orange ring for current, gray for pending.
- Previous-step rows are condensed into one-line green check summaries (e.g. `Step 2 · Test · key-pair · 28 ms · SELECT ✓ · USAGE ✓ · 64 tables · 142 dbt models`).

**Discover step** sub-components (`DiscoveredObjectsTable`):

- Filter input + `Select all` button.
- Table: checkbox · `Table` (mono) · `Rows` · `Cols` · `FKs` · `Inferred entity` (typed badge) · `PII` (amber chip).
- Bulk-action footer: `n of m selected · k hidden · Show all p →`.

**Right preview pane** (sticky):

- `SourceIdentityPanel` — Account · Database · Schema · Role · dbt project (mono key/value list).
- `TargetDatabasePanel` — name pill with `primary` badge.
- `ForgeCalloutBanner` — orange-soft band with `Roadmap` pill: `Forge will refine these mappings on first sync — open Forge Studio`.
- `SyncEstimatePanel` — Rows · Entities · Embeddings (count · 1024 d) · Storage · First sync · Incremental.

Action bar (sticky bottom): `Back` · summary text · `Save draft` · `Continue`.

## 9. WorkbenchShell (`V1`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ DatabaseSubHeader (name · id · health · metadata · actions)          │
├────────┬───────────────────────────────────┬─────────────────────────┤
│ Tab    │ Active tab content                │ InspectorPanel          │
│ rail   │                                   │ 320 / 360 px            │
│ 180–   │                                   │ (resizable, dismissable)│
│ 200 px │                                   │                         │
└────────┴───────────────────────────────────┴─────────────────────────┘
```

Tab rail = `WorkbenchTabRail` with three groups (`Operate` / `Inspect` / `Build`), each with a small caps eyebrow and dense list. Active tab: orange left indicator + orange-soft background. Counts and status badges render inline (Sources [9], Entities [4.04M], Drift [2 amber], etc.).

InspectorPanel is 320 px on most tabs, **360 px on Graph and Query** (where the inspector / trace carries more content), `100 %` on mobile slide-up. Resizable splitter between the main pane and the inspector.

## 10. SyncPipelinePanel (`V1`)

10-step ordered list. Each step is a row:

```
●  1   extract                          done       142 ms
●  2   normalize                        done        58 ms
●  3   enrich                           done        31 ms
●  4   graph events                     done        24 ms
○  5   resolve sem. + LLM    4/6        running    pulse
●  6   embed                            queued        —
○  7   temporal commit       18         pending      —
○  8   community detect                 not started  —
○  9   feedback rebalance               not started  —
○ 10   publish                          not started  —
```

Status dots: green `done`, orange pulse `running`, blue `queued`, amber `pending` with count, gray `not started`. Click any step → opens lineage scoped to that step.

## 11. EntitiesByTypePanel (`V1`)

Gauge list with color-coded dot per type:

```
●  Customer    1.42M   +3.2K / 24h
●  Product     28.4K   +120
●  Order       2.42M   +8.1K
●  Episode     412K    +1.4K
●  Decision    1,832   +12
●  Review      184K    +540
```

Order respects type prevalence; deltas use `text-green` for positive, `text-red` for negative, `text-muted` for zero.

## 12. ActiveSourcePanel (`V1`)

Single highlighted row:

```
[Snowflake] snowflake-warehouse  6.9M / 18.2M    [████░░] 38%   in progress    0 errors    [⋯]
```

Footer link: `8 other sources synced · 0 errors · View all →`.

## 13. SchemaTab Components (`Preview`)

### 13.1 SchemaObjectTree (240 px)

Filter input · folder header (`LATTICE_DW.PROD_CORE`) · scrollable list of tables. Each row: icon (zap amber for fact, link purple for bridge, gray dimmed for staged) · table name (mono) · column count. Selected row: orange-soft background, orange left border. Footer link: `+ k more tables · m dbt models · Load all →`.

### 13.2 SchemaColumnTable

Sticky header. Columns:

| Header | Content |
|---|---|
| Column | mono name + id badge (orange) for keys |
| Type | mono |
| Null % | mono right-aligned |
| Inferred predicate | typed chip (`has_email`, `has_country`, `has_churn_risk`) |
| Extraction | typed chip — `from PK`, `inferred`, `enum`, `regex`, `temporal`, `Forge · view`, `Forge · dbt metric`, `LLM-extracted` |
| PII | amber chip with reason |

Row click → ColumnInspector.

### 13.3 ForeignKeyGraph

SVG mini-map (default 720 × 210, low-opacity grid background). Nodes: type-coded headers (orange dim, green dim, blue dashed for derived/inferred, purple for bridge). Edges: solid lines for declared FKs, blue dashed for inferred FKs with confidence labels (`0.94`).

### 13.4 ColumnInspector (right rail)

- Title: column name (mono) + extraction badge + predicate badge.
- `ViewDefinitionPanel` — SQL code block (dark, syntax highlighted) for Forge-derived views.
- `DistributionPanel` — small histogram (8 bars, green / amber / red), scale `0.0 low → 1.0 high`.
- `ProfilePanel` — `P50` · `P95` · `Cardinality` · `Refresh`.
- `WhyForgeDerivedCallout` — orange-soft band explaining preservation of upstream semantics.

## 14. EntityTable (`V1`)

- Columns: ID (mono) · type · canonical name · sources · facts · edges · feedback weight · valid_at · last seen.
- Filters above: type · source · valid-at range · feedback-weight slider · search.
- Row click → InspectorPanel.

## 15. GraphCanvas (`V1`)

- Full-bleed (no card container). Background grid at low opacity.
- **Left tool rail:** `select` / `pan` / `path` / `filter` / `layout` / `temporal mode (current / as-of / replay)`.
- **Top filter chips:** source · node type · edge type · date range · confidence · extraction method · current-only.
- **Bottom command bar:** `@graph …` autocomplete (mono, suggests entities, predicates, sources).
- **Right inspector:** `EntityInspector` for nodes; edge inspector when an edge is selected.

Encoding rules (shape + color) live in `contextd-theme-plan.md` §Visual Language. Edge styles: solid (confirmed), dashed (inferred / LLM), dotted (temporal / historical), thick orange (selected path), low-opacity (outside current context window).

## 16. EntityInspector (`V1`)

Right-side panel on Graph and Entities tabs.

- Header: name + type badge + canonical id (mono).
- Top-line facts band (e.g. `LTV $48.2K · churn 0.62 · 3 returns this Q`).
- **SupersessionChain** — vertical timeline of fact versions: `v3 churn=0.62 · superseded v2 churn=0.41 on 2026-04-14`.
- **TopEdges** — incoming + outgoing relationships with counts.
- **ProvenancePanel** — source tables (mono) + extraction method per fact.
- **CohortsPanel** — chip stack of cohorts the entity belongs to.
- Footer actions: `Open in entities`, `Open lineage`, `Mark for resolver review`, `Copy id`.

## 17. QueryConsole (`V1`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ scope: [snowflake] [now] [type · customer] [cohort · VIP]   recipe   │
├──────────────────────────────────────────────────────────────────────┤
│ > @search @graph VIP customers with elevated churn risk after recent │
│   returns this quarter — context + retention playbook                │
│ [@search] [@graph] [@temporal] [@core] [@cohort] [@decision]         │
│  token budget [████░░░░░░] 1,020 / 2,000   ⌘↵   [Run]                │
├──────────────────────────────────────────────────────────────────────┤
│ ✦ Answer                                  ★ 5  138 ms  −7,810 tok    │
│ Markdown answer with entity / decision / playbook chips inline       │
├──────────────────────────────────────────────────────────────────────┤
│ What was retrieved                                                    │
│  Top entities    [chip] [chip] [chip] [chip] … [+20 more]            │
│  Sources used    dim_customers · 8                                    │
│                  fct_orders dbt · 6                                   │
│                  …                                                    │
│  all from snowflake-warehouse · LATTICE_DW                            │
├──────────────────────────────────────────────────────────────────────┤
│ ▼ Context packet                                JSON · 1,840 tokens   │
│   {  "cohort": "vip",                                                 │
│      "primary_entities": [ … ],                                       │
│      "orders": [ … ],                                                 │
│      "decisions": [ … ],                                              │
│      "playbook": { … },                                               │
│      "metadata": { … } }                                              │
├──────────────────────────────────────────────────────────────────────┤
│ ▶ Rate this answer  ★★★★★                                             │
└──────────────────────────────────────────────────────────────────────┘
```

- `ScopeRow` — source chips · temporal chip · filter chips · `Recipe · RRF` selector.
- `MentionChip` set: `@search`, `@graph`, `@temporal as_of:…`, `@core …`, `@cohort …`, `@decision …`.
- `TokenBudgetBar` — orange progress, `used / budget` mono.
- `AnswerPanel` — sparkles icon header, badges (rating · latency · tokens saved vs chunk-RAG).
- `RetrievedPanel` — left `Top entities` chip stack (with feedback / churn scores), right `Sources used` list with counts.
- `ContextPacketPanel` — collapsible (open by default), dark monospace code block, header meta `JSON · n tokens`. Output of the assembly pipeline (see `04-product-and-architecture.md` §closed loop).
- `FeedbackPanel` — 5 stars + thumbs-up; submission updates EMA via `db.feedback()`.

## 18. QueryTracePanel (`V1`)

Right-side sticky panel (360 px) on the Query tab. Always visible — not collapsible.

- **Pipeline** (7 numbered steps):
  1. `parse intent` (4 ms)
  2. `seed (BM25 + cosine)` (18 ms)
  3. `BFS · 2 hops` (38 ms)
  4. `rerank · RRF` (14 ms)
  5. `feedback · EMA` (5 ms)
  6. `temporal prune` (7 ms)
  7. `assemble · budget 2k` (52 ms)
- **LatencyBreakdown** — three bars: `Retrieval (1–3)` blue, `Rerank + feedback (4–5)` purple, `Assemble (6–7)` orange. Total above (`138 ms`).
- **TokenBudget** — full bar with percentage, `used / budget` mono.
- **CallerCard** — shield-check icon, avatar gradient, name, role, audit id (mono).

V1 wires the pipeline and latency from today's hybrid-search service; substrate-level fields are gated behind Roadmap labels.

## 19. SchemaTable (`Preview`)

(See §13 — the Schema tab assembles `SchemaObjectTree` + `SchemaColumnTable` + `ForeignKeyGraph` + `ColumnInspector`.)

## 20. LineageTimeline (`Preview`)

Time-ordered event stream: source record → sync job → normalized entity → graph event → graph node/edge → query result. Each step is a chip with payload preview on click. Failed/skipped graph events visible with a red badge.

## 21. DecisionCard (`Preview`)

Subject · outcome · decided_by · policy reference. Inputs (entity refs, click → InspectorPanel). Exception · justification. Affected entities (chip stack). Supersession chain (timeline).

## 22. DriftPanel (`Preview`)

Inner tab strip: `Source schema` · `Entity` · `Relationship` · `Context` · `Sync`. V1 implements *Source schema* and *Sync*; the others render an empty state with the criterion that would trigger them.

## 23. ForgeStudio (`Roadmap`)

3-pane:

```
┌──────────┬─────────────────────────┬──────────────┐
│  Source  │  Proposed mapping       │  Graph       │
│  schema  │  (entities / relations  │  preview     │
│  tree    │   / facts / derived /   │  (canvas)    │
│          │   episodes)             │              │
└──────────┴─────────────────────────┴──────────────┘
[Diff vs vN-1]   [Smoke test queries]   [Apply → Forge Mapping vN]
```

Inferred mapping editable inline; bulk operations on row select. Validation warnings render in a banner. Sample-data trace per row. `Roadmap` badge in header; sample fixture mode is the V1 representation.

## 24. ResolverStudio (`Roadmap`)

- **Resolver Profile selector** (per entity type — Person, Account, Contact, Deal, …).
- **Stage timeline:** `Blocking` → `Fellegi–Sunter` → `Cross-encoder` → `Coreference` → `PSL transitive closure` → `Active learning`. Each stage shows pass-through count + match rate.
- **Adjudication queue:** residual hard cases. Each case = side-by-side records + score + `Accept` / `Reject` / `Merge`.
- **Identity Graph viewer:** canonical entity → source-record-IDs across sources, with confidence + audit trail.

## 25. CoresPanel (`Roadmap`)

```
┌─────────────────────────────────────────────┬─────────────────────┐
│ Snapshots                                    │ Workflow            │
│  hash · created · status · entities · edges  │  ● Build            │
│  · embeddings · weights · size               │  ● Test             │
│                                              │  ● Promote          │
│                                              │  ● Rollback         │
├─────────────────────────────────────────────┼─────────────────────┤
│ Diff (entity / edge / fact / weight)         │ Test results        │
└─────────────────────────────────────────────┴─────────────────────┘
```

Mono SHA-256 short hashes everywhere. Test panel runs the saved query suite across one or two cores.

## 26. MCPConsole (`Preview`)

- **Transports table:** `stdio` · `SSE` · `HTTP` (status · port · auth).
- **Tool registry:** name · status · last invocation · p50 latency · errors.
- **Invocation tail:** live log of the last N calls.
- **Snippet generator:** `Connect from Claude Code / Cursor / Windsurf` → copy-paste config.

## 27. SavedQueriesPanel (`V1`)

Library at `/saved-queries` (and the dashboard's right-rail "Recent queries" widget):

- Columns: `Name` · `Scope` · `Recipe` · `Last run` (mono relative) · `p50 latency` · `★ rating` · `Last edited`.
- Row click → opens the query in the QueryConsole with scope and mention chips pre-populated.
- Right-rail variant on the dashboard shows the top 5 with star, token, latency only.

## 28. InspectorPanel (`V1`)

Universal right-side details panel. Slots:

- `title` (entity / edge / run / source / column / decision / event).
- `metaRow` (mono ID, type, source, status badges).
- `tabs` (Details / Lineage / Temporal / Feedback / Raw).
- `body` per tab.
- `actions` (footer: `Open in graph`, `Open lineage`, `Copy id`, `Mark for resolver review`).

## 29. EmptyState (`V1`)

- Single icon (lucide).
- One-line description of what's missing.
- One primary action.
- Optional one-line `What will be created` preview.
- No hero. No marketing.

## 30. CommandPalette (`V1`)

`⌘K` opens.

- Sections: `Databases` · `Sources` · `Entities` · `Saved queries` · `Cores` · `Cohorts` · `Settings` · `Docs`.
- Inline `@search …` runs a query.
- Inline `:settings api keys` jumps to a settings sub-section.
- Keyboard shortcuts visible on each row.

## 31. Form Patterns (`V1`)

- shadcn `Form` + `react-hook-form` + zod schemas.
- Inline validation (right of input, single line).
- Dangerous actions: typed-confirmation pattern (already in code) — preserved.
- Sensitive fields (API keys, passwords): masked; with `Reveal` and `Copy` (audit-logged).

## 32. Theming Hooks

- `<ThemeProvider>` (already in `lib/theme-provider.tsx`) — preserve.
- Hard rule: components never set dark/light surface colors directly; they reference shadcn CSS vars (`bg-background`, `text-foreground`, `border-border`, etc.). Any non-token color must come from one of the brand tokens (`orange`, `amber`, `green`, `blue`, `red`, `purple`).
- Status pills use `bg-{tone}/10 text-{tone} border-{tone}/22`. The pulsing dot uses a 1 s `pulse` animation only on `running` and `Operational` variants.

## 33. Acceptance Criteria

A component ships only when:

1. It renders correctly on both light and dark.
2. Status surfaces use the implementation-status badge vocabulary (`V1` / `Preview` / `Roadmap`).
3. Empty states are operational.
4. IDs / hashes / timestamps render in mono (JetBrains Mono).
5. Keyboard navigation works across the primary axis (rows, tabs, mention chips).
6. Tooltips exist on every icon-only control.
7. The component does not invent data: Preview / Roadmap surfaces clearly say so.
8. Density matches the HTML reference: row height ≤ 40 px compact / 48 px comfortable, panel inner padding `p-4` to `p-6`, no card-in-card.
