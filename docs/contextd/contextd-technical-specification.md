---
title: "ContextD: Technical Specification"
subtitle: "The Context Graph Database — Architecture, Engine Implementation, Modules, Benchmarks, Capabilities"
date: "2026-04-28"
toc: true
toc-depth: 3
geometry: margin=1in
fontsize: 11pt
---

# ContextD: Technical Specification

This document is the consolidated technical specification of ContextD — a context graph database for AI agents. It documents architecture, engine implementation at the substrate level, productized modules, benchmarks, capabilities, and integration surface as a single technical reference.

The document is technical in tone throughout. Marketing positioning, customer use cases, and applied scenarios are documented separately and are not reproduced here.

---

# 1. System Architecture

## 1.1 What ContextD is

ContextD is a database. It ingests enterprise data through a 10-step pipeline, transforms raw episodes (emails, messages, tickets, CRM rows) into a structured knowledge graph with bitemporal state and decision lineage, learns from feedback what matters, and serves AI agents structured context windows via an SDK, REST API, MCP server, or any of six wire protocols (Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP). Every fact carries provenance, every retrieval is feedback-weighted, every snapshot is versioned.

ContextD is not an AI agent — it serves context to agents. It is not a workflow tool. It is not a vector database (vectors are 1 of 6 data models). It is not an analytics platform. It is not a general-purpose database — it is opinionated for context assembly. It is not a RAG framework — it is the persistent data layer that RAG frameworks lack.

## 1.2 Six-layer architecture

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
│ 10-Step Ingestion · Hybrid Query Engine · 7-Step Context Assembly        │
│ Feedback EMA · Ontology Engine · Context Cores · Context Resolver        │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: UNIFIED MULTI-MODEL STORAGE SUBSTRATE                           │
│ Graph + Document + KV + Vector (HNSW/PQ) + Full-Text (BM25)              │
│ + Time-Series (Gorilla XOR) · 70+ SIMD Algorithms · ACID Transactions    │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1.5: CONTEXT FORGE — pre-pipeline mapping layer                    │
│ Source Introspector · Data Profiler · Business Logic Ingester            │
│ Mapping Inference Engine · Forge Studio · Forge Mapping artifact         │
│ Forge Profiles · Forge-to-Pipeline Bridge                                │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: CONNECTOR LAYER                                                 │
│ Airbyte Engine (600+ sources) · Custom SDK Connectors (P0 + SDK)         │
│ OAuth2 Service (30+ providers) · Incremental Sync                        │
└──────────────────────────────────────────────────────────────────────────┘
```

## 1.3 Today's stack vs the unified substrate

The current production stack is a multi-database arrangement: PostgreSQL for tenant metadata, Neo4j for graph and full-text, Milvus for vectors, Redis for hot caching, Temporal for durable workers. The migration target is a single multi-model engine that subsumes the Neo4j and Milvus roles into one ACID-transactional engine. PostgreSQL, Redis, and Temporal remain in their orthogonal roles.

Why the migration matters technically:

- Cross-model ACID becomes possible. A single transaction can update the graph adjacency lists, the HNSW vector index, the BM25 inverted index, the time-series sealed segments, and the audit log under one WAL fsync.
- Schema drift across databases disappears.
- Latency taxes drop — every query no longer crosses 3-5 network hops.
- License entanglements (SSPL, Commons-Clause, Business-Source-License variants) are eliminated by an Apache-2.0 substrate choice.

## 1.4 The closed loop

```
CONNECTOR     CONTEXT FORGE        INGESTION PIPELINE                QUERY ENGINE
Snowflake ─┐                                                          Natural Language Query
Postgres  ─┤  ┌─ Introspect ─┐                                              │
SFDC      ─┼─►├─ Profile ────┼─► Forge        ┌─ Step 1: Episode             ▼
HubSpot   ─┤  ├─ Ingest BL ──┤   Mapping ────►├─ Step 2: Retrieve Context  Hybrid Search
Gmail     ─┤  ├─ Infer (7) ──┤  (versioned    ├─ Step 3: Extract ◄ Forge   ◄ feedback
Slack     ─┘  └─ Studio ─────┘   msgpack +     │     +Ontology               ▼
                       ↑          SHA-256)      ├─ Step 4: Resolve (det.)   Reranker
                  Customer review               ├─ Step 5: Resolve(sem+LLM)  ▼
                  / edit / approve              ├─ Step 6: Edges  ◄ Forge   Apply Feedback
                                                 ├─ Step 7: Dedup/Invalidate ▼
                                                 ├─ Step 8: Embeddings        Token-Budget Prune
                                                 ├─ Step 9: Save ──────────► ▼
                                                 ├─ Forge-derived facts       Context Window
                                                 │   computed                   │
                                                 └─ Step 10: Communities       ▼
                                                                          Agent Rates (1-5)
              CONTEXT CORES                                                    │
              Build  ◄── Snapshot ◄── Graph Storage                            ▼
              Test   ◄── Query Suite                                    EMA Weight Update
              Promote ──► Production                                       per node & edge
              Rollback ◄── Previous Version                                    │
                                                                                ▼
                                                                          Graph Storage
```

The feedback loop closes the system. The Forge loop ensures the customer's analyst-team work is honored at ingestion time. Every retrieval informs the next.

---

# 2. ContextD-Native Database Implementation

This section documents *how* the ContextD engine is implemented at the substrate level — the data structures, algorithms, page formats, locking protocols, encoding schemes, replication state machines, and crash-recovery techniques required to ship every subsystem reliably at enterprise scale. It is the longest section of this document because every claim ContextD makes downstream of "context-first database" reduces to a substrate-level commitment described here.

## 2.1 Storage engine fundamentals

The substrate is page-based. Every read and write moves through fixed-size pages held by a buffer pool, and durability is provided by a write-ahead log. The choice of page-based-with-LSM-trees-on-top sits between extremes: append-only logs at one end, mutable B-trees at the other. This balance is the right one for a workload that mixes high-throughput writes (ingestion pipeline + Resolver streaming) with point-read-heavy queries (retrieval) and large compaction batches (Context Cores).

### 2.1.1 Page format

Every persisted file is a sequence of fixed-size pages (default 64 KiB; configurable per file type — index pages typically 256 KiB to amortize binary-search costs). Each page has a small header followed by content:

```
Page layout:
   offset 0   ─ page version (4 bytes, big-endian unsigned int)
   offset 4   ─ content size (4 bytes, content end inside the page)
   offset 8   ─ content
   ...
   offset N-1 ─ end of page
```

The version is the optimistic-concurrency sequence number. The content size lets the engine handle pages that are not fully utilized.

### 2.1.2 Page types and per-type binary layout

The substrate carries six concrete page types, each with its own header trailer pair beyond the common 8-byte prefix:

| Type | Owner component | Header size | Notable trailer |
|------|-----------------|-------------|-----------------|
| Bucket page | record buckets | 10 bytes (slot count) + 8 KiB slot directory | None |
| LSM data page | LSM tree (mutable + compacted) | 16 bytes (key count + min/max key offsets) | 4-byte CRC32C |
| LSM bloom page | LSM tree | 12 bytes (m, k, fingerprint hash) | None |
| Vector graph page | HNSW graph store | 12 bytes (level, node count) | Variable (PQ codes inline) |
| Time-series sealed page | TimeSeriesShard | 16 bytes (column descriptor) | 4-byte CRC32C |
| Audit log page | append-only segment | 12 bytes (entry count + segment seq) | Hash-chain footer |

Each page header is laid out little-endian on disk regardless of host endianness; the substrate normalizes endianness at the codec boundary so files copied from one host to another are bit-for-bit identical.

### 2.1.3 Page cache

A single global buffer pool maps `(database_id, file_id, page_number)` → cached page object. Implemented as a concurrent map with a configurable maximum-RAM quota; eviction is reactive (when memory pressure crosses a threshold, evict pages with no active references in approximately-LRU order). The pool serves both read-only views (`ImmutablePage`) and write-locked views (`MutablePage`); a single physical page can hand out either, but the engine guarantees writers and readers do not see each other through the cache during a transaction.

A separate concurrent map tracks **pending-flush** pages — pages dirty in the write set but not yet on disk — so a reader can choose between (a) reading from the buffer pool and (b) waiting for the flush to complete. This avoids stale reads after a crash.

A dedicated background flusher thread drains the dirty queue. The flusher supports per-database **suspend** (drop all dirty pages and pause flushes) which is required during operations like compaction or core promotion that need exclusive control.

### 2.1.4 Buffer pool eviction algorithm

The buffer pool implements an approximate-LRU algorithm based on **CLOCK with reference and dirty bits**:

```
Each cached page carries:
   pin_count   (uint16)  — number of active accessors
   ref_bit     (bit)     — set on every access, cleared by the sweeper
   dirty_bit   (bit)     — set on first mutation
   last_access (int64)   — monotonic counter

evict_one():
   while true:
      page = clock_hand.next()
      if page.pin_count > 0: continue            # skip pinned pages
      if page.ref_bit:
         page.ref_bit = 0                        # second-chance
         continue
      if page.dirty_bit:
         flush_queue.enqueue(page)               # async write-out
         continue
      remove_from_cache(page)
      return page.id
```

Pin counts are incremented on `getPage()` and decremented on `releasePage()`. A page that is ever pinned during a sweep cycle survives. Pages that have stayed dirty longer than `max_dirty_age_ms` (default 5 seconds) are forcibly flushed by a background drainer regardless of pressure.

Hit-rate target: >95% on the hot working set. Working-set theory predicts this for graph-traversal workloads with 70-80% locality (the Forge-derived community structure of typical context graphs concentrates traffic on a small number of dense subgraphs).

### 2.1.5 Page prefetching and read-ahead

Three prefetch triggers reduce page-fault stalls:

1. **Sequential-scan detector.** When two consecutive page reads in the same file land at adjacent page numbers, the reader marks the file as "scanning" and issues asynchronous reads for the next 128 pages.
2. **Iterator hint.** LSM tree iterators carry an explicit `lookahead_pages` parameter; the iterator queues prefetches one batch ahead of its current position.
3. **Vector-index neighbor prefetch.** When the HNSW search expands a node, the neighbor list of the candidate is prefetched in parallel with the distance computation, so the next layer of expansion finds neighbors warm in cache.

A pool of background reader threads (default 4) services prefetch I/O concurrently with foreground work. NVMe SSDs sustain 250K+ IOPS, so prefetch parallelism is critical to keep the device queue full.

### 2.1.6 Bucket page layout (record container)

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

The pointer table at the head and records growing from the tail let the engine reuse arbitrary-position deletes without reorganization.

Each record-pointer slot holds a position-in-page **plus** a sentinel size encoding:

| Sentinel size | Meaning |
|--------------:|---------|
| size > 0 | active record, varint-encoded length |
| 0 | deleted record (slot reusable) |
| -1 | placeholder pointer to a record relocated to another page |
| -2 | first chunk of a multi-page record |
| -3 | continuation chunk of a multi-page record |
| ≤ -5 | placeholder content pointed to from another page |

A record's stable identifier (RID) is `(bucket_id, position)` where `position = page_number × maxRecordsInPage + slot_in_page`. RID is the global pointer used by relationships, indexes, the Identity Graph, and provenance metadata.

### 2.1.7 Free-space tracking

Per bucket, a bounded open-addressing primitive integer→integer map tracks `page_id → free_space_bytes` for pages that have recently been touched. The map is bounded (default ~100 entries) so insert-heavy workloads can find a partially-full page quickly without scanning the whole bucket. Three reuse-space modes — `LOW`, `MEDIUM`, `HIGH` — trade off insert speed (always-append) versus disk efficiency (reuse first-fit slot).

### 2.1.8 Record encoding

Records are encoded with explicit type tags and variable-length size fields. Variable-length integers use a compact 7-bits-per-byte encoding so common small values cost 1-2 bytes.

For the graph engine specifically, edge segments use **zigzag** encoding (maps signed integers to unsigned so negative ids don't burn high bits) plus VLQ (variable-length quantity) for the bucket-id and position fields. This brings a 96-bit RID down to typically 4-5 bytes for the in-edge / out-edge lists of a vertex. At enterprise scale (10⁸ edges), the difference between fixed 12-byte RIDs and ~5-byte VLQ-encoded RIDs is hundreds of GB of disk and memory.

### 2.1.9 Tombstone handling and slot reuse

Logical deletes set the slot's sentinel size to 0, leaving the record bytes in place but unreadable. Physical reclamation happens during bucket compaction:

1. The compaction worker iterates pages from low to high.
2. For each page: if `live_bytes / total_bytes < compaction_threshold` (default 0.5), the page is marked for rewrite.
3. Live records are copied into a new page, slot directory rebuilt, RIDs updated via a per-bucket forwarding map.
4. The forwarding map is consulted on every secondary-index lookup until the next index repair cycle finalizes the new RIDs.

LSM tree tombstones use a special `value_type = TOMBSTONE` byte. Tombstones survive compaction as long as any non-compacted level still contains an older version of the key — once they reach the bottom level, they are dropped.

### 2.1.10 Variable-length records and overflow chains

Records ≤ 50% of page size store inline. Larger records split:

- **First chunk** has slot sentinel `-2` and a 4-byte forward pointer to the next chunk.
- **Continuation chunks** have sentinel `-3`, plus 4-byte back-pointer + 4-byte forward-pointer.
- **Final chunk** has sentinel `-3` and a forward-pointer of `0`.

A single record can span an arbitrary number of pages. Reads follow the chain, materializing the record into a contiguous buffer; writes follow the chain in reverse for atomicity. Large blob fields (e.g., a 10 MiB document body) are routed to a separate **blob bucket** rather than the entity bucket — the entity record stores only the blob's RID. Blobs themselves are LZ4-compressed before chunking.

## 2.2 Multi-model unification at one engine

Six data models share a single storage substrate. The unification is not bolt-on — it is built into the abstraction layer.

### 2.2.1 Component abstraction

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

All under one `txId` with one WAL fsync. This is what makes "ACID across data models" real.

### 2.2.2 File-level lock manager

Concurrency is controlled at file granularity. A `LockManager<int, Object>` maps file_id → lock holder; the holder is the requesting transaction context. Locks are acquired during commit-phase 1 in **deterministic order by file_id** to eliminate deadlock cycles by construction. Per-file locks are held for the duration of phase-1 only (~milliseconds) — concurrent commits to disjoint file sets proceed in parallel.

### 2.2.3 Type system and dictionary encoding

The substrate stores high-frequency strings (predicate names, source identifiers, extraction methods, label tags) in a per-database **dictionary component** that maps `string ↔ int32`. On record encode:

- A first-time string is interned: the dictionary writes a new `(id, string)` row, returns the id.
- Subsequent encodes of the same string return the cached id.

On-record overhead drops from ~70 bytes raw (typical predicate name + source name) to 8 bytes (two 4-byte ids). The dictionary itself is a small LSM tree, fully in cache (typically <10 MB for a million-string vocabulary), and read with sub-microsecond latency per lookup.

### 2.2.4 Schema registry and component catalog

Per-database schema state lives in a JSON manifest replicated through the Raft log:

```
schema.json
   version            (int — incremented on every DDL)
   types              (map: typeName → TypeDescriptor)
   indexes            (map: indexName → IndexDescriptor)
   buckets            (map: bucketName → BucketDescriptor)
   files              (map: fileId → FileDescriptor)
   created_at, updated_at
```

The `TypeDescriptor` enumerates property names, types, default values, bitemporal flag, embedded vector dimensions, and which secondary indexes apply. DDL operations are routed through Raft so all replicas converge to identical schema state before any DML observes the change.

## 2.3 Two-phase commit transactions with optimistic concurrency

ContextD does not use lock-based pessimistic concurrency for record writes. Instead, every page carries a version counter, and conflicts are detected at commit time.

### 2.3.1 The page-version OCC protocol

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

### 2.3.2 Isolation levels

Two levels are supported. **Read Committed** (default): each statement within a transaction sees a fresh snapshot of the page cache. **Repeatable Read**: the first read of any page caches the immutable view in the transaction context; subsequent reads of the same page return the cached view, providing snapshot isolation.

### 2.3.3 MVCC visibility resolution

Snapshot isolation requires per-row visibility decisions. Each row carries `tx_min` (the tx that created it) and `tx_max` (the tx that deleted/superseded it; nullable). At read time:

```
visible_to(snapshot_S, row_R):
   if R.tx_min is uncommitted_at(S):       return false
   if R.tx_min > S.snapshot_xmax:          return false   # created after snapshot
   if R.tx_min in S.snapshot_xip:          return false   # in-flight at snapshot
   if R.tx_max is null:                    return true    # never deleted
   if R.tx_max is uncommitted_at(S):       return true    # delete in-flight
   if R.tx_max > S.snapshot_xmax:          return true    # delete after snapshot
   if R.tx_max in S.snapshot_xip:          return true    # delete in-flight at snapshot
   return false                                           # delete committed before snapshot
