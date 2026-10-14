# 11 — Distinguishing Technical Capabilities

> The technical properties that make ContextD's design hard to retrofit onto an existing graph database, vector database, or RAG framework. These are structural commitments — choices baked into the schema, the storage layer, and the engine internals — not features bolted on top.
>
> Each section names the capability, describes the implementation requirements, and explains why the requirements compose poorly with alternative architectures.

---

## 1. Database-native multi-model storage

A single ACID engine holds graph, vector (HNSW + product quantization), full-text (BM25), document, key-value, and time-series indexes side by side. Every transaction is atomic across all six models. A commit may simultaneously append a record to a bucket, update an HNSW vector index, insert into the full-text inverted index, write to the time-series sealed-segment store, and update the graph adjacency-list segments — all under one WAL fsync.

**Implementation requirements.**

- A unified page cache, transaction manager, and WAL serving every component (`Bucket`, `LSMTreeIndex`, `LSMVectorIndex`, `LSMTreeFullTextIndex`, `TimeSeriesShard`, `Dictionary`).
- Optimistic concurrency control via page versions (Section 3 of `05-contextd-native-db-implementation.md`) so concurrent commits to disjoint pages proceed in parallel.
- A file-level lock manager that orders locks deterministically to eliminate deadlock cycles by construction.
- A query planner that routes per query primitive — cosine over the HNSW index, BM25 over the inverted index, BFS over the adjacency lists — within one transaction context.

**Why retrofitting fails.**

A graph database with a vector-index plugin cannot deliver cross-model ACID — the plugin runs in its own process or its own transactional domain. A vector database with graph features bolted on cannot deliver native graph algorithms (PageRank, Louvain, Label Propagation, shortest-path) with SIMD acceleration. Adding a sixth data model on top of a fixed engine doubles the page cache, doubles the WAL, and breaks the lock ordering. Multi-model is a substrate-level commitment; it is not feasible as an extension.

---

## 2. Bitemporal-at-schema-level

Every Entity, Relationship, Fact, and Decision row carries four timestamp columns: `valid_at` and `invalid_at` (event time, when the fact was true in the world) plus `created_at` and `expired_at` (transaction time, when the system recorded or superseded the fact). Supersession is implemented as insert-not-update with an OCC version check; nothing is deleted.

**Implementation requirements.**

- Schema-level commitment to four timestamp columns on every row of every primitive type — 32 bytes per row of metadata overhead.
- Four index designs per fact predicate: current-state (partial index on `expired_at IS NULL`), historical-state (composite on `valid_at desc, invalid_at desc`), knowledge-state (composite on `created_at desc, expired_at desc`), and audit-state (reverse scan of the third).
- A pipeline supersession step that detects contradictions during ingestion (via hybrid search on edge fact embeddings), runs an LLM adjudication only on ambiguous candidates, and emits the supersession transaction atomically.
- Compaction logic that physically reorganizes closed (`expired_at IS NOT NULL`) rows into compacted pages with high pack ratio while leaving live rows on the hot path.

**Why retrofitting fails.**

Bitemporal storage cannot be added to an existing graph database without rewriting the data layer. The four-column commitment is per row of every type; partial bitemporal (e.g., only on facts) breaks the symmetry that lets the same query planner answer all four temporal query types. Existing customer data is not back-fillable — the historical event-time and transaction-time information was never recorded in the first place.

---

## 3. Feedback-weighted retrieval at the data layer

Every node and edge in the graph carries a `feedback_weight` field (4 bytes inline in the record header). Every retrieval multiplies its reranker score by the inline weight at zero additional I/O cost. Streaming exponential-moving-average updates (α=0.1) write through the same OCC commit path as any other transaction.

**Implementation requirements.**

- A 4-byte feedback-weight field reserved in the on-disk record header for every Entity and Relationship.
- An idempotent feedback log keyed on `(session_id, query_id)` to deduplicate replayed events.
- A batched-write optimization that accumulates feedback events for a 500-millisecond window or 100 events (whichever first) into one transaction.
- The query planner reading the inline weight during result assembly so `final_score = reranker_score × feedback_weight` adds zero additional reads.
- Inheritance rules during supersession: a new fact row inherits the old row's feedback weight rather than resetting to the cold-start value, so accumulated relevance signal is preserved across attribute changes.

**Why retrofitting fails.**

A vector database with a post-hoc reranker cannot integrate feedback at the data layer — the reranker runs after retrieval, so feedback is a top-of-stack adjustment, not a query-path multiplication. Adding a per-record float to a graph database that did not reserve the slot at schema design time means a full table rewrite. Idempotent batched feedback updates require the OCC commit path; a database without this primitive cannot deliver them at scale.

