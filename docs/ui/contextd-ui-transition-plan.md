# ContextD UI Transition Plan

This is the phased migration from the current app to the database-console flow in
`contextd-screens-final.html`, `contextd-theme-plan.md`, `contextd-ui-components.md`,
and `contextd-ui-flow-plan.md`.

## Current System Map

### Frontend

- React/Vite app with `DashboardLayout` wrapping protected routes behind `AuthGuard`.
- API calls go through `frontend/src/lib/api.ts`, which injects auth, organization context,
  and PostHog session headers.
- Main data stores are Zustand:
  - `collections` for collection/database list and source connections.
  - `sources` for connector catalog and connector detail schemas.
  - `organizations` for current org, role, billing state, and feature flags.
  - `chatStore` for local query/chat history.
- Current protected surfaces:
  - `/` was the graph-chat dashboard.
  - `/sources` contains both collection cards and connector catalog tabs.
  - `/collections/:readable_id` is the current collection detail page.
  - `/graph` is the organization graph explorer.
  - `/chat` and `/chat/:chatId` are the full query/chat experience.
  - `/cohorts`, `/auth-providers`, `/organization/settings`, `/admin`, billing routes.

### Backend

- FastAPI app exposes route prefixes directly, not under `/v1`.
- Existing backend nouns remain `collections` in APIs and database models.
- Core live API surfaces:
  - `/collections` list/create/count/update/delete and `/collections/:id/refresh_all`.
  - `/source-connections` create/list/detail/update/delete/run/jobs/cancel.
  - `/sources` connector catalog and detailed config/auth schemas.
  - `/collections/:id/chat`, `/chat/search`, `/graph/context`, `/graph/traverse`,
    `/trace/neighborhood` for graph-augmented query.
  - `/graph/organizations/:orgId` for graph visualization.
  - `/sync`, `/graph-events`, `/entities`, `/cohorts`, `/admin`, `/usage`, `/billing`.

## Migration Principle

The UI vocabulary moves from **collection** to **context database** first. Backend routes and
storage stay as-is until the frontend has stable database-facing routes and enough coverage to
add compatibility endpoints safely.

Every phase must leave existing live features reachable and wired:

- Source creation, OAuth callback, direct auth, and sync runs continue to use current endpoints.
- Existing `/collections/:readable_id` links keep working while `/databases/:readable_id` is added.
- Query/chat stays backed by the existing graph-chat endpoints.
- Preview/Roadmap surfaces must be clearly labeled and never imply backend support that does not exist.

## Phase 1 — Shell, Theme, Route Aliases

Goal: make the app feel like the target control plane without changing backend contracts.

- Replace the flat/sidebar chrome with the target app shell: sidebar, topbar, command trigger,
  environment badge, API health pill, theme switcher, and footer status strip.
- Add user-facing aliases:
  - `/databases/:readable_id` renders the existing collection detail page.
  - `/query` renders the existing query/chat page.
  - `/mcp` renders the MCP surface.
- Move the root route toward the target database dashboard by rendering the existing
  collections tab as `Context databases`.
- Retheme CSS tokens to the black/orange enterprise palette and default theme to `system`.
- Keep legacy routes `/collections/:readable_id`, `/chat`, and `/semantic-mcp` operational.

Checkpoint:

- `npm run build` in `frontend/` passes.
- Existing collection/source/query/graph routes still render.

Status: implemented as the first safe slice. The new app shell, theme tokens, route aliases,
root database entrypoint, and health/status chrome are live while legacy routes remain available.

## Phase 2 — Dashboard Becomes Database Operations

Goal: replace the old card grid with the target dense dashboard.

- Convert the current collections tab into `DatabaseTable`.
- Show metrics from existing endpoints first:
  - Database count from `/collections/count`.
  - Source counts from `/source-connections?collection=...`.
  - Entity counts from connection stats when available.
  - Last sync status from source connection list items.
- Add empty states that create the next object: a context database or source connection.
- Keep connector catalog in the same page temporarily, but make `/sources?tab=connectors`
  the canonical source catalog entrypoint.