```

The CLOG (commit log) is a bitmap of `tx_id → state`. Each tx has 2 bits: 00 = in-progress, 01 = committed, 10 = aborted. The bitmap is page-cached and updated atomically on commit/abort. Visibility checks are sub-microsecond.

### 2.3.4 Snapshot management

A **snapshot** captures a point-in-time view: `(snapshot_xmin, snapshot_xmax, snapshot_xip)`.

- `snapshot_xmin` = smallest tx id that was still in-progress when the snapshot was taken.
- `snapshot_xmax` = next-to-be-allocated tx id.
- `snapshot_xip` = list of tx ids in-progress at snapshot time.

Active snapshots are tracked per-connection in a process-wide ring buffer. The **oldest active snapshot's xmin** gates vacuum: any row with `tx_max < oldest_xmin` is unreachable and can be physically reclaimed.

Long-running readers (analytical queries, reports against the customer-context graph) hold snapshots; their xmin pins the vacuum horizon. A configurable `max_snapshot_age_ms` (default 1 hour) caps this — older snapshots receive a `SnapshotTooOldException` on next access.

### 2.3.5 Conflict detection across components

A single transaction may write to N components (bucket + 3 indexes + vector + full-text + time-series). The OCC check runs per-page across **every** component. If any component's page version mismatches at commit time, the entire transaction rolls back atomically — no partial writes.

The deterministic file-lock ordering also serves as conflict-detection ordering: tx A and tx B touching disjoint file sets never block; tx A and tx B touching overlapping file sets see at most one succeed.

### 2.3.6 Long-running read transactions

For analytical workloads (Context Core builds, audit reports, decision-lineage walks), the substrate supports **CONSISTENT_READ** isolation: a snapshot is materialized at transaction start and held for the transaction's lifetime, regardless of duration. The vacuum horizon respects active CONSISTENT_READ transactions; their snapshots cannot be reclaimed.

For queries that don't need snapshot consistency (live dashboards), **DIRTY_READ** is offered as an explicit opt-in: each read picks the latest committed version with no snapshot tracking, eliminating xmin pinning entirely.

## 2.4 Write-Ahead Log and durability

### 2.4.1 WAL record format

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

The trailing size and magic sentinel let the recovery process scan the WAL forwards or backwards and detect torn writes.

### 2.4.2 Flush modes

Three durability modes per transaction:

- `NO` — write to OS buffer, do not fsync. Lowest latency.
- `YES_NO_METADATA` — fsync the WAL file's data extent only. Crash-safe across OS reboots; ~1ms additional latency on SSDs.
- `YES_FULL` — fsync data + filesystem metadata. Strongest guarantee; ~5-10ms per commit.

### 2.4.3 Crash recovery

On startup:

1. List all WAL files; sort by sequence number.
2. For each WAL file in order, scan records:
   - For each page block: if `currPageVersion > current_version_of(page)`, apply the delta (redo). Else skip (already applied).
3. Mark recovery complete; new WAL files start fresh.

The page-version guard makes recovery **idempotent**.

### 2.4.4 Group commit protocol

Single-fsync-per-commit caps throughput at the device's fsync rate (~5-10K commits/sec on consumer NVMe). The substrate amortizes this cost via group commit:

```
commit_request(tx):
   tx.phase1_result = run_phase_1(tx)
   gc = group_committer.acquire()
   gc.queue.append(tx)
   if gc.is_leader(tx):
      wait_for_followers(window_us=200)        # batch up to 200µs of arrivals
      buf = concat([t.wal_segment for t in gc.queue])
      walfile.write(buf)
      walfile.fsync()
      for t in gc.queue: t.signal_phase2_done()
   else:
      tx.wait_for_signal()
   run_phase_2(tx)
```

A leader transaction batches up to 64 follower transactions (or 200µs window) into one fsync. Effective throughput: 50,000-100,000 commits/sec on the same NVMe under high concurrency. Latency overhead per follower: ≤ 200µs of wait.

### 2.4.5 Checkpoint protocol (fuzzy ARIES-style)

The WAL grows monotonically; recovery time is proportional to WAL size. Checkpoints bound recovery:

```
checkpoint():
   begin_checkpoint_marker = walfile.append(BEGIN_CKPT, lsn)
   ATT  = active_tx_table.snapshot()           # tx_id → first_lsn
   DPT  = dirty_page_table.snapshot()          # page_id → recovery_lsn (oldest unflushed update)
   walfile.append(END_CKPT, ATT, DPT, lsn=end_lsn)
   metadata.last_checkpoint_lsn = end_lsn
```

The checkpoint is **fuzzy** — it does not require a quiesce. New transactions continue running; the snapshot of ATT and DPT is taken at the BEGIN marker, but recovery starts replay from `min(DPT.recovery_lsn for all dirty pages)`. This means recovery skips pages that were already flushed before the checkpoint.

Checkpoint frequency is configurable: every 1M transactions or every 60 seconds, whichever comes first. Checkpoint duration on a 100K-dirty-page database: ≈50 ms.

### 2.4.6 WAL segment rotation and archival

WAL files are sized at 64 MiB (configurable). When the active segment fills:

1. The writer atomically rolls to a new segment (`wal-NNN+1.dat`).
2. The previous segment is sealed (renamed to `.sealed`).
3. A background archiver ships sealed segments to cold storage (S3, GCS, HDFS, or any S3-compatible object store) for point-in-time recovery.

Local sealed segments are retained until both (a) they precede the most recent checkpoint and (b) they have been confirmed durable in cold storage. Default local retention is 7 days; cold storage retention follows the tenant's PITR policy.

### 2.4.7 Recovery state machine

Startup walks four explicit states:

```
DOWN
 │
 │ open all data files; mmap WAL segments
 ▼
RECOVERING
 │
 │ scan checkpoints; identify replay LSN range
 ▼
REPLAYING
 │
 │ apply WAL deltas in LSN order; idempotency via page-version guard
 │ rebuild active_tx_table for in-progress transactions
 ▼
COMPENSATING
 │
 │ rollback any tx that did not commit (apply priorBytes)
 │ truncate aborted WAL records
 ▼
ONLINE
```

Replay throughput: 200 MB/s on NVMe, 50 MB/s on cloud block storage. A 500 MB WAL segment replays in ~3-10 seconds.

## 2.5 Bitemporal storage at scale

ContextD's bitemporal claim — every fact tracks both event time and transaction time — has specific implementation costs and benefits.

### 2.5.1 Schema

Every Fact, Relationship, Entity, and Decision row carries four timestamp columns:

```
   valid_at      (timestamp, NOT NULL — when this became true in the world)
   invalid_at    (timestamp, nullable — when it stopped being true; null = current)
   created_at    (timestamp, NOT NULL — when we recorded it)
   expired_at    (timestamp, nullable — when we superseded our record; null = current)
```

A fact is *current* when `invalid_at IS NULL AND expired_at IS NULL`. A fact is *known to us as of date T* when `created_at <= T AND (expired_at IS NULL OR expired_at > T)`. A fact was *true in the world at date T* when `valid_at <= T AND (invalid_at IS NULL OR invalid_at > T)`.

### 2.5.2 Supersession is insert-not-update

When a new fact contradicts an old one:

```
on_supersession(old_fact_id, new_fact):
    in one transaction:
        UPDATE old_fact SET expired_at = now(), invalid_at = new_fact.valid_at
                       WHERE id = old_fact_id AND expired_at IS NULL
        INSERT new_fact with valid_at, created_at = now()
```

The OCC version check on the old fact's page protects against double-supersession. After the transaction commits, both rows exist. Storage cost: each fact mutation creates one new row plus updates one old row → ~2× write amplification. LSM compaction compensates by physically reorganizing closed (`expired_at IS NOT NULL`) facts into compacted pages with high pack ratio.

### 2.5.3 Indexing strategies

Four temporal access patterns require four index designs:

1. **Current state** (most common) — partial index on `(subject_entity_id, predicate, expired_at IS NULL)`.
2. **Historical state at T** — composite index `(subject_entity_id, predicate, valid_at desc, invalid_at desc)`. Range scan from `valid_at <= T` then filter `invalid_at IS NULL OR > T`.
3. **Knowledge state at T** — composite index `(subject_entity_id, predicate, created_at desc, expired_at desc)`.
4. **Audit state** (when did we learn X?) — covered by index #3 with reverse scan.

The four indexes per fact predicate are expensive (~4× write cost on every fact insert) but essential.

### 2.5.4 Bitemporal query rewriter

User-level temporal SQL is rewritten at the logical-plan stage:

```
SELECT subject, object FROM facts
WHERE predicate = 'budget'
  AS OF SYSTEM TIME '2026-03-01'
  AS OF VALID TIME  '2026-02-15'

  ↓ rewriter ↓

SELECT subject, object FROM facts
WHERE predicate = 'budget'
  AND created_at <= '2026-03-01'
  AND (expired_at IS NULL OR expired_at > '2026-03-01')
  AND valid_at <= '2026-02-15'
  AND (invalid_at IS NULL OR invalid_at > '2026-02-15')
```

The rewriter chooses which of the four temporal indexes to use based on the cost estimator's cardinality estimate of each predicate. For "current state" queries (no AS OF clauses), it picks the partial index; for AS OF SYSTEM TIME, it picks index #3; for AS OF VALID TIME, it picks index #2; for AS OF BOTH, it picks the index with the more selective leading column.

### 2.5.5 Vacuum and garbage collection of expired rows

A background **vacuum** worker reclaims rows that no active snapshot can see:

```
vacuum_worker(database):
   horizon = oldest_active_snapshot_xmin(database)
   for bucket in database.buckets:
      for page in bucket.pages:
         dead_rows = [r for r in page.records
                       if r.tx_max != null and r.tx_max < horizon]
         if dead_rows:
            rewrite_page(page, exclude=dead_rows)
            update_index_pointers(dead_rows)
```

Vacuum runs every 30s on a sliding cursor, processing one bucket at a time. Rewritten pages preserve RIDs of surviving rows; dead rows' RIDs are placed in a free-list for reuse.

Bitemporal-expired rows (rows with `expired_at IS NOT NULL` older than the tenant's retention window) are subject to additional retention rules: depending on policy, they are either fully reclaimed or moved to a separate "cold-history" bucket whose pages are LZ4-compressed and stored on slower media.

### 2.5.6 Temporal compaction

Beyond vacuum, a **temporal compactor** physically reorganizes closed facts:

- Pages with > 80% closed rows (high `expired_at IS NOT NULL` ratio) are merged.
- Ten consecutive closed-fact-only pages compact into one compressed page.
- Compaction occurs during off-peak windows (configurable cron) to avoid contention with live ingest.

Net pack ratio after temporal compaction: 8-10× space reduction on long-running graphs.

## 2.6 Provenance encoding

Every record (entity, relationship, fact, decision, episode) carries provenance metadata:

```
   source_pipeline       (string, dictionary-encoded → 4 bytes)
   source_task           (string, dictionary-encoded → 4 bytes)
   extraction_method     (enum: deterministic | llm_extraction | forge_derived |
                          ontology_constrained | manual | structured_import)
   source_episode_id     (RID — points back to the originating Episode)
```

The string fields are not stored as raw strings. Instead the engine uses a dictionary component (a global string-to-id map) to assign 4-byte ids. So the on-record overhead is ~16 bytes (two 4-byte string-ids + one enum byte + one 8-byte RID) instead of ~70 bytes raw. At 100M records, that's 1.6 GB instead of 7 GB.

A secondary index on `source_episode_id` enables the query *"give me every entity / fact / relationship derived from episode X"*.

## 2.7 Decision lineage as first-class data

Decisions are not text in audit logs. They are typed entities with a strict schema and dedicated indexing.

### 2.7.1 Vertex schema

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
   provenance metadata
```

### 2.7.2 Edge types

Four typed edges connect a Decision into the broader graph:

- `DECIDED_BY` → Person entity
- `INFORMED_BY` → array of Fact / Episode RIDs
- `APPLIED_POLICY` → Policy entity (versioned vertex type)
- `AFFECTED` → array of Entity RIDs

### 2.7.3 Indexes

- Composite LSM index on `(decision_type, decided_at desc, expired_at IS NULL)` for time-range audit queries.
- LSM index on `decided_by` for *"all decisions made by Jordan Blake"* queries.
- LSM index on `applied_policy` for *"all decisions citing policy X"*.
- Full-text index on `subject + justification` for free-text audit search.

### 2.7.4 Decision graph traversal patterns

A **decision lineage walk** is a backward BFS from a Decision vertex through INFORMED_BY edges:

```
decision_lineage(decision_id, max_depth=5):
   visited = {decision_id}
   queue = [(decision_id, 0)]
   trace = []
   while queue:
      (vid, depth) = queue.pop(0)
      if depth > max_depth: continue
      v = load_vertex(vid)
      trace.append({"vertex": v, "depth": depth})
      for edge in v.out_edges_of_type(["INFORMED_BY", "APPLIED_POLICY"]):
         if edge.target not in visited:
            visited.add(edge.target)
            queue.append((edge.target, depth + 1))
   return trace
```

Cost: O(N) where N is the number of vertices reachable in `max_depth` hops from the seed Decision. Typical decisions in production graphs touch 10-50 vertices total — the walk completes in <10 ms.

A **decision impact walk** is the reverse: forward BFS through AFFECTED to find every entity touched by a Decision and every downstream Decision conditioned on those entities. Used for audit replay during compliance reviews.

## 2.8 Audit log

### 2.8.1 Append-only segment file

The audit log is its own component, separate from the WAL. Per entry:

```
   timestamp (8)
   user_id (string-id, 4 bytes)
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

The hash chain makes the log **tamper-evident**.

### 2.8.2 Sealed-segment pattern

The active segment is appended in-memory + buffered to disk; on size threshold (64 MiB) or time threshold (1 hour), the segment is sealed:

1. Compute final segment hash (covers all entries).
2. fsync the segment file.
3. Atomically rename from `audit.<seq>.active` to `audit.<seq>.sealed`.

Sealed segments are immutable.

### 2.8.3 Indexing

A separate LSM tree index is built over sealed segments, keyed on `(timestamp, user_id, action)`. This answers *"every action user X took between dates Y and Z"* in milliseconds even when the audit corpus is hundreds of GB.

### 2.8.4 Hash-chain verification protocol

Verification is a linear walk; any deviation flags tampering:

```
verify_audit_chain(database):
   prev = genesis_hash(database)            # SHA-256("contextd-genesis-" + db_id + create_ts)
   for segment in database.audit_segments_in_order():
      for entry in segment.entries():
         computed = SHA-256(entry.bytes_excluding_hash)
         if entry.hash      != computed:    raise HashMismatch(entry.timestamp)
         if entry.prev_hash != prev:        raise BrokenChain(entry.timestamp)
         prev = entry.hash
      if segment.sealed_hash != SHA-256(concat(entry_hashes)):
         raise SegmentSealMismatch(segment.id)
   return ChainStatus.VALID
```

A periodic verification job (default: hourly) walks each sealed segment. For regulated tenants, the chain head is published to an external append-only attestation service (timestamped to a write-only log; supported targets: AWS Timestream, Azure immutable storage, public blockchain checkpointing). External attestation makes internal compromise externally detectable: an adversary that rewrites the local chain cannot rewrite the external attestation history.

## 2.9 RBAC at the storage layer

Access control is enforced inside the storage engine, so a Cypher / SQL / Mongo / Redis client connected via any wire protocol receives the same isolation guarantees with no additional code.

### 2.9.1 Per-database user object

Every connection is associated with a `SecurityDatabaseUser` object:

```
   userName
   groups (array of string)
   fileAccessMap (boolean[fileId][access_type])  # per-file permission lookup
   databaseAccessMap (boolean[database_action])  # database-level permissions
   resultSetLimit (long)
   readTimeout (long)
```

The `fileAccessMap` is a two-dimensional bit-array indexed by `(fileId, access_type_ordinal)`. Access types are `CREATE_RECORD`, `READ_RECORD`, `UPDATE_RECORD`, `DELETE_RECORD`. Database-level actions are `UPDATE_SECURITY`, `UPDATE_SCHEMA`, `UPDATE_DATABASE_SETTINGS`.

### 2.9.2 Permission check at every record op

Every call into a bucket starts with:

```
   bucket.createRecord(record, ...):
       database.checkPermissionsOnFile(fileId, ACCESS.CREATE_RECORD)
           → user.requestAccessOnFile(fileId, ACCESS.CREATE_RECORD)
               → return fileAccessMap[fileId][CREATE_RECORD.ordinal()]
       if denied: throw SecurityException
       proceed with the actual write
```

The check is two array indices and one bit test — sub-microsecond on a hot path.

### 2.9.3 RBAC compilation pipeline

Operators express grants declaratively. The compiler converts grants into the bitmap form the engine consults at hot path:

```
grants.yaml:
   - principal: { role: viewer, name: marketing }
     resource:  { type: company, scope: tag = "campaign:*" }
     actions:   [READ]
   - principal: { user: alice@acme.com }
     resource:  { type: deal }
     actions:   [READ, UPDATE, FEEDBACK]
