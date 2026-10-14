# 10 — Roadmap & Build Plan

> Phase plan from the current multi-DB stack to the unified substrate. Every milestone is grounded in either current shipping code or measured numbers from `09-benchmarks-and-validation.md`. Each phase lists scope, validation, and exit criteria.

---

## Starting point

The starting point is a multi-database production stack: PostgreSQL for tenant metadata, Neo4j for graph and full-text, Milvus for vectors, Redis for hot caching, Temporal for durable workers, FastAPI for the API surface, ~40 source connectors, 30+ OAuth providers. Working end-to-end today: a 10-step ingestion pipeline, a 5-phase entity-resolution cascade, a streaming EMA feedback engine, federated hybrid search, and a streaming chat/RAG service.

The substrate has been benchmarked end-to-end against a realistic dataset; bottlenecks (HNSW lock contention, adjacency-list page locks, HTTP server ceiling) are quantified with specific engineering responses (see `09-benchmarks-and-validation.md`).

---

## The migration target

A single unified database with the ContextD intelligence layer on top of an Apache 2.0 multi-model substrate (ArcadeDB, see `09-benchmarks-and-validation.md` and `14-references.md`):

```
┌─────────────────────────────────────────────────────────────────┐
│  ContextD intelligence layer                                    │
│    bitemporal schema + 10-step ingestion                        │
│    + 5-phase entity resolution + Resolver Engine                │
│    + 7-step context assembly with token budgeting               │
│    + streaming EMA feedback (α=0.1)                             │
│    + ontology engine                                            │
│    + Context Cores (versioned snapshots)                        │
│    + decision lineage (first-class entities)                    │
├─────────────────────────────────────────────────────────────────┤
│  Multi-model substrate                                          │
│    Graph + Vector (HNSW/PQ) + Full-Text (BM25) + Document       │
│    + KV + Time-Series (Gorilla XOR) — single ACID engine        │
│    + native graph algorithms with SIMD acceleration             │
│    + native MCP server                                          │
│    + six wire protocols (Bolt/PG/Mongo/Redis/gRPC/HTTP)         │
└─────────────────────────────────────────────────────────────────┘
```

The unified substrate subsumes the current Neo4j (graph + full-text) and Milvus (vectors) roles. PostgreSQL, Redis, and Temporal remain in their current orthogonal roles (billing/account metadata, hot cache, durable workers) — they are not in the migration scope.

---

## Phased roadmap

### Phase 1 (Q3 2026) — Storage Foundation

**Engineering scope (Weeks 1-3):**
- ArcadeDB Docker container in dev environment with all 6 protocol ports exposed
- `ArcadeDBDriver` (async HTTP, command + query + Cypher methods, connection pooling via httpx)
- Schema initialization (all 7 vertex types + 7 edge types, HNSW vector indexes on `Entity.name_embedding` + `RELATES_TO.fact_embedding`, full-text indexes on `Entity.name` + `RELATES_TO.fact`, unique indexes on IDs)
- Pydantic v2 model layer (Entity, Episode, Fact, Relationship, Saga, Community, Decision; LLM output models for structured extraction)

**Why this comes first:** every subsequent phase needs the substrate driver and schema. Standalone validation: write 1M test entities via `/batch` API, verify HNSW + FTS index build times match benchmark (~150s + ~600s for 475K entities).

**Exit criteria:** schema loads idempotently, driver passes round-trip tests for all 6 vertex types and all CRUD ops, baseline `/batch` ingest rate matches benchmark (~1,828 vertices/sec).

### Phase 2 (Q3-Q4 2026) — Context Forge

**Why this comes before the ingestion pipeline.** The pipeline reads the Forge Mapping as configuration (see Forge-to-Pipeline Bridge in `06-context-forge.md`). Without Atlas, the pipeline falls back to LLM-only extraction for structured sources — expensive and unreliable. Phase 2 must ship before Phase 3.

