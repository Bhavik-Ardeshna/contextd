# ContextD ArcadeDB Native Implementation Roadmap

> This file replaces the previous fragmented task documents in `tasks/`.
> It is the implementation roadmap for the parts of the ContextD technical
> specification that should live natively inside the ArcadeDB fork at
> `database/arcadedb/`.

## Goal

Build the ContextD substrate inside ArcadeDB so graph, document, key-value,
vector, full-text, time-series, bitemporal history, provenance, audit, RBAC,
snapshots, and wire protocols share one ACID storage engine and one WAL.

The Python/FastAPI application remains responsible for product orchestration:
source connectors, OAuth flows, Temporal worker scheduling, LLM calls, API
presentation, billing, and UI. PostgreSQL remains appropriate for tenant and
application metadata. Redis remains appropriate for hot caches and sessions.
The database-native work below replaces the Neo4j plus Milvus substrate role
and removes cross-store consistency gaps.

## Sources Reviewed

- Product specification: `docs/contextd/contextd-technical-specification.md`
- Existing task files replaced by this roadmap:
  - `tasks/ARCADEDB_IMPLEMENTATION.md`
  - `tasks/COMPLETE_IMPLEMENTATION_GUIDE.md`
  - `tasks/IMPLEMENTATION_PLAN.md`
  - `tasks/MERGED_SPEC.md`
  - `tasks/SUBSTRATE_CHANGES_SPEC.md`
  - `tasks/todo.md`
- ContextD backend areas that currently implement or compensate for database
  substrate behavior:
  - `backend/contextd/platform/sync/`
  - `backend/contextd/platform/graph/`
  - `backend/contextd/search/`
  - `backend/contextd/platform/destinations/`
  - `backend/contextd-adk/src/contextd_adk/memory/`
- ArcadeDB engine, server, HA, protocol, and index modules under
  `database/arcadedb/`.

## Current Architecture Baseline

### ContextD Today

ContextD currently stores and serves graph substrate data through a
multi-database arrangement:

- PostgreSQL stores metadata, entities, sync jobs, source connections, API keys,
  and normalized entity fields.
- Neo4j stores the graph as `GraphNode` nodes and `RELATES_TO` edges, with JSON
  payloads and `ft_*` helper properties for full-text search.
- Neo4j GDS powers traversal strategies such as PPR and PCST in
  `backend/contextd/platform/graph/traversal/`.
- Milvus is used through the ADK memory provider stack for vector memory.
- Redis supports application cache/session/pubsub concerns.
- Temporal schedules and runs sync workflows.

The target is not to collapse every dependency. The target is to collapse the
data substrate used for context assembly: graph, vector, full-text, temporal
history, facts, provenance, lineage, audit, and retrieval ranking.

### ArcadeDB Baseline

The ArcadeDB fork already has many necessary primitives:

- Page manager and buffer pool: `engine/src/main/java/com/arcadedb/engine/PageManager.java`
- WAL and transaction manager: `engine/src/main/java/com/arcadedb/engine/TransactionManager.java`
- Transaction context and ordered file locks: `engine/src/main/java/com/arcadedb/database/TransactionContext.java`
- Bucket storage and slot-table page layout: `engine/src/main/java/com/arcadedb/engine/LocalBucket.java`
- Component abstraction: `engine/src/main/java/com/arcadedb/engine/Component.java`
- Schema catalog and dictionary: `engine/src/main/java/com/arcadedb/schema/LocalSchema.java`
- Graph records and adjacency segments: `engine/src/main/java/com/arcadedb/graph/`
- SQL planner/executor: `engine/src/main/java/com/arcadedb/query/sql/`
- OpenCypher parser, planner, optimizer, and executor:
  `engine/src/main/java/com/arcadedb/query/opencypher/`
- LSM indexes: `engine/src/main/java/com/arcadedb/index/lsm/`
- Full-text wrapper: `engine/src/main/java/com/arcadedb/index/fulltext/`
- Vector index using JVector with graph state, PQ files, async rebuilds, and
  filtered search hooks: `engine/src/main/java/com/arcadedb/index/vector/`
- Time-series engine and continuous aggregates:
  `engine/src/main/java/com/arcadedb/engine/timeseries/`
- Server security bitmaps:
  `server/src/main/java/com/arcadedb/server/security/ServerSecurityDatabaseUser.java`
- Raft HA module: `ha-raft/src/main/java/com/arcadedb/server/ha/raft/`
- Wire protocol modules: `postgresw/`, `bolt/`, `redisw/`, `mongodbw/`,
  `grpcw/`, `graphql/`, `gremlin/`, and HTTP in `server/`.

The roadmap below intentionally builds on those primitives instead of creating
a separate ContextD storage engine.

## Database-Native Scope Boundary

### Build Inside ArcadeDB

- ContextD primitive schemas for Entity, Relationship, Fact, Episode, Saga,
  Community, Decision, Policy, and Identity Graph records.
- Bitemporal fields, insert-not-update supersession, query rewriting, indexes,
  vacuum, and temporal compaction.
- Provenance metadata encoded through the database dictionary and indexed by
  source episode.
- Decision lineage as typed vertices and edges with dedicated traversal
  procedures.
- Hash-chained audit log component separate from WAL.
- Storage-layer RBAC, tenant isolation, resource governance, result limits, and
  protocol-independent enforcement.
- Hybrid retrieval primitives: BM25, HNSW/PQ, filtered ANN, graph traversal,
  RRF, feedback-weight multiplication, and feedback EMA update operations.
- Context Core build/test/diff/promote/rollback as content-addressed engine
  snapshots.
- WAL, checkpoint, replication, backup, PITR, encryption, compression,
  off-heap memory accounting, and Prometheus metrics needed for the substrate.
- Wire protocol support that exposes the same engine capabilities over SQL,
  Cypher/Bolt, HTTP, gRPC, Redis, Mongo, and Gremlin paths.

### Keep Outside ArcadeDB

- OAuth and connector credential refresh flows.
- Source-specific API clients and file converters.
- Temporal workflows and worker orchestration.
- LLM extraction, summarization, cross-encoder reranking, ontology prompt
  assembly, and human review UIs.
- Billing, organization management, API-key lifecycle UI, and product admin.
- Context Forge Studio and Resolver Studio user interfaces.

Some Forge and Resolver artifacts belong in ArcadeDB as stored data and indexes:
Forge mappings, resolver profiles, identity edges, resolution audit trails, and
ontology constraints. The ML inference and review loops stay in the backend.

## Validation Baseline

## Implementation Checkpoint: 2026-05-03

The first ArcadeDB-native implementation slice has started in the fork under
`database/arcadedb/`.

Completed:

- Added `ContextDPrimitiveSchema` in
  `engine/src/main/java/com/arcadedb/contextd/schema/`.
- Added `contextd_install_schema()` SQL function in
  `engine/src/main/java/com/arcadedb/function/sql/contextd/` and registered it
  with ArcadeDB's default SQL function factory.
- Added native schema installation for all Phase 1.1 primitive types:
  Entity, Relationship, Fact, Episode, Saga, Community, Decision, Policy,
  Identity, ResolutionEvent, and FeedbackEvent.
- Added persisted ContextD schema metadata using ArcadeDB type custom values:
  primitive category, schema version, bitemporal flag, and provenance-required
  flag.
- Added shared bitemporal and provenance properties to each primitive type.
- Added first LSM exact/provenance indexes for canonical IDs, primitive IDs,
  source episode lookup, fact predicates, decision types, identity lookups, and
  feedback targets.
- Added record-write provenance enforcement through ArcadeDB's existing
  `DocumentValidator` path for types marked with
  `contextd.provenance.required=true`.
- Added bitemporal write enforcement through the same native validation path:
  `created_at` and `valid_at` default when missing, `invalid_at` and
  `expired_at` remain optional, valid-time ranges reject `valid_at >
  invalid_at`, and system-time ranges reject `created_at > expired_at`.
- Fixed SQL/HTTP runtime datetime behavior by defaulting through
  ArcadeDB-compatible datetime objects and comparing `LocalDateTime` values as
  UTC, matching ArcadeDB's own datetime conversion semantics.
- Added shared temporal visibility evaluation in
  `engine/src/main/java/com/arcadedb/contextd/temporal/ContextDTemporalVisibility.java`.
- Added SQL predicates for native ContextD temporal visibility:
  `contextd_is_current()`, `contextd_valid_at(<instant>)`,
  `contextd_system_at(<instant>)`, and
  `contextd_bitemporal_at(<valid-instant>, <system-instant>)`.
- Registered those functions in ArcadeDB's default SQL function factory so they
  work from regular SQL `WHERE` clauses over documents, vertices, and edges.
- Added native insert-not-update supersession in
  `engine/src/main/java/com/arcadedb/contextd/temporal/ContextDTemporalService.java`.
- Added `contextd_supersede(<old-rid>, <replacement-map>, <valid-at> [, <system-at>])`
  in `engine/src/main/java/com/arcadedb/function/sql/contextd/`, registered with
  the SQL function factory. It closes the old bitemporal record and inserts the
  new record in one ArcadeDB transaction, with rollback on replacement
  validation failure. This first supersession path supports document and vertex
  primitives; relationship-edge supersession still needs endpoint-aware
  insertion logic.
- Added ContextD fact temporal composite LSM indexes in
  `ContextDPrimitiveSchema`:
  `(subject_entity_id, predicate, expired_at)`,
  `(subject_entity_id, predicate, valid_at, invalid_at)`,
  `(subject_entity_id, predicate, created_at, expired_at)`, and
  `(object_entity_id, predicate, created_at)`.
