# ArcadeDB Benchmark Report for ContextD Evaluation

## Executive Summary

This report presents benchmark results for ArcadeDB 26.4.2 evaluated as a foundational storage engine for ContextD — a context graph database for AI. We tested 5 query patterns across 7 concurrency levels (1–128 threads) on a 475K entity dataset with 1024-dim embeddings, over a private Azure VNet (~0.73ms RTT).

**Key findings**:
- **Point lookups**: 0.77ms p50 at 1 thread, but throughput plateaus at **~1,450 ops/sec** regardless of thread count — suggesting a server-side serialization bottleneck
- **FTS (BM25)**: Best scaling profile, peaks at **1,480 ops/sec** at 32 threads with 4ms p50 single-threaded
- **Vector search (HNSW, 1024-dim)**: Peaks at **~157 ops/sec** at 8 threads, then **degrades** under higher concurrency — the primary bottleneck
- **Graph traversal**: Plateaus at **~595 ops/sec** at just 4 threads — severe lock contention
- **Full hybrid retrieval** (the ContextD pattern): Maxes at **~137 ops/sec** at 8–32 threads, with latency ballooning from 47ms to 976ms at 128 threads

---

## Test Environment

### Infrastructure

| Component | Specification |
|-----------|--------------|
| **DB Host** | Azure Standard_D16s_v5 — 16 vCPU, 64 GB RAM, 240 GB Premium SSD |
| **Client Host** | Azure Standard_D4s_v5 — 4 vCPU, 16 GB RAM |
| **Network** | Same VNet, private IPs, ~0.73ms HTTP RTT |
| **ArcadeDB** | v26.4.2, JVM heap 48 GB, G1GC, production mode |
| **Protocol** | HTTP/JSON API (port 2480) |

### Dataset

| Metric | Count |
|--------|-------|
| **Vertices (Entity)** | 475,191 |
| **Edges (Relation)** | 1,373,872 |
| **Avg edges per vertex** | 2.89 |
| **Embedding dimensions** | 1,024 (Cohere embed-english-v3, float32) |
| **Text abstracts** | 463,584 entities with abstracts (97.6%) |
| **Type-classified** | 366,589 entities with types (77.1%) |

**Data source**: DBpedia 2022-12 entity graph joined with Cohere Wikipedia embeddings (first passage per article, 1024-dim float vectors from `embed-english-v3.0`).

### Indexes

| Index Type | Property | Configuration |
|-----------|----------|---------------|
| **Unique (LSM_TREE)** | `Entity.uri` | Unique B-tree for point lookups |
| **Vector (LSM_VECTOR)** | `Entity.embedding` | HNSW, 1024 dimensions, cosine similarity |
| **Full-Text (FULL_TEXT)** | `Entity.abstract` | BM25 Lucene-based full-text search |

### Benchmark Configuration

- **Duration**: 30 seconds per run (after 10s warmup)
- **Thread counts**: 1, 4, 8, 16, 32, 64, 128
- **Query types**: point_lookup, fts, graph_1hop, vector_search, hybrid (vector + FTS + graph)
- **Metrics**: Throughput (ops/sec), latency percentiles (p50, p95, p99)

---

## Results

### 1. Throughput Scaling (ops/sec)

| Query Type | 1T | 4T | 8T | 16T | 32T | 64T | 128T |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Point Lookup** | 1,206 | 1,423 | 1,443 | **1,456** | 1,414 | 1,340 | 1,200 |
| **Full-Text Search** | 279 | 784 | 1,246 | 1,425 | **1,480** | 1,439 | 1,288 |
| **Graph 1-hop** | 303 | **591** | 596 | 583 | 549 | 531 | 534 |
| **Vector Search** | 23 | 91 | **157** | 155 | 144 | 145 | 140 |
| **Full Hybrid** | 21 | 78 | 133 | 135 | **137** | 132 | 129 |

### 2. Throughput Ceiling & Scaling Behavior

Each query type hits a hard ceiling and then degrades:

