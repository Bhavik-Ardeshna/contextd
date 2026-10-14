# ContextD Production Cleanup Plan

Status: planning only
Created: 2026-04-25
Scope: stabilize the current codebase, make every public and internal surface ContextD-only, remove stale code, and prepare for the ContextD vision without adding new product functionality yet.

## 1. Executive Summary

The current repo is not production-grade ContextD yet. It contains a large inherited ingestion/search backend, a React application, graph chat, agent orchestration, sync workers, graph storage, vector/search experiments, and many early ContextD-like ideas. The first job is to make the foundation clean and stable.

The cleanup phase must not become a feature sprint. The immediate goal is:

1. Freeze current behavior and create a reliable baseline.
2. Make ContextD the only product, package, runtime, docs, UI, and API identity.
3. Remove stale code, misleading disabled paths, duplicate abstractions, and legacy docs/examples.
4. Harden configuration, auth, logging, secrets, sync, graph operations, and LLM usage.
5. Add tests around existing behavior before heavy refactors.
6. Split oversized modules into typed, bounded services.
7. Only after stability, begin ContextD primitives such as bitemporal facts, feedback weights, decision lineage, ontology routing, Context Cores, and MCP.

## 2. Hard Rule For This Plan

ContextD is the only name allowed in this plan and in the target codebase.

The cleanup work may need temporary compatibility shims in code during migration, but those shims must be private, time-boxed, documented in migration tickets, and removed as soon as runtime paths no longer depend on them. No public UI, API response, env var, Docker object, docs page, example, SDK snippet, or generated OpenAPI text should expose any non-ContextD identity.

## 3. Non-Goals

Do not implement new ContextD features during this phase.

Specifically, do not add:

- ArcadeDB migration.
- Context Cores.
- MCP server.
- New connectors.
- New billing features.
- New chat features.
- New agent behaviors.
- New retrieval algorithms.
- New ontology engine.
- New hosted-platform assumptions.

The phase is about production cleanup and correctness.

## 4. Vision Anchors

The target product described in `docs/contextD.md` is a context graph database for AI agents.

ContextD should eventually:

- Ingest enterprise data from systems like Gmail, CRM, tickets, Slack, docs, and databases.
- Transform raw records into structured entities, relationships, facts, episodes, sagas, communities, and decisions.
- Track time with bitemporal semantics: real-world validity and system knowledge time.
- Preserve provenance back to the source episode for every claim.
- Retrieve context with hybrid search: keyword, vector, graph traversal, and reranking.
- Assemble token-efficient context windows for agents.
- Learn from feedback by updating graph weights.
- Support versioned graph snapshots through Context Cores.

The target examples in `docs/example.md` imply three core product modes:

- Data 360: entity profile, live relationships, timeline, and context assembly.
- Audience activation and cohort analysis.
- Decision auditing with temporal knowledge and provenance.

The cleanup phase should keep those outcomes in mind, but it should not build them prematurely.

## 5. Current Codebase Reality

The current repo contains:

- Backend FastAPI app.
- Backend tests.
- Frontend React/Vite app.
- Docker Compose infrastructure.
- Examples and notebooks.
- Native ContextD ADK package under `backend/contextd-adk`.

Current size and risk indicators:

- About 570 backend Python files.
- About 162,606 backend lines.
- About 62,474 frontend lines.
- 102 backend Python files over 500 lines.
- 35 frontend files over 500 lines.
- Only 7 backend test files found under the current backend test folder.
- No frontend test/spec files found outside dependencies.
- Existing uncommitted work is present in graph chat, agent orchestration, frontend chat, graph chat API, and dashboard files.

Important production concerns:

- The package namespace, runtime identifiers, docs, examples, env defaults, headers, storage keys, and container names are not yet ContextD-only.
- Some vector/search destination code is disabled while other code still assumes a vector destination exists.
- Graph nodes do not yet have the full bitemporal and feedback fields from the ContextD vision.
- Graph edges have partial temporal fields but not the full transaction-time model.
- Several security-sensitive defaults are dev-friendly and must fail closed in non-local environments.
- LLM usage is spread across multiple backend modules with hardcoded model names.
- Frontend auth, OAuth, dashboard, search, and API client code is too concentrated and too chatty in logs.

## 6. Cleanup Definition Of Done

The cleanup phase is done when:

- ContextD is the only product identity in public and internal surfaces.
- Fresh local setup starts with ContextD names.
- Existing sync, search, graph chat, auth, and dashboard behavior still works.
- No live production path depends on commented-out or misleading code.
- Dev-only settings are visibly dev-only and fail closed outside local/test.
- Backend package boundaries are understandable.
- Frontend route/page/component boundaries are understandable.
- Tests cover core existing behavior before future ContextD feature work begins.
- Build, lint, and tests pass locally and in CI.
- The app starts locally from a fresh checkout.
- The worker starts locally and can process a simple sync.
- Graph chat returns a typed response for a fixture collection.
- Production environment validation blocks unsafe defaults.
- A repository scan confirms no forbidden legacy product identity remains outside approved temporary private shims.

## 7. Workstream A: Baseline Freeze And Inventory

Goal: create a known-good baseline before any refactor.

Tasks:

- Record current git status and protect existing modified/untracked work.
- Run backend lint, type checks, tests, and build/start commands. Record failures without fixing them.
- Run frontend lint, type checks, build, and local start commands. Record failures without fixing them.
- Record current Docker Compose startup behavior.
- Record current worker startup behavior.
- Record a simple sync attempt and outcome.
- Record a simple graph chat/query attempt and outcome.
- Generate a ContextD naming inventory with categories:
  - package/import references;
  - runtime config/env references;
  - database names and queue names;
  - Docker container/image/volume names;
  - cloud/infra object names;
  - frontend visible strings;
  - frontend storage keys;
  - HTTP headers;
  - SDK snippets and examples;
  - docs and notebooks;
  - comments/docstrings/internal class names.
- Generate stale/dead-code inventory:
  - disabled destination code;
  - legacy adapters;
  - deprecated frontend props/types;
  - unused pages/components;
  - generated files that should not be in source control;
  - nested project boundaries;
  - dead Docker and deployment assets;
  - unused dependencies.
- Mark every item as one of:
  - remove now;
  - rename now;
  - keep with temporary private compatibility shim;
  - defer with owner, reason, and removal date.

Acceptance criteria:

- One baseline report exists.
- One naming inventory exists.
- One stale-code inventory exists.
- No implementation cleanup begins before baseline failures are known.

## 8. Workstream B: ContextD Naming And Namespace Migration

Goal: make ContextD the only identity while avoiding a dangerous big-bang rename.

### 8.1 Naming Standard

Use these names consistently:

- Product: ContextD.
- Backend package target: `contextd`.
- CLI prefix target: `contextd`.
- Docker project target: `contextd`.
- Default database target: `contextd`.
- Default queue target: `contextd-sync-queue`.
- Default graph/index target: `contextd_graph`.
- Public API domain placeholder: `api.contextd.local` until real domains are chosen.
- Public app domain placeholder: `app.contextd.local` until real domains are chosen.
- Public docs domain placeholder: `docs.contextd.local` until real domains are chosen.

Do not use a second public product name during cleanup. ContextD should be the UI, docs, API, and code identity.

### 8.2 Backend Namespace Migration

Safe sequence:

1. Rename backend package metadata.
2. Introduce `contextd` as the target package namespace.
3. Keep temporary private import aliases only if required to avoid breaking Alembic, workers, or runtime scripts.
4. Move modules by bounded context, not by raw file tree.
5. Update imports in small vertical slices.
6. Remove private aliases after tests, workers, migrations, and scripts no longer need them.

Required backend rename areas:

- Package metadata.
- Backend root package.
- FastAPI title and root docs response.
- Exception names.
- field helper names.
- system metadata names.
- HTTP client wrapper names.
- platform sync path.
- Temporal worker module path.
- Alembic import paths.
- test import paths.
- generated OpenAPI names.

Acceptance criteria:

- No backend response, OpenAPI title, error message, log prefix, module docstring, or root page exposes a non-ContextD identity.
- Any temporary compatibility shim is private, covered by tests, and has a removal ticket.

### 8.3 Frontend Naming Migration

Required frontend rename areas:

- package name.
- page titles.
- visible labels.
- logos and alt text.
- localStorage keys.
- API headers.
- docs links.
- SDK snippets.
- icon asset names.
- README and setup text.

Important migration notes:

- localStorage key migration should read the previous key once, write the new ContextD key, then remove the previous key after one release.
- API header migration should accept the previous header and new ContextD header for one release, then remove the previous header.
- Any user-visible old copy should be removed immediately.

Acceptance criteria:

- UI source, built assets, browser title, visible text, and API client code present only ContextD identity.
- Old browser storage and header support is temporary and private.

### 8.4 Runtime And Infra Naming Migration

Required rename areas:

- Docker container names.
- Docker image names.
- Docker volume names.
- default database name.
- default database user.
- default Neo4j graph name.
- default Temporal task queue.
- Terraform project names.
- object storage bucket names.
- startup scripts.
- env examples.

Migration must not delete local developer volumes unexpectedly. Provide explicit reset/migration commands when changing local data names.

Acceptance criteria:

- Fresh setup uses ContextD runtime identifiers.
- Existing local setups can migrate or intentionally reset.
- Production infra object rename has a migration plan before any change.

## 9. Workstream C: Stale Code Removal

Goal: make the live behavior obvious.

### 9.1 Search And Indexing Honesty

Current problem:

- Some destination insert/delete paths are disabled.
- Search still assumes a vector-backed destination in places.
- Search now has a single default live path, but the codebase still needs periodic checks to keep it that way.

Tasks:

- Keep the current production search path explicit: Neo4j graph plus Neo4j fulltext.
- Remove unreachable commented blocks from destination handlers.
- Keep ADK memory vectors isolated to Milvus.
- Ensure search factory behavior matches sync/index behavior.

Acceptance criteria:

- Exactly one default search/indexing path exists for fresh development.
- Disabled paths are not registered in the live path.
- Search, sync, and cleanup behavior agree.

### 9.2 Legacy And Compatibility Cleanup

Tasks:

- Inventory `legacy`, `deprecated`, `TODO`, `FIXME`, broad `pass`, broad `except`, and ignored type/lint comments.
- Separate intentional abstract methods from accidental empty implementations.
- Replace silent failure in live paths with typed exceptions or structured logs.
- Remove SDK snippets that cannot run.
- Remove duplicate rules across builders, CRUD, schemas, config metadata, frontend constants, and docs.
- Remove unused dependencies after confirming no live path imports them.
- Remove or quarantine old notebooks/examples that do not represent ContextD.

Acceptance criteria:

- No silent failure exists in auth, sync, graph commit, billing, search, file retrieval, or LLM paths.
- Compatibility code has owner, test coverage, and removal date.

### 9.3 Nested Project Boundary

Current problem:

- A nested agent-runtime project exists inside the backend area and can confuse build/test/search ownership.

Tasks:

- Decide whether it is:
  - vendored dependency;
  - git submodule;
  - local package;
  - code to absorb.
- If kept, isolate it from normal source traversal unless explicitly imported.
- If absorbed, migrate only the used runtime pieces into a ContextD bounded context.
- Exclude nested research/frontend/test artifacts from normal app build unless intentionally used.

Acceptance criteria:

- The main backend has one clear dependency relationship to the nested runtime.
- Search, lint, and test commands do not accidentally sweep unrelated nested artifacts.

## 10. Workstream D: Clean Code Standards

Goal: make the codebase boring, typed, readable, and maintainable.

Rules for cleanup implementation:

- Read files before editing.
- Prefer small vertical slices over sweeping rewrites.
- Keep new files under 500 lines.
- Split existing oversized files when tests protect the behavior.
- Keep endpoint modules thin.
- Put business rules in services.
- Put persistence in repositories/CRUD modules.
- Put external calls behind typed gateways.
- Use Pydantic or typed interfaces for all public boundaries.
- Validate input at API, connector, file, and auth boundaries.
- Avoid stringly typed cross-module contracts.
- Avoid broad `dict[str, Any]` except at true untrusted boundaries.
- Use explicit errors instead of boolean/None failure signals.
- Remove duplicate logic instead of wrapping it.
- Do not add abstractions unless they remove real duplication or isolate a real dependency.
- Keep comments only where they explain non-obvious decisions.
- No secrets in code, examples, logs, tests, or docs.

Definition of clean code for ContextD:

- A new engineer can find the live sync path, graph path, search path, auth path, and LLM path within 10 minutes.
- Each bounded context has a small public API.
- Tests describe expected behavior more clearly than comments.
- Production behavior is explicit in config and never hidden behind commented code.

## 11. Workstream E: Architecture Boundaries

Goal: align the repo with domain-driven design.

Proposed bounded contexts:

- Identity and tenancy: users, organizations, auth, API keys, roles.
- Connector catalog: sources, auth providers, credentials, config schemas.
- Sync and ingestion: sync jobs, cursors, raw files, Temporal workflows.
- Entity store: normalized entities, entity definitions, counts, source state.
- Context graph: graph events, graph commit, nodes, edges, traversal, merge.
- Search and context assembly: retrieval, ranking, formatting, token budgeting.
- Agent interface: graph chat, agent orchestration, cohort probes.
- Billing and usage: plans, usage limits, billing periods.
- Admin and operations: health, cleanup, diagnostics.

Refactor sequence:

1. Add characterization tests to current modules.
2. Define service boundaries and public interfaces.
3. Extract oversized files into services by behavior.
4. Move modules after tests pass.
5. Remove private compatibility aliases after module moves are complete.

High-priority split targets:

- Admin endpoints.
- Graph chat endpoint.
- Agent orchestration.
- Source connection service.
- Source connection helper service.
- Entity sync pipeline.
- Search factory.
- Frontend dashboard.
- Frontend search response.
- Frontend API client.

Acceptance criteria:

- No new backend file exceeds 500 lines.
- No new frontend file exceeds 500 lines.
- Public service APIs use typed request/response models.
- Endpoints become thin orchestration layers.

## 12. Workstream F: Config, Security, And Environment Hardening

Goal: fail closed in production and reduce accidental data exposure.

Tasks:

- Add environment profile validation for `local`, `test`, `dev`, `stg`, and `prd`.
- Fail startup outside local/test if:
  - auth is disabled;
  - dev auth is enabled;
  - default dev secret is used;
  - state signing secret is missing/weak;
  - encryption key is missing/weak;
  - default database passwords are used;
  - full prompt logging is enabled;
  - wildcard CORS is enabled;
  - analytics keys are missing when analytics is enabled;
  - storage path points to unsafe root or parent directories.
- Move analytics keys to environment config.
- Make analytics opt-in for local/self-host.
- Remove direct analytics SDK exposure on `window`.
- Replace broad CORS defaults with environment-owned domain allowlists.
- Redact OAuth codes, access tokens, refresh tokens, credentials, prompts, and raw records from logs.
- Add path sanitizer review for file retrieval, storage, and raw data handling.
- Add secret scanning to CI.

Acceptance criteria:

- Production startup refuses unsafe defaults.
- Logs do not include OAuth codes, access tokens, credentials, full prompts, raw user data, or large context payloads.
- Security-sensitive config is covered by tests.

## 13. Workstream G: Sync, Graph, And Ingestion Stabilization

Goal: make existing ingestion and graph behavior reliable before adding ContextD primitives.

Tasks:

- Decide whether graph events are the default live path or experimental.
- Decide whether two-phase graph commit is production-ready or should stay off.
- Ensure sync jobs are idempotent:
  - rerunning a sync does not duplicate graph nodes;
  - deletion/orphan cleanup is deterministic;
  - failed commits are retryable;
  - cursor updates happen only after durable persistence.
- Add tests for graph event commit status:
  - pending;
  - committed;
  - failed;
  - skipped.
- Add tests for entity identity stability across sync runs.
- Add tests for connector cursor behavior.
- Add structured error categories for connector failures.
- Emit operator-readable progress and failure summaries per sync job.
- Define recovery steps for stuck jobs.

Acceptance criteria:

- A failed sync can be retried without corrupting Postgres or Neo4j state.
- The operator can answer what failed, why, and what data was affected.

## 14. Workstream H: Search And Context Assembly Stabilization

Goal: make current retrieval behavior predictable and measurable.

Tasks:

- Define one canonical search request/response contract.
- Remove or isolate legacy search schemas.
- Add tests for filters, temporal options, graph traversal depth, empty results, and partial failures.
- Add latency, result count, and token estimate metrics.
- Add deterministic context assembly tests with golden fixtures.
- Centralize token counting and prompt-size limits.
- Ensure graph chat does not silently fall back to a different strategy without response metadata.
- Keep Decision Trace as an execution trace of what ran, not as full decision-lineage feature yet.

Acceptance criteria:

- Given a fixture collection, the same query returns stable context metadata.
- The UI can show execution path without guessing.
- Empty, partial, and failed retrieval all have typed responses.

## 15. Workstream I: LLM Gateway Cleanup

Goal: centralize existing LLM usage without adding new capabilities.

Tasks:

- Create one backend LLM gateway interface.
- Move model names to config.
- Add per-use-case model policy:
  - extraction;
  - graph enrichment;
  - agent orchestration;
  - answer synthesis;
  - property synthesis;
  - embeddings.
- Add timeout and retry policy per use case.
- Add structured-output validation and error reporting.
- Add prompt redaction before logging.
- Add cost counters by organization, collection, sync job, and request id.
- Add tests for timeout, provider error, schema validation error, and redaction.

Acceptance criteria:

- No direct provider client construction exists outside the gateway except tests.
- No hardcoded model names remain in production code.
- LLM failures are typed and observable.

## 16. Workstream J: Frontend Cleanup

Goal: reduce UI fragility without changing product behavior.

Tasks:

- Split the dashboard into:
  - route container;
  - chat input/composer;
  - message list;
  - decision trace panel;
  - query trace list;
  - graph node details;
  - collection selector;
  - streaming state hook.
- Split API client concerns:
  - token provider;
  - request queue;
  - organization header;
  - retry/refresh behavior;
  - analytics session header;
  - endpoint clients.
- Fix auth config property mismatch.
- Remove credential/OAuth/debug logging.
- Add a frontend test runner if one is not present.
- Add tests for auth config, API client behavior, route guarding, and Decision Trace rendering.
- Replace stale SDK snippets with ContextD snippets only after backend API naming is stable.

Acceptance criteria:

- No frontend source file newly exceeds 500 lines.
- Dashboard behavior remains unchanged but is testable by component/hook.
- No sensitive auth or OAuth state is logged to the browser console.

## 17. Workstream K: API Contract And Validation

Goal: make public APIs typed, validated, and versionable.

Tasks:

- Define which endpoints are public, internal, admin-only, and dev-only.
- Remove dev endpoints from production OpenAPI.
- Require typed request/response models for all public endpoints.
- Add pagination, limits, and upper bounds to list/search endpoints.
- Standardize error response shape.
- Standardize organization scoping and API key auth behavior.
- Add request body size tests and timeout tests.
- Ensure all path parameters are validated.
- Add API versioning policy before public contract changes.

Acceptance criteria:

- OpenAPI describes only supported public/internal APIs.
- Public endpoints have validation tests.
- No endpoint trusts client-provided organization ids without access checks.

## 18. Workstream L: Observability And Operations

Goal: make production support possible.

Tasks:

- Standardize request ids across frontend, backend, worker, sync job, graph commit, and LLM calls.
- Add structured logs with consistent fields:
  - request id;
  - organization id;
  - collection id;
  - sync id;
  - sync job id;
  - connector short name;
  - graph commit id;
  - LLM request id;
  - latency.
- Add Prometheus metrics for:
  - API latency;
  - API error rates;
  - sync job durations;
  - connector error counts;
  - graph commit failures;
  - LLM cost and failures;
  - search latency;
  - context token estimates.
- Add health checks for:
  - database connectivity;
  - graph connectivity;
  - cache connectivity;
  - worker connectivity;
  - search/indexing readiness.
- Create operator runbooks only after behavior is stable.

Acceptance criteria:

- A production error can be traced from UI request to backend request to sync/graph/LLM operation.
- Operators can identify failing connectors, stuck sync jobs, failing graph commits, and degraded search/index services.

## 19. Workstream M: Tests And Quality Gates

Goal: create confidence before future feature work.

Backend test priorities:

- Settings validation and production fail-closed behavior.
- Auth context, API key organization scoping, and dev auth restrictions.
- Source connection create/update/delete.
- Sync job lifecycle and cursor behavior.
- Graph event generation and commit status.
- Entity identity stability and semantic merge guard behavior.
- Search factory behavior and retrieval error handling.
- Graph chat request/response metadata.
- Billing guard rails if billing remains in scope.
- LLM gateway timeout/error/redaction behavior.

Frontend test priorities:

- Auth config.
- API client request headers and retry behavior.
- Organization switching.
- Route guards.
- Dashboard chat state.
- Decision Trace panel rendering.
- Error states.
- Sensitive-log absence for OAuth/auth paths.

CI gates:

- Backend lint.
- Backend type check or staged typing target.
- Backend tests.
- Frontend lint.
- Frontend type check.
- Frontend build.
- Secret scan.
- Forbidden identity scan after migration reaches the final phase.
- Max-file-size report with exceptions.

Acceptance criteria:

- New feature work cannot merge unless cleanup CI passes.
- Refactors have tests before movement.
- Quality gates are automated, not tribal knowledge.