- Added `ContextDTemporalIndexTest` to prove the index families are installed,
  the SQL planner selects the current-state and valid-time composite indexes
  for raw temporal predicates, and superseded/current fact versions remain
  visible through indexed bitemporal predicates.
- Added deterministic engine test fixture under
  `engine/src/test/java/com/arcadedb/contextd/` for representative entities,
  relationships, episodes, superseded/current facts, decision, policy,
  identities, resolution event, feedback event, saga, and community records.
- Recorded the fork baseline in `database/arcadedb/docs/contextd/baseline.md`.

Verified:

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDPrimitiveSchemaTest,ContextDProvenanceTest,ContextDFixtureTest,ContextDBitemporalSchemaTest,ContextDTemporalFunctionTest,ContextDSupersessionTest,ContextDTemporalIndexTest
mvn test -pl engine -Dtest=CRUDTest,BasicGraphTest,DocumentValidationTest,SelectIndexExecutionTest,SQLScriptTest,ACIDTransactionTest
mvn test -pl gremlin -Dtest=GremlinTest,SQLFromGremlinTest,GremlinGroovyEngineTest
mvn test -pl server -Dtest=HTTPGraphIT,RemoteDatabaseIT,RemoteSchemaIT,RemoteQueriesIT
mvn install -DskipTests -pl package -am
```

The focused ContextD engine slice passes with 24 tests total after adding
`ContextDTemporalIndexTest`. Existing compatibility suites also pass:

- 86 engine tests covering ACID transactions, CRUD, graph operations, document
  validation, SQL scripts, and index selection.
- 21 Gremlin tests covering the existing Gremlin query integration, with one
  pre-existing skipped test.
- 34 server/remote tests covering HTTP graph, remote query, remote database,
  and remote schema behavior.

The package reactor build passes for the runnable distribution.

Live ArcadeDB E2E validation was run against a rebuilt package server on HTTP
port `2490` with a clean database root:

- Created fresh databases through `/api/v1/server`.
- Installed the native schema through `select contextd_install_schema() as installed`.
- Verified all 11 ContextD primitive types via `schema:types`.
- Inserted facts, entity vertices, relationship edges, and policy records over
  HTTP.
- Confirmed bitemporal defaults produce matching `created_at` and `valid_at`
  values when both are omitted.
- Confirmed provenance dictionary registration for `source_pipeline` and
  `source_task`.
- Confirmed write-time rejection for missing `source_task`, `valid_at >
  invalid_at`, and `created_at > expired_at`.
- Inserted two `ContextDFact` rows that model a superseded budget fact with
  explicit valid-time and system-time intervals using SQL
  `date(..., 'yyyy-MM-dd HH:mm:ss')` values.
- Confirmed `contextd_is_current()` returns only the visible current fact.
- Confirmed `contextd_valid_at('2026-02-01T00:00:00Z')` returns the old fact on
  the valid timeline.
- Confirmed `contextd_system_at('2026-03-01T00:00:00Z')` returns the old fact on
  the system timeline.
- Confirmed `contextd_bitemporal_at(...)` returns the old fact while both
  timelines include it, excludes it after system expiration, and returns the new
  fact after its valid/system start.
- Superseded an old `ContextDFact` through
  `select contextd_supersede(...) as rid`.
- Confirmed old and new fact records both remain queryable, with old
  `invalid_at`/`expired_at` closed and new `invalid_at`/`expired_at` open.
- Confirmed repeated supersession of an already expired old RID is rejected.
- Confirmed invalid replacement provenance is rejected and the original current
  fact remains unexpired after rollback.
- Confirmed `EXPLAIN` uses
  `ContextDFact[subject_entity_id,predicate,expired_at]` for current fact
  lookup.
- Confirmed existing ArcadeDB features still work in the same live database
  after installing ContextD schema and inserting ContextD records:
  REST SQL document query, ordinary index plan, SQL graph traversal,
  OpenCypher, Gremlin, GraphQL, and REST transaction rollback.
- Ran a lightweight REST timing smoke: 40 ordinary indexed reads averaged
  12.023ms/request and 40 ContextD current temporal reads averaged
  11.266ms/request.
- Restarted the packaged ArcadeDB server against the same database root and
  confirmed ordinary document/index state, OpenCypher graph state, ContextD
  bitemporal fact state, and ContextD temporal index selection persisted.

Run these before any database implementation phase and keep the results in the
phase notes.

```bash
cd database/arcadedb
mvn clean install -DskipTests
mvn test -pl engine -Dtest=LocalBucketTest
mvn test -pl postgresw -Dtest=Postgres*Test
mvn test -pl server -Dtest=*Security*Test
```

Smoke the server after packaging:

```bash
cd database/arcadedb
mvn clean install -DskipTests
./package/target/arcadedb-*/bin/server.sh
```

Then verify through at least HTTP and one wire protocol:

```bash
curl -u root:playwithdata http://localhost:2480/api/v1/server
psql "host=localhost port=5432 user=root password=playwithdata dbname=ContextD" -c "select 1"
```

For ContextD integration validation, keep the Python app running against the
existing stack until the ArcadeDB destination is complete:

```bash
make infra
make backend
make worker
make frontend
```

Each phase below has its own narrower validation gate.

## Phase 0: Substrate Bring-Up, Inventory, and Bench Harness

### 0.1 Stabilize The ArcadeDB Fork State

**What to build**

Create an explicit fork baseline for ContextD work: source commit SHA, current
local changes, build status, test status, and module inventory.

**Where**

- Add documentation under `database/arcadedb/docs/contextd/`.
- Do not commit submodule pin changes in the parent repo until the ArcadeDB fork
  has its own commits.
- Track dirty fork files before work starts. Current known dirty files are:
  - `database/arcadedb/postgresw/src/main/java/com/arcadedb/postgres/PostgresNetworkExecutor.java`
  - `database/arcadedb/ARCHITECTURE.md`

**Why**

ArcadeDB is a git submodule and commits belong to the fork. The parent
`contextd-engine` repo should only pin a commit after fork work is reviewed.

**Implementation steps**

- Record `git -C database/arcadedb rev-parse HEAD`.
- Record `git -C database/arcadedb status --short`.
- Run `mvn clean install -DskipTests`.
- Run focused tests for engine, postgresw, vector, full-text, and security.
- Store the baseline in `database/arcadedb/docs/contextd/baseline.md`.

**Validation**

```bash
git -C database/arcadedb status --short
cd database/arcadedb && mvn clean install -DskipTests
cd database/arcadedb && mvn test -pl engine -Dtest="*Vector*Test,*FullText*Test,*Security*Test"
cd database/arcadedb && mvn test -pl postgresw -Dtest="Postgres*Test"
```

### 0.2 Create ContextD Substrate Test Fixtures

**What to build**

Create reusable fixture loaders for a small but representative ContextD graph:
people, companies, episodes, facts, relationships, decisions, feedback events,
and temporal supersessions.

**Where**

- Engine tests: `database/arcadedb/engine/src/test/java/com/arcadedb/contextd/`
- Server/protocol tests: `database/arcadedb/server/src/test/java/com/arcadedb/contextd/`
- E2E fixtures: `database/arcadedb/e2e/src/test/resources/contextd/`

**Why**

Every later phase needs the same data shape. Rebuilding ad hoc fixtures per
test will hide integration defects and make performance comparisons noisy.

**Implementation details**

- Build a `ContextDFixture` Java helper that creates types:
  `Entity`, `Relationship`, `Fact`, `Episode`, `Decision`, `Policy`.
- Include one superseded fact: Acme budget was `$5M`, then became `$7M`.
- Include one decision that cites the new budget fact and a policy.
- Include one ambiguous person identity that resolves to a canonical entity.
- Include vectors with fixed deterministic float arrays, not random vectors.
- Include full-text fields with known terms and one exact phrase.
- Include `feedback_weight` values at `0.5`, `0.8`, and `0.95`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDFixtureTest
```

Expected proof:

- Fixture creates all types and indexes.
- Fixture inserts all primitives in one transaction.
- Fixture can be reopened and queried after close/open.
- RIDs remain stable across reopen.

### 0.3 Build A Repeatable Benchmark Harness

**What to build**

A benchmark harness that reproduces the spec's hot paths at a small scale first:
point lookup, graph traversal, vector search, full-text search, hybrid search,
fact supersession, feedback update, audit append, and protocol query latency.

**Where**

- `database/arcadedb/load-tests/src/main/java/com/arcadedb/contextd/`
- `database/arcadedb/docs/contextd/benchmarks/`

**Why**

The spec contains performance claims. Each substrate feature must have a
before-and-after measurement before it is accepted.

**Implementation details**

- Add one load-test runner per hot path.
- Use deterministic seeds and fixed graph shape so runs are comparable.
- Emit JSON lines with commit SHA, module version, JVM flags, dataset scale,
  p50, p95, p99, throughput, heap, direct memory, and page-cache stats.