Backend follow-up only if current responses are too thin:

- Add a read-only dashboard summary endpoint returning per-database sources, entity counts,
  edge counts, pending syncs, drift count, and last sync.

Checkpoint:

- Creating a database still uses existing collection creation flow.
- Opening a database works through both `/databases/:id` and `/collections/:id`.

Status: started. The root view now uses a dense database operations table and metric strip backed
by the existing collections and source connection stores. The connector catalog is now the
target-style `Source catalog` surface on `/sources?tab=connectors`, with search, filter chips,
connector health metadata, and a setup preview pane while preserving the existing connect action.

## Phase 3 — Database Workbench Shell

Goal: wrap the existing collection detail page in the target workbench structure.

- Introduce `WorkbenchShell` for `/databases/:readable_id/*`.
- Start with live tabs:
  - Overview: reuse current collection/source connection state.
  - Sources: reuse current source connection table/details.
  - Entities: reuse `EntityStateList`.
  - Graph: reuse existing graph components where scoped data exists.
  - Query: reuse graph-chat query console scoped to the database.
- Add honest Preview tabs:
  - Schema, Temporal, Lineage, Decisions, Drift.
- Add Roadmap tabs behind feature flags:
  - Forge, Resolver, Cores.

Backend follow-up:

- Add read-only schema/introspection endpoint or surface existing connector introspection artifacts.
- Add query trace metadata fields if the current graph-chat response does not expose enough timing.

Checkpoint:

- Existing `CollectionDetailView` actions still work: rename, delete, add source, run sync,
  refresh all, inspect source jobs.

## Phase 4 — Source Setup Wizard

Goal: evolve creation from modal/panel flow into the five-step source setup wizard.

- Keep `CollectionCreationModal` and side panel internals while replacing screen composition:
  Auth -> Test -> Discover -> Scope -> Schedule.
- For V1, wire Auth and Schedule to existing `source-connections` create/run behavior.
- For Test and Discover, first show available config/auth validation; then add backend support for
  structured source connection test and schema discovery.
- Add right-side preview pane with source identity, target database, sync estimate, and Forge callout.

Backend follow-up:

- Add `POST /source-connections/test` for latency/auth/permission checks.
- Add `POST /source-connections/discover` for schema/object preview before saving.

Checkpoint:

- OAuth redirect and direct-auth flows keep their current success/error behavior.

Status: started. The connector-first modal entry now uses target database language, selected
connector context, five-step setup framing, and the updated topology preview while still creating
the backing object through the existing `/collections` endpoint before source configuration.

## Phase 5 — Query Console And Graph Workbench

Goal: make query and graph stop feeling like generic chat/canvas and become database tools.

- Split query into main console plus always-visible trace panel.
- Render retrieved entities, sources used, context packet, token budget, and feedback panel from
  current graph-chat response where possible.
- Keep existing chat history and `/chat/:id` links until saved queries are introduced.
- Reframe `/graph` as cross-database graph explorer; workbench graph is database-scoped.

Backend follow-up:

- Add explicit context-packet JSON and timing/trace fields to graph-chat responses.
- Add persisted saved queries after the UI shape is stable.

Checkpoint:

- Existing graph-chat calls, charts, references, and subgraph expansion continue to work.

## Phase 6 — Preview/Roadmap Surfaces

Goal: expose the product roadmap honestly without coupling it to unfinished backend flows.

- Build Preview shells for Schema, Temporal, Lineage, Decisions, Drift, and MCP.
- Build Roadmap placeholders for Forge, Resolver, Cores with feature flags and sample fixture labels.
- No destructive action is enabled without backend support.

Checkpoint:

- Feature flags can hide Roadmap routes without breaking route resolution.

## Verification Strategy

- Frontend: `npm run build`, then focused browser checks for `/`, `/sources?tab=connectors`,
  `/databases/:id`, `/query`, `/graph`, and `/organization/settings`.
- Backend: existing pytest suites around collections, source connections, graph chat, sync, and admin.
- Contract safety: avoid renaming backend models/routes until aliases and UI migration are complete.