---

## 4. Decision lineage as first-class data

Decisions are not text in audit logs. They are typed vertices with a strict schema and four typed edge classes (`DECIDED_BY` to a Person, `INFORMED_BY` to a list of Fact and Episode RIDs, `APPLIED_POLICY` to a versioned Policy, `AFFECTED` to changed entities). The vertex carries the same bitemporal columns as facts, so a decision can be superseded just like an attribute.

**Implementation requirements.**

- A `Decision` vertex type with strict schema enforcement (decision_type enum, justification mandatory if exception=true, etc.).
- The four typed edges with cardinality and direction enforced.
- A composite index on `(decision_type, decided_at desc, expired_at IS NULL)` to enable time-range audit queries in milliseconds.
- A pipeline step that recognizes decision content during episode ingestion (approval emails, formal policy applications, system-recorded approvals) and emits the typed `Decision` record rather than a generic Fact.
- Bitemporal applied to decisions, with separate cycles for "when the decision was made" versus "when we recorded it" versus "when it was superseded."

**Why retrofitting fails.**

A graph database that lets you create `Decision` as a free-form node type does not enforce the schema invariants. A document database with decision records does not have the typed edges to Policy and to inputs, so lineage queries become full-document scans. The bitemporal-on-decisions requirement (Section 2) compounds the difficulty.

---

## 5. Versioned content-addressed graph snapshots

A Context Core is an immutable msgpack archive containing the entire graph state at a logical point in time: entities, relationships, facts, embeddings, ontology, retrieval policies, feedback weights, identity-graph edges. Identified by SHA-256 of the archive bytes. Build, test, promote, rollback as atomic operations.

**Implementation requirements.**

- A consistent snapshot algorithm: open a transaction in REPEATABLE_READ isolation, stream the rows of every primitive type, record the WAL high-water mark.
- Per-stream compression (LZ4 frame) for archive blobs so partial reads (e.g., a Diff that only needs entities) do not decompress irrelevant streams.
- Content addressing: SHA-256 over the assembled archive bytes, with the archive stored at a path derived from the hash. Identical snapshots produce identical hashes; cheap deduplication.
- A staging-database mechanism for promoting a core: load the archive into a side-database, validate, atomically swap the database pointer in the connection-routing layer (zero downtime) — or live-swap (minutes of downtime, simpler).
- A diff algorithm that walks the per-primitive streams of two cores in canonical order, detecting adds, removes, modifies, and producing a structured diff document that is itself versioned.

**Why retrofitting fails.**

Versioning a database snapshot means versioning the entanglement of graph topology, embeddings, indexes, and feedback weights. Most graph databases provide schema migrations but not operational-state snapshots. Bolt-on snapshots over a graph + vector store are inconsistent because the two stores commit independently. Content addressing requires deterministic serialization; deterministic serialization requires control of the engine's internal record encoding. The combination is not assemblable from external libraries.

---

## 6. Schema-aware pre-pipeline mapping

Before any ingestion runs, a schema introspector reads the source DDL, a data profiler samples actual values, and a business-logic ingester parses the customer's existing dbt manifest, LookML, MetricFlow YAML, SQL views, and stored procedures. A seven-pass inference engine produces a candidate mapping into ContextD primitives, surfaces it in a three-pane review UI, and saves the approved mapping as a versioned msgpack artifact. The 10-step ingestion pipeline reads the mapping at runtime; structured records take a deterministic path, free-text fields take an LLM-extraction path.

**Implementation requirements.**

- Multi-format business-logic parsers: dbt manifest.json + sources.yml + schema.yml; LookML view/explore/measure files; MetricFlow / Cube semantic-layer YAML; SQL views and stored procedures via a SQL AST library; Tableau and Power BI calculated fields; plain-language metric definitions via LLM-assisted parsing.
- A data profiler computing HyperLogLog cardinality, Count-Min Sketch top-K, regex pattern fits, PII heuristics, and cross-column mutual information.
- An inference engine running seven passes (table → entity-type, FK → relationship-type, junction-table detection, column → fact-predicate, time-series / audit-table recognition, derived-metric translation, confidence scoring) and producing a candidate mapping with per-inference confidence and reasoning trail.
- A three-pane review UI (source schema | proposed mapping | graph preview) with inline edit, bulk operations, validation panel, sample-data trace, smoke-test queries, and version diff.
- A content-addressed mapping artifact (msgpack + SHA-256) that compiles to an in-memory routing table at the pipeline's runtime.
- A bridge into the ingestion pipeline that routes each row to deterministic-extraction or LLM-extraction based on the routing table.

**Why retrofitting fails.**