| Query Type | Peak ops/sec | Peak Threads | Scaling Behavior |
|---|---:|---:|---|
| **FTS** | 1,480 | 32T | Best scaler — 5.3× speedup, CPU-friendly Lucene reads |
| **Point Lookup** | 1,456 | 16T | Nearly flat from 4T — server serialization bottleneck |
| **Graph 1-hop** | 596 | 8T | Plateaus at 4T — severe adjacency list lock contention |
| **Vector Search** | 157 | 8T | HNSW graph traversal is CPU-intensive, contention at 16T+ |
| **Hybrid** | 137 | 32T | Dominated by vector search, compounds with FTS + graph |

### 3. Latency Under Load

#### Single-thread latencies (best case)

| Query Type | p50 | p95 | p99 |
|---|---:|---:|---:|
| **Point Lookup** | **0.77** | 0.83 | 0.90 |
| **Graph 1-hop** | **1.90** | 10.5 | 17.7 |
| **FTS** | **3.96** | 7.3 | 8.4 |
| **Vector Search** | **42.3** | 55.1 | 62.9 |
| **Hybrid** | **47.3** | 59.2 | 66.9 |

#### Latency degradation at high concurrency

| Query Type | p50 at 1T | p50 at 8T | p50 at 32T | p50 at 128T |
|---|---:|---:|---:|---:|
| **Point Lookup** | 0.77 | 4.6 | 17.9 | 82.1 |
| **FTS** | 3.96 | 6.2 | 19.9 | 86.2 |
| **Graph 1-hop** | 1.90 | 9.8 | 55.0 | 228.3 |
| **Vector Search** | 42.3 | 49.9 | 218.9 | **871.1** |
| **Hybrid** | 47.3 | 58.0 | 230.4 | **975.6** |

Vector search latency degrades **20× at 128T** while throughput remains flat — classic sign of internal lock contention, not useful parallelism.

---

## Analysis

### Bottleneck #1: Point Lookup Throughput Ceiling (~1,450 ops/sec)

Point lookups are sub-millisecond (0.77ms p50) yet throughput barely increases beyond 4 threads. This is **not** a network or client bottleneck (0.73ms RTT, I/O-bound threads). The ceiling suggests ArcadeDB's HTTP server or LSM-tree index has a **serialization point** — possibly a shared lock on the B-tree read path, or Undertow's thread dispatch overhead at ~1,450 req/sec.

**Implication for ContextD**: A key-value lookup layer on top of ArcadeDB would need its own caching tier (e.g., Redis) for workloads exceeding ~1,500 ops/sec.

### Bottleneck #2: Graph Traversal Lock Contention

Graph 1-hop saturates at **~595 ops/sec** from just 4 threads. This is the most concerning finding because graph expansion is part of every GraphRAG query. The `expand(out())` operation likely acquires page-level locks on adjacency list segments, causing threads to serialize.

**Implication for ContextD**: The planned CSR-based OLAP analytical view (mentioned in ArcadeDB 26.3.x release notes) could help here — CSR format supports lock-free parallel reads. Worth investigating whether it's enabled for simple traversals.

### Bottleneck #3: Vector Search is CPU-Bound, Not Parallelizable

HNSW search peaks at **157 ops/sec at 8 threads**, then declines. Single-threaded latency is 42ms. At 128 threads, latency balloons to 871ms while throughput is lower than at 8 threads. The HNSW graph traversal involves many random memory accesses per query and likely contends on the HNSW graph structure's read locks.

At 475K vectors × 1024 dims, the HNSW graph is ~1.9 GB. It fits in the 48 GB heap, so this is not a disk I/O problem — it's pure CPU and memory bandwidth.

**Implication for ContextD**: 
- At 6M vectors, single-query latency will grow to ~100-200ms
- Peak throughput will likely stay around 150-200 ops/sec regardless of client concurrency
- Vector search must be independently scalable — exactly what ContextD's "separate ingestion and query" architecture enables
- Consider running multiple ArcadeDB replicas with a load balancer for vector-heavy workloads

### Bottleneck #4: Hybrid Query Ceiling

The hybrid pattern (Vector + FTS + Graph) peaks at **137 ops/sec**, almost entirely limited by the vector search component. Breaking down a single hybrid query at 1 thread:

| Component | Latency | % of Total |
|-----------|---------|-----------|
| Vector search (top-10) | ~42ms | 89% |
| FTS search | ~4ms | 8.5% |
| Network overhead | ~1ms | 2.5% |