**Engineering scope (Weeks 4-9):**
- **Source Introspector adapters** for Postgres, MySQL, SQL Server, Snowflake, BigQuery (the v1 priority set; Oracle / Databricks / ClickHouse follow in Phase 7 connector wave)
- **Data Profiler** — HyperLogLog cardinality, Count-Min Sketch top-K, regex pattern library, Presidio-based PII detection, mutual-information cross-column correlation
- **Business Logic Ingester** — dbt manifest.json + sources.yml + schema.yml parser; LookML view/model/explore parser; SQL view + stored-procedure parser via SQLGlot; MetricFlow / Cube.dev YAML parser; plain-language metric definition (LLM-assisted structured extraction)
- **Mapping Inference Engine** — seven inference passes (table→entity, FK→relationship, junction-table detection, column→fact-predicate, time-series/audit recognition, derived-metric translation, confidence scoring)
- **Forge Mapping artifact** — msgpack serialization + SHA-256 content addressing (reuses Context Cores serialization machinery, ship in Phase 7)
- **Forge Studio v1** — three-pane UI (source schema | mapping | graph preview), inline edit, validation panel, sample-data trace, smoke-test queries, version diff
- **Forge Profiles** — initial set: Salesforce, HubSpot, Stripe, dbt-Snowflake, generic OLTP Postgres
- **Forge-to-Pipeline Bridge** — interface contract for the Phase 3 pipeline to consume Forge Mappings

**Validation:** onboard a real enterprise customer's Snowflake + dbt project end-to-end. Goal: from connect-to-source to applied Forge Mapping in under 4 hours; ≥80% of inferred mappings accepted by customer without modification; ≥60% LLM cost reduction vs LLM-only extraction baseline on the same dataset.

**Exit criteria:** Forge Mapping v1 saves and rollbacks work; Forge Studio renders three-pane UI for a real Snowflake source; Bridge interface frozen so Phase 3 can build against it.

### Phase 3 (Q4 2026 – Q1 2027) — Ingestion Pipeline (Forge-aware)

**Engineering scope (Weeks 10-13):**
- LLM client with structured output via OpenAI function calling + Pydantic validation (already implemented, needs porting from current `backend/contextd/platform/llm/`)
- 10-step pipeline runner (orchestrator) wired to substrate driver
- **Forge Mapping reader** — pipeline consumes the artifact emitted by Phase 2; routes each source episode to deterministic vs LLM extraction paths
- Entity extraction (Step 3) — deterministic for Forge-covered tables; Jinja2 prompts + previous episode context + ontology subset for unstructured fields
- Entity resolution (Steps 4-5) — port datasketch MinHash/LSH, numpy cosine, LLM final from current `entity_resolution.py`
- Edge extraction (Step 6) — deterministic from Atlas FK definitions; LLM-driven for unstructured sources; ontology domain/range enforced
- Edge dedup/supersession (Step 7)
- Embedding generation (Step 8) via OpenAI batch API
- Bulk save to substrate (Step 9) using `/batch` API
- **Derived-fact computation pass** — runs after Step 9; computes Forge-derived metrics (LTV, health_status, etc.) from customer-supplied formulas; emits derived facts with provenance
- Community detection (Step 10) — Louvain/LP via substrate-native graph algorithms

**Validation:** ingest the benchmark dataset (475K DBpedia entities) end-to-end through the pipeline; verify entity dedup rate ~80% before LLM, total LLM cost per 1K episodes within budget. Then ingest the design-partner Snowflake+dbt dataset using their applied Forge Mapping; verify dbt-defined metrics appear as derived facts; LLM cost reduction matches Phase 2 target (≥60%).

**Exit criteria:** ingestion pipeline completes 1M episodes end-to-end without manual intervention; deterministic and LLM extraction paths both functional; provenance stamping on every element including Forge-derived facts (`extraction_method = forge_derived_metric`); OpenTelemetry spans for every step.

### Phase 4 (Q1 2027) — Context Resolver

**Why this comes early.** Cross-source identity stitching is the technical core of ContextD's unification claim. The Resolver Engine reads the same Forge Mapping that configures ingestion (Phase 2/3), uses the substrate's HNSW vector index (Phase 1) for blocking, and outputs the bitemporal Identity Graph that downstream retrieval (Phase 5) and decision lineage queries depend on. Phase 4 must ship before retrieval to ensure cross-source queries work correctly.