- Keep benchmark tests annotated with `@Tag("benchmark")`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl load-tests -Dtest=ContextD*Benchmark -Dgroups=benchmark
```

## Phase 1: ContextD Primitive Model And Schema Metadata

### 1.1 Add ContextD Primitive Type Definitions

**What to build**

Define the database-native storage contract for ContextD primitives:

- `ContextDEntity`
- `ContextDRelationship`
- `ContextDFact`
- `ContextDEpisode`
- `ContextDSaga`
- `ContextDCommunity`
- `ContextDDecision`
- `ContextDPolicy`
- `ContextDIdentity`
- `ContextDResolutionEvent`
- `ContextDFeedbackEvent`

**Where**

- Schema metadata: `engine/src/main/java/com/arcadedb/schema/`
- Optional helper package: `engine/src/main/java/com/arcadedb/contextd/schema/`
- SQL DDL integration:
  `engine/src/main/java/com/arcadedb/query/sql/parser/`
  and `engine/src/main/java/com/arcadedb/query/sql/executor/`
- OpenCypher label/type conventions:
  `engine/src/main/java/com/arcadedb/query/opencypher/`

**Why**

The spec's primitives must not be convention-only JSON documents. They need
schema-level meaning so indexes, temporal rewrites, RBAC, lineage traversals,
snapshots, and protocol output all agree on the same fields.

**Implementation details**

- Add `ContextDTypeDescriptor` as schema extension metadata stored under
  `LocalSchema.extensions`.
- Mark primitive categories with stable enum values:
  `ENTITY`, `RELATIONSHIP`, `FACT`, `EPISODE`, `SAGA`, `COMMUNITY`,
  `DECISION`, `POLICY`, `IDENTITY`, `FEEDBACK_EVENT`.
- Add a builder that creates standard properties for each primitive. Example
  `ContextDFact`:
  - `subject_entity_id`
  - `predicate`
  - `object_value`
  - `object_entity_id`
  - `confidence`
  - `feedback_weight`
  - `valid_at`
  - `invalid_at`
  - `created_at`
  - `expired_at`
  - `source_pipeline`
  - `source_task`
  - `extraction_method`
  - `source_episode_id`
- Do not require a new storage file type for each primitive. Use normal
  vertex, edge, document, full-text, vector, and time-series components.
- Store primitive metadata in schema JSON so it survives restart and Raft
  replication.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDPrimitiveSchemaTest
```

Expected proof:

- Creating a database installs the primitive schema.
- Schema reload preserves primitive descriptors.
- Invalid primitive definitions fail with clear schema errors.
- SQL and Cypher can see the created types.

### 1.2 Implement Provenance As A First-Class Record Contract

**What to build**

Every ContextD record must carry provenance:

- `source_pipeline`
- `source_task`
- `extraction_method`
- `source_episode_id`

Dictionary-encode high-cardinality strings and index `source_episode_id`.

**Where**

- Serializer: `engine/src/main/java/com/arcadedb/serializer/BinarySerializer.java`
- Record types: `engine/src/main/java/com/arcadedb/database/`
- Dictionary: `engine/src/main/java/com/arcadedb/engine/Dictionary.java`
- Schema/property validation: `engine/src/main/java/com/arcadedb/schema/`
- Query projections: `engine/src/main/java/com/arcadedb/query/sql/executor/ResultInternal.java`

**Why**

Provenance is part of ContextD's correctness model. It must be available for
retrieval, audit, deletion, and compliance without application-side joins.

**Implementation details**

- Start with properties rather than changing the low-level record header.
  This gets compatibility and query visibility immediately.
- Add a schema flag `contextd.provenance.required=true`.
- Add validation in the record write path for ContextD primitive types.
- Use the existing dictionary component to store pipeline and task names.
- Add a secondary index on `source_episode_id`.
- Once the behavior is stable, optionally optimize by adding a compact
  provenance header section to ContextD primitive records.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDProvenanceTest
```

Expected proof:

- Writes without required provenance fail for ContextD primitives.
- Writes with provenance can be queried by `source_episode_id`.
- Dictionary IDs are reused for repeated pipeline/task values.
- Existing non-ContextD records are unaffected.

### 1.3 Create A ContextD Arcade Destination Contract For Backend Migration

**What to build**

Define the engine API that the Python backend will eventually call instead of
Neo4j and Milvus.

**Where**

- HTTP handlers: `server/src/main/java/com/arcadedb/server/http/handler/`
- gRPC service: `grpc/` and `grpcw/src/main/java/com/arcadedb/server/grpc/`
- Python integration later:
  `backend/contextd/platform/destinations/arcadedb.py`

**Why**

ArcadeDB can expose the native features through SQL/Cypher, but the backend
needs a stable, efficient bulk-ingest and search interface during migration.

**Implementation details**

- Add HTTP `/contextd/batch` for primitive upserts and deletes.
- Add HTTP `/contextd/search` for hybrid retrieval once Phase 5 exists.
- Add HTTP `/contextd/feedback` for EMA updates once Phase 5 exists.
- Add gRPC equivalents for high-throughput service-to-service use.
- Request payloads should use RIDs or stable external IDs plus type names.
- Return per-record statuses so ingestion can retry only failed records.

**Validation**

```bash
cd database/arcadedb
mvn test -pl server -Dtest=ContextDHttpApiTest
mvn test -pl grpcw -Dtest=ContextDGrpcApiTest
```

## Phase 2: Bitemporal Storage, Supersession, And Temporal Queries

### 2.1 Add Bitemporal Schema Flags And Required Columns

**What to build**

Implement schema-level bitemporal enforcement for Entity, Relationship, Fact,
and Decision rows:

- `valid_at`
- `invalid_at`
- `created_at`
- `expired_at`

**Where**

- Schema model: `engine/src/main/java/com/arcadedb/schema/LocalDocumentType.java`
- Property validation: `engine/src/main/java/com/arcadedb/database/DocumentValidator.java`
- SQL DDL parser/executor:
  `engine/src/main/java/com/arcadedb/query/sql/parser/`
  and `engine/src/main/java/com/arcadedb/query/sql/executor/`
- OpenCypher validation:
  `engine/src/main/java/com/arcadedb/query/opencypher/parser/`

**Why**

Bitemporal behavior cannot be bolted on in application code. The database must
know which types are temporal so it can rewrite queries, pick indexes, vacuum
history, and preserve old facts.

**Implementation details**

- Add a type custom property, for example `contextd.bitemporal=true`.
- Require all four columns on bitemporal types.
- Default `created_at` to transaction timestamp.
- Default `valid_at` to `created_at` unless the caller supplies event time.
- Default `invalid_at` and `expired_at` to null.
- Add validation that `valid_at <= invalid_at` when `invalid_at` is present.
- Add validation that `created_at <= expired_at` when `expired_at` is present.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDBitemporalSchemaTest
```

### 2.2 Implement Insert-Not-Update Supersession

**What to build**

Add engine-level supersession operations that atomically close an old fact and
insert the new fact in one transaction.

**Where**

- New package: `engine/src/main/java/com/arcadedb/contextd/temporal/`
- Transaction integration: `engine/src/main/java/com/arcadedb/database/TransactionContext.java`
- SQL functions/procedures:
  `engine/src/main/java/com/arcadedb/function/sql/contextd/`
- OpenCypher procedure registry:
  `engine/src/main/java/com/arcadedb/query/opencypher/procedures/`

**Why**

The spec requires contradictory facts to coexist. Direct update or delete would
destroy auditability and break historical queries.

**Implementation details**

- Add `ContextDTemporalService.supersede(oldRid, newRecord, validAt)`.
- The method must:
  - Load old record with write intent.
  - Verify `expired_at IS NULL`.
  - Set old `expired_at` to transaction timestamp.
  - Set old `invalid_at` to the new record's `valid_at`.
  - Insert the new record with `created_at` set to transaction timestamp.
  - Commit both record changes and affected indexes atomically.
- Rely on existing page-version OCC to reject double-supersession.
- Surface conflicts as `NeedRetryException` or a specific
  `BitemporalSupersessionConflictException`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDSupersessionTest
```

Expected proof:

- Old and new facts both remain queryable by RID.
- Only one concurrent supersession wins.
- Indexes reflect one current fact and one historical fact.
- Rollback restores both old and new records to pre-transaction state.

### 2.3 Build The Four Temporal Index Families

**What to build**

Create and maintain indexes for the four required temporal access patterns:

- Current state.
- Valid-time history.
- System-time knowledge state.
- Audit state.

**Where**

- Index metadata: `engine/src/main/java/com/arcadedb/schema/IndexMetadata.java`
- Index builder: `engine/src/main/java/com/arcadedb/schema/TypeIndexBuilder.java`
- LSM indexes: `engine/src/main/java/com/arcadedb/index/lsm/`
- Query planner: `engine/src/main/java/com/arcadedb/query/sql/executor/SelectExecutionPlanner.java`
- Cypher optimizer statistics:
  `engine/src/main/java/com/arcadedb/query/opencypher/optimizer/`

**Why**

Bitemporal queries are only useful if current and historical access patterns
remain cheap at large scale.

**Implementation details**

- Add `ContextDTemporalIndexBuilder`.
- For facts, create:
  - `(subject_entity_id, predicate, expired_at)` with partial-current semantics.
  - `(subject_entity_id, predicate, valid_at, invalid_at)`.
  - `(subject_entity_id, predicate, created_at, expired_at)`.
  - `(object_entity_id, predicate, created_at)` where object is an entity RID.
- For relationships, mirror subject/target with edge type.
- For decisions, index `(decision_type, decided_at, expired_at)`,
  `decided_by`, and `applied_policy`.
- Partial-index behavior can initially be represented by including nullable
  `expired_at` in the key and planning `IS NULL` scans, then optimized later.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDTemporalIndexTest
```

Expected proof:

- `EXPLAIN` shows the correct temporal index for current, valid-time,
  system-time, and both-time queries.
- Writes update all four index families.
- Removing or superseding a record leaves historical index entries valid.

### 2.4 Add SQL Temporal Grammar And Logical Rewriter

**What to build**

Support temporal SQL syntax:

```sql
SELECT subject_entity_id, object_value
FROM ContextDFact
WHERE predicate = 'budget'
AS OF SYSTEM TIME '2026-03-01T00:00:00Z'
AS OF VALID TIME '2026-02-15T00:00:00Z'
```

**Where**

