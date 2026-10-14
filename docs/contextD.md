# ContextD — The Context Graph Database for AI

> **One sentence:** ContextD is a database that ingests enterprise data (emails, CRM records, tickets, Slack messages), transforms it into a structured knowledge graph with temporal awareness and provenance tracking, learns what matters through feedback, and serves AI agents structured context — targeting ~80% fewer tokens than chunk-based RAG.

> **The mental model:** Think of ContextD as the **memory** of an AI agent. Not "memory" like a chat history. Memory like a human brain — it knows *who* is connected to *whom*, *when* things happened, *what* changed, *why* decisions were made, and it gets better at recalling the right things the more you use it.

---

## Quick Start — Read This First

### Is ContextD right for your problem?

| If you need... | Use | Not ContextD? |
|----------------|-----|---------------|
| Semantic search over documents | A vector DB (Pinecone, Weaviate) | You don't need relationships or time |
| A simple RAG prototype | LangChain + a vector store | You need speed to demo, not production context quality |
| Relationship-aware context with temporal state | **ContextD** | This is the sweet spot |
| Cross-system queries (CRM + support + email in one query) | **ContextD** | No other system unifies these natively |
| A general-purpose database for your app | PostgreSQL, MongoDB | ContextD is opinionated for AI context |

### Prerequisites & constraints you should know now

```
Must have:
  - Docker (for ArcadeDB in server mode)
  - Python 3.11+
  - An OpenAI API key (for embeddings + LLM extraction)

Cost awareness:
  - Each ingested episode costs ~$0.01-0.05 in LLM API calls (extraction + embeddings)
  - At 1,000 episodes/day, expect ~$10-50/day in OpenAI costs
  - Feedback processing is free (no LLM calls — pure math)

Friction points to plan for:
  - Embedded mode requires Java 21+ (via jpype) — most teams use Docker server mode instead
  - ArcadeDB is powerful but less widely documented than Postgres/Neo4j — expect some learning curve
  - The ontology engine is optional — start without it, add it when you need extraction consistency
  - Hybrid search and context assembly are still being built (core pipeline + feedback are live)
```

### Fastest path to a working system

```bash
# 1. Start ArcadeDB (2 minutes)
docker run -d -p 2480:2480 -p 2424:2424 arcadedata/arcadedb:latest

# 2. Install Python dependencies
pip install httpx pydantic openai datasketch numpy

# 3. Create database + schema (Section 29, Phase 1)
# 4. Ingest your first episode (Section 29, Phase 2)
# 5. Query your graph (Section 29, Phase 3)
```

