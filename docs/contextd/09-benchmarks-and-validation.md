# 09 — Benchmarks & Validation

> **This file is the engineering ground-truth.** Every number here is **measured**, not aspirational. We benchmarked ArcadeDB v26.4.2 — the unified-substrate candidate for the future ContextD storage layer — against a realistic dataset and workload before committing to it. The results, including the bottlenecks we found, define our architectural roadmap.

---

## Why we ran this benchmark

Before staking ContextD's category bet on a unified substrate, we needed to know:

1. **Can ArcadeDB actually serve our hybrid retrieval workload?** (vector + FTS + graph in one query)
2. **Where does it bottleneck?** (so we know what to fix and what to architect around)
3. **What does honest p50/p95/p99 latency look like under load?** (so VC claims don't blow up under technical DD)
4. **What protocols are production-ready vs not?** (HTTP API vs PostgreSQL wire protocol vs Bolt)

The website talks about `<10ms graph traversal`. The benchmark tells us *exactly when* that holds and when it doesn't.

---

## Test environment

| Component | Specification |
|-----------|--------------|
| **DB Host** | Azure Standard_D16s_v5 — 16 vCPU, 64 GB RAM, 240 GB Premium SSD |
| **Client Host** | Azure Standard_D4s_v5 — 4 vCPU, 16 GB RAM |
| **Network** | Same VNet, private IPs, ~0.73ms HTTP RTT |
| **ArcadeDB** | v26.4.2, JVM heap 48 GB, G1GC, production mode |
| **Protocol** | HTTP/JSON API (port 2480) |

**Dataset:**

| Metric | Count |
|--------|-------|
| Vertices (Entity) | 475,191 |
| Edges (Relation) | 1,373,872 |
| Avg edges per vertex | 2.89 |
| Embedding dimensions | 1,024 (Cohere `embed-english-v3.0`, float32) |
| Text abstracts | 463,584 entities (97.6%) |
| Type-classified | 366,589 entities (77.1%) |

Source: DBpedia 2022-12 entity graph joined with Cohere Wikipedia embeddings. Real-world distributions, not synthetic.

**Indexes:**

| Index | Property | Configuration |
|-------|----------|---------------|
| Unique (LSM_TREE) | `Entity.uri` | Unique B-tree |
| Vector (LSM_VECTOR) | `Entity.embedding` | HNSW, 1024 dims, cosine |
| Full-Text | `Entity.abstract` | BM25 Lucene-based |

**Methodology:**

- 30s runs after 10s warmup
- Thread counts: 1, 4, 8, 16, 32, 64, 128
- Query types: point_lookup, fts (BM25), graph_1hop, vector_search, hybrid (vector + FTS + graph)
- Metrics: throughput (ops/sec), latency percentiles (p50, p95, p99)
- Real query vectors sampled from the actual dataset (not random)
- Connection-pooled HTTP sessions; `time.perf_counter()` for per-op latency

---

## Throughput results (ops/sec)

| Query Type | 1T | 4T | 8T | 16T | 32T | 64T | 128T | Peak |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **Point Lookup** | 1,206 | 1,423 | 1,443 | **1,456** | 1,414 | 1,340 | 1,200 | 1,456 @ 16T |
| **Full-Text Search** | 279 | 784 | 1,246 | 1,425 | **1,480** | 1,439 | 1,288 | 1,480 @ 32T |
| **Graph 1-hop** | 303 | **591** | 596 | 583 | 549 | 531 | 534 | 596 @ 8T |
| **Vector Search** | 23 | 91 | **157** | 155 | 144 | 145 | 140 | 157 @ 8T |
| **Full Hybrid** (vector + FTS + graph) | 21 | 78 | 133 | 135 | **137** | 132 | 129 | 137 @ 32T |

### Headline takeaways

- **Hybrid (the actual workload) peaks at 137 ops/sec @ 32 threads.** This is the number that matters for ContextD.
- **FTS is the best scaler.** 5.3× speedup from 1T → 32T. Lucene is CPU-friendly.
- **Vector search caps at 8 threads.** HNSW graph traversal is CPU-bound; more threads = lock contention.
- **Graph traversal saturates at 4 threads.** Adjacency-list page-level locks. Most concerning finding.
- **Point lookup has a server-side ceiling at ~1,450 ops/sec.** Looks like Undertow / HTTP-server-level serialization.

---

## Single-thread latencies (best case)

| Query | p50 | p95 | p99 |
|---|---:|---:|---:|
| Point Lookup | **0.77** | 0.83 | 0.90 |
| Graph 1-hop | **1.90** | 10.5 | 17.7 |
| FTS | **3.96** | 7.3 | 8.4 |
| Vector Search | **42.3** | 55.1 | 62.9 |
| Hybrid | **47.3** | 59.2 | 66.9 |

Single-threaded numbers are excellent. **47ms p50 for full hybrid retrieval is competitive with or better than any equivalent multi-DB stitch.** The website's `<10ms` claim is real *for graph traversal alone* (1.90ms p50) — not for full hybrid retrieval.

## Latency degradation under load

| Query | p50 @ 1T | p50 @ 8T | p50 @ 32T | p50 @ 128T |
|---|---:|---:|---:|---:|
| Point Lookup | 0.77 | 4.6 | 17.9 | 82.1 |
| FTS | 3.96 | 6.2 | 19.9 | 86.2 |
| Graph 1-hop | 1.90 | 9.8 | 55.0 | 228.3 |
| Vector Search | 42.3 | 49.9 | 218.9 | **871.1** |
| Hybrid | 47.3 | 58.0 | 230.4 | **975.6** |

Vector search latency degrades **20× from 8T to 128T** while throughput remains flat — classic internal lock contention, not useful parallelism. **This is the dominant bottleneck in ContextD's hybrid retrieval and the most important architectural finding.**

---

## Bottleneck analysis

### Bottleneck #1 — Point Lookup ceiling (~1,450 ops/sec)

Sub-millisecond queries (0.77ms p50) yet throughput barely scales beyond 4 threads. Not network-bound (0.73ms RTT). Suggests serialization in ArcadeDB's HTTP server (Undertow at ~1,450 req/sec) or LSM-tree read path (shared lock on B-tree read).

**Engineering response.**
- Cache frequently-accessed entities in-process (Caffeine / LRU)
- Add a Redis caching tier above ~1,500 ops/sec
- Use the substrate as the persistent store, not the hot query path
- Consider read replicas to scale linearly past the ceiling

This is the *easy* bottleneck — well-understood pattern (Postgres + pgbouncer + Redis) applies directly.

### Bottleneck #2 — Graph traversal lock contention (~595 ops/sec @ 4T)

Most concerning finding. Graph 1-hop saturates at just 4 threads. `expand(out())` likely acquires page-level locks on adjacency-list segments.

**Engineering response.**
- Investigate ArcadeDB's CSR-based Graph Analytical View (introduced in 26.3.x). CSR format supports lock-free parallel reads — could be the answer.
- Profile to determine page-level vs record-level contention.
- Cache hot subgraphs in CSR on the query side.
- For deep traversals (2-3 hops), the contention compounds. Consider read replicas with sharded subgraphs.

This is the *important* bottleneck — graph expansion is part of every GraphRAG query. If we can't fix it, we cap at ~600 ops/sec on graph workloads. Several paths forward; the CSR analytical view is the most promising.

### Bottleneck #3 — Vector search is CPU-bound, not parallelizable (157 ops/sec @ 8T)

HNSW graph traversal involves many random memory accesses per query and contends on internal read locks. At 475K vectors × 1024 dims, the HNSW graph is ~1.9 GB — fits in 48 GB heap, so not a disk problem. Pure CPU + memory bandwidth.

**Implications at scale:**
- At 6M vectors (12× current), single-query latency grows to ~100-200ms
- Peak throughput will stay around 150-200 ops/sec regardless of client concurrency
- This is the dominant component of hybrid query latency (~89% of the 47ms budget)

**Engineering response.**
- **Vector search must be independently scalable.** Run multiple ArcadeDB read replicas behind a load balancer for vector-heavy workloads.
- **Medium-term:** dedicated vector search service (jvector or similar) horizontally scalable per-shard.
- **Long-term:** Product Quantization (PQ) + pre-filtering to reduce HNSW search cost — already supported by LSMVector at index creation time.
- **Architecture commitment:** ContextD's separation of ingestion and query layers (already designed) makes this scaling story clean.

This is the *hard* bottleneck and the one that informs the most architecture. The good news: HNSW lock contention is a well-known pattern; horizontal scaling solves it.

### Bottleneck #4 — Hybrid query ceiling (137 ops/sec)

The hybrid pattern is dominated by vector search. Component breakdown at 1T:

| Component | Latency | % of total |
|-----------|---------|-----------|
| Vector search (top-10) | ~42ms | 89% |
| FTS search | ~4ms | 8.5% |
| Network overhead | ~1ms | 2.5% |

Graph expansion adds minimal overhead in this benchmark because we expand from very few seed nodes. **In a real ContextD workload with 2-3 hop traversal, graph contention (Bottleneck #2) compounds.**

**Engineering response.** Once Bottlenecks #2 and #3 are addressed, hybrid throughput follows. Specifically:
- Vector replicas behind LB → vector throughput linear with replica count
- Graph CSR view → graph throughput unconstrained
- Combined hybrid throughput becomes the *sum* of the slowest path, not the bottleneck

---

## Protocol & infrastructure findings

### PostgreSQL wire protocol — unusable in current form

During local testing, we discovered `CodeUtils.sleep(100)` in ArcadeDB's PG protocol handler:

- **File:** `arcadedb/postgresw/src/main/java/com/arcadedb/postgres/PostgresNetworkExecutor.java:1515`
- **Behavior:** polling loop with 100ms sleep adds a 100ms floor to every query
- **Impact:** ~50× slower than HTTP API
- **Fix:** replace polling with blocking I/O (`channel.read()`)

**Action item:** patch this in our ArcadeDB fork before shipping any PG-protocol customer access. We've already identified the change; it's small and localized. Upstream PR planned.

### Network impact — 8× improvement with private VNet

| Configuration | SELECT 1 RTT (p50) |
|--------------|---:|
| Public IPs (cross-region) | 5.71ms |
| Private VNet (same subnet) | **0.73ms** |

For point lookups (0.77ms query time), network was **88% of latency** on public IPs. **Production deployments must co-locate client and DB in the same VNet.** This is a deployment-hygiene finding, not a substrate flaw.

### Bulk ingestion — `/batch` API is 20× faster than SQL

| Method | Vertex Rate |
|--------|------------|
| SQL INSERT (per-row) | 67/sec |
| HTTP `/batch` API (JSONL) | **1,828/sec** |

Index build times (475K entities, post-ingestion):
- Unique B-tree index: **9.8s**
- HNSW vector index (1024-dim): **150.5s**
- Full-text index: **~600s**

**Action items.**
- Always use `/batch` API for ingestion. The current ContextD ingestion pipeline already does this.
- Build full-text indexes asynchronously after bulk ingest. 600s is fine for one-time initial loads but unacceptable for incremental — investigate incremental FTS index update strategies.

---

## What this means for ContextD's architecture

The benchmark shaped four core architectural commitments:

### 1. Separate ingestion and query paths

The substrate's HNSW indexing takes 150s for 475K vectors. Ingestion is bulk-write-heavy. Querying is read-heavy with totally different access patterns. Mixing them creates contention.

ContextD's existing architecture already separates these via Temporal-orchestrated workers (write side) and FastAPI request handlers (read side). The unified substrate fits this naturally.

### 2. Independent horizontal scalability for vector search

Bottleneck #3 makes this non-negotiable. The path:

```
                          ┌─── ArcadeDB read replica (vector-optimized) ───┐
                          ├─── ArcadeDB read replica (vector-optimized) ───┤
       Load Balancer ────►│                                                │
                          ├─── ArcadeDB read replica (vector-optimized) ───┤
                          └─── ArcadeDB read replica (vector-optimized) ───┘

       Single primary (ArcadeDB writer) handles ingestion via /batch
```

Per-shard vector throughput becomes independent of cluster size.

### 3. Hot-path cache layer

Bottleneck #1 forces us to keep Redis in the production stack even after the substrate migration. Substrate becomes the system of record; Redis is the hot read cache.

### 4. CSR-based analytical view investigation

Bottleneck #2 is the open question. ArcadeDB 26.3.x introduced CSR-based Graph Analytical Views which (if enabled for our query patterns) provide lock-free parallel graph reads. We need to:

- Validate that CSR view works for our 2-3 hop BFS workload
- Measure throughput and latency under the same benchmark conditions
- Decide whether to use CSR view as the default or fall back to traditional traversal for write-heavy workloads

This is in the Q2 2026 engineering roadmap.

---

## Honest claim discipline (what we say externally vs internally)

The website says "[TARGET] <10ms graph traversal" and "[TARGET] 80% token reduction." These are true *as targets* for the unified ContextD product, but they are not benchmarked at production scale. Internally we say:

> **Graph traversal:** 1.90ms p50 single-thread on 475K vertices. Plateaus at ~600 ops/sec @ 4 threads under the current substrate; targeted to scale linearly with read replicas + CSR view.
>
> **Hybrid retrieval:** 47ms p50 single-thread, ~137 ops/sec peak throughput on the substrate as-tested. Targeted at <50ms p50 + 1000+ ops/sec aggregate via horizontal scaling per the architectural responses above.
>
> **Token reduction:** structurally achievable (~80% target) via dedup + temporal pruning + feedback weighting. Actual reduction depends on workload, graph density, and feedback maturity.

When VCs ask, we share the benchmark numbers. When they ask why we believe the targets, we walk through the architectural responses. Both sets of numbers are real; neither is fudged.

---

## Raw appendix tables

For completeness, the full per-thread breakdown.

### Point Lookup

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,205.6 | 0.77 | 0.83 | 0.90 | 0.76 | 14.0 | 2,593 |
| 4 | 1,422.9 | 2.40 | 4.80 | 6.40 | 2.52 | 21.8 | 3,166 |
| 8 | 1,442.7 | 4.56 | 10.70 | 14.22 | 5.17 | 40.5 | 3,216 |
| 16 | 1,455.6 | 8.83 | 22.59 | 31.33 | 10.36 | 219.9 | 3,288 |
| 32 | 1,413.8 | 17.94 | 47.87 | 65.79 | 21.21 | 329.7 | 3,068 |
| 64 | 1,339.9 | 35.67 | 108.00 | 151.13 | 44.97 | 219.9 | 2,958 |
| 128 | 1,199.6 | 82.13 | 238.43 | 329.67 | 100.10 | 329.7 | 2,669 |

> Errors note: ~7% point-lookup errors caused by special characters in DBpedia URIs breaking SQL string escaping — *not* an ArcadeDB bug. Production code uses parameterized queries.

### Full-Text Search (BM25)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 279.1 | 3.96 | 7.30 | 8.40 |
| 4 | 783.5 | 5.28 | 10.07 | 11.80 |
| 8 | 1,245.7 | 6.21 | 13.00 | 17.00 |
| 16 | 1,424.8 | 10.56 | 22.06 | 28.48 |
| 32 | 1,480.3 | 19.90 | 43.72 | 57.74 |
| 64 | 1,439.2 | 38.81 | 101.27 | 139.16 |
| 128 | 1,287.6 | 86.22 | 234.18 | 328.75 |

### Graph 1-Hop Traversal

| Threads | ops/sec | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 302.9 | 1.90 | 10.54 | 17.68 |
| 4 | 591.4 | 5.15 | 17.39 | 28.36 |
| 8 | 595.5 | 9.84 | 36.01 | 59.58 |
| 16 | 582.9 | 22.25 | 65.99 | 116.05 |
| 32 | 549.3 | 55.02 | 81.38 | 102.20 |
| 64 | 530.5 | 82.00 | 356.04 | 622.01 |
| 128 | 533.5 | 228.31 | 334.09 | 733.51 |

### Vector Search (HNSW ANN, 1024-dim, top-10)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 23.3 | 42.29 | 55.11 | 62.86 |
| 4 | 90.7 | 42.81 | 57.38 | 65.17 |
| 8 | 156.7 | 49.92 | 68.87 | 81.21 |
| 16 | 154.6 | 101.79 | 145.76 | 167.33 |
| 32 | 144.0 | 218.85 | 314.79 | 366.10 |
| 64 | 145.3 | 439.88 | 553.23 | 665.16 |
| 128 | 139.5 | 871.14 | 1553.83 | 1992.42 |

### Full Hybrid (Vector + FTS + Graph)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 20.9 | 47.31 | 59.17 | 66.93 |
| 4 | 78.1 | 50.29 | 66.27 | 80.30 |
| 8 | 133.1 | 58.05 | 82.20 | 127.88 |
| 16 | 134.8 | 116.34 | 164.62 | 190.24 |
| 32 | 137.3 | 230.40 | 344.88 | 405.80 |
| 64 | 132.1 | 485.20 | 739.32 | 866.98 |
| 128 | 128.6 | 975.59 | 1625.30 | 2105.07 |

---

## Known limitations of this benchmark

1. **Single server.** No clustering / replication tested. Real production architecture uses leader + read replicas — likely 3-5× higher aggregate throughput.
2. **475K-entity dataset.** Numbers at 5M+ would show different profiles, especially for vector search. We will rerun at scale on the production substrate.
3. **4-vCPU client.** At 128 threads, client-side scheduling overhead may inflate latency. Production clients are bigger.
4. **Synthetic concurrency.** Benchmark uses Python with `requests` and connection-pooled HTTP sessions. Real workload mix has different inter-arrival patterns.
5. **Python GIL.** Client-side threads share GIL but workload is I/O-bound so impact is minimal.

We're transparent about all of these. Subsequent benchmarks (planned Q3 2026) will exercise replication, scale, and real workload patterns.

---

*Continue to `10-roadmap-and-build-plan.md` for how the benchmark findings translate into the engineering roadmap, or `11-technical-capabilities.md` for what makes this defensible.*