- Grammar:
  `engine/src/main/antlr4/com/arcadedb/query/sql/grammar/SQLLexer.g4`
  and `SQLParser.g4`
- Parser AST:
  `engine/src/main/java/com/arcadedb/query/sql/parser/`
- Planner:
  `engine/src/main/java/com/arcadedb/query/sql/executor/SelectExecutionPlanner.java`
- Filter/index matching:
  `engine/src/main/java/com/arcadedb/query/sql/executor/QueryPlanningInfo.java`

**Why**

The spec's bitemporal model needs first-class query syntax. Requiring every
client to write four timestamp predicates by hand creates inconsistent behavior.

**Implementation details**

- Add AST nodes for optional `AS OF SYSTEM TIME` and `AS OF VALID TIME`.
- Rewrite to predicates:
  - `created_at <= systemTime`
  - `expired_at IS NULL OR expired_at > systemTime`
  - `valid_at <= validTime`
  - `invalid_at IS NULL OR invalid_at > validTime`
- If no temporal clauses are present on a bitemporal type, inject current-state
  predicates by default unless the query opts into `ALL TEMPORAL VERSIONS`.
- Update `EXPLAIN` output to show temporal rewrite and selected index.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDTemporalSqlParserTest
mvn test -pl engine -Dtest=ContextDTemporalSqlExecutionTest
```

### 2.5 Add Cypher Temporal Predicates And Procedures

**What to build**

Expose equivalent temporal behavior to Cypher/Bolt clients.

**Where**

- OpenCypher AST/parser:
  `engine/src/main/java/com/arcadedb/query/opencypher/ast/`
  and `parser/`
- OpenCypher planner:
  `engine/src/main/java/com/arcadedb/query/opencypher/planner/`
- Procedures:
  `engine/src/main/java/com/arcadedb/query/opencypher/procedures/`

**Why**

ContextD currently trains prompts and tools around Neo4j Cypher. Migration to
ArcadeDB must preserve temporal graph query capability through Bolt.

**Implementation details**

- Add procedures first:
  - `contextd.temporal.current(label, predicateMap)`
  - `contextd.temporal.asOfValid(label, instant, predicateMap)`
  - `contextd.temporal.asOfSystem(label, instant, predicateMap)`
  - `contextd.temporal.asOfBoth(label, validInstant, systemInstant, predicateMap)`
- Later extend Cypher grammar only if procedure ergonomics are insufficient.
- Ensure procedures route through the same storage-layer RBAC checks.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDTemporalCypherProcedureTest
mvn test -pl bolt -Dtest=ContextDTemporalBoltIT
```

### 2.6 Implement Vacuum And Temporal Compaction

**What to build**

Background workers for:

- MVCC dead-row vacuum.
- Bitemporal retention.
- Cold-history bucket movement.
- Temporal compaction of closed facts.

**Where**

- New package: `engine/src/main/java/com/arcadedb/contextd/temporal/`
- Page/bucket operations: `engine/src/main/java/com/arcadedb/engine/LocalBucket.java`
- Scheduler hooks: `engine/src/main/java/com/arcadedb/schema/LocalSchema.java`
- Server config: `server/src/main/java/com/arcadedb/server/`

**Why**

Insert-not-update doubles writes for supersession. Without compaction and
retention, long-lived graphs will grow without bound.

**Implementation details**

- Track active temporal scans and oldest snapshot.
- Add per-type retention settings:
  - retain current forever.
  - retain history for N days.
  - move expired history to cold bucket after N days.
  - physically delete tombstoned data after legal retention.
- Reuse `PageManager.suspendFlushAndExecute` only for operations that need
  exclusive file control.
- Preserve RIDs for surviving rows during page rewrites where possible.
- If RID changes are unavoidable, write forwarding records and repair indexes.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDTemporalVacuumTest
mvn test -pl engine -Dtest=ContextDTemporalCompactionTest
```

## Phase 3: Decision Lineage, Identity Graph, And Resolver Artifacts

### 3.1 Implement Decision As A Strict Primitive

**What to build**

Decision records with required fields and typed edges:

- `DECIDED_BY`
- `INFORMED_BY`
- `APPLIED_POLICY`
- `AFFECTED`

**Where**

- Schema helpers: `engine/src/main/java/com/arcadedb/contextd/schema/`
- Graph engine: `engine/src/main/java/com/arcadedb/graph/`
- SQL/Cypher procedures:
  `engine/src/main/java/com/arcadedb/function/sql/contextd/`
  and `engine/src/main/java/com/arcadedb/query/opencypher/procedures/`

**Why**

Decisions are not audit-log text. They are graph facts with bitemporal history
and provenance. The engine must enforce their shape.

**Implementation details**

- Require `justification` when `exception=true`.
- Require `decided_at`, `decision_type`, `subject`, `outcome`, and provenance.
- Require all four edge classes for complete decisions, with an explicit
  `allow_incomplete=true` flag for staged ingestion.
- Add indexes:
  - `(decision_type, decided_at, expired_at)`
  - `decided_by`
  - `applied_policy`
  - full-text on `subject` and `justification`

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDDecisionSchemaTest
```

### 3.2 Implement Lineage And Impact Traversal Procedures

**What to build**

Native procedures:

- `contextd.decision.lineage(decisionRid, maxDepth)`
- `contextd.decision.impact(decisionRid, maxDepth)`

**Where**

- Graph traversal package: `engine/src/main/java/com/arcadedb/graph/`
- SQL functions: `engine/src/main/java/com/arcadedb/function/sql/graph/`
- Cypher procedures:
  `engine/src/main/java/com/arcadedb/query/opencypher/procedures/`

**Why**

Lineage and impact walks are core compliance operations and should execute near
the adjacency lists under the same permissions and snapshot.

**Implementation details**

- Use BFS over typed edge filters.
- Include vertex RID, type, depth, edge type, provenance, and temporal fields in
  each returned row.
- Enforce `maxDepth`, `maxResults`, timeout, and RBAC per visited file.
- Support `AS OF` options by reusing the temporal visibility logic.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDDecisionTraversalTest
```

Expected proof:

- Backward lineage reaches facts, episodes, and policy.
- Forward impact reaches affected entities and downstream decisions.
- Temporal lineage at a past system time excludes later facts.

### 3.3 Store Identity Graph And Resolver Events Natively

**What to build**

Native storage for Resolver artifacts:

- Canonical entity.
- Source identities.
- Candidate matches.
- Resolution events.
- Attribute consensus with provenance.
- Bitemporal merge/split history.

**Where**

- Schema helpers: `engine/src/main/java/com/arcadedb/contextd/schema/`
- Vector index for blocking: `engine/src/main/java/com/arcadedb/index/vector/`
- Full-text/name indexes: `engine/src/main/java/com/arcadedb/index/fulltext/`
- SQL/Cypher procedures under ContextD packages.

**Why**

The expensive ML parts of Resolver stay in Python, but the persistent Identity
Graph and resolution history must be ACID and bitemporal with the graph.

**Implementation details**

- Add primitive types:
  - `ContextDCanonicalEntity`
  - `ContextDSourceIdentity`
  - `ContextDIdentityEdge`
  - `ContextDResolutionEvent`
- Add exact-match indexes on normalized emails and source IDs.
- Add full-text indexes on normalized names.
- Add vector indexes on name/profile embeddings.
- Add MinHash/LSH blocking support as stored signatures first. Native MinHash
  query acceleration can be a later optimization.
- Add procedures:
  - `contextd.identity.lookupExact(...)`
  - `contextd.identity.candidates(...)`
  - `contextd.identity.merge(...)`
  - `contextd.identity.split(...)`

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDIdentityGraphTest
```

## Phase 4: Full-Text, BM25, Phrase Search, And Analyzer Control

### 4.1 Replace Coordination-Factor Scoring With BM25

**What to build**

Implement real BM25 scoring for `LSMTreeFullTextIndex`.

**Where**

- `engine/src/main/java/com/arcadedb/index/fulltext/LSMTreeFullTextIndex.java`
- `engine/src/main/java/com/arcadedb/index/fulltext/FullTextQueryExecutor.java`
- `engine/src/main/java/com/arcadedb/schema/FullTextIndexMetadata.java`
- `engine/src/main/java/com/arcadedb/index/IndexCursorEntry.java`

**Why**

Current scoring counts matching terms. The spec requires BM25 so exact terms,
names, IDs, and jargon rank predictably and can be fused with vector and graph
results.

**Implementation details**

- Store posting values as `(term_frequency, document_length, optional positions)`.
- Track corpus stats:
  - document count.
  - average document length.
  - document frequency per term.
- Add `BM25Scorer` with configurable `k1=1.2` and `b=0.75`.
- Ensure `IndexCursorEntry.score` can represent non-integer scores. If changing
  the existing field is too invasive, add a `doubleScore` accessor and preserve
  integer score for compatibility until callers migrate.
- Keep corpus statistics transactionally consistent with document writes.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=BM25ScorerTest
mvn test -pl engine -Dtest=ContextDFullTextBM25Test
```

Expected proof:

- A term appearing in many documents has lower IDF.
- A shorter document with the same term frequency ranks higher.
- Results sort descending by BM25.
- Existing full-text query syntax still works.

### 4.2 Add Positional Posting Lists For Phrase Search

**What to build**

Support exact phrase search using per-document term positions.

**Where**

- `engine/src/main/java/com/arcadedb/index/fulltext/`
- `engine/src/main/java/com/arcadedb/schema/FullTextIndexMetadata.java`

**Why**

Context assembly often needs exact phrases from episodes and policies. Phrase
search should not be approximated with AND queries.

**Implementation details**

- Add metadata option `positions=true`.
- Store position arrays in the posting value.
- For `PhraseQuery`, require candidate documents to contain all terms and then
  intersect positions with `p, p+1, ...`.
- Keep position storage optional to avoid overhead on fields that do not need
  phrase search.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDPhraseSearchTest
```

