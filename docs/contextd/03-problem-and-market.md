# 03 — Problem & Market

## Three problems with current AI context infrastructure

Three problems show up consistently when teams build AI agents on top of conventional data stacks.

### Problem 1 — The multi-database tax

A representative production AI stack runs five or more separate data systems: a graph database for relationships, a vector database for embeddings, a relational database for tenant metadata, a key-value cache for hot reads, and an object store for raw artifacts. A custom orchestration layer (LangChain or hand-rolled glue) coordinates them.

```
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Graph DB│ │Vector DB│ │  RDBMS  │ │  Cache  │ │ Object  │
   └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘
        │           │           │           │           │
        └───────────┴────┬──────┴───────────┴───────────┘
                         │
              ┌──────────┴───────────┐
              │ Orchestration layer  │
              │ (LangChain + glue)   │
              └──────────┬───────────┘
                         │
                   ┌─────┴─────┐
                   │ AI agent  │
                   └───────────┘
```

The operational consequences:

- No cross-database ACID — a write to the graph store may succeed while the vector write fails, leaving the two indexes inconsistent.
- Schema drift across connectors that pump records with subtly different shapes per source.
- Maintenance overhead — five databases × patching/upgrade/monitoring × on-call rotation.
- Latency taxes — every query crosses three to five network hops.
- License entanglements — each component has its own commercial terms (SSPL, BSL, Commons Clause, proprietary cloud-only) that compose into a legal review nightmare for embedding scenarios.

### Problem 2 — Temporal blindness

Most graph and vector databases store *current* state. They cannot answer:

- "What did we know about a customer's budget on March 15?"
- "Who was the account owner *at the time* of that discount approval?"
- "What facts had been recorded *before* the incident?"

These are the bread-and-butter queries of compliance, audit, sales coaching, and post-mortem analysis. Without bitemporal storage at the schema level, every audit becomes a forensic reconstruction from event logs.

### Problem 3 — Static retrieval that does not learn

Static retrieval (vector + reranker) treats every query as the first query. The system does not learn that:

- Marketing-tagged entities are useless for support-agent queries.
- Old organizational-chart entities are misleading after a re-org.
- Domain-specific jargon entities should rank above generic ones for engineering queries.
- Decision-lineage edges are uniquely useful for audit queries.

After six months of production traffic, customers want a graph that has *learned*. Conventional systems offer no path to that.

---

## Where the market is

### The vector-database category is the leading edge but incomplete

The vector-database category — Pinecone, Weaviate, Qdrant, Chroma, Milvus, plus extensions in Postgres (pgvector), Redis, and MongoDB Atlas — proved that AI teams will pay for purpose-built infrastructure. Estimates put the 2025 market at roughly $4.4B, growing 25-35% annually.

The category is converging on the same realization: similarity search alone misses relationships, time, and structure. Pinecone added metadata filtering and hybrid search. Weaviate added knowledge-graph features. Qdrant added payload filtering. Each of these moves is an admission that vector search is one of several retrieval methods, not the answer.

A principled, ground-up Context Graph Database is the structural endpoint of that convergence — not a feature added to a vector store, but a database designed for context from the schema up.

### Adjacent categories

| Category | Examples | Where it overlaps with ContextD |
|----------|----------|---------------------------------|
| Vector databases | Pinecone, Weaviate, Qdrant, Milvus, Chroma | Subset of ContextD's hybrid retrieval |
| Graph databases | Neo4j, Amazon Neptune, TigerGraph | Subset — no bitemporal, no AI-native ingestion, no feedback |
| Customer Data Platforms | Segment, mParticle, Hightouch | Cross-system identity stitching, but for marketers — not agents, not graph-native, not bitemporal |
| Knowledge-graph platforms | Stardog, Ontotext, Diffbot | RDF/SPARQL legacy stacks; ContextD is the AI-native modern alternative |
| RAG infra & orchestration | LangChain, LlamaIndex, Haystack | Orchestration; ContextD is the persistent data layer they currently lack |
| AI agent platforms | Anthropic Claude / MCP, OpenAI Operator, LangGraph, CrewAI | Customers and channels for ContextD via MCP |

The TAM (AI infrastructure, narrow definition) is in the $10–15B range in 2025, plausibly $50B+ by 2030 if AI agents become standard enterprise tooling. The relevant market — every enterprise running AI agents needs context infrastructure — is materially larger and currently has no incumbent.

### Why no existing incumbent is positioned to address this

| Incumbent class | Structural blocker |
|-----------------|---------------------|
| Established graph databases (Neo4j) | License entanglement (SSPL); bitemporal would require core engine rewrites; not AI-native |
| Vector databases (Pinecone) | Pure vector architecture; no graph engine; no ACID; closed-source revenue model |
| Generalist DBs (MongoDB) | Vector + graph are bolt-ons; no bitemporal-as-schema |
| Analytics platforms (Snowflake, Databricks) | Query latency wrong for agent workloads; no first-class graph |
| Hyperscaler cloud DBs (Neptune, Cosmos DB) | Multi-cloud lock-in; no AI-native ingestion; conservative roadmap cadence |
| RAG orchestration (LangChain) | No persistent data layer; trying to *use* a context DB, not build one |

The structural opening: a system built on a multi-model substrate (a single ACID engine handling graph + vector + full-text + KV + document + time-series), with a clean bitemporal-and-decision-lineage schema and an AI-native ingestion pipeline, occupies space no incumbent can move to without breaking their existing data layer.

---

## Why now

| Force | Implication |
|-------|-------------|
| Foundation-model commoditization | When every team has access to parity-class LLMs, the differentiator is *context quality*. Owning the context layer is the moat. |
| Multi-database operational pain | Every infrastructure team running AI agents complains about it. Consolidation buyers exist now. |
| MCP standard adoption | Anthropic's Model Context Protocol shipped in late 2024 and is being adopted across major agent frameworks. Low-friction distribution. |
| Mature Apache-2.0 multi-model substrate | A genuine open-source multi-model engine exists and is benchmarked (`09-benchmarks-and-validation.md`). The architecture is buildable, not a science project. |
| Vector-DB ceiling visible | The market has accepted that similarity alone is insufficient. The next generation is hybrid + structured + temporal + feedback-weighted. |
| Bitemporal demand from regulated industries | Audit, compliance, decision lineage. Demand is concrete and growing. |

---

*Continue to `04-product-and-architecture.md` for the technical architecture, or `09-benchmarks-and-validation.md` for measured substrate performance.*