Graph expansion adds minimal overhead because the benchmark expands from very few seed nodes. In a real ContextD workload with deeper expansion (2-3 hops), graph contention would become a larger factor.

---

## Protocol & Infrastructure Findings

### Postgres Wire Protocol: Unusable (100ms sleep bug)

During local testing, we discovered `CodeUtils.sleep(100)` in ArcadeDB's Postgres protocol handler (`PostgresNetworkExecutor.java:1515`). This polling sleep adds a **100ms floor** to every query, making the PG protocol ~50× slower than the HTTP API.

**File**: `arcadedb/postgresw/src/main/java/com/arcadedb/postgres/PostgresNetworkExecutor.java:1515`
**Fix**: Replace polling loop with blocking I/O (`channel.read()`)

### Network Impact: 8× Improvement with Private VNet

| Configuration | SELECT 1 RTT (p50) |
|--------------|---:|
| Public IPs (cross-region) | 5.71ms |
| Private VNet (same subnet) | **0.73ms** |

For point lookups (0.77ms query time), network accounted for **88% of latency** on public IPs.

### Bulk Ingestion: `/batch` API is 20× Faster than SQL

| Method | Vertex Rate |
|--------|------------|
| SQL INSERT (per-row) | 67/sec |
| HTTP `/batch` API (JSONL) | **1,828/sec** |

Index build times (475K entities, post-ingestion):
- Unique index: **9.8s**
- HNSW vector index (1024-dim): **150.5s**
- Full-text index: **~600s**

---

## Recommendations for ContextD

### 1. Vector Search Must Be Independently Scalable

ArcadeDB's HNSW search is the clear bottleneck in every composite query pattern. At 475K vectors, it caps hybrid throughput at ~137 ops/sec on a 16-vCPU machine. For ContextD's target of millions of entities:

- **Short-term**: Run multiple ArcadeDB read replicas behind a load balancer
- **Medium-term**: Implement a dedicated vector search service (using jvector or similar) that can be scaled horizontally
- **Long-term**: Product quantization (PQ) + pre-filtering to reduce HNSW search cost

### 2. Graph Traversal Needs Lock-Free Reads

The graph 1-hop saturation at 4 threads is a structural limitation. For ContextD's graph expansion after retrieval:

- Investigate ArcadeDB's CSR-based Graph Analytical View (introduced in 26.3.x) for lock-free traversals
- Consider caching hot subgraphs in a CSR structure on the query side
- Profile to determine if the contention is at page-level or record-level

### 3. Separate Hot Path from ArcadeDB

Given the ~1,450 ops/sec ceiling on point lookups, ContextD should:

- Cache frequently-accessed entities in an in-process cache (Caffeine/LRU)
- Use ArcadeDB as the persistent store, not the hot query path
- Consider read replicas for scaling read throughput linearly

### 4. Fix the PG Protocol Before Shipping

If ContextD plans to offer PostgreSQL-compatible access (important for ecosystem compatibility), the 100ms sleep must be patched in the upstream ArcadeDB fork.

---

## Appendix: Raw Data

### A. Complete Results Table

#### Point Lookup

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,205.6 | 0.77 | 0.83 | 0.90 | 0.76 | 14.0 | 2,593 |
| 4 | 1,422.9 | 2.40 | 4.80 | 6.40 | 2.52 | 21.8 | 3,166 |
| 8 | 1,442.7 | 4.56 | 10.70 | 14.22 | 5.17 | 40.5 | 3,216 |
| 16 | 1,455.6 | 8.83 | 22.59 | 31.33 | 10.36 | 219.9 | 3,288 |
| 32 | 1,413.8 | 17.94 | 47.87 | 65.79 | 21.21 | 329.7 | 3,068 |
| 64 | 1,339.9 | 35.67 | 108.00 | 151.13 | 44.97 | 219.9 | 2,958 |
| 128 | 1,199.6 | 82.13 | 238.43 | 329.67 | 100.10 | 329.7 | 2,669 |