## 20. Future ContextD Primitives After Cleanup

Only after cleanup reaches the acceptance criteria, start implementing the vision in this order:

1. Production graph schema contract:
   - Entity;
   - Relationship;
   - Fact;
   - Episode;
   - Decision;
   - Saga;
   - Community.
2. Bitemporal fields:
   - `valid_at`;
   - `invalid_at`;
   - `created_at`;
   - `expired_at`.
3. Provenance:
   - source episode;
   - extraction method;
   - extractor version;
   - source connector;
   - sync job id.
4. Feedback weights:
   - neutral defaults;
   - explicit feedback API;
   - EMA updates;
   - audit log of weight changes.
5. Context assembly:
   - stable token budget;
   - deterministic priority order;
   - lineage inclusion.
6. Decision lineage:
   - first-class decision nodes;
   - policy links;
   - exception tracking.
7. Hybrid retrieval:
   - keyword;
   - vector;
   - graph traversal;
   - reranking.
8. Entity resolution:
   - exact;
   - entropy gate;
   - MinHash/LSH;
   - cosine;
   - LLM judge.
9. Saga tracking:
   - episode chains;
   - incremental summaries.
10. Context Cores and MCP.

Do not begin these until the current product can build, test, and run cleanly.

## 21. Suggested Execution Phases

### Phase 0: Baseline And Decisions

Duration: 2-4 days.

Deliverables:

- Current failure report for build/lint/test.
- ContextD naming inventory.
- Stale-code inventory.
- Storage decision note for cleanup phase.
- Public naming decision confirming ContextD-only.
- Dependency ownership decision for the nested agent-runtime project.

Exit criteria:

- Team agrees what stays, what goes, what is renamed, and what is deferred.

### Phase 1: Production Safety

Duration: 1-2 weeks.

Deliverables:

- Production settings fail closed.
- Prompt logging disabled by default.
- Dev secrets blocked outside local/test.
- Auth config bug fixed.
- Sensitive frontend logs removed.
- Basic settings/auth/API client tests.

Exit criteria:

- Product can no longer accidentally start in production with dev security posture.

### Phase 2: Live Path Stabilization

Duration: 2-3 weeks.

Deliverables:

- Search/indexing live path chosen and made explicit.
- Disabled destination code removed or re-enabled with tests.
- Graph event path tested.
- Sync retry/idempotency tests.
- LLM usage routed through one gateway.

Exit criteria:

- Existing sync/search/chat behavior is deterministic enough to refactor.

### Phase 3: ContextD Naming Migration

Duration: 2-4 weeks.

Deliverables:

- Backend package metadata renamed.
- Runtime names migrated.
- Frontend visible strings and keys migrated.
- Docker/env names migrated.
- Docs/examples updated.
- Temporary private compatibility aliases added only where needed.
- Forbidden identity scan enforced in CI.

Exit criteria:

- ContextD is the only public and internal identity, excluding approved temporary private shims.

### Phase 4: Modularization

Duration: 3-5 weeks.

Deliverables:

- Oversized backend endpoints split.
- Oversized frontend pages split.
- Service boundaries defined by bounded context.
- Tests added around each extracted unit.
- File-size exception list reduced and owned.

Exit criteria:

- Core files are maintainable, testable, and under size limits where practical.

### Phase 5: ContextD Primitive Implementation Planning

Duration: 1 week.

Deliverables:

- Updated roadmap for bitemporal facts, feedback, decisions, sagas, and context assembly.
- Schema migration plan.
- API contract plan.
- Test fixture plan.
- Migration rollback plan.

Exit criteria:

- Feature implementation can begin on a stable foundation.

## 22. Risk Register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Big-bang namespace rename breaks runtime | Imports, migrations, workers, tests, Docker, and scripts all depend on current paths | Use temporary private shims and vertical migrations |
| Storage confusion continues | Search can assume a vector index while sync does not write one | Pick one live path and enforce it with tests |
| Dev settings leak to production | Auth disabled, prompt logs, wildcard CORS, and default passwords create real exposure | Environment fail-closed checks |
| Large files hide regressions | Dashboard, graph chat, and orchestration behavior are concentrated | Add characterization tests before splitting |
| Existing dirty work gets overwritten | Several files already have uncommitted edits | Read before edit and isolate cleanup changes |
| Vision work starts too early | New features on unstable code increase drift | Explicit no-feature gate until cleanup passes |
| Runtime rename misses infrastructure | Old queue, database, or container names cause confusing operations | Inventory runtime identifiers before migration |
| LLM costs remain invisible | Extraction and chat can burn cost without attribution | Central gateway with organization/request/sync cost metrics |
| Tests remain too shallow | Refactor confidence stays low | Make quality gates blocking before feature work |