```

Compilation steps:

1. **Resolve principals.** Look up role / user / group in the user catalog.
2. **Resolve resources.** Map type names to bucket file_ids; expand scope predicates into RID ranges (or compile dynamic-scope predicates into pre-filter bitmaps for query time).
3. **Resolve actions.** Map enum names to ordinal bits.
4. **Project to bitmap.** For each (user_id, file_id) pair, set bits in `fileAccessMap[file_id]` per granted action.
5. **Atomic swap.** New compiled bitmap installed; old bitmap kept for in-flight transactions until they finish.

Recompilation is triggered on grant change; full compile time for a 1000-user, 50-resource policy is ~30 ms — well below request latency.

### 2.9.4 Wire-protocol RBAC dispatch

Every wire protocol terminates at the same bucket-level access check. Per-protocol mapping:

| Protocol | Translation |
|----------|-------------|
| Bolt (Cypher) | `MATCH (n:Person) ...` → bucket.scan() on Person bucket → `READ_RECORD` check |
| PostgreSQL (SQL) | `SELECT * FROM facts WHERE ...` → indexed scan → `READ_RECORD` check on facts bucket |
| Mongo Wire | `db.entities.find({...})` → bucket.scan() on entities bucket → `READ_RECORD` |
| Redis (RESP) | `GET entity:123` → bucket.point_lookup() → `READ_RECORD` |
| gRPC | typed RPC → routed to bucket op → relevant access check |
| HTTP REST | typed endpoint → routed to bucket op → relevant access check |

All paths converge on the same `requestAccessOnFile` call. There is no path where a wire protocol bypasses RBAC. New protocols added to the substrate inherit RBAC enforcement automatically.

## 2.10 Multi-tenancy

### 2.10.1 Database-per-tenant isolation

Each tenant gets a separate database directory. A database is the unit of: file system tree (data files, WAL, audit log), schema, page cache budget allocation, transaction id sequence, RBAC state, replication group. There is no shared mutable state between tenants at the substrate layer.

This is stronger isolation than schema-per-tenant in a shared database. Cross-tenant queries are physically impossible.

### 2.10.2 Page cache quota

The page cache buffer pool is global at the JVM level but is partitioned with per-tenant soft quotas:

- Each tenant has a configured `max_cache_bytes`. Sum across tenants ≤ JVM heap.
- The eviction strategy prefers to evict pages from tenants that exceed their quota first.
- Within a tenant's quota, eviction is approximate-LRU.

### 2.10.3 Per-tenant resource governance

Beyond cache quotas, every tenant carries:

| Resource | Cap | Enforcement point |
|----------|-----|-------------------|
| Concurrent open transactions | configurable (default 256) | Tx allocator |
| QPS (queries per second) | configurable | Token bucket at protocol dispatcher |
| Write rate (records/sec) | configurable | Bucket write path |
| Result set rows | configurable | Cursor materializer |
| Per-query latency | configurable timeout | Query executor |
| WAL bytes/sec | configurable | WAL writer back-pressure |

Tenants exceeding QPS receive `429 Too Many Requests` (or protocol-specific equivalent). Tenants exceeding result-set caps receive truncation with explicit `result_truncated=true` metadata.

### 2.10.4 Cross-tenant audit isolation

Each tenant's audit log is a distinct hash chain. There is no global audit stream — auditors review per-tenant chains. Operational metrics (system-wide latency, cache hit-rate) are aggregated separately and emitted to operator-only dashboards.

## 2.11 Graph engine internals

### 2.11.1 Adjacency-list segments per vertex per direction

Each vertex stores a linked list of edge segments per direction (`out` and `in`). A segment is a fixed-capacity buffer (sized to fit comfortably within one bucket page) holding (edgeRID, neighborVertexRID) pairs. When a segment fills, a new segment is allocated and the previous-pointer is updated.

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

### 2.11.2 Why separate `_out_edges` and `_in_edges` files

Each vertex type has three associated buckets: the vertex bucket itself, an `_out_edges` bucket holding all out-segments, and an `_in_edges` bucket holding all in-segments. The split:

- Halves the I/O for unidirectional traversals.
- Allows independent compaction.
- Localizes lock scope.

### 2.11.3 Bulk-load fast path

The naive insert-edge path constructs RID objects, allocates temp buffers, copies into segments. The fast path (`addAtEndDirect`) takes raw `(int bucket_id, long position, int neighbor_bucket, long neighbor_position)` primitives and inlines the zigzag + VLQ encoding directly into the segment buffer with no intermediate object allocation. Throughput: ~5M edges/sec on a modern CPU.

### 2.11.4 Lock contention and the dual-format graph

Two responses to graph-traversal lock contention:

**Response A — analytical view.** Build a Compressed Sparse Row (CSR) snapshot of the graph in memory, refreshed periodically (e.g., every minute) from the live data. CSR is a contiguous array of (vertex_id, edge_offset) pointers + a contiguous array of (neighbor_id, edge_id) pairs. Traversal becomes pointer arithmetic + sequential reads — lock-free, cache-friendly, 10× faster for read-heavy workloads.

**Response B — sharded read replicas.** Read replicas hold the same write-side state but answer traversal queries independently. Query routing distributes requests across replicas.

The two responses compose.

### 2.11.5 Roaring bitmap adjacency for analytical workloads

For workloads dominated by set operations on vertex IDs (e.g., "all customers with churn risk > 0.5 and a deal in pipeline"), the substrate can build **roaring bitmap** indexes over vertex labels.

A roaring bitmap chunks the 32-bit RID space into 16-bit prefix buckets, and stores each chunk as one of three container types:

| Container | Used when | Layout |
|-----------|-----------|--------|
| Array | < 4096 elements | sorted uint16 array |
| Bitmap | ≥ 4096 elements, scattered | 8 KiB raw bitmap |
| Run | long contiguous ranges | (start, length) pairs |

Each chunk picks the smallest of the three. AND/OR/XOR/NOT operations are SIMD-accelerated on bitmap chunks and bound-respecting on array chunks. A 100M-vertex graph's "Customer" label bitmap occupies 12 MB on disk, 12 MB in memory — operations over it at 10 GB/sec aggregate throughput.

### 2.11.6 BFS / DFS traversal engine

The traversal engine is a stateful operator that decodes adjacency segments lazily:

```
bfs(start_vid, target_predicate, max_hops, max_results):
   visited  = roaring_bitmap()
   visited.add(start_vid)
   frontier = [start_vid]
   results  = []
   for hop in 1..max_hops:
      next_frontier = []
      for v in frontier:
         for (eid, neighbor) in v.out_edges_iterator():
            if visited.contains(neighbor): continue
            visited.add(neighbor)
            if target_predicate(neighbor):
               results.append((v, neighbor, hop))
               if len(results) >= max_results: return results
            next_frontier.append(neighbor)
      frontier = next_frontier
      if not frontier: break
   return results
```

Memory budget: ~16 bytes per visited vertex (in the roaring bitmap) + ~5 bytes per cached adjacency entry. A 1M-vertex BFS with hop limit 4 fits in ~40 MB.

DFS uses a stack instead of a queue and supports per-edge **abort predicates** (e.g., "stop expanding when path length exceeds N").

### 2.11.7 Cypher pattern matching and physical plans

A Cypher query like:

```cypher
MATCH (a:Person {name: 'Alice'})-[r:WORKS_AT]->(o:Org)<-[:WORKS_AT]-(b:Person)
RETURN b
```

is parsed to an AST; the logical plan is:

```
PROJECT(b)
  EXPAND(b ←WORKS_AT— o)
    EXPAND(a —WORKS_AT→ o)
      NODE_INDEX_SCAN(a:Person, name='Alice')
```

The physical planner enumerates choices per operator:

| Operator | Choices |
|----------|---------|
| NODE scan | full bucket scan, or index lookup (LSM tree on Person.name) |
| EXPAND | adjacency-segment iterator, or roaring-bitmap intersect |
| FILTER | inline, or index-driven pre-filter |
| AGGREGATE | hash-aggregate, or sort-aggregate |
| SORT | in-memory quicksort, or external merge-sort |

The cost-based selector (Section 2.17) picks the cheapest plan per operator given current statistics.

### 2.11.8 Variable-length path search with constraints

`(a)-[*1..5]-(b)` translates to a bounded BFS, but with extra knobs: `*MIN..MAX`, edge-type filters per hop, weight-sum constraints, shortest-path mode.

The substrate supports bidirectional BFS for shortest-path: BFS expands from both `a` and `b` simultaneously; meeting frontiers terminate the search. For typical 6-degrees-of-separation queries on social-graph-sized data, bidirectional BFS reduces work by `√N` versus unidirectional BFS.

For weighted shortest path, Dijkstra with a binary-heap frontier; for very large graphs, A* with a bounded-error heuristic.

## 2.12 Vector index (HNSW + Product Quantization)

### 2.12.1 HNSW graph structure

Hierarchical Navigable Small World (HNSW) is a layered graph where each layer is a navigable graph approximating the nearest-neighbor relationship. Search starts at the top (sparse) layer, greedily navigates to the closest node, descends to the next layer, repeats until layer 0 (densest). Each layer's degree is bounded (typically `M = 16-64` neighbors per node).

Construction is incremental — each insert finds the closest nodes at each layer, links them, and probabilistically promotes the new node to higher layers. Construction time per insert: O(log N × M × dim).

### 2.12.2 Three graph states

The graph index has three operating states:

- `LOADING` — initial state at startup, no graph available.
- `IMMUTABLE` — graph is on disk, mmap'd, optimized for searches (zero-copy reads). Inserts go to a delta buffer.
- `MUTABLE` — graph is on heap, accepting incremental inserts.

### 2.12.3 Async rebuild with hot-swap

When the mutable accumulator reaches its threshold, an async rebuild thread:

1. Snapshots the current vectors + delta buffer.
2. Builds a new HNSW graph from the snapshot.
3. Persists the new graph to a temp file.
4. fsync, atomic rename into place.
5. Hot-swap the in-memory graph reference.
6. Drain any inserts that arrived during the rebuild.

A JVM-wide semaphore caps concurrent rebuilds across all databases (default: 1).

### 2.12.4 Product Quantization (PQ) for compression

A 1024-dimensional float32 vector is 4 KiB. At 100M vectors, that's 400 GB of raw embeddings — too much for RAM-resident search.

Product Quantization reduces this. The vector is split into M sub-vectors (e.g., M=64); each sub-vector is quantized against a learned codebook of K codes (e.g., K=256 → 1 byte per sub-vector). The encoded vector is M bytes total. For M=64, K=256 on 1024-dim vectors: 64 bytes per encoded vector instead of 4096. **64× compression.** 100M vectors fit in 6 GB instead of 400 GB.

### 2.12.5 Filtered ANN

A common query is *"find the k nearest vectors to q, but only among entities of type Customer where churn_risk > 0.5"*. The pre-filter approach: compute the bitmap of valid RIDs, pass the bitmap to the HNSW search, and during graph traversal skip nodes whose RID is not in the bitmap.

### 2.12.6 HNSW insert algorithm (full pseudocode)

```
insert(q, M, efConstruction, mL):
   level = floor(-ln(uniform(0,1)) * mL)            # level multiplier mL = 1/ln(M)
   ep = entrypoint
   for lc in topLayer..level+1:
      ep = search_layer(q, ep, ef=1, layer=lc)
   for lc in min(topLayer, level)..0:
      W = search_layer(q, ep, efConstruction, layer=lc)
      neighbors = select_neighbors_heuristic(q, W, M, layer=lc)
      add_bidirectional_edges(q, neighbors, layer=lc)
      for n in neighbors:
         if degree(n, lc) > Mmax_lc:
            n.neighbors[lc] = select_neighbors_heuristic(n, n.neighbors[lc], Mmax_lc, layer=lc)
      ep = W
   if level > topLayer:
      entrypoint = q
      topLayer = level
```

Default parameters used by ContextD: `M=16`, `Mmax=M`, `Mmax0=2M=32`, `efConstruction=200`, `mL=1/ln(M)≈0.36`. The level distribution is geometric with mean `mL`; ~63% of nodes live at layer 0 only, ~23% at layer 1, ~9% at layer 2, decaying.

### 2.12.7 HNSW search algorithm (full pseudocode)

```
search_layer(q, ep, ef, layer):
   visited    = {ep}
   candidates = priority_queue([(dist(q, ep), ep)])      # min-heap by distance
   results    = max_heap([(dist(q, ep), ep)], cap=ef)    # max-heap, capped
   while not candidates.empty():
      c = candidates.pop_min()
      f = results.peek_max()
      if dist(c, q) > dist(f, q):
         break
      for n in c.neighbors[layer]:
         if n in visited: continue
         visited.add(n)
         d = dist(q, n)
         if d < dist(f, q) or len(results) < ef:
            candidates.push((d, n))
            results.push((d, n))
            if len(results) > ef: results.pop_max()
   return results

knn_search(q, k, ef_search):
   ep = entrypoint
   for lc in topLayer..1:
      ep = search_layer(q, ep, ef=1, layer=lc)
   W = search_layer(q, ep, ef=max(ef_search, k), layer=0)
   return top_k(W, k)
```

`ef_search` is the recall/latency knob: `ef_search=k` is fast and lower-recall; `ef_search=10k` is slower and near-exact. ContextD defaults to `ef_search=64` for k=10, achieving ~99% recall at ~50ms p50 on a 100M-vector index.

### 2.12.8 PQ training (Lloyd's k-means on each subspace)

```
train_pq(X, M, K, max_iters):
   d = X.shape[1]
   sub_dim = d // M
   codebook = zeros(M, K, sub_dim)
   for sub in 0..M-1:
      X_sub   = X[:, sub*sub_dim : (sub+1)*sub_dim]
      centers = kmeans_pp_init(X_sub, K)              # K-means++ seeding
      for it in 1..max_iters:
         labels  = assign_to_nearest(X_sub, centers)  # SIMD dist on sub_dim floats
         new_c   = batch_mean(X_sub, labels, K)
         if max_norm(new_c - centers) < epsilon: break
         centers = new_c
      codebook[sub] = centers
   return codebook
```

Training cost on a single A100 GPU: ~30 minutes for 10M vectors, M=64, K=256, max_iters=25. Re-training is triggered when the embedding model is upgraded; otherwise codebooks are stable for the lifetime of the index.

### 2.12.9 Asymmetric Distance Computation (ADC)

ADC speeds up PQ-compressed search dramatically. For a query `q`, build a per-query lookup table once:

```
build_lut(q, codebook):
   d = q.shape[0]
   sub_dim = d // M
   lut = zeros(M, K)
   for sub in 0..M-1:
      q_sub = q[sub*sub_dim : (sub+1)*sub_dim]
      for k in 0..K-1:
         lut[sub][k] = squared_distance(q_sub, codebook[sub][k])
   return lut

approx_distance(q, x_encoded, lut):
   d = 0
   for sub in 0..M-1:
      d += lut[sub][x_encoded[sub]]      # M lookups, M floating-point adds
   return d
```

For M=64 sub-vectors, distance computation collapses to 64 lookups + 63 adds — ≈10-15 ns on modern CPUs versus ~250 ns for full 1024-dim L2. The LUT itself fits in L1 cache (64 × 256 × 4 = 64 KiB).

### 2.12.10 SIMD-accelerated distance kernels

Distance computations (both full and ADC) are SIMD-vectorized:

| Instruction set | Floats/instr | 1024-dim L2 cost |
|----------------|--------------|------------------|
| Scalar | 1 | ~1024 fma |
| AVX2 | 8 | ~128 fma |
| AVX-512 | 16 | ~64 fma |
| ARM NEON | 4 | ~256 fma |
| ARM SVE2 | 16 (variable) | ~64-128 fma |

The substrate uses Java 21 Vector API; the JIT auto-selects platform intrinsics. On AVX-512 hardware, full L2 throughput is ~250 distances/microsecond per core.

### 2.12.11 Filtered ANN with bitmap pre-filter

For pre-filtered ANN (a roaring-bitmap of valid RIDs), the search loop adds one bitmap check per neighbor expansion:

```
search_layer_filtered(q, ep, ef, layer, valid_bitmap):
   ...
   for n in c.neighbors[layer]:
      if not valid_bitmap.contains(n.rid): continue   # skip filtered-out
      if n in visited: continue
      ...
```

Filtering reduces the candidate pool. To compensate for the reduced pool's effect on convergence, `ef_search` is auto-inflated by the inverse of the filter selectivity: `ef_effective = ef_search × (1 / selectivity)`, capped at `ef_search × 16`.

### 2.12.12 Vector refinement / re-ranking

For workloads that need higher-than-PQ recall, the engine offers two-stage retrieval:

1. **Stage 1 — PQ-compressed search.** Returns top-`2k` candidates using ADC.
2. **Stage 2 — Exact re-rank.** Loads full float32 vectors for the 2k candidates from disk; re-computes exact distance; sorts; returns top-k.

Stage-2 cost: 2k disk reads + 2k full distance computations. For k=10, 2k=20: ~20 × (~1ms cold disk) + 20 × (~250ns fma) ≈ 5-10 ms additional. Recall improves from ~90% (PQ-only) to ~99% (refined).

## 2.13 Full-text index

Full-text BM25 search is built on the same LSM-tree primitive as range indexes, plus an external tokenizer / analyzer / stemmer pipeline.

### 2.13.1 Inverted index basics

The LSM tree stores:

```
   key:    (term_string, document_RID)
   value:  (term_frequency, document_length)
```

A search for term `t` is a range scan over all keys with `term = t`. The result is the posting list with frequencies, which the BM25 scorer combines with corpus-level statistics (document count, average document length) to compute relevance.

### 2.13.2 BM25 scoring

For each query term `t` matching candidate document `d`:

```
   score(d, t) = idf(t) * tf(d, t) * (k1 + 1) / (tf(d, t) + k1 * (1 - b + b * |d| / avgdl))
   total_score(d) = Σ_t score(d, t)
```

Default parameters: k1=1.2, b=0.75.

### 2.13.3 Posting-list compression

- Frame Of Reference (FOR) — store the minimum RID, then deltas relative to that minimum.
- PForDelta — exception-encoded variant that handles outliers.

### 2.13.4 Tokenizer / analyzer / stemmer pipeline

Text → posting list updates flow through:

1. **Lexer** — Unicode-aware tokenization (UAX #29 word boundaries, configurable extra splitters per language).
2. **Lowercase normalizer** — locale-aware (Turkish dotted-I rule, German ß handling).
3. **Stop-word filter** — language-specific stop-word lists (English ≈174 words, configurable).
4. **Stemmer** — Snowball stemmer family (Porter for English; corresponding stemmers for 26 languages).
5. **Synonym expander** — optional; replaces tokens with their canonical form using customer-supplied synonym dictionary.
6. **N-gram / edge-gram filter** — optional; produces additional posting-list entries for prefix-search support.

Each step is configurable per-field. A `description` field might use stop-words + stemmer; an `email` field uses no analyzer at all (exact match only).

### 2.13.5 Skip-list posting list traversal

Posting lists are augmented with skip pointers every 64 entries. AND queries (`MATCH(t1) AND MATCH(t2)`) use **galloping search**: when scanning posting list A for the next entry ≥ current position in B, the scanner skips ahead exponentially (1, 2, 4, 8, ... entries) until it overshoots, then binary-searches the overshot range.

Galloping reduces intersection cost from `O(min(|A|, |B|))` to `O(log(avg_skip) × min(|A|, |B|))` for skewed distributions — effectively linear in the smaller list with a small constant factor.

### 2.13.6 Phrase search with positional posting lists

For phrase queries (`"context graph database"`), posting lists carry per-document position arrays:

```
   key:    (term, document_RID)
   value:  (term_frequency, document_length, position_array)