### 4.3 Add Analyzer Profiles Per Field

**What to build**

Configurable analyzer pipelines per indexed field:

- exact.
- standard.
- stopword plus stemmer.
- synonym.
- edge-gram.

**Where**

- `engine/src/main/java/com/arcadedb/schema/FullTextIndexMetadata.java`
- `engine/src/main/java/com/arcadedb/index/fulltext/`
- SQL DDL parser and index builder.

**Why**

ContextD fields have different semantics. Email, ticket ID, and policy code
need exact matching. Natural language fields need normalization.

**Implementation details**

- Extend full-text index metadata with a per-field analyzer map.
- Reuse Lucene analyzers where available and license-compatible.
- If adding Snowball analyzers requires dependency changes, verify license and
  update `ATTRIBUTIONS.md` and `NOTICE`.
- Add DDL syntax for analyzer options.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDAnalyzerProfileTest
```

## Phase 5: Vector Search, Filtered ANN, And Hybrid Retrieval

### 5.1 Harden HNSW/PQ For ContextD Embeddings

**What to build**

Make `LSMVectorIndex` ready for ContextD entity, relationship, fact, ontology,
and resolver embeddings at 10M to 100M scale.

**Where**

- `engine/src/main/java/com/arcadedb/index/vector/LSMVectorIndex.java`
- `engine/src/main/java/com/arcadedb/index/vector/LSMVectorIndexGraphFile.java`
- `engine/src/main/java/com/arcadedb/index/vector/LSMVectorIndexPQFile.java`
- `engine/src/main/java/com/arcadedb/index/vector/VectorQuantizationMetadata.java`
- `engine/src/main/java/com/arcadedb/schema/LSMVectorIndexMetadata.java`

**Why**

Vector search replaces Milvus for substrate retrieval. It must support disk
graphs, PQ compression, async rebuilds, filtered search, and exact re-ranking.

**Implementation details**

- Expose ContextD defaults:
  - `M=16`.
  - `efConstruction=200`.
  - `efSearch=64` for top-10.
  - refinement candidates `2k`.
- Add metadata for embedding model, dimensions, distance function, PQ params,
  and codebook version.
- Add a rebuild trigger when embedding model changes.
- Make graph build progress visible through metrics and admin API.
- Ensure async rebuild hot-swap drains mutations that arrive during rebuild.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDVectorIndexLifecycleTest
mvn test -pl engine -Dtest=ContextDVectorPQRecallTest
```

### 5.2 Replace Set-Based RID Filter With Bitmap-Aware Filtered ANN

**What to build**

Efficient pre-filtered vector search for filters such as entity type, source,
tenant scope, tag, temporal current state, or RBAC visibility.

**Where**

- Existing hook: `engine/src/main/java/com/arcadedb/index/vector/RIDBitsFilter.java`
- New bitmap utilities: `engine/src/main/java/com/arcadedb/utility/` or
  `engine/src/main/java/com/arcadedb/index/bitmap/`
- Query planner integration:
  `engine/src/main/java/com/arcadedb/query/sql/executor/`

**Why**

The current filter uses `Set<RID>`. At large scale, filters must be compact,
composable, and cheap to intersect.

**Implementation details**

- Implement `RIDBitmap` with chunked containers. Start with ArcadeDB-native
  primitive arrays; introduce RoaringBitmap only if license and performance
  review pass.
- Add bitmap builders for:
  - type label.
  - source.
  - tags.
  - RBAC scope.
  - temporal current rows.
- Make vector search inflate `ef_search` based on filter selectivity, capped at
  `16x`.
- Add exact re-ranking over full vectors after PQ candidate retrieval.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDFilteredVectorSearchTest
```

Expected proof:

- Filtered search returns only allowed RIDs.
- Low-selectivity filters inflate `ef_search`.
- Exact re-ranking improves recall compared with PQ-only search.

### 5.3 Implement Native RRF Hybrid Fusion

**What to build**

A native retrieval operator that fuses BM25, vector, and graph traversal ranked
lists using Reciprocal Rank Fusion.

**Where**

- New executor steps:
  `engine/src/main/java/com/arcadedb/query/sql/executor/RRFFusionStep.java`
  `engine/src/main/java/com/arcadedb/query/sql/executor/HybridSearchStep.java`
- Scoring helpers:
  `engine/src/main/java/com/arcadedb/contextd/search/`
- SQL functions:
  `engine/src/main/java/com/arcadedb/function/sql/contextd/`
- HTTP/gRPC endpoint later in `server/` and `grpcw/`.

**Why**

ContextD retrieval must combine lexical, semantic, and structural signals under
one transaction. Doing this in Python over three stores adds latency and breaks
snapshot consistency.

**Implementation details**

- Define `HybridSearchRequest`:
  - query text.
  - optional embedding vector.
  - type/source/tag filters.
  - temporal options.
  - k and candidate limits.
  - recipe name.
- Execute in parallel where safe:
  - BM25 full-text search.
  - HNSW vector search.
  - graph traversal from seed entities.
- Deduplicate by canonical RID.
- Compute `rrf = sum(1 / (k + rank_i))` with default `k=60`.
- Multiply by `feedback_weight` in Phase 5.4.
- Return method-specific ranks and scores for explainability.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDRRFFusionTest
mvn test -pl engine -Dtest=ContextDHybridSearchExecutionTest
```

### 5.4 Add Feedback Weight And Streaming EMA Updates

**What to build**

Feedback-weighted retrieval:

- Every Entity, Relationship, and Fact has a `feedback_weight`.
- Retrieval multiplies reranker score by weight.
- Feedback events update weight by streaming EMA.

**Where**

- Record/schema fields: `engine/src/main/java/com/arcadedb/contextd/schema/`
- Query result scoring: `engine/src/main/java/com/arcadedb/contextd/search/`
- SQL function/procedure: `engine/src/main/java/com/arcadedb/function/sql/contextd/`
- Audit integration: Phase 6 audit component.

**Why**

The spec requires retrieval to learn from feedback without extra I/O. A field
is enough initially; moving to a fixed record-header slot can be a performance
optimization after behavior is proven.

**Implementation details**

- Use default `0.5`.
- Add procedure:
  `contextd.feedback.submit(targetRid, rating, sessionId, userId, metadata)`.
- Normalize rating:
  `normalized = (rating - 1) / 4`.
- Update:
  `newWeight = round(clamp(old + 0.1 * (normalized - old), 0.0, 1.0), 4)`.
- Detect duplicate submissions with a feedback event id.
- Append feedback audit entry.
- Return old weight, new weight, and applied flag.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDFeedbackEMATest
mvn test -pl engine -Dtest=ContextDFeedbackHybridRankingTest
```

Expected proof:

- Duplicate feedback is idempotent.
- Positive feedback increases weight gradually.
- Negative feedback decreases weight gradually.
- Hybrid results reorder when feedback makes a lower raw result more useful.

### 5.5 Add Context Assembly Query Primitive

**What to build**

A database-native primitive that returns the structured payload needed by AI
agents:

- primary entities.
- relationships.
- relevant facts.
- temporal context.
- decision history.
- saga/community summaries.
- source references.
- metadata.

**Where**

- New package: `engine/src/main/java/com/arcadedb/contextd/assembly/`
- SQL function/procedure:
  `engine/src/main/java/com/arcadedb/function/sql/contextd/`
- HTTP/gRPC endpoint later in server modules.

**Why**

The full product context assembly algorithm should be close to the data so it
can use bitemporal visibility, graph traversal, indexes, feedback weights, and
RBAC in one snapshot.

**Implementation details**

- Start with deterministic assembly over an already parsed request. Intent
  parsing remains in Python.
- Inputs:
  - seed RIDs or query text plus embedding.
  - temporal constraints.
  - max tokens or max records.
  - retrieval recipe.
- Use hybrid search to select candidates.
- Expand graph neighborhoods with max depth and edge filters.
- Pull current facts first, then recent changes, then decision lineage.
- Budget by estimated serialized size until tokenizer integration exists.
- Return JSON through `JSONObject`/`JSONArray`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDContextAssemblyTest
```

## Phase 6: Audit Log, Tamper Evidence, And Compliance Operations

### 6.1 Add AuditLog As A Component

**What to build**

An append-only hash-chained audit log component separate from WAL.

**Where**

- New package: `engine/src/main/java/com/arcadedb/audit/`
- Component registration: `engine/src/main/java/com/arcadedb/schema/LocalSchema.java`
- Transaction callbacks: `engine/src/main/java/com/arcadedb/database/TransactionContext.java`
- Server auth/request context:
  `server/src/main/java/com/arcadedb/server/http/handler/`
  and wire protocol modules.

**Why**

WAL exists for recovery, not compliance. Audit needs queryable, sealed,
tamper-evident segments that survive normal WAL cleanup.

**Implementation details**

- Add `AuditLogComponent extends Component`.
- Segment layout:
  - `audit.<seq>.active`.
  - `audit.<seq>.sealed`.
- Entry fields:
  - timestamp.
  - user id dictionary id.
  - api key id dictionary id.
  - action enum.
  - resource type dictionary id.
  - resource RID array.
  - latency ms.
  - IP address.
  - user agent dictionary id.
  - prev hash.
  - payload hash.
  - entry hash.
