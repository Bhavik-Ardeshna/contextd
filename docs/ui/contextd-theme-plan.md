# ContextD UI Theme Plan

> Visual reference: `/docs/ui/contextd-screens-final.html`. This file pins the design tokens that the HTML resolves at runtime; both Markdown and HTML are kept in sync.

## Direction

ContextD's console must feel like an **enterprise database control plane** for AI context: dense, precise, technical, fast. The closest energy is Supabase Studio / Neon / Linear (infra clarity, low chrome) — but the visual subject is *graph + bitemporal context*, so the theme makes relationships, temporal state, lineage, and provenance visible everywhere.

Both **light** and **dark** themes are first-class. Operators on call run dark in low-light environments and light in well-lit offices. The product must respect both. Defaults to **system**.

The light theme is the canonical surface in the production mockup — a calm, warm-neutral cream/white that lets the orange brand and the semantic accents do all the visual work. The dark theme inverts to graphite/black with the same hue intent. Operators see the same data hierarchy regardless of theme.

## Product Feel

- **Database first.** Every page surfaces database concepts: entities, edges, facts, episodes, decisions, indexes, cores, sync jobs, schemas, lineage.
- **Context graph first.** The graph is a navigable data structure with provenance, validity, and confidence — not decoration.
- **Enterprise calm.** High contrast, low noise, precise tables, compact panels, clear operational states. No marketing blobs. No oversized hero. No glassy gradients inside the app.
- **Modern but not playful.** Restrained motion. No icon spam. No mystery-meat IA.
- **Black/orange identity.** Orange is the command/action color in both themes. Surfaces shift; hue intent stays.

## Design Tokens

### Core Palette

| Token | Dark | Light | Usage |
|---|---|---|---|
| `background` | `#050505` | `#FAFAF7` | App body, login base, graph canvas base |
| `surface-1` | `#0A0A0A` | `#FFFFFF` | Sidebar, topbar, primary panels |
| `surface-2` | `#111111` | `#F6F6F2` | Cards, sheets, dialog body, table rows |
| `surface-3` | `#191919` | `#EFEFEA` | Hover row, nested controls, segmented control track |
| `border` | `#2A2A2A` | `#E5E5E0` | Default boundaries |
| `border-strong` | `#3A3A3A` | `#CFCFC8` | Focus, selected rows, primary panels |
| `foreground` | `#F6F6F4` | `#0E0E0E` | Primary text |
| `muted` | `#A3A3A3` | `#5A5A5A` | Secondary text |
| `subtle` | `#6F6F6F` | `#8A8A87` | Hint, metadata, disabled text |
| `orange` | `#E45F1A` | `#E45F1A` | Primary action, selected nav, hot path |
| `orange-soft` | `#FF8A3D` | `#F26B2C` | Hover, focus ring, graph glow |
| `amber` | `#F4B04A` | `#C8801B` | Temporal drift, warning, pending sync |
| `green` | `#48C78E` | `#1F9D6A` | Healthy, synced, complete |
| `blue` | `#5DADEC` | `#1F86CC` | Indexing, info, vector memory |
| `red` | `#EF5350` | `#D03A36` | Error, failed sync, destructive |
| `purple` | `#A78BFA` | `#7B5CF0` | LLM extraction, inferred entity |

> Light-theme accents are *slightly* darkened so badges remain legible on a cream background without losing the brand mapping.

### shadcn CSS Variable Mapping