```

Phrase match algorithm:

1. Find all documents containing every phrase term.
2. For each candidate document, intersect the position arrays: term_i must occur at position p such that term_i+1 occurs at p+1.
3. A document matches if any consecutive position chain spans the full phrase.

Cost: O(min_term_occurrences) per candidate document.

### 2.13.7 Hybrid scoring fusion (RRF)

Reciprocal Rank Fusion combines ranked lists from BM25, vector cosine, and graph traversal:

```
RRF_score(d) = Σ_methods 1 / (k + rank_method(d))
```

`k = 60` (default, from Cormack et al. 2009). RRF is rank-based, so it is invariant to the absolute scale differences between BM25 (0-20), cosine (0-1), and BFS depth-rank (1-N) — essential because mixing raw scores would over-weight whichever method has the largest dynamic range.

## 2.14 Time-series engine for change tracking

### 2.14.1 Sharded design

A time-series type is split into N shards. Writes are distributed round-robin to balance load. Each shard owns:

- A mutable bucket — paginated component holding row-oriented samples.
- A sealed store — sequence of sealed-segment files holding compressed samples.
- A compaction lock (read-write) and an append lock.

### 2.14.2 Mutable bucket layout

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

### 2.14.3 Compaction codecs

- **Delta-of-delta** for timestamps. First raw, then delta, then dod with prefix-coded variable-bit encoding (1 bit for dod=0, 2 bits + 7 = 9 bits for [-64,63], etc.). For uniformly-spaced samples, average is ~1 bit per timestamp → 64× compression.
- **Gorilla XOR** for floats. XOR with previous value; if XOR = 0 → 1 bit; else prefix + leading-zero count + meaningful bits. For slowly-changing values: ~2-3 bits per value.
- **Simple8b** for integers. Variable-length packing where 60 bits store 1-240 ints depending on max value.
- **Dictionary encoding** for low-cardinality columns.

### 2.14.4 SIMD-accelerated aggregation

Aggregation queries use Java 21 Vector API (or platform-native SIMD intrinsics) to process batches of 256 / 512 samples per instruction. For numeric aggregations on typical hardware, this is 4-8× faster than scalar code.

### 2.14.5 Time-series query engine

`SELECT avg(value) FROM ts WHERE ts.symbol='X' AND timestamp BETWEEN t1 AND t2 GROUP BY toStartOfMinute(timestamp)` is evaluated as:

1. **Shard pruning.** Hash `symbol='X'` to shard id; only that shard is touched.
2. **Segment pruning.** For the chosen shard, sealed segments whose `(min_ts, max_ts)` doesn't overlap `[t1, t2]` are skipped.
3. **Streaming decode.** Surviving segments stream-decode (Gorilla → float, Simple8b → int) into a row buffer.
4. **Streaming aggregation.** Hash table keyed by minute bucket; running sum + count; emit row when watermark passes.

Memory bound: O(buckets_in_window) regardless of input size.

### 2.14.6 Down-sampling and continuous aggregates

Pre-computed rollups reduce query cost on long ranges:

```
1m aggregator:    every  1 minute, write (min, max, sum, count) for the prior minute
5m aggregator:    every  5 minutes, write rollup of 1m results
1h aggregator:    every  60 minutes, rollup of 5m results
1d aggregator:    every  24 hours, rollup of 1h results
```

Queries automatically pick the coarsest rollup that covers the requested window. Late-arriving data invalidates affected rollup cells; an incremental rollup re-computer fixes them in the next worker cycle.

### 2.14.7 Retention and tiering

Per-shard retention policies move data through tiers:

| Tier | Storage | Codec | Retention window |
|------|---------|-------|------------------|
| Hot | NVMe, mmap'd | Gorilla + Simple8b | 7 days |
| Warm | SSD, paged | Gorilla + Simple8b + LZ4 page compression | 90 days |
| Cold | Object store (S3/GCS) | LZ4 (page) + ZSTD (segment) | unlimited (subject to tenant policy) |

Background promotion / demotion runs on a sliding cursor; transitioning a sealed segment from hot to warm costs one re-encode pass.

## 2.15 Replication and high availability

### 2.15.1 Architecture

A cluster runs N nodes (typically 3 or 5). One node is the **leader**; the others are **followers**. All writes go through the leader; reads can be served by any node (with bounded staleness).

The Raft protocol guarantees:

- A single leader at any time.
- Every committed log entry is durable on a quorum of nodes.
- Every committed entry is applied in log order on every node.

### 2.15.2 State machine bridge

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
       persist lastAppliedIndex
```

Five log-entry types let the cluster replicate not only data writes but also schema migrations, RBAC changes, and snapshot installs.

### 2.15.3 Page-version idempotency

A follower may receive the same log entry twice. The `applyChanges` step compares `log_entry.page_version` against `current_version_of(page)`. If `log_entry.page_version <= current_version`, the entry is already applied; skip.

### 2.15.4 Quorum policies

- `MAJORITY` (default) — writes commit when a majority of nodes acknowledge. Tolerates `floor((N-1)/2)` failures.
- `ALL` — writes commit only when every node acknowledges. Stronger durability, lower throughput.

### 2.15.5 Raft AppendEntries RPC flow

```
AppendEntriesRequest:
   term            (int64)   leader's current term
   leaderId        (int64)   for follower redirect
   prevLogIndex    (int64)   index of log entry preceding new entries
   prevLogTerm     (int64)   term of prevLogIndex entry
   entries[]       (LogEntry[])    empty for heartbeat
   leaderCommit    (int64)   leader's commitIndex

AppendEntriesResponse:
   term            (int64)   responder's current term
   success         (bool)    true if log matched at prevLogIndex
   matchIndex      (int64)   responder's last matched index (for fast catch-up)
```

Follower handler:

```
on_append_entries(req):
   if req.term < currentTerm: return (currentTerm, false, lastLogIndex)
   if req.term > currentTerm: currentTerm = req.term; role = FOLLOWER
   reset_election_timer()
   if log.entry_at(req.prevLogIndex).term != req.prevLogTerm:
      return (currentTerm, false, log.find_conflict_index(req.prevLogIndex))
   for (i, entry) in enumerate(req.entries):
      if log.has_entry(req.prevLogIndex + 1 + i)
         and log.entry_at(req.prevLogIndex + 1 + i).term != entry.term:
         log.truncate_from(req.prevLogIndex + 1 + i)
      log.append(entry)
   if req.leaderCommit > commitIndex:
      commitIndex = min(req.leaderCommit, log.last_index)
      apply_committed_entries_up_to(commitIndex)
   return (currentTerm, true, log.last_index)
```

Leader sends AppendEntries every 50 ms (heartbeat) and on every committed write. Heartbeats carry zero entries; they exist only to suppress follower election timeouts.

### 2.15.6 Raft leader election

```
on_election_timeout():
   role = CANDIDATE
   currentTerm += 1
   votedFor = self
   votes = 1
   reset_election_timer(random in [150ms, 300ms])
   for peer in peers:
      send RequestVote(currentTerm, lastLogIndex, lastLogTerm) to peer

on_request_vote(req):
   if req.term < currentTerm: return (currentTerm, false)
   if req.term > currentTerm: currentTerm = req.term; votedFor = null; role = FOLLOWER
   up_to_date = (req.lastLogTerm  > log.last_term) or
                (req.lastLogTerm == log.last_term and req.lastLogIndex >= log.last_index)
   if (votedFor in [null, req.candidateId]) and up_to_date:
      votedFor = req.candidateId
      reset_election_timer()
      return (currentTerm, true)
   return (currentTerm, false)

on_vote_response(resp):
   if resp.term > currentTerm: revert_to_follower(resp.term); return
   if resp.granted: votes += 1
   if votes > N/2:
      role = LEADER
      send empty AppendEntries to all peers (assert leadership)
```

Election timeouts are randomized to avoid split votes. Empirical convergence: 99% of leader elections in well-provisioned clusters complete in < 300 ms.

### 2.15.7 Raft snapshot install

When the log grows past a threshold (default 100,000 entries or 1 GB), the leader snapshots its state machine and discards prior log entries:

```
take_snapshot():
   snapshotIndex = lastAppliedIndex
   snapshotTerm  = log.entry_at(snapshotIndex).term
   blob          = state_machine.serialize()
   write_snapshot_file(snapshotIndex, snapshotTerm, blob)
   log.truncate_before(snapshotIndex + 1)

InstallSnapshotRPC(leader → follower):
   term, leaderId, snapshotIndex, snapshotTerm,
   offset, data_chunk, done

on_install_snapshot(req):
   if req.term < currentTerm: return currentTerm
   buffer.append(req.offset, req.data_chunk)
   if req.done:
      state_machine.deserialize(buffer)
      lastAppliedIndex = req.snapshotIndex
      log.discard_before(req.snapshotIndex + 1)
   return currentTerm
```

Snapshot transfer is chunked (default 64 KiB chunks) and zstd-compressed in flight. A 10 GB state-machine snapshot transfers in ~80 seconds over a gigabit link.

### 2.15.8 Read replicas with bounded staleness

Followers can serve reads if their state is sufficiently fresh. A **lease-based** mechanism:

- Leader maintains a continually-refreshed lease (renewed on every successful AppendEntries to a quorum).
- Follower piggybacks `leader_commit_index` on its heartbeat response. If `(now - lease_renewal) < lease_ttl`, the follower may serve reads at staleness ≤ lease_ttl (default 1 s).
- If lease has expired, follower 307-redirects reads to the leader.

This gives "read your writes" semantics for clients pinned to the leader and bounded-staleness reads from any follower for analytical queries.

### 2.15.9 Cross-region async replication

For disaster recovery and geo-redundancy, the substrate supports **async followers** in remote regions. These nodes:

- Run Raft as voting members in a separate consensus group, not the primary one.
- Receive the primary group's committed log via a one-way replication channel (Kafka, NATS, or direct TCP).
- Lag behind the primary by `RPO` (recovery-point objective) — typically 1-5 seconds.
- Can be promoted to a new primary group on regional failure (`failover` operation).

## 2.16 Performance and scale envelope

| Subsystem | Implementation choice | Headline performance |
|-----------|----------------------|----------------------|
| Page cache | Concurrent map + async flusher + CLOCK eviction | Cache hit ratio > 95% on hot working set |
| Bucket page format | 2048-slot pointer table + tail-grown records | ~5K records/sec/thread for inserts |
| Bulk graph load | `addManyAtEndDirect` zigzag-VLQ inline | ~5M edges/sec single-thread |
| LSM tree index | Mutable + compacted dual; bloom + skip-list per page | ~10ms point-lookup at billion-key scale |
| HNSW vector | Async rebuild + PQ compression + ADC + SIMD distance | < 50ms p50 search at 100M-vector index |
| Filtered ANN | Roaring-bitmap pre-filter, ef_search auto-inflation | recall ≥ 99% after refinement |
| Full-text BM25 | LSM tree posting lists + FOR/PForDelta + skip-list intersection | ~5ms term scan at billion-document corpus |
| Phrase search | Positional posting lists | ~10ms p50 at million-document corpus |
| Time-series | Delta-of-delta + Gorilla XOR + sealed segments | ~1-3 bits per sample |
| Time-series query | Shard pruning + streaming decode | ~10M samples/sec/core scan throughput |
| Bitemporal | Four indexes per fact predicate | < 5ms p50 for any of the four temporal queries |
| Resolver | HNSW + LSH blocking + cross-encoder | ~50K resolved entities/sec at steady state |
| Feedback EMA | Cached weight in record header | Zero-overhead retrieval-time multiplication |
| Two-phase commit | Page-version OCC + ordered file locks + group commit | ~50K-100K commits/sec with `YES_NO_METADATA` durability |
| WAL throughput | Group-committed sequential writes | ~200 MB/s on NVMe, ~50 MB/s on cloud block storage |
| Crash recovery | Idempotent WAL replay | ~10 GB/min replay rate; sub-minute recovery for typical workloads |
| Checkpoint duration | ARIES-style fuzzy snapshot | ~50 ms for 100K dirty pages |
| Replication | Raft + page-version idempotent apply + lease reads | < 50ms commit latency on 5-node cluster (LAN) |
| Wire protocols | NIO selector + per-protocol modules | Sub-millisecond protocol overhead |
| Connection capacity | Selector + thread-pool dispatch | ~10K concurrent connections per node |
| Backup throughput | Page-snapshot + zstd | ~500 MB/s outbound to S3-compatible target |
| PITR | Full backup + continuous WAL archive | Point-in-time precision: 1 transaction |

## 2.17 Query optimizer and cost model

A cost-based query planner converts a logical plan into the cheapest physical plan it can construct.

### 2.17.1 Logical-to-physical rewriting

The optimizer enumerates physical alternatives per logical operator using a memoization table (Cascades-style):

| Logical op | Physical alternatives |
|-----------|----------------------|
| NodeScan(label, predicate) | full-bucket-scan, index-lookup-on-property, roaring-label-bitmap-scan |
| Expand(direction, edge_type) | adjacency-segment-iter, csr-snapshot-iter, bitmap-intersect |
| Filter(predicate) | inline, index-pre-filter, late-materialization |
| Project(fields) | inline, late-materialization |
| Sort(keys) | in-memory-quicksort, external-merge-sort, index-driven-order |
| Aggregate(group_keys, reducers) | hash-aggregate, sort-aggregate, streaming-aggregate-on-sorted-input |
| Join(condition) | hash-join, merge-join (sorted inputs), nested-loop-with-index, broadcast-join |
| Limit(n) | inline (top-n short-circuit), full-then-truncate |

Equivalence rules transform plans: predicate pushdown, projection pushdown, filter splitting, distinct elimination, redundant-sort removal.

### 2.17.2 Cost estimation

The cost of a plan is:

```
cost(plan) = α × est_cardinality(plan)
           + β × est_io_pages(plan)
           + γ × est_cpu_cycles(plan)
           + δ × est_network_round_trips(plan)
```

where `α, β, γ, δ` are platform-tuned weights (default: cardinality dominates, IO and CPU comparable, network expensive). Cardinality estimation propagates from leaf scans up the tree using histograms and selectivity formulas.

### 2.17.3 Statistics

Per indexed property, the optimizer maintains:

| Statistic | Form | Refresh |
|-----------|------|---------|
| Total row count | uint64 | maintained transactionally |
| Distinct value count | HyperLogLog (12-bit precision) | sampled hourly |
| Top-K most-common values | (value, frequency) pairs, K=100 | refreshed every 100K writes |
| Equi-depth histogram | 32 buckets covering value range | sampled hourly |
| Null fraction | float | maintained transactionally |
| Avg value width | bytes | maintained transactionally |

Statistics for unindexed properties are sampled on demand when the optimizer requires them.

### 2.17.4 Plan caching and plan stability

Compiled physical plans are cached, keyed by `(query_template_hash, parameter_types)`:

- LRU cache (default 1024 entries) per database.
- Plans invalidated on schema change or significant statistics drift (> 20% change in any cardinality).
- Plan stability hint: the operator can pin a plan version for known-good queries to defend against unstable plans across statistics refreshes.

## 2.18 Schema engine

### 2.18.1 DDL execution

DDL operations (`CREATE TYPE`, `CREATE INDEX`, `CREATE EDGE TYPE`, `ALTER TYPE`, `DROP INDEX`) route through the Raft state machine as `SCHEMA_ENTRY` log entries. The leader:

1. Validates the DDL syntactically and semantically (no name collisions, types resolve).
2. Appends `SCHEMA_ENTRY` to the log.
3. Awaits quorum acknowledgment.
4. Applies the entry locally, updating `schema.json` and bumping `schema_version`.

Followers apply identically on entry receipt. DDL is always linearizable with respect to DML.

### 2.18.2 Online schema migration

| Operation | Strategy |
|-----------|---------|
| ADD column (nullable) | Zero-downtime; column added to schema; existing records implicitly null; reads return null until first write |
| ADD column (NOT NULL with default) | Zero-downtime; default applied at read time; backfill writes default into existing records as a background pass |
| DROP column | Logical drop (column hidden from schema); physical reclamation deferred until next bucket compaction |
| RENAME column | Schema-level rename; on-disk records carry stable column ordinal so no data movement |
| CHANGE column type | Shadow-table approach: new column added with new type, background converter fills it, atomic schema swap, old column dropped |
| ADD index | Concurrent build (Section 2.18.3) |
| DROP index | Mark INVALID; background remover; final flip after no readers reference it |

### 2.18.3 Concurrent index build

```
build_index_concurrent(idx_def):
   idx = create_index_in_state INVALID
   snapshot_xid = take_snapshot()
   for record in bucket.scan(visibility=snapshot_xid):
      idx.insert(record.key_for_index, record.rid)
   # catch-up phase
   for txn_log_entry in wal_since(snapshot_xid):
      if txn_log_entry.affects(bucket):
         idx.apply(txn_log_entry)
   atomic flip:
      idx.state = ACTIVE
      schema.indexes[idx.name] = idx
```

The catch-up phase is iterative: it re-scans the WAL until catch-up overhead drops below a threshold, then takes the file lock for a final delta apply, then flips the state.

### 2.18.4 Schema versioning and bitemporal queries

Every schema change increments `schema_version` and records `(version, timestamp, operator, ddl_text)` in a system table. Bitemporal queries that target historical state can request the schema as it existed at that historical moment — useful for replaying audit reports against old data shapes.