- Seal on size threshold or time threshold.
- Build sealed segment index on `(timestamp, user_id, action)`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=AuditLogComponentTest
mvn test -pl server -Dtest=ContextDAuditHttpTest
```

### 6.2 Implement Audit Chain Verification And Attestation Hooks

**What to build**

Verification API for audit chains and optional publication of chain heads to an
external attestation target.

**Where**

- `engine/src/main/java/com/arcadedb/audit/`
- Server admin handlers:
  `server/src/main/java/com/arcadedb/server/http/handler/`
- Scheduler/plugin:
  `server/src/main/java/com/arcadedb/server/plugin/`

**Why**

Tamper evidence only matters if the system can prove chain continuity and catch
rewrites.

**Implementation details**

- Add `AuditChainVerifier`.
- Verify:
  - each payload hash.
  - each entry hash.
  - each `prev_hash`.
  - each sealed segment hash.
- Expose `GET /contextd/audit/verify`.
- Add a pluggable `AuditAttestationSink` interface. Do not hardcode cloud
  providers in the engine in the first pass.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=AuditChainVerifierTest
```

Expected proof:

- Clean chain verifies.
- Modified payload fails.
- Removed entry fails.
- Reordered segment fails.

### 6.3 Implement Right-To-Deletion Tombstone Flow

**What to build**

A database operation that marks all data for a canonical identity as deleted
without breaking audit history.

**Where**

- `engine/src/main/java/com/arcadedb/contextd/compliance/`
- Bitemporal service from Phase 2.
- Audit service from Phase 6.
- Graph traversal from Phase 3.

**Why**

GDPR deletion must be database-native because affected facts, relationships,
episodes, embeddings, full-text entries, and audit entries all share storage.

**Implementation details**

- Input: canonical entity RID, requester identity, legal basis.
- Find all facts, relationships, decision links, and episodes referencing the
  identity.
- Supersede each with `expired_at=now` and `invalid_at=now`.
- Clear entity properties except stable identifiers needed for audit.
- Tombstone episode content with deterministic hash.
- Remove or invalidate vector and full-text entries for redacted content.
- Append audit entry with affected RIDs.
- Mark physical purge deadline for compaction.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDRightToDeletionTest
```

## Phase 7: Storage-Layer RBAC, Multi-Tenancy, And Resource Governance

### 7.1 Map ContextD Roles And Scopes To ArcadeDB Security

**What to build**

Implement ContextD roles:

- Owner.
- Admin.
- Editor.
- Viewer.
- Agent.
- Connector.

And scopes:

- source.
- entity type.
- tag.
- PII permission.
- direct SQL/Cypher permission.
- feedback permission.

**Where**

- Engine security interface:
  `engine/src/main/java/com/arcadedb/security/SecurityDatabaseUser.java`
- Server security implementation:
  `server/src/main/java/com/arcadedb/server/security/ServerSecurityDatabaseUser.java`
- Security repositories:
  `server/src/main/java/com/arcadedb/server/security/`
- Query planner filters:
  `engine/src/main/java/com/arcadedb/query/sql/executor/`
  and `engine/src/main/java/com/arcadedb/query/opencypher/`

**Why**

All protocols must enforce the same access model. Application-side filtering is
insufficient for SQL, Bolt, Redis, Mongo, gRPC, and HTTP direct access.

**Implementation details**

- Extend file bitmap permissions for coarse type-level access.
- Add dynamic scope predicates compiled into RID bitmaps:
  - sources.
  - entity types.
  - tags.
  - PII read.
- Add action bits for:
  - `SUBMIT_FEEDBACK`.
  - `READ_DECISION_LINEAGE`.
  - `MANAGE_CONTEXT_CORES`.
  - `DIRECT_QUERY`.
- Ensure `LocalBucket.createRecord`, `getRecord`, `updateRecord`, and delete
  remain the final enforcement point for file-level rights.
- Ensure query planners inject dynamic scope filters before result materializing.

**Validation**

```bash
cd database/arcadedb
mvn test -pl server -Dtest=ContextDRBACTest
mvn test -pl postgresw -Dtest=ContextDPostgresRBACTest
mvn test -pl bolt -Dtest=ContextDBoltRBACTest
```

### 7.2 Enforce Database-Per-Tenant Isolation

**What to build**

Tenant database lifecycle helpers and guardrails.

**Where**

- Server database management:
  `server/src/main/java/com/arcadedb/server/`
- HTTP admin handlers:
  `server/src/main/java/com/arcadedb/server/http/handler/`
- HA/Raft database install/drop:
  `ha-raft/src/main/java/com/arcadedb/server/ha/raft/`

**Why**

The spec requires a separate database directory per tenant. Cross-tenant
queries should be physically impossible.

**Implementation details**

- Add tenant database naming and path validation.
- Add create/drop/export/import APIs that operate one tenant database at a
  time.
- Ensure audit, WAL, schema, and security files are per database.
- Reject cross-database query attempts from ContextD protocol endpoints.

**Validation**

```bash
cd database/arcadedb
mvn test -pl server -Dtest=ContextDTenantIsolationTest
```

### 7.3 Add Per-Tenant Quotas And Rate Limits

**What to build**

Per-tenant controls:

- page cache soft quota.
- concurrent transaction cap.
- query QPS.
- write records/sec.
- result set cap.
- query timeout.
- WAL bytes/sec.

**Where**

- Page cache: `engine/src/main/java/com/arcadedb/engine/PageManager.java`
- Transaction allocation: `engine/src/main/java/com/arcadedb/database/TransactionContext.java`
- Server/protocol dispatch:
  `server/src/main/java/com/arcadedb/server/network/`
  and protocol modules.
- Result materialization:
  `engine/src/main/java/com/arcadedb/query/sql/executor/ResultSet.java`

**Why**

Multi-tenant cloud operation requires noisy-neighbor controls inside the
database process.

**Implementation details**

- Track per-database page-cache bytes and prefer eviction from databases above
  quota.
- Add token buckets at protocol dispatch.
- Add result truncation metadata: `result_truncated=true`.
- Apply read timeout from `SecurityDatabaseUser.getReadTimeout()`.
- Emit metrics per tenant database.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDQuotaTest
mvn test -pl server -Dtest=ContextDRateLimitTest
```

## Phase 8: Graph Engine And Query Optimizer Enhancements

### 8.1 Add ContextD BFS/DFS Traversal Operators

**What to build**

Database-native traversal operators that support:

- typed edge filters.
- max hops.
- target predicates.
- abort predicates.
- temporal visibility.
- RBAC visibility.
- bounded memory.

**Where**

- Graph engine: `engine/src/main/java/com/arcadedb/graph/`
- SQL executor: `engine/src/main/java/com/arcadedb/query/sql/executor/`
- OpenCypher executor:
  `engine/src/main/java/com/arcadedb/query/opencypher/executor/steps/`

**Why**

ContextD currently depends on Neo4j and GDS for PPR/PCST style traversals.
ArcadeDB needs native structural retrieval for hybrid search and context
assembly.

**Implementation details**

- Start with BFS and DFS over existing adjacency segments.
- Use primitive RID queues and visited bitmaps.
- Respect result cap and timeout.
- Return depth, path edge types, and source method score.
- Add bidirectional BFS for shortest path.
- Add Dijkstra/A* only after unweighted traversal is stable.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDGraphTraversalTest
mvn test -pl engine -Dtest=ContextDShortestPathTest
```

### 8.2 Build Read-Optimized Graph Analytical Views

**What to build**

Compressed Sparse Row snapshots and optional bitmap adjacency views for
read-heavy graph traversal.

**Where**

- Existing graph analytical view hints:
  `engine/src/main/java/com/arcadedb/graph/CSRVertexIterable.java`
  and related GAV classes.
- Schema view metadata: `engine/src/main/java/com/arcadedb/schema/`
- OpenCypher GAV operators:
  `engine/src/main/java/com/arcadedb/query/opencypher/executor/operators/`

**Why**

The spec identifies traversal lock contention as a bottleneck. Read-optimized
views make context assembly faster without weakening write-side ACID.

**Implementation details**

- Build CSR from live graph on a schedule or after N mutations.
- Store snapshot version and source transaction id.
- Route eligible read queries to CSR when staleness is acceptable.
- Fall back to live adjacency when queries require latest committed data.
- Add bitmap adjacency indexes for high-cardinality set intersections.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDGraphAnalyticalViewTest
```

### 8.3 Expand Cost Model And Statistics

**What to build**

Cost model support for ContextD query shapes:

- temporal predicates.
- hybrid search.
- vector filters.
- graph expansion.
- bitmap intersections.
- bitemporal indexes.

**Where**

- SQL planner: `engine/src/main/java/com/arcadedb/query/sql/executor/`
- OpenCypher optimizer:
  `engine/src/main/java/com/arcadedb/query/opencypher/optimizer/statistics/`
- Schema statistics: `engine/src/main/java/com/arcadedb/schema/LocalSchema.java`

**Why**

The planner must pick current-state indexes, temporal history indexes, vector
pre-filters, graph traversal strategy, and late materialization predictably.

**Implementation details**

- Maintain row counts transactionally.
- Add HyperLogLog distinct estimates if dependency review permits, otherwise
  start with sampled distinct counts.