Existing players own one or two of the requirements but never all of them. ETL tools own ingestion but not the graph schema or curation UX. Data catalogs own metadata but not the ingestion pipeline. Graph databases own the storage but not the multi-format business-logic parser. Building a parser that handles seven business-logic formats is a multi-quarter engineering investment by itself; combining it with a graph-aware curation UI and a runtime bridge into the ingestion pipeline is what makes the module a productized capability rather than a script.

The economic effect is concrete: when the customer's analyst team has already encoded business logic in semantic-layer formats, the deterministic-extraction path drops LLM extraction cost by 60–80% on structured sources because most rows do not need LLM inference at all.

---

## 7. Cross-source identity stitching as a productized module

When the same person appears across sources without a shared identifier — a CRM contact ID, an email address in headers, a chat-platform user ID, a ticketing-system requester ID, a code-host author handle, a directory-service key, plus free-text mentions in email bodies — they collapse into one canonical entity with confidence-weighted source-of-truth edges and a complete audit trail.

**Implementation requirements.**

- A six-stage probabilistic pipeline: vector + LSH + learned blocking; Fellegi-Sunter probabilistic record linkage with EM-learned m and u probabilities; cross-encoder pairwise matching with per-domain fine-tuning; cross-document coreference resolution (CDCR) for free-text mentions; Probabilistic Soft Logic transitive closure on a bitemporal Identity Graph; active-learning queue with LLM adjudication for the residual ambiguous cases.
- An Identity Graph artifact stored in the substrate as canonical-entity vertices linked to source-record-IDs by confidence-weighted edges; bitemporal annotations on every link.
- A vector index for blocking (the same HNSW used for retrieval) with bitmap pre-filters for type-scoped blocking.
- A neural matching model server (in-process or out-of-process) with per-entity-type fine-tuned cross-encoders and a batching layer at thousands of pair-comparisons per second.
- A coreference + named-entity-recognition stack handling free-text mentions; cross-document mention alignment.
- A constraint store and reconciliation pass for transitive closure; conflict detection on contradictory non-match assertions.
- A review surface (active-learning queue, conflict queue, identity-graph explorer) with bulk operations and label-feedback into the model fine-tuning loop.
- Per-entity-type pre-tuned configurations bundling cross-encoder weights, attribute schemas, NER model selection, and decision thresholds.

**Why retrofitting fails.**

Productizing cross-source resolution requires simultaneous ownership of multi-source ingestion, vector indexing for blocking, fine-tuneable neural matching with labeled per-domain training data, a coreference + NER stack for unstructured text, a probabilistic-soft-logic engine for constraint propagation, bitemporal storage for the resulting Identity Graph, and an active-learning review surface. Customer-data-platform vendors own marketing-focused identity stitching but neither the graph schema nor the unstructured-text coreference. Data catalogs own metadata. Open-source ER libraries are libraries — no Identity Graph, no review queue, no integration with a transactional graph store. Each component is a multi-quarter engineering investment in isolation; combining them into one module is the moat.

---

## 8. Provenance on every element

Every entity, relationship, fact, and decision row carries dictionary-encoded `source_pipeline`, `source_task`, `extraction_method`, and `source_episode_id` metadata (~16 bytes per record after string-id compression). A reverse index on `source_episode_id` answers "every primitive derived from this episode" in milliseconds.

**Implementation requirements.**

- Schema reservation of the four provenance fields on every primitive type.
- A dictionary component (string-to-id map) for source-pipeline names and source-task identifiers, reducing the on-record overhead from ~70 bytes raw to ~16 bytes compressed.
- A pipeline that stamps every emitted record with the active provenance values; no implicit defaults that would make audit trails ambiguous.
- An LSM tree index on `source_episode_id → list of derived RIDs` for reverse-traversal queries.
- Bitemporal-aware provenance: when a fact is superseded, the new fact carries its own provenance pointing to the new originating episode; the old fact's provenance is preserved unchanged.

**Why retrofitting fails.**

Adding mandatory provenance fields to an existing graph database is a full data-layer rewrite. Per-record metadata that compresses to ~16 bytes requires a global string dictionary; ad-hoc metadata stored as document fields balloons to ~70 bytes per record and dominates storage at scale.

---

## 9. Hybrid retrieval composability under one engine

Three search methods (BM25 keyword search, cosine vector search, BFS graph traversal) run in parallel under a single transaction context, share a consistent snapshot, and return scored results to a configurable reranker layer. Five reranker strategies (RRF, MMR, cross-encoder, node-distance, episode-mentions) compose with the three methods; pre-built recipes make hybrid retrieval one configuration argument.

**Implementation requirements.**