## 2.19 Connection management and wire-protocol multiplexer

### 2.19.1 NIO selector and event loop

A single-threaded NIO selector accepts connections on every protocol port, registers them for OP_READ, and dispatches readable events to a thread pool. Per-connection state is encapsulated in a `Connection` object with:

- byte buffer for partial reads
- protocol decoder state machine
- in-flight command queue
- backpressure watermarks
- credentials / RBAC user object

A second selector dispatches OP_WRITE for outbound traffic.

### 2.19.2 Per-protocol module

Each wire protocol is a self-contained module implementing `(decode, dispatch, encode)`:

| Protocol | Encoding | Library affinity | RTT target |
|----------|----------|------------------|------------|
| Bolt | PackStream binary | Neo4j drivers | ~1 ms |
| PostgreSQL | Frontend/Backend protocol | psql, pgwire | ~1 ms |
| MongoDB Wire | BSON over OP_MSG | PyMongo, official drivers | ~2 ms |
| Redis RESP2/RESP3 | text/binary | redis-py, Jedis | < 1 ms |
| gRPC | HTTP/2 + protobuf | gRPC clients | ~2 ms |
| HTTP REST | JSON over HTTP/1.1 or HTTP/2 | curl, any HTTP client | ~3 ms |

### 2.19.3 Backpressure and rate limiting

| Layer | Knob | Behavior on saturation |
|-------|------|------------------------|
| Socket | OS write buffer | TCP back-pressure pauses readers |
| Connection | in-flight command limit | New commands queued; `MAX_IN_FLIGHT_REACHED` after threshold |
| Tenant | QPS token bucket | Excess commands rejected with `RATE_LIMITED` |
| Engine | buffer-pool watermark | Ingestion connections paused; query connections continue |
| WAL | bytes/sec limit | Phase-2 throttled; phase-1 conflicts increase, retries triggered |

### 2.19.4 Pipelining and batching

| Mode | Protocol | Pattern |
|------|----------|---------|
| Bolt pipelining | RUN/PULL/DISCARD streamed without round-trip | up to 64 statements per pipeline |
| PG extended-query | Parse/Bind/Describe/Execute/Sync | up to 1000 statements per Sync barrier |
| /batch (HTTP) | bulk JSON-lines body | 5K-50K records per request |
| Bulk-insert (Mongo) | OP_MSG with sequence | 1000 documents per call |

## 2.20 Encryption and the AES-GCM key chain

### 2.20.1 KEK / DEK hierarchy

```
Operator KMS (AWS KMS, GCP KMS, Vault, HSM)
   └── KEK (key encryption key, never leaves KMS)
        └── DEK (data encryption key, wrapped by KEK)
             ├── per-tenant variant       → encrypts tenant's data files
             └── per-token variant        → encrypts OAuth tokens
```

The DEK is materialized in process memory only when needed. Wrapped DEK ciphertext is stored alongside the encrypted file as a sidecar.

### 2.20.2 Per-page encryption

```
Encrypted page layout:
   nonce          (12 bytes, unique per page-write)
   auth_tag       (16 bytes, GCM authentication tag)
   ciphertext     (page_size bytes)
```

AES-256-GCM (default; AES-128-GCM optional for FIPS-restricted environments). Authenticated encryption: a tampered byte fails `decrypt` and flags the page as compromised. Encryption overhead: ~5% throughput on AES-NI hardware.

### 2.20.3 Key rotation

| Rotation | Frequency | Mechanism |
|----------|-----------|-----------|
| KEK | Annual | KMS rotates; all DEKs re-wrapped (no data re-encryption) |
| DEK | Quarterly | Background re-encrypt-in-place rewriter; old DEK retained 30 days for backup compatibility |
| Per-tenant DEK revoke | On tenant termination | Tenant DEK destroyed; ciphertext becomes unreadable forever |

### 2.20.4 KMS integration

| KMS | Integration mode |
|-----|------------------|
| AWS KMS | Native gRPC client, `Decrypt` API for DEK unwrap, IAM-scoped per-tenant keys |
| GCP KMS | Native client, `Decrypt` + asymmetric signing for audit attestation |
| Azure Key Vault | REST API client, RBAC scoping per tenant |
| HashiCorp Vault | Transit secret engine, dynamic credential rotation |
| External HSM | PKCS#11 standard interface, FIPS 140-2 Level 3 hardware |

## 2.21 Backup, restore, and point-in-time recovery

### 2.21.1 Full backup (online)

```
backup_full(tenant, target):
   begin_snapshot(tenant)              # captures snapshot_xmin
   for file in tenant.data_files():
      stream = file.snapshot_reader()  # page-version-consistent snapshot
      write(target, file.id, zstd_compress(stream))
   write(target, tenant.schema_json)
   write(target, tenant.audit_segments_sealed_so_far)
   end_snapshot(tenant)
```

The snapshot reader uses page-version OCC: pages are read at their snapshot version regardless of subsequent in-place writes (writes go to new pages by version). No quiesce required.

### 2.21.2 Continuous WAL archive

Sealed WAL segments are shipped to backup target as soon as they seal. The archive forms a continuous log enabling per-transaction PITR.

### 2.21.3 PITR replay

```
restore_pitr(tenant, target_time):
   restore_full(latest_full_backup_before(target_time))
   for wal_seg in archive.sealed_segments_between(backup_time, target_time):
      replay(wal_seg, stop_after_tx_with_timestamp <= target_time)
```

Granularity: any committed transaction. Replay throughput: ~200 MB/s on NVMe.

### 2.21.4 Cross-region disaster recovery

A warm standby cluster in a different region runs as an async follower of the primary cluster's Raft log. RPO ≤ 1 second under typical load; RTO ≤ 60 seconds for warm follower promotion (network reconfiguration + leader election in the new primary group).

## 2.22 Compression algorithms in detail

### 2.22.1 LZ4 for hot blobs

Block-mode LZ4 with 64 KiB blocks. Throughput: ~500 MB/s/core compress, ~3 GB/s/core decompress. Used for: archive blobs, large text fields embedded in records, payloads larger than 4 KiB. Compression ratio: ~2-3× on natural text, ~1.2× on already-compressed payloads.

### 2.22.2 ZSTD for cold data

Level 3 (default) for hot-warm archive; level 19 for very-cold archive. Throughput: ~150 MB/s/core compress at level 3. Used for: cold sealed time-series segments, long-retention audit archives, WAL archive. Compression ratio: ~3-5× on natural data; level-19 ratio is 20-30% better than level-3.

### 2.22.3 Page-level vs record-level compression

| Strategy | Pros | Cons | When |
|---------|------|------|------|
| Per-record | Random access; fast point reads | Lower ratio for small records | Hot OLTP records, full-text posting list values |
| Per-page | Higher ratio; better entropy estimation | Whole-page decompression on read | Cold time-series, archive segments |

### 2.22.4 Compression dictionary training

For zstd, a periodic background job samples 100K records, trains a custom dictionary, and stores it in metadata. Subsequent compressions reference the dictionary, achieving 4× better ratio on small records (< 1 KiB) where the dictionary content dominates raw data.

## 2.23 Off-heap memory and NIO direct buffers

### 2.23.1 Direct ByteBuffer pool

The substrate operates almost entirely off-heap. A pool of pre-allocated direct ByteBuffers (`Unsafe.allocateMemory`) holds:

- Page-cache pages (~95% of database memory)
- WAL ring buffers
- Wire-protocol I/O buffers
- HNSW PQ codes and adjacency segments (mmap'd)

Off-heap allocation defeats GC pressure on the hot path. Java heap usage stays small (~2 GB) regardless of database size; the JVM is oblivious to most of the engine's memory footprint.

### 2.23.2 Unsafe / FFM API usage

Performance-critical paths use `sun.misc.Unsafe` (Java ≤ 21) or the new Foreign Function & Memory API (Java 22+) for:

- Bulk memory copy with SIMD acceleration
- Native-aligned integer / float / long reads to satisfy CPU vector instructions
- mmap fast-paths bypassing JNI overhead

### 2.23.3 Memory accounting and leak detection

Every native allocation passes through a tracked allocator. Per-tenant allocation totals are exported to Prometheus. A periodic audit compares total native allocated bytes vs the sum of accounted allocations; drift > 5% triggers a leak alarm.

### 2.23.4 NUMA awareness

On multi-socket hosts, the buffer pool is partitioned by NUMA node. Handler threads are pinned to the NUMA node owning the page-cache partition they typically access. This reduces remote-memory access by 60-80% on dual-socket hosts and is essential for latency-sensitive workloads on EPYC / Xeon-Platinum hardware.

## 2.24 Putting it all together — an end-to-end commit walkthrough

To make the substrate-level commitments concrete, here is the sequence of operations triggered by a single `INSERT INTO entities (...) RETURNING id` against a multi-tenant ContextD instance:

1. **Wire protocol decode.** The TCP segment carrying the SQL Parse message arrives at the PostgreSQL listener; the NIO selector dispatches the buffer to a worker thread; the protocol decoder produces a `Parse(sql, params)` command.
2. **Auth + RBAC.** The connection's `SecurityDatabaseUser` object is consulted; the user must have `CREATE_RECORD` permission on the entities bucket.
3. **Query parsing.** SQL parser produces an AST; optimizer rewrites to a logical plan: `INSERT(entities, values) → BUCKET_APPEND + INDEX_INSERT × N + AUDIT_APPEND`.
4. **Transaction start.** A new tx_id is allocated; an MVCC snapshot is taken; in-progress xip list is updated.
5. **Bucket append.** A target page is selected from the per-bucket free-space tracker; the record is encoded (dictionary-encoded provenance + record body); slot directory updated.
6. **Index inserts.** For each indexed property, a (key, rid) pair is appended to the LSM tree's mutable level; bloom filter updated.
7. **Vector index insert.** Embedding vector is appended to the HNSW mutable accumulator; if accumulator threshold crossed, an async rebuild is queued.
8. **Full-text tokenize + insert.** Text fields tokenized through analyzer pipeline; per-token (term, rid, frequency) tuples appended to inverted-index LSM tree.
9. **Audit log append.** New audit entry constructed; prev_hash linked; SHA-256 computed.
10. **OCC commit phase 1.** File locks acquired in deterministic order; page versions verified.
11. **WAL build.** All page deltas serialized into a WAL segment record; trailing magic written.
12. **Group commit.** This tx joins the leader's commit batch; leader fsyncs WAL once for the batch.
13. **OCC commit phase 2.** Page versions incremented; flush queue updated; locks released.
14. **Raft replicate (if clustered).** WAL record packaged as `TX_ENTRY`; leader sends AppendEntries to followers; on majority ack, commitIndex advances.
15. **Followers apply.** Each follower's state-machine bridge applies the delta; page-version idempotency guards against double-apply.
16. **Result encode.** `INSERT RETURNING` cursor materializes the new id; PG protocol encodes RowDescription + DataRow + CommandComplete.
17. **Wire send.** OP_WRITE flushes the response; client receives.

End-to-end latency on a well-provisioned cluster: 1-3 ms p50 with `YES_NO_METADATA` durability. Every step in this walkthrough is implemented with the data structures and protocols documented above.

---

# 3. Context Forge — Pre-Pipeline Mapping Module

Before any context graph can be built from a structured enterprise source, Context Forge runs to ingest schema + data + business logic, propose a deterministic mapping into ContextD primitives, surface it in a curation UI for the customer to review and edit, and emit a versioned mapping artifact that configures the 10-step pipeline.

## 3.1 Why Context Forge exists

The 10-step pipeline (Section 5) treats every source as raw text and relies on LLM extraction for everything if no other configuration exists. This works for unstructured sources (Gmail, Slack, ticket bodies). It fails for structured enterprise sources in three ways:

- **Ignores schema knowledge.** A typical customer arrives with a Postgres OLTP, a Snowflake data warehouse with a 150-model dbt project, a LookML model with 100+ measures, a Salesforce schema with custom objects. Re-deriving via LLM discards their work.
- **Business logic is active derivation.** Most analytics value lives in derived metrics (LTV, health_status, MRR), not raw columns. The customer has formulas; the LLM cannot reproduce them.
- **Enterprises do not trust black-box ingestion.** Regulated industries require auditable mappings.

## 3.2 The four-stage flow

Context Forge runs once per source connection at onboarding, then re-runs incrementally when the source schema changes:

```
┌──────────────────────────────────────────────────────────────────┐
│  Stage 1: INTROSPECTION                                          │
│  Source Introspector + Data Profiler + Business Logic Ingester   │
│  → Output: canonical Source Profile (schema graph + data stats   │
│            + business logic DAG)                                 │
├──────────────────────────────────────────────────────────────────┤
│  Stage 2: INFERENCE                                              │
│  Mapping Inference Engine                                        │
│  → Output: Candidate Forge Mapping                               │
├──────────────────────────────────────────────────────────────────┤
│  Stage 3: CURATION                                               │
│  Forge Studio (user-facing review/edit UI)                       │
│  → Output: Approved Forge Mapping                                │
├──────────────────────────────────────────────────────────────────┤
│  Stage 4: COMMIT                                                 │
│  Forge Mapping serialized as msgpack, SHA-256 hashed             │
│  Versioned, content-addressed, immutable                         │
│  Forge-to-Pipeline Bridge configures the 10-step pipeline        │
└──────────────────────────────────────────────────────────────────┘
```

## 3.3 Components

### 3.3.1 Source Introspector

Connects to source systems and extracts what is structurally known.

| Source family | What is read | Adapter |
|---------------|--------------|---------|
| PostgreSQL | `pg_catalog.pg_tables`, `pg_constraint` (FKs/PKs), `pg_index`, `pg_views`, `pg_proc` (stored procs), table-level comments | Native |
| MySQL / MariaDB | `information_schema.{tables, columns, key_column_usage, statistics, views, routines}` | Native |
| SQL Server | `sys.tables`, `sys.foreign_keys`, `sys.indexes`, `sys.views`, `sys.procedures` | Native |
| Oracle | `ALL_TABLES`, `ALL_CONSTRAINTS`, `ALL_VIEWS`, `ALL_PROCEDURES` | Native |
| Snowflake | `INFORMATION_SCHEMA`, `ACCOUNT_USAGE.OBJECT_DEPENDENCIES`, tagging | Native |
| BigQuery | `INFORMATION_SCHEMA.{TABLES, COLUMNS, COLUMN_FIELD_PATHS, KEY_COLUMN_USAGE}` | Native |
| Databricks / Spark SQL | Unity Catalog, info_schema, lineage | Native |
| ClickHouse | `system.tables`, `system.columns`, MergeTree partition keys | Native |
| Salesforce | Object Describe API (custom objects, custom fields, lookup relationships, validation rules, formula fields) | API |
| HubSpot | Object schema + property API + association API | API |
| NetSuite, Workday, Dynamics, Zuora | SOAP/REST schema discovery | API |

### 3.3.2 Data Profiler

Statistical analysis of column values:

| Statistic | Algorithm | Why it matters |
|-----------|-----------|----------------|
| Cardinality estimate | HyperLogLog | Distinguishes high-cardinality (`email`) from categorical (`status`) |
| Top-K values + frequency | Count-Min Sketch | Identifies enums and reference values |
| Null rate | Sample-based | Distinguishes optional from required attributes |
| String length distribution | Sampled histogram | Pattern fingerprint (36-char strings → UUIDs) |
| Regex pattern fit | Pattern-library match | Detects emails, phones, IPs, URLs, ISO dates |
| Value-range / outlier | Sampled histogram | Distinguishes IDs from amounts |
| Cross-column dependencies | Mutual information | Detects undeclared FKs |
| PII / PHI heuristics | Presidio + custom rules | Auto-flags sensitive columns |
| Time-pattern analysis | (timestamp columns) | Detects monotonic timestamps |

The Profiler runs against samples (typically 10K-100K rows per table). Samples are stored ephemerally and not retained after the mapping is committed.

### 3.3.3 Business Logic Ingester

Accepts business logic from all formats enterprises actually use:

| Format | What it provides | Parser |
|--------|------------------|--------|
| dbt project (`manifest.json` + `sources.yml` + `schema.yml`) | Models, sources, tests, exposures, lineage | Native dbt-graph parser |
| dbt Semantic Layer / MetricFlow YAML | Metric definitions, dimensions, time grains | YAML parser |
| LookML (Looker model + view files) | Views, explores, measures, dimensions, derived tables, parameters | LookML parser |
| Cube.dev | Cubes, measures, dimensions, joins | JS schema parser |
| OpenLineage / DataHub | Cross-tool lineage, tags, glossary terms | OpenLineage spec |
| Tableau workbooks (`.tds`/`.twb` XML) | Calculated fields, parameters | XML parser |
| Power BI / DAX (model.bim, .pbix) | DAX measures, calculated columns | DAX parser |
| SQL views & stored procedures | Derivation logic | SQLGlot parser → AST → derivation DAG |
| Custom YAML / JSON business rules | Customer-specific schemas | Schema-validated YAML/JSON |
| Plain language metric definitions | "LTV = monthly_revenue / churn_rate" | LLM-assisted structured-form extraction |

### 3.3.4 Mapping Inference Engine

Seven inference passes:

1. **Table-to-Entity-Type classifier.** Heuristics: singular vs plural in name, naming conventions (`dim_*`, `fct_*`, `_log`, `_audit`), cardinality of PK, presence of `created_at` + `updated_at`, ontology cross-reference. LLM-assisted naming for ambiguous cases.
2. **FK-to-Relationship classifier.** FK direction, cardinality (1:1 / 1:N / N:M), type naming, ontology object_property matches.
3. **Junction Table Detector.** Tables with composite PK over exactly two FKs become bidirectional Relationships.
4. **Column-to-Fact-Predicate mapper.** Column name → predicate name, type + profile → fact value type, ontology cardinality / functional / disjoint constraints.
5. **Time-Series / Audit-Table Recognizer.** High-cardinality + monotonic timestamp + repeated entity FK → Episodes. `*_history` / `*_audit` / `*_log` → bitemporal annotation hints.
6. **Derived-Metric Translator.** Each metric from the Business Logic DAG becomes a Derived Fact. Formula normalized via SQLGlot / LookML evaluator / DAX evaluator. Dependencies on base columns resolved to source facts.
7. **Confidence Scoring.** Every inference receives a 0-1 confidence based on ontology-match strength, naming convention consistency, data-profile alignment, LLM agreement, customer-provided business-logic agreement.

### 3.3.5 Forge Mapping artifact

When applied, an Forge Mapping is content-addressed and immutable:

- **Versioned.** v1, v2, ... per source connection.
- **Content-addressed.** msgpack-serialized, SHA-256 hashed.
- **Immutable.** Once applied, not edited in place. Edits create a new draft → applied as a new version.
- **Diffable.** Forge Studio shows the diff between any two versions.
- **Rollbackable.** Reverting to a previous Forge Mapping triggers re-ingestion against the older mapping.
- **Exportable.** YAML/JSON export for code review, change management, or sharing across tenants.

### 3.3.6 Forge Studio

Three-pane review/edit UI:

- **Source-side view** — original DB schema with stats (row counts, last-updated, sample data).
- **Mapping middle view** — proposed mapping with confidence indicators (green/yellow/red), inline edit.
- **Graph-side view** — preview of the resulting ContextD graph.

Features: sample-data preview, predefined smoke-test queries, validation panel (warnings: no PK, ambiguous FK direction, type mismatches), version diff, save / apply / export.

### 3.3.7 Forge Profiles

Pre-built mappings for common schemas: Salesforce CRM, HubSpot, Stripe, Shopify, Zendesk, Jira/Linear, dbt+Fivetran-modeled Snowflake, generic OLTP Postgres. Customers fork and customize.

### 3.3.8 Forge-to-Pipeline Bridge

Once an Forge Mapping is applied, the 10-step ingestion pipeline reads it as configuration. The Bridge changes the pipeline's behavior:

- **Step 3 (Extract Nodes) becomes deterministic for known structures.** For source tables covered by the Forge Mapping, entities are produced from rows rather than via LLM extraction. LLM extraction is reserved for unstructured fields and unstructured sources.
- **Step 6 (Extract Edges) reads FK + junction definitions.** Relationships from the Forge Mapping are produced deterministically.
- **Derived facts are computed.** After Step 9 (Save to Graph), the Bridge runs the derived-fact computation pass against the customer's formulas.

Net effect: LLM cost is reduced by 60-80% for enterprises with significant structured sources.

---

# 4. Context Resolver — Cross-Source Identity Stitching

Context Resolver is the architectural block that turns raw, multi-source records into canonical entities. It stitches the same person, company, or asset across sources with no shared unique ID.

## 4.1 Two paths

| Source profile | Path | Mechanism |
|----------------|------|-----------|
| Structured-with-stable-ID (warehouse PKs/FKs, SaaS object IDs) | Deterministic | Context Forge FK graph + source-record-ID equality |
| Heterogeneous / unstructured / no shared ID | Probabilistic | Context Resolver — six-stage pipeline |

## 4.2 The six-stage Resolver Engine

```
                Heterogeneous record  +  source provenance
                                  │
                                  ▼
   ┌──────────────────────── Stage A — Blocking ─────────────────────────┐
   │  HNSW vector ANN over entity-embedding space                         │
   │  + DeepBlocker-style learned blocking on tabular attributes          │
   │  + 3-gram MinHash + LSH on textual fields                            │
   │  → reduces O(N²) candidate space to O(N log N)                       │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage B — Probabilistic record linkage ─────┐
   │  Fellegi-Sunter framework                                            │
   │   ─ m-probability + u-probability per attribute                      │
   │   ─ Match weight = log₂(m / u)                                       │
   │   ─ EM learns m, u from unlabeled data per source domain             │
   │   ─ Aggregate match weight across attributes                         │
   │   ─ Calibrated thresholds via Platt scaling / isotonic regression    │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage C — Neural pairwise matching ─────────┐
   │  Cross-encoder transformer (DITTO-style)                             │
   │   ─ RoBERTa / DeBERTa-v3 base; ~110M parameters                      │
   │   ─ Fine-tuned per entity-type via Resolver Profiles                 │
   │   ─ Supervised contrastive + triplet loss                            │
   │   ─ Batched on GPU; ~5K pairs/sec sustained                          │
   │   ─ Bi-encoder fast-path for high-volume streams                     │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage D — Coreference for unstructured text ┐
   │  When the entity appears as a free-text mention:                     │
   │   ─ NER via transformer (GLiNER zero-shot, RoBERTa-NER fine-tuned)   │
   │   ─ Within-document coreference (e2e-coref / MaverickCoref)          │
   │   ─ Cross-Document Coreference Resolution (CDCR)                     │
   │   ─ Mention-to-canonical linking via Stages B/C                      │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage E — Identity Graph stitching ─────────┐
   │  Each canonical_id is a vertex; each source-record-ID links via a    │
   │  confidence-weighted edge with provenance.                           │
   │   ─ Probabilistic Soft Logic transitive closure                      │
   │   ─ Conflict detection on contradictory non-match constraints        │
   │   ─ Soft-link mode for low-confidence stitches                       │
   │   ─ Bitemporal annotations on every edge                             │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage F — Active learning + LLM adjudication┐
   │  Residual hard cases — typically 5-10% of candidates near threshold. │
   │   ─ Uncertainty sampling                                             │
   │   ─ Human label via Resolver Studio review queue                     │
   │   ─ LLM final adjudication via few-shot or chain-of-thought          │
   └──────────────────────────────────────────────────────────────────────┘
```

### 4.2.1 What is explicitly avoided

- String-distance heuristics (Levenshtein, Jaro-Winkler, edit distance) as primary signals. They are famously brittle on real enterprise data.
- Graph-only ER without coreference for unstructured text. ~30% of enterprise entity references live in free text.
- One-shot LLM extraction. Too expensive at scale, inconsistent without fine-tuning.

## 4.3 Identity Graph (the persistent artifact)

Every canonical entity carries an array of source identifiers + a reconciled attribute view + a complete audit trail.

```
canonical_id (UUID)
├── identifiers[] = [
│     { source: "salesforce",  source_id: "...",  confidence: 1.00, evidence: "deterministic_pk" },
│     { source: "gmail",       source_id: "...",  confidence: 0.99, evidence: "email_exact + domain_match" },
│     { source: "slack",       source_id: "...",  confidence: 0.94, evidence: "cross_encoder + display_name + workspace_email" },
│     ...
│   ]
├── attribute_consensus = {  attributes reconciled across sources, with provenance
│     "name": "Alice Chen"  (source: salesforce, confidence: 1.00),
│     "email_primary": "alice.chen@acme.com" (source: salesforce, confidence: 1.00),
│     "title_current": "VP of Engineering" (source: confluence, confidence: 0.97, valid_at: 2025-06-15)
│   }
└── audit_trail = [ ... resolution events ordered by created_at ... ]
```

The graph is bitemporal: every identifier link carries `valid_at` / `invalid_at` and `created_at` / `expired_at`.

## 4.4 Resolver Studio

Three review queues:

1. **Active-learning queue.** Pairs flagged at Stage F via uncertainty sampling. Reviewer sees both records side-by-side with attribute alignment, the cross-encoder's confidence, and Stage B's Fellegi-Sunter score breakdown per attribute.
2. **Conflict queue.** PSL constraint violations from Stage E.
3. **Identity-graph explorer.** Navigate canonical entities, drill into any single edge for evidence trace, query by source-id or canonical-id, view bitemporal change history.

Bulk operations: "Reject all stitches with confidence < 0.7 from source X", "Re-run Stage C with the latest fine-tuned model", "Lock this canonical entity".

## 4.5 Resolver Profiles

Pre-tuned matching configurations per entity type:

| Profile | Best for | Includes |
|---------|----------|----------|
| `person-crm` | Customer / contact / lead unification | Cross-encoder fine-tuned on customer-record pairs; FS schema with email + phone + name + employer + role; CDCR for free-text mentions |
| `person-engineering` | Developers / engineering contributors | Fine-tuned on commit metadata + handle patterns + email + LDAP key; emphasis on author identity reconciliation |
| `organization-account` | Companies / accounts / business entities | FS schema includes domain + parent / subsidiary signals + DUNS + industry codes |
| `deal-opportunity` | Sales opportunities across CRM + email + Slack threads | Cross-encoder tuned for deal-stage transitions; CDCR for opportunity mentions |
| `device-asset` | Devices / endpoints / assets in IT contexts | Different attribute set (MAC, IP, device fingerprint, agent ID) |
| `product-sku` | Product-catalog entities | Standard ER, high-volume short-attribute matching |

## 4.6 Performance and scale

| Operation | Target | Mechanism |
|-----------|--------|-----------|
| Block O(N²) → O(N log N) | < 10 ms per record at 100M-vector index | HNSW + LSH parallel blocking |
| Pairwise match (Stage C) | ~ 5,000 pairs/sec on a single GPU | Cross-encoder batched inference |
| End-to-end resolution (Stages A-E) | ~ 50,000 entities/sec at steady state | Streaming pipeline, async stages |
| Active-learning loop turnaround | < 24 h surface-to-fine-tuned-model | Studio review queue + nightly fine-tune |
| Identity Graph reconciliation | Bitemporal-consistent merges, no orphan records | PSL transitive closure + supersession rules |

---

# 5. Core Technology Subsystems

## 5.1 The six data primitives

### 5.1.1 Entity (Node) — "the nouns"

```
Entity {
  id:                UUID [PK]
  canonical_id:      UUID        — resolved identity (after dedup)
  entity_type:       STRING      — person | company | project | ticket | deal | document
  name:              STRING
  labels:            [STRING]    — multi-label classification
  summary:           STRING
  name_embedding:    [FLOAT]     — stored in HNSW vector index
  source:            STRING      — origin system
  feedback_weight:   FLOAT [0.0-1.0], default 0.5
  valid_at / invalid_at:   TIMESTAMP — event time bounds
  created_at / expired_at: TIMESTAMP — transaction time bounds
  confidence:        FLOAT       — entity resolution confidence
  source_pipeline, source_task, extraction_method:  provenance
}
```

`canonical_id` is what unifies sources into one resolved person.

### 5.1.2 Relationship (Edge) — "the verbs"

```
Relationship {
  source_entity_id → target_entity_id: UUID
  relationship_type: STRING
  fact:              STRING      — natural-language description
  fact_embedding:    [FLOAT]
  weight / feedback_weight: FLOAT
  episodes:          [UUID]
  valid_at, invalid_at, created_at, expired_at
  reference_time, source, extraction_method, source_pipeline, source_task
}
```

### 5.1.3 Fact (Atomic Statement)

```
Fact {
  subject_entity_id: UUID
  predicate:         STRING
  object:            STRING|UUID
  valid_at, invalid_at, created_at, expired_at
  confidence, feedback_weight
  source_episode_id
  extraction_method
}
```

When a new fact contradicts an old one, the old fact is never deleted. Old fact: `expired_at = now()`, `invalid_at = when_new_fact_became_true`. New fact: created alongside. Both coexist.

### 5.1.4 Episode (Source) — "the raw material"

```
Episode {
  episode_type:  STRING      — message | json | text
  source:        STRING      — gmail | slack | github | salesforce | ...
  content:       TEXT
  metadata:      JSON
  entity_edges:  [UUID]
  valid_at:      TIMESTAMP
  created_at:    TIMESTAMP
}
```

### 5.1.5 Saga (Narrative)

```
Saga { name; summary (incrementally LLM-updated);
       first_episode_id; last_episode_id; last_summarized_at }

Saga ──HAS_EPISODE──▶ Episode ──NEXT_EPISODE──▶ Episode  (temporal linked list)
```

### 5.1.6 Community (Cluster)

```
Community { name; name_embedding; summary (LLM-generated) }
```

Auto-discovered via Louvain or Label Propagation.

### 5.1.7 Decision

```
Decision {
  decision_type:     "approval" | "exception" | "selection" | "commitment"
  subject:           "20% discount for Acme Corp"
  outcome:           "approved"
  decided_by:        UUID → Person
  decided_at:        TIMESTAMP
  inputs:            [UUID] → episodes + facts that informed this
  policy:            UUID → policy entity applied
  exception:         BOOLEAN
  justification:     TEXT
  affected_entities: [UUID]
  superseded_by:     UUID  — if later overridden
}
```

### 5.1.8 Schema relationships

```
Episode ──extracts──▶ Entity · Fact · Relationship
Entity ──has_fact──▶ Fact
Entity ──related_to──▶ Entity (via Relationship)
Saga ──has_episode──▶ Episode ──next_episode──▶ Episode
Community ──has_member──▶ Entity
Fact ──superseded_by──▶ Fact (temporal chain)
Decision ──informed_by──▶ Fact · Episode
Decision ──decided_by──▶ Entity (person)
Decision ──applied_policy──▶ Entity (policy)
Decision ──affected──▶ Entity (what changed)
Ontology ──constrains──▶ Ingestion Pipeline (steps 3 and 6)
```

## 5.2 The 10-step ingestion pipeline

```
Raw Data → [1]  Create Episode
         → [2]  Retrieve Context (previous episodes for continuity)
         → [3]  Extract Nodes (LLM ◄── Ontology Engine constrains)
         → [4]  Resolve Entities — Deterministic (exact, entropy gate, MinHash)
         → [5]  Resolve Entities — Semantic + LLM (cosine, LLM final)
         → [6]  Extract Edges (LLM ◄── Ontology Engine constrains)
         → [7]  Resolve/Dedup Edges (hybrid search → supersede contradictions)
         → [8]  Generate Embeddings (parallel batch via OpenAI → HNSW)
         → [9]  Save to Graph (bulk write with full provenance)
         → [10] Community Detection (optional: Louvain/LP → LLM summary)
```

Each step is wrapped in an OpenTelemetry span. Each element is stamped with `source_pipeline`, `source_task`, `extraction_method`, `source_episode_id` — full traceability.

### 5.2.1 Entity resolution — the 5-phase cascade

```
New Entity
   │
   ▼
[Phase 1: Exact Match] ──── match? → MERGE  (free, instant, 100%)
   │ no match
   ▼
[Phase 2: Entropy Gate] ─── entropy < 1.5 bits or < 6 chars? → SKIP FUZZY
   │ passes gate
   ▼
[Phase 3: MinHash/LSH] ──── Jaccard ≥ 0.9? → MERGE  (cheap, deterministic, ~95%)
   │ no match
   ▼
[Phase 4: Cosine Similarity] ── ≥ 0.6? → CANDIDATE (up to 15)
   │ candidates found
   ▼
[Phase 5: LLM Final] ────── LLM says same? → MERGE; else → CREATE NEW
```

Parameters: MinHash with 3-gram shingles, 32 permutations, LSH band size 4, Jaccard threshold 0.9. Cosine on name embeddings (1536-dim), threshold 0.6, max 15 candidates per entity. Entropy: Shannon entropy < 1.5 bits OR length < 6 characters → skip fuzzy.

Phases 1-3 handle ~80% of resolutions before LLM is called.

## 5.3 The bitemporal time model

| Dimension | Fields | What it means |
|-----------|--------|---------------|
| Event Time | `valid_at` → `invalid_at` | When was this true *in the real world*? |
| Transaction Time | `created_at` → `expired_at` | When did **we** record/learn/supersede this? |

Reality and our knowledge of reality change independently.

### 5.3.1 Four temporal queries (Cypher)

```cypher
-- Current state — "What is Acme's budget?"
WHERE f.invalid_at IS NULL AND f.expired_at IS NULL
RETURN f.object  -- "$7M"

-- Historical state — "What was Acme's budget on Feb 1?"
WHERE f.valid_at <= datetime("2026-02-01")
  AND (f.invalid_at IS NULL OR f.invalid_at > datetime("2026-02-01"))
-- "$5M"

-- Knowledge state — "What did we know about Acme's budget on Mar 1?"
WHERE f.created_at <= datetime("2026-03-01")
  AND (f.expired_at IS NULL OR f.expired_at > datetime("2026-03-01"))
-- "$5M" (we hadn't learned about the increase yet)

-- Audit state — "When did we learn about the $7M budget?"
WHERE f.object = "$7M"
RETURN f.created_at  -- "2026-04-03"
```

## 5.4 Hybrid retrieval

### 5.4.1 Three search methods in parallel

| Method | How | Strong at | Misses |
|--------|-----|-----------|--------|
| BM25 | Keyword search inside substrate FTS index | Exact terms, names, IDs, jargon | Paraphrases, synonyms |
| Cosine | HNSW nearest-neighbor via vector index | Semantic meaning, paraphrases | Exact names, IDs |
| BFS | Breadth-first graph traversal from seed entities | Structural relationships | Disconnected entities |

### 5.4.2 Five reranking strategies

| Reranker | Logic | Best for |
|----------|-------|----------|
| RRF (default) | `score(d) = Σ 1/(k + rank_i(d))`, k=60 | General purpose — balanced across all methods |
| MMR | Balances relevance vs diversity (λ=0.7) | Variety, no 10 similar results |
| Cross-Encoder | Neural reranking | Maximum accuracy when latency OK |
| Node Distance | Closer in graph hops scores higher | Relationship queries |
| Episode Mentions | More/recent episode mentions score higher | Recency queries |

3 methods × 5 rerankers = 15 composable strategies. Plus pre-built recipes (`COMBINED_HYBRID_SEARCH_RRF`, `EDGE_HYBRID_SEARCH_RRF`, `NODE_HYBRID_SEARCH_RRF`).

### 5.4.3 Why RRF as default

Scores from BM25, cosine, and BFS live on different scales (BM25: 0-20, cosine: 0-1, BFS: 0-1). RRF uses rank positions instead — scale-independent. The k=60 constant is the well-tested default from the original RRF literature.

### 5.4.4 Feedback scoring

```
final_score = reranker_score × feedback_weight

Cold start (no feedback yet):
  All weights = 0.5  →  final = reranker × 0.5  (neutral, pure relevance ordering)

After 30 positive interactions:
  Entity A: reranker=0.92, feedback=0.87 → final = 0.80
  Entity B: reranker=0.85, feedback=0.95 → final = 0.8075   ← outranks A
```

## 5.5 The 7-step context assembly algorithm

1. **Parse Intent** — decompose NL query into entity references, relationship type hints, temporal constraints, search filters. Identify seed entities for BFS.
2. **Seed Entity Selection** — BM25 + cosine identify primary entities → BFS starting points.
3. **Hybrid Parallel Search** — BM25 + cosine + BFS simultaneously via `asyncio.gather`.
4. **Rerank & Merge** — dedup by UUID, apply reranker.
5. **Apply Feedback Weights** — `final = reranker × feedback_weight`.
6. **Budget-Aware Temporal Pruning** — fill `max_tokens` in priority order: primary entities, direct relationships, current facts, saga summaries, decision lineage.
7. **Serialize & Package** — structured JSON.

### 5.5.1 Output JSON

```json
{
  "query": "Tell me about the Acme deal",
  "context": {
    "primary_entities": [...],
    "relationships": [...],
    "relevant_facts": [...],
    "temporal_context": {
      "current_state": {...},
      "recent_changes": [...]
    },
    "decision_history": [...],
    "saga_summary": "...",
    "communities": [...],
    "sources": [...]
  },
  "metadata": {
    "tokens_used": 847,
    "tokens_saved_vs_chunk_rag": 3420,
    "entities_traversed": 23,
    "confidence": 0.94,
    "avg_feedback_weight": 0.72,
    "search_recipe": "COMBINED_HYBRID_SEARCH_RRF",
    "query_latency_ms": 127
  }
}
```

## 5.6 The feedback system — streaming EMA learning

### 5.6.1 The math

```python
# Step 1: Normalize 1-5 rating to 0.0-1.0
normalized = (score - 1) / 4    # 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0

# Step 2: EMA update (alpha = 0.1)
updated_weight = previous_weight + 0.1 * (normalized - previous_weight)

# Step 3: Clamp + round
updated_weight = round(clamp(updated_weight, 0.0, 1.0), 4)
```

### 5.6.2 Why α=0.1

Small enough to be stable (no single rating swings the weight from 0.5 to 1.0). Large enough to adapt within ~30 interactions. Higher α (e.g., 0.3) makes recent feedback dominate — risk of oscillation. Lower α (e.g., 0.01) means the system never learns.

### 5.6.3 Design properties

- **Cold-start safe.** Everything starts at 0.5. System works perfectly without feedback.
- **Purely additive.** Feedback only improves results — never makes them worse than "no feedback."
- **Idempotent.** Duplicate submissions detected via `memify_metadata` flag and skipped.
- **Auditable.** All feedback events logged with timestamps, session IDs, user IDs.

## 5.7 The ontology engine

The ontology is optional. It constrains what the LLM can extract, improving consistency and reducing hallucinated entity types.

### 5.7.1 Schema (OWL-like JSON)

```json
{
  "id": "crm-ontology",
  "classes": {
    "Person": {
      "labels": {"en": "Person"},
      "comment": "A human individual",
      "subclass_of": ["Agent"],
      "disjoint_with": ["Organization"]
    },
    "Organization": { "subclass_of": ["Agent"] }
  },
  "object_properties": {
    "works_at": {
      "domain": ["Person"], "range": ["Organization"],
      "functional": false
    },
    "ceo_of": {
      "domain": ["Person"], "range": ["Organization"],
      "functional": true
    }
  },
  "datatype_properties": {
    "has_email": {
      "domain": ["Person"], "range": "xsd:string",
      "functional": true
    }
  }
}
```

### 5.7.2 Four-step semantic routing

1. **Embed ontology** — every class and property → vector embedding.
2. **Select subset per chunk** — vector-match against ontology embeddings (threshold 0.3, top-k 10) + dependency resolution.
3. **Inject into LLM prompt** — relevant subset serialized into extraction prompt via Jinja2 templates.
4. **Validate output** — class filtering, domain/range, cardinality, disjoint classes.

### 5.7.3 Validation rules

| Rule | Enforces | Example |
|------|----------|---------|
| Class filtering | Only ontology-defined types | "Vehicle" dropped if only Person/Organization defined |
| Domain/range | Relationships connect valid types | "works_at" must go Person → Organization |
| Cardinality | Functional props max 1 value | `ceo_of` functional → one company per person |
| Disjoint classes | Entity can't span conflicts | Person ≠ Organization |

Pre-built ontologies: CRM, Support, Engineering, Marketing.

## 5.8 Context Cores — versioned graph snapshots

Versioned, portable, content-addressed snapshots of entire graph + embeddings + ontology + retrieval policies + feedback weights.

### 5.8.1 Lifecycle

```
BUILD ──► TEST ──► VERSION ──► PROMOTE ──► PRODUCTION
                                              ▲
                                          ROLLBACK
```

### 5.8.2 Core contents

| Component | What it contains |
|-----------|------------------|
| Graph data | All entities, relationships, facts, decisions |
| Embeddings | Entity name + relationship fact vectors |
| Ontology | Schema that constrained extraction |
| Source manifests | Which episodes/connectors contributed, timestamps |
| Retrieval policies | Search recipe configs |
| Feedback weights | All learned relevance scores |
| Metadata | SHA-256 content hash, build timestamp, builder identity |

### 5.8.3 Operations

```bash
# Build
contextd core build --name "customer-context" --graph "production"
# → acme-context:v5 (12.4 MB, 57s, sha256:a4f8e2c91d3b7...)

# Test (golden query suite)
contextd core test --core "customer-context:v5" --queries "test-suite.yaml"
# → 50/50 pass | avg latency 42ms | avg tokens 1,420

# Diff
contextd core diff --from "customer-context:v4" --to "customer-context:v5"
# → +147 entities, +389 edges, +412 facts, latency -7%

# Promote
contextd core promote --core "customer-context:v5" --target "production"

# Rollback (instant)
contextd core rollback --target "production" --to "customer-context:v4"
```

Serialization: msgpack (30-50% smaller than JSON, 2-10× faster to encode/decode) + content-addressed SHA-256 hashing. Each core is immutable once built.

---

# 6. Benchmarks and Validation

This section captures measured performance. Numbers are recorded from a controlled test on the substrate; they are the engineering ground-truth that informs architectural decisions.

## 6.1 Test environment

| Component | Specification |
|-----------|--------------|
| DB Host | Azure Standard_D16s_v5 — 16 vCPU, 64 GB RAM, 240 GB Premium SSD |
| Client Host | Azure Standard_D4s_v5 — 4 vCPU, 16 GB RAM |
| Network | Same VNet, private IPs, ~0.73ms HTTP RTT |
| ArcadeDB | v26.4.2, JVM heap 48 GB, G1GC, production mode |
| Protocol | HTTP/JSON API (port 2480) |

## 6.2 Dataset

| Metric | Count |
|--------|-------|
| Vertices (Entity) | 475,191 |
| Edges (Relation) | 1,373,872 |
| Avg edges per vertex | 2.89 |
| Embedding dimensions | 1,024 (Cohere `embed-english-v3.0`, float32) |
| Text abstracts | 463,584 entities (97.6%) |
| Type-classified | 366,589 entities (77.1%) |

Source: DBpedia 2022-12 entity graph joined with Cohere Wikipedia embeddings.

## 6.3 Indexes

| Index | Property | Configuration |
|-------|----------|---------------|
| Unique (LSM_TREE) | `Entity.uri` | Unique B-tree |
| Vector (LSM_VECTOR) | `Entity.embedding` | HNSW, 1024 dims, cosine |
| Full-Text | `Entity.abstract` | BM25 Lucene-based |

## 6.4 Throughput results (ops/sec)

| Query Type | 1T | 4T | 8T | 16T | 32T | 64T | 128T | Peak |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Point Lookup | 1,206 | 1,423 | 1,443 | 1,456 | 1,414 | 1,340 | 1,200 | 1,456 @ 16T |
| Full-Text Search | 279 | 784 | 1,246 | 1,425 | 1,480 | 1,439 | 1,288 | 1,480 @ 32T |
| Graph 1-hop | 303 | 591 | 596 | 583 | 549 | 531 | 534 | 596 @ 8T |
| Vector Search | 23 | 91 | 157 | 155 | 144 | 145 | 140 | 157 @ 8T |
| Full Hybrid (vector + FTS + graph) | 21 | 78 | 133 | 135 | 137 | 132 | 129 | 137 @ 32T |

### 6.4.1 Headline takeaways

- Hybrid (the actual workload) peaks at **137 ops/sec** at 32 threads.
- FTS is the best scaler. 5.3× speedup from 1T → 32T. Lucene is CPU-friendly.
- Vector search caps at 8 threads. HNSW graph traversal is CPU-bound; more threads = lock contention.
- Graph traversal saturates at 4 threads. Adjacency-list page-level locks.
- Point lookup has a server-side ceiling at ~1,450 ops/sec. Looks like Undertow / HTTP-server-level serialization.

## 6.5 Single-thread latencies (best case)

| Query | p50 | p95 | p99 |
|---|---:|---:|---:|
| Point Lookup | 0.77 | 0.83 | 0.90 |
| Graph 1-hop | 1.90 | 10.5 | 17.7 |
| FTS | 3.96 | 7.3 | 8.4 |
| Vector Search | 42.3 | 55.1 | 62.9 |
| Hybrid | 47.3 | 59.2 | 66.9 |

**47ms p50 for full hybrid retrieval is competitive with or better than any equivalent multi-DB stitch.**

## 6.6 Latency degradation under load

| Query | p50 @ 1T | p50 @ 8T | p50 @ 32T | p50 @ 128T |
|---|---:|---:|---:|---:|
| Point Lookup | 0.77 | 4.6 | 17.9 | 82.1 |
| FTS | 3.96 | 6.2 | 19.9 | 86.2 |
| Graph 1-hop | 1.90 | 9.8 | 55.0 | 228.3 |
| Vector Search | 42.3 | 49.9 | 218.9 | 871.1 |
| Hybrid | 47.3 | 58.0 | 230.4 | 975.6 |

Vector search latency degrades **20× from 8T to 128T** while throughput remains flat — classic internal lock contention.

## 6.7 Bottleneck analysis

### 6.7.1 Bottleneck #1 — Point Lookup ceiling (~1,450 ops/sec)

Sub-millisecond queries (0.77ms p50) yet throughput barely scales beyond 4 threads. Not network-bound. Suggests serialization in the HTTP server or LSM-tree read path.

**Engineering response.** Cache frequently-accessed entities in-process (Caffeine / LRU). Add a Redis caching tier above ~1,500 ops/sec. Consider read replicas to scale linearly past the ceiling.

### 6.7.2 Bottleneck #2 — Graph traversal lock contention (~595 ops/sec @ 4T)

Most concerning finding. Graph 1-hop saturates at just 4 threads. `expand(out())` likely acquires page-level locks on adjacency-list segments.

**Engineering response.** Investigate the substrate's CSR-based Graph Analytical View. CSR format supports lock-free parallel reads. Profile to determine page-level vs record-level contention. Cache hot subgraphs in CSR on the query side.

### 6.7.3 Bottleneck #3 — Vector search is CPU-bound, not parallelizable (157 ops/sec @ 8T)

HNSW graph traversal involves many random memory accesses per query and contends on internal read locks. At 475K vectors × 1024 dims, the HNSW graph is ~1.9 GB — fits in 48 GB heap, so not a disk problem.

**Implications at scale.** At 6M vectors (12× current), single-query latency grows to ~100-200ms. Peak throughput will stay around 150-200 ops/sec regardless of client concurrency.

**Engineering response.** Vector search must be independently scalable. Run multiple read replicas behind a load balancer for vector-heavy workloads. Medium-term: dedicated vector search service horizontally scalable per-shard. Long-term: PQ + pre-filtering already supported.

### 6.7.4 Bottleneck #4 — Hybrid query ceiling (137 ops/sec)

The hybrid pattern is dominated by vector search. Component breakdown at 1T:

| Component | Latency | % of total |
|-----------|---------|-----------|
| Vector search (top-10) | ~42ms | 89% |
| FTS search | ~4ms | 8.5% |
| Network overhead | ~1ms | 2.5% |

## 6.8 Protocol & infrastructure findings

### 6.8.1 PostgreSQL wire protocol — unusable in current form

`CodeUtils.sleep(100)` polling loop in the PG protocol handler adds a 100ms floor to every query — **~50× slower than HTTP API**. **File:** `arcadedb/postgresw/src/main/java/com/arcadedb/postgres/PostgresNetworkExecutor.java:1515`. **Fix:** replace polling with blocking I/O (`channel.read()`).

### 6.8.2 Network impact — 8× improvement with private VNet

| Configuration | SELECT 1 RTT (p50) |
|--------------|---:|
| Public IPs (cross-region) | 5.71ms |
| Private VNet (same subnet) | 0.73ms |

For point lookups (0.77ms query time), network was 88% of latency on public IPs. **Production deployments must co-locate client and DB in the same VNet.**

### 6.8.3 Bulk ingestion — `/batch` API is 20× faster than SQL

| Method | Vertex Rate |
|--------|------------|
| SQL INSERT (per-row) | 67/sec |
| HTTP `/batch` API (JSONL) | 1,828/sec |

Index build times (475K entities, post-ingestion):

- Unique B-tree index: 9.8s
- HNSW vector index (1024-dim): 150.5s
- Full-text index: ~600s

## 6.9 Architectural commitments derived from the benchmark

The benchmark shaped four core architectural commitments:

1. **Separate ingestion and query paths.** The substrate's HNSW indexing takes 150s for 475K vectors. Mixing ingestion and querying creates contention.
2. **Independent horizontal scalability for vector search.** Per-shard vector throughput becomes independent of cluster size.
3. **Hot-path cache layer.** Substrate becomes the system of record; Redis is the hot read cache.
4. **CSR-based analytical view investigation.** Lock-free parallel graph reads.

---

# 7. Distinguishing Technical Capabilities

These are structural commitments — choices baked into the schema, the storage layer, and the engine internals — not features bolted on top. Each section names the capability and explains why retrofitting onto an alternative architecture fails.

## 7.1 Database-native multi-model storage

A single ACID engine holds graph, vector (HNSW + product quantization), full-text (BM25), document, key-value, and time-series indexes side by side. Every transaction is atomic across all six models.

**Implementation requirements.** Unified page cache, transaction manager, and WAL serving every component. Optimistic concurrency control via page versions. File-level lock manager that orders locks deterministically. Query planner routes per query primitive within one transaction context.

**Why retrofitting fails.** A graph database with a vector-index plugin cannot deliver cross-model ACID — the plugin runs in its own process. A vector database with graph features bolted on cannot deliver native graph algorithms. Multi-model is a substrate-level commitment.

## 7.2 Bitemporal-at-schema-level

Every Entity, Relationship, Fact, and Decision row carries four timestamp columns. Supersession is implemented as insert-not-update with an OCC version check.

**Why retrofitting fails.** Bitemporal storage cannot be added to an existing graph database without rewriting the data layer. The four-column commitment is per row of every type. Existing customer data is not back-fillable — the historical event-time and transaction-time information was never recorded in the first place.

## 7.3 Feedback-weighted retrieval at the data layer

Every node and edge carries a `feedback_weight` field (4 bytes inline in the record header). Every retrieval multiplies its reranker score by the inline weight at zero additional I/O cost. Streaming EMA updates write through the same OCC commit path as any other transaction.

**Why retrofitting fails.** A vector database with a post-hoc reranker cannot integrate feedback at the data layer. Adding a per-record float to a graph database that did not reserve the slot at schema design time means a full table rewrite.

## 7.4 Decision lineage as first-class data

Decisions are typed vertices with a strict schema and four typed edge classes. The vertex carries the same bitemporal columns as facts.

**Why retrofitting fails.** A graph database that lets you create `Decision` as a free-form node type does not enforce the schema invariants. A document database with decision records does not have the typed edges to Policy and to inputs.

## 7.5 Versioned content-addressed graph snapshots

A Context Core is an immutable msgpack archive containing the entire graph state at a logical point in time. Identified by SHA-256 of the archive bytes.

**Why retrofitting fails.** Versioning a database snapshot means versioning the entanglement of graph topology, embeddings, indexes, and feedback weights. Most graph databases provide schema migrations but not operational-state snapshots.

## 7.6 Schema-aware pre-pipeline mapping

Context Forge introspects source schema, profiles data, parses business logic, runs seven inference passes, surfaces in a review UI, saves a versioned msgpack artifact.

**Why retrofitting fails.** ETL tools own ingestion but not graph schema or curation UX. Data catalogs own metadata but not ingestion pipeline. Graph databases own storage but not multi-format business-logic parsers. Combining all three into one productized module is the moat.

## 7.7 Cross-source identity stitching as a productized module

Six-stage probabilistic pipeline. Bitemporal Identity Graph artifact. Resolver Studio review surface. Per-entity-type pre-tuned configurations.

**Why retrofitting fails.** Productizing cross-source resolution requires simultaneous ownership of multi-source ingestion, vector indexing for blocking, fine-tuneable neural matching with labeled per-domain training data, coreference + NER stack, probabilistic-soft-logic engine, bitemporal storage for the resulting Identity Graph, and active-learning review surface.

## 7.8 Provenance on every element

Every entity, relationship, fact, and decision row carries dictionary-encoded `source_pipeline`, `source_task`, `extraction_method`, and `source_episode_id` metadata (~16 bytes per record after string-id compression).

## 7.9 Hybrid retrieval composability under one engine

Three search methods running in parallel under a single transaction context. Five reranker strategies compose with the three methods.

**Why retrofitting fails.** Vector-only databases lack the graph engine. Graph-only databases lack a native HNSW vector index. SQL extensions adding vectors and graph have weak performance characteristics. Cross-process hybrid search adds latency and breaks transaction consistency.

## 7.10 Wire-protocol polyglot

A single instance speaks multiple wire protocols simultaneously, all terminating at the same internal command-execution interface.

## 7.11 Replicated state with log-typed entries

Raft consensus with five state-machine entry types. Page-version guards make every entry idempotent on replay.

## 7.12 Permissive-license substrate

The substrate is genuinely Apache 2.0. The intelligence layer on top is Apache 2.0 / MIT in the open-core. Customers can embed, fork, modify, and redistribute without legal conversation.

## 7.13 How these capabilities compose

The system's overall defensibility comes from the *combination* — every customer that integrates ContextD ends up with all twelve simultaneously. Switching costs compound: a tenant migrating away loses the Identity Graph, the bitemporal change history, the feedback-weighted retrieval state, the Forge Mappings, the Context Cores, and the audit log all at once.

The capabilities also feed each other. Bitemporal storage makes the Identity Graph audit-grade. Feedback weights make hybrid retrieval continuously self-improving. Decision lineage requires bitemporal and provenance. Context Cores require multi-model ACID and content-addressed serialization.

---

# 8. Integration, Deployment, Security

## 8.1 Integration paths

### 8.1.1 Python SDK

```python
from contextd import ContextD
from contextd.search import COMBINED_HYBRID_SEARCH_RRF

# Embedded mode — DB runs in-process
db = ContextD(path="./my_graph")

# Server mode — connect to remote instance
# db = ContextD(url="https://api.contextd.ai/v1", api_key="...")

# Ingest
result = await db.ingest_episode(
    name="Team Update",
    content="Alice mentioned the Acme deal is closing next week...",
    source="slack",
    reference_time=datetime(2026, 4, 10),
    saga="acme-deal-negotiation",
)

# Hybrid query
result = db.query("Who are the decision makers for Project Atlas?",
                  config=COMBINED_HYBRID_SEARCH_RRF)

# Temporal query
result = db.query("What did we know about Atlas on March 15th?",
                  as_of="2026-03-15")

# Assemble context for an AI agent
context = db.get_context(query="Draft a follow-up email", max_tokens=2000)

# Submit feedback
await db.feedback(session_id="sess_1", query_id="q_1", score=4,
                  used_entities=["e_789"], used_edges=["edge_456"])

# Context Core operations
core = db.core.build(name="acme-context", graph="production")
db.core.promote(core="acme-context:v3", target="production")
```

### 8.1.2 MCP Server (two-layer architecture)

| Layer | Provided by | Tools |
|-------|-------------|-------|
| Layer 1: Substrate built-in | substrate-native MCP | `execute_command`, `get_schema`, `list_databases`, `query`, `server_status`, `profiler` |
| Layer 2: ContextD context tools | ContextD engine | `query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `get_saga_summary`, `submit_feedback`, `ingest_episode` |

| Transport | Use case |
|-----------|----------|
| stdio | Claude Code, Cursor, Windsurf — local AI tool integration |
| SSE | Web agent frameworks, real-time streaming |
| HTTP | REST integrations, serverless functions |

### 8.1.3 REST API endpoints

```
POST   /query                       # Natural-language query
POST   /cypher                      # Direct Cypher query
POST   /search                      # Hybrid search with config
GET    /entities/:id                # Get entity by ID
GET    /entities/:id/relationships  # Get relationships
GET    /entities/:id/timeline       # Bitemporal timeline
GET    /decisions/:id/lineage       # Full decision chain
GET    /sagas/:id/summary           # Saga narrative
POST   /context                     # Assemble context for an agent
POST   /ingest/episode              # Ingest raw data
POST   /feedback                    # Submit feedback rating
POST   /cores/build                 # Build Context Core
POST   /cores/:id/promote           # Promote to production
POST   /cores/:id/rollback          # Rollback
```

### 8.1.4 Wire protocol polyglot

A single instance speaks six protocols simultaneously:

| Protocol | Drivers | Use case |
|----------|---------|----------|
| Bolt | Neo4j Python/Java/Node/Go/.NET | Cypher queries, existing Neo4j code |
| PostgreSQL | psql, pgAdmin, JDBC, SQLAlchemy | SQL queries, BI tool integration |
| MongoDB | PyMongo, Mongoose, any MongoDB driver | Document queries, JSON ops |
| Redis | redis-py, Jedis, any Redis client | KV ops, caching |
| gRPC | Custom gRPC clients (any language) | High-performance service-to-service |
| HTTP/REST | curl, any HTTP client | Universal access, web integrations |

## 8.2 Deployment modes

| Mode | Latency target | Setup | Use case |
|------|---------|-------|----------|
| Embedded | <10ms | `pip install contextd` (Java 21 via jpype) | Local agents, edge, prototyping |
| Server | <50ms | `docker compose up` | Team usage, shared instance |
| Cloud | <300ms | Managed multi-tenant | Production, fully managed |
| Enterprise | <50ms | On-prem / air-gapped K8s | HA clustering, compliance |

### 8.2.1 Performance profiles

| Profile | Page cache | Workers | Use case |
|---------|-----------|---------|----------|
| `high-performance` | Unlimited (50% RAM) | 50% cores | Production, benchmarking |
| `default` | 4 GB | Auto | General use |
| `low-ram` | 16 MB | Auto | Edge, constrained |
| `low-cpu` | Standard | 1 thread | Background processing |

### 8.2.2 Scalability targets

| Dimension | v1 (Cloud GA) | v2 (Cloud maturity) |
|-----------|--------------|---------------------|
| Entities per graph | 10M | 100M |
| Relationships per graph | 50M | 500M |
| Facts per graph | 100M | 1B |
| Episodes per graph | 10M | 100M |
| Connectors per tenant | 30 | 100 |
| Concurrent queries | 100 QPS | 500 QPS |
| Cloud tenants | 1,000 | 10,000 |

## 8.3 RBAC — six roles with three scoping dimensions

### 8.3.1 Roles

| Role | Description |
|------|-------------|
| Owner | Full access; can delete graph |
| Admin | Manage connectors, users, roles; no deletion |
| Editor | Read/write data, trigger syncs; no user/connector management |
| Viewer | Read-only, scoped (source / entity-type / tags) |
| Agent | Programmatic, scoped read + feedback submit |
| Connector | Write-only to own source |

### 8.3.2 Permission matrix

| Permission | Owner | Admin | Editor | Viewer | Agent | Connector |
|-----------|:-----:|:-----:|:------:|:------:|:-----:|:---------:|
| Read entities/relationships/facts | Y | Y | Y | scoped | scoped | N |
| Read decision lineage | Y | Y | Y | scoped | scoped | N |
| Read episodes (raw data) | Y | Y | Y | N | N | N |
| Write entities/facts | Y | Y | Y | N | N | own source |
| Submit feedback | Y | Y | Y | N | Y | N |
| Manage connectors | Y | Y | N | N | N | N |
| Manage Context Cores | Y | Y | N | N | N | N |
| Natural-language query | Y | Y | Y | scoped | scoped | N |
| Direct Cypher / SQL | Y | Y | Y | N | N | N |
| Delete graph | Y | N | N | N | N | N |

### 8.3.3 Three scoping dimensions

```json
// Sales agent: only sees Gmail + Salesforce data
{
  "role": "agent",
  "name": "sales-agent",
  "scopes": {
    "sources": ["salesforce", "gmail"],
    "sources_denied": ["slack"]
  }
}

// Marketing analyst: only sees companies, deals, campaigns
{
  "role": "viewer",
  "name": "marketing-analyst",
  "scopes": {
    "entity_types": ["company", "deal", "campaign"],
    "entity_types_denied": ["person_internal"]
  }
}

// Project-scoped agent: only sees Project Atlas
{
  "role": "agent",
  "name": "project-atlas-agent",
  "scopes": {
    "tags": ["project:atlas"]
  }
}
```

Every query enforces these scopes server-side — no client-side filtering.

## 8.4 Multi-tenancy architecture

```
Organization (Tenant)
├── Graph (isolated substrate database)
│   ├── Connectors (data sources)
│   ├── Entities, Relationships, Facts, Episodes, Sagas, Communities
│   └── Context Cores (versioned snapshots)
├── Users
├── API Keys
└── Audit Log (append-only, immutable, queryable)
```

Complete isolation:

- Separate substrate database per tenant
- No cross-tenant data access possible
- Separate connector OAuth tokens per tenant
- Audit log per tenant; retention 1 year (free) → 7 years (enterprise)

This is enforced at the substrate level, not application code.

## 8.5 Audit logging

```json
{
  "timestamp": "2026-04-13T14:30:00Z",
  "user_id": "user_123",
  "api_key_id": "key_456",
  "action": "query",
  "resource_type": "entity",
  "resource_ids": ["entity_789", "entity_012"],
  "query": "Who owns the Acme deal?",
  "search_recipe": "COMBINED_HYBRID_SEARCH_RRF",
  "result_count": 3,
  "latency_ms": 127,
  "ip_address": "192.168.1.100",
  "user_agent": "contextd-python-sdk/2.0"
}
```

## 8.6 Encryption & data security

| Surface | Approach |
|---------|----------|
| In transit | TLS 1.3 for all API communication |
| At rest | AES-256 for stored data (Cloud) |
| API keys | SHA-256 hashed, never stored plaintext, revocable |
| OAuth tokens | Encrypted at rest, rotated automatically |
| PII | Optional auto-detection on ingestion with redaction or tagging |
| Right to deletion | Cascade delete — removing an entity removes all linked relationships, facts, and episode references |

## 8.7 Connector authentication patterns

### 8.7.1 OAuth 2.0 (cloud SaaS)

The OAuth service handles the full Authorization Code grant with PKCE for confidential clients, rotates refresh tokens on every access-token refresh (per RFC 6749 §6 and Salesforce / Slack-specific rotation rules), and persists encrypted tokens at rest:

```
Token storage row:
   tenant_id (uuid)
   source (string-id)
   access_token (encrypted, AES-256-GCM)
   access_token_expires_at (timestamp)
   refresh_token (encrypted, AES-256-GCM)
   refresh_token_expires_at (timestamp, may be NULL for non-rotating providers)
   scope (string)
   provider_user_id (string)
   created_at, updated_at (timestamps)
```

Refresh is preemptive: a background task refreshes any access token whose `expires_at` is within 5 minutes of now. Failed refresh increments a `consecutive_refresh_failures` counter; after 3 failures, the source connection is marked degraded.

Encryption keys live in a separate KMS. The token-encryption-key (DEK) is itself encrypted by a master key (KEK) and rotated annually; rotation re-encrypts existing tokens via a background job.

### 8.7.2 API key (Stripe, Shopify, Snowflake user-password, Postgres connection strings)

Provider API keys are stored in the same encrypted-at-rest store as OAuth tokens. The customer rotates API keys manually through the source-connection management UI; the system supports zero-downtime rotation.

### 8.7.3 Service-account / private-key (BigQuery, GCP integrations, signed-JWT flows)

For service-account-based providers, the customer uploads a private key during source-connection setup. The key is encrypted at rest with the same DEK/KEK chain. Connector workers fetch the key on demand to mint short-lived signed JWTs.

## 8.8 Network security

| Surface | Protection |
|---------|------------|
| Client → API | TLS 1.3 only; certificates rotated via cert-manager / equivalent; HSTS header on HTTP/REST endpoint |
| Inter-service (intra-cluster) | Optional mTLS — both sides present X.509 certificates issued by an internal CA; certs rotated every 24 hours |
| Wire-protocol listeners (Bolt, PG, Mongo, Redis, gRPC) | Per-protocol TLS support |
| Network ingress (Cloud) | IP allowlist per tenant (CIDR ranges, configurable); regional VPC peering for enterprise customers; private endpoints |
| MCP transport | stdio (no network exposure); SSE/HTTP behind TLS-terminating proxy with API-key auth |

For air-gapped enterprise deployments, the substrate runs without external network egress. LLM API calls are routed to an on-premises model server; embedding generation uses a self-hosted embedding model.

## 8.9 Audit log tamper-evidence

The audit log is hash-chained for tamper-evidence. Each entry holds:

```
   prev_hash (32 bytes)     = SHA-256 of previous entry's bytes
   payload_hash (32 bytes)  = SHA-256 of this entry's payload
   entry_hash (32 bytes)    = SHA-256(prev_hash || payload_hash)
```

Any retroactive modification of an entry invalidates its `entry_hash`, which propagates forward through every subsequent entry. A periodic verification job (default: hourly) walks each sealed segment and flags any mismatch.

For regulated tenants, the chain head is published to an append-only external attestation service at a configurable cadence (default: every 15 minutes).

## 8.10 PII detection and handling

### 8.10.1 Detection rules

| Class | Examples | Detection |
|-------|----------|-----------|
| `pii.email` | RFC 5322 email addresses | Regex on string fields |
| `pii.phone` | E.164, NANP, common national formats | Regex + post-validation |
| `pii.ssn` | US Social Security Number | Regex + Luhn-style checksum |
| `pii.credit_card` | Visa, MasterCard, AmEx, Discover | Regex + Luhn checksum |
| `pii.passport` | National passport patterns | Regex per country code |
| `pii.iban` | International Bank Account Numbers | IBAN checksum |
| `pii.ip_address` | IPv4, IPv6 | Regex |
| `phi.medical_record` | Domain-specific patterns | Regex + NER |
| `phi.diagnosis_code` | ICD-10, SNOMED CT codes | Lookup table |

### 8.10.2 Handling policies

| Policy | Effect on the affected fact |
|--------|-----------------------------|
| `tag` | Fact stored as-is, with sensitivity tag; queries by users without `pii.read` permission see the fact redacted |
| `redact` | Fact's `object` value replaced with a deterministic hash (so equality joins still work) before storage |
| `tokenize` | Fact's value replaced with a tokenization-vault reference; the original lives in a separate vault with stricter access control |
| `block` | Fact dropped entirely, with an audit-log entry recording the block |

### 8.10.3 Right to deletion

When a customer requests deletion of a person's data:

1. Identity Graph is queried for the canonical entity matching the requestor.
2. All facts, relationships, edges where the entity appears are marked with `expired_at = now()` and `invalid_at = now()` — bitemporal supersession with no replacement.
3. Episodes referencing the entity are tombstoned: `content` is overwritten with a hash, while metadata is retained for the audit chain.
4. The entity vertex is tombstoned: all properties except `canonical_id` are cleared.
5. An audit-log entry records the deletion with the requester, requesting party, legal basis (GDPR Article 17, etc.), and the affected RID list.
6. Background compaction physically removes the tombstoned data from sealed-segment files within 30 days.

## 8.11 Compliance certifications

| Standard | Implementation evidence |
|----------|-------------------------|
| GDPR | Data residency, right to deletion, consent tracking via per-source consent records, data-processor agreement template, sub-processor inventory |
| SOC 2 Type I/II | Audit log, access controls (RBAC matrix), encryption (TLS 1.3 + AES-256), incident-response runbook, change-management via Context Cores promote/rollback, monitoring (OpenTelemetry + Prometheus alerts) |
| ISO 27001 | ISMS documentation, risk register, supplier-management process, business-continuity plan, internal-audit cadence |
| HIPAA (when activated) | PHI-class detection rules enabled by default, BAA-compliant cloud regions, audit-log retention ≥ 6 years, encryption-at-rest via FIPS 140-2 validated cryptography |
| FedRAMP (when activated) | FedRAMP Moderate/High baseline controls, FIPS 140-2 modules only, deployment in AWS GovCloud or Azure Government, dedicated SCIF-compliant operations team |

## 8.12 Observability

### 8.12.1 OpenTelemetry tracing

| Operation | Spans created |
|-----------|---------------|
| Ingestion pipeline | 1 parent + 1 child per step (all 10) |
| Entity resolution | 1 span per stage (normalize, entropy, minhash, cosine, llm) |
| Search | 1 parent + child per method (BM25, cosine, BFS) + reranker |
| Context assembly | 1 span covering token optimization + packaging |
| Feedback | 1 span per weight update batch |
| Connector sync | 1 parent + children for auth, extract, transform, load |

### 8.12.2 Semantic span attributes

```
contextd.pipeline.name           = "gmail_connector_v1"
contextd.pipeline.task_name      = "extract_nodes"
contextd.pipeline.episode_id     = "ep_456"
contextd.search.type             = "COMBINED_HYBRID_SEARCH_RRF"
contextd.search.query            = "Acme deal status"
contextd.search.result_count     = 23
contextd.resolution.stage        = "minhash"
contextd.session.id              = "sess_abc"
contextd.feedback.score          = 4
```

### 8.12.3 Prometheus metrics

| Metric | Type |
|--------|------|
| `contextd_queries_total` | Counter |
| `contextd_query_latency_seconds` | Histogram |
| `contextd_ingestion_episodes_total` | Counter |
| `contextd_ingestion_latency_seconds` | Histogram |
| `contextd_entity_resolution_accuracy` | Gauge |
| `contextd_feedback_scores` | Histogram |
| `contextd_context_tokens_saved` | Counter |

---

*End of technical specification.*