- Track null fraction, avg width, top-K values, and histograms.
- Invalidate cached plans on schema version changes and major stats drift.
- Extend `EXPLAIN` to show estimated cardinality and selected physical op.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDOptimizerStatsTest
mvn test -pl engine -Dtest=ContextDQueryPlanStabilityTest
```

## Phase 9: Context Cores And Snapshot Lifecycle

### 9.1 Build Content-Addressed Context Core Export

**What to build**

Immutable snapshots containing graph data, embeddings, ontology, retrieval
policies, feedback weights, source manifests, and metadata.

**Where**

- New package: `engine/src/main/java/com/arcadedb/contextd/core/`
- Integration/export module:
  `integration/src/main/java/com/arcadedb/integration/`
- Page manager suspend hook:
  `engine/src/main/java/com/arcadedb/engine/PageManager.java`

**Why**

Context Cores are versioned graph state. They must snapshot multiple storage
components consistently: buckets, LSM indexes, vector graph/PQ files, full-text
postings, feedback, and schema.

**Implementation details**

- Add `ContextCoreBuilder`.
- Take a consistent snapshot using transaction snapshot and page-version reads.
- Serialize as msgpack if an Apache-compatible dependency is acceptable. If not,
  use ArcadeDB binary/JSON first and add msgpack after license review.
- Compute SHA-256 over canonical archive bytes.
- Include:
  - schema version.
  - source transaction id.
  - build timestamp.
  - builder identity.
  - component manifest with file hashes.

**Validation**

```bash
cd database/arcadedb
mvn test -pl integration -Dtest=ContextCoreExportTest
```

### 9.2 Implement Test, Diff, Promote, And Rollback

**What to build**

Engine operations:

- build.
- test against golden queries.
- diff two cores.
- promote to active core.
- rollback.

**Where**

- `engine/src/main/java/com/arcadedb/contextd/core/`
- Server handlers:
  `server/src/main/java/com/arcadedb/server/http/handler/`
- Console commands:
  `console/src/main/java/com/arcadedb/console/`

**Why**

Core promotion must atomically swap graph state without partial file visibility.

**Implementation details**

- Store cores under a per-database `context-cores/` directory.
- Use `PageManager.suspendFlushAndExecute` during final promote/rollback file
  switch.
- Promote by atomically updating a manifest pointer, not by copying large files
  into place while readers are active.
- Add golden query runner that executes SQL/Cypher/hybrid search against a core.
- Diff counts entities, relationships, facts, decisions, index stats, and
  retrieval scores for golden queries.

**Validation**

```bash
cd database/arcadedb
mvn test -pl integration -Dtest=ContextCoreLifecycleTest
```

## Phase 10: WAL, Checkpoints, Replication, Backup, And PITR

### 10.1 Implement Group Commit

**What to build**

Batch multiple transaction WAL buffers into one fsync.

**Where**

- `engine/src/main/java/com/arcadedb/engine/TransactionManager.java`
- `engine/src/main/java/com/arcadedb/engine/WALFile.java`

**Why**

Single fsync per commit caps throughput. ContextD ingestion and feedback events
require high write concurrency.

**Implementation details**

- Add `GroupCommitter` with leader/follower batching.
- Window default: 200 microseconds.
- Max batch: 64 transactions or configurable bytes.
- Preserve transaction ordering and error propagation.
- Expose metrics:
  - group size.
  - wait time.
  - fsync duration.
  - commit latency.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=GroupCommitterTest
mvn test -pl load-tests -Dtest=ContextDCommitThroughputBenchmark
```

### 10.2 Add Fuzzy ARIES-Style Checkpoints

**What to build**

Checkpoint records that bound crash recovery time without quiescing writes.

**Where**

- `engine/src/main/java/com/arcadedb/engine/TransactionManager.java`
- `engine/src/main/java/com/arcadedb/engine/WALFile.java`
- New checkpoint metadata class in `engine/src/main/java/com/arcadedb/engine/`

**Why**

Recovery time cannot grow with all WAL history. ContextD cloud tenants need
predictable restart behavior.

**Implementation details**

- Add `BEGIN_CKPT` and `END_CKPT` WAL record types.
- Track active transaction table and dirty page table.
- Persist `last_checkpoint_lsn`.
- Recovery starts from minimum dirty-page recovery LSN.
- Keep existing page-version idempotency.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=CheckpointRecoveryTest
```

### 10.3 Add WAL Archive And PITR

**What to build**

Continuous archive of sealed WAL segments and point-in-time restore.

**Where**

- Engine WAL: `engine/src/main/java/com/arcadedb/engine/`
- Integration backup/restore:
  `integration/src/main/java/com/arcadedb/integration/`
- Server admin API:
  `server/src/main/java/com/arcadedb/server/http/handler/`

**Why**

Enterprise deployments require per-transaction restore and cross-region
disaster recovery.

**Implementation details**

- Seal WAL segments before archive upload.
- Add pluggable archive target interface for filesystem and S3-compatible
  storage first.
- Add restore flow:
  - restore latest full backup before target time.
  - replay archived WAL until target transaction timestamp.
- Include audit segments and schema manifests in backups.

**Validation**

```bash
cd database/arcadedb
mvn test -pl integration -Dtest=ContextDPITRTest
```

### 10.4 Extend Raft Log Entries For ContextD State

**What to build**

Ensure Raft replicates all ContextD substrate state:

- transactions.
- schema.
- security.
- audit segment state.
- context core manifest changes.
- database install/drop.

**Where**

- `ha-raft/src/main/java/com/arcadedb/server/ha/raft/RaftLogEntryType.java`
- `ha-raft/src/main/java/com/arcadedb/server/ha/raft/RaftLogEntryCodec.java`
- `ha-raft/src/main/java/com/arcadedb/server/ha/raft/ArcadeStateMachine.java`

**Why**

Replicas must converge on data, schema, RBAC, audit state, and active context
core pointers.

**Implementation details**

- Audit append can be part of transaction entry if it is committed with the
  transaction. Segment seal metadata may need its own entry.
- Context Core promote/rollback must be a linearizable state-machine entry.
- Security bitmap changes must continue to use security entries and atomic swap.
- Keep page-version guards for idempotent follower apply.

**Validation**

```bash
cd database/arcadedb
mvn test -pl ha-raft -Dtest=ContextDRaftStateMachineTest
mvn test -pl e2e-ha -Dtest=ContextDClusterIT
```

## Phase 11: Encryption, Compression, Off-Heap Memory, And Observability

### 11.1 Move From Record Encryption Hook To Per-Page Encryption

**What to build**

Per-page AES-GCM encryption with KEK/DEK wrapping and key rotation hooks.

**Where**

- Existing encryption hook:
  `engine/src/main/java/com/arcadedb/database/DataEncryption.java`
  and `DefaultDataEncryption.java`
- Page IO path:
  `engine/src/main/java/com/arcadedb/engine/PaginatedComponentFile.java`
  and `ComponentFile.java`
- Server/KMS config:
  `server/src/main/java/com/arcadedb/server/`

**Why**

The current encryption abstraction encrypts byte arrays at serialization
boundaries. The spec requires page-level authenticated encryption for data
files, with per-tenant key control.

**Implementation details**

- Define encrypted page layout:
  - 12-byte nonce.
  - ciphertext.
  - 16-byte auth tag.
- Store wrapped DEK sidecar per database or per file.
- Implement key provider interface:
  - local dev provider.
  - environment variable provider.
  - external KMS provider later.
- Add quarterly DEK rotation background rewriter.
- Do not log key material.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=PageEncryptionTest
```

### 11.2 Add Compression Policies

**What to build**

Compression at record, page, and cold-segment levels:

- LZ4 for hot blobs.
- ZSTD for cold segments and archives.
- Dictionary training for small cold records.

**Where**

- Existing compression package:
  `engine/src/main/java/com/arcadedb/compression/`
- Serializer: `engine/src/main/java/com/arcadedb/serializer/BinarySerializer.java`
- Time-series sealed store:
  `engine/src/main/java/com/arcadedb/engine/timeseries/`
- Backup/archive: `integration/src/main/java/com/arcadedb/integration/`

**Why**

ContextD stores long-lived episodes, facts, audit logs, and time-series. Cold
history must compress aggressively while hot records remain fast.

**Implementation details**