**Engineering scope (Weeks 12-15):**
- **Resolver Engine — six stages** (cost-cascading; no fuzzy-string heuristics as primary signals):
  - **Stage A — Blocking:** HNSW vector ANN over entity-embedding space (substrate-native), DeepBlocker-style learned blocking on tabular attributes, 3-gram MinHash + LSH on textual fields via `datasketch`
  - **Stage B — Probabilistic record linkage:** Fellegi-Sunter framework; per-attribute m-probability + u-probability; EM-learned parameters per source domain; Platt-scaled / isotonic-calibrated thresholds
  - **Stage C — Neural pairwise matching:** DITTO-style cross-encoder (RoBERTa or DeBERTa-v3 base, ~110M params); supervised contrastive + triplet loss; bi-encoder fast-path for high-volume streams; ~5K pairs/sec on a single GPU
  - **Stage D — Coreference resolution for unstructured text:** GLiNER (zero-shot NER) + RoBERTa-NER (fine-tuned); within-document e2e-coref / MaverickCoref; Cross-Document Coreference Resolution (CDCR) for mention alignment across documents
  - **Stage E — Identity Graph stitching:** confidence-weighted edges in the substrate; Probabilistic Soft Logic transitive closure; conflict detection on non-match constraints; soft-link mode for low-confidence stitches; bitemporal annotations on every edge
  - **Stage F — Active learning + LLM adjudication:** uncertainty-sampling queue; query-by-committee fine-tune loop; LLM few-shot / chain-of-thought adjudication for residual ~1-2%
- **Identity Graph schema** in substrate — vertex per `canonical_id`, edges to source-record-IDs with `(source, source_id, confidence, evidence, valid_at, invalid_at, created_at, expired_at)`; attribute-consensus reconciliation; complete audit trail
- **Resolver Studio v1** — three queues (active-learning, conflict, identity-graph explorer); inline pair review; bulk operations; Stage C confidence + Stage B Fellegi-Sunter score breakdown per pair
- **Initial Resolver Profiles:** `person-crm`, `person-engineering`, `organization-account` (each bundles a fine-tuned cross-encoder, Fellegi-Sunter attribute schema, NER model selection, calibrated decision threshold)
- **Resolver-to-Pipeline Bridge** — pipeline Steps 4-5 + 7 invoke the Resolver Engine for non-deterministic records; Identity Graph atomic update at Step 9; Studio review queue surfaces alongside Forge Studio

**Validation.** Onboard a real customer with at least four heterogeneous sources (Salesforce + Gmail + Slack + GitHub or similar). Goal: cross-source unification accuracy ≥ 95% (precision) on a labeled holdout set; active-learning loop converges within 200-500 labels for a novel domain; bitemporal supersession on identifier link changes works end-to-end without orphan records.

**Exit criteria.** Cross-source queries (e.g., *"all artifacts authored by Alice Chen across all sources"*) return correct results; Identity Graph survives a tenant-wide rebuild without merge conflicts; active-learning queue is operational with measurable model-improvement turnaround.

### Phase 5 (Q1–Q2 2027) — Hybrid Retrieval Engine

**Engineering scope (Weeks 8-11):**
- BM25 search via substrate full-text index
- Cosine search via substrate HNSW vector index
- BFS traversal via substrate Cypher
- All three running in parallel via `asyncio.gather`
- Reranker implementations: RRF (default), MMR, Cross-Encoder, Node Distance, Episode Mentions
- 7-step context assembly with `tiktoken` token budgeting
- Pre-built search recipes (`COMBINED_HYBRID_SEARCH_RRF`, `EDGE_HYBRID_SEARCH_RRF`, `NODE_HYBRID_SEARCH_RRF`, ...)

**Validation:** golden query suite (50 queries) compared between current Neo4j+Milvus stack and unified substrate. Goal: substrate matches or exceeds quality on every query, with end-to-end latency within benchmark prediction (47ms p50 single-thread, scaling to budgeted multi-tenant aggregate).