```css
:root,
.light {
  --background: 40 25% 97%;
  --foreground: 0 0% 5%;
  --card: 0 0% 100%;
  --card-foreground: 0 0% 5%;
  --popover: 0 0% 100%;
  --popover-foreground: 0 0% 5%;
  --primary: 18 79% 50%;
  --primary-foreground: 0 0% 100%;
  --secondary: 40 15% 95%;
  --secondary-foreground: 0 0% 5%;
  --muted: 40 12% 92%;
  --muted-foreground: 0 0% 35%;
  --accent: 40 15% 95%;
  --accent-foreground: 0 0% 5%;
  --destructive: 2 70% 52%;
  --destructive-foreground: 0 0% 100%;
  --border: 40 10% 88%;
  --input: 40 10% 88%;
  --ring: 18 79% 50%;
  --radius: 0.5rem;
}

.dark {
  --background: 0 0% 2%;
  --foreground: 60 9% 96%;
  --card: 0 0% 6%;
  --card-foreground: 60 9% 96%;
  --popover: 0 0% 6%;
  --popover-foreground: 60 9% 96%;
  --primary: 18 79% 50%;
  --primary-foreground: 0 0% 100%;
  --secondary: 0 0% 10%;
  --secondary-foreground: 60 9% 96%;
  --muted: 0 0% 12%;
  --muted-foreground: 0 0% 64%;
  --accent: 0 0% 10%;
  --accent-foreground: 60 9% 96%;
  --destructive: 2 83% 63%;
  --destructive-foreground: 0 0% 100%;
  --border: 0 0% 16%;
  --input: 0 0% 16%;
  --ring: 18 79% 50%;
  --radius: 0.5rem;
}
```

### Typography

- **Sans:** `Inter` (preferred) → fallback `ui-sans-serif`, `system-ui`.
- **Mono:** `JetBrains Mono` (preferred) → fallback `ui-monospace`, `SFMono-Regular`, `Menlo`. Used for IDs, hashes, query snippets, schema fields, timestamps, line counts, paths.
- **Scale**
  - Page title: `text-2xl` to `text-3xl`, semibold (600).
  - Section title: `text-base`, semibold.
  - Panel title: `text-sm`, semibold.
  - Body: `text-sm`.
  - Metadata: `text-xs`.
  - Badges: `text-[11px]`.
- **Tracking:** default. No negative tracking. Uppercase only on `eyebrow`-class labels (one wordmark deep at most).

### Radius, Density, Layout

- Base font size: `13 px` (`text-sm`-equivalent). Line-height: `1.45`. Numbers and IDs in JetBrains Mono.
- Radius scale: `8 px` (panels), `6 px` (buttons / inputs), `5 px` (smaller controls / chips). Modals / sheets max `10 px`.
- App gutters: `24 px` desktop, `16 px` tablet, `12 px` mobile.
- **Sidebar:** `244 px` expanded, `56 px` collapsed. Schema and Query tabs default to collapsed for content width.
- **Topbar:** `52 px`. **Footer status strip:** `28 px`. **DatabaseSubHeader:** `52 px`.
- **Workbench tab rail:** `200 px` on Overview, `180 px` on Schema / Graph / Query.
- Table row: `40 px` compact, `48 px` comfortable. (Power-user toggle.)
- No card-in-card. Use panels, bands, tables, split panes, drawers.
- Right inspector: `320 px` desktop default, `360 px` on Graph and Query (where the inspector / trace carries more content), `100 %` mobile slide-up.

### Surface Patterns

- **Panel** = `surface-1` background + 1px `border` + 8px radius + small inner padding (`p-4` to `p-6`). No drop shadow on light. Subtle `panel` shadow on dark only.
- **Band** = full-width section divider with `border-y` + `surface-2` (used in workbench between tabs and inspector).
- **Section header** = small caps eyebrow + title + actions on right. Always 1 row.

## Visual Language

### Grid Backgrounds

Used only on login, empty states, graph canvases, onboarding. Inside the product, grids are nearly invisible.

- Dark grid line: `rgba(255,255,255,0.035)`.
- Light grid line: `rgba(0,0,0,0.04)`.
- Orange graph line glow: `rgba(228,95,26,0.20)` dark; `rgba(228,95,26,0.18)` light.
- Node glow: `rgba(228,95,26,0.35)` dark; `rgba(228,95,26,0.18)` light.

### Graph Encoding

Visuals encode meaning — never decoration.

