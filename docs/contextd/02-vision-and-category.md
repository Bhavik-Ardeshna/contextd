# 02 — Vision & Category

## The thesis

Every generation of computing has minted a new database category around the data shape that mattered most.

| Era | Dominant data shape | Category-defining DB |
|-----|---------------------|----------------------|
| 1970s — relational era | Tabular records | Oracle, DB2 |
| 2000s — web era | Documents | MongoDB |
| 2010s — analytics era | Columnar facts | Snowflake, ClickHouse |
| 2010s — graph era | Relationships | Neo4j |
| 2020s — AI similarity era | Vector embeddings | Pinecone, Weaviate |
| **2020s+ — AI agent era** | **Context** | **ContextD** |

Each new category emerged because the dominant data shape couldn't be efficiently expressed in the previous one. **Context** — the assembled, relationship-aware, temporally-grounded, feedback-weighted view that AI agents need — is the dominant shape of this generation, and no existing DB category fits.

## Why "context" needs its own category

Context is not a document, not a vector, not a graph in isolation. **Context is the assembled output** that an AI agent receives at query time:

```
Query: "Prepare me for a call with Acme Corp"

What the agent actually needs:
  - The current account state (entity attributes + facts current as of today)
  - Who's involved (people connected to Acme, with their sentiments + roles)
  - What's recent (saga summary of the last quarter)
  - What's outstanding (open commitments, support tickets, contractual exceptions)
  - What we know we don't know (e.g., budget ceiling vs estimated budget)
  - What decisions led here (15% discount approved on 4/2 with net-60 exception, why)
  - What's been useful in past similar calls (feedback-weighted ranking)
```

**No existing database produces this assembled object.** Vector DBs return chunks. Graph DBs return paths. Document DBs return rows. Each of these is *raw material*, not *context*.

The teams building serious AI agents today are stitching context together in application code, on top of Neo4j + Pinecone + Postgres + Redis + LangChain + custom adapters. That's an operational nightmare and an architectural dead end. **Context belongs in the database layer, not the orchestration layer.**

## What "ContextD" means as a category

A Context Graph Database is a database that:

1. **Stores six data models natively.** Graph + vector + full-text + document + KV + time-series in one ACID engine. Not orchestration over five databases.
2. **Carries bitemporal metadata on every fact.** Every entity, relationship, fact, and decision tracks both *when it was true in the world* and *when we recorded/learned/superseded it*. This is a schema-level commitment — it cannot be retrofitted.
3. **Treats decisions as first-class auditable entities.** Inputs, policy, exception, justification, affected entities, supersession chain — all queryable.
4. **Learns from feedback at the data layer.** Every node and edge carries a feedback weight updated via streaming EMA. Retrieval is feedback-weighted at every layer of the query path, not just a post-hoc reranker.
5. **Applies an ontology actively during extraction.** Not post-hoc validation. The ontology is embedded, vector-routed, and injected into LLM prompts at extraction time. This catches hallucinated entity types and invalid relationships before they pollute the graph.
6. **Versions and tests the entire knowledge state.** Context Cores: content-addressed, immutable, msgpack-serialized snapshots of the graph + embeddings + weights. Build / test / promote / rollback. CI/CD for knowledge — a workflow that doesn't exist anywhere else today.

## Why this category emerges *now*

Five forces converging:

### 1. Foundation models commoditized

When every AI team has cheap access to GPT-4, Claude 4, Gemini 2.5, Llama 4, and the gap between top models is shrinking, the differentiator is no longer the model — it's the context. The "context engine" sits between every AI agent and every LLM, and whoever owns it owns most of the value.

### 2. Vector search is hitting its ceiling

The $4.4B vector DB market (Pinecone, Weaviate, Chroma, Milvus, Qdrant) demonstrated demand for embedding-based retrieval, but the limits are visible:
- No structural relationships between chunks
- No temporal awareness
- No supersession of stale facts
- No learning from past queries
- No decision lineage
- No cross-source unification

Vector DBs are now framed (correctly) as *one of several retrieval methods*, not the answer. ContextD subsumes vector search as one of three retrieval methods in a hybrid pipeline (BM25 + cosine + BFS), reranked, feedback-weighted.

### 3. The multi-DB stitch is now a $$$ operational problem

Production AI infrastructure circa 2026 looks like this:

```
                  ┌─────────────┐
                  │  AI Agent   │
                  └──────┬──────┘
                         │
              ┌──────────┴──────────┐
              │  LangChain / custom │
              │   orchestration     │
              └──┬──┬──┬──┬──┬──┬───┘
                 │  │  │  │  │  │
              ┌──┘  │  │  │  │  └──┐
              ▼     ▼  ▼  ▼  ▼     ▼
           ┌────┐ ┌────┐┌──┐┌────┐┌────┐┌─────────┐
           │Neo4│ │Pine││PG││Redi││Snow││...custom│
           │  j │ │cone││  ││ s  ││flake│connector│
           └────┘ └────┘└──┘└────┘└────┘└─────────┘

  No cross-model ACID. Consistency gaps everywhere.
  3-5× operational cost. Ops nightmare for real workloads.
```

CTOs we've talked to are explicitly looking for consolidation. The Snowflake → Databricks → Confluent unification arc is happening again at the AI infrastructure layer. ContextD is the consolidation play.

### 4. MCP is becoming the universal AI-data protocol

Anthropic's Model Context Protocol (shipped late 2024, adoption accelerating) is becoming the default agent-to-data interface. Claude, Cursor, Windsurf, OpenAI Operator, and every serious agent framework speaks MCP. ContextD is **MCP-native** with a two-layer architecture:

- **Layer 1: Substrate built-in MCP** — raw DB operations (`execute_command`, `get_schema`, `query`)
- **Layer 2: ContextD MCP** — context tools (`query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `get_saga_summary`, `submit_feedback`, `ingest_episode`)

stdio for local agents, SSE for streaming web frameworks, HTTP for serverless. Every agent framework can plug in.

### 5. The substrate exists — and it's truly Apache 2.0

ArcadeDB (Apache 2.0) is the first multi-model database that combines graph, vector (HNSW + PQ), full-text (Lucene BM25), document, KV, and time-series (Gorilla XOR) in a single ACID engine, with 70+ SIMD-accelerated graph algorithms (Java 21 Vector API), built-in MCP server, and wire-protocol polyglot (Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP).

Critically, the license is genuine Apache 2.0 — not SSPL (MongoDB), not Commons Clause (Redis Stack), not BSL (CockroachDB, Couchbase). We can embed, modify, and distribute freely. This makes a category-defining product viable.

## The category positioning statement

> **MongoDB owns documents. Pinecone owns vectors. Neo4j owns graphs. ContextD owns context.**
>
> ContextD is not a graph database with search bolted on, or a vector database with relationships added. It is a database-native system for context, where every primitive — entities, relationships, facts, episodes, sagas, communities, decisions — is purpose-built for producing the best possible context window for AI agents.

## How ContextD relates to adjacent categories

| Adjacent category | What they do | What ContextD adds | Complement or compete? |
|-------------------|-------------|-------------------|------------------------|
| **Vector DBs** (Pinecone, Weaviate, Qdrant) | Similarity over embeddings | Relationships + time + structure + learning | Subsume (vector is 1 of 3 retrieval methods) |
| **Graph DBs** (Neo4j, Neptune, TigerGraph) | Relationship queries | Bitemporal + feedback + AI-native + ontology + decision lineage | Subsume; benefit from same Cypher / Bolt protocol |
| **RAG frameworks** (LangChain, LlamaIndex, Haystack) | Orchestration | Persistent data layer they currently lack | Strong complement — they call ContextD for context |
| **Knowledge graph platforms** (Stardog, Ontotext) | RDF/SPARQL semantic graphs | AI-native (LLM extraction), feedback-weighted retrieval, MCP | Modern alternative |
| **Data observability** (Monte Carlo, Acceldata) | Pipeline reliability | First-class decision lineage as a data product | Adjacent, no overlap |
| **Customer Data Platforms** (Segment, mParticle, Hightouch) | Cross-system identity unification + activation | Same plumbing problem, but for AI agents instead of marketers | Adjacent — overlapping ICP at enterprise data team |

## What success looks like

In 5 years, "Context Graph Database" is on the standard architecture diagram for AI applications, and ContextD is the default — the way Snowflake is the default for analytics or Postgres is the default for OLTP. AI agents don't talk to vector DBs, graph DBs, and document DBs separately. They talk to ContextD via MCP, get a structured context window, and the LLM does the rest.

The "Pinecone moment" of the agent era is the **moment a developer realizes they can stop stitching three databases together**. We want to own that moment.

---

*Continue to `03-problem-and-market.md` for sizing and competitive landscape, or skip to `04-product-and-architecture.md` for the technical breakdown.*