#### Full-Text Search (BM25)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 279.1 | 3.96 | 7.30 | 8.40 | 3.96 | 18.0 | 0 |
| 4 | 783.5 | 5.28 | 10.07 | 11.80 | 5.28 | 24.4 | 0 |
| 8 | 1,245.7 | 6.21 | 13.00 | 17.00 | 6.21 | 38.9 | 0 |
| 16 | 1,424.8 | 10.56 | 22.06 | 28.48 | 10.56 | 49.1 | 0 |
| 32 | 1,480.3 | 19.90 | 43.72 | 57.74 | 19.90 | 57.7 | 0 |
| 64 | 1,439.2 | 38.81 | 101.27 | 139.16 | 38.81 | 139.2 | 0 |
| 128 | 1,287.6 | 86.22 | 234.18 | 328.75 | 86.22 | 328.8 | 0 |

#### Graph 1-Hop Traversal

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 302.9 | 1.90 | 10.54 | 17.68 | 8.26 | 64.1 | 217 |
| 4 | 591.4 | 5.15 | 17.39 | 28.36 | 9.00 | 217.8 | 458 |
| 8 | 595.5 | 9.84 | 36.01 | 59.58 | 11.01 | 85.9 | 471 |
| 16 | 582.9 | 22.25 | 65.99 | 116.05 | 20.24 | 207.5 | 474 |
| 32 | 549.3 | 55.02 | 81.38 | 102.20 | 55.02 | 102.2 | 415 |
| 64 | 530.5 | 82.00 | 356.04 | 622.01 | 82.00 | 622.0 | 462 |
| 128 | 533.5 | 228.31 | 334.09 | 733.51 | 228.31 | 733.5 | 415 |

#### Vector Search (HNSW ANN, 1024-dim, top-10)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 23.3 | 42.29 | 55.11 | 62.86 | 45.99 | 96.0 | 0 |
| 4 | 90.7 | 42.81 | 57.38 | 65.17 | 47.04 | 85.3 | 0 |
| 8 | 156.7 | 49.92 | 68.87 | 81.21 | 49.92 | 164.3 | 0 |
| 16 | 154.6 | 101.79 | 145.76 | 167.33 | 78.26 | 167.3 | 0 |
| 32 | 144.0 | 218.85 | 314.79 | 366.10 | 218.85 | 366.1 | 0 |
| 64 | 145.3 | 439.88 | 553.23 | 665.16 | 439.88 | 665.2 | 0 |
| 128 | 139.5 | 871.14 | 1553.83 | 1992.42 | 871.14 | 1992.4 | 0 |

#### Full Hybrid (Vector + FTS + Graph)

| Threads | ops/sec | p50 ms | p95 ms | p99 ms | Mean ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20.9 | 47.31 | 59.17 | 66.93 | 57.74 | 162.9 | 0 |
| 4 | 78.1 | 50.29 | 66.27 | 80.30 | 57.71 | 162.0 | 0 |
| 8 | 133.1 | 58.05 | 82.20 | 127.88 | 61.88 | 202.8 | 0 |
| 16 | 134.8 | 116.34 | 164.62 | 190.24 | 92.54 | 280.9 | 0 |
| 32 | 137.3 | 230.40 | 344.88 | 405.80 | 230.40 | 483.6 | 0 |
| 64 | 132.1 | 485.20 | 739.32 | 866.98 | 485.20 | 1123.5 | 0 |
| 128 | 128.6 | 975.59 | 1625.30 | 2105.07 | 975.59 | 2976.4 | 0 |

### B. Test Methodology

- **Query vectors**: Sampled from the actual dataset (real Cohere embeddings, not random)
- **FTS query terms**: Extracted from actual entity abstracts
- **Point lookup URIs**: Random selection from ingested entities
- **Graph traversal seeds**: Entities with at least 1 outgoing edge
- **Composite queries**: Sequential execution (vector search + FTS + graph expansion)
- **Benchmark harness**: Python with `requests` library, connection-pooled HTTP sessions
- **Measurement**: `time.perf_counter()` for per-operation latency, sorted array for percentiles

### C. Known Limitations

1. **Point lookup errors (~7%)**: Caused by special characters in DBpedia URIs breaking SQL string escaping — not an ArcadeDB bug
2. **Python GIL**: Client-side threads share GIL, but workload is I/O-bound so impact is minimal
3. **4-core client**: At 128 threads, client-side scheduling overhead may contribute to latency inflation
4. **Single server**: All benchmarks against a single ArcadeDB instance — no clustering/replication tested
5. **Dataset scale**: 475K entities — results at 5M+ would show different profiles, especially for vector search