| Type | Shape | Color | Notes |
|---|---|---|---|
| Source record | Rounded square | blue-gray | Raw connector record |
| Person | Circle | orange | People (Gmail, Slack, Salesforce contacts) |
| Organization / Account | Hex-like rounded square | green | Companies, teams |
| Database table | Cylinder | blue | Postgres / Snowflake / ClickHouse / Salesforce object |
| LLM extraction | Diamond | purple | Inferred node or relationship |
| Temporal event / Episode | Pill | amber | Validity or change event |
| Decision | Shield | orange-red | Auditable decision entity |
| Forge-derived fact | Square w/ corner mark | blue | Deterministically derived (no LLM) |

Edge styling:

- Solid: confirmed.
- Dashed: inferred / LLM extraction.
- Dotted: temporal / historical.
- Thick orange: selected path.
- Low opacity: outside current context window.

### Status Colors (universal)

- **Healthy / synced**: green
- **Pending / scheduled**: amber
- **Running / indexing**: blue
- **Failed / drift / conflict**: red / orange-red
- **Inferred / LLM**: purple
- **Empty / unknown / disabled**: gray

### Implementation Status Badges

- `V1` — green soft (`bg-green/10 text-green border-green/20`)
- `Preview` — blue soft
- `Roadmap` — purple soft
- `Disabled` — gray soft

These run as 11px pills next to surface titles where applicable.

## Component System

shadcn primitives + tailwind utilities. Composition over one-off visual hacks.

Detailed specs live in [`contextd-ui-components.md`](./contextd-ui-components.md). Inventory:

- `AppShell` — sidebar + topbar + content + footer status.
- `PageHeader` — title, breadcrumbs, status badge, actions.
- `MetricStrip` — 5–8 dense operational metrics with deltas.
- `DatabaseCard` / `DatabaseTable` — context-database list + status + sync action.
- `SourceConnectorCard` — auth / sync / introspection / temporal / extraction chips.
- `SourceSetupWizard` — 5-step wizard + right-side live preview pane.
- `WorkbenchShell` — vertical tab rail + main + right inspector.
- `EntityTable` — database-table view with feedback-weight slider.
- `GraphCanvas` — full-bleed canvas + tool rail + filter chips + bottom command bar + right inspector.
- `QueryConsole` — scope selector + mention chips + answer + retrieved entities + context packet + query trace + token metrics + feedback.
- `SchemaTable` — table → column → FK / inferred relations preview, marks Forge-derived rows.
- `LineageTimeline` — temporal event stream with current/historical states.
- `DecisionCard` — first-class decision entity card.
- `DriftPanel` — five drift category tabs.
- `ForgeStudio` (Roadmap) — 3-pane mapping review.
- `ResolverStudio` (Roadmap) — stage timeline + adjudication queue + identity-graph viewer.
- `CoresPanel` (Roadmap) — snapshots list + Build/Test/Promote/Rollback rail + diff view.
- `MCPConsole` (Preview) — transports table + tool registry + invocation tail.
- `InspectorPanel` — universal right-side details for any selected primitive.
- `EmptyState` — operational empty state with single primary action.

### Buttons

- Primary: orange filled. Reserved for create/start/run.
- Secondary: surface-2 + border.
- Ghost: navigation, table-cell actions.
- Destructive: red outline (confirmation step required).
- Icon-only: lucide; tooltip mandatory.

### Tables

Central to the database feel:

- Sticky header.
- Mono IDs / hashes / timestamps.
- Row hover: `surface-3`.
- Status badges inline.
- Right-aligned counts and durations.
- Column density toggle.
- Empty state inside tbody (no marketing card).
- Row click → inspector. Row keyboard nav with `j/k` and `↑/↓`.

### Forms

- shadcn `Form`, `Input`, `Select`, `Tabs`, `RadioGroup`, `Switch`, `Textarea`.
- Source setup wizard uses a right-side live validation pane (latency, auth, schema discovered, permissions).
- Sensitive fields: masked, with explicit security copy and "rotate" affordance.
- Connection test result is structured (latency, auth status, schema discovered, permission map), not a single line.

### Empty States

Always operational:

- State the missing thing.
- Offer one primary action.
- Show the next database object that will be created.
- Avoid feature explanations.

> "No sources connected. Add Postgres, Gmail, or Slack to start building this context database."

## Page-Specific Notes

### Login

- Grid background most visible here.
- Centered ContextD wordmark.
- Compact login panel.
- "Local development mode" badge when auth is disabled.

### Dashboard

- "Context Databases" list.
- Health strip: sources, entities, edges, pending events, drift.
- Recent sync runs.
- Recent queries with token / latency metrics.
- No marketing hero.

### Workbench

- Persistent header + vertical tab rail + main pane + right inspector.
- Tabs labeled with their implementation status badge where not V1.

### Graph

- Full-bleed canvas. Tool rail. Filter chips. Bottom command bar. Right inspector.

### Query Console

- Scope selector + mentions + answer + entities + sources + context packet + trace + token metrics.

### Forge / Resolver / Cores (Roadmap)

- 3-pane Studio (Forge), Stage timeline (Resolver), Build/Test/Promote/Rollback rail (Cores).
- Sample fixture mode behind a "Roadmap" badge.

## Motion

Easing curves (named tokens used by the HTML mockup):

- `--ease-out` — `cubic-bezier(0.16, 1, 0.3, 1)` (default for hover / focus).
- `--ease-snappy` — `cubic-bezier(0.4, 0, 0.2, 1)` (default for nav-item, tabs, chips, buttons).
- `--ease-spring` — `cubic-bezier(0.34, 1.56, 0.64, 1)` (used sparingly for drawer / sheet entrance).

Durations:

- 120–180 ms hover / focus.
- 180–240 ms drawer / sheet.
- Graph selection may animate edges briefly.
- Status pulses for `running` indexing and the `Operational` API health pill — 1 s cycle, low-opacity delta.
- No ambient decorative motion.

## Accessibility

- WCAG AA minimum on both themes.
- Icon-only buttons: tooltip + aria-label.
- Dialogs: visible or visually-hidden `DialogTitle`.
- Focus ring: orange, 2px, offset 2px.
- Tables: keyboard row navigation; column header sort accessible.
- Theme respects `prefers-color-scheme` and `prefers-reduced-motion`.

## V1 Implementation Strategy

1. Replace global theme tokens (light + dark) and remove legacy color variables. Lock sidebar `244 / 56`, topbar `52`, footer `28`, sub-header `52`.
2. Build AppShell (sidebar with `Workspace / Operations / Settings` groups), PageHeader, DatabaseSubHeader, KPIStrip, StatusBadge / StatusPill, DatabaseTable primitives.
3. Redesign Login + Dashboard (KPIStrip · DatabaseTable · Recent activity · Saved queries rail).
4. Redesign Workbench shell with the 3-group vertical tab rail (`Operate / Inspect / Build`) + right inspector slot at 320 / 360 px.
5. Redesign Sources catalog + Source Setup Wizard (5-step + sticky right preview pane: SourceIdentity / TargetDatabase / ForgeCallout / SyncEstimate).
6. Build Workbench Overview (KPIStrip · EntitiesByTypePanel · SyncPipelinePanel · ActiveSourcePanel · Inspector).
7. Build Workbench Schema (Preview): SchemaObjectTree · SchemaColumnTable · ForeignKeyGraph · ColumnInspector.
8. Build Workbench Graph + EntityInspector (SupersessionChain · TopEdges · Provenance · Cohorts).
9. Build Workbench QueryConsole + always-on QueryTracePanel (7-step pipeline · LatencyBreakdown · TokenBudget · CallerCard).
10. Add honest Preview surfaces for Temporal, Lineage, Decisions, Drift.
11. Add Roadmap UI shells for Forge / Resolver / Cores behind a feature flag, in the `Build` group of the tab rail.
12. Polish Admin + add MCP Preview console.
13. Audit responsive, keyboard, accessibility across both themes.

The sequenced delivery plan with file-level mapping lives in `contextd-ui-transition-plan.md`.