The full build guide is in [Section 29](#29-build-guide) with runnable code for every step.

### What's working now vs. what's coming

| Status | What's included |
|--------|----------------|
| **LIVE** | Core data models, ArcadeDB driver, 10-step ingestion pipeline, entity resolution (MinHash + LLM), LLM integration, embeddings, feedback engine, 30+ connectors, OAuth2, FastAPI API, OpenTelemetry tracing |
| **BUILDING** | Hybrid search (BM25 + cosine + BFS), context assembly (token optimization), community detection, ontology engine |
| **PLANNED** | Context Cores, MCP server, advanced rerankers, decision lineage, RBAC enforcement |

If a feature below is marked BUILDING or PLANNED, the architecture is designed but not all code paths are production-ready. The build guide shows how to implement each piece.

---

## Table of Contents

0. [Quick Start — Read This First](#quick-start--read-this-first) (decision guide, prerequisites, fastest path)
1. [The Problem (Why This Exists)](#1-the-problem)
2. [The Solution (What ContextD Is — and Isn't)](#2-the-solution)
3. [The Mental Model — How to Think About It](#3-the-mental-model)
4. [End-to-End Walkthrough: From Raw Email to AI Context](#4-end-to-end-walkthrough)
5. [The 6 Building Blocks (Data Primitives)](#5-the-6-building-blocks)
6. [How the Primitives Connect (Schema Relationships)](#6-how-the-primitives-connect)
7. [The Bitemporal Time Model](#7-the-bitemporal-time-model)
8. [Decisions as First-Class Citizens](#8-decisions-as-first-class-citizens)
9. [Data Ingestion — The 10-Step Pipeline](#9-data-ingestion--the-10-step-pipeline)
10. [Saga Tracking — Narrative Continuity](#10-saga-tracking)
11. [Entity Resolution — The 5-Phase Dedup](#11-entity-resolution--the-5-phase-dedup)
12. [The Ontology Engine](#12-the-ontology-engine)
13. [Retrieval — Hybrid Search Pipeline](#13-retrieval--hybrid-search-pipeline)
14. [Context Assembly — The 7-Step Algorithm](#14-context-assembly--the-7-step-algorithm)
15. [Feedback System — How the Graph Learns](#15-feedback-system)
16. [Context Cores — CI/CD for Context](#16-context-cores)
17. [Connectors — 600+ Data Sources](#17-connectors)
18. [Technology Stack (with Rationale)](#18-technology-stack)
19. [Architecture — The 5 Layers](#19-architecture--the-5-layers)
20. [The Closed Loop — How Data Actually Flows](#20-the-closed-loop)
21. [What ContextD Builds vs. What ArcadeDB Provides](#21-contextd-vs-arcadedb)
22. [Integration Paths (SDK, API, MCP, Wire Protocols)](#22-integration-paths)
23. [Observability — OTEL + Prometheus](#23-observability)
24. [Security, RBAC & Compliance](#24-security-rbac--compliance)
25. [Deployment Modes](#25-deployment-modes)
26. [Use Cases with Full Examples](#26-use-cases)
27. [What Makes ContextD Different (11 Differentiators)](#27-differentiators)
28. [Implementation Status](#28-implementation-status)
29. [Step-by-Step Build Guide (with Implementation Details)](#29-build-guide)
30. [Repository Structure](#30-repository-structure)
31. [Key Numbers Reference](#31-key-numbers)

---

## 1. The Problem

**AI agents work with the wrong context.** Every current approach fails in a specific, predictable way:

| Approach | What It Does | Why It Fails | Concrete Example of Failure |
|----------|-------------|--------------|----------------------------|
| **Vector Search** (Pinecone, Weaviate) | Finds ~1,000 "similar" text chunks | No relationships, no time, no structure | You search "Mercury" and get results about the planet, the element, AND the car — all equally ranked. No way to know which one you meant. |
| **Graph Databases** (Neo4j, Neptune) | Stores entity relationships | No temporal awareness, no decision lineage, SSPL restricts embedding | You can find that Alice works at Acme, but you can't ask "who worked there *last March*?" or "when did we *learn* she left?" |
| **RAG Frameworks** (LangChain, LlamaIndex) | Orchestrates retrieval + LLM | Framework only — no persistent data layer, no context storage, no learning | Every query starts from scratch. The system doesn't remember that last time it retrieved support tickets for Acme, they were useless — it retrieves them again. |
| **Multi-DB Assembly** (Neo4j + Pinecone + custom) | Cobbles together graph + vector + temporal logic | 3+ databases, no cross-model ACID transactions, consistency gaps, 3x infra cost | You write a relationship to Neo4j and an embedding to Pinecone. One succeeds, one fails. Now your graph and your search index disagree. |
| **ContextD** | Unified context graph with bitemporal state, hybrid retrieval, ontology-grounded extraction, feedback learning | — | One engine, ACID transactions across all 6 data models, learns from use. |

**The core insight:** AI agents don't need "similar documents." They need **relationship-aware, temporally-grounded, ontology-constrained, feedback-weighted context assembly.** That's not a feature you bolt onto an existing database — it requires a purpose-built system.

### Explain it like I'm 5

> Imagine your friend asks you about someone named "Alice." A search engine gives you a stack of papers that mention the name "Alice" — some about Alice in Wonderland, some about your coworker Alice, some about Alice Springs in Australia. That's vector search. Now imagine instead you have a really smart notebook that knows *your* Alice, knows she works at Acme, knows she was promoted last month, knows she sent you an angry email yesterday, and knows you usually care about her deal status when you ask. That notebook gives you exactly what you need in one page instead of a stack of 20 papers. That's ContextD.

### Explain it to an investor

> Every AI application hits the same bottleneck: context quality. The $4.4B vector database market (Pinecone, Weaviate) solves similarity search but misses relationships, temporal state, and learning. Enterprises are stitching together 3-5 databases with fragile orchestration code — creating operational nightmares and consistency gaps.
>
> ContextD collapses that entire stack into a single ACID database engine purpose-built for AI context. It delivers 80% token reduction vs. chunk-based RAG, self-improving retrieval via feedback weights, and versioned context snapshots (Context Cores) with CI/CD workflows.
>
> **Category positioning:** MongoDB owns documents. Pinecone owns vectors. Neo4j owns graphs. **ContextD owns context.** This is a new database category — the Context Graph Database — and we're defining it.

---

## 2. The Solution

ContextD is a **database**, not a framework. Not a wrapper. Not a layer. A database.

### What ContextD IS

| It Is | What That Means |
|-------|----------------|
| A **database** | Stores entities, relationships, facts, temporal state, decisions, and context — with ACID transactions |
| A **context construction engine** | Transforms raw data into structured knowledge via a 10-step pipeline |
| An **AI-native query system** | Hybrid retrieval (BM25 + vectors + graph traversal), not flat similarity search |
| A **temporal knowledge system** | Bitemporal model — tracks both "when it was true" and "when we learned it" |
| A **learning system** | Feedback-weighted graph that gets smarter with every interaction |
| **Versionable** | Context Cores = CI/CD for your knowledge graph (build, test, promote, rollback) |

### What ContextD is NOT

| It is Not | Why Not |
|-----------|---------|
| An AI agent | It serves context *to* agents. It doesn't take actions or make decisions. |
| A workflow tool | It doesn't automate processes. It provides the knowledge layer. |
| A vector database | Vectors are one of six data models inside it. Vectors alone can't represent relationships or time. |
| An analytics platform | It serves context windows, not dashboards. |
| A general-purpose DB | It's opinionated — every design choice optimizes for context assembly. |
| A RAG framework | It's the **persistent data layer** that RAG frameworks lack. |

---

## 3. The Mental Model

Before diving into technical details, internalize this mental model. Everything in ContextD flows from it.

### The Library Analogy

Think of ContextD as a **living library** with a brilliant librarian:

- **Episodes** = the raw books, letters, and documents arriving at the library
- **Entities** = the index cards in the card catalog (people, companies, projects)
- **Relationships** = the lines drawn between index cards ("Alice works at Acme")
- **Facts** = individual notes on each card ("Acme's budget is $5M as of January")
- **Sagas** = the storyline shelf — all the books about the "Acme Deal Negotiation" grouped together in order
- **Communities** = the sections of the library ("Everything related to the Acme account team")
- **Decisions** = a special log book recording every important decision, who made it, why, and what policy they cited

**The librarian (ContextD Engine):**
- When a new document arrives, the librarian reads it, creates/updates index cards, draws new connections, and notes any new facts (= **ingestion pipeline**)
- When you ask "what should I know about Acme?", the librarian doesn't photocopy 20 random books. She walks through the card catalog, follows relationships, checks what's current (not outdated), prioritizes what you've found useful before, and hands you a single briefing page (= **context assembly**)
- When you say "that briefing was perfect" or "you gave me irrelevant stuff", the librarian adjusts which cards and connections she prioritizes next time (= **feedback learning**)
- Every week, the librarian takes a snapshot of the entire catalog — so if something goes wrong, you can restore last week's version (= **Context Cores**)

### The Closed Loop

This is the single most important diagram. ContextD is not a pipeline — it's a **closed loop**:

```
Data Sources ──► Ingestion Pipeline ──► Graph Storage ──► Query Engine ──► AI Agent
                        ▲                                       │              │
                        │                                       │              │
                  Ontology Engine                               ▼              │
                  (constrains extraction)              Context Assembly         │
                                                               │              │
                                                               ▼              │
                                                        Assembled Context ────┘
                                                               │
                                                               ▼
                                                     Agent rates response (1-5)
                                                               │
                                                               ▼
                                                      Feedback EMA Update
                                                               │
                                                               ▼
                                                    Graph weights updated ──► (back to Graph Storage)
```

The feedback loop is what distinguishes ContextD from static retrieval systems. With explicit feedback (1-5 ratings from agents or users), the graph gradually surfaces more useful context over time. Without feedback, the system still works — feedback is purely additive.

---

## 4. End-to-End Walkthrough

Let's trace a single email through the entire system — from raw Gmail message to assembled context to feedback — so you can see every component in action.

### Step 1: An email arrives

```
From: alice@acme.com
To: bob@ourcompany.com
Date: 2026-04-15
Subject: Re: Q2 Budget Discussion

Hi Bob,

Just confirmed with our CFO — we're increasing the Q2 budget from $2.4M to $3.1M.
Also, Sarah Chen is taking over as the new VP of Engineering, replacing Tom Liu who moved to advisory.
Let's discuss the expanded scope in our Thursday call.

Best,
Alice
```

### Step 2: Gmail connector creates an Episode

```python
Episode {
  episode_type: "message",
  source: "gmail",
  content: "Hi Bob, Just confirmed with our CFO...",
  metadata: {
    from: "alice@acme.com",
    to: "bob@ourcompany.com",
    date: "2026-04-15",
    subject: "Re: Q2 Budget Discussion",
    thread_id: "thread_789",
    message_id: "msg_456"
  },
  valid_at: 2026-04-15,    # when the email was sent
  created_at: 2026-04-15T14:30:00Z  # when we ingested it
}
```

### Step 3: Pipeline extracts entities (Step 3 of 10)

The LLM reads the email + previous emails in this thread and extracts:

```
Entities extracted:
  - Alice (person, source: acme.com)
  - Bob (person, source: ourcompany.com)
  - Acme Corp (company)
  - Sarah Chen (person, new VP Engineering)
  - Tom Liu (person, moved to advisory)
  - Acme CFO (person, unnamed — referenced but not identified)
```

### Step 4: Entity Resolution (Steps 4-5 of 10)

The pipeline checks if these entities already exist:

```
"alice@acme.com" → Exact match on existing entity "Alice Chen" from Salesforce → MERGE
"Bob"            → Cosine similarity 0.87 with "Bob Martinez" from CRM → LLM confirms → MERGE
"Acme Corp"      → Exact match → MERGE
"Sarah Chen"     → No match → CREATE NEW (confidence: 0.92)
"Tom Liu"        → MinHash Jaccard 0.95 with "Thomas Liu" from LinkedIn → MERGE
```

### Step 5: Pipeline extracts relationships & facts (Steps 6-7)

```
Relationships extracted:
  - Sarah Chen → works_at → Acme Corp (role: VP Engineering)
    valid_at: 2026-04-15, invalid_at: null
  - Tom Liu → works_at → Acme Corp (role: Advisory)
    valid_at: 2026-04-15, invalid_at: null
  - Alice → discussed → Q2 Budget
    valid_at: 2026-04-15

Facts extracted:
  - Acme Corp has_budget "$3.1M for Q2 2026"
    valid_at: 2026-04-01, invalid_at: null

Contradictions detected (Step 7):
  - Old fact: Acme Corp has_budget "$2.4M" (valid_at: 2026-01-01)
    → SUPERSEDED: expired_at set to now(), invalid_at set to 2026-04-01
  - Old relationship: Tom Liu → works_at → Acme Corp (role: VP Engineering)
    → SUPERSEDED: invalid_at set to 2026-04-15
```

### Step 6: Embeddings generated, saved to graph (Steps 8-9)

All new entity names and relationship facts get vector embeddings. Everything is written to ArcadeDB with full provenance:

```
Every element stamped with:
  source_pipeline: "gmail_connector_v1"
  source_task: "task_2026-04-15T14:30:00Z"
  extraction_method: "llm_extraction"
  source_episode_id: "ep_456"
```

### Step 7: An AI agent queries for context

Two weeks later, an agent needs to prepare for a call:

```python
context = db.get_context(
    query="Prepare me for a call with Acme Corp",
    max_tokens=2000,
    include_lineage=True,
)
```

The Context Assembly engine:
1. **Parses intent** → identifies "Acme Corp" as the seed entity
2. **Runs parallel search** → BM25 finds exact "Acme" matches, Cosine finds semantically related entities, BFS walks from Acme to Alice, Sarah, Tom, the deal, the budget facts, the thread saga
3. **Reranks** → RRF merges results from all three methods
4. **Applies feedback weights** → Entities proven useful in past call preps rank higher
5. **Prunes to token budget** → Fills 2000 tokens: entities first, then relationships, then facts, then saga summary
6. **Serializes** → Structured JSON with primary entities, relationships, current facts, recent changes, decision history

### Step 8: Agent uses context, user rates quality

The agent produces a great briefing. The user rates it 5/5.

```python
await db.feedback(
    session_id="sess_abc",
    query_id="q_123",
    score=5,
    used_entities=["alice_uuid", "acme_uuid", "sarah_uuid"],
    used_edges=["alice_works_at_acme", "sarah_works_at_acme"],
)
```

### Step 9: Graph learns

Each entity and edge mentioned in the feedback gets an EMA update:

```
Alice entity:   feedback_weight: 0.5 → 0.5 + 0.1 × (1.0 - 0.5) = 0.55
Acme entity:    feedback_weight: 0.6 → 0.6 + 0.1 × (1.0 - 0.6) = 0.64  (already had some positive feedback)
Sarah entity:   feedback_weight: 0.5 → 0.55  (first feedback, moves toward useful)
```

Next time someone asks about Acme, these entities will rank slightly higher. After 30 positive interactions, they'll dominate the results for Acme-related queries.

---

## 5. The 6 Building Blocks

Everything in ContextD is one of six types. Think of these as the atoms of your knowledge graph.

### 5.1 Entity (Node) — "The nouns"

Represents a thing: a person, company, project, ticket, deal, or document.

```
Entity {
  id:                UUID [PK]
  canonical_id:      UUID        — resolved identity (after dedup, multiple sources → one entity)
  entity_type:       STRING      — person | company | project | ticket | deal | document
  name:              STRING      — "Alice Chen"
  labels:            [STRING]    — ["enterprise-customer", "vp-level"]
  summary:           STRING      — "VP Engineering at Acme Corp, key stakeholder in Q2 deal"
  name_embedding:    [FLOAT]     — stored in HNSW index for fast similarity search
  source:            STRING      — "salesforce" | "gmail" | "github" | ...
  feedback_weight:   FLOAT       — learned relevance [0.0-1.0], starts at 0.5
  valid_at:          TIMESTAMP   — when this entity became relevant in the real world
  invalid_at:        TIMESTAMP   — when it stopped being relevant (null = still active)
  created_at:        TIMESTAMP   — when we first recorded it
  expired_at:        TIMESTAMP   — when we superseded our record (null = current)
  confidence:        FLOAT       — entity resolution confidence score
  source_pipeline:   STRING      — "gmail_connector_v1"
  source_task:       STRING      — "task_abc123"
  extraction_method: STRING      — "llm_extraction" | "structured_import" | "manual" | "ontology_constrained"
}
```

**Why `canonical_id` matters:** When "John Smith" appears in Salesforce, "john@acme.com" appears in Gmail, and "john.smith" appears in Slack, the entity resolution pipeline merges them. `canonical_id` points all three records to the same resolved identity. This is how ContextD knows they're all the same person.

### 5.2 Relationship (Edge) — "The verbs"

A typed, directed connection between two entities: "Alice **works_at** Acme Corp."

```
Relationship {
  source_entity_id:  UUID → Alice
  target_entity_id:  UUID → Acme Corp
  relationship_type: STRING      — works_at | owns | assigned_to | approved | discussed | ...
  fact:              STRING      — "Alice has been VP of Engineering at Acme Corp since 2023"
  fact_embedding:    [FLOAT]     — enables semantic search over relationships
  weight:            FLOAT       — relationship strength
  feedback_weight:   FLOAT       — learned relevance [0.0-1.0]
  episodes:          [UUID]      — every episode that mentioned this relationship
  valid_at / invalid_at:          — event time bounds
  created_at / expired_at:        — transaction time bounds
  reference_time:    TIMESTAMP   — timestamp from the source episode
  source + extraction_method + source_pipeline + source_task:  — provenance
}
```

**Why the `fact` field is important:** Relationships aren't just typed edges — they carry a natural language description. "Alice works at Acme Corp as VP of Engineering" is searchable by both keywords (BM25) and meaning (cosine similarity). This powers hybrid search over relationships, not just entities.

### 5.3 Fact (Atomic Statement) — "The claims"

A single, time-bounded, verifiable statement extracted from source data.

```
Fact {
  subject_entity_id: UUID → Acme Corp
  predicate:         STRING      — has_budget | decided_to | committed_to | ...
  object:            STRING|UUID — "$3.1M for Q2 2026" (or a link to another entity)
  valid_at:          TIMESTAMP   — when this became true
  invalid_at:        TIMESTAMP   — when this stopped being true (null = still true)
  created_at:        TIMESTAMP   — when we recorded it
  expired_at:        TIMESTAMP   — when we superseded our record (null = current)
  confidence:        FLOAT       — extraction confidence
  feedback_weight:   FLOAT       — learned relevance [0.0-1.0]
  source_episode_id: UUID        — which episode this came from
  extraction_method: STRING      — how it was extracted
}
```

**Supersession (critical concept):** When a new fact contradicts an old one (budget went from $2.4M to $3.1M), the old fact is **never deleted**. Instead:
- Old fact: `expired_at` = now(), `invalid_at` = when the new fact became true
- New fact: created alongside the old one

This preserves complete history and enables all four temporal query types (explained in Section 7).

### 5.4 Episode (Source) — "The raw material"

The unprocessed source event. Everything else is *extracted from* episodes.

```
Episode {
  episode_type:  STRING      — message | json | text
  source:        STRING      — gmail | slack | github | salesforce | ...
  content:       TEXT        — raw content of the email/message/record
  metadata:      JSON        — headers, timestamps, sender, receiver, thread_id, ...
  entity_edges:  [UUID]      — entities and relationships extracted from this episode
  valid_at:      TIMESTAMP   — when the original event occurred
  created_at:    TIMESTAMP   — when we ingested this episode
}
```

**Design principle:** Every entity, relationship, and fact traces back to one or more episodes. This is full provenance — for any piece of knowledge in the graph, you can answer "where did this come from?"

### 5.5 Saga (Narrative) — "The storyline"

A storyline that spans multiple episodes. "The Acme deal negotiation" might involve 47 emails, 12 Slack threads, and 5 CRM updates over 3 months.

```
Saga {
  name:              STRING      — "Acme Corp Enterprise Deal Q1-Q2 2026"
  summary:           STRING      — incrementally updated by LLM as episodes are added
  first_episode_id:  UUID        — first episode in the story
  last_episode_id:   UUID        — most recent episode
  last_summarized_at: TIMESTAMP  — when the summary was last refreshed
}
```

**How episodes connect within a saga:**
- `Saga --HAS_EPISODE--> Episode` (saga knows all its episodes)
- `Episode --NEXT_EPISODE--> Episode` (temporal linked list — efficient "what happened next?" traversal)

**Incremental summarization:** When a new episode is added, the LLM receives `existing_summary + new_episode_content` and produces an updated summary. This avoids re-reading the entire history every time — streaming summarization.

### 5.6 Community (Cluster) — "The neighborhood"

A group of closely connected entities, discovered automatically by graph algorithms.

```
Community {
  name:            STRING      — "Acme Account Team"
  name_embedding:  [FLOAT]     — for community-level search
  summary:         STRING      — LLM-generated: "Cluster of 12 entities centered around..."
}
```

Communities are detected via ArcadeDB's native SIMD-accelerated algorithms (Louvain, Label Propagation). They provide macro-level structure for navigating large graphs — instead of searching 100,000 entities, you can search 500 communities first.

---

## 6. How the Primitives Connect

This is the schema relationship map — memorize it:

```
Episode ──extracts──► Entity + Fact + Relationship
Entity ──has_fact──► Fact
Entity ──related_to──► Entity (via Relationship edge)
Saga ──has_episode──► Episode ──next_episode──► Episode
Community ──has_member──► Entity
Fact ──superseded_by──► Fact (temporal chain — old facts link to newer ones)
Decision ──informed_by──► Fact + Episode
Decision ──decided_by──► Entity (person)
Decision ──applied_policy──► Entity (policy)
Decision ──affected──► Entity (what changed)
Ontology ──constrains──► Ingestion Pipeline (steps 3 and 6)
```

**Key insight:** Everything traces back to Episodes. Episodes are the source of truth. Entities, relationships, and facts are *derived* from episodes via the ingestion pipeline. This means you always have full provenance — you can always answer "where did this knowledge come from?"

---

## 7. The Bitemporal Time Model

This is one of ContextD's most powerful and most misunderstood features. Every entity, relationship, and fact tracks **two independent time dimensions:**

| Dimension | Fields | What It Means | Analogy |
|-----------|--------|--------------|---------|
| **Event Time** | `valid_at` → `invalid_at` | When was this true **in the real world**? | "Alice worked at Acme from January to June" |
| **Transaction Time** | `created_at` → `expired_at` | When did **we** record/learn/supersede this? | "We wrote this in our notebook on March 5th" |

### Why two clocks?

Because reality and our knowledge of reality change independently. The same fact can be "true in the world" at a different time than when "we knew it."

### Supersession Walkthrough (trace this carefully)

```
t=1 (Jan 15)  Email arrives: "Acme's annual budget is $5M"
              → Fact created:  {predicate: "budget", object: "$5M",
                                valid_at: 2026-01-01, invalid_at: NULL,
                                created_at: 2026-01-15, expired_at: NULL}

t=2 (Apr 3)   Email arrives: "Acme increased their budget to $7M"
              → Pipeline Step 7 detects contradiction via semantic search
              → LLM adjudication confirms: this supersedes the old fact
              → Old fact updated: expired_at = 2026-04-03, invalid_at = 2026-04-01
              → New fact created:  {predicate: "budget", object: "$7M",
                                    valid_at: 2026-04-01, invalid_at: NULL,
                                    created_at: 2026-04-03, expired_at: NULL}

BOTH facts now exist in the graph. Nothing was deleted. This enables:
```

### Four Temporal Queries (with actual Cypher)

**1. Current State** — "What is Acme's budget?"
```cypher
MATCH (acme:Entity {name: "Acme"})-[:HAS_FACT]->(f:Fact {predicate: "budget"})
WHERE f.invalid_at IS NULL AND f.expired_at IS NULL
RETURN f.object AS budget
-- Returns: "$7M"
```

**2. Historical State** — "What was Acme's budget on Feb 1?"
```cypher
MATCH (acme:Entity {name: "Acme"})-[:HAS_FACT]->(f:Fact {predicate: "budget"})
WHERE f.valid_at <= datetime("2026-02-01")
  AND (f.invalid_at IS NULL OR f.invalid_at > datetime("2026-02-01"))
RETURN f.object AS budget
-- Returns: "$5M"  (it was true on Feb 1, superseded later)
```

**3. Knowledge State** — "What did we know about Acme's budget on Mar 1?"
```cypher
MATCH (acme:Entity {name: "Acme"})-[:HAS_FACT]->(f:Fact {predicate: "budget"})
WHERE f.created_at <= datetime("2026-03-01")
  AND (f.expired_at IS NULL OR f.expired_at > datetime("2026-03-01"))
RETURN f.object AS budget
-- Returns: "$5M"  (we hadn't learned about the increase yet on Mar 1)
```

**4. Audit State** — "When did we learn about the $7M budget?"
```cypher
MATCH (acme:Entity {name: "Acme"})-[:HAS_FACT]->(f:Fact {predicate: "budget"})
WHERE f.object = "$7M"
RETURN f.created_at AS when_we_learned_it
-- Returns: "2026-04-03"
```

### Why this matters for AI

Without bitemporal, an AI agent can't distinguish between "Alice left Acme in March" and "we learned in June that Alice left in March." When an agent is making a decision based on what was known *at the time of a past decision*, it needs to query knowledge state — not current state. This is critical for compliance, audit, and decision lineage.

---

## 8. Decisions as First-Class Citizens

> **Status: PLANNED** — The schema is designed (below) but decision extraction and lineage querying are on the roadmap.

Most systems treat decisions as invisible side effects buried in event logs. ContextD's design makes them searchable, traceable, and auditable.

```
Decision {
  decision_type:     "approval" | "exception" | "selection" | "commitment"
  subject:           "20% discount for Acme Corp"
  outcome:           "approved"
  decided_by:        UUID → Person entity (who made the decision)
  decided_at:        TIMESTAMP
  inputs:            [UUID] → episodes + facts that informed this decision
  policy:            UUID → policy entity that was applied
  exception:         BOOLEAN — was standard policy overridden?
  justification:     TEXT — "Strategic account, 3-year commitment, $2.4M TCV"
  affected_entities: [UUID] → what entities were changed as a result
  superseded_by:     UUID → if this decision was later overridden
}
```

**Why this matters:** You can query "Show me all discount approvals over 15% in Q1, who approved each, what policy they cited, and whether exceptions were justified." This is impossible with flat document stores — you need graph lineage, bitemporal tracking, and first-class decision entities connected to their inputs, policies, and outcomes.

---

## 9. Data Ingestion — The 10-Step Pipeline

Every piece of data goes through this pipeline. Each step has provenance — you can always trace back to the original source.

```
Raw Data → [1] Create Episode
         → [2] Retrieve Context (previous episodes for continuity)
         → [3] Extract Nodes (LLM ◄── Ontology Engine constrains)
         → [4] Resolve Entities — Deterministic (exact match, entropy gate, MinHash)
         → [5] Resolve Entities — Semantic + LLM (cosine similarity, LLM final)
         → [6] Extract Edges (LLM ◄── Ontology Engine constrains)
         → [7] Resolve/Dedup Edges (hybrid search + LLM → supersede contradictions)
         → [8] Generate Embeddings (parallel batch via OpenAI → LSMVector HNSW)
         → [9] Save to Graph (bulk write to ArcadeDB with full provenance)
         → [10] Community Detection (optional: Louvain/LP → LLM summarization)
```

### Step-by-step with implementation details

**Step 1 — Create Episode.** Wrap raw data in an `EpisodicNode` vertex. Store `content`, `metadata`, `valid_at` (when the original event happened), `source`, and `episode_type`.

**Step 2 — Retrieve Context.** Fetch the previous N episodes (default: last 10) in the same group/saga. This gives the LLM conversation history — so when an email says "as I mentioned yesterday," the LLM knows what "yesterday" refers to.

**Step 3 — Extract Nodes.** Send episode content + context window + optional ontology subset to the LLM. The LLM returns structured entities via Pydantic-validated output:
```python
# LLM returns something like:
ExtractedEntities(entities=[
    Entity(name="Alice Chen", entity_type="person", summary="VP Engineering at Acme"),
    Entity(name="Acme Corp", entity_type="company", summary="Enterprise customer"),
])
```
If an ontology is active, only ontology-defined entity types are accepted (e.g., "Vehicle" would be dropped if only Person and Organization are defined). The ontology subset is selected via semantic routing (explained in Section 12).

**Step 4 — Resolve Entities (Deterministic).** Before calling the LLM (expensive), try cheap dedup:
- (a) Normalize: lowercase, collapse whitespace, strip punctuation
- (b) Exact match → merge immediately
- (c) Entropy gate: compute Shannon entropy. If < 1.5 bits or name < 6 chars → skip fuzzy matching (strings like "Q1", "API", or "USA" are too short/generic for reliable fuzzy matching)
- (d) 3-gram MinHash with 32 permutations + LSH banding (band size 4)
- (e) Jaccard similarity ≥ 0.9 → merge

**Step 5 — Resolve Entities (Semantic + LLM).** For remaining unresolved entities:
- (a) Compute cosine similarity of name embeddings against all existing entities
- (b) Threshold ≥ 0.6, take up to 15 candidates per entity
- (c) Send candidates to LLM for final yes/no dedup decision
- (d) LLM returns `NodeDuplicate(id, name, duplicate_candidate_id)` for confirmed matches
- (e) Type promotion: merge labels from both resolved entities

This cascading approach reduces LLM calls by ~80% — only genuinely ambiguous cases reach the LLM.

**Step 6 — Extract Edges.** Send entities + episode content to LLM. Returns relationships with temporal annotations:
```python
ExtractedEdges(edges=[
    Edge(source="Alice Chen", target="Acme Corp", type="works_at",
         fact="Alice is VP of Engineering at Acme Corp since 2023",
         valid_at="2023-06-01", invalid_at=None),
])
```
Self-edges are dropped. Edges referencing unknown entities are filtered. Ontology domain/range constraints are enforced if active.

**Step 7 — Resolve/Dedup Edges.** Match new edges against existing ones using hybrid search (`EDGE_HYBRID_SEARCH_RRF` — BM25 + cosine on fact embeddings). LLM identifies:
- **Duplicate facts** → merge into existing (append episode UUID to edge's `episodes` list)
- **Contradicted facts** → supersede (set `invalid_at` and `expired_at` on old edge, create new)

**Step 8 — Generate Embeddings.** Batch-embed all new entity names and relationship facts via OpenAI. Store in LSMVector HNSW indexes with Product Quantization compression.

**Step 9 — Save to Graph.** Bulk write to ArcadeDB: episodes, entities, relationships, episodic edges. Every element is stamped with: `source_pipeline`, `source_task`, `extraction_method`, `source_episode_id`.

**Step 10 — Community Detection (Optional).** Run Label Propagation or Louvain on the updated graph region. LLM generates summaries for each community via bottom-up hierarchical summarization. Creates/updates `CommunityNode` vertices with `HAS_MEMBER` edges.

### Behavioral Spec Examples (BDD)

These are the kind of tests you'd write to validate each pipeline step:

```
GIVEN an episode with content mentioning "Alice works at Acme"
WHEN  extracted with CRM ontology
THEN  a Person entity "Alice" and Organization entity "Acme" are created
      with a "works_at" relationship

GIVEN two entities "John Smith" and "john smith" with Jaccard similarity >= 0.9
WHEN  resolved through the deterministic pipeline
THEN  they are merged into a single canonical entity

GIVEN an ontology where "works_at" has domain Person and range Organization
WHEN  LLM extracts "Acme works_at Alice"
THEN  the relationship is DROPPED — domain/range violated

GIVEN a saga with 5 episodes
WHEN  a 6th episode is added
THEN  NEXT_EPISODE links episode 5 → episode 6, and saga summary is incrementally updated

GIVEN an entity extracted from an episode
WHEN  saved to the graph
THEN  source_pipeline, source_task, and extraction_method are all populated
```

---

## 10. Saga Tracking

Sagas provide **narrative continuity** across episodes. When episodes belong to an ongoing storyline — a deal negotiation, a support escalation, a project kickoff — the saga system chains them together and maintains an incrementally updated summary.

### How it works

```
[A] Create or Fetch Saga  — If saga parameter provided, create SagaNode by name or fetch existing
[B] Link Episode to Saga  — HAS_EPISODE edge from saga to new episode
[C] Chain Temporally       — NEXT_EPISODE edge from previous episode to new one (temporal linked list)
[D] Update Summary         — LLM(existing_summary + new_episode) → updated_summary (streaming, not re-read)
```

### In code

```python
result = await db.ingest_episode(
    name="Acme Deal Update",
    content="Hi team, Acme has agreed to the revised pricing...",
    source="gmail",
    reference_time=datetime(2026, 4, 10),
    saga="acme-deal-negotiation",               # Creates or appends to saga
    saga_previous_episode_uuid="ep_abc123",      # Chain to previous episode
)
```

**Why this matters:** Without sagas, an agent would need to read every individual email/message to understand a storyline. With sagas, the agent gets a single summary that's always up-to-date — plus it can traverse individual episodes via `NEXT_EPISODE` edges if it needs detail.

---

## 11. Entity Resolution — The 5-Phase Dedup

This is how ContextD knows that "Alice Chen", "A. Chen", "alice.chen@acme.com", and "Alice (VP Eng)" are all the same person.

```
New Entity
   │
   ▼
[Phase 1: Exact Match] ─── match? → MERGE (free, instant)
   │ no match
   ▼
[Phase 2: Entropy Gate] ─── entropy < 1.5 bits or < 6 chars? → SKIP FUZZY (unreliable name)
   │ passes gate
   ▼
[Phase 3: MinHash/LSH] ─── Jaccard ≥ 0.9? → MERGE (cheap, deterministic)
   │ no match
   ▼
[Phase 4: Cosine Similarity] ─── cosine ≥ 0.6? → CANDIDATE (up to 15 per entity)
   │ candidates found
   ▼
[Phase 5: LLM Final] ─── LLM says same? → MERGE, else → CREATE NEW (expensive, last resort)
```

### Why cascading?

| Phase | Cost | Speed | Accuracy | What it catches |
|-------|------|-------|----------|----------------|
| 1. Exact Match | Free | Instant | 100% | "john smith" = "John Smith" |
| 2. Entropy Gate | Free | Instant | N/A (filter) | Prevents "Q1", "API", "USA" from entering fuzzy |
| 3. MinHash/LSH | Very cheap | <1ms | ~95% | "Jonathan Smith" ≈ "John Smith" (high character overlap) |
| 4. Cosine | Cheap | <10ms | ~90% | "J. Smith" ≈ "John Smith" (semantic similarity) |
| 5. LLM | Expensive | ~500ms | ~99% | "john@acme.com" = "John Smith, VP at Acme Corp" |

Phases 1-3 handle ~80% of resolutions before the LLM is ever called. This saves both cost and latency.

### Key parameters to remember

```
MinHash:  3-gram shingles, 32 permutations, LSH band size 4, Jaccard threshold 0.9
Cosine:   name embeddings, threshold 0.6, max 15 candidates per entity
Entropy:  Shannon entropy < 1.5 bits OR name length < 6 characters → skip fuzzy
```

---

## 12. The Ontology Engine

> **Status: BUILDING** — The architecture and validation logic are designed. Semantic routing is being implemented.

The ontology engine is **optional**. It constrains what the LLM can extract, improving consistency and reducing hallucinated entity types.

### Should you use it? (Decision guide)

| Situation | Recommendation |
|-----------|---------------|
| Prototyping or < 10K entities | **Skip it.** LLM-only extraction works fine at small scale. Add ontology later when you see inconsistent entity types. |
| Single data source (e.g., just Gmail) | **Probably skip.** The LLM can figure out Person/Company/Topic without help. |
| Multiple sources producing overlapping entity types | **Use it.** Without ontology, Salesforce might produce "Account" while Gmail produces "Company" for the same concept. |
| Regulated domain (finance, healthcare) | **Use it.** Ontology enforces that only valid relationship types are created — critical for audit. |
| You need consistent extraction across team members | **Use it.** Ontology acts as a shared schema contract. |

### What it is

A set of rules defining what types of things can exist and how they can relate. In OWL-like JSON:

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
    "Organization": {
      "labels": {"en": "Organization"},
      "comment": "A company, team, or group",
      "subclass_of": ["Agent"]
    }
  },
  "object_properties": {
    "works_at": {
      "domain": ["Person"],
      "range": ["Organization"],
      "functional": false,
      "max_cardinality": null
    },
    "ceo_of": {
      "domain": ["Person"],
      "range": ["Organization"],
      "functional": true    // max 1 value — a person can only be CEO of one company
    }
  },
  "datatype_properties": {
    "has_email": {
      "domain": ["Person"],
      "range": "xsd:string",
      "functional": true    // one primary email per person
    }
  }
}
```

### How it works (4-step semantic routing, TrustGraph-inspired)

**Step 1 — Embed ontology.** All ontology elements (classes, properties) are converted to vector embeddings, combining identifiers, labels, and descriptions.

**Step 2 — Select relevant subset.** For each incoming text chunk, vector-match against ontology embeddings (threshold 0.3, top-k 10). Include dependency resolution (parent classes, domain/range constraints).

**Step 3 — Inject into LLM prompt.** The relevant ontology subset is serialized and injected into the extraction prompt via Jinja2 templates. The LLM sees only the constraints relevant to this specific chunk — not the entire ontology.

**Step 4 — Validate output.** After extraction, validate against ontology rules:

| Rule | What It Enforces | Example |
|------|-----------------|---------|
| Class filtering | Only defined entity types accepted | "Vehicle" dropped if only Person/Organization defined |
| Domain/range | Relationships must connect valid types | "works_at" must go Person → Organization, not reverse |
| Cardinality | Functional properties max 1 value | `ceo_of` can only have one target per person |
| Disjoint classes | Entity can't belong to conflicting classes | Something can't be both Person AND Organization |

**Pre-built ontologies:** CRM, Support, Engineering, Marketing. System works without ontology (LLM-only extraction), but produces higher-quality graphs with one.

---

## 13. Retrieval — Hybrid Search Pipeline

When an AI agent queries ContextD, three search methods run **in parallel**, then results are merged by a reranker.

### Three Search Methods

| Method | How It Works | Good At | Misses |
|--------|-------------|---------|--------|
| **BM25** | Lucene keyword search inside ArcadeDB | Exact terms, names, IDs, jargon | Paraphrases, synonyms |
| **Cosine** | HNSW nearest-neighbor via LSMVector | Semantic meaning, paraphrases | Exact names, IDs |
| **BFS** | Breadth-first graph traversal from seed entities | Structural relationships, neighbors | Entities not connected to seeds |

### Five Reranking Strategies

| Reranker | Formula / Logic | When to Use |
|----------|----------------|-------------|
| **RRF** (default) | `score = Σ 1/(k + rank)` across all methods | General purpose — balanced across all methods |
| **MMR** | Balances relevance vs. diversity via lambda | When you want variety, not 10 similar results |
| **Cross-Encoder** | Neural model re-scores each pair (query, result) | Maximum accuracy when latency isn't critical |
| **Node Distance** | Prefers results closer in graph hops to query entities | Relationship-focused queries ("who works with Alice?") |
| **Episode Mentions** | Prefers results mentioned in more/recent episodes | Recency-focused queries ("what's new with Acme?") |

**Composability:** 3 methods x 5 rerankers = 15 possible strategies. Plus 6 pre-built recipes (like `COMBINED_HYBRID_SEARCH_RRF`). Configurable per query.

### Query Flow

```
Natural Language Query
   │
   ▼
[1. Parse Intent] → extract entity references, temporal constraints, relationship hints
   │
   ├──[BM25 Search]────────────┐
   ├──[Cosine Search]──────────┤  (all three run in parallel)
   └──[BFS Traversal]─────────┘
                                │
                                ▼
                    [2. Reranker] (RRF / MMR / CrossEncoder / ...)
                                │
                                ▼
                    [3. Apply Feedback Weights]
                    final_score = reranker_score × feedback_weight
                                │
                                ▼
                    [4. Token Budget Pruning]
                                │
                                ▼
                    [5. Assembled Context JSON]
```

---

## 14. Context Assembly — The 7-Step Algorithm

This is the heart of ContextD's value. It takes raw search results and assembles a structured, token-efficient context package.

**Step 1 — Parse Intent.** Decompose the natural language query into structured criteria: entity references, relationship type hints, temporal constraints, search filters.

**Step 2 — Seed Entity Selection.** BM25 (exact name matches) + Cosine (semantic matches) identify the primary entities. These become starting points for BFS.

**Step 3 — Hybrid Parallel Search.** Execute BM25 + Cosine + BFS simultaneously. BFS walks from seed entities, collecting neighbors, paths, and communities up to configurable depth.

**Step 4 — Rerank & Merge.** Deduplicate by UUID. Apply configured reranker to produce a single ranked list.

**Step 5 — Apply Feedback Weights.** `final_score = reranker_score × feedback_weight`. Elements proven useful historically rank higher.

**Step 6 — Budget-Aware Temporal Pruning.** Given a `max_tokens` budget, fill in priority order:
1. Primary entities (highest priority — always included)
2. Direct relationships between primary entities
3. Facts with current-state temporal filter
4. Saga summaries (narrative context)
5. Decision lineage (if `include_lineage=True`)

Items are added until the token budget is exhausted. Outdated facts are deprioritized.

**Step 7 — Serialize & Package.** Output structured JSON:

```json
{
  "query": "Tell me about the Acme deal",
  "context": {
    "primary_entities": [
      {"name": "Acme Corp", "type": "company", "summary": "...", "feedback_weight": 0.82}
    ],
    "relationships": [
      {"source": "Alice Chen", "type": "works_at", "target": "Acme Corp", "fact": "VP Engineering since 2023"}
    ],
    "relevant_facts": [
      {"subject": "Acme Corp", "predicate": "has_budget", "object": "$3.1M Q2", "valid_at": "2026-04-01"}
    ],
    "temporal_context": {
      "current_state": {"deal_stage": "negotiation", "budget": "$3.1M"},
      "recent_changes": ["Budget increased from $2.4M to $3.1M on Apr 1", "Sarah Chen replaced Tom Liu as VP Eng"]
    },
    "decision_history": [...],
    "saga_summary": "Enterprise negotiation spanning Jan-Apr 2026. Key contacts: Alice (VP Eng), Bob (Sales)...",
    "communities": ["Acme Account Team (12 entities)"],
    "sources": ["gmail", "salesforce", "slack"]
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

### Why fewer tokens? (target: ~80% reduction)

Traditional chunk-based RAG retrieves top-k similar chunks (k=10-20, each ~200-400 tokens) → ~3,400 tokens of overlapping, redundant text with no structure. An entity mentioned in 5 chunks appears 5 times.

ContextD retrieves **specific entities, relationships, and facts** — structured, deduplicated (an entity appears once), temporally filtered (only current facts), and feedback-weighted (only proven-useful elements). The target is ~800-1,000 tokens for equivalent coverage (~80% reduction). The actual reduction depends on query complexity, graph density, and how much feedback has accumulated. Early queries without feedback will see smaller reductions; well-trained graphs with months of feedback will approach the target.

**How the reduction works mechanically:** Deduplication (entities mentioned across 5 chunks → 1 structured record), temporal pruning (superseded facts dropped), and feedback pruning (low-weight elements excluded). Relationships and temporal context also reduce hallucination from stale data.

---

## 15. Feedback System

The graph gets smarter with every interaction.

### The Math (EMA — Exponential Moving Average)

```python
# Step 1: Normalize the 1-5 rating to 0.0-1.0
normalized = (score - 1) / 4      # 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0

# Step 2: EMA update (alpha = 0.1)
updated_weight = previous_weight + 0.1 * (normalized - previous_weight)

# Step 3: Clamp and round
updated_weight = round(clamp(updated_weight, 0.0, 1.0), 4)
```

### Worked example showing learning over time

```
Entity: "Acme Support Tickets"

Week 1 (no feedback):     feedback_weight = 0.50 (neutral)
  → Query about Acme support → reranker=0.90 × 0.50 = 0.45

Week 1 (score: 5/5):      0.50 + 0.1 × (1.0 - 0.50) = 0.55
Week 2 (score: 4/5):      0.55 + 0.1 × (0.75 - 0.55) = 0.57
Week 2 (score: 5/5):      0.57 + 0.1 × (1.0 - 0.57) = 0.613
Week 3 (score: 5/5):      0.613 + 0.1 × (1.0 - 0.613) = 0.652
...after 30 positive rounds:  ≈ 0.92

Week 4:
  → Same query → reranker=0.90 × 0.92 = 0.828   ← RANKS MUCH HIGHER

Compare with "Acme Marketing Campaign":
  After 30 rounds where it was in results but never useful (score: 2/5 average):
  weight drifted from 0.50 → 0.31
  → reranker=0.85 × 0.31 = 0.264   ← DEMOTED

The graph learned: support agents need ticket data, not marketing data.
```

### Feedback submission

```python
await db.feedback(
    session_id="session_abc123",
    query_id="q_456",
    score=4,                          # 1-5 scale
    used_entities=["entity_789"],     # which entities were in the response
    used_edges=["edge_345"],          # which edges were in the response
)
```

### Design properties

- **Cold start safe:** Everything starts at 0.5 (neutral). System works perfectly without any feedback.
- **Purely additive:** Feedback only improves results — it never makes the system worse than "no feedback."
- **Idempotent:** Duplicate submissions detected via `memify_metadata` flag and skipped.
- **Auditable:** All feedback events logged with timestamps, session IDs, and user IDs.

### Auto-Feedback Detection (Planned)

Beyond explicit 1-5 ratings, the roadmap includes LLM-based analysis of conversation turns for implicit feedback: "that was exactly what I needed" (positive), "no, that's wrong" (negative), "actually the revenue was $50M not $30M" (correction → supersede fact). This creates a continuous learning signal without requiring explicit ratings.

---

## 16. Context Cores

> **Status: PLANNED** — The architecture is designed and the build guide (Section 29, Phase 6) shows how to implement it. This is not yet production-ready.

Context Cores are **versioned, testable, deployable snapshots** of your entire context graph. Think of them like Docker images for knowledge graphs.

### Lifecycle

```
BUILD ──► TEST ──► VERSION ──► PROMOTE ──► PRODUCTION
                                               ▲
                                           ROLLBACK
```

### What's inside

| Component | What It Contains |
|-----------|-----------------|
| Graph data | All entities, relationships, facts, decisions |
| Embeddings | Entity name + relationship fact vectors |
| Ontology | The schema that constrained extraction |
| Source manifests | Which episodes/connectors contributed, with timestamps |
| Retrieval policies | Search recipe configs |
| Feedback weights | All learned relevance scores |
| Metadata | SHA-256 content hash, build timestamp, builder identity |

### In practice

```bash
# Build a snapshot of current graph
contextd core build --name "customer-context" --graph "production"

# Run test queries to validate context quality
contextd core test --core "customer-context:v4" --queries "test-suite.yaml"
# Result: 47/50 pass (3 missing relationships from stale connector)

# Fix the connector, rebuild
contextd core build --name "customer-context" --graph "production"
contextd core test --core "customer-context:v5" --queries "test-suite.yaml"
# 50/50 pass → promote

contextd core promote --core "customer-context:v5" --target "production"

# Something breaks later → rollback in seconds
contextd core rollback --target "production" --to "customer-context:v4"

# Investigate what changed between versions
contextd core diff --from "customer-context:v4" --to "customer-context:v5"
```

**Serialization:** msgpack format + content-addressed SHA-256 hashing. Each core is immutable once built.

---

## 17. Connectors

ContextD has two tiers of connectors. **P0 connectors** (6 sources) are custom-built with deep extraction logic. **P1 connectors** (600+ sources) use Airbyte's open-source catalog with a ContextD quality layer on top — these require running Airbyte as a Docker sidecar and have less sophisticated extraction than P0.

### P0 — Custom-Built (High Quality, Live)

These have deep extraction logic — they don't just forward raw data, they understand the *semantics* of each source:

| Connector | What Gets Extracted | Entity Types Produced |
|-----------|--------------------|-----------------------|
| **Gmail** | Thread structure, headers, body, attachments, labels | Person, Thread, Topic, Commitment, Decision |
| **Salesforce** | Accounts, contacts, opportunities, activities, custom objects | Company, Person, Deal, Activity |
| **Slack** | Messages, threads, reactions, mentions, channels | Person, Channel, Topic, Decision |
| **GitHub** | Repos, issues, PRs, commits, reviews, comments | Person, Repository, Issue, PR |
| **Zendesk** | Tickets, agents, customers, SLAs, satisfaction | Person, Ticket, Company |
| **HubSpot** | Contacts, companies, deals, activities, lists | Person, Company, Deal, Campaign |

**Gmail deep-dive example:**
- Extracts thread structure (which emails belong together)
- Parses headers (From, To, CC, BCC, Date, Subject, Message-ID, In-Reply-To)
- Strips HTML from body
- Extracts commitments ("I'll send the proposal by Friday")
- Extracts decisions ("Approved the 20% discount")
- Creates relationships: `person → emailed → person`, `person → discussed → topic`, `person → committed_to → commitment`, `email → part_of → thread`, `thread → about → topic`

### P1 — Airbyte + Quality Layer

600+ connectors via Airbyte, with a quality layer that adds:
- LLM entity/relationship extraction
- Ontology constraints
- MinHash + cosine deduplication
- Full provenance metadata

**Highlighted P1 sources:** Notion, Jira, Linear, Google Drive, PostgreSQL, Snowflake, Microsoft Teams, Outlook.

### Building Your Own Connector

```python
from contextd import Connector, Episode

class MyCustomConnector(Connector):
    name = "my_system"
    auth_type = "api_key"

    async def fetch_episodes(self, since: datetime = None) -> list[Episode]:
        records = await self.client.get_records(since=since)
        return [
            Episode(
                episode_type="json",
                source="my_system",
                source_id=r.id,
                content=r.to_text(),
                metadata=r.metadata,
                valid_at=r.created_at,
            )
            for r in records
        ]
```

**OAuth2:** 30+ providers supported out of the box (Google, Microsoft, GitHub, Slack, Salesforce, HubSpot, etc.). Tokens encrypted at rest and rotated automatically.

---

## 18. Technology Stack

| Component | Technology | License | Why This Choice |
|-----------|-----------|---------|-----------------|
| **Unified Storage** | ArcadeDB | Apache 2.0 | Only multi-model DB with graph + vector + doc + KV + full-text + time-series in one ACID engine. No operational glue. Embedded-first with sub-10ms traversal. |
| **Vector Search** | LSMVector (jvector HNSW) | Apache 2.0 | Native to ArcadeDB. Product Quantization compression. No external vector DB needed. |
| **Full-Text Search** | Lucene BM25 | Apache 2.0 | Native to ArcadeDB. Battle-tested. Powers BM25 leg of hybrid search. |
| **Entity Resolution** | Custom (Graphiti-inspired) | MIT | 5-phase cascade: exact → entropy → MinHash → cosine → LLM. Replaces Splink with AI-native approach. |
| **Ontology Engine** | Custom (TrustGraph-inspired) | Apache 2.0 | OWL-like JSON, semantic routing, Jinja2 prompt injection. Active constraint during extraction. |
| **Feedback Engine** | Custom (Cognee-inspired) | Apache 2.0 | Streaming EMA (α=0.1). Idempotent. Session-aware. Graph gets smarter with use. |
| **Connectors** | Airbyte + Custom SDK | Apache 2.0 | 600+ pre-built via Airbyte + 6 hand-built P0 connectors (Gmail, Salesforce, Slack, GitHub, Zendesk, HubSpot) with deep extraction. Custom SDK for building more. |
| **API Server** | FastAPI (Python) | MIT | Async, high-performance, auto-generated OpenAPI docs. |
| **MCP Server** | Custom (multi-transport) | MIT | stdio/SSE/HTTP. Layers context tools on ArcadeDB's built-in MCP. |
| **Observability** | OpenTelemetry + Prometheus | Apache 2.0 | Span tracing for pipeline steps, searches, queries. NullSpan graceful fallback. |
| **Graph Algorithms** | ArcadeDB native (70+ SIMD) | Apache 2.0 | PageRank, Louvain, Label Propagation, shortest path, betweenness. Java 21 Vector API SIMD acceleration. |
| **LLM Providers** | OpenAI + Anthropic | — | Extraction, dedup, summarization, reranking. Extensible interface. |
| **Deployment** | Docker / Kubernetes | — | Dev via Compose, prod via K8s HA clustering, embedded via jpype. |

---

## 19. Architecture — The 5 Layers

See [Section 3 (Mental Model)](#3-the-mental-model) for the intuitive version. Here's the precise technical stack at each layer:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: INTEGRATION                                                     │
│ Python SDK · MCP Server (stdio/SSE/HTTP) · REST API (FastAPI) · GraphQL  │
│ Wire Protocols: Bolt · PostgreSQL · MongoDB · Redis · gRPC · HTTP        │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: RBAC & AUTH (PLANNED)                                           │
│ API Keys (SHA-256) · OAuth 2.0 · Role Scoping · Append-Only Audit Logs   │
│ 6 Roles: Owner · Admin · Editor · Viewer · Agent · Connector             │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: CONTEXTD ENGINE (LIVE + BUILDING)                               │
│ 10-Step Ingestion · 5-Phase Entity Resolution · Hybrid Query Engine      │
│ 7-Step Context Assembly · Context Cores · Feedback EMA · Ontology Engine │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: ARCADEDB UNIFIED STORAGE (LIVE)                                 │
│ Graph + Document + KV + Vector (HNSW/PQ) + Full-Text (BM25)             │
│ + Time-Series (Gorilla XOR) · 70+ SIMD Algorithms · ACID Transactions    │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: CONNECTOR LAYER (LIVE)                                          │
│ Airbyte Engine (600+ sources) · Custom SDK Connectors (6 P0 + SDK)       │
│ OAuth2 Service (30+ providers) · Incremental Sync                        │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 20. The Closed Loop

This is how data *actually* flows. Note the feedback loop writing back to graph storage:

```
CONNECTOR               INGESTION PIPELINE                     QUERY ENGINE
Gmail ──┐           ┌─ Step 1: Create Episode                Natural Language Query
Slack ──┤           ├─ Step 2: Retrieve Context                     │
SFDC ──┼── Eps ──►├─ Step 3: Extract Nodes ◄── Ontology            ▼
GitHub─┤           ├─ Step 4: Resolve (deterministic)        1. Parse Intent
  ...  │           ├─ Step 5: Resolve (semantic+LLM)         2. Hybrid Search ◄── feedback_weight
       │           ├─ Step 6: Extract Edges ◄── Ontology     3. Rerank ◄── feedback_weight
       │           ├─ Step 7: Dedup/Invalidate Edges         4. Apply Feedback Weights
       │           ├─ Step 8: Generate Embeddings            5. Budget-Aware Pruning
       │           ├─ Step 9: Save to Graph ───────────────► 6. Temporal Enrichment
       │           └─ Step 10: Community Detection           7. Assemble Context Window
       │                                                            │
       │           CONTEXT CORES                                    │
       │           Build ◄── Snapshot ◄── Graph Storage             │
       │           Test ◄── Query Suite                             │
       │           Promote ──► Production                           ▼
       │           Rollback ◄── Previous Version              ASSEMBLED CONTEXT
       │                                                            │
       │           FEEDBACK LOOP                                    ▼
       └───── Agent rates response (1-5) ───────────────► EMA Weight Update
                    used_entities/edges ─────────────────► per node & edge
                    idempotent processing ──────────────► ──► Graph Storage
```

---

## 21. What ContextD Builds vs. What ArcadeDB Provides

This distinction is critical for implementation:

| ArcadeDB Provides (Storage Primitives) | ContextD Builds (Intelligence Layer) |
|----------------------------------------|-------------------------------------|
| Graph engine (Cypher, Gremlin, SQL) | 10-step ingestion pipeline |
| Vector indexes (LSMVector HNSW) | 5-phase entity resolution (MinHash + cosine + LLM) |
| Full-text search (Lucene BM25) | Ontology-constrained extraction |
| Document storage (JSON) | Streaming EMA feedback engine |
| Key-value store | 7-step context assembly |
| Time-series (Gorilla XOR) | Bitemporal schema design |
| 70+ SIMD graph algorithms | Context Cores (versioning) |
| Wire protocols (Bolt, PG, Mongo, Redis, gRPC) | MCP/API integration surface |
| HA clustering, WAL, ACID | Connector SDK + quality layer |
| Built-in MCP server | Decision lineage model |

**Key insight:** ArcadeDB is a powerful storage engine. ContextD is the intelligence layer that makes it useful for AI context. Every ContextD feature is purpose-built for producing the best possible context window for AI agents.

---

## 22. Integration Paths

### Python SDK

```python
from contextd import ContextD
from contextd.search import COMBINED_HYBRID_SEARCH_RRF

# Embedded mode — database runs in-process, < 10ms latency
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

# Query with hybrid search
result = db.query(
    "Who are the decision makers for Project Atlas?",
    config=COMBINED_HYBRID_SEARCH_RRF,
)

# Temporal query
result = db.query("What did we know about Atlas on March 15th?", as_of="2026-03-15")

# Get assembled context for an AI agent
context = db.get_context(query="Draft a follow-up email", max_tokens=2000)

# Submit feedback
await db.feedback(session_id="sess_1", query_id="q_1", score=4,
                  used_entities=["e_789"], used_edges=["edge_456"])

# Context Core operations
core = db.core.build(name="acme-context", graph="production")
db.core.promote(core="acme-context:v3", target="production")
```

### MCP Server (Two-Layer Architecture)

| Layer | What It Provides | Tools |
|-------|-----------------|-------|
| **Layer 1: ArcadeDB Built-in** | Raw database operations | execute_command, get_schema, list_databases, query, server_status |
| **Layer 2: ContextD** | Context-specific tools | query_context, get_entity, get_timeline, get_decision_lineage, get_saga_summary, submit_feedback, ingest_episode |

| Transport | Use Case |
|-----------|----------|
| `stdio` | Claude Code, Cursor, Windsurf — local AI tool integration |
| `SSE` | Web-based agent frameworks, real-time streaming |
| `HTTP` | REST-based integrations, serverless functions |

### REST API (FastAPI)

```
POST   /query                       # Natural language query
POST   /cypher                      # Direct Cypher query
POST   /search                      # Hybrid search with config
GET    /entities/:id                # Get entity by ID
GET    /entities/:id/relationships  # Get relationships
GET    /entities/:id/timeline       # Bitemporal timeline
GET    /decisions/:id/lineage       # Full decision chain
GET    /sagas/:id/summary           # Saga narrative
POST   /context                     # Assemble context for agent
POST   /ingest/episode              # Ingest raw data
POST   /feedback                    # Submit feedback rating
POST   /cores/build                 # Build context core
POST   /cores/:id/promote           # Promote to production
POST   /cores/:id/rollback          # Rollback
```

### Wire Protocols (Polyglot — All hit the same data)

| Protocol | Drivers | Use Case |
|----------|---------|----------|
| **Bolt** | Neo4j Python/Java/Node/Go/.NET | Cypher queries, existing Neo4j code |
| **PostgreSQL** | psql, pgAdmin, JDBC, SQLAlchemy | SQL-familiar teams, BI tools |
| **MongoDB** | PyMongo, Mongoose | Document-oriented access |
| **Redis** | redis-py, Jedis | Key-value caching, sessions |
| **gRPC** | Custom clients (any language) | High-performance inter-service |
| **HTTP/REST** | curl, any HTTP client | Universal access |

**Key advantage:** A single ContextD instance speaks all 6 protocols simultaneously. No driver lock-in. Use whatever your team already knows.

---

## 23. Observability

### What Gets Traced (OpenTelemetry)

| Operation | Spans Created |
|-----------|--------------|
| Ingestion pipeline | 1 parent + 1 child per step (all 10 steps) |
| Entity resolution | 1 span per stage (normalize, entropy, minhash, cosine, llm) |
| Search | 1 parent + child per method (BM25, cosine, BFS) + reranker |
| Context assembly | 1 span covering token optimization and packaging |
| Feedback | 1 span per weight update batch |
| Connector sync | 1 parent + children for auth, extract, transform, load |

### Semantic Span Attributes

Every span carries domain-specific attributes:

```
contextd.pipeline.name          = "gmail_connector_v1"
contextd.pipeline.task_name     = "extract_nodes"
contextd.pipeline.episode_id    = "ep_456"
contextd.search.type            = "COMBINED_HYBRID_SEARCH_RRF"
contextd.search.query           = "Acme deal status"
contextd.search.result_count    = 23
contextd.resolution.stage       = "minhash"
contextd.session.id             = "sess_abc"
contextd.feedback.score         = 4
```

### Prometheus Metrics

| Metric | Type |
|--------|------|
| `contextd_queries_total` | Counter |
| `contextd_query_latency_seconds` | Histogram |
| `contextd_ingestion_episodes_total` | Counter |
| `contextd_ingestion_latency_seconds` | Histogram |
| `contextd_entity_resolution_accuracy` | Gauge |
| `contextd_feedback_scores` | Histogram |
| `contextd_context_tokens_saved` | Counter |

### Configuration

```python
db = ContextD(
    path="./my_graph",
    tracing=True,
    otel_service_name="contextd-production",
    otel_exporter_otlp_endpoint="https://otel-collector.internal:4318",
)
# Or via env vars: CONTEXTD_TRACING_ENABLED, OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT
```

**Graceful fallback:** When OTEL is not installed, ContextD uses `NullSpan` — all tracing calls become no-ops. Zero disruption.

---

## 24. Security, RBAC & Compliance

### Six Roles with Permissions Matrix

| Permission | Owner | Admin | Editor | Viewer | Agent | Connector |
|-----------|-------|-------|--------|--------|-------|-----------|
| Read entities/relationships/facts | Y | Y | Y | scoped | scoped | N |
| Read decision lineage | Y | Y | Y | scoped | scoped | N |
| Read episodes (raw data) | Y | Y | Y | N | N | N |
| Write entities/facts | Y | Y | Y | N | N | own source |
| Submit feedback | Y | Y | Y | N | Y | N |
| Manage connectors | Y | Y | N | N | N | N |
| Manage context cores | Y | Y | N | N | N | N |
| Natural language query | Y | Y | Y | scoped | scoped | N |
| Direct Cypher/SQL query | Y | Y | Y | N | N | N |
| Delete graph | Y | N | N | N | N | N |

### Scoping (3 Dimensions)

Viewer and Agent roles can be restricted along three dimensions:

```json
// Sales agent: can only see Gmail + Salesforce data
{
  "role": "agent",
  "name": "sales-agent",
  "scopes": { "sources": ["salesforce", "gmail"] }
}

// Marketing analyst: sees only companies, deals, campaigns
{
  "role": "viewer",
  "name": "marketing-analyst",
  "scopes": { "entity_types": ["company", "deal", "campaign"] }
}

// Project-scoped agent: only sees Project Atlas data
{
  "role": "agent",
  "name": "atlas-agent",
  "scopes": { "tags": ["project:atlas"] }
}
```

### Multi-Tenancy

Complete isolation: each tenant gets a **separate ArcadeDB database**. No cross-tenant data access possible. Separate connector auth per tenant.

```
Organization (Tenant)
├── Graph (isolated ArcadeDB database)
│   ├── Connectors (data sources)
│   ├── Entities, Relationships, Facts, Episodes, Sagas, Communities
│   └── Context Cores (versioned snapshots)
├── Users
│   ├── user_1 (role: owner)
│   ├── user_2 (role: admin)
│   └── user_3 (role: viewer, scope: sources=["salesforce"])
├── API Keys
│   ├── key_1 (role: editor)
│   ├── key_2 (role: agent, scope: sources=["gmail"])
│   └── key_3 (role: agent, scope: tags=["project:atlas"])
└── Audit Log (append-only, immutable, queryable)
```

### Audit Logging

Every data access is logged. Append-only, immutable:

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

Retention: 1 year (free), 7 years (enterprise).

### Encryption & Compliance

- **In transit:** TLS 1.3
- **At rest:** AES-256 (cloud deployments)
- **API keys:** SHA-256 hashed, never stored in plaintext, revocable
- **PII:** Optional auto-detection with redaction or tagging
- **Right to deletion:** Cascade delete — removing an entity removes all linked relationships, facts, and episode references

| Standard | Timeline | Scope |
|----------|----------|-------|
| **GDPR** | Launch (P0) | Data residency, right to deletion, consent tracking |
| **SOC 2 Type I** | Month 9 | Controls documentation, audit readiness |
| **SOC 2 Type II** | Month 15 | Full audit with 6-month observation |
| **ISO 27001** | Month 18 | Information security management system |

---

## 25. Deployment Modes

| Mode | Latency | How to Start | Use Case |
|------|---------|-------------|----------|
| **Embedded** | <10ms | `pip install contextd` | Local agents, edge devices, prototyping |
| **Server** | <50ms | `docker compose up` | Team usage, shared instance |
| **Cloud** | <300ms | Sign up at contextd.ai | Production, fully managed |
| **Enterprise** | <50ms | On-prem / air-gapped K8s | HA clustering, compliance |

### Performance Profiles

| Profile | Page Cache | Workers | Use Case |
|---------|-----------|---------|----------|
| `high-performance` | Unlimited (50% RAM) | 50% cores | Production, benchmarking |
| `default` | 4GB | Auto | General use |
| `low-ram` | 16MB | Auto | Edge devices, constrained environments |
| `low-cpu` | Standard | 1 thread | Background processing, minimal resources |

### High Availability

ArcadeDB supports **Leader-Replica clustering** with synchronous replication (configurable), automatic leader election, and Write-Ahead Log (WAL) with configurable flush modes (no-flush / flush / fsync). Production deployments use leader-replica replication for zero-downtime failover.

### Scalability Targets

| Dimension | v1 | v2 |
|-----------|----|----|
| Entities per graph | 10M | 100M |
| Relationships per graph | 50M | 500M |
| Facts per graph | 100M | 1B |
| Episodes per graph | 10M | 100M |
| Connectors per tenant | 30 | 100 |
| Concurrent queries | 100 QPS | 500 QPS |
| Cloud tenants | 1,000 | 10,000 |

### Java 21 Dependency Note

Embedded mode (`pip install contextd`) requires **Java 21+** via jpype for ArcadeDB's JVM. Most production deployments use standalone server mode (Docker), which hides the Java dependency entirely. The Java 21 requirement only affects developers running embedded mode locally.

---

## 26. Use Cases

### Use Case 1: AI Agent Memory — Customer 360

**The scenario:** An AI sales assistant needs to prepare for a customer call.

**Without ContextD:** Agent searches CRM for deal info. Doesn't know about 3 angry support tickets filed last week, a marketing email that promised a feature that doesn't exist, or a Slack conversation where the CEO mentioned evaluating competitors.

**With ContextD:**
```python
context = db.get_context(
    query="Prepare me for a call with Acme Corp",
    max_tokens=2000,
    include_lineage=True,
)
# Returns: deal status, ALL touchpoints across CRM + support + marketing + comms,
# sentiment trajectory, open issues, key stakeholders, and decision history
# Feedback-weighted: most useful context from prior call preps ranked highest
```

### Use Case 2: Compliance & Audit — Decision Lineage

**The scenario:** Legal needs all discount approvals over 15% in Q1.

```cypher
MATCH (d:Decision {decision_type: "discount"})
WHERE d.outcome > "15%"
  AND d.decided_at >= datetime("2026-01-01")
  AND d.decided_at < datetime("2026-04-01")
OPTIONAL MATCH (d)-[:DECIDED_BY]->(approver)
OPTIONAL MATCH (d)-[:APPLIED_POLICY]->(policy)
RETURN d.subject, d.outcome, approver.name,
       policy.name, d.exception, d.justification
ORDER BY d.decided_at
```

Every discount links back to its inputs, policy, and exception status. **This is impossible with vector search** — you need graph lineage, bitemporal tracking, and decision entities.

### Use Case 3: Audience Activation — Cross-System Behavioral Query

**The scenario:** "Find high-usage companies with urgent tickets, not contacted in 14 days" — churn risk cohort:

```cypher
MATCH (c:Entity {entity_type: "company"})-[:HAS_FACT]->(f1:Fact {predicate: "product_usage"})
WHERE f1.object > "high"
AND EXISTS {
  MATCH (c)-[:FILED]->(t:Entity {entity_type: "ticket"})
  WHERE t.attributes.priority = "high"
    AND t.valid_at > datetime() - duration("P30D")
}
AND NOT EXISTS {
  MATCH (c)-[:CONTACTED_BY]->(outreach)
  WHERE outreach.valid_at > datetime() - duration("P14D")
}
RETURN c.name, count(t) AS open_tickets
ORDER BY c.attributes.arr DESC
```

This crosses CRM, support, and marketing data in a **single graph query** with bitemporal filtering. Impossible with separate databases.

### Use Case 4: RAG Enhancement — 80% Token Reduction

```python
from contextd.search import COMBINED_HYBRID_SEARCH_RRF

context = db.get_context(
    query="What's our current security posture for the AWS deployment?",
    max_tokens=1500,
    search_recipe=COMBINED_HYBRID_SEARCH_RRF,
)
# Returns: 847 tokens (vs. ~3,400 from chunk RAG)
# Connected facts: architecture docs, security review, Jira tickets,
# pen test results, compliance policy
# Feedback-weighted: elements proven useful in past security queries rank higher
```

**How the reduction works:** Chunk-based RAG retrieves ~10-20 similar chunks (each 200-400 tokens) → ~3,400 tokens with massive redundancy (same entity mentioned across 5 chunks). ContextD retrieves structured entities, relationships, and facts — deduplicated, temporally filtered, feedback-weighted. ~847 tokens. Same coverage, 80% smaller context window.

### Use Case 5: Context Core CI/CD

```bash
# Build a snapshot of current graph state
contextd core build --name "customer-context" --graph "production"

# Run golden query test suite
contextd core test --core "customer-context:v5" --queries "test-suite.yaml"
# 50/50 pass → promote

contextd core promote --core "customer-context:v5" --target "production"

# Something breaks → rollback in seconds
contextd core rollback --target "production" --to "customer-context:v4"

# See what changed between versions
contextd core diff --from "customer-context:v4" --to "customer-context:v5"
```

---

## 27. Differentiators

| # | Differentiator | What It Means | Status | Why It's Hard to Replicate |
|---|---------------|--------------|--------|---------------------------|
| 1 | **Database-native** | Single ACID engine with 6 data models | LIVE | Requires building on a multi-model DB from day one, not bolting on |
| 2 | **Bitemporal by design** | Every fact tracks event time + transaction time | LIVE | Can't be added retroactively — must be in the data model from the start |
| 3 | **Feedback-weighted retrieval** | Graph improves via EMA learning (α=0.1) | LIVE | Requires integrating feedback into every query path, not just a reranker |
| 4 | **Ontology-grounded extraction** | Ontology actively constrains LLM output during extraction | BUILDING | Not post-hoc validation — semantic routing during prompt construction |
| 5 | **Context Cores** | CI/CD for knowledge graphs — build, test, version, promote, rollback | PLANNED | Requires content-addressed snapshotting of entire graph + embeddings + weights |
| 6 | **Decision lineage** | Decisions are first-class, auditable, traceable entities | PLANNED | Requires purpose-built schema, not just graph traversal |
| 7 | **10-step episodic ingestion** | Full provenance on everything (Graphiti + TrustGraph + Cognee inspired) | LIVE | Three frameworks' best ideas, unified into one pipeline |
| 8 | **Hybrid retrieval composability** | 3 methods x 5 rerankers = 15 configurable strategies | BUILDING | Requires BM25, vectors, and graph traversal in the same engine |
| 9 | **Wire protocol polyglot** | 6 protocols (Bolt, PG, Mongo, Redis, gRPC, HTTP), 1 engine | ArcadeDB feature — no competitor has this breadth |
| 10 | **80% token reduction** | Structured context vs. chunk-based RAG | Only possible with entity dedup, temporal filtering, and feedback weights |
| 11 | **Apache 2.0 substrate** | No SSPL, no Commons Clause, no BSL | True open-source — can embed, modify, and distribute freely |

---

## 28. Implementation Status

### LIVE (Production-Ready)
- Core data models (8 Pydantic classes)
- ArcadeDB driver (HTTP + MCP)
- 10-step ingestion pipeline
- Entity resolution (MinHash + LLM)
- LLM integration (OpenAI + Anthropic)
- Embedding generation (OpenAI)
- Feedback engine (EMA + sessions)
- 30+ data connectors
- OAuth2 service (30+ providers)
- FastAPI REST API
- OpenTelemetry tracing (NullSpan fallback)
- Chat/RAG service (streaming)

### BUILDING (In Progress)
- Hybrid search (BM25 + Cosine + BFS)
- Context assembly (token optimization)
- Community detection (SIMD algorithms)
- Ontology engine (OWL-like JSON)
- BDD test suite (pytest + vitest)

### PLANNED (Roadmap)
- Context Cores (build/test/promote/rollback)
- MCP Server (stdio/SSE/HTTP)
- Rerankers (RRF, MMR, Cross-Encoder, Node Distance, Episode Mentions)
- Decision lineage (first-class entities)
- RBAC enforcement (all roles + scoping)
- Auto-feedback detection (LLM-based)
- Context Core diffing (between versions)
- Grafana dashboards

---

## 29. Build Guide — Full Implementation Reference

If you're implementing ContextD from scratch, build in this order. Each phase depends on the previous one. Every step includes the **exact tech stack, actual code, key algorithms, and design rationale.**

### Environment & Dependencies

```bash
# Required tools
Python 3.11+          # async support, match statements, Pydantic v2
Docker + Docker Compose  # ArcadeDB, Airbyte
Java 21+              # Only for embedded mode (jpype)

# Python dependencies (requirements.txt)
pydantic>=2.0         # Data models, LLM output validation
httpx>=0.25           # Async HTTP client for ArcadeDB API
openai>=1.0           # LLM extraction + embeddings
anthropic>=0.30       # Alternative LLM provider
fastapi>=0.110        # REST API server
uvicorn>=0.29         # ASGI server
jinja2>=3.1           # Ontology prompt templates
msgpack>=1.0          # Context Core serialization
datasketch>=1.6       # MinHash/LSH implementation
numpy>=1.26           # Vector math (cosine similarity)
opentelemetry-api>=1.24       # Tracing
opentelemetry-sdk>=1.24       # Tracing
prometheus-client>=0.20       # Metrics
google-auth>=2.29     # Gmail OAuth2
google-api-python-client>=2.0 # Gmail API
```

```yaml
# docker-compose.yml — Development environment
version: "3.9"
services:
  arcadedb:
    image: arcadedata/arcadedb:latest
    ports:
      - "2480:2480"   # HTTP API
      - "2424:2424"   # Binary protocol
      - "6379:6379"   # Redis protocol
      - "5432:5432"   # PostgreSQL protocol
      - "7687:7687"   # Bolt (Neo4j) protocol
      - "8843:8843"   # gRPC protocol
    environment:
      JAVA_OPTS: "-Darcadedb.server.rootPassword=contextd_dev"
      arcadedb.server.plugins: "MongoDB Protocol:com.arcadedb.mongo.MongoDBProtocolPlugin"
    volumes:
      - arcadedb_data:/home/arcadedb/databases
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:2480/api/v1/ready"]
      interval: 5s
      retries: 10

volumes:
  arcadedb_data:
```

```bash
# Environment variables (.env)
ARCADEDB_URL=http://localhost:2480
ARCADEDB_USERNAME=root
ARCADEDB_PASSWORD=contextd_dev
ARCADEDB_DATABASE=contextd

OPENAI_API_KEY=sk-...              # For embeddings + extraction
OPENAI_MODEL=gpt-4o                # For entity/edge extraction
OPENAI_EMBEDDING_MODEL=text-embedding-3-small  # 1536 dimensions

ANTHROPIC_API_KEY=sk-ant-...       # Alternative LLM
ANTHROPIC_MODEL=claude-sonnet-4-6  # For extraction

CONTEXTD_FEEDBACK_ALPHA=0.1        # EMA learning rate
CONTEXTD_ENTROPY_THRESHOLD=1.5     # Shannon entropy gate
CONTEXTD_MINHASH_PERMS=32          # MinHash permutations
CONTEXTD_MINHASH_THRESHOLD=0.9     # Jaccard threshold
CONTEXTD_COSINE_THRESHOLD=0.6      # Name embedding threshold
CONTEXTD_COSINE_MAX_CANDIDATES=15  # Max candidates per entity
CONTEXTD_ONTOLOGY_THRESHOLD=0.3    # Ontology selection threshold
CONTEXTD_ONTOLOGY_TOP_K=10         # Ontology elements per chunk

CONTEXTD_TRACING_ENABLED=false     # OpenTelemetry
OTEL_SERVICE_NAME=contextd
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

---

### Phase 1: Storage Foundation (Weeks 1-3)

**Tech stack:** ArcadeDB (Docker), httpx (async HTTP), Pydantic v2
**Why ArcadeDB:** Only multi-model DB that does graph + vector + full-text + document + KV + time-series in one ACID engine. Apache 2.0 (no SSPL/BSL). Embedded-first with sub-10ms traversal. 70+ SIMD-accelerated graph algorithms. Built-in wire protocol polyglot (Bolt, PG, Mongo, Redis, gRPC).

#### Step 1: ArcadeDB Driver

**Why httpx over requests:** Async-native, connection pooling, HTTP/2 support. ArcadeDB exposes a REST API — no proprietary driver needed.

```python
# contextd/db/driver.py
import httpx
from pydantic import BaseModel
from typing import Any

class ArcadeDBDriver:
    """Async HTTP driver for ArcadeDB REST API.

    Design choice: We use the HTTP API rather than the binary protocol because:
    1. It works in embedded mode (jpype) and server mode identically
    2. No proprietary driver dependency
    3. JSON responses map directly to Pydantic models
    4. Connection pooling via httpx handles concurrency
    """

    def __init__(self, url: str, username: str, password: str, database: str):
        self.base_url = f"{url}/api/v1"
        self.database = database
        self.client = httpx.AsyncClient(
            auth=(username, password),
            timeout=30.0,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def command(self, sql: str, params: dict = None) -> dict:
        """Execute a write command (CREATE, UPDATE, DELETE).
        Uses /command endpoint which supports DDL and DML."""
        response = await self.client.post(
            f"{self.base_url}/command/{self.database}",
            json={"language": "sql", "command": sql, "params": params or {}},
        )
        response.raise_for_status()
        return response.json()

    async def query(self, sql: str, params: dict = None) -> list[dict]:
        """Execute a read query (SELECT, MATCH).
        Uses /query endpoint optimized for reads."""
        response = await self.client.post(
            f"{self.base_url}/query/{self.database}",
            json={"language": "sql", "command": sql, "params": params or {}},
        )
        response.raise_for_status()
        return response.json().get("result", [])

    async def cypher(self, query: str, params: dict = None) -> list[dict]:
        """Execute a Cypher query (MATCH, CREATE, MERGE).
        ArcadeDB supports Cypher natively via its graph engine."""
        response = await self.client.post(
            f"{self.base_url}/command/{self.database}",
            json={"language": "cypher", "command": query, "params": params or {}},
        )
        response.raise_for_status()
        return response.json().get("result", [])

    async def create_database(self):
        """Create the database if it doesn't exist."""
        await self.client.post(
            f"{self.base_url}/server",
            json={"command": f"create database {self.database}"},
        )

    async def close(self):
        await self.client.aclose()
```

#### Step 2: Schema Definition

**Why separate vertex/edge types (not generic nodes):** ArcadeDB enforces type safety at the storage level. Typed vertices get their own indexes, property validation, and inheritance. This means `Entity` queries never scan `Episode` data — critical for performance at scale.

```python
# contextd/db/schema.py
SCHEMA_COMMANDS = [
    # --- Vertex Types (one per primitive) ---
    # Each carries bitemporal fields + provenance
    """CREATE VERTEX TYPE Entity IF NOT EXISTS""",
    """ALTER TYPE Entity IF NOT EXISTS
       CREATE PROPERTY id STRING,
       CREATE PROPERTY canonical_id STRING,
       CREATE PROPERTY entity_type STRING,
       CREATE PROPERTY name STRING,
       CREATE PROPERTY labels LIST,
       CREATE PROPERTY summary STRING,
       CREATE PROPERTY name_embedding LIST,
       CREATE PROPERTY source STRING,
       CREATE PROPERTY feedback_weight DOUBLE DEFAULT 0.5,
       CREATE PROPERTY valid_at DATETIME,
       CREATE PROPERTY invalid_at DATETIME,
       CREATE PROPERTY created_at DATETIME,
       CREATE PROPERTY expired_at DATETIME,
       CREATE PROPERTY confidence DOUBLE,
       CREATE PROPERTY source_pipeline STRING,
       CREATE PROPERTY source_task STRING,
       CREATE PROPERTY extraction_method STRING""",

    """CREATE VERTEX TYPE Episode IF NOT EXISTS""",
    """ALTER TYPE Episode IF NOT EXISTS
       CREATE PROPERTY id STRING,
       CREATE PROPERTY episode_type STRING,
       CREATE PROPERTY source STRING,
       CREATE PROPERTY content STRING,
       CREATE PROPERTY metadata MAP,
       CREATE PROPERTY entity_edges LIST,
       CREATE PROPERTY valid_at DATETIME,
       CREATE PROPERTY created_at DATETIME""",

    """CREATE VERTEX TYPE Fact IF NOT EXISTS""",
    """ALTER TYPE Fact IF NOT EXISTS
       CREATE PROPERTY id STRING,
       CREATE PROPERTY subject_entity_id STRING,
       CREATE PROPERTY predicate STRING,
       CREATE PROPERTY object STRING,
       CREATE PROPERTY valid_at DATETIME,
       CREATE PROPERTY invalid_at DATETIME,
       CREATE PROPERTY created_at DATETIME,
       CREATE PROPERTY expired_at DATETIME,
       CREATE PROPERTY confidence DOUBLE,
       CREATE PROPERTY feedback_weight DOUBLE DEFAULT 0.5,
       CREATE PROPERTY source_episode_id STRING,
       CREATE PROPERTY extraction_method STRING""",

    """CREATE VERTEX TYPE Saga IF NOT EXISTS""",
    """CREATE VERTEX TYPE Community IF NOT EXISTS""",
    """CREATE VERTEX TYPE Decision IF NOT EXISTS""",

    # --- Edge Types ---
    """CREATE EDGE TYPE RELATES_TO IF NOT EXISTS""",  # Entity → Entity (Relationship)
    """ALTER TYPE RELATES_TO IF NOT EXISTS
       CREATE PROPERTY relationship_type STRING,
       CREATE PROPERTY fact STRING,
       CREATE PROPERTY fact_embedding LIST,
       CREATE PROPERTY weight DOUBLE,
       CREATE PROPERTY feedback_weight DOUBLE DEFAULT 0.5,
       CREATE PROPERTY episodes LIST,
       CREATE PROPERTY valid_at DATETIME,
       CREATE PROPERTY invalid_at DATETIME,
       CREATE PROPERTY created_at DATETIME,
       CREATE PROPERTY expired_at DATETIME,
       CREATE PROPERTY reference_time DATETIME,
       CREATE PROPERTY source STRING,
       CREATE PROPERTY extraction_method STRING,
       CREATE PROPERTY source_pipeline STRING,
       CREATE PROPERTY source_task STRING""",

    """CREATE EDGE TYPE HAS_FACT IF NOT EXISTS""",       # Entity → Fact
    """CREATE EDGE TYPE EXTRACTED_FROM IF NOT EXISTS""",  # Entity/Fact → Episode
    """CREATE EDGE TYPE HAS_EPISODE IF NOT EXISTS""",     # Saga → Episode
    """CREATE EDGE TYPE NEXT_EPISODE IF NOT EXISTS""",    # Episode → Episode
    """CREATE EDGE TYPE HAS_MEMBER IF NOT EXISTS""",      # Community → Entity
    """CREATE EDGE TYPE DECIDED_BY IF NOT EXISTS""",      # Decision → Entity
    """CREATE EDGE TYPE INFORMED_BY IF NOT EXISTS""",     # Decision → Fact/Episode

    # --- Indexes ---
    # HNSW vector index on entity name embeddings — powers cosine search in retrieval
    """CREATE INDEX ON Entity(name_embedding) VECTOR HNSW
       TYPE FLOAT DIMENSIONS 1536 SIMILARITY COSINE""",
    # HNSW vector index on relationship fact embeddings — powers edge dedup + search
    """CREATE INDEX ON RELATES_TO(fact_embedding) VECTOR HNSW
       TYPE FLOAT DIMENSIONS 1536 SIMILARITY COSINE""",
    # Full-text index on entity names — powers BM25 leg of hybrid search
    """CREATE INDEX ON Entity(name) FULL_TEXT""",
    # Full-text index on relationship facts — powers BM25 edge search
    """CREATE INDEX ON RELATES_TO(fact) FULL_TEXT""",
    # Unique index on entity IDs
    """CREATE INDEX ON Entity(id) UNIQUE""",
    """CREATE INDEX ON Episode(id) UNIQUE""",
    """CREATE INDEX ON Fact(id) UNIQUE""",
]

async def initialize_schema(driver: ArcadeDBDriver):
    """Run all schema commands. Idempotent via IF NOT EXISTS."""
    for cmd in SCHEMA_COMMANDS:
        await driver.command(cmd)
```

#### Step 3: Pydantic Models

**Why Pydantic v2:** 5-50x faster validation than v1. Native JSON schema generation for OpenAPI docs. `model_validator` for cross-field validation. Direct serialization to ArcadeDB-compatible dicts.

```python
# contextd/models.py
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from uuid import uuid4
from typing import Optional
from enum import Enum

class EntityType(str, Enum):
    PERSON = "person"
    COMPANY = "company"
    PROJECT = "project"
    TICKET = "ticket"
    DEAL = "deal"
    DOCUMENT = "document"

class ExtractionMethod(str, Enum):
    LLM_EXTRACTION = "llm_extraction"
    STRUCTURED_IMPORT = "structured_import"
    MANUAL = "manual"
    ONTOLOGY_CONSTRAINED = "ontology_constrained"

class Entity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    canonical_id: Optional[str] = None
    entity_type: EntityType
    name: str
    labels: list[str] = []
    summary: str = ""
    name_embedding: list[float] = []
    source: str
    feedback_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expired_at: Optional[datetime] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_pipeline: str = ""
    source_task: str = ""
    extraction_method: ExtractionMethod = ExtractionMethod.LLM_EXTRACTION

    @model_validator(mode="after")
    def set_canonical_id(self):
        if self.canonical_id is None:
            self.canonical_id = self.id
        return self

class Episode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    episode_type: str          # "message" | "json" | "text"
    source: str                # "gmail" | "slack" | "github" | ...
    content: str
    metadata: dict = {}
    entity_edges: list[str] = []
    valid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Fact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    subject_entity_id: str
    predicate: str
    object: str
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expired_at: Optional[datetime] = None
    confidence: float = 1.0
    feedback_weight: float = 0.5
    source_episode_id: str = ""
    extraction_method: ExtractionMethod = ExtractionMethod.LLM_EXTRACTION

# --- LLM Output Models (for structured extraction) ---

class ExtractedEntity(BaseModel):
    """What the LLM returns when extracting entities from episode content."""
    name: str
    entity_type: str
    summary: str = ""

class ExtractedEntities(BaseModel):
    entities: list[ExtractedEntity]

class ExtractedEdge(BaseModel):
    """What the LLM returns when extracting relationships."""
    source_name: str
    target_name: str
    relationship_type: str
    fact: str                          # Natural language description
    valid_at: Optional[str] = None     # ISO datetime string
    invalid_at: Optional[str] = None

class ExtractedEdges(BaseModel):
    edges: list[ExtractedEdge]

class EdgeDedupResult(BaseModel):
    """LLM output for edge dedup — which are duplicates, which are contradictions."""
    duplicate_facts: list[str] = []     # IDs of existing edges that are duplicates
    contradicted_facts: list[str] = []  # IDs of existing edges that are superseded

class NodeDuplicate(BaseModel):
    """LLM output for entity resolution — confirmed duplicate pair."""
    entity_name: str
    duplicate_of: str                   # Name of existing entity it matches
    confidence: float = 0.9
```

---

**How to verify Phase 1 is working:**
```bash
# 1. ArcadeDB is running
curl http://localhost:2480/api/v1/ready  # Should return 200

# 2. Database exists
curl -u root:contextd_dev http://localhost:2480/api/v1/databases  # Should list "contextd"

# 3. Schema is loaded — run from Python:
#    entities = await driver.query("SELECT count(*) FROM Entity")
#    # Should return [{"count": 0}] (empty but no error = schema exists)
```

---

### Phase 2: Ingestion Pipeline (Weeks 4-7)

**Tech stack:** OpenAI SDK (async), Pydantic structured output, Jinja2 templates
**Why OpenAI for extraction:** Best structured output support (function calling, JSON mode). Anthropic Claude used as fallback. Both accessed via async clients for pipeline parallelism.

#### Step 4: LLM Client with Structured Output

**Design choice — why Pydantic for LLM output:** The LLM returns JSON that must conform to our schema. Pydantic validates this at parse time, catching hallucinated fields or invalid types before they enter the graph. This is cheaper than post-hoc cleanup.

```python
# contextd/llm/client.py
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import Type, TypeVar
import json

T = TypeVar("T", bound=BaseModel)

class LLMClient:
    """Async LLM client with structured output via Pydantic models.

    Design choice: We use OpenAI's function calling (tool_use) to get
    structured JSON, then validate with Pydantic. This gives us:
    1. Type-safe extraction (no parsing regexes)
    2. Automatic retry on validation failure
    3. Schema evolution via Pydantic model changes
    """

    def __init__(self, model: str = "gpt-4o"):
        self.client = AsyncOpenAI()  # Uses OPENAI_API_KEY env var
        self.model = model

    async def extract(
        self, prompt: str, output_model: Type[T], temperature: float = 0.0
    ) -> T:
        """Send prompt, get structured output validated against a Pydantic model."""
        # Convert Pydantic model to JSON schema for function calling
        schema = output_model.model_json_schema()

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "extract",
                    "description": f"Extract {output_model.__name__}",
                    "parameters": schema,
                },
            }],
            tool_choice={"type": "function", "function": {"name": "extract"}},
        )

        tool_call = response.choices[0].message.tool_calls[0]
        raw_json = json.loads(tool_call.function.arguments)
        return output_model.model_validate(raw_json)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts via OpenAI embeddings API.
        Uses text-embedding-3-small (1536 dims) — best cost/quality ratio."""
        response = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in response.data]
```

#### Step 4a: Pipeline Orchestrator

This is the `run_pipeline` function that ties all 10 steps together. Every other pipeline step plugs into this orchestrator.

```python
# contextd/pipeline/runner.py
from contextd.models import Episode, Entity
from contextd.llm.client import LLMClient
from contextd.db.driver import ArcadeDBDriver
from contextd.pipeline.extract_nodes import extract_entities
from contextd.pipeline.entity_resolution import EntityResolver
from datetime import datetime

async def run_pipeline(driver: ArcadeDBDriver, llm: LLMClient, episode: Episode) -> dict:
    """Execute the 10-step episodic ingestion pipeline.

    Returns a summary of what was created/merged/superseded.
    Each step is wrapped in an OTEL span (if tracing is enabled).
    """
    stats = {"entities_created": 0, "entities_merged": 0,
             "edges_created": 0, "edges_superseded": 0, "facts_created": 0}

    # Step 1: Save episode to graph
    episode.created_at = datetime.utcnow()
    await driver.command(f"""
        INSERT INTO Episode SET
            id = '{episode.id}', episode_type = '{episode.episode_type}',
            source = '{episode.source}', content = '{_escape(episode.content)}',
            valid_at = '{episode.valid_at.isoformat() if episode.valid_at else ""}',
            created_at = sysdate()
    """)

    # Step 2: Retrieve context (previous episodes in same source for continuity)
    previous = await driver.query(f"""
        SELECT FROM Episode WHERE source = '{episode.source}'
        ORDER BY created_at DESC LIMIT 10
    """)

    # Step 3: Extract entities via LLM
    extracted = await extract_entities(llm, episode, previous, ontology_subset=None)

    # Steps 4-5: Resolve entities (5-phase dedup)
    resolver = EntityResolver(driver, llm)
    existing_entities = await driver.query("SELECT FROM Entity WHERE expired_at IS NULL LIMIT 1000")
    resolved_entities = []
    for ext_entity in extracted.entities:
        new_entity = Entity(
            name=ext_entity.name, entity_type=ext_entity.entity_type,
            summary=ext_entity.summary, source=episode.source,
            source_pipeline="ingestion_v1", extraction_method="llm_extraction",
            source_episode_id=episode.id,
        )
        canonical_id = await resolver.resolve(new_entity, existing_entities)
        if canonical_id:
            new_entity.canonical_id = canonical_id
            stats["entities_merged"] += 1
        else:
            stats["entities_created"] += 1
        resolved_entities.append(new_entity)

    # Step 6: Extract edges via LLM (see extract_edges.py)
    # Step 7: Resolve/dedup edges (see edge_resolution.py)
    # Step 8: Generate embeddings for new entities and edges
    names_to_embed = [e.name for e in resolved_entities if not e.name_embedding]
    if names_to_embed:
        embeddings = await llm.embed(names_to_embed)
        for entity, embedding in zip(
            [e for e in resolved_entities if not e.name_embedding], embeddings
        ):
            entity.name_embedding = embedding

    # Step 9: Bulk save to graph
    for entity in resolved_entities:
        await driver.command(f"""
            INSERT INTO Entity SET
                id = '{entity.id}', canonical_id = '{entity.canonical_id}',
                entity_type = '{entity.entity_type}', name = '{_escape(entity.name)}',
                summary = '{_escape(entity.summary)}', source = '{entity.source}',
                name_embedding = {entity.name_embedding},
                feedback_weight = 0.5, created_at = sysdate(),
                source_pipeline = '{entity.source_pipeline}',
                extraction_method = '{entity.extraction_method}'
        """)

    # Step 10: Community detection (optional, skip for now)
    return stats

def _escape(s: str) -> str:
    """Escape single quotes for ArcadeDB SQL. In production, use parameterized queries."""
    return s.replace("'", "\\'") if s else ""

# ⚠️  IMPORTANT: The f-string SQL throughout this guide is for readability.
# In production, ALWAYS use parameterized queries to prevent SQL injection:
#   await driver.command("INSERT INTO Entity SET name = :name", {"name": entity.name})
# ArcadeDB supports :param syntax in its HTTP API.
```

#### Step 5: Entity Extraction (Pipeline Step 3)

**Why this prompt structure:** The LLM needs three things: (1) the current episode content, (2) previous episodes for context continuity, (3) ontology constraints if active. The prompt explicitly asks for structured output to minimize hallucination.

```python
# contextd/pipeline/extract_nodes.py
from jinja2 import Template

ENTITY_EXTRACTION_PROMPT = Template("""You are an entity extraction system. Extract all entities (people, companies, projects, tickets, deals, documents) from the following content.

{% if previous_episodes %}
## Previous Context (for continuity)
{% for ep in previous_episodes %}
[{{ ep.source }} | {{ ep.valid_at }}]: {{ ep.content[:500] }}
{% endfor %}
{% endif %}

{% if ontology_subset %}
## Ontology Constraints
Only extract entities of these types: {{ ontology_subset.classes | join(', ') }}
Valid relationship types: {{ ontology_subset.properties | join(', ') }}
{% endif %}

## Current Content to Extract From
Source: {{ episode.source }}
Date: {{ episode.valid_at }}
{{ episode.content }}

## Instructions
- Extract every person, company, project, ticket, deal, or document mentioned
- For each entity, provide: name (full name if available), entity_type, and a brief summary
- If the same entity is mentioned multiple ways, pick the most complete name
- Do NOT extract generic terms ("the team", "everyone") unless they refer to a specific named group
""")

async def extract_entities(
    llm: LLMClient,
    episode: Episode,
    previous_episodes: list[Episode],
    ontology_subset: dict | None = None,
) -> ExtractedEntities:
    """Pipeline Step 3: LLM extracts entities from episode content.

    Design choice — why we pass previous episodes:
    When an email says "as Alice mentioned", the LLM needs the prior email
    to know which Alice. Without context, it might create a duplicate or
    miss the reference entirely. Default: last 10 episodes in same saga.
    """
    prompt = ENTITY_EXTRACTION_PROMPT.render(
        episode=episode,
        previous_episodes=previous_episodes[-10:],
        ontology_subset=ontology_subset,
    )
    return await llm.extract(prompt, ExtractedEntities)
```

#### Step 6: Entity Resolution — Full Algorithm Implementation

**Tech stack:** datasketch (MinHash/LSH), numpy (cosine similarity), custom Shannon entropy
**Why datasketch:** Battle-tested MinHash/LSH library, handles the hash math correctly. We don't need to implement our own hash functions — just configure permutations and threshold.

```python
# contextd/pipeline/entity_resolution.py
import math
import re
from collections import Counter
from datasketch import MinHash, MinHashLSH
import numpy as np
from contextd.models import Entity, NodeDuplicate

# ─── Phase 1: Normalization ───
def normalize_name(name: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation.
    Why: "John  Smith" and "john smith" should match in Phase 1,
    avoiding unnecessary MinHash/LLM calls."""
    name = name.lower().strip()
    name = re.sub(r'\s+', ' ', name)         # collapse whitespace
    name = re.sub(r'[^\w\s]', '', name)       # strip punctuation
    return name

# ─── Phase 2: Shannon Entropy Gate ───
def shannon_entropy(name: str) -> float:
    """Calculate Shannon entropy in bits.

    Why this gate exists: Short/repetitive strings like "Q1", "API", "USA",
    or "AAA" have low entropy and produce unreliable fuzzy matches.
    A 3-character string can match almost anything via MinHash.

    Formula: H = -Σ p(x) × log2(p(x)) for each unique character.
    Threshold: < 1.5 bits → skip fuzzy matching entirely.
    """
    if not name:
        return 0.0
    counts = Counter(name.lower())
    total = len(name)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy

def passes_entropy_gate(name: str, threshold: float = 1.5) -> bool:
    """Returns True if the name is reliable enough for fuzzy matching.
    Short names (< 6 chars) or low-entropy names are skipped."""
    if len(name) < 6:
        return False
    return shannon_entropy(name) >= threshold

# ─── Phase 3: MinHash/LSH ───
def build_minhash(name: str, num_perm: int = 32) -> MinHash:
    """Convert a name to a MinHash signature using 3-gram shingles.

    Why 3-grams (not words): Character n-grams catch typos and abbreviations.
    "Jonathan" and "John" share 3-grams like "joh", "ohn".
    Why 32 permutations: Balances accuracy vs. memory. 32 perms give
    ~6% error rate on Jaccard estimates — sufficient for threshold 0.9.
    """
    m = MinHash(num_perm=num_perm)
    # Generate 3-gram shingles from normalized name
    name = normalize_name(name)
    for i in range(len(name) - 2):
        shingle = name[i:i+3]
        m.update(shingle.encode('utf-8'))
    return m

class EntityResolver:
    """5-phase entity resolution pipeline.

    Design rationale for cascading:
    Phase 1 (exact): Free, instant, 100% accurate for exact matches
    Phase 2 (entropy): Free filter, prevents unreliable fuzzy on short strings
    Phase 3 (MinHash): ~$0, <1ms, catches 60% of fuzzy duplicates
    Phase 4 (cosine): ~$0.0001, <10ms, catches 20% more via semantic similarity
    Phase 5 (LLM): ~$0.01, ~500ms, handles the remaining 20% ambiguous cases

    Net effect: ~80% of resolutions are handled before the LLM is called.
    At 10,000 entities/day, this saves ~$80/day in LLM costs.
    """

    def __init__(self, driver, llm, num_perm=32, jaccard_threshold=0.9,
                 cosine_threshold=0.6, max_candidates=15):
        self.driver = driver
        self.llm = llm
        self.num_perm = num_perm
        self.jaccard_threshold = jaccard_threshold
        self.cosine_threshold = cosine_threshold
        self.max_candidates = max_candidates
        # LSH index for fast approximate nearest-neighbor on MinHash
        # band_size=4 with 32 perms = 8 bands → catches pairs with Jaccard ≥ ~0.5
        # We then filter to ≥ 0.9 after candidate retrieval
        self.lsh = MinHashLSH(threshold=jaccard_threshold, num_perm=num_perm)

    async def resolve(self, new_entity: Entity, existing_entities: list[Entity]) -> str | None:
        """Returns canonical_id of matching entity, or None if new.

        Flow: exact_match → entropy_gate → minhash → cosine → llm
        Each phase either returns a match or passes to the next.
        """
        normalized = normalize_name(new_entity.name)

        # Phase 1: Exact match
        for existing in existing_entities:
            if normalize_name(existing.name) == normalized:
                return existing.canonical_id  # Merge immediately

        # Phase 2: Entropy gate
        if not passes_entropy_gate(new_entity.name):
            return None  # Too short/generic for fuzzy → create new entity

        # Phase 3: MinHash/LSH
        new_minhash = build_minhash(new_entity.name, self.num_perm)
        for existing in existing_entities:
            existing_minhash = build_minhash(existing.name, self.num_perm)
            jaccard = new_minhash.jaccard(existing_minhash)
            if jaccard >= self.jaccard_threshold:
                return existing.canonical_id  # High character overlap → merge

        # Phase 4: Cosine similarity on name embeddings
        if not new_entity.name_embedding:
            [embedding] = await self.llm.embed([new_entity.name])
            new_entity.name_embedding = embedding

        candidates = []
        for existing in existing_entities:
            if not existing.name_embedding:
                continue
            similarity = cosine_similarity(
                new_entity.name_embedding, existing.name_embedding
            )
            if similarity >= self.cosine_threshold:
                candidates.append((existing, similarity))

        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:self.max_candidates]

        if not candidates:
            return None  # No semantic matches → create new entity

        # Phase 5: LLM final resolution
        prompt = f"""Are these the same entity? Answer with the matching entity name or "NO_MATCH".

New entity: "{new_entity.name}" ({new_entity.entity_type}, {new_entity.source})
Candidates:
{chr(10).join(f'  - "{c.name}" ({c.entity_type}, {c.source})' for c, _ in candidates)}
"""
        result = await self.llm.extract(prompt, NodeDuplicate)
        if result.duplicate_of and result.duplicate_of != "NO_MATCH":
            for existing, _ in candidates:
                if existing.name == result.duplicate_of:
                    return existing.canonical_id

        return None  # LLM says no match → create new entity

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.
    Why not scipy: Avoid heavy dependency for a single function.
    numpy is already required for other vector operations."""
    a, b = np.array(a), np.array(b)
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0
```

#### Step 7: Edge Extraction & Supersession (Pipeline Steps 6-7)

```python
# contextd/pipeline/extract_edges.py

EDGE_EXTRACTION_PROMPT = Template("""Extract relationships between the following entities from the content below.

## Known Entities
{% for entity in entities %}
- {{ entity.name }} ({{ entity.entity_type }})
{% endfor %}

## Content
{{ episode.content }}

## Instructions
- For each relationship, provide: source_name, target_name, relationship_type, fact (natural language description), valid_at (ISO date if mentioned), invalid_at (if the relationship ended)
- Only create relationships between entities in the list above
- Do NOT create self-relationships (source = target)
- The "fact" field should be a complete sentence describing the relationship
""")

EDGE_DEDUP_PROMPT = Template("""Compare this new relationship against existing ones. Identify duplicates and contradictions.

## New Relationship
{{ new_edge.source_name }} → {{ new_edge.relationship_type }} → {{ new_edge.target_name }}
Fact: "{{ new_edge.fact }}"

## Existing Relationships (found via search)
{% for edge in existing_edges %}
[ID: {{ edge.id }}] {{ edge.source }} → {{ edge.relationship_type }} → {{ edge.target }}
  Fact: "{{ edge.fact }}"
  Valid: {{ edge.valid_at }} → {{ edge.invalid_at or "now" }}
{% endfor %}

## Instructions
- duplicate_facts: IDs of existing edges that say the same thing as the new one
- contradicted_facts: IDs of existing edges that the new one supersedes/contradicts
""")

async def supersede_edge(driver, edge_id: str, new_valid_at: datetime):
    """Mark an existing edge as superseded.

    Design choice — why we set BOTH expired_at and invalid_at:
    - expired_at = when WE learned this was no longer current (transaction time)
    - invalid_at = when it STOPPED being true in the real world (event time)
    These can differ: we might learn on April 3 that something stopped being true on April 1.
    Both old and new edges coexist in the graph — nothing is deleted.
    """
    await driver.command(f"""
        UPDATE RELATES_TO SET
            expired_at = sysdate(),
            invalid_at = '{new_valid_at.isoformat()}'
        WHERE id = '{edge_id}'
    """)
```

---

**How to verify Phase 2 is working:**
```python
# Ingest a test episode and check the graph
result = await run_pipeline(driver, llm, Episode(
    episode_type="text",
    source="test",
    content="Alice Chen is the VP of Engineering at Acme Corp. She reports to Bob Martinez.",
))
# result should show entities_created >= 2, edges_created >= 1

# Verify entities exist
entities = await driver.query("SELECT name, entity_type FROM Entity")
# Should include "Alice Chen" (person) and "Acme Corp" (company)
```

---

### Phase 3: Retrieval Engine (Weeks 8-11)

**Tech stack:** ArcadeDB full-text (Lucene BM25), ArcadeDB vector (LSMVector HNSW), ArcadeDB Cypher (BFS traversal), custom RRF/MMR rerankers
**Why all three in one engine:** ACID transactions across search methods. A single query can combine BM25 keyword match, vector similarity, and graph traversal without cross-database consistency issues.

#### Step 8: Three Search Methods

```python
# contextd/search/methods.py
from dataclasses import dataclass

@dataclass
class SearchResult:
    id: str
    score: float
    source_method: str  # "bm25" | "cosine" | "bfs"
    data: dict

async def bm25_search(driver, query: str, limit: int = 20) -> list[SearchResult]:
    """BM25 keyword search via ArcadeDB's built-in Lucene full-text index.

    Why BM25 (not just vector search): Vector search finds semantic meaning
    but misses exact terms. When a user queries "JIRA-1234" or "Alice Chen",
    BM25 finds the exact match instantly. Vector search would return
    semantically similar but wrong entities.

    ArcadeDB uses Lucene under the hood — same engine as Elasticsearch.
    """
    results = await driver.query(f"""
        SELECT *, search_score() as score
        FROM Entity
        WHERE SEARCH_INDEX('Entity.name', '{query}') = true
        ORDER BY score DESC
        LIMIT {limit}
    """)
    return [SearchResult(id=r["id"], score=r["score"], source_method="bm25", data=r)
            for r in results]

async def cosine_search(driver, query_embedding: list[float], limit: int = 20) -> list[SearchResult]:
    """HNSW nearest-neighbor search via ArcadeDB's LSMVector index.

    Why HNSW (not brute-force): O(log N) search vs O(N). At 10M entities,
    HNSW returns results in <10ms. Brute-force would take >1s.

    Why Product Quantization: Compresses 1536-dim float vectors by ~4x,
    reducing memory usage from ~23GB to ~6GB for 10M entities.
    PQ is configured at index creation time in ArcadeDB.
    """
    embedding_str = str(query_embedding)
    results = await driver.query(f"""
        SELECT *, vectorDistance('name_embedding', {embedding_str}, 'cosine') as score
        FROM Entity
        ORDER BY score ASC
        LIMIT {limit}
    """)
    # ArcadeDB returns distance (lower = more similar), convert to similarity
    return [SearchResult(id=r["id"], score=1.0 - r["score"], source_method="cosine", data=r)
            for r in results]

async def bfs_search(driver, seed_entity_ids: list[str], max_depth: int = 3,
                     limit: int = 50) -> list[SearchResult]:
    """Breadth-first graph traversal from seed entities.

    Why BFS (not DFS): BFS explores all neighbors at depth 1 before depth 2.
    This ensures we get the most directly-connected context first, which is
    almost always more relevant than deeply-nested connections.

    Why max_depth=3: In a typical enterprise graph, 3 hops covers:
    - Depth 1: Direct relationships (Alice works_at Acme)
    - Depth 2: Second-order (Acme's other employees, Alice's other companies)
    - Depth 3: Third-order (those employees' projects, deals)
    Beyond 3 hops, relevance drops off sharply.
    """
    seed_ids = ", ".join(f"'{id}'" for id in seed_entity_ids)
    results = await driver.cypher(f"""
        MATCH (seed:Entity)-[r*1..{max_depth}]-(connected:Entity)
        WHERE seed.id IN [{seed_ids}]
        RETURN DISTINCT connected, length(r) as depth
        ORDER BY depth ASC
        LIMIT {limit}
    """)
    return [SearchResult(
        id=r["connected"]["id"],
        score=1.0 / (1 + r["depth"]),  # Closer = higher score
        source_method="bfs",
        data=r["connected"],
    ) for r in results]
```

#### Step 9: Reranker Implementations

```python
# contextd/search/rerankers.py
from collections import defaultdict

def rrf_rerank(result_lists: list[list[SearchResult]], k: int = 60) -> list[SearchResult]:
    """Reciprocal Rank Fusion — merges ranked lists from multiple search methods.

    Formula: RRF_score(d) = Σ  1 / (k + rank_i(d))  for each method i
    where rank_i(d) is the rank of document d in method i's results.

    Why k=60: This is the standard constant from the original RRF paper
    (Cormack et al., 2009). It prevents high-ranked items from dominating
    too strongly. Higher k = more democratic fusion. 60 is well-tested.

    Why RRF over simple score averaging: Scores from BM25, cosine, and BFS
    are on different scales (BM25: 0-20, cosine: 0-1, BFS: 0-1).
    RRF uses rank positions instead, making it scale-independent.
    """
    scores = defaultdict(float)
    data = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            scores[result.id] += 1.0 / (k + rank + 1)
            data[result.id] = result.data

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [SearchResult(id=id, score=score, source_method="rrf", data=data[id])
            for id, score in merged]

def mmr_rerank(results: list[SearchResult], query_embedding: list[float],
               lambda_param: float = 0.7, limit: int = 20) -> list[SearchResult]:
    """Maximal Marginal Relevance — balances relevance vs. diversity.

    Formula: MMR = argmax [ λ × sim(d, q) - (1-λ) × max(sim(d, d_selected)) ]

    Why MMR: RRF can return 10 highly-similar entities about the same topic.
    MMR ensures diversity — if entity A is about "Acme's Q2 budget", the
    next result won't be another budget entity but something complementary
    like "Acme's team changes" or "recent support tickets".

    lambda_param: 0.7 = 70% relevance, 30% diversity (good default).
    Lower lambda = more diversity. Higher = more relevance.
    """
    import numpy as np

    selected = []
    remaining = list(results)

    while remaining and len(selected) < limit:
        best_score = -float('inf')
        best_idx = 0

        for i, candidate in enumerate(remaining):
            # Relevance to query
            relevance = candidate.score

            # Max similarity to already-selected items (diversity penalty)
            if selected:
                max_sim = max(
                    cosine_similarity(
                        candidate.data.get("name_embedding", []),
                        s.data.get("name_embedding", []),
                    )
                    for s in selected
                ) if candidate.data.get("name_embedding") else 0
            else:
                max_sim = 0

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected

def node_distance_rerank(results: list[SearchResult], seed_ids: list[str]) -> list[SearchResult]:
    """Prefer results closer in graph hops to seed entities.

    Why: For queries like "who works with Alice?", 1-hop neighbors (Alice's
    direct coworkers) are far more relevant than 3-hop connections.
    BFS already returns depth, so we just sort by it.
    """
    return sorted(results, key=lambda r: r.data.get("depth", 99))

def episode_mentions_rerank(results: list[SearchResult]) -> list[SearchResult]:
    """Prefer entities mentioned in more/recent episodes.

    Why: An entity mentioned in 50 episodes is likely more important than one
    mentioned in 2. And recent mentions are more relevant than old ones.
    This is especially useful for recency-focused queries ("what's new?").
    """
    return sorted(results, key=lambda r: len(r.data.get("episodes", [])), reverse=True)
```

#### Step 10: Context Assembly with Token Budgeting

```python
# contextd/assembly/context.py
import tiktoken

# Why tiktoken: OpenAI's fast BPE tokenizer. We need accurate token counts
# to stay within the agent's context window budget.
ENCODER = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))

async def assemble_context(
    driver, llm, query: str, max_tokens: int = 2000,
    search_recipe: str = "COMBINED_HYBRID_SEARCH_RRF",
    include_lineage: bool = False,
) -> dict:
    """The 7-step context assembly algorithm.

    Design rationale — why priority-based token budgeting:
    Not all context is equally valuable. Primary entities are critical (always
    included). Relationships provide structure. Facts provide detail. Sagas
    provide narrative. Decisions provide audit trail. We fill the budget in
    this priority order, stopping when we run out of tokens.

    This is fundamentally different from chunk-based RAG, which treats all
    chunks as equal-priority. Our approach guarantees the most important
    context is always present, even in tight budgets.
    """

    # Step 1: Parse intent — extract entity references and temporal constraints
    query_embedding = (await llm.embed([query]))[0]

    # Step 2: Seed entity selection — BM25 + cosine find primary entities
    bm25_seeds = await bm25_search(driver, query, limit=5)
    cosine_seeds = await cosine_search(driver, query_embedding, limit=5)
    seed_ids = list({r.id for r in bm25_seeds + cosine_seeds}[:5])

    # Step 3: Hybrid parallel search — all three methods simultaneously
    import asyncio
    bm25_results, cosine_results, bfs_results = await asyncio.gather(
        bm25_search(driver, query, limit=20),
        cosine_search(driver, query_embedding, limit=20),
        bfs_search(driver, seed_ids, max_depth=3, limit=50),
    )

    # Step 4: Rerank & merge
    merged = rrf_rerank([bm25_results, cosine_results, bfs_results])

    # Step 5: Apply feedback weights
    for result in merged:
        feedback_weight = result.data.get("feedback_weight", 0.5)
        result.score *= feedback_weight  # final_score = reranker × feedback

    merged.sort(key=lambda r: r.score, reverse=True)

    # Step 6: Budget-aware temporal pruning
    budget_remaining = max_tokens
    context = {
        "primary_entities": [],
        "relationships": [],
        "relevant_facts": [],
        "temporal_context": {"current_state": {}, "recent_changes": []},
        "decision_history": [],
        "saga_summary": "",
        "communities": [],
        "sources": set(),
    }

    # Priority 1: Primary entities (always included)
    for result in merged[:10]:
        entity_json = serialize_entity(result.data)
        tokens = count_tokens(str(entity_json))
        if tokens <= budget_remaining:
            context["primary_entities"].append(entity_json)
            context["sources"].add(result.data.get("source", ""))
            budget_remaining -= tokens

    # Priority 2: Relationships between primary entities
    entity_ids = [e["id"] for e in context["primary_entities"]]
    if entity_ids and budget_remaining > 100:
        relationships = await fetch_relationships(driver, entity_ids)
        for rel in relationships:
            # Temporal filter: only current relationships (invalid_at IS NULL)
            if rel.get("invalid_at"):
                continue
            rel_json = serialize_relationship(rel)
            tokens = count_tokens(str(rel_json))
            if tokens <= budget_remaining:
                context["relationships"].append(rel_json)
                budget_remaining -= tokens

    # Priority 3: Facts (current state, temporally filtered)
    if budget_remaining > 100:
        facts = await fetch_current_facts(driver, entity_ids)
        for fact in facts:
            fact_json = serialize_fact(fact)
            tokens = count_tokens(str(fact_json))
            if tokens <= budget_remaining:
                context["relevant_facts"].append(fact_json)
                budget_remaining -= tokens

    # Priority 4: Saga summary (if available)
    if budget_remaining > 200:
        saga_summaries = await driver.query(f"""
            SELECT s.name, s.summary FROM Saga s
            JOIN HAS_EPISODE he ON s = he.out
            JOIN Episode ep ON he.in = ep
            WHERE ep.id IN (
                SELECT source_episode_id FROM Fact
                WHERE subject_entity_id IN [{",".join(f"'{i}'" for i in entity_ids)}]
            )
            LIMIT 3
        """)
        for saga in saga_summaries:
            summary_text = f"{saga['name']}: {saga.get('summary', '')}"
            tokens = count_tokens(summary_text)
            if tokens <= budget_remaining:
                context["saga_summary"] += summary_text + "\n"
                budget_remaining -= tokens

    # Priority 5: Decision lineage (if requested and budget allows)
    if include_lineage and budget_remaining > 150:
        decisions = await driver.query(f"""
            SELECT FROM Decision
            WHERE affected_entities CONTAINSANY [{",".join(f"'{i}'" for i in entity_ids)}]
            AND expired_at IS NULL
            ORDER BY decided_at DESC
            LIMIT 5
        """)
        for decision in decisions:
            dec_json = {
                "type": decision.get("decision_type"),
                "subject": decision.get("subject"),
                "outcome": decision.get("outcome"),
                "decided_at": str(decision.get("decided_at", "")),
                "exception": decision.get("exception", False),
            }
            tokens = count_tokens(str(dec_json))
            if tokens <= budget_remaining:
                context["decision_history"].append(dec_json)
                budget_remaining -= tokens

    context["sources"] = list(context["sources"])

    return {
        "query": query,
        "context": context,
        "metadata": {
            "tokens_used": max_tokens - budget_remaining,
            "tokens_saved_vs_chunk_rag": (max_tokens - budget_remaining) * 3,
            "entities_traversed": len(merged),
            "avg_feedback_weight": sum(r.score for r in merged[:10]) / max(len(merged[:10]), 1),
            "search_recipe": search_recipe,
        },
    }

# --- Helper functions used by assemble_context ---

def serialize_entity(data: dict) -> dict:
    """Convert raw ArcadeDB entity record to context-window-friendly JSON."""
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("entity_type"),
        "summary": data.get("summary", ""),
        "source": data.get("source"),
        "feedback_weight": data.get("feedback_weight", 0.5),
    }

def serialize_relationship(data: dict) -> dict:
    return {
        "source": data.get("source_name", ""),
        "type": data.get("relationship_type"),
        "target": data.get("target_name", ""),
        "fact": data.get("fact", ""),
        "valid_at": str(data.get("valid_at", "")),
    }

def serialize_fact(data: dict) -> dict:
    return {
        "subject": data.get("subject_entity_id"),
        "predicate": data.get("predicate"),
        "object": data.get("object"),
        "valid_at": str(data.get("valid_at", "")),
        "confidence": data.get("confidence", 1.0),
    }

async def fetch_relationships(driver, entity_ids: list[str]) -> list[dict]:
    """Fetch current (non-expired) relationships between a set of entities."""
    ids = ", ".join(f"'{i}'" for i in entity_ids)
    return await driver.query(f"""
        SELECT expand(bothE('RELATES_TO')) FROM Entity
        WHERE id IN [{ids}]
        AND invalid_at IS NULL AND expired_at IS NULL
    """)

async def fetch_current_facts(driver, entity_ids: list[str]) -> list[dict]:
    """Fetch current (non-expired, non-invalidated) facts for a set of entities."""
    ids = ", ".join(f"'{i}'" for i in entity_ids)
    return await driver.query(f"""
        SELECT FROM Fact
        WHERE subject_entity_id IN [{ids}]
        AND invalid_at IS NULL AND expired_at IS NULL
        ORDER BY valid_at DESC
        LIMIT 50
    """)
```

---

**How to verify Phase 3 is working:**
```python
# After ingesting a few episodes, run a context assembly query
context = await assemble_context(driver, llm, "Tell me about Acme Corp", max_tokens=1000)
# context["metadata"]["tokens_used"] should be > 0
# context["context"]["primary_entities"] should contain Acme Corp
# context["context"]["relationships"] should contain works_at edges
```

---

### Phase 4: Feedback & Learning (Weeks 12-13)

**Tech stack:** Custom EMA engine, ArcadeDB UPDATE queries
**Why EMA over simple averaging:** EMA adapts to changing relevance patterns. If an entity was useful last month but isn't anymore, EMA gradually reduces its weight. Simple averaging would keep it artificially high forever. The α=0.1 learning rate means recent feedback matters more but can't cause wild swings.

```python
# contextd/feedback/engine.py
from datetime import datetime

class FeedbackEngine:
    """Streaming EMA feedback engine.

    Design choices:
    - α=0.1: Small enough to be stable (no single rating swings the weight
      from 0.5 to 1.0), large enough to adapt within ~30 interactions.
    - Cold start at 0.5: Neutral. The system works perfectly without feedback.
      Adding feedback only improves results — it can never make them worse.
    - Idempotent: The memify_metadata flag prevents double-processing.
    """

    def __init__(self, driver, alpha: float = 0.1):
        self.driver = driver
        self.alpha = alpha

    async def process_feedback(
        self, session_id: str, query_id: str, score: int,
        used_entities: list[str], used_edges: list[str],
    ) -> dict:
        """Process a feedback submission.

        Score normalization: 1-5 → 0.0-1.0 via (score - 1) / 4
        EMA update: new_weight = old_weight + α × (normalized - old_weight)
        """
        # Idempotency check — skip if already processed
        existing = await self.driver.query(f"""
            SELECT FROM FeedbackLog
            WHERE session_id = '{session_id}' AND query_id = '{query_id}'
        """)
        if existing:
            return {"status": "already_processed"}

        normalized = (score - 1) / 4.0  # 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0

        updated = {"entities": 0, "edges": 0}

        # Update entity weights
        for entity_id in used_entities:
            await self.driver.command(f"""
                UPDATE Entity SET feedback_weight =
                    ROUND(
                        MAX(0.0, MIN(1.0,
                            feedback_weight + {self.alpha} * ({normalized} - feedback_weight)
                        )),
                    4)
                WHERE id = '{entity_id}'
            """)
            updated["entities"] += 1

        # Update edge weights
        for edge_id in used_edges:
            await self.driver.command(f"""
                UPDATE RELATES_TO SET feedback_weight =
                    ROUND(
                        MAX(0.0, MIN(1.0,
                            feedback_weight + {self.alpha} * ({normalized} - feedback_weight)
                        )),
                    4)
                WHERE id = '{edge_id}'
            """)
            updated["edges"] += 1

        # Log feedback for audit + idempotency
        await self.driver.command(f"""
            INSERT INTO FeedbackLog SET
                session_id = '{session_id}',
                query_id = '{query_id}',
                score = {score},
                normalized = {normalized},
                entity_ids = {used_entities},
                edge_ids = {used_edges},
                processed_at = sysdate()
        """)

        return {"status": "processed", "updated": updated}
```

---

### Phase 5: Ontology Engine (Weeks 14-15)

**Tech stack:** Jinja2 (prompt templates), numpy (embedding similarity), Pydantic (schema validation)
**Why Jinja2 for prompt injection:** The ontology subset changes per chunk. Jinja2 templates cleanly separate the prompt structure from the dynamic ontology constraints. This is the TrustGraph "OntoRAG" pattern — the ontology isn't passive validation, it's active participation in extraction.

```python
# contextd/ontology/engine.py
from pydantic import BaseModel
import numpy as np

class OntologyEngine:
    """TrustGraph-inspired ontology engine with semantic routing.

    Design choice — why semantic routing (not full ontology injection):
    A CRM ontology might have 50 classes and 200 properties. Injecting all
    of them into every LLM prompt wastes tokens and confuses the model.
    Instead, we embed ontology elements and vector-match them against each
    chunk. Only the ~10 most relevant constraints are injected.

    This means an email about "budget approvals" gets Person, Organization,
    Budget, Approval constraints — not Vehicle, Product, Campaign.
    """

    def __init__(self, llm, ontology_schema: dict,
                 threshold: float = 0.3, top_k: int = 10):
        self.llm = llm
        self.schema = ontology_schema
        self.threshold = threshold
        self.top_k = top_k
        self.element_embeddings = {}  # {element_name: embedding}

    async def initialize(self):
        """Step 1: Embed all ontology elements."""
        elements = []
        for class_name, class_def in self.schema.get("classes", {}).items():
            text = f"{class_name}: {class_def.get('comment', '')} {class_def.get('labels', {}).get('en', '')}"
            elements.append((f"class:{class_name}", text))
        for prop_name, prop_def in self.schema.get("object_properties", {}).items():
            domain = ", ".join(prop_def.get("domain", []))
            range_ = ", ".join(prop_def.get("range", []))
            text = f"{prop_name}: relationship from {domain} to {range_}"
            elements.append((f"prop:{prop_name}", text))

        texts = [text for _, text in elements]
        embeddings = await self.llm.embed(texts)
        for (name, _), embedding in zip(elements, embeddings):
            self.element_embeddings[name] = embedding

    async def select_subset(self, chunk_text: str) -> dict:
        """Step 2: For a text chunk, find the most relevant ontology elements.

        How it works:
        1. Embed the chunk text
        2. Cosine similarity against all ontology element embeddings
        3. Filter by threshold (0.3) and take top-k (10)
        4. Resolve dependencies (if we select "works_at", include its domain/range classes)
        """
        [chunk_embedding] = await self.llm.embed([chunk_text])

        scored = []
        for name, emb in self.element_embeddings.items():
            sim = float(np.dot(chunk_embedding, emb) /
                       (np.linalg.norm(chunk_embedding) * np.linalg.norm(emb)))
            if sim >= self.threshold:
                scored.append((name, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [name for name, _ in scored[:self.top_k]]

        # Dependency resolution: include parent classes and domain/range types
        classes = set()
        properties = set()
        for name in selected:
            if name.startswith("class:"):
                cls = name.split(":")[1]
                classes.add(cls)
                # Include parent classes
                for parent in self.schema["classes"].get(cls, {}).get("subclass_of", []):
                    classes.add(parent)
            elif name.startswith("prop:"):
                prop = name.split(":")[1]
                properties.add(prop)
                # Include domain/range classes
                prop_def = self.schema["object_properties"].get(prop, {})
                for d in prop_def.get("domain", []):
                    classes.add(d)
                for r in prop_def.get("range", []):
                    classes.add(r)

        return {"classes": list(classes), "properties": list(properties)}

    def validate_extraction(self, entities: list, edges: list) -> tuple[list, list]:
        """Step 4: Validate extracted entities and edges against ontology.

        Returns (valid_entities, valid_edges) with invalid items dropped.
        This catches LLM hallucinations like:
        - Entity type "Vehicle" when only Person/Organization defined
        - "Acme works_at Alice" (domain/range violation)
        - Two CEO relationships for one person (cardinality violation)
        """
        valid_entities = []
        valid_classes = set(self.schema.get("classes", {}).keys())
        disjoint_pairs = []
        for cls, defn in self.schema.get("classes", {}).items():
            for disjoint in defn.get("disjoint_with", []):
                disjoint_pairs.append((cls, disjoint))

        for entity in entities:
            # Class filtering
            if valid_classes and entity.entity_type not in valid_classes:
                continue  # Drop: undefined type
            valid_entities.append(entity)

        valid_edges = []
        for edge in edges:
            prop_def = self.schema.get("object_properties", {}).get(edge.relationship_type)
            if not prop_def:
                valid_edges.append(edge)  # Unknown type: allow (ontology is optional)
                continue

            # Domain/range enforcement
            source_type = next((e.entity_type for e in valid_entities
                               if e.name == edge.source_name), None)
            target_type = next((e.entity_type for e in valid_entities
                               if e.name == edge.target_name), None)
            if source_type and prop_def.get("domain") and source_type not in prop_def["domain"]:
                continue  # Drop: domain violation
            if target_type and prop_def.get("range") and target_type not in prop_def["range"]:
                continue  # Drop: range violation

            # Cardinality check (functional = max 1)
            if prop_def.get("functional"):
                existing = [e for e in valid_edges
                           if e.source_name == edge.source_name
                           and e.relationship_type == edge.relationship_type]
                if existing:
                    continue  # Drop: cardinality violation

            valid_edges.append(edge)

        return valid_entities, valid_edges
```

---

### Phase 6: Context Cores (Weeks 16-17)

**Tech stack:** msgpack (serialization), hashlib (SHA-256 content addressing)
**Why msgpack over JSON:** 30-50% smaller, 2-10x faster serialization. For a graph with 10M entities, the difference is GBs of storage and minutes of serialization time. Content-addressed hashing (SHA-256 of the packed bytes) ensures immutability — any change produces a different hash.

```python
# contextd/cores/engine.py
import msgpack
import hashlib
from datetime import datetime

class ContextCoreEngine:
    """Build, test, promote, and rollback versioned graph snapshots.

    Design choice — why content-addressed (not incremental):
    Each core is a complete, self-contained snapshot. This means:
    1. Any core can be loaded independently (no dependency chain)
    2. Diffing is straightforward (compare two complete snapshots)
    3. Rollback is instant (just swap the pointer, no undo operations)
    Trade-off: Larger storage per version. Mitigated by msgpack compression.
    """

    def __init__(self, driver):
        self.driver = driver

    async def build(self, name: str, graph: str = "production") -> dict:
        """Snapshot entire graph state into a Context Core."""
        # Export all vertices and edges
        entities = await self.driver.query("SELECT FROM Entity")
        episodes = await self.driver.query("SELECT FROM Episode")
        facts = await self.driver.query("SELECT FROM Fact")
        relationships = await self.driver.query("SELECT FROM RELATES_TO")
        communities = await self.driver.query("SELECT FROM Community")
        decisions = await self.driver.query("SELECT FROM Decision")

        core_data = {
            "name": name,
            "graph": graph,
            "built_at": datetime.utcnow().isoformat(),
            "data": {
                "entities": entities,
                "episodes": [{"id": e["id"], "source": e["source"]} for e in episodes],
                "facts": facts,
                "relationships": relationships,
                "communities": communities,
                "decisions": decisions,
            },
            "feedback_weights": {
                e["id"]: e.get("feedback_weight", 0.5) for e in entities
            },
        }

        # Serialize with msgpack
        packed = msgpack.packb(core_data, use_bin_type=True)

        # Content-addressed hash
        sha256 = hashlib.sha256(packed).hexdigest()
        core_data["metadata"] = {
            "sha256": sha256,
            "size_bytes": len(packed),
            "entity_count": len(entities),
            "fact_count": len(facts),
        }

        # Store core reference
        await self.driver.command(f"""
            INSERT INTO ContextCore SET
                name = '{name}',
                version = '{sha256[:12]}',
                sha256 = '{sha256}',
                built_at = sysdate(),
                status = 'built',
                entity_count = {len(entities)},
                fact_count = {len(facts)}
        """)

        return core_data["metadata"]

    async def test(self, core_id: str, test_suite: list[dict]) -> dict:
        """Run a test suite against a core. Each test is a query + expected results."""
        results = {"passed": 0, "failed": 0, "errors": []}
        for test in test_suite:
            query = test["query"]
            expected = test.get("expected_entities", [])
            actual = await self.driver.query(f"""
                SELECT name FROM Entity
                WHERE name IN {expected}
                AND expired_at IS NULL
            """)
            actual_names = {r["name"] for r in actual}
            if set(expected).issubset(actual_names):
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "query": query,
                    "missing": list(set(expected) - actual_names),
                })
        return results
```

---

### Phase 7: API & Connectors (Weeks 18-21)

**Tech stack:** FastAPI (REST), google-api-python-client (Gmail), httpx (Salesforce/GitHub/Slack APIs)

```python
# contextd/api/server.py
import os
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from contextd.db.driver import ArcadeDBDriver
from contextd.llm.client import LLMClient
from contextd.assembly.context import assemble_context
from contextd.feedback.engine import FeedbackEngine

app = FastAPI(title="ContextD API", version="1.0.0")

# Why FastAPI: Async-native (matches our async driver + LLM clients),
# auto-generated OpenAPI docs, Pydantic request/response validation,
# dependency injection for driver/auth.

# --- Request Models ---
class ContextRequest(BaseModel):
    query: str
    max_tokens: int = Field(default=2000, ge=100, le=16000)
    search_recipe: str = "COMBINED_HYBRID_SEARCH_RRF"
    include_lineage: bool = False

class IngestRequest(BaseModel):
    name: str
    content: str
    source: str
    episode_type: str = "text"
    metadata: dict = {}
    reference_time: str | None = None       # ISO datetime
    saga: str | None = None                 # Creates or appends to saga
    saga_previous_episode_uuid: str | None = None

    def to_episode(self):
        from contextd.models import Episode
        from datetime import datetime
        return Episode(
            episode_type=self.episode_type,
            source=self.source,
            content=self.content,
            metadata=self.metadata,
            valid_at=datetime.fromisoformat(self.reference_time) if self.reference_time else None,
        )

class FeedbackRequest(BaseModel):
    session_id: str
    query_id: str
    score: int = Field(ge=1, le=5)
    used_entities: list[str] = []
    used_edges: list[str] = []

# --- Dependency Injection ---
_driver: ArcadeDBDriver | None = None
_llm: LLMClient | None = None

async def get_driver() -> ArcadeDBDriver:
    """Singleton ArcadeDB driver. Created once, reused across requests.
    Why singleton: Connection pooling via httpx — one pool handles all concurrency."""
    global _driver
    if _driver is None:
        _driver = ArcadeDBDriver(
            url=os.getenv("ARCADEDB_URL", "http://localhost:2480"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_PASSWORD", "contextd_dev"),
            database=os.getenv("ARCADEDB_DATABASE", "contextd"),
        )
    return _driver

def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient(model=os.getenv("OPENAI_MODEL", "gpt-4o"))
    return _llm

# --- Endpoints ---
@app.post("/context")
async def get_context(request: ContextRequest, driver=Depends(get_driver)):
    """Assemble context for an AI agent. This is the primary endpoint."""
    return await assemble_context(
        driver=driver,
        llm=get_llm(),
        query=request.query,
        max_tokens=request.max_tokens,
        search_recipe=request.search_recipe,
        include_lineage=request.include_lineage,
    )

@app.post("/ingest/episode")
async def ingest_episode(request: IngestRequest, driver=Depends(get_driver)):
    """Ingest a raw episode through the 10-step pipeline."""
    from contextd.pipeline.runner import run_pipeline
    return await run_pipeline(driver, get_llm(), request.to_episode())

@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest, driver=Depends(get_driver)):
    """Submit feedback to update graph weights."""
    engine = FeedbackEngine(driver, alpha=0.1)
    return await engine.process_feedback(
        session_id=request.session_id,
        query_id=request.query_id,
        score=request.score,
        used_entities=request.used_entities,
        used_edges=request.used_edges,
    )

# Start: uvicorn contextd.api.server:app --reload
```

---

### Phase 8: Observability & RBAC (Weeks 22-24)

**Tech stack:** opentelemetry-sdk (tracing), prometheus-client (metrics), hashlib (API key hashing)

```python
# contextd/observability/tracing.py
from contextlib import contextmanager

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    tracer = trace.get_tracer("contextd")
except ImportError:
    tracer = None

@contextmanager
def span(name: str, attributes: dict = None):
    """Create an OTEL span, or a no-op NullSpan if OTEL isn't installed.

    Why NullSpan fallback: Observability is optional. The system must work
    identically with or without OTEL. If OTEL isn't installed, we return
    a no-op context manager that does nothing — zero overhead, zero errors.
    """
    if tracer:
        with tracer.start_as_current_span(name) as s:
            if attributes:
                for k, v in attributes.items():
                    s.set_attribute(k, v)
            yield s
    else:
        yield None  # NullSpan — no-op

# Usage in pipeline:
# with span("extract_nodes", {"contextd.pipeline.episode_id": episode.id}):
#     entities = await extract_entities(llm, episode, previous)
```

```python
# contextd/auth/rbac.py
import hashlib
from fastapi import Request, HTTPException

# Why SHA-256 for API keys: Keys are never stored in plaintext.
# When a user sends their key, we hash it and compare against stored hashes.
# If the database is compromised, attackers get hashes, not usable keys.

ROLE_PERMISSIONS = {
    "owner":     {"read", "write", "delete", "manage_users", "manage_connectors", "manage_cores", "query", "cypher", "feedback"},
    "admin":     {"read", "write", "manage_users", "manage_connectors", "manage_cores", "query", "cypher", "feedback"},
    "editor":    {"read", "write", "query", "cypher", "feedback"},
    "viewer":    {"read", "query"},
    "agent":     {"read", "query", "feedback"},
    "connector": {"write_own_source"},
}

async def check_permission(request: Request, required: str, driver=None):
    """RBAC middleware — checks API key, role, and scoping."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(401, "Missing API key")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_record = await driver.query(f"SELECT FROM APIKey WHERE key_hash = '{key_hash}'")
    if not key_record:
        raise HTTPException(401, "Invalid API key")

    role = key_record[0]["role"]
    permissions = ROLE_PERMISSIONS.get(role, set())
    if required not in permissions:
        raise HTTPException(403, f"Role '{role}' lacks permission '{required}'")

    # Apply scoping for viewer/agent roles
    scopes = key_record[0].get("scopes", {})
    return {"role": role, "scopes": scopes}
```

---

## 30. Repository Structure

The current repository contains the documentation website:

```
Implementing_contextD/
├── README.md                # This file
└── website/
    ├── index.html           # Complete product documentation (2,195 lines)
    ├── css/
    │   └── styles.css       # Design system (Inter + JetBrains Mono, orange accent #E8500A, responsive)
    └── js/
        └── app.js           # Interactivity (scroll animations, sidebar nav, accordions, tabs, counters)
```

### Target Implementation Structure

```
contextd/
├── contextd/
│   ├── __init__.py              # ContextD class (embedded + server modes)
│   ├── models.py                # Pydantic models (Entity, Episode, Fact, Saga, etc.)
│   ├── db/
│   │   ├── driver.py            # ArcadeDB async HTTP driver (httpx)
│   │   └── schema.py            # Schema definitions + initialization
│   ├── pipeline/
│   │   ├── runner.py            # 10-step pipeline orchestrator
│   │   ├── extract_nodes.py     # Step 3: LLM entity extraction
│   │   ├── extract_edges.py     # Step 6: LLM relationship extraction
│   │   ├── entity_resolution.py # Steps 4-5: 5-phase dedup (MinHash + cosine + LLM)
│   │   ├── edge_resolution.py   # Step 7: Edge dedup + supersession
│   │   └── community.py         # Step 10: Label Propagation + LLM summarization
│   ├── search/
│   │   ├── methods.py           # BM25, cosine, BFS search implementations
│   │   ├── rerankers.py         # RRF, MMR, Cross-Encoder, Node Distance, Episode Mentions
│   │   └── recipes.py           # Pre-built search strategy configs
│   ├── assembly/
│   │   └── context.py           # 7-step context assembly + token budgeting
│   ├── feedback/
│   │   └── engine.py            # EMA feedback engine (α=0.1)
│   ├── ontology/
│   │   ├── engine.py            # Semantic routing + validation
│   │   └── prebuilt/            # CRM, Support, Engineering, Marketing ontologies
│   ├── connectors/
│   │   ├── base.py              # Connector base class (auth, pagination, incremental sync)
│   │   ├── gmail.py             # Gmail connector (OAuth2 + deep extraction)
│   │   ├── salesforce.py        # Salesforce connector
│   │   ├── slack.py             # Slack connector
│   │   ├── github.py            # GitHub connector
│   │   └── airbyte.py           # Airbyte quality layer wrapper
│   ├── cores/
│   │   └── engine.py            # Context Cores (build, test, promote, rollback)
│   ├── auth/
│   │   └── rbac.py              # 6 roles, 3 scoping dimensions, API key management
│   ├── observability/
│   │   ├── tracing.py           # OpenTelemetry spans + NullSpan fallback
│   │   └── metrics.py           # Prometheus metric exposition
│   ├── api/
│   │   └── server.py            # FastAPI REST endpoints
│   └── mcp/
│       └── server.py            # MCP server (stdio/SSE/HTTP transports)
├── docker-compose.yml           # ArcadeDB + dev environment
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
└── tests/
    ├── test_pipeline.py         # BDD specs for ingestion pipeline
    ├── test_resolution.py       # Entity resolution unit tests
    ├── test_search.py           # Search + reranker tests
    └── test_feedback.py         # EMA feedback tests
```

**Live site:** [contextd-tech.vercel.app](https://contextd-tech.vercel.app/)

---

## 31. Key Numbers Reference

| Metric | Value |
|--------|-------|
| Data models in one engine | 6 (graph, vector, full-text, document, KV, time-series) |
| Graph algorithms (SIMD) | 70+ |
| Token reduction vs. chunk RAG | 80% (~847 vs ~3,400 tokens) |
| Graph traversal latency | <10ms |
| Ingestion pipeline steps | 10 |
| Entity resolution phases | 5 |
| Search methods (parallel) | 3 (BM25, cosine, BFS) |
| Reranking strategies | 5 (RRF, MMR, Cross-Encoder, Node Distance, Episode Mentions) |
| Context assembly steps | 7 |
| Data connectors | 6 P0 custom + 600+ via Airbyte |
| Wire protocols | 6 (Bolt, PG, Mongo, Redis, gRPC, HTTP) |
| RBAC roles | 6 (Owner, Admin, Editor, Viewer, Agent, Connector) |
| Scoping dimensions | 3 (source, entity type, tags) |
| Feedback learning rate (α) | 0.1 |
| Feedback cold start weight | 0.5 (neutral) |
| MinHash permutations | 32 |
| MinHash LSH band size | 4 |
| Cosine similarity threshold | 0.6 |
| Jaccard similarity threshold | 0.9 |
| Entropy gate threshold | 1.5 bits |
| Ontology selection threshold | 0.3 (cosine), top-k 10 |
| OAuth2 providers | 30+ |
| Audit log retention | 1 year (free), 7 years (enterprise) |

---

*Built by Nikhil Reddy & Bhavik. Inspired by Graphiti, TrustGraph, and Cognee. Powered by ArcadeDB (Apache 2.0).*