- Add per-type compression policy metadata.
- Compress large blob fields before bucket chunking.
- Add page-level compression for cold-history buckets.
- Add ZSTD only after license and attribution review.
- Add compression ratio metrics by component.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=ContextDCompressionPolicyTest
```

### 11.3 Add Direct Buffer Pool And Memory Accounting

**What to build**

Track direct/off-heap allocations for page cache, WAL buffers, wire protocol
buffers, vector graph/PQ files, and bitmap indexes.

**Where**

- Page manager: `engine/src/main/java/com/arcadedb/engine/PageManager.java`
- Vector index: `engine/src/main/java/com/arcadedb/index/vector/`
- Network/server buffers:
  `server/src/main/java/com/arcadedb/server/network/`
- Metrics module: `metrics/src/main/java/com/arcadedb/metrics/`

**Why**

ContextD's large working sets cannot rely on Java heap alone. Operators need
accurate memory accounting and leak alarms.

**Implementation details**

- Add `NativeMemoryTracker`.
- Track allocation owner:
  - database name.
  - component file id.
  - subsystem.
- Export per-tenant direct memory totals.
- Add periodic drift check against JVM buffer pool MXBeans.
- Alert if accounted vs observed direct memory differs by more than 5%.

**Validation**

```bash
cd database/arcadedb
mvn test -pl engine -Dtest=NativeMemoryTrackerTest
mvn test -pl metrics -Dtest=ContextDMemoryMetricsTest
```

### 11.4 Add ContextD OpenTelemetry And Prometheus Metrics

**What to build**

Metrics and traces for:

- ingestion writes.
- temporal supersession.
- hybrid search.
- vector search.
- full-text search.
- graph traversal.
- feedback updates.
- audit append/verify.
- context core lifecycle.
- page cache, WAL, checkpoint, and Raft.

**Where**

- Metrics module: `database/arcadedb/metrics/`
- Server monitoring: `server/src/main/java/com/arcadedb/server/monitor/`
- Query execution instrumentation:
  `engine/src/main/java/com/arcadedb/query/`

**Why**

The spec calls for query latency, ingestion latency, feedback, context tokens
saved, and resolution accuracy. The database must expose substrate metrics even
when product metrics are gathered in Python.

**Implementation details**

- Add Prometheus counters/histograms:
  - `contextd_queries_total`
  - `contextd_query_latency_seconds`
  - `contextd_hybrid_search_latency_seconds`
  - `contextd_vector_search_latency_seconds`
  - `contextd_temporal_supersessions_total`
  - `contextd_feedback_scores`
  - `contextd_audit_verification_failures_total`
- Add trace attributes for query recipe, result count, tenant database, and
  index names.
- Ensure sensitive query text can be disabled or redacted.

**Validation**

```bash
cd database/arcadedb
mvn test -pl metrics -Dtest=ContextDMetricsTest
```

## Phase 12: Wire Protocol Polyglot And Backend Migration

### 12.1 Normalize ContextD Capabilities Across Protocols

**What to build**

Expose the same ContextD operations across:

- HTTP.
- PostgreSQL wire.
- Bolt/Cypher.
- gRPC.
- Redis.
- Mongo.

**Where**

- HTTP: `server/src/main/java/com/arcadedb/server/http/handler/`
- PostgreSQL: `postgresw/src/main/java/com/arcadedb/postgres/`
- Bolt: `bolt/src/main/java/com/arcadedb/bolt/`
- gRPC: `grpc/` and `grpcw/`
- Redis: `redisw/src/main/java/com/arcadedb/redis/`
- Mongo: `mongodbw/src/main/java/`

**Why**

The spec's protocol-polyglot claim only holds if RBAC, bitemporal visibility,
audit logging, and query semantics are shared by every protocol.

**Implementation details**

- Route all protocol commands through the same database operations.
- Add audit context to each protocol executor.
- Ensure direct SQL/Cypher permission is checked before arbitrary query
  execution.
- Add protocol-specific error mapping:
  - rate limit.
  - RBAC denied.
  - temporal syntax error.
  - stale replica.
  - audit verification failure.
- Keep protocol modules using `provided` scope for `arcadedb-server`.

**Validation**

```bash
cd database/arcadedb
mvn test -pl postgresw -Dtest=ContextDPostgresProtocolTest
mvn test -pl bolt -Dtest=ContextDBoltProtocolTest
mvn test -pl grpcw -Dtest=ContextDGrpcProtocolTest
mvn test -pl redisw -Dtest=ContextDRedisProtocolTest
mvn test -pl mongodbw -Dtest=ContextDMongoProtocolTest
```

### 12.2 Build The Python ArcadeDB Destination

**What to build**

Add a backend destination that writes ContextD normalized entities and graph
events into ArcadeDB instead of Neo4j/Milvus.

**Where**

- `backend/contextd/platform/destinations/arcadedb.py`
- `backend/contextd/platform/builders/destinations.py`
- `backend/contextd/platform/sync/handlers/`
- `backend/contextd/search/operations/retrieval.py`
- `backend/contextd/platform/agent_orchestration/tools/cypher.py`

**Why**

The database work is not complete until ContextD can ingest and retrieve
through ArcadeDB in real flows.

**Implementation details**

- Implement `BaseDestination`:
  - `setup_collection`
  - `bulk_insert`
  - `delete_by_sync_id`
  - `bulk_delete_by_parent_ids`
  - `search`
- Translate existing normalized entities and graph events into ContextD
  primitive requests.
- Keep the old Neo4j destination behind a feature flag during migration.
- Add `ARCADEDB_URL`, `ARCADEDB_USER`, `ARCADEDB_PASSWORD`, and
  `CONTEXTD_SUBSTRATE_PROVIDER=arcadedb`.
- Keep Python Temporal workflow boundaries unchanged.

**Validation**

```bash
cd backend
poetry run pytest tests/platform/test_arcadedb_destination.py --no-cov
poetry run pytest tests/api/test_search.py --no-cov
```

Then run an end-to-end sync with `CONTEXTD_SUBSTRATE_PROVIDER=arcadedb` and
verify:

- entities land in ArcadeDB.
- graph edges land in ArcadeDB.
- full-text search returns expected nodes.
- vector search returns expected nodes.
- hybrid context search returns structured results.
- feedback updates reorder results.

## Phase 13: Performance, Scale, And Release Gates

### 13.1 Required Performance Gates

For each gate, record dataset shape, JVM flags, hardware, commit SHA, p50, p95,
p99, throughput, and memory.

| Gate | Target for first native release |
| --- | --- |
| Current fact lookup | p50 under 5 ms on 10M facts |
| Temporal as-of lookup | p50 under 10 ms on 10M facts |
| BM25 term search | p50 under 20 ms on 10M docs |
| Phrase search | p50 under 30 ms on 1M docs |
| Vector search | p50 under 75 ms on 10M vectors with PQ |
| Filtered vector search | recall within 1 percent of unfiltered exact candidate set after refinement |
| Hybrid RRF search | p50 under 150 ms on 10M entities |
| BFS depth 3 | p50 under 50 ms on 10M nodes / 50M edges for selective seeds |
| Feedback update | p50 under 10 ms single record |
| Audit append | less than 5 percent write-throughput overhead |
| Crash recovery | recover 1 GB WAL in under 60 seconds |
| Context Core promote | atomic pointer swap under 1 second after build |

### 13.2 Required Correctness Gates

- Cross-model transaction rollback leaves no partial bucket, graph, vector,
  full-text, audit, or time-series writes.
- Every protocol enforces storage-layer RBAC.
- Every ContextD primitive has provenance.
- Bitemporal current, valid-time, system-time, and both-time queries return
  expected rows after supersession.
- Audit chain detects payload mutation, entry deletion, and segment reorder.
- Context Core export hash is stable across repeated exports of identical data.
- Raft followers apply ContextD transaction, schema, security, audit seal, and
  core promotion entries idempotently.
- PITR restores to a transaction boundary and excludes later transactions.

### 13.3 Release Checklist

- `mvn clean install -DskipTests` passes in `database/arcadedb`.
- Focused unit tests pass for modified modules.
- E2E protocol tests pass for HTTP, PostgreSQL, Bolt, and gRPC.
- HA tests pass for Raft transaction replication and snapshot install.
- Benchmark report is updated under `database/arcadedb/docs/contextd/benchmarks/`.
- `ATTRIBUTIONS.md` and `NOTICE` are updated for any new dependency.
- Parent repo submodule pin is bumped only after ArcadeDB fork commits are
  pushed to `github.com/nikhil-contextd/arcadedb`.

## Phase Ordering And Dependency Graph

```text
Phase 0 baseline
  -> Phase 1 primitive schema/provenance
     -> Phase 2 bitemporal storage
        -> Phase 3 decision lineage and identity graph
        -> Phase 5 hybrid retrieval
           -> Phase 12 Python ArcadeDB destination
     -> Phase 4 BM25/phrase search
        -> Phase 5 hybrid retrieval
     -> Phase 6 audit
        -> Phase 7 RBAC/governance
        -> Phase 10 replication/PITR
     -> Phase 8 graph optimizer
        -> Phase 5 hybrid retrieval
        -> Phase 9 Context Cores
     -> Phase 11 encryption/compression/metrics
        -> Phase 13 release gates
```

Do not start backend migration as the primary path before these engine features
exist: primitive schema, bitemporal current-state queries, full-text BM25,
vector search, graph traversal, RBAC, and audit append.

## Known Lessons Preserved From Previous Task Files

- Do not use `available()` plus `sleep()` for PostgreSQL wire reads. Use blocking
  or selector-based IO and verify latency with JDBC/psql.
- Record format changes are high risk. Prefer schema/property implementation
  first, then optimize into fixed headers after behavior is proven.
- Full-text scores must support floating-point values before BM25 can be
  correct.
- Full-text corpus statistics must be transactionally consistent with index
  updates.
- One thread per connection does not scale to the spec's connection target.
  Protocol modules need NIO selector based dispatch for high concurrency.
- Feedback weight default is `0.5`, not `1.0`, for spec-compatible cold start.
- ArcadeDB submodule changes must be committed and pushed in the ArcadeDB fork,
  not in the parent `contextd-engine` repository.
- Benchmark before and after every storage/index/query-path change.
- Group commit is foundational for the target write throughput.
- Page version is the OCC and recovery idempotency foundation. Preserve it
  across every new component.

## Immediate Next Tasks

- [ ] Create `database/arcadedb/docs/contextd/baseline.md` with current fork SHA,
      dirty state, build results, and focused test results.
- [ ] Add `ContextDFixtureTest` and the fixture helper under the ArcadeDB engine
      test tree.
- [ ] Add primitive schema descriptors for ContextD types and persist them in
      `schema.json`.
- [ ] Add provenance enforcement and `source_episode_id` indexing.
- [ ] Implement the first bitemporal current-state index and SQL rewrite for
      current facts.
- [ ] Add BM25 scorer tests before changing full-text scoring.
- [ ] Add feedback EMA tests using the default weight of `0.5`.

## Final Definition Of Done

This roadmap is complete when ContextD can ingest a representative source sync
into ArcadeDB, then serve a hybrid context query through the database-native
substrate with:

- one transaction spanning graph, vector, full-text, provenance, and audit;
- bitemporal facts and relationships queryable by current and historical state;
- decision lineage returned by native traversal;
- feedback updates reflected in subsequent ranking;
- RBAC enforced identically over HTTP, PostgreSQL, Bolt, and gRPC;
- a Context Core built, tested, promoted, and rolled back;
- audit chain verification passing after all operations;
- crash recovery, backup, PITR, and Raft replication validated by tests.
