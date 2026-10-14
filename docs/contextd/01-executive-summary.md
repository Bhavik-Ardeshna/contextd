# 01 — Executive Summary

## ContextD — The Context Graph Database for AI

> **One sentence.** ContextD is an AI-native database that ingests enterprise data (Gmail, Salesforce, Slack, GitHub, Postgres, Snowflake, ...), constructs a relationship-aware knowledge graph with bitemporal state and decision lineage, learns from feedback what matters, and serves AI agents structured context — replacing chunk-based RAG with [TARGET] ~80% fewer tokens and dramatically higher answer quality.

> **Category bet.** MongoDB owns documents. Pinecone owns vectors. Neo4j owns graphs. **ContextD owns context.** This is a new database category — the *Context Graph Database* — and the timing is now.

---

## The thesis in one diagram

```
                   Today's stack                    Tomorrow's bet
                   ─────────────                    ──────────────
   Vector DB ───┐                                  ┌─── ContextD (unified)
   Graph DB  ───┤   3-5 databases stitched         │      one ACID engine
   Time-series ─┤   together in app code,          │      bitemporal native
   Doc DB    ───┤   no cross-model ACID,           │      6 data models native
   KV cache  ───┘   3× infra cost                  │      feedback-weighted retrieval
                                                   │      [TARGET] 80% token reduction
                                                   │      versioned context (CI/CD)
                                                   └────────────────────────────────
                                                   built on Apache 2.0 multi-model
                                                   substrate (ArcadeDB)
```

---

## Why now (timing)

1. **AI agent failure rates are dominated by context quality.** Token budget, hallucination, irrelevant retrieval — every public AI agent benchmark shows the same chokepoint. Vector search alone can't fix it.
2. **Enterprises are hitting the multi-DB wall.** Real production AI stacks now run Neo4j + Pinecone + Postgres + Redis + a custom orchestration layer. Operational cost scales linearly with model complexity. CTOs are looking for consolidation.
3. **Foundation-model commoditization makes context the moat.** When every team has access to GPT-4 / Claude 4 / Gemini, the differentiator is *what context you feed them*. ContextD owns the "context layer."
4. **MCP is becoming the default agent-to-data interface.** Anthropic's Model Context Protocol shipped late 2024 and adoption is accelerating across Claude, Cursor, Windsurf, OpenAI Operator. ContextD is MCP-native (two-layer architecture: substrate built-ins + ContextD context tools).
5. **A genuinely Apache-2.0 substrate exists.** ArcadeDB (Apache 2.0) is the only multi-model DB doing graph + vector + full-text + KV + document + time-series in a single ACID engine. No SSPL, no Commons Clause, no BSL. We can embed, fork, distribute freely.

---

## Where things stand today

| | |
|---|---|
| **Production stack** | Multi-database infrastructure: PostgreSQL + Neo4j + Milvus + Redis + Temporal. FastAPI backend, React/ShadCN frontend, ~40 source connectors, OAuth2 service for 30+ providers. |
| **Engineering surface** | 10-step ingestion pipeline. 5-phase entity-resolution cascade (MinHash + cosine + LLM). Streaming EMA feedback engine. OpenTelemetry tracing with NullSpan fallback. Chat/RAG service with streaming. |
| **Substrate validation** | End-to-end benchmark on ArcadeDB v26.4.2 over 475K entities + 1.37M edges + 1024-dim embeddings. Hybrid throughput peaks at **[BENCH] 137 ops/sec @ 32T** with 47 ms p50 single-thread. Specific bottlenecks identified — HNSW lock contention, graph adjacency-list page locks, PG-protocol polling-sleep bug — each with a concrete engineering response (`09-benchmarks-and-validation.md`). |

## What we're building next (12-18 months)

- **Unified ContextD substrate** — migrate primary storage from Postgres+Neo4j+Milvus to a single ArcadeDB-based engine with the intelligence layer on top (bitemporal schema, ontology engine, context cores, hybrid retrieval).
- **Context Cores** — versioned, content-addressed, immutable graph snapshots. Build / test / promote / rollback workflows. CI/CD for knowledge.
- **MCP server (two-layer)** — substrate built-ins (raw DB ops) + ContextD context tools (`query_context`, `get_timeline`, `get_decision_lineage`, `submit_feedback`). stdio/SSE/HTTP transports.
- **Cloud (multi-tenant managed)** — separate ArcadeDB database per tenant, RBAC enforcement, audit log, GDPR at launch.
- **Compliance** — SOC 2 Type I (Month 9) → Type II (Month 15) → ISO 27001 (Month 18).

---

## Differentiators (the moat, see `11-technical-capabilities.md`)

1. **Database-native, not a layer.** Built on a single ACID multi-model engine — not orchestration code over 5 databases.
2. **Bitemporal by design.** Every fact tracks both event time and transaction time. Cannot be retrofitted onto an existing graph DB.
3. **Feedback-weighted retrieval.** Streaming EMA (α=0.1) updates relevance scores on every node and edge, integrated into every query path — not a post-hoc reranker.
4. **Ontology-grounded extraction.** Ontology elements are embedded, vector-routed per chunk, and injected into LLM prompts dynamically — active constraint, not post-hoc validation.
5. **Context Cores = CI/CD for context.** Content-addressed (SHA-256), versioned, msgpack-serialized snapshots of entire graph + embeddings + weights. Build, test, promote, rollback. No competitor has this.
6. **Decision lineage as first-class data.** Decisions are entities with full traceability — inputs, policy, exception, affected entities. Impossible with flat retrieval.
7. **Wire protocol polyglot.** A single instance speaks Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP. No driver lock-in.
8. **Apache 2.0 substrate.** No SSPL trap. No Commons Clause. No BSL. True open-source.

---

## Headline takeaways

1. **The category is real.** Every serious AI infrastructure team is currently building a sub-scale, brittle version of this in-house. The structural answer is a purpose-built substrate.
2. **The technical bet is grounded.** The substrate has been benchmarked end-to-end on real hardware — bottlenecks identified, engineering responses specified. See `09-benchmarks-and-validation.md`.
3. **Execution is in motion.** A working ingestion pipeline, entity resolution, feedback engine, and 30+ connectors are running today. The unified-substrate migration is a consolidation effort, not a research project.
4. **The moat compounds.** Bitemporal storage, feedback-weighted retrieval, and decision-lineage-as-data cannot be retrofitted onto an existing graph or vector DB. Every month of customer feedback makes the graph more useful and harder to leave.

---

## Public material

- **Site:** https://contextd-tech.vercel.app

---

*Continue to `02-vision-and-category.md` for the long-form thesis, or skip to `09-benchmarks-and-validation.md` for the engineering ground-truth.*