## 23. Implementation Readiness And Safety Gates

This plan is ready to implement as a staged production-hardening program. It is not ready to implement as one large refactor, one large rename, or one large cleanup pull request.

The code should continue working after every implementation slice. If any slice breaks startup, build, tests, sync, search, graph chat, or local developer setup, stop and either fix that slice immediately or back it out before moving to the next slice.

### Readiness Decision

Ready now:

- Phase 0 baseline and inventory.
- Characterization tests around current behavior.
- Naming and stale-code inventories.
- Security/config audit with findings only.
- Storage-path decision document.

Not ready yet:

- Large runtime namespace migration.
- Package path migration.
- Infrastructure object migration.
- Broad module extraction.
- ContextD primitive implementation.
- Production security fail-closed changes without environment-specific tests.

Phase 0 is mandatory. It is the safety checkpoint that tells the team what currently works, what already fails, and which failures are acceptable baseline debt versus new regressions.

### Required Gates For Every Implementation Slice

Every slice must include:

- Exact scope and files/modules affected.
- Expected compatibility impact.
- Tests added or updated.
- Validation commands run and results recorded.
- Rollback note.
- Confirmation that no new product functionality was added.
- Confirmation that no forbidden non-ContextD public identity was introduced.

Minimum validation after every slice:

- Backend lint/type/test command, or documented reason it is not applicable.
- Frontend lint/type/build command, or documented reason it is not applicable.
- App startup check when backend, frontend, config, Docker, auth, or routing changes.
- Worker startup check when sync, queues, jobs, storage, or config changes.
- Simple fixture sync when ingestion, entity processing, storage, search, or graph code changes.
- Simple fixture query or graph chat check when search, graph, LLM gateway, context assembly, or API response contracts change.
- Forbidden identity scan when naming, docs, API metadata, env vars, Docker, frontend text, package metadata, or examples change.

### Naming Migration Safety

ContextD naming should move from least risky to most risky:

1. Public docs and visible UI text.
2. API metadata, generated docs, and examples.
3. Frontend keys, headers, and client constants with compatibility fallbacks where needed.
4. Environment variables and Docker names with migration notes.
5. Package metadata and runtime service names.
6. Backend import/package paths only after tests and temporary private shims are in place.

Do not rename package/runtime paths before compatibility shims and tests exist. A clean name is not useful if the application no longer imports, starts, or runs migrations.

### Production Hardening Safety

Security hardening must fail closed in production-like environments while keeping local and test workflows usable.

For every fail-closed change:

- Define local, test, staging, and production behavior.
- Add tests for unsafe production config.
- Add tests for valid local/test config.
- Ensure startup errors are explicit and actionable.
- Avoid changing unrelated behavior in the same slice.

### Backout Strategy

Implementation should use small branches or small pull requests grouped by workstream. Do not mix security hardening, naming migration, package movement, storage behavior, and frontend restructuring in one change.

Back out the current slice if:

- A validation gate newly fails.
- Startup becomes ambiguous or environment-dependent in an undocumented way.
- A public API contract changes without an explicit compatibility decision.
- A runtime rename cannot be made compatible.
- A stale-code removal deletes a path that is still exercised by tests, startup, sync, search, or graph chat.

### Answer To The Core Question

After this production hardening, the code should work better than it does now only if the gates above are followed. The plan does not assume correctness by intention. It requires repeated proof through baseline capture, characterization tests, incremental changes, and smoke checks.

The correct expectation is:

- Ready to start Phase 0 now.
- Safe to implement Phase 1 only after Phase 0 results are documented.
- Safe to continue through later phases only while every slice preserves working behavior.
- Not safe to skip directly to broad cleanup, broad rename, or new ContextD features.

## 24. Immediate Next Action

Do not start implementation yet.

The next engineering action should be a baseline pass:

1. Run current build/lint/test commands.
2. Record failures without fixing them.
3. Produce the ContextD naming inventory.
4. Produce the stale-code inventory.
5. Confirm storage, package, and runtime naming decisions.

Only then should code changes begin.