**Exit criteria:** context assembly returns valid JSON for all golden queries; metadata fields (`tokens_used`, `tokens_saved_vs_chunk_rag`, `query_latency_ms`, `avg_feedback_weight`) populated correctly.

### Phase 6 (Q2 2027) — Feedback & Learning

**Engineering scope (Weeks 12-13):**
- Streaming EMA feedback engine on substrate (port from current Postgres-backed engine)
- Idempotency via `memify_metadata` flag
- Audit logging
- Auto-feedback detection prototype (LLM-based analysis of conversation turns for implicit feedback)

**Why this is short:** the EMA math and idempotency logic are already implemented and tested in the current stack — Phase 4 is largely a port to the substrate's UPDATE syntax, plus the new auto-feedback prototype.

**Exit criteria:** 100K feedback events processed end-to-end; entity weights converge correctly under repeated feedback; feedback events appear in audit log.

### Phase 7 (Q2 2027) — Ontology Engine

**Engineering scope (Weeks 14-15):**
- Embed ontology elements via OpenAI
- Semantic routing (cosine match per chunk, top-k 10, threshold 0.3)
- Dependency resolution (parent classes via `subclass_of`, domain/range types)
- Jinja2 prompt injection
- Validation (class filter, domain/range, cardinality, disjoint)
- Pre-built ontologies: CRM, Support, Engineering, Marketing

**Validation:** ingest the same dataset twice — once without ontology, once with CRM ontology. Measure: % of "Vehicle"-style hallucinated types eliminated, % of domain/range violations caught, total entity count delta.

**Exit criteria:** ontology can be enabled/disabled per ingestion job; pre-built ontologies ship with the SDK.

### Phase 8 (Q2-Q3 2027) — Context Cores

**Engineering scope (Weeks 16-17):**
- Build operation: snapshot graph + embeddings + ontology + retrieval policies + feedback weights → msgpack-serialized + SHA-256 hashed
- Test operation: load core into staging, run query suite, score against expected results
- Promote / rollback (instant pointer swap)
- Diff (compare two cores)

**Validation:** build a core from production graph, simulate a "bad migration" (corrupt 5% of edges), verify rollback restores correct state in <1s.

**Exit criteria:** golden CI/CD workflow demoable: build → test → diff → promote → rollback. End-to-end CLI feature complete.

### Phase 9 (Q3 2027) — API & Connectors port