- All three search primitives implemented inside the same engine, sharing the page cache and transaction manager.
- An async fan-out primitive that runs the three searches concurrently and merges results without serializing through application code.
- A composable reranker interface: each reranker is a function from scored result lists to a ranked output list, with shared utilities (cached embeddings, RID bitmaps).
- A per-query configuration channel that lets a client select methods, rerankers, and parameters per call.

**Why retrofitting fails.**

Vector-only databases with BM25 hybrid search lack the graph engine. Graph-only databases with full-text search lack a native HNSW vector index. SQL extensions that add vectors and graph have the three primitives but with weak performance characteristics on each. Cross-process hybrid search adds latency and breaks transaction consistency. Composability requires the three primitives in the same engine.

---

## 10. Wire-protocol polyglot

A single instance speaks multiple wire protocols simultaneously, all terminating at the same internal command-execution interface. Per-protocol session state (transaction context, prepared statements, pubsub subscriptions) is managed independently.

**Implementation requirements.**

- A unified internal `execute(database, query, params, transaction_context, security_user) → ResultSet` interface that every protocol terminates at.
- Per-protocol listener modules with their native framing, serialization, and authentication flows.
- Async non-blocking I/O on a NIO-style selector, not blocking polling — polling adds a latency floor equal to the polling interval.
- Per-protocol session state isolation: a session in one protocol does not share state with a session in another even on the same database.

**Why retrofitting fails.**

A database with one native protocol can add a second via a translation gateway, but the gateway adds a hop and serializes protocol-specific session state through application memory. Multiple native protocols sharing one engine require each to be implemented as a first-class listener with its own auth flow, framing, and session model — and each routing into the same internal interface. This is a substrate-level architectural commitment.

---

## 11. Replicated state with log-typed entries

Replication uses a Raft consensus protocol with five state-machine entry types (transaction WAL deltas, schema DDL, database install, database drop, security/RBAC changes). Page-version guards make every entry idempotent on replay; followers can apply the same entry twice and converge to the same state.

**Implementation requirements.**

- A state machine that bridges the Raft log to the storage layer, decoding each entry type and applying the corresponding storage operation.
- Page-version guards in the apply path: if `entry.page_version <= current_version_of(page)`, skip the entry as already applied.
- Snapshot install for catch-up: when a follower's log is too far behind, stream the entire database snapshot from the leader and atomically swap into place.
- Watchdog logic for crash recovery: on startup, complete any partial snapshot installs (or roll them back), and resume from the persisted last-applied index.
- Quorum policies (majority or all) selectable per-deployment.

**Why retrofitting fails.**

Adding consensus replication to an existing database that did not design page-version OCC into its commit path means race conditions on replay. Snapshot install requires deterministic database serialization — the same primitive used for Context Cores. Five log-entry types versus one means five separate apply-paths and five idempotency guards, each a structural commitment in the schema and the storage engine.

---

## 12. Permissive-license substrate

The substrate is genuinely Apache 2.0. The intelligence layer on top is Apache 2.0 / MIT in the open-core. Customers can embed, fork, modify, and redistribute without legal conversation — no SSPL, Commons Clause, or business-source-license entanglement.

**Implementation requirements.**

- A real Apache-2.0 substrate, not relicensed or copyleft-dependent software.
- Every transitive dependency audited for license compatibility; any non-permissive dependency vendored or replaced.
- A clean trademark and IP policy that lets the open-source distribution stand on its own.

**Why retrofitting fails.**

A database on a non-permissive substrate can rebrand the wrapper but cannot change the underlying license. The ecosystem effects of Apache 2.0 (every solo developer, every internal tool, every embedded scenario unblocked) require a permissive substrate from the start.

---

## How these capabilities compose

Each section above describes a single distinguishing capability. The system's overall defensibility comes from the combination — every customer that integrates ContextD ends up with all twelve simultaneously. Switching costs compound: a tenant migrating away loses the Identity Graph, the bitemporal change history, the feedback-weighted retrieval state, the Forge Mappings, the Context Cores, and the audit log all at once. Rebuilding any one of these on a competing system is months of engineering; rebuilding all twelve is years.

The capabilities also feed each other. Bitemporal storage makes the Identity Graph audit-grade (every link is timestamped). Feedback weights make hybrid retrieval continuously self-improving. Decision lineage requires bitemporal and provenance. Context Cores require multi-model ACID and content-addressed serialization. Wire-protocol polyglot makes embedded mode realistic. Permissive licensing makes the whole stack distributable. Each capability is hard to retrofit; the combination is the architectural moat.

---

*Continue to `12-use-cases.md` for concrete query and ingestion scenarios that exercise these capabilities, or `05-contextd-native-db-implementation.md` for engine-level depth on how each is implemented.*
