# 05 — ContextD-Native Database Implementation

> **What this file is.** The engineering deep-dive on **how** ContextD's features are implemented at the substrate level. Files 04-15 describe the *shape* of each feature (schema, API, UX, moat). This file describes the *internals* — the data structures, algorithms, page formats, locking protocols, and crash-recovery techniques required to ship each feature reliably at enterprise scale.
>
> **Style.** No code; pseudocode where the shape of an algorithm matters. Technical terminology grounded in the database-engineering literature. Each section starts with the user-facing ContextD feature, then enumerates the implementation techniques that make it work.

---

## Table of contents

1. [Storage engine fundamentals](#1-storage-engine-fundamentals)
2. [Multi-model unification at one engine](#2-multi-model-unification-at-one-engine)
3. [Two-phase commit transactions with optimistic concurrency](#3-two-phase-commit-transactions-with-optimistic-concurrency)
4. [Write-Ahead Log and durability](#4-write-ahead-log-and-durability)
5. [Bitemporal storage at scale](#5-bitemporal-storage-at-scale)
6. [Provenance encoding](#6-provenance-encoding)
7. [Decision lineage as first-class data](#7-decision-lineage-as-first-class-data)
8. [Audit log](#8-audit-log)
9. [RBAC at the storage layer](#9-rbac-at-the-storage-layer)
10. [Multi-tenancy](#10-multi-tenancy)
11. [Graph engine internals](#11-graph-engine-internals)
12. [Vector index internals (HNSW + Product Quantization)](#12-vector-index-internals-hnsw--product-quantization)
13. [Full-text index internals](#13-full-text-index-internals)
14. [Time-series engine for change tracking](#14-time-series-engine-for-change-tracking)
15. [Context Forge artifact internals](#15-context-forge-artifact-internals)
16. [Context Resolver and Identity Graph internals](#16-context-resolver-and-identity-graph-internals)
17. [Context Cores (versioning) internals](#17-context-cores-versioning-internals)
18. [EMA feedback engine internals](#18-ema-feedback-engine-internals)
19. [Hybrid retrieval coordination](#19-hybrid-retrieval-coordination)
20. [Context assembly engine](#20-context-assembly-engine)
21. [Wire protocol polyglot](#21-wire-protocol-polyglot)
22. [MCP server](#22-mcp-server)
23. [Replication and high availability](#23-replication-and-high-availability)
24. [Compression and codec selection](#24-compression-and-codec-selection)
25. [Performance and scale envelope](#25-performance-and-scale-envelope)

---

## 1. Storage engine fundamentals

The substrate is page-based, not record-based. Every read and write moves through fixed-size pages held by a buffer pool, and durability is provided by a write-ahead log. The choice of page-based-with-LSM-trees-on-top sits between two extremes (append-only logs at one end, mutable B-trees at the other) and is the right one for a workload that mixes high-throughput writes (ingestion pipeline + Resolver streaming) with point-read-heavy queries (retrieval) and large compaction batches (Context Cores).

### 1.1 Page format

Every persisted file is a sequence of fixed-size pages (default 64 KiB; configurable per file type — index pages typically 256 KiB to amortize binary-search costs). Each page has a small header followed by content:

```
Page layout:
   offset 0   ─ page version (4 bytes, big-endian unsigned int)
   offset 4   ─ content size (4 bytes, content end inside the page)
   offset 8   ─ content
   ...
   offset N-1 ─ end of page
```

The version is the optimistic-concurrency sequence number. The content size lets the engine handle pages that are not fully utilized (sparse pages from in-place updates).

### 1.2 Page cache

A single global buffer pool maps `(database_id, file_id, page_number)` → cached page object. Implemented as a concurrent map with a configurable maximum-RAM quota; eviction is reactive (when memory pressure crosses a threshold, evict pages with no active references in approximately-LRU order). The pool serves both read-only views (`ImmutablePage`) and write-locked views (`MutablePage`); a single physical page can hand out either, but the engine guarantees writers and readers do not see each other through the cache during a transaction.

A separate concurrent map tracks **pending-flush** pages — pages dirty in the write set but not yet on disk — so a reader can choose between (a) reading from the buffer pool and (b) waiting for the flush to complete. This avoids stale reads after a crash.

A dedicated background flusher thread drains the dirty queue. The flusher supports per-database **suspend** (drop all dirty pages and pause flushes) which is required during operations like compaction or core promotion that need exclusive control.

### 1.3 Bucket page layout (record container)

A *bucket* is the storage unit for records of a single entity type. Each page within a bucket contains:

```
   offset 0   ─ page version (4 bytes)
   offset 4   ─ content size (4 bytes)
   offset 8   ─ recordsInPage (2 bytes — short)
   offset 10  ─ recordOffsetTable (2048 entries × 4 bytes = 8 KiB)
   offset 8202 ─ free space, then records growing from the tail
   ...
   end of page ─ first record (the table is appended forward, records are appended backward)
```

The pointer table at the head and records growing from the tail let the engine reuse arbitrary-position deletes without reorganization. The pointer table size is fixed at 2048 slots per default page; increase the page size if records are small enough that 2048 hits the limit.

Each record-pointer slot holds a position-in-page **plus** a sentinel size encoding:

| Sentinel size | Meaning |
|--------------:|---------|
| size > 0 | active record, varint-encoded length |
| 0 | deleted record (slot reusable) |
| -1 | placeholder pointer to a record relocated to another page (during update overflow) |
| -2 | first chunk of a multi-page record |
| -3 | continuation chunk of a multi-page record |
| ≤ -5 | placeholder content pointed to from another page |

When a record exceeds the available space at update time, it is moved to a new page and a placeholder is left at the original RID; subsequent reads follow the placeholder. When a record exceeds page size at all, it is split into a chunk chain.

A record's stable identifier (RID) is `(bucket_id, position)` where `position = page_number × maxRecordsInPage + slot_in_page`. The bucket_id is the file id (32-bit). Position is 64-bit. Together, every record in the substrate has a globally unique 96-bit RID; this is what relationships, indexes, the Identity Graph, and provenance metadata all point to.

### 1.4 Free-space tracking

Per bucket, a bounded open-addressing primitive integer→integer map tracks `page_id → free_space_bytes` for pages that have recently been touched. The map is bounded (default ~100 entries) so insert-heavy workloads can find a partially-full page quickly without scanning the whole bucket. Three reuse-space modes — `LOW`, `MEDIUM`, `HIGH` — trade off insert speed (always-append) versus disk efficiency (reuse first-fit slot).

### 1.5 Record encoding

Records are encoded with explicit type tags and variable-length size fields. Strings, numbers, lists, and embedded documents all have type-specific binary layouts. Variable-length integers use a compact 7-bits-per-byte encoding so common small values cost 1-2 bytes.

For the graph engine specifically, edge segments use **zigzag** encoding (maps signed integers to unsigned so negative ids don't burn high bits) plus VLQ (variable-length quantity) for the bucket-id and position fields. This brings a 96-bit RID down to typically 4-5 bytes for the in-edge / out-edge lists of a vertex. At enterprise scale (10⁸ edges), the difference between fixed 12-byte RIDs and ~5-byte VLQ-encoded RIDs is hundreds of GB of disk and memory.

---

## 2. Multi-model unification at one engine

Six data models share a single storage substrate. The unification is not bolt-on — it is built into the abstraction layer:

### 2.1 Component abstraction

Every storable construct is a `Component`. Concrete components are `Bucket` (record store), `LSMTreeIndex` (sorted index), `LSMTreeFullTextIndex` (inverted index), `LSMVectorIndex` (HNSW vector index), `TimeSeriesShard` (compressed time-series), `Dictionary` (string-to-id mapping). Each component owns one or more files (with stable file_ids), participates in the page cache the same way, registers for lock-manager file locks the same way, and writes WAL deltas the same way.

This means an ACID transaction can span any combination of components. A single commit may simultaneously:

- Append a record to an entity bucket
- Update the in-edge linked list of two graph vertices
- Insert into three LSM tree indexes (one per indexed property)
- Insert a vector embedding into the HNSW index
- Insert tokens into the full-text inverted index
- Write a per-second sample to a time-series shard
- Update a feedback weight on an entity edge
- Append an entry to the audit log

All under one `txId` with one WAL fsync. This is what makes "ACID across data models" real, and is the structural property no orchestration-over-N-databases can replicate.

### 2.2 File-level lock manager

Concurrency is controlled at file granularity. A `LockManager<int, Object>` maps file_id → lock holder; the holder is the requesting transaction context. Locks are acquired during commit-phase 1 in **deterministic order by file_id** to eliminate deadlock cycles by construction. Per-file locks are held for the duration of phase-1 only (~milliseconds) — concurrent commits to disjoint file sets proceed in parallel.

Explicit locks (`LOCK FILE x, y, z`) for cross-document multi-step transactions are supported but rarely needed.

### 2.3 Schema-aware dispatch

When an SQL/Cypher/Gremlin/Mongo query references a type, the engine routes through the schema layer to find the registered component(s): the bucket for record storage, plus any indexes on referenced properties. The query planner is the single place where the multi-model nature manifests at the user level — a `SELECT … WHERE name = ?` may use the LSM tree on `name`, while a `WHERE near(embedding, ?)` uses the HNSW index, and a `MATCH (a)-[r]->(b)` uses the graph engine. The same transaction can mix all three.

---

## 3. Two-phase commit transactions with optimistic concurrency

ContextD does **not** use lock-based pessimistic concurrency for record writes. Instead, every page carries a version counter, and conflicts are detected at commit time. This trades some retry cost (under contention) for the freedom of long, lock-free read paths during transaction execution.

### 3.1 The page-version OCC protocol

When a transaction reads a page, it remembers the page's version. On commit, the engine compares the recorded version against the latest version of the same page in the buffer pool:

```
commit_phase_1(tx):
    acquire file locks in deterministic order
    for page in tx.modified_pages:
        if page.version != current_version_of(page.page_id):
            raise ConcurrentModificationException → tx.rollback()
    build WAL buffer (txId, timestamp, page deltas)
    return phase1_result

commit_phase_2(phase1_result):
    write WAL durably (per configured flush mode)
    for page in tx.modified_pages:
        page.version += 1
        flush_or_queue_for_async_flush(page)
    update record-count deltas, fire post-commit callbacks
    release file locks
```

Each `MutablePage` tracks a `(modified_range_from, modified_range_to)` so the WAL writes only the changed bytes (the "page delta"), not the full page. For a 64-KiB page where 80 bytes changed, the WAL entry is ~120 bytes (plus headers), not 64 KiB.

### 3.2 Isolation levels

Two levels are supported. **Read Committed** (default): each statement within a transaction sees a fresh snapshot of the page cache. Cheap but allows non-repeatable reads. **Repeatable Read**: the first read of any page caches the immutable view in the transaction context; subsequent reads of the same page return the cached view, providing snapshot isolation. The cost is per-transaction memory proportional to the read set.

The engine does not implement Serializable; cross-statement serializability for the application is achieved via explicit locking when required.

### 3.3 Why this works for ContextD's mix

Most ContextD transactions are write-amplification-bounded ingestions: one episode → ~5-15 entity rows, ~5-10 edges, ~3-5 facts, ~10-20 index updates, all touching disjoint pages. Conflict rates between concurrent ingestions are very low because per-source partitioning naturally segregates the working set. Retry cost is correspondingly negligible. For read paths (retrieval), the `READ_COMMITTED` snapshot is sufficient because hybrid search results are inherently approximate (RRF ranking, feedback weights).

The query layer does not need long-running serializable transactions — feedback updates are streaming idempotent EMA updates (Section 18), which by construction tolerate concurrent application via the same OCC retry loop.

---

## 4. Write-Ahead Log and durability

### 4.1 WAL record format

A committed transaction writes one record to the active WAL file:

```
   txId (8)           transaction identifier, monotonically allocated
   timestamp (8)      wall-clock when phase-2 started
   pageCount (4)      number of page-delta blocks in this record
   segmentSize (4)    total byte length of the record
   pageBlock × pageCount:
       fileId (4)
       pageNumber (4)
       deltaFrom (4)         start of the modified region within the page
       deltaTo (4)           end of the modified region (exclusive)
       currPageVersion (4)   version after this delta is applied
       currPageSize (4)      page content size after this delta
       priorBytes (deltaTo - deltaFrom)   page bytes before the change (used for undo)
       newBytes (deltaTo - deltaFrom)     page bytes after the change (used for redo)
   trailingSegmentSize (4)   echo of segmentSize for backward scanning
   magic (8)                 fixed sentinel for record-boundary detection
```

The trailing size and magic sentinel let the recovery process scan the WAL forwards or backwards and detect torn writes (a partially-written record is visible because either the trailing size or the magic mismatches).

### 4.2 Flush modes

Three durability modes per transaction:

- `NO` — write to OS buffer, do not fsync. Lowest latency, durability only across application crashes (not OS crashes).
- `YES_NO_METADATA` — fsync the WAL file's data extent only. Crash-safe across OS reboots; ~1ms additional latency on SSDs.
- `YES_FULL` — fsync data + filesystem metadata. Strongest guarantee; ~5-10ms per commit.

Most ingestion uses `NO` or `YES_NO_METADATA` (durability requirement: don't lose more than the last few seconds on crash). User-driven writes (decision approvals, RBAC changes, schema migrations) use `YES_FULL`.

### 4.3 WAL file rotation and archive

WAL files are size-bounded (64 MiB default). When the active file reaches its limit, the engine atomically rotates to a new file and the old file becomes inactive. Inactive files are kept until all their pages are flushed to data files; then the WAL files are deleted (or archived for point-in-time recovery — see Section 17.5).

A pool of pre-allocated WAL files reduces commit-time latency because allocation/zeroing happens in the background.

### 4.4 Crash recovery

On startup:

1. List all WAL files; sort by sequence number.
2. For each WAL file in order, scan records:
   - For each page block: if `currPageVersion > current_version_of(page)`, apply the delta (redo). Else skip (already applied).
3. Mark recovery complete; new WAL files start fresh.

The page-version guard makes recovery **idempotent**. A WAL block that was already applied during a previous successful flush is detected and skipped, regardless of how many times the recovery process is restarted.

### 4.5 Durability for non-page artifacts

WAL records pages. Some artifacts — Forge Mappings, Context Cores, audit log — are not paged in the same way. Their durability is handled by:

- **Atomic file rename.** Write to a temp file in the same directory; fsync; rename to final path. POSIX guarantees rename is atomic. This is how Forge Mapping versions, Context Core blobs, and sealed time-series segments are written.
- **Sealed-segment pattern.** Audit log (Section 8) and time-series sealed store (Section 14) both append to a mutable buffer until size or time threshold; then atomically seal the buffer as an immutable file via the rename trick.

---

## 5. Bitemporal storage at scale

ContextD's bitemporal claim — every fact tracks both event time and transaction time — has specific implementation costs and benefits. Implemented well, it is an indexing problem. Implemented naively, it is a write-amplification disaster.

### 5.1 Schema

Every Fact, Relationship, Entity, and Decision row carries four timestamp columns:

```
   valid_at      (timestamp, NOT NULL — when this became true in the world)
   invalid_at    (timestamp, nullable — when it stopped being true; null = current)
   created_at    (timestamp, NOT NULL — when we recorded it)
   expired_at    (timestamp, nullable — when we superseded our record; null = current)
```

A fact is *current* when `invalid_at IS NULL AND expired_at IS NULL`. A fact is *known to us as of date T* when `created_at <= T AND (expired_at IS NULL OR expired_at > T)`. A fact was *true in the world at date T* when `valid_at <= T AND (invalid_at IS NULL OR invalid_at > T)`. The four temporal query types are direct combinations.

### 5.2 Supersession is insert-not-update

When a new fact contradicts an old one (Step 7 of the ingestion pipeline), the engine **does not delete or update the old fact**. It performs:

```
on_supersession(old_fact_id, new_fact):
    in one transaction:
        UPDATE old_fact SET expired_at = now(), invalid_at = new_fact.valid_at
                       WHERE id = old_fact_id AND expired_at IS NULL
        INSERT new_fact with valid_at, created_at = now()
```

The OCC version check on the old fact's page protects against double-supersession. After the transaction commits, both rows exist. Queries for current state filter on `expired_at IS NULL`; queries for history walk the chain. Storage cost: each fact mutation creates one new row plus updates one old row → ~2× write amplification compared to in-place update. LSM compaction (Section 11) compensates by physically reorganizing closed (`expired_at IS NOT NULL`) facts into compacted pages with high pack ratio.

### 5.3 Indexing strategies

Four temporal access patterns require four index designs:

1. **Current state** (most common) — index on `(subject_entity_id, predicate, expired_at IS NULL)`. The partial-index condition lets the index serve only the current rows; the planner can short-circuit.
2. **Historical state at T** — composite index `(subject_entity_id, predicate, valid_at desc, invalid_at desc)`. Range scan from `valid_at <= T` then filter `invalid_at IS NULL OR > T`. The index key length lets the planner stop at the first matching row.
3. **Knowledge state at T** — composite index `(subject_entity_id, predicate, created_at desc, expired_at desc)`. Same range scan pattern.
4. **Audit state** (when did we learn X?) — covered by index #3 with reverse scan.

The four indexes per fact predicate are expensive (~4× write cost on every fact insert) but are essential. Compaction reorganizes them periodically to keep the index page-fill ratio above ~80%.

### 5.4 The interval-tree alternative

A purer bitemporal approach uses an interval tree (or PostgreSQL-style GIST index on tstzrange). For ContextD specifically, the four-index B-tree-on-LSM-tree approach is preferred because:

- Most queries are point-in-time, not interval-overlap.
- Workloads are write-heavy; B-tree indexes compose better with LSM compaction than interval trees.
- The composite-index range scan pattern matches existing planner expertise.

Interval-tree indexes are reserved for specific analytical queries that ask "which facts overlapped with date range X?" — a less common pattern.

### 5.5 Storage cost at 100M facts

Per-fact overhead from bitemporal columns alone: 4 × 8 bytes = 32 bytes. Across 100M facts: 3 GB of timestamp metadata. Acceptable.

Index overhead: ~64 bytes per index entry × 4 indexes × 100M = 25.6 GB of index data. Significant but bounded; LSM compaction reduces by ~30%.

### 5.6 Interaction with feedback weights

Feedback weights (Section 18) live on the same row as the fact. When a row is superseded, the new row inherits the old row's feedback weight as a starting point — preventing the EMA from being reset on every supersession. This is critical: a fact whose object value changes (say, a customer's address updates) should not lose its accumulated relevance signal.

---

## 6. Provenance encoding

Every record (entity, relationship, fact, decision, episode) carries provenance metadata so the system can answer "where did this come from" without scanning the audit log.

### 6.1 Per-record fields

```
   source_pipeline       (string, ~20 bytes — e.g., "ingestion_v3")
   source_task           (string, ~30 bytes — task instance id)
   extraction_method     (enum: deterministic | llm_extraction | forge_derived |
                          ontology_constrained | manual | structured_import)
   source_episode_id     (RID — points back to the originating Episode)
```

### 6.2 Storage encoding

The string fields are not stored as raw strings. Instead the engine uses a **dictionary** component (a global string-to-id map) to assign 4-byte ids. So the on-record overhead is ~16 bytes (two 4-byte string-ids + one enum byte + one 8-byte RID) instead of ~70 bytes raw. At 100M records, that's 1.6 GB instead of 7 GB.

### 6.3 Indexes for reverse queries

A secondary index on `source_episode_id` enables the query *"give me every entity / fact / relationship derived from episode X"* — used during audit, debugging, and Context Core diff. The index is a single LSM tree keyed by episode RID with a list of derived RIDs as value.

### 6.4 Provenance is bitemporal-aware

When a fact is superseded, the new fact carries its own provenance pointing to the new episode. The old fact's provenance is preserved unchanged. Query *"which episode introduced the fact we believed on March 15?"* returns the provenance of the row whose `(created_at, expired_at)` window contains March 15 — automatically correct via the bitemporal index.

---

## 7. Decision lineage as first-class data

Decisions are not text in audit logs. They are **typed entities** with a strict schema and dedicated indexing.

### 7.1 Vertex schema

The Decision vertex type:

```
   id (RID)
   decision_type (enum: approval | exception | selection | commitment | rejection)
   subject (string — what was decided)
   outcome (string — the decision's result)
   decided_at (timestamp)
   exception (boolean — was standard policy overridden?)
   justification (text — required if exception=true)
   confidence (float — for inference-derived decisions; 1.0 for explicit ones)
   superseded_by (nullable RID → another Decision)
   bitemporal columns (valid_at, invalid_at, created_at, expired_at)
   provenance metadata (Section 6)
```

### 7.2 Edge types

Four typed edges connect a Decision into the broader graph:

- `DECIDED_BY` → Person entity (the human or system that made the decision)
- `INFORMED_BY` → array of Fact / Episode RIDs (the evidence base)
- `APPLIED_POLICY` → Policy entity (which policy was cited; Policy is itself a versioned vertex type)
- `AFFECTED` → array of Entity RIDs (what the decision changed)

Edges are stored in the graph engine's adjacency-list segments (Section 11), so traversing a decision's lineage is O(degree) per hop with no joins.

### 7.3 Indexes

- Composite LSM index on `(decision_type, decided_at desc, expired_at IS NULL)` for time-range audit queries.
- LSM index on `decided_by` for *"all decisions made by Jordan Blake"* queries.
- LSM index on `applied_policy` for *"all decisions citing policy X"*.
- Full-text index on `subject + justification` for free-text audit search.

### 7.4 Storage cost

A typical decision row is ~300 bytes including bitemporal metadata and provenance. The four edge arrays add ~50 bytes per decision (most decisions have 2-5 inputs, 1 policy, 1-3 affected entities). Indexes ~200 bytes.

At 1M decisions per tenant per year: ~550 MB. Easily handled.

### 7.5 Auditor query performance

The audit query *"every discount approval over 15% in Q1, with approver, policy, and exception status"* (Use Case 2 in file 11) executes as:

```
   1. Index scan on (decision_type=discount, decided_at in [Q1])
       → typically 50-500 candidate rows
   2. For each: traverse DECIDED_BY edge (1 hop, O(1))
   3. For each: traverse APPLIED_POLICY edge (1 hop, O(1))
   4. Filter on outcome > "15%"
   5. Project the resulting tuple
```

End-to-end: a few milliseconds at 100K decisions per quarter. Compare with the alternative (full-text scan over emails + cross-database joins) — orders of magnitude slower and inherently incomplete.

### 7.6 Bitemporal applied to decisions

A decision can be *superseded* (overturned by a later decision) or *retracted* (we discovered the decision was based on faulty input). Both are bitemporal events. The engine treats decision supersession identically to fact supersession (Section 5.2): the old decision's `expired_at` is set, a new decision row is created. Audit queries can reconstruct *what was the active discount policy on March 15*, separately from *what we believe in retrospect*.

---

## 8. Audit log

### 8.1 Append-only segment file

The audit log is its own component, separate from the WAL. Format:

```
   per entry:
       timestamp (8)
       user_id (string-id, 4 bytes — dictionary-encoded)
       api_key_id (string-id, 4 bytes)
       action (enum: query | ingest | feedback | core_build | core_promote |
               core_rollback | rbac_change | schema_change | ...)
       resource_type (string-id)
       resource_ids (variable-length array of RIDs, VLQ-encoded)
       latency_ms (4)
       ip_address (16 — IPv6 or zero-padded IPv4)
       user_agent (string-id)
       prev_hash (32 — SHA-256 of previous entry; first entry's prev_hash is zeroes)
       hash (32 — SHA-256 of this entry's bytes excluding the hash field)
```

The hash chain makes the log **tamper-evident**: any retroactive modification of an entry would invalidate the hash chain from that point onward, which is detectable by recomputing.

### 8.2 Sealed-segment pattern

The active segment is appended in-memory + buffered to disk; on size threshold (default 64 MiB) or time threshold (default 1 hour), the segment is **sealed**:

1. Compute final segment hash (covers all entries).
2. fsync the segment file.
3. Atomically rename from `audit.<seq>.active` to `audit.<seq>.sealed`.

Sealed segments are immutable and are the durability boundary for compliance reporting. Background tasks may compress or move sealed segments to cold storage (S3-style object store) per retention policy.

### 8.3 Indexing

A separate LSM tree index is built over sealed segments, keyed on `(timestamp, user_id, action)`. This is the index that answers *"every action user X took between dates Y and Z"* in milliseconds even when the audit corpus is hundreds of GB. The index is rebuilt incrementally as new segments are sealed; the active (mutable) segment is queried by linear scan if needed (typically tens of MB).

### 8.4 Retention

Per-tenant retention policy: 1 year (default), 7 years (enterprise tier), or unlimited. Background "audit-reaper" task scans sealed segments older than the retention bound and either deletes them or moves them to cold storage. The hash chain is preserved across reaper events because each segment's first entry references the previous sealed segment's hash.

### 8.5 Why a separate log, not the WAL?

The WAL is page-delta-oriented and rewritten on commit success. The audit log needs:

- Durability independent of transaction outcome (audit even on rollback).
- Hash-chained append-only semantics.
- Different retention timeline (years, not minutes).
- Different access pattern (analytical scan, not point recovery).

Same write-once principles, completely different requirements. So they are separate components sharing the same `Component` abstraction.

---

## 9. RBAC at the storage layer

Access control is not application-level filtering. It is enforced inside the storage engine, so a Cypher / SQL / Mongo / Redis client connected via any wire protocol receives the same isolation guarantees with no additional code.

### 9.1 Per-database user object

Every connection is associated with a `SecurityDatabaseUser` object. The user holds:

```
   userName
   groups (array of string)
   fileAccessMap (boolean[fileId][access_type])  # per-file permission lookup
   databaseAccessMap (boolean[database_action])  # database-level permissions
   resultSetLimit (long, -1 if unlimited)
   readTimeout (long, -1 if unlimited)
```

The `fileAccessMap` is a two-dimensional bit-array indexed by `(fileId, access_type_ordinal)`. Access types are `CREATE_RECORD`, `READ_RECORD`, `UPDATE_RECORD`, `DELETE_RECORD`. Database-level actions are `UPDATE_SECURITY`, `UPDATE_SCHEMA`, `UPDATE_DATABASE_SETTINGS`.

### 9.2 Permission check at every record op

Every call into a bucket (`createRecord`, `updateRecord`, `getRecord`, `deleteRecord`) starts with:

```
   bucket.createRecord(record, ...):
       database.checkPermissionsOnFile(fileId, ACCESS.CREATE_RECORD)
           → user.requestAccessOnFile(fileId, ACCESS.CREATE_RECORD)
               → return fileAccessMap[fileId][CREATE_RECORD.ordinal()]
       if denied: throw SecurityException
       proceed with the actual write
```

The check is two array indices and one bit test — sub-microsecond on a hot path. For 1M record-ops/sec, RBAC overhead is roughly 1% of total CPU.

### 9.3 Group → file-access compilation

At user attach time (or when group membership changes), the security manager compiles the user's groups into the `fileAccessMap`:

```
   for each group in user.groups:
       group_definition = security_config.groups[group]
       for each (typeName, accessList) in group_definition.types:
           for each fileId in schema.getFilesForType(typeName):
               for each access in accessList:
                   user.fileAccessMap[fileId][access.ordinal()] = true
```

Compilation is amortized — happens once per session attach, not per query. Cached until the security config or schema changes (then invalidated and recomputed).

### 9.4 Three scoping dimensions

The RBAC matrix in `13-integration-deployment-security.md` describes three scopes — sources, entity types, tags. Implementation:

- **Source scope**: a user's group definition explicitly lists the source bucket file_ids; the compilation step grants `READ_RECORD` only on those file_ids. All other source buckets remain `false` in the access map.
- **Entity-type scope**: same mechanism, but the file_ids are entity-type buckets rather than source buckets.
- **Tag scope**: filtering on a per-record property; cannot be implemented purely at the file-access map level (because all tagged-with-X records share the same bucket as untagged records). Implementation injects a server-side filter into the query AST after parsing — the user's scope predicate is appended as `AND tags CONTAINS 'project:atlas'`.

### 9.5 Replication of security state

User and group definitions are replicated across cluster members via dedicated Raft log entries (see Section 23.3, the `SECURITY_USERS_ENTRY` type), so a node coming back from a failure has the same RBAC view as the leader.

---

## 10. Multi-tenancy

### 10.1 Database-per-tenant isolation

Each tenant gets a separate database directory. A database is the unit of: file system tree (data files, WAL, audit log), schema, page cache budget allocation, transaction id sequence, RBAC state, replication group. There is no shared mutable state between tenants at the substrate layer.

This is stronger isolation than schema-per-tenant in a shared database. Cross-tenant queries are physically impossible because there is no SQL/Cypher operator that crosses database boundaries.

### 10.2 Page cache quota

The page cache buffer pool is global at the JVM level but is partitioned with per-tenant soft quotas. The quota mechanism:

- Each tenant has a configured `max_cache_bytes`. Sum across tenants ≤ JVM heap.
- The eviction strategy prefers to evict pages from tenants that exceed their quota first.
- Within a tenant's quota, eviction is approximate-LRU.

This prevents one large tenant from starving smaller co-tenants. In practice, oversubscription is allowed (sum of quotas can exceed JVM heap), and quotas are enforced only under memory pressure.

### 10.3 Transaction manager per tenant

Each database has its own `TransactionManager` instance (active WAL files, transaction id sequence, file lock manager). This means commit-time work parallelizes naturally across tenants. A long compaction in tenant A does not block writes in tenant B.

### 10.4 Tenant context propagation

Every entry point — REST, MCP, wire-protocol session — carries a tenant id. The id is resolved to the database object once at session start and cached. All subsequent calls within the session use the cached database directly (no per-call lookup overhead).

### 10.5 Resource budgets and noisy-neighbor protection

Beyond the cache quota:

- **Concurrent query limit per tenant** (default: 32 concurrent in-flight queries). Prevents a tenant from spawning thousands of parallel queries.
- **Result-set size limit per user** (configurable via the security model — Section 9.1).
- **Read timeout per user** (configurable).
- **Ingestion rate limit per source connection** (configurable; protects the substrate from a misconfigured connector firehose).

### 10.6 Backup and restore boundaries

Backups are per-database. A tenant's full state — data files, WAL position, audit log, Forge Mappings, Context Cores — can be exported as a single archive and restored elsewhere. Cross-tenant migration is a copy-and-relabel operation, not a complex schema export.

---

## 11. Graph engine internals

The graph engine's job is to make `MATCH (a)-[r]->(b)` cheap. Two design choices dominate.

### 11.1 Adjacency-list segments per vertex per direction

Each vertex stores a linked list of *edge segments* per direction (`out` and `in`). A segment is a fixed-capacity buffer (sized to fit comfortably within one bucket page) holding (edgeRID, neighborVertexRID) pairs. When a segment fills, a new segment is allocated and the previous-pointer is updated.

```
Vertex V {
   ...vertex properties...
   out_edges:  pointer to first OutEdgeSegment
   in_edges:   pointer to first InEdgeSegment
}

OutEdgeSegment (size ~4-8 KiB):
   used_bytes (4)
   prev_segment_ptr (RID)
   entries: zigzag-VLQ-encoded sequence of (edgeRID, neighborVertexRID)
```

A traversal `MATCH (V)-[r]->(neighbor)` walks the linked list of out-segments starting from V, decoding entries inline. Per-edge cost: ~5 bytes decode + 1 bucket hop to fetch the edge record (skipped for "light" edges with no properties).

### 11.2 Why separate `_out_edges` and `_in_edges` files

Each vertex type (e.g., Customer, Account) has three associated buckets: the vertex bucket itself, an `_out_edges` bucket holding all out-segments for vertices of that type, and an `_in_edges` bucket holding all in-segments. The split:

- **Halves the I/O for unidirectional traversals.** A query that only walks out-edges loads only the out_edges bucket pages. With combined storage, each vertex page would carry both directions and waste 50% of the I/O budget on unused edges.
- **Allows independent compaction.** Out-edges and in-edges have different write rates (out-edges grow fastest at the source vertex of a new edge; in-edges grow fastest at the target). Independent files mean independent compaction schedules.
- **Localizes lock scope.** A bulk-import of edges all originating from one vertex only locks the out_edges file for that vertex's pages, not the symmetric in_edges file (which is locked separately, for a different range of pages).

### 11.3 Encoding of edge entries

The naive encoding of an entry is 12 bytes: two 96-bit RIDs. The optimized encoding uses zigzag mapping (signed → unsigned, common-small-values dominate the encoded range) plus VLQ:

```
   bucket_id is 4 bytes raw, but most graphs use < 65 bucket types →
       4 bytes naively becomes 1 byte VLQ
   position is 8 bytes raw, but typical graphs have positions < 2^28 →
       8 bytes naively becomes 4 bytes VLQ
   total per entry: ~5-10 bytes (vs 24 bytes naive)
```

At 1B edges, the per-edge savings (~14 bytes) translates to ~14 GB of disk. Practically meaningful at enterprise scale.

### 11.4 Bulk-load fast path

The naive insert-edge path constructs a Java `RID` object, allocates a temp Binary buffer, writes the encoded bytes, copies into the segment. For a 100M-row import, this is GC-heavy.

The fast path (`addAtEndDirect`) takes raw `(int bucket_id, long position, int neighbor_bucket, long neighbor_position)` primitives and inlines the zigzag + VLQ encoding directly into the segment buffer with no intermediate object allocation. For batch inserts (`addManyAtEndDirect`), the segment's `used_bytes` field is read once, all entries are written in a tight loop, then `used_bytes` is updated once. Throughput: ~5M edges/sec on a modern CPU, dominated by buffer-write bandwidth.

### 11.5 Light edges

An edge with no properties (only a type and the two endpoints) does not need a separate edge record. The engine optimizes by storing only the entry in both the out-segment and in-segment, with the edge type encoded in the segment header. Reading such an edge constructs a "light edge" object on the fly. At enterprise scale where most relationships have no properties, this halves the storage and traversal cost.

### 11.6 Lock contention and the dual-format graph

The benchmark report (file 08) flagged a substrate-level concern: graph 1-hop traversal saturates at 4 threads due to adjacency-list page locks. Two responses:

**Response A — analytical view.** Build a *Compressed Sparse Row* (CSR) snapshot of the graph in memory, refreshed periodically (e.g., every minute) from the live data. CSR is a contiguous array of (vertex_id, edge_offset) pointers + a contiguous array of (neighbor_id, edge_id) pairs. Traversal becomes pointer arithmetic + sequential reads — lock-free, cache-friendly, 10× faster for read-heavy workloads. The CSR view is built incrementally (only changed regions rebuild) so refresh cost stays bounded.

**Response B — sharded read replicas.** Read replicas hold the same write-side state but answer traversal queries independently. Query routing distributes requests across replicas, limiting per-replica concurrency to a level the adjacency-list segments can serve cleanly.

The two responses compose: a cluster runs N read replicas, each maintains a CSR analytical view, and queries route to the replica with the freshest view (or the one whose stale tolerance matches the query). This is the practical scaling story for graph throughput.

---

## 12. Vector index internals (HNSW + Product Quantization)

The vector index supports two operations: insert a vector for an entity, and find the *k* nearest neighbors of a query vector. Both must be fast on a 100M-vector index.

### 12.1 HNSW graph structure

Hierarchical Navigable Small World (HNSW) is a layered graph where each layer is a navigable graph approximating the nearest-neighbor relationship. Search starts at the top (sparse) layer, greedily navigates to the closest node, descends to the next layer, repeats until layer 0 (densest). Each layer's degree is bounded (typically `M = 16-64` neighbors per node).

Construction is incremental — each insert finds the closest nodes at each layer, links them, and probabilistically promotes the new node to higher layers. Construction time per insert: O(log N × M × dim).

### 12.2 Three graph states

The graph index has three operating states:

- `LOADING` — initial state at startup, no graph available, queries fall back to brute force or wait.
- `IMMUTABLE` — graph is on disk, mmap'd, optimized for searches (zero-copy reads). Inserts go to a delta buffer.
- `MUTABLE` — graph is on heap, accepting incremental inserts. Higher write latency, lower memory efficiency.

The transitions are:

- `LOADING → IMMUTABLE` on initial graph load from disk.
- `IMMUTABLE → MUTABLE` when the delta buffer reaches a threshold (the system is about to rebuild).
- `MUTABLE → IMMUTABLE` after async rebuild completes, hot-swapping the new on-disk graph.

### 12.3 Async rebuild with hot-swap

When the mutable accumulator reaches its threshold, an async rebuild thread:

1. Snapshots the current vectors + delta buffer.
2. Builds a new HNSW graph from the snapshot (CPU-bound, ~20 minutes for 10M vectors on a single machine).
3. Persists the new graph to a temp file.
4. fsync, atomic rename into place.
5. Hot-swap the in-memory graph reference.
6. Drain any inserts that arrived during the rebuild and apply them as incremental inserts to the new mutable instance.

A JVM-wide semaphore caps concurrent rebuilds across all databases (default: 1) — rebuild is memory-intensive (~3× the resident graph size during construction), and concurrent rebuilds can OOM.

A separate inactivity-rebuild timer triggers rebuild when mutations exist but haven't reached the threshold for a while. This prevents indefinite delay of accumulated changes.

### 12.4 Build state for crash recovery

A build process can be interrupted (kill, OOM, hardware fault). The build state machine handles this:

- `BUILDING` — index is being created/rebuilt. WAL is intentionally **disabled** during build because the entire index file is rewritten atomically; per-page WAL would be redundant overhead.
- `READY` — index is complete and serving queries.
- `INVALID` — a `BUILDING` was interrupted by crash; the index file is corrupt. On startup, the index refuses queries and requires a manual `REBUILD INDEX` command.

This is a reasonable trade-off: better to fail loud than serve incorrect approximate-search results.

### 12.5 Product Quantization (PQ) for compression

A 1024-dimensional float32 vector is 4 KiB. At 100M vectors, that's 400 GB of raw embeddings — too much for RAM-resident search.

Product Quantization reduces this. The vector is split into M sub-vectors (e.g., M=64); each sub-vector is quantized against a learned codebook of K codes (e.g., K=256 → 1 byte per sub-vector). The encoded vector is M bytes total. For M=64, K=256 on 1024-dim vectors: 64 bytes per encoded vector instead of 4096. **64× compression.** 100M vectors fit in 6 GB instead of 400 GB.

The quality trade-off: PQ-based distance is approximate. For ContextD's hybrid retrieval, that's fine — the cosine leg of the search is a candidate generator, and the PQ approximation typically loses < 5% recall@10 on 1024-dim embeddings. The system uses PQ as the primary search engine and falls back to exact distance on the small candidate set returned by PQ.

Codebooks (the learned quantizer) and encoded vectors are persisted in a separate file (the `pqFile`). The codebook is loaded into memory at startup; encoded vectors are mmap'd. Search is zero-disk-I/O after warmup.

### 12.6 Filtered ANN

A common query is *"find the k nearest vectors to q, but only among entities of type Customer where churn_risk > 0.5"*. Naive HNSW search ignores filters; a post-filter loses recall when the filter is selective.

The pre-filter approach: compute the bitmap of valid RIDs (using the LSM index on `entity_type` and `churn_risk`), pass the bitmap to the HNSW search, and during graph traversal skip nodes whose RID is not in the bitmap. The bitmap is a compact bit array (1 bit per RID); a 100M-RID bitmap is 12 MB. Per-search overhead: a few cache lines for bitmap lookup per visited node.

For very selective filters (< 1% of vectors match), brute-force search over the matching set may beat filtered HNSW. The planner picks based on filter selectivity estimates from index statistics.

---

## 13. Full-text index internals

Full-text BM25 search is built on the same LSM-tree primitive as range indexes, plus an external tokenizer / analyzer / stemmer pipeline.

### 13.1 Inverted index basics

An inverted index maps `term → posting list` where the posting list is the set of RIDs of records containing that term. For BM25 scoring, the posting also stores per-document term frequency and document length.

The LSM tree stores:

```
   key:    (term_string, document_RID)
   value:  (term_frequency, document_length)
```

A search for term `t` is a range scan over all keys with `term = t`. The result is the posting list with frequencies, which the BM25 scorer combines with corpus-level statistics (document count, average document length) to compute relevance.

### 13.2 Analyzer pipeline

Before indexing, text passes through:

1. **Tokenization** — split text on whitespace, punctuation, language-specific boundaries.
2. **Lowercasing** — case normalization.
3. **Stop-word filtering** — remove "the", "is", "and", etc.
4. **Stemming** — reduce "running" / "runs" / "ran" to the same stem.
5. **N-gram emission** (optional) — emit character n-grams for partial-match queries.

The result is a sequence of normalized terms. Each gets inserted into the inverted index with the document's RID and term frequency. Same pipeline runs on queries to produce term lookups.

The analyzer is pluggable per index; different fields (English text, code, customer names) get different pipelines.

### 13.3 BM25 scoring

For each query term `t` matching candidate document `d`:

```
   score(d, t) = idf(t) * tf(d, t) * (k1 + 1) / (tf(d, t) + k1 * (1 - b + b * |d| / avgdl))
   total_score(d) = Σ_t score(d, t)
```

where `idf` is the corpus-level inverse document frequency, `tf` is the term frequency in this document, `|d|` is the document length, `avgdl` is the average document length, and `k1`, `b` are tuning parameters (default k1=1.2, b=0.75).

The implementation pre-computes `idf` for each term during a corpus-statistics pass; it's cached and updated incrementally on document insert/delete.

### 13.4 Posting-list compression

In a busy index, a popular term's posting list is hundreds of MB. Compression is essential.

- **Frame Of Reference (FOR)** — store the minimum RID, then deltas relative to that minimum. Combined with bit packing (e.g., 12 bits per delta if all deltas fit in 4096), this reduces posting lists by 5-10×.
- **PForDelta** — exception-encoded variant that handles outliers (delta > 4095) without falling back to full 64-bit encoding for the whole block.

The substrate uses LSM-tree pages as the natural unit, applying compression per page.

### 13.5 Index update on supersession

When a fact is superseded (Section 5.2), the inverted index entries pointing to the old fact must be removed (or marked deleted). The substrate uses a **tombstone** pattern: instead of physically deleting from the index, insert a tombstone record with a special sentinel RID. Compaction periodically merges tombstones with the underlying data, physically removing both. This avoids high write amplification on deletes.

For ContextD's bitemporal model, *both* the new and old fact are kept in the index (current and historical). Queries that filter `expired_at IS NULL` use the LSM tree's bitemporal index to filter at retrieval time, not the FTS layer. This means the FTS index covers all versions; the bitemporal filter narrows to current.

---

## 14. Time-series engine for change tracking

Time-series storage is a specialized component used internally for telemetry (query latencies, ingestion rates, feedback histograms) and for tracking per-entity attribute changes (every `valid_at`/`invalid_at` transition is recordable as a sample).

### 14.1 Sharded design

A time-series type is split into N shards. Writes are distributed round-robin to balance load. Each shard owns:

- A **mutable bucket** — a paginated component holding row-oriented samples.
- A **sealed store** — a sequence of sealed-segment files holding compressed samples.
- A compaction lock (read-write) and an append lock.

Queries fan out across all shards and merge-sort results by timestamp. The merge is an N-way priority-queue merge of N pre-sorted iterators.

### 14.2 Mutable bucket layout

```
   header page:
      magic ("TSBC", 4 bytes)
      formatVersion (1)
      columnCount (2 bytes)
      sampleCount (8 bytes)
      minTimestamp (8 bytes)
      maxTimestamp (8 bytes)
      compactionInProgress (1 byte)
      compactionWatermark (8 bytes — sealed-store offset)
      activeDataPageCount (4 bytes)

   data pages:
      sampleCountInPage (2 bytes — read as unsigned short)
      minTsInPage (8 bytes)
      maxTsInPage (8 bytes)
      rows: fixed-size [timestamp(8) | col1 | col2 | ...] each
```

Row-oriented mutable storage gives ACID guarantees (each commit writes whole pages, page-version OCC catches conflicts) and fast appends. Read patterns over recent samples are fine on this layout because temporal locality means recent pages are cached.

### 14.3 Compaction to sealed store

When the mutable bucket reaches a size threshold or time threshold, compaction kicks in:

1. Acquire compaction lock (write side).
2. Read samples from mutable bucket sequentially.
3. Compress columns:
   - Timestamps with **delta-of-delta** encoding (Section 24.1)
   - Float values with **Gorilla XOR** encoding (Section 24.2)
   - Integer values with **Simple8b**
   - Low-cardinality strings (TAG columns) with **dictionary** encoding
4. Write compressed block to a `.tmp` file.
5. fsync, atomically rename to `.sealed`.
6. Update mutable bucket header: increment `compactionWatermark`, decrement `sampleCount`.
7. Truncate mutable bucket pages that have been sealed.
8. Release compaction lock.

The `.tmp` + atomic rename ensures crash safety: a crash between steps 4 and 5 leaves the `.tmp` file and the mutable bucket unchanged; recovery deletes the temp file. A crash between steps 5 and 6 leaves a sealed file and the original mutable data; recovery sees the orphan sealed file, checks its watermark against the bucket header, and either commits or rolls back the truncate.

### 14.4 Block structure

A sealed block holds 64K samples by default. Per-block header records the timestamp range, column codecs used, compression dictionary references. Range queries skip blocks whose timestamp range doesn't intersect the query.

### 14.5 SIMD-accelerated aggregation

Aggregation queries (e.g., `AVG(latency_ms) WHERE timestamp BETWEEN ...`) operate on decoded sample arrays. The engine uses Java 21 Vector API (or platform-native SIMD intrinsics) to process batches of 256 / 512 samples per instruction. For numeric aggregations on typical hardware, this is 4-8× faster than scalar code.

### 14.6 Integration with ContextD bitemporal

Every fact mutation (Section 5.2) emits a time-series sample to a per-entity per-predicate stream. This means *the bitemporal change history of any attribute is also queryable as a time-series* — useful for change-rate analytics ("how often does Acme's health_status change?") and for retrieval that wants to weight recent changes more heavily.

---

## 15. Context Forge artifact internals

The Forge Mapping is a versioned, content-addressed configuration artifact (not a normal record).

### 15.1 Serialization format

The Mapping is serialized as **msgpack** — a binary, schema-less, length-prefixed format. Reasons:

- 30-50% smaller than JSON for the same data.
- 2-10× faster to encode/decode.
- Schema-evolution friendly (added fields are silently ignored by old readers).
- Widely supported (Python, JS, Java, Rust libraries are all production-grade).

The schema is versioned in the artifact itself:

```
   FORGE_MAPPING_V<N>:
      schema_version (1 byte)
      created_at (8 bytes)
      created_by (string)
      source_descriptor (msgpack object — connection metadata)
      ontology_baseline (string — name of the ontology used)
      entity_mappings (array of EntityMapping objects)
      relationship_mappings (array of RelationshipMapping objects)
      fact_mappings (array of FactMapping objects)
      derived_fact_mappings (array of DerivedFactMapping objects with formula DAG)
      episode_mappings (array of EpisodeMapping objects)
      validation_warnings (array of strings)
      reviewer_overrides (array of ReviewerOverride objects)
      metadata (msgpack object — open extension)
```

### 15.2 Content-addressing

After serialization, the SHA-256 of the byte stream is computed and used as the artifact's primary identifier. The artifact is stored at a path derived from the hash (e.g., `forge_mappings/<source_id>/<sha256_first_2>/<sha256_rest>.msgpack`).

This gives:

- **Immutability by construction.** The artifact's identity is its contents. Any change produces a different hash, hence a different identifier.
- **Cheap deduplication.** If two sources produce identical mappings (uncommon but possible — e.g., identical Forge Profile applied), they share storage.
- **Diffing-friendly.** Comparing two versions is comparing two byte streams. Structural diff operates on the decoded object trees.

### 15.3 Versioning per source

A separate metadata table maps `(tenant_id, source_id) → list of (version, sha256, applied_at, applied_by)`. The active version is the most recent `applied_at`; rollback rewrites the active pointer to a previous version. The artifact files themselves are never deleted — they form the version history.

### 15.4 Loading and the in-memory routing table

When a source's mapping becomes active, the engine loads the msgpack artifact, parses it, and compiles it into a fast-access in-memory routing table:

```
   RoutingTable:
       table_to_entity_type:    map[source_table_name] → entity_type_id
       table_pk_columns:         map[source_table_name] → list of pk column names
       fk_to_relationship:       map[(source_table, fk_column)] → (relationship_type_id, direction, cardinality)
       junction_tables:          set of source_table_names mapped as junctions
       column_to_fact_predicate: map[(source_table, column)] → (predicate_id, value_type, pii_flag)
       derived_facts_dag:        DAG of DerivedFactSpec with dependencies and formula AST
       episode_tables:           set of source_table_names mapped as Episodes with timestamp column ref
```

Routing-table lookups are O(1) hash table. The pipeline (Step 3 — Extract Nodes; Step 6 — Extract Edges) consults this table per row to decide whether to use deterministic extraction or fall back to LLM extraction for unstructured columns.

### 15.5 Bridge to the ingestion pipeline

The pipeline integrates the Forge Mapping at two points:

- **Pre-extraction**, Step 3: for each row, the routing table maps `(source_table, columns) → (entity_type, fact_predicates, derived_fact_specs)`. Deterministic mapping produces records directly. Non-mapped (free-text) columns fall through to the LLM extractor.
- **Pre-edge-extraction**, Step 6: for each FK column with a mapping, the relationship type is known; the edge is created directly without LLM. For cross-record relationships not pre-mapped, the LLM extractor runs on the surrounding context.

The atomic transactional commit at Step 9 writes all the deterministic + LLM results together — same WAL, same OCC, same provenance-stamped records.

### 15.6 Derived-fact computation pass

After the entity / fact / edge writes commit, a separate post-commit phase walks the `derived_facts_dag` in topological order and computes derived facts:

```
   for each DerivedFactSpec in topological_order(dag):
       inputs = resolve dependencies from just-committed records
       value = evaluate formula on inputs
       insert Fact row with (subject, predicate, object=value,
                              extraction_method=forge_derived,
                              source_pipeline=<spec.id>,
                              ... bitemporal columns inherited from base inputs)
```

Formula AST evaluation supports arithmetic, conditional (CASE), aggregations over recent samples (AVG over last N samples), and configurable null handling (`NULLIF`, `COALESCE`).

The post-commit derived-fact pass is itself transactional: a single transaction wraps all derived facts for one ingestion event. If a formula errors (divide-by-zero, missing dependency), the derived fact is skipped with a warning logged to the audit log; the originating ingestion does not roll back.

---

## 16. Context Resolver and Identity Graph internals

### 16.1 Identity Graph storage

The Identity Graph is stored in the substrate using regular vertex / edge primitives:

- `CanonicalEntity` vertex — one per resolved person / organization / asset.
- `Identifier` edge — connects a `CanonicalEntity` to a source-record-RID with confidence and evidence.

Edge schema:

```
   source_canonical_entity → target_source_record (RID)
   source (string-id, dictionary-encoded — "salesforce", "gmail", ...)
   source_id (string — the source's native id)
   confidence (float, 0.0-1.0)
   evidence (string-id — encoded reason: "deterministic_pk", "fellegi_sunter", ...)
   stage (enum — which Resolver stage produced this link)
   bitemporal columns (valid_at, invalid_at, created_at, expired_at)
```

The vertex carries the `attribute_consensus` — reconciled attribute values across sources, each tagged with its source-of-truth.

### 16.2 HNSW for Stage A blocking

Blocking (Section 4.2 of file 06) uses the existing HNSW index built on the entity-name-embedding column of `CanonicalEntity`. Per-record blocking lookup: top-50 nearest neighbors by cosine, returned as candidate set. Cost: ~10 ms at 100M canonical entities (per Section 12).

### 16.3 LSH MinHash for textual blocking

A complementary blocking layer uses 3-gram MinHash over entity names (and other short textual attributes). MinHash signatures are stored as fixed-size byte arrays (32 hash functions × 4 bytes = 128 bytes per signature). Locality-Sensitive Hashing buckets signatures into bands; candidate pairs are signatures sharing at least one band.

The LSH index is itself an LSM tree keyed on `(band_id, signature_hash) → list of canonical_entity_ids`. Lookup is one range scan per band; total candidate set is the union across bands.

For ContextD, MinHash blocking complements HNSW: it catches typos and abbreviations that the embedding might miss, while HNSW catches semantic similarity (different name, same entity).

### 16.4 Cross-encoder model server

Stage C (neural pairwise matching) runs a transformer model. Two deployment options:

- **In-process model.** Load the model into the JVM via ONNX Runtime / Triton. Lowest latency. Requires careful memory management.
- **Out-of-process model server.** Run a separate process exposing a gRPC interface. The substrate batches pairs and sends them over the wire. Higher latency (typically 1-5 ms RTT) but cleaner resource isolation and easier model upgrade.

ContextD ships with the out-of-process model server as the default (better operational story for cloud deployments) with the in-process option available for embedded mode.

The batching layer collects pairs from concurrent resolution requests and dispatches batches of 32-64 pairs per RPC. A single GPU sustains ~5K pairs/sec under this batching scheme.

### 16.5 PSL constraint storage

Probabilistic Soft Logic (PSL) constraints — "if A↔B and B↔C, then A↔C with confidence A·B" — are stored as a `Constraint` vertex type with a small DSL for the constraint shape. A nightly reconciliation pass:

```
   for each canonical_entity in tenant:
       for each constraint involving this entity:
           propagate confidence
           if propagation produces a new high-confidence link: create Identifier edge
           if propagation produces a contradiction: add to conflict queue
```

This is bounded-cost (proportional to graph degree × constraint count) and runs in the background. Real-time stitching from Stages A-D doesn't wait on PSL; PSL handles second-order inferences asynchronously.

### 16.6 Soft-link mode

Low-confidence stitches (typically 0.7 < confidence < 0.85) are stored as Identifier edges with an additional `is_candidate` flag. The CanonicalEntity holds `(definite_identifiers, candidate_identifiers)` — definite identifiers are merged into the attribute_consensus, candidates are not. A candidate is promoted to definite when:

- Corroborating evidence arrives (a new source identifier with strong overlap to the candidate set).
- A reviewer in Resolver Studio approves the link.
- A PSL constraint propagation strengthens its confidence above the promotion threshold.

This avoids the worst failure mode (a wrong stitch silently merges two distinct customers) by retaining the original separation until the merge is corroborated.

### 16.7 Active-learning queue

Items requiring human review are stored in a separate `ResolverReviewItem` bucket:

```
   ResolverReviewItem:
       canonical_entity_a (RID)
       candidate_canonical_entity_b (RID)
       proposed_action (enum: merge | non_match)
       stage_C_confidence (float)
       stage_B_breakdown (map of attribute → match_weight)
       evidence (text — short explanation)
       priority (float — uncertainty score)
       status (enum: pending | reviewed_match | reviewed_non_match | dismissed)
       reviewed_at, reviewed_by (nullable)
```

A separate index on `(status=pending, priority desc)` orders the queue by uncertainty for the reviewer. Approved labels are written back to `Identifier` edges (or to `non_match` constraints in the PSL store) and feed the model fine-tuning loop.

### 16.8 Feedback into model fine-tuning

Labels accumulated in the review queue are aggregated into a fine-tuning dataset. Periodically (configurable; default nightly), a fine-tuning job:

1. Pulls all `reviewed_match` and `reviewed_non_match` items added since the last fine-tune.
2. Builds positive and negative pairs.
3. Runs supervised training on the pre-trained cross-encoder model.
4. Validates on a held-out test set.
5. If F1 improves, deploys the new model to the model server.

The fine-tuning job is resource-intensive (single-GPU, ~1-3 hours per run depending on data volume) and runs off the critical path.

---

## 17. Context Cores (versioning) internals

A Context Core is an immutable, content-addressed snapshot of a graph state.

### 17.1 Snapshot algorithm

The challenge: snapshot a transactional database without halting writes. Approach:

1. **Open a snapshot transaction in REPEATABLE_READ isolation.** All reads see a consistent point-in-time view.
2. **Record the WAL position at snapshot start.** Call this `WAL_HWM`.
3. **Stream all rows to the serializer.** The transaction's snapshot view ensures consistency.
4. **At end-of-stream, record the tx start timestamp** as the core's logical-time identifier.
5. **WAL replay catch-up** (optional): if the snapshot was taken with `READ_COMMITTED` (faster but inconsistent), replay WAL from `WAL_HWM` forward until the database state matches the desired logical time.

Most snapshots use `REPEATABLE_READ` for consistency. WAL catch-up is used only for incremental snapshots.

### 17.2 Serialization

The core is a single msgpack archive containing:

```
   CORE_V<N>:
      schema_version (1 byte)
      built_at (8 bytes)
      built_by (string)
      tenant_id (string)
      logical_time (8 bytes — the snapshot's WAL position / tx timestamp)
      forge_mapping_refs (list of sha256 — the active mappings at snapshot time)
      ontology_ref (sha256 — the active ontology)
      entities (compressed stream of msgpack-packed Entity rows)
      relationships (compressed stream)
      facts (compressed stream)
      decisions (compressed stream)
      episodes (compressed stream — content-only or by-reference based on retention policy)
      sagas (compressed stream)
      communities (compressed stream)
      embeddings (compressed stream of (RID, float[]) pairs)
      indexes (compressed stream of LSM tree dumps for relevant indexes)
      feedback_weights (compressed stream of (RID, weight) pairs)
      identity_graph (compressed stream of CanonicalEntity + Identifier edges)
      provenance_index (compressed stream)
      checksum (sha256)
```

Streams are compressed individually so partial reads (e.g., Diff just needs entities) avoid decompressing irrelevant parts. The compression codec is LZ4 for archive blobs (decode speed > storage size for cores) — a typical 10M-entity core compresses ~3:1 with LZ4.

### 17.3 Content-addressing and dedup

The core's primary identifier is the SHA-256 of the entire archive. Cores are stored at `cores/<sha256>.msgpack.lz4`. Deduplication: if a tenant builds the same core twice (no changes between builds), the system detects the duplicate hash and skips the upload.

### 17.4 Promote and rollback

The active core for a tenant is recorded in tenant metadata as a single SHA reference. Promote = atomic update of the reference (with WAL durability). Rollback = atomic update back to the previous reference.

The data files themselves are not affected by promote/rollback. A "promotion" doesn't move data; it only changes which logical version the query path uses. The data files always reflect the latest committed state.

To actually serve queries from a promoted core, two implementation strategies:

- **Live database swap.** Stop the live database, load the core into a fresh database directory, atomically rename. Pros: simplest. Cons: minutes of downtime per promotion for large cores.
- **Side-database staging.** Load the core into a staging database alongside the live one. Run validation queries against the staging database. Atomically swap the database pointer in the connection-routing layer. Pros: zero downtime. Cons: 2× storage during the staging window, additional connection-routing complexity.

ContextD ships staging by default for cloud, live-swap for embedded.

### 17.5 Diff algorithm

Comparing two cores:

1. **Same hash → no diff.** Identical cores produce no output.
2. **Schema-version compatibility check.** Different schema versions require a translation pass.
3. **Stream-wise diff per primitive type.** Both cores' streams are sorted by canonical_id (or RID for non-canonical types). A merge-walk identifies adds, removes, modifies.
4. **For modifies, bytewise diff** of the msgpack-packed row.

The output is a structured diff document (also msgpack-packed, also content-addressed) that is itself versioned and queryable.

### 17.6 Test runner

Test queries against a core run in a sandboxed staging database:

```
   load_core_to_staging(core_sha256)
   for each test_query in test_suite:
       result = staging_database.run(test_query)
       assert result matches expected_pattern
   tear_down_staging
```

The staging database is ephemeral; the test runner cleans up after the run. Test results are stored as `CoreTestRun` records with `(core_sha256, test_suite_id, passed, failed, errors)`.

### 17.7 Retention and pruning

Cores are kept indefinitely by default. A retention policy can prune cores older than N days that are not referenced by any active branch or test run. Pruning is conservative — it does not delete a core unless the SHA is unreachable from all roots (active core, recent test runs, named branches).

---

## 18. EMA feedback engine internals

### 18.1 Per-element feedback weight

Every `Entity`, `Relationship`, and `Fact` row carries:

```
   feedback_weight (float, 0.0-1.0, default 0.5)
   feedback_count (uint32 — number of EMA updates applied)
   last_feedback_at (timestamp)
```

These three fields add 13 bytes per row.

### 18.2 Streaming EMA update

A feedback event arrives with `(session_id, query_id, score, used_entities[], used_edges[])`. Per used entity / edge, the engine computes the EMA update in a single transaction:

```
   normalized = (score - 1) / 4              # score in [1, 5] → [0.0, 1.0]
   for each rid in used_entities + used_edges:
       row = read row at rid (page-version recorded for OCC)
       new_weight = row.feedback_weight + 0.1 * (normalized - row.feedback_weight)
       row.feedback_weight = clamp(new_weight, 0.0, 1.0)
       row.feedback_count += 1
       row.last_feedback_at = now()
       write row (page-version checked at commit)
```

OCC retry handles concurrent updates to the same row. In practice, retry rate is < 1% even at 10K feedback events/sec because retrieval queries for different queries rarely target identical entity sets.

### 18.3 Idempotency

Duplicate feedback submissions are detected via a `FeedbackLog` index keyed on `(session_id, query_id)`:

```
   if FeedbackLog has entry for (session_id, query_id):
       return "already processed"
   else:
       apply EMA updates as above
       insert FeedbackLog entry
```

The two operations (EMA updates + FeedbackLog insert) run in one transaction. Either both succeed or neither does.

### 18.4 Batched-write optimization

At high feedback rates, batching reduces commit overhead. The engine accumulates feedback events for up to 500 ms or 100 events (whichever first) and applies them in one transaction:

```
   batched_apply([events]):
       deduplicate by (session_id, query_id)
       group by rid
       for each rid in groups: compute aggregate EMA (apply each event in order)
       single transaction with N row updates
```

This can reduce transaction count by 50-100× under load; the page-version OCC handles the consolidated updates as one logical change per row.

### 18.5 Cached weight in record header

For retrieval-time fast access, the page-record header for `Entity` / `Relationship` carries the `feedback_weight` directly (4 bytes). The query engine reads the weight inline with the record fetch, so applying `final_score = reranker_score × feedback_weight` adds zero extra I/O.

### 18.6 Feedback decay

A weight that hasn't been updated in months may no longer reflect current relevance. A nightly **decay pass** can apply a slow exponential decay:

```
   for each row where last_feedback_at < now() - 30_days:
       row.feedback_weight = 0.5 + (row.feedback_weight - 0.5) * decay_factor
       (where decay_factor = exp(-Δt / half_life), half_life = 90 days)
```

This is opt-in per tenant; many use cases prefer "weights are sticky" semantics, in which case decay is disabled.

---

## 19. Hybrid retrieval coordination

### 19.1 Async fan-out

A retrieval query runs three searches concurrently. Pseudocode:

```
   coroutine bm25_task = BM25_search(query_terms, top_k=20)
   coroutine cosine_task = HNSW_search(query_embedding, top_k=20)
   coroutine bfs_task = graph_BFS(seed_entities, max_depth=3, top_k=50)
   
   results = await all(bm25_task, cosine_task, bfs_task)
```

The three runs share the same transaction context (so they see a consistent snapshot of the graph). Each is parallelized internally if the underlying primitive supports parallelism (e.g., HNSW per-shard search across replicas).

### 19.2 RRF reranking

Reciprocal Rank Fusion:

```
   for each method in [bm25_results, cosine_results, bfs_results]:
       for rank, item in enumerate(method, start=1):
           rrf_score[item.rid] += 1 / (k + rank)
   
   sorted_results = sorted(rrf_score, by=score desc)
```

The constant `k` (default 60) controls how aggressively top-ranked items dominate. Implementation cost is O(N log N) where N is the total number of distinct items across the three lists.

### 19.3 Feedback-weight multiplication

After RRF, each item is multiplied by its feedback weight (read inline from the record header):

```
   for each item in rrf_sorted:
       final_score[item] = item.rrf_score * item.feedback_weight
```

O(N), no additional I/O.

### 19.4 MMR reranking (when configured)

Maximal Marginal Relevance trades relevance for diversity:

```
   selected = []
   remaining = rrf_sorted
   while len(selected) < limit and remaining:
       best = argmax over remaining:
           lambda * relevance(item, query) - (1 - lambda) * max_similarity(item, selected)
       selected.append(best)
       remaining.remove(best)
```

Cost: O(N²) in the worst case where every item is compared against every previously selected item. Mitigation: precompute item embeddings; the inner `max_similarity` is a vector op (SIMD-acceleratable).

### 19.5 Cross-encoder reranking (when configured)

For maximum quality, the top 50 RRF-ranked items can be passed to the cross-encoder model server. The model produces a relevance score per item; final ranking is by the cross-encoder score. Cost: 1-2 ms RTT per batch (50 items in one RPC).

### 19.6 Token-budget pruning

The Context Assembly stage (Section 20) takes the reranked list and packs it into the token budget. The pruner is a streaming filter:

```
   budget = max_tokens
   for each item in reranked_order:
       cost = token_count(serialize(item))
       if cost > budget: continue
       output(item)
       budget -= cost
       if budget < 100: break
```

Token counting uses a tokenizer compatible with the target LLM (default: GPT-4-class tokenizers via `tiktoken`).

---

## 20. Context assembly engine

The 7-step assembly is implemented as a stateful pipeline.

### 20.1 Stage operators

Each step is an operator over typed data:

```
   ParseIntent: NL_query → ParsedIntent { entity_refs, temporal_constraints, relationship_hints, search_filters }
   SeedSelection: ParsedIntent → SeedEntities (small list of starting RIDs)
   HybridSearch: SeedEntities + ParsedIntent → RankedResults (Section 19)
   RerankAndMerge: RankedResults → DedupedRankedResults
   ApplyFeedback: DedupedRankedResults → FeedbackWeightedResults
   BudgetPrune: FeedbackWeightedResults + token_budget → PrunedResults
   Serialize: PrunedResults → ContextBundle (typed JSON)
```

### 20.2 Priority-based budget filling

The pruner doesn't take results in pure rank order. Priority order:

1. Primary entities (always included up to budget).
2. Direct relationships between primary entities (current state only).
3. Relevant facts (current-state filter; bitemporal index on `(invalid_at IS NULL, expired_at IS NULL)`).
4. Saga summaries — short narrative blocks.
5. Decision lineage — only if `include_lineage=True`.

This guarantees the most important context is always present, even under tight budgets.

### 20.3 Output shape

The serialized output is a typed JSON document with metadata block:

```
   {
     query: ...,
     context: {
       primary_entities: [...],
       relationships: [...],
       relevant_facts: [...],
       temporal_context: { current_state: {...}, recent_changes: [...] },
       decision_history: [...],
       saga_summary: "...",
       communities: [...],
       sources: [...]
     },
     metadata: {
       tokens_used: int,
       tokens_saved_vs_chunk_rag: int,
       entities_traversed: int,
       confidence: float,
       avg_feedback_weight: float,
       search_recipe: string,
       query_latency_ms: int
     }
   }
```

The metadata block is what makes ContextD's "80% token reduction" claim verifiable per query — the agent can log `tokens_saved_vs_chunk_rag` and aggregate over time.

### 20.4 Caching

For repeated queries (same NL query in a short window), the assembled `ContextBundle` is cached at the application layer keyed on `(query_text, tenant_id, max_tokens, user_id)`. Cache TTL is short (default 60s) because the underlying graph mutates continuously. The cache is opt-in per tenant.

---

## 21. Wire protocol polyglot

Each protocol is a translation layer that terminates at the unified internal command-execution interface. The translation layers are completely separate (per-module isolation, per-protocol session state) — a Bolt session does not share state with a Postgres session even on the same connection address.

### 21.1 Unified internal interface

All protocols ultimately call:

```
   execute(database, sql_or_cypher_or_gremlin, params, transaction_context, security_user) → ResultSet
```

The dispatcher routes to the correct query engine (SQL, OpenCypher, Gremlin, or graph-internal SELECT) based on language hint. The result set is a streaming iterator of records; protocols stream records back to the client over their respective wire formats.

### 21.2 Protocol-specific listeners

Each protocol has its own network listener:

- **Bolt** — TCP socket on port 7687 (default), packstream-encoded handshake, chunked request/response framing, WebSocket fallback for browser clients.
- **PostgreSQL** — TCP socket on port 5432, extended-query protocol (Parse, Bind, Execute, Sync), portal management for cursor-based result streaming.
- **MongoDB** — TCP socket on port 27017, BSON-encoded wire messages.
- **Redis** — TCP socket on port 6379, RESP protocol (text-based, command/response).
- **gRPC** — TCP socket on port 8843, protobuf-defined service map.
- **HTTP/REST** — TCP socket on port 2480, JSON-over-HTTP with internal command dispatcher.

Each listener is independently configurable (port, TLS, auth method) and runs as a separate accept loop.

### 21.3 Per-protocol session state

A session holds:

- The authenticated `SecurityDatabaseUser` (Section 9).
- The current transaction context (or `null` if auto-commit).
- Any prepared statement / portal state (for PG-protocol cursors).
- Subscription state (for MongoDB tailable cursors, Redis pubsub).
- Authentication credentials and the authorization decision cache.

Sessions are independent; one session crashing or timing out does not affect others.

### 21.4 Async I/O

All listeners use non-blocking I/O with selector-based event loops (NIO in Java). One I/O thread can serve thousands of idle connections. Active queries are dispatched to a worker thread pool.

The naive alternative — one thread per connection — does not scale beyond a few hundred connections. The async-I/O design lets a single substrate instance accept tens of thousands of connections with bounded resource use.

### 21.5 Why a polling protocol is wrong

Polling-based protocol implementations (where the server sleeps for N ms between connection checks) add a latency floor equal to the polling interval. This is the exact bug the benchmark report flagged in the PG-protocol implementation: a 100-ms polling sleep added a 100-ms floor to every query. **Production-grade implementation uses blocking I/O on a NIO selector** — the OS wakes the thread when bytes arrive, with no polling delay.

The fix at the substrate level: replace `sleep(100)` with `channel.read()` (blocking until bytes arrive or the channel closes). This is a small, localized patch but unblocks the entire PG-protocol path.

---

## 22. MCP server

### 22.1 Two-layer tool registry

A registry maps tool names to handler functions:

```
   tools[tool_name] = {
       schema: JSONSchema,
       handler: function(args) → Result,
       authorization_check: function(user, args) → bool
   }
```

Layer 1 (substrate built-ins) registers raw DB tools: `execute_command`, `query`, `get_schema`, etc.

Layer 2 (ContextD context tools) registers semantic tools: `query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `submit_feedback`, `ingest_episode`.

When the agent connects, it sees the union of both layers (subject to RBAC scoping — Section 22.4).

### 22.2 Transport multiplexing

Three transports, all dispatching to the same registry:

- **stdio** — line-delimited JSON-RPC over stdin/stdout. Used by Claude Code / Cursor / Windsurf for local-process integration.
- **SSE** — Server-Sent Events over HTTP. Streams responses; suitable for slow agents.
- **HTTP** — JSON-RPC over HTTP POST. Stateless; suitable for serverless agent backends.

The transport layer handles framing; the dispatcher is shared.

### 22.3 JSON-RPC dispatch

A request is `{"method": tool_name, "params": {...}, "id": request_id}`. Dispatch:

```
   request → (lookup tool by name, validate params against schema, run authorization,
              execute handler, format result, send response)
```

Errors are returned as JSON-RPC error objects with structured error codes.

### 22.4 RBAC integration

The MCP server runs every tool invocation through the user's `SecurityDatabaseUser` (Section 9). A tool whose handler reads from the entity bucket triggers a `READ_RECORD` permission check on the bucket file_id. A tool that writes (`ingest_episode`) triggers `CREATE_RECORD` checks.

Tool registration declares its required permissions. The dispatcher's authorization step checks `user.can(required_permission)` before invoking the handler.

### 22.5 Streaming responses

For long-running tools (`get_context` over a large graph), the SSE transport streams partial results. The handler emits messages as it produces output; the SSE layer formats them as Server-Sent Events. Stdio transport uses newline-delimited JSON for similar streaming semantics.

---

## 23. Replication and high availability

ContextD's HA story uses Raft consensus for strong consistency.

### 23.1 Architecture

A cluster runs N nodes (typically 3 or 5). One node is the **leader**; the others are **followers**. All writes go through the leader; reads can be served by any node (with bounded staleness).

The Raft protocol guarantees:

- A single leader at any time.
- Every committed log entry is durable on a quorum of nodes.
- Every committed entry is applied in log order on every node.

### 23.2 State machine bridge

A `StateMachine` object bridges the Raft log to the substrate:

```
   apply(log_entry):
       decoded = decode(log_entry.bytes)
       case decoded.type:
           TX_ENTRY → apply WAL page deltas to local storage
           SCHEMA_ENTRY → apply DDL (file creation, schema JSON update)
           INSTALL_DATABASE_ENTRY → snapshot install (download from leader if local empty)
           DROP_DATABASE_ENTRY → drop database files
           SECURITY_USERS_ENTRY → update local security map
       update lastAppliedIndex
       persist lastAppliedIndex (so crash recovery resumes correctly)
```

Five log-entry types let the cluster replicate not only data writes but also schema migrations, RBAC changes, and snapshot installs — with the same consensus guarantees.

### 23.3 Page-version idempotency

A follower may receive the same log entry twice (e.g., during catch-up after a network partition). The `applyChanges` step compares `log_entry.page_version` against `current_version_of(page)`. If `log_entry.page_version <= current_version`, the entry is already applied; skip. This makes replay-after-restart idempotent.

### 23.4 Snapshot install

When a follower is too far behind (its log doesn't go back far enough), it requests a snapshot from the leader. The leader streams the entire database state (all data files + WAL position) over the network. The follower writes the stream to a staging directory, atomically swaps it into place, and resumes from the snapshot's WAL position.

Crash safety: if the install is interrupted, the recovery logic on next start either completes the swap (if the staging is fully written) or rolls it back (if partial). The leader retransmits if the follower remains incomplete.

### 23.5 Read consistency

Reads against the leader are linearizable. Reads against a follower are bounded-stale (delay = follower's apply lag). For most ContextD queries, follower reads are fine; for queries that require strong consistency (e.g., reading a feedback weight you just wrote), the client can pin to the leader or use a `read_after_write` token.

### 23.6 Failure modes

- **Leader crash** — Raft elects a new leader from the followers within milliseconds (default election timeout: 150-300 ms). New writes are accepted on the new leader. Old leader is fenced (when it returns, it discovers its term is stale and steps down).
- **Network partition** — the side without a quorum cannot accept writes (preserves consistency). The side with a quorum continues. On heal, the minority side is brought up to date via log replication or snapshot install.
- **Total cluster failure** — on restart, the surviving nodes recover from local state + WAL; once a quorum reaches the same state, a new leader is elected.

### 23.7 Quorum policies

Two policies for write acceptance:

- `MAJORITY` (default) — writes commit when a majority of nodes acknowledge. Tolerates `floor((N-1)/2)` failures.
- `ALL` — writes commit only when every node acknowledges. Stronger durability, lower throughput.

Most deployments use `MAJORITY`. `ALL` is for the rare workload that needs every replica to be exact-copy at all times (e.g., regulatory archival scenarios).

---

## 24. Compression and codec selection

### 24.1 Delta-of-delta encoding for timestamps

Sample timestamps are usually near-monotonic with near-constant interval. The compression scheme:

```
   first timestamp:     stored raw (8 bytes)
   second timestamp:    stored as delta from first (raw 8 bytes)
   third timestamp on:  stored as delta-of-delta (dod) with prefix code:
       dod == 0:                        '0'      (1 bit)
       dod in [-64, 63]:                '10' + 7 bits zigzag (9 bits total)
       dod in [-256, 255]:              '110' + 9 bits zigzag (12 bits total)
       dod in [-2047, 2047]:            '1110' + 12 bits zigzag (16 bits total)
       otherwise:                        '1111' + 64 bits raw (68 bits total)
```

For uniformly-spaced samples, average is ~1 bit per timestamp → 64× compression vs raw. For variable-rate samples, ~3-5 bits per timestamp → 16-20× compression.

### 24.2 Gorilla XOR encoding for floats

For float values that change slowly (typical telemetry: latency, weight, score), Gorilla's XOR scheme:

```
   first value:                 stored raw (64 bits)
   subsequent value:
       XOR with previous value
       if XOR == 0:             '0' (1 bit)
       else:                    '1' + leading-zero count + meaningful-bit count + meaningful bits
```

For values that share most high bits (e.g., a feedback_weight that drifts from 0.5 to 0.6), the meaningful-bit run is short → ~2-3 bits per value. For uncorrelated values, falls back to ~10-15 bits.

### 24.3 Simple8b for integers

Variable-length integer packing where 60 bits store 1-240 ints depending on max value:

```
   selector (4 bits) — chooses pack scheme
   payload (60 bits) — packed ints per scheme
```

Schemes range from "1 × 60-bit int" (selector 0) through "60 × 1-bit ints" (selector 14). The encoder picks the scheme that maximizes density per block.

### 24.4 Dictionary encoding

For low-cardinality columns (e.g., status enums, source names): build a dictionary `{value → small_id}`. Store the small_id (1-4 bytes) instead of the value (typically 10-30 bytes per string).

The dictionary itself is stored once per sealed segment (or once per database for stable enums). For cardinality > 65536, dictionary encoding doesn't apply; fall back to raw or LZ4.

### 24.5 LZ4 for archive blobs

Cores and audit segments use LZ4 frame compression for the whole serialized stream. LZ4 is chosen for decode speed (~3 GB/s on modern CPUs) over higher compression ratios — when restoring a Context Core, decode time matters more than archive size.

### 24.6 Codec selection

The system selects the codec per column based on type and observed cardinality:

- `timestamp` columns → DeltaOfDelta
- `float` columns → GorillaXOR
- `int` columns → Simple8b
- `string` columns with cardinality < 65536 → Dictionary
- `string` columns otherwise → raw (fall through)
- archive blobs → LZ4 frame

The selection happens at compaction time based on statistics gathered during the scan.

---

## 25. Performance and scale envelope

Headline implementation choices and the operational characteristics they unlock:

| Subsystem | Implementation choice | Headline performance |
|-----------|----------------------|----------------------|
| Page cache | Concurrent map + async flusher | Cache hit ratio > 95% on hot working set |
| Bucket page format | 2048-slot pointer table + tail-grown records | ~5K records/sec/thread for inserts |
| Bulk graph load | `addManyAtEndDirect` zigzag-VLQ inline | ~5M edges/sec single-thread |
| LSM tree index | Mutable + compacted dual; binary search per page | ~10ms point-lookup at billion-key scale |
| HNSW vector | Async rebuild + PQ compression | < 50ms p50 search at 100M-vector index |
| Full-text BM25 | LSM tree posting lists + FOR/PForDelta compression | ~5ms term scan at billion-document corpus |
| Time-series | Delta-of-delta + Gorilla XOR + sealed segments | ~1-3 bits per sample |
| Bitemporal | Four indexes per fact predicate | < 5ms p50 for any of the four temporal queries |
| Resolver | HNSW + LSH blocking + cross-encoder | ~50K resolved entities/sec at steady state |
| Feedback EMA | Cached weight in record header | Zero-overhead retrieval-time multiplication |
| Two-phase commit | Page-version OCC + ordered file locks | ~10K commits/sec with `YES_NO_METADATA` durability |
| Replication | Raft + page-version idempotent apply | < 50ms commit latency on 5-node cluster (LAN) |
| Wire protocols | NIO selector + per-protocol modules | Sub-millisecond protocol overhead |

These are implementation targets — not all are simultaneously achievable on a single instance. Cluster scaling (read replicas, sharded vector services, dedicated time-series shards) is the path beyond single-instance capacity. The implementation choices above ensure the substrate scales horizontally where needed without architectural rework.

---

*This file maps each ContextD feature to the engine-level techniques required to implement it. Cross-references: data shapes in `04-product-and-architecture.md`; module specs in `06-context-forge.md` and `07-context-resolver.md`; subsystem technology in `08-core-technology.md`; measured performance in `09-benchmarks-and-validation.md`; build sequence in `10-roadmap-and-build-plan.md`.*