**Engineering scope (Weeks 18-21):**
- FastAPI server (already exists, port routes to substrate backend)
- MCP server (custom multi-transport: stdio for local AI tools like Claude Code/Cursor/Windsurf, SSE for web frameworks, HTTP for serverless)
- Two-layer MCP architecture: substrate built-ins + ContextD context tools (`query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `get_saga_summary`, `submit_feedback`, `ingest_episode`)
- Migrate existing 40 connectors to use substrate driver
- Airbyte integration for the 600+ P1 sources (Docker sidecar)

**Exit criteria:** all current API endpoints + MCP tools backed by substrate; existing customers migrate seamlessly; Claude Code agent can connect to a ContextD instance via stdio MCP and call `query_context`.

### Phase 10 (Q3-Q4 2027) — Observability, RBAC, Compliance

**Engineering scope (Weeks 22-24):**
- OpenTelemetry tracing across all subsystems with semantic span attributes
- Prometheus metric exposition
- RBAC middleware enforcing 6 roles + 3 scoping dimensions
- Audit logging (append-only, immutable, queryable)
- API key management (SHA-256 hashed, revocable)
- Multi-tenancy enforcement (separate substrate database per tenant)
- SOC 2 Type I controls implemented (Month 9)
- GDPR compliance (right to deletion cascade, data residency selection, consent tracking)

**Exit criteria:** SOC 2 Type I auditor signoff; pen-test pass; multi-tenant isolation validated by external review.

---

## Compliance & enterprise readiness timeline

| Standard | Timeline | Scope |
|----------|----------|-------|
| **GDPR** | Cloud launch (Q3 2027) | Data residency, right to deletion, consent tracking |
| **SOC 2 Type I** | Month 9 (Q1 2027) | Controls documentation, audit readiness |
| **SOC 2 Type II** | Month 15 (Q3 2027) | Full audit, 6-month observation |
| **ISO 27001** | Month 18 (Q4 2027) | ISMS |
| **HIPAA** (optional) | Q1 2028 if pulled by customers | Healthcare data handling |
| **FedRAMP** (optional) | 2028+ if pulled by gov customers | Federal authorization |

## Cloud launch sequence

| Quarter | Milestone |
|---------|-----------|
| Q4 2026 | Private design-partner deployments (3-5 customers, on-prem or single-tenant managed) |
| Q1 2027 | Public managed beta — multi-tenant cloud, pay-as-you-go credits |
| Q2 2027 | Public managed GA — SLAs, region selection, audit log retention tiers |
| Q3 2027 | Enterprise GA — air-gapped install, HA clustering, dedicated tenancy, SOC 2 Type II |
| Q4 2027 | ContextD Cloud regions: us-east, us-west, eu-west, ap-southeast |

---

## Technical KPIs

| Metric | Target end of Phase 5 | Target end of Phase 10 |
|--------|----------------------|------------------------|
| Aggregate ingestion rate | 1M episodes/day | 100M episodes/day |
| Connectors operational | ~40 | 80+ deep-extract + 600+ via Airbyte quality layer |
| Context-assembly p50 latency | < 100 ms | < 50 ms |
| Context Forge onboarding time (connect → applied mapping) | < 4 h | < 1 h via Forge Profiles |
| Context Forge inference acceptance rate (no manual edits) | ≥ 80 % | ≥ 90 % |
| LLM-cost reduction vs LLM-only baseline (structured-data customers) | ≥ 60 % | ≥ 75 % |
| Resolver acceptance rate at Stage F human review | ≥ 95 % | ≥ 98 % |
| Forge Profiles shipped | 8 | 25+ |
| Resolver Profiles shipped | 3 | 10+ |
| Concurrent query throughput (single instance, baseline) | 100 QPS | 500 QPS |
| Graph traversal throughput | matches benchmark + analytical view | exceeds benchmark via replicated reads |

Compliance-track milestones (SOC 2 Type I → Type II → ISO 27001) run in parallel and are described in the compliance timeline above.

## Architectural-risk timeline

If the lock-free graph traversal optimization (Bottleneck 2 response in `09-benchmarks-and-validation.md`) does not meet throughput targets, an additional 1-2 quarters absorb graph scaling work (sharded subgraphs, dedicated graph cache, per-replica CSR view). All other items are execution risk and absorb into normal phase slip.

If LLM-cost economics shift downward (open-source frontier models reach parity), Phase 7 (Ontology Engine) can ship deeper extraction passes per episode at no marginal cost — upside risk.

---

## Why the phase order is what it is

1. **Storage before ingestion.** Phase 1 establishes the substrate; everything downstream depends on it.
2. **Forge before ingestion.** The pipeline reads the Forge Mapping as configuration. Without Forge, ingestion falls back to LLM-only extraction for structured sources.
3. **Resolver before retrieval.** Cross-source identity stitching produces canonical entities; retrieval ranks them. Stitching first.
4. **Retrieval before feedback.** Feedback is a no-op until retrieval works.
5. **Ontology after feedback.** Ontology improves extraction quality; it is an enhancement, not a blocker.
6. **Context Cores after the engine stabilizes.** Versioning a moving target produces unstable artifacts.
7. **API + connectors before observability + compliance.** The exposed surface stabilizes; then the operational and audit machinery wraps around it.

Compliance instrumentation (audit log, SOC 2 controls) runs in parallel from Month 6 because Type II requires a 6-month observation window before audit.

---

*Continue to `11-technical-capabilities.md` for the technical defensibility analysis, or `12-use-cases.md` for concrete query and ingestion scenarios.*
