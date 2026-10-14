# ContextD — Master Source Document

> **Purpose of this file**
> A single, structured dump of every authoritative source on ContextD: the public site (contextd-tech.vercel.app), the long-form technical spec (`contextD.md`), the worked query examples (`example-queries-just intuition-based.md`), and the engineering benchmark report (`BENCHMARK_REPORT.md`). This file is the source-of-truth aggregate; the topic-wise files (`01` through `14`) refine and structure this material per concern.
>
> **Reading order:** Section 0 (one-page synthesis) → Section 1 (vision and category) → Section 10 (benchmarks, the honest engineering ground-truth) → everything else.
>
> **Authoritative claims:** Numbers prefixed with **[BENCH]** come from the benchmark report (measured on real hardware). Numbers prefixed with **[TARGET]** are engineering targets / aspirational claims from the website and long-form spec — they are real product goals, but not yet measured. Always cite the right tag.

---

## 0. One-Page Synthesis

**ContextD is a database, not a framework.** It ingests enterprise data (Gmail, Salesforce, Slack, GitHub, Zendesk, HubSpot, Notion, Jira, Postgres, Snowflake, ...), constructs a relationship-aware, temporally-grounded knowledge graph, learns what matters from feedback, and serves AI agents structured context — replacing chunk-based RAG.

| | |
|---|---|
| **Category** | Context Graph Database (a new category — "MongoDB owns documents, Pinecone owns vectors, Neo4j owns graphs, **ContextD owns context**") |
| **Today's stack** | PostgreSQL (metadata) + Neo4j (graph + Lucene full-text) + Milvus (vectors) + Redis (cache/sessions) + Temporal (durable workers). FastAPI backend, React/ShadCN frontend, 30+ enterprise connectors, OAuth2 service. |
| **Tomorrow's stack** | A single unified engine — "ContextD" — built on top of an Apache 2.0 multi-model substrate (ArcadeDB is the leading candidate). Graph + vector (HNSW/PQ) + full-text (BM25) + KV + document + time-series in one ACID engine. Adds the bitemporal schema, 10-step ingestion pipeline, 5-phase entity resolution, feedback EMA, ontology engine, context cores, and 7-step context assembly. |
| **The bet** | Collapsing 3-5 databases into one ACID engine purpose-built for context unlocks (a) bitemporal queries, (b) feedback-weighted self-improving retrieval, (c) versioned context snapshots ("Context Cores" — CI/CD for knowledge), (d) ~80% [TARGET] token reduction vs chunk-based RAG. |
| **Validation** | Internal benchmark on ArcadeDB v26.4.2 against a 475K-entity / 1.37M-edge graph with 1024-dim embeddings: hybrid (vector + FTS + graph) peaks at **[BENCH] 137 ops/sec** at 8-32 threads with 47ms p50 single-thread; vector search peaks at **[BENCH] 157 ops/sec** at 8 threads. The benchmark surfaced exact bottlenecks (HNSW lock contention, graph traversal page locks, PG-protocol 100ms sleep bug) and informs the architectural roadmap. |
| **Founders** | Nikhil Reddy & Bhavik (per website footer). |
| **Substrate** | ArcadeDB (Apache 2.0) — multi-model engine providing graph + vector + full-text + KV + document + time-series in one ACID transaction. |
| **Reference tools & prior art** | Consolidated in  (substrate dependencies, adjacent open-source projects, academic references). |

---

## 1. Vision and Category

### 1.1 Why ContextD exists

> AI agents work with the wrong context. Every current approach fails in a specific, predictable way.

| Approach | What It Does | What It Misses | Concrete failure |
|----------|-------------|----------------|------------------|
| Vector search (Pinecone, Weaviate) | Retrieves ~1,000 similar text chunks | No relationships, no time, no structure | Search "Mercury" returns the planet, the element, AND the car — equally ranked |
| Graph DBs (Neo4j, Neptune) | Stores entity relationships | No temporal awareness, no decision lineage, not AI-native; SSPL restricts embedding | Find that Alice works at Acme, but not "who worked there *last March*?" |
| RAG frameworks (LangChain, LlamaIndex) | Orchestrates retrieval + LLM | No persistent data layer, no learning, no context storage | Every query starts from scratch — system doesn't remember last query was useless |
| Multi-DB assembly (Neo4j + Pinecone + custom) | Cobbles graph + vector + temporal logic | 3+ databases, no cross-model ACID, consistency gaps, 3× infra cost | Write to Neo4j succeeds, write to Pinecone fails — graph and search index disagree |
| **ContextD** | Unified context graph with bitemporal state, hybrid retrieval, ontology-grounded extraction, feedback learning | — | One engine, ACID across all 6 data models, learns from use |

### 1.2 The core insight

AI agents don't need similar documents. They need **relationship-aware, temporally-grounded, ontology-constrained, feedback-weighted context assembly.** That's not a feature you bolt onto an existing database — it requires a purpose-built system.

### 1.3 The category

> MongoDB owns documents. Pinecone owns vectors. Neo4j owns graphs. **ContextD owns context.**

This is a new database category — the **Context Graph Database** — purpose-built for AI applications that need relationship-aware, temporally-grounded, feedback-weighted context at query time.

### 1.4 What ContextD IS / IS NOT

| ContextD IS | ContextD IS NOT |
|-------------|------------------|
| A **database** — stores entities, relationships, facts, decisions, temporal state | An AI agent — it serves context *to* agents |
| A **context construction engine** — 10-step pipeline turns raw data into structured knowledge | A workflow tool — it doesn't take actions |
| An **AI-native query system** — hybrid retrieval (BM25 + vectors + graph) | A vector database — vectors are 1 of 6 data models |
| A **temporal knowledge system** — bitemporal model | An analytics platform — it serves context windows, not dashboards |
| A **learning system** — feedback-weighted graph that gets smarter | A general-purpose DB — opinionated for context assembly |
| **Versionable** — Context Cores = CI/CD for knowledge | A RAG framework — it's the persistent data layer RAG frameworks lack |

---

## 2. The Six Building Blocks (Data Primitives)

Every piece of data carries bitemporal metadata, provenance stamps, and feedback weights.

### 2.1 Entity (Node) — "the nouns"

People, companies, projects, tickets, deals, documents.

```
Entity {
  id:                UUID [PK]
  canonical_id:      UUID        — resolved identity (after dedup)
  entity_type:       STRING      — person | company | project | ticket | deal | document
  name:              STRING
  labels:            [STRING]    — multi-label
  summary:           STRING      — regional summary of relationships
  name_embedding:    [FLOAT]     — stored in HNSW vector index
  source:            STRING      — origin system
  feedback_weight:   FLOAT [0.0-1.0], default 0.5
  valid_at / invalid_at:   TIMESTAMP — event time bounds
  created_at / expired_at: TIMESTAMP — transaction time bounds
  confidence:        FLOAT       — entity resolution confidence
  source_pipeline, source_task, extraction_method:  provenance
}
```

`canonical_id` is what makes "John Smith" (Salesforce), "john@acme.com" (Gmail), and "john.smith" (Slack) resolve to the same person.

### 2.2 Relationship (Edge) — "the verbs"

Typed, directed, temporally-tracked edges between entities ("Alice **works_at** Acme Corp").

```
Relationship {
  source_entity_id → target_entity_id: UUID
  relationship_type: STRING      — works_at | owns | assigned_to | approved | discussed | ...
  fact:              STRING      — natural language description
  fact_embedding:    [FLOAT]     — semantic search over relationships
  weight / feedback_weight: FLOAT
  episodes:          [UUID]      — every episode that mentioned this relationship
  valid_at, invalid_at, created_at, expired_at:  bitemporal
  reference_time:    TIMESTAMP   — from source episode
  source, extraction_method, source_pipeline, source_task:  provenance
}
```

The `fact` field carries a natural-language description that's searchable by both keywords (BM25) and meaning (cosine).

### 2.3 Fact (Atomic Statement) — "the claims"

A single, time-bounded, verifiable statement extracted from source data.

```
Fact {
  subject_entity_id: UUID
  predicate:         STRING      — has_budget | decided_to | committed_to | ...
  object:            STRING|UUID — value or link to entity
  valid_at, invalid_at, created_at, expired_at: bitemporal
  confidence, feedback_weight: quality signals
  source_episode_id: UUID
  extraction_method: llm_extraction | structured_import | manual | ontology_constrained
}
```

**Supersession (critical):** when a new fact contradicts an old one, the old fact is **never deleted**. Old fact gets `expired_at = now()` and `invalid_at = when_new_fact_became_true`. New fact is created alongside. This preserves complete history.

### 2.4 Episode (Source) — "the raw material"

The unprocessed source event. Everything else is *extracted from* episodes. Full provenance.

```
Episode {
  episode_type:  STRING      — message | json | text
  source:        STRING      — gmail | slack | github | salesforce | ...
  content:       TEXT
  metadata:      JSON        — headers, timestamps, sender/receiver
  entity_edges:  [UUID]      — entities/edges extracted from this episode
  valid_at:      TIMESTAMP   — when the event occurred
  created_at:    TIMESTAMP   — when ingested
}
```

### 2.5 Saga (Narrative) — "the storyline"

A storyline spanning multiple episodes — e.g., "Acme deal negotiation: 47 emails over 3 months."

```
Saga {
  name, summary (incrementally LLM-updated)
  first_episode_id, last_episode_id
  last_summarized_at
}

Saga ──HAS_EPISODE──▶ Episode ──NEXT_EPISODE──▶ Episode  (temporal linked list)
```

### 2.6 Community (Cluster) — "the neighborhood"

A group of closely connected entities, discovered automatically via graph algorithms (Louvain, Label Propagation).

```
Community {
  name
  name_embedding   — community-level search
  summary          — LLM-generated: "Cluster of 12 entities centered around..."
}
```

### 2.7 Decision — "first-class auditability"

Most systems treat decisions as invisible side effects. ContextD makes them searchable, traceable, auditable.

```
Decision {
  decision_type:     "approval" | "exception" | "selection" | "commitment"
  subject:           "20% discount for Acme Corp"
  outcome:           "approved"
  decided_by:        UUID → Person
  decided_at:        TIMESTAMP
  inputs:            [UUID] → episodes + facts that informed this decision
  policy:            UUID → policy entity that was applied
  exception:         BOOLEAN
  justification:     TEXT
  affected_entities: [UUID]
  superseded_by:     UUID — if later overridden
}
```

### 2.8 Schema relationships

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

Everything traces back to Episodes — full provenance.

---

## 3. The Bitemporal Time Model

Every entity, relationship, and fact tracks **two independent time dimensions**.

| Dimension | Fields | What it means | Analogy |
|-----------|--------|---------------|---------|
| **Event Time** | `valid_at` → `invalid_at` | When was this true *in the real world*? | "Alice worked at Acme from January to June" |
| **Transaction Time** | `created_at` → `expired_at` | When did **we** record/learn/supersede this? | "We wrote this in our notebook on March 5th" |

### 3.1 Why two clocks

Reality and our knowledge of reality change independently.

### 3.2 Supersession walkthrough

```
t=1 (Jan 15)  Email: "Acme's annual budget is $5M"
              → Fact created: {predicate: "budget", object: "$5M",
                               valid_at: 2026-01-01, invalid_at: NULL,
                               created_at: 2026-01-15, expired_at: NULL}

t=2 (Apr 3)   Email: "Acme increased their budget to $7M"
              → Pipeline detects contradiction via semantic search
              → LLM confirms: this supersedes the old fact
              → Old fact: expired_at = 2026-04-03, invalid_at = 2026-04-01
              → New fact: {object: "$7M", valid_at: 2026-04-01, invalid_at: NULL,
                           created_at: 2026-04-03, expired_at: NULL}

BOTH facts exist in the graph. Nothing was deleted.
```

### 3.3 Four temporal queries (Cypher)

**Current state** — what is true right now?

```cypher
MATCH (acme:Entity {name: "Acme"})-[:HAS_FACT]->(f:Fact {predicate: "budget"})
WHERE f.invalid_at IS NULL AND f.expired_at IS NULL
RETURN f.object  -- "$7M"
```

**Historical state** — what was true at time T?

```cypher
WHERE f.valid_at <= datetime("2026-02-01")
  AND (f.invalid_at IS NULL OR f.invalid_at > datetime("2026-02-01"))
-- "$5M"
```

**Knowledge state** — what did we know at time T?

```cypher
WHERE f.created_at <= datetime("2026-03-01")
  AND (f.expired_at IS NULL OR f.expired_at > datetime("2026-03-01"))
-- "$5M" (we hadn't learned about the increase yet on Mar 1)
```

**Audit state** — when did we learn X?

```cypher
WHERE f.object = "$7M"
RETURN f.created_at  -- "2026-04-03"
```

### 3.4 Why this matters for AI

Without bitemporal, an AI agent can't distinguish "Alice left Acme in March" from "we learned in June that Alice left in March." When making a decision based on what was known *at the time of a past decision*, the agent must query knowledge state, not current state. This is critical for compliance, audit, and decision lineage.

---

## 4. The 10-Step Ingestion Pipeline

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

### 4.1 Step-by-step

1. **Create Episode** — wrap raw data in `EpisodicNode`; store `content`, `metadata`, `valid_at`, `source`, `episode_type`.
2. **Retrieve Context** — fetch previous N episodes (default 10) in same group/saga. Gives LLM conversation history so "as I mentioned yesterday" resolves correctly.
3. **Extract Nodes** — send episode content + context window + optional ontology subset to LLM; receive Pydantic-validated `ExtractedEntities`. Ontology drops invalid types.
4. **Resolve Entities — Deterministic** — (a) normalize, (b) exact match, (c) Shannon entropy gate (skip if <1.5 bits or <6 chars), (d) 3-gram MinHash with 32 perms + LSH band size 4, (e) Jaccard ≥ 0.9 → merge.
5. **Resolve Entities — Semantic + LLM** — cosine similarity ≥ 0.6 on name embeddings retrieves up to 15 candidates per entity; LLM final yes/no on ambiguous cases. ~80% of resolutions handled before LLM is called.
6. **Extract Edges** — LLM extracts relationships with temporal annotations; self-edges dropped, ontology domain/range enforced.
7. **Resolve/Dedup Edges** — hybrid search (`EDGE_HYBRID_SEARCH_RRF`: BM25 + cosine on fact embeddings) finds duplicates and contradictions. LLM adjudicates: duplicates merge into existing (append episode UUID); contradictions supersede (set `invalid_at` and `expired_at`).
8. **Generate Embeddings** — batch-embed entity names + relationship facts via OpenAI; store in HNSW with Product Quantization compression.
9. **Save to Graph** — bulk write episodes, entities, relationships, episodic edges. Provenance on every element.
10. **Community Detection** — optional. Label Propagation or Louvain on updated graph region; LLM bottom-up hierarchical summarization; create/update `CommunityNode` vertices.

### 4.2 Saga tracking

```
A. Create or fetch Saga       — by name; or fetch existing
B. Link Episode to Saga       — HAS_EPISODE edge
C. Chain Temporally           — NEXT_EPISODE edge from previous → new
D. Update Summary             — LLM(existing_summary + new_episode) → updated_summary (streaming, never re-read)
```

### 4.3 BDD specs (representative)

```
GIVEN an episode with content "Alice works at Acme"
WHEN  extracted with CRM ontology
THEN  Person "Alice" + Organization "Acme" + works_at relationship are created.

GIVEN two entities "John Smith" and "john smith" with Jaccard ≥ 0.9
WHEN  resolved through deterministic pipeline
THEN  they merge into a single canonical entity.

GIVEN an ontology where works_at has domain Person and range Organization
WHEN  LLM extracts "Acme works_at Alice"
THEN  the relationship is DROPPED (domain/range violated).

GIVEN a saga with 5 episodes
WHEN  a 6th episode is added
THEN  NEXT_EPISODE links episode 5 → 6 and saga summary is incrementally updated.

GIVEN an entity extracted from an episode
WHEN  saved to the graph
THEN  source_pipeline, source_task, extraction_method are all populated.
```

---

## 5. Context Resolver — The Cross-Source Identity Stitching Module

> **Productized as a discrete architectural block in Layer 3** alongside Context Forge and Context Cores. Detailed in `07-context-resolver.md`.

Entity resolution at ContextD takes two paths:

- **Structured sources with stable unique IDs** (Snowflake `customer_id`, Salesforce `Id`, Stripe `cus_*`, GitHub `node_id`) — handled by Context Forge as a **deterministic join**. Same source-ID always resolves to the same `canonical_id`.
- **Heterogeneous / unstructured / no-shared-ID sources** — where Alice Chen appears as `alice.chen@acme.com` (Gmail), `slack_user_id=U023BECGF` (Slack), `requester_id=3478291` (Zendesk), `a-chen` (GitHub), `ldap:achen` (Confluence), and a free-text mention *"as Alice mentioned yesterday..."* — runs the Context Resolver six-stage probabilistic pipeline.

### 5.1 Module composition (5 components)

1. **Resolver Engine** — six-stage runtime processing every ingestion event + batch jobs
2. **Identity Graph** — persistent bitemporal artifact in the substrate (canonical entities ↔ source-record-IDs with confidence-weighted edges)
3. **Resolver Studio** — review surface (active-learning queue, conflict queue, identity-graph explorer)
4. **Resolver Profiles** — pre-tuned matching configurations per entity type (`person-crm`, `person-engineering`, `organization-account`, `deal-opportunity`, `device-asset`, `product-sku`)
5. **Resolver-to-Pipeline Bridge** — integration with the 10-step ingestion pipeline (deterministic vs probabilistic routing, Identity Graph atomic update)

### 5.2 The six-stage probabilistic pipeline (cost-cascading, advanced techniques only)

| Stage | Technique | Reference |
|-------|-----------|-----------|
| **A — Blocking** | HNSW vector ANN + DeepBlocker learned blocking + 3-gram MinHash/LSH; reduces O(N²) → O(N log N) | Malkov & Yashunin 2018; Thirumuruganathan VLDB 2021; Indyk & Motwani 1998 |
| **B — Probabilistic record linkage** | Fellegi-Sunter framework with EM-learned m-probabilities and u-probabilities; Platt-scaled / isotonic-calibrated thresholds | Fellegi & Sunter 1969; Winkler 1988 |
| **C — Neural pairwise matching** | DITTO-style cross-encoder transformer (RoBERTa / DeBERTa-v3 base, ~110M params); supervised contrastive + triplet loss; > 95% F1 on Magellan benchmark suite; ~5K pairs/sec on GPU | Li et al. VLDB 2020 |
| **D — Coreference resolution for free text** | GLiNER zero-shot + RoBERTa-NER for mentions; e2e-coref / MaverickCoref / SpanBERT-coref for within-doc; Cross-Document Coreference Resolution (CDCR) for across-document mention alignment | Lee et al. 2017; MaverickCoref 2024; Cattan et al. 2021; CDLM 2021 |
| **E — Identity Graph stitching** | Confidence-weighted edges on a bitemporal graph; **Probabilistic Soft Logic (PSL)** for transitive closure with confidence multiplication; conflict detection; soft-link mode for low-confidence stitches | Bach et al. JMLR 2017 |
| **F — Active learning + LLM adjudication** | Uncertainty sampling surfaces near-threshold matches to Resolver Studio; query-by-committee fine-tune loop; LLM few-shot / CoT for residual ~1-2% | Settles 2009; AnyMatch / MatchGPT 2024 |

What we explicitly avoid as primary signals: string-distance heuristics (Levenshtein, Jaro-Winkler), graph-only ER without coreference for unstructured text, one-shot LLM-only matching at scale.

### 5.3 The Identity Graph artifact

Every canonical entity carries an array of source-record-IDs with confidence scores, evidence traces, attribute-consensus reconciliation, and a complete audit trail. Every identifier link is bitemporal — `valid_at` / `invalid_at` for event time, `created_at` / `expired_at` for transaction time. When a customer's email changes after a re-org, the new identifier supersedes the old without losing the historical link. Queryable via Cypher, SQL, or MCP.

```
canonical_id (UUID)
├── identifiers[] = [ (source, source_id, confidence, evidence, valid_at, invalid_at), ... ]
├── attribute_consensus = { reconciled per-attribute view with provenance }
└── audit_trail = [ CREATE / STITCH / SUPERSEDE events with timestamps ]
```

### 5.4 Performance targets

| Operation | Target |
|-----------|--------|
| Block O(N²) → O(N log N) | < 10 ms per record at 100M-vector index |
| Pairwise match (Stage C) | ~ 5,000 pairs/sec on a single GPU |
| End-to-end resolution (Stages A-E) | ~ 50,000 entities/sec at steady state |
| Active-learning loop turnaround | < 24 h surface-to-fine-tuned-model |
| Identity Graph reconciliation | Bitemporal-consistent merges, no orphan records |

### 5.5 Why this is hard to replicate

A working cross-source resolution module requires **simultaneously**: (a) multi-source ingestion, (b) a vector index for blocking, (c) fine-tuneable neural matching with labeled per-domain training data, (d) coreference / NER stack for unstructured text, (e) probabilistic soft-logic engine for constraint propagation, (f) bitemporal storage for the resulting Identity Graph, and (g) an active-learning UI surface (Resolver Studio). Each is a multi-quarter engineering investment; the combination is the moat.

**For the full module reference** — Resolver Engine internals, Identity Graph schema, Resolver Studio queues, Resolver Profiles per entity type, customer onboarding flow, in-scope vs deferred scope, and common technical questions — see `07-context-resolver.md`.

---

## 6. The Ontology Engine

The ontology engine is **optional**. It constrains what the LLM can extract, improving consistency and reducing hallucinated entity types.

### 6.1 When to use it

| Situation | Recommendation |
|-----------|----------------|
| Prototyping or < 10K entities | Skip — LLM-only extraction works fine |
| Single data source (e.g., just Gmail) | Probably skip |
| Multiple sources with overlapping entity types | Use it (Salesforce "Account" vs Gmail "Company") |
| Regulated domain (finance, healthcare) | Use it (audit) |
| Consistent extraction across teams | Use it (shared schema contract) |

### 6.2 Schema (OWL-like JSON)

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
      "subclass_of": ["Agent"]
    }
  },
  "object_properties": {
    "works_at": {
      "domain": ["Person"], "range": ["Organization"],
      "functional": false
    },
    "ceo_of": {
      "domain": ["Person"], "range": ["Organization"],
      "functional": true   // max 1 — a person is CEO of one company
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

### 6.3 Four-step semantic routing

1. **Embed ontology** — every class/property → vector embedding (combining identifier + label + description).
2. **Select subset** — for each chunk, vector-match against ontology embeddings (threshold 0.3, top-k 10) + dependency resolution (parent classes, domain/range constraints).
3. **Inject into prompt** — relevant subset serialized into LLM extraction prompt via Jinja2.
4. **Validate output** — class filtering, domain/range, cardinality, disjoint classes.

### 6.4 Validation rules

| Rule | Enforces | Example |
|------|----------|---------|
| Class filtering | Only ontology-defined types | "Vehicle" dropped if only Person/Organization defined |
| Domain/range | Relationships connect valid types | "works_at" must go Person → Organization |
| Cardinality | Functional props max 1 value | `has_email` functional → only one per person |
| Disjoint classes | Entity can't span conflicts | Person ≠ Organization |

**Pre-built ontologies:** CRM, Support, Engineering, Marketing.

---

## 7. Retrieval — Hybrid Search Pipeline

### 7.1 Three search methods (parallel)

| Method | How | Good at | Misses |
|--------|-----|---------|--------|
| **BM25** | Lucene keyword search | Exact terms, names, IDs, jargon | Paraphrases, synonyms |
| **Cosine** | HNSW nearest-neighbor | Semantic meaning, paraphrases | Exact names, IDs |
| **BFS** | Breadth-first graph traversal | Structural relationships | Disconnected entities |

### 7.2 Five reranking strategies

| Reranker | Logic | When |
|----------|-------|------|
| **RRF** (default) | `Σ 1/(k + rank)` (k=60) — scale-independent rank fusion | General purpose |
| **MMR** | Balances relevance vs diversity (λ=0.7) | Want variety, not 10 similar |
| **Cross-Encoder** | Neural BGE/OpenAI/Gemini reranking | Max accuracy when latency OK |
| **Node Distance** | Closer in graph hops ranks higher | "Who works with Alice?" |
| **Episode Mentions** | More/recent episode mentions rank higher | "What's new with Acme?" |

3 methods × 5 rerankers = **15 strategies**. Composability via search recipes (`COMBINED_HYBRID_SEARCH_RRF`, `EDGE_HYBRID_SEARCH_RRF`, `NODE_HYBRID_SEARCH_RRF`, ...).

### 7.3 Query flow

```
NL Query
   │
   ▼
[1. Parse Intent] → entity refs, relationship hints, temporal scope, filters
   │
   ├──[BM25 Search]──┐
   ├──[Cosine Search]┤   (parallel)
   └──[BFS Traverse]─┘
                     ▼
              [2. Reranker]  (RRF / MMR / CrossEncoder / ...)
                     ▼
              [3. Apply Feedback Weights]   final = reranker × feedback
                     ▼
              [4. Token Budget Pruning]
                     ▼
              [5. Assembled Context JSON]
```

### 7.4 Feedback scoring

```
final_score = reranker_score × feedback_weight

Cold start: all weights = 0.5  →  final_score = reranker_score × 0.5  (neutral, pure relevance)

Example after 30 positive feedback rounds:
Entity A: reranker=0.92, feedback=0.87 → final = 0.80
Entity B: reranker=0.85, feedback=0.95 → final = 0.8075   ← outranks A despite lower relevance
```

---

## 8. Context Assembly — The 7-Step Algorithm

This is the heart of the value: take raw search results and assemble a structured, token-efficient context package.

1. **Parse Intent** — decompose NL query into entity references, relationship type hints, temporal constraints, search filters. Identify seed entities for BFS.
2. **Seed Entity Selection** — BM25 + cosine identify primary entities → BFS starting points.
3. **Hybrid Parallel Search** — BM25 + cosine + BFS simultaneously.
4. **Rerank & Merge** — dedup by UUID; apply configured reranker.
5. **Apply Feedback Weights** — `final = reranker × feedback_weight`.
6. **Budget-Aware Temporal Pruning** — fill `max_tokens` in priority order:
   1. Primary entities (always)
   2. Direct relationships between primary entities (current only)
   3. Relevant facts (current-state temporal filter)
   4. Saga summaries
   5. Decision lineage (if `include_lineage=True`)
   Stop when budget exhausted.
7. **Serialize & Package** — structured JSON with primary entities, relationships, current facts, recent changes, decision history, saga summary, communities, source provenance, metadata.

### 8.1 Output JSON example

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

### 8.2 Why ~80% [TARGET] fewer tokens

Chunk-based RAG retrieves ~10-20 similar chunks (each ~200-400 tokens) → ~3,400 tokens of overlapping, redundant text. An entity mentioned in 5 chunks appears 5 times.

ContextD retrieves **specific entities, relationships, facts** — structured (entity appears once), temporally filtered (only current facts), feedback-weighted (only proven-useful elements). Target ~800-1,000 tokens for equivalent coverage.

The reduction is workload-dependent — early queries without feedback see smaller reductions; well-trained graphs with months of feedback approach the target.

---

## 9. Feedback System — How the Graph Learns

The graph gets smarter with every interaction.

### 9.1 The math (EMA — Exponential Moving Average)

```python
# Step 1: Normalize 1-5 rating to 0.0-1.0
normalized = (score - 1) / 4    # 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0

# Step 2: EMA update (alpha = 0.1)
updated_weight = previous_weight + 0.1 * (normalized - previous_weight)

# Step 3: Clamp + round
updated_weight = round(clamp(updated_weight, 0.0, 1.0), 4)
```

### 9.2 Worked example

```
Entity: "Acme Support Tickets"

Week 1 (no feedback):     weight = 0.50  (neutral)
                          Query → reranker=0.90 × 0.50 = 0.45

Week 1 (5/5):             0.50 + 0.1 × (1.0 - 0.50) = 0.55
Week 2 (4/5, 5/5):        0.55 → 0.57 → 0.613
Week 3 (5/5):             0.652
... after 30 positive rounds:  ≈ 0.92

Week 4:                   reranker=0.90 × 0.92 = 0.828   ← RANKS HIGH

Compare "Acme Marketing Campaign" (30 rounds at avg 2/5):
weight: 0.50 → 0.31  →  reranker=0.85 × 0.31 = 0.264   ← DEMOTED

The graph learned: support agents need ticket data, not marketing data.
```

### 9.3 Submission

```python
await db.feedback(
    session_id="session_abc123",
    query_id="q_456",
    score=4,
    used_entities=["entity_789"],
    used_edges=["edge_345"],
)
```

### 9.4 Design properties

- **Cold start safe:** everything starts at 0.5. System works perfectly without feedback.
- **Purely additive:** feedback only improves results — never makes them worse than "no feedback".
- **Idempotent:** duplicate submissions skipped via `memify_metadata` flag.
- **Auditable:** all feedback events logged with timestamps, session IDs, user IDs.

### 9.5 Auto-feedback detection

LLM-based analysis of conversation turns: "that was exactly what I needed" (positive), "no, that's wrong" (negative), "actually the revenue was $50M not $30M" (correction → supersede fact). Continuous learning signal without explicit ratings.

---

## 10. Context Cores — CI/CD for Context

Versioned, portable, content-addressed snapshots of entire graph — data, embeddings, ontology, retrieval policies, feedback weights.

### 10.1 Lifecycle

```
BUILD ──► TEST ──► VERSION ──► PROMOTE ──► PRODUCTION
                                              ▲
                                          ROLLBACK
```

### 10.2 Core contents

| Component | What it contains |
|-----------|------------------|
| Graph data | All entities, relationships, facts, decisions |
| Embeddings | Entity name + relationship fact vectors |
| Ontology | Schema that constrained extraction |
| Source manifests | Which episodes/connectors contributed, timestamps |
| Retrieval policies | Search recipe configs |
| Feedback weights | All learned relevance scores |
| Metadata | SHA-256 content hash, build timestamp, builder identity |

### 10.3 Operations

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

**Serialization:** msgpack (30-50% smaller than JSON, 2-10× faster) + content-addressed SHA-256 hashing. Each core immutable once built.

---

## 11. Connectors

ContextD has two tiers.

### 11.1 P0 — Custom-built

Deep extraction logic — they understand the *semantics* of each source, not just forward raw data.

| Connector | Extracts | Entity types produced |
|-----------|----------|-----------------------|
| **Gmail** | Threads, headers, body, attachments, labels | Person, Thread, Topic, Commitment, Decision |
| **Salesforce** | Accounts, contacts, opportunities, activities, custom objects | Company, Person, Deal, Activity |
| **Slack** | Messages, threads, reactions, mentions, channels | Person, Channel, Topic, Decision |
| **GitHub** | Repos, issues, PRs, commits, reviews, comments | Person, Repository, Issue, PR |
| **Zendesk** | Tickets, agents, customers, SLAs, satisfaction | Person, Ticket, Company |
| **HubSpot** | Contacts, companies, deals, activities, lists | Person, Company, Deal, Campaign |

**Gmail deep-dive:** parses thread structure, headers (From/To/CC/BCC/Date/Subject/Message-ID/In-Reply-To), strips HTML, extracts commitments ("I'll send the proposal by Friday") and decisions ("Approved the 20% discount"). Creates `person→emailed→person`, `person→discussed→topic`, `person→committed_to→commitment`, `email→part_of→thread`, `thread→about→topic` relationships.

### 11.2 P1 — Airbyte + Quality Layer

600+ connectors via Airbyte's open-source catalog with ContextD's quality layer:
- LLM entity/relationship extraction
- Ontology constraints
- MinHash + cosine deduplication
- Full provenance metadata

Highlighted P1: Notion, Jira, Linear, Google Drive, PostgreSQL, Snowflake, Microsoft Teams, Outlook.

### 11.3 Custom Connector SDK (Python)

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
            ) for r in records
        ]
```

**OAuth2:** 30+ providers out of the box (Google, Microsoft, GitHub, Slack, Salesforce, HubSpot, ...). Tokens encrypted at rest, rotated automatically.

### 11.4 Connectors visible in repo's frontend (current state)

Airtable, Asana, Attio, Bitbucket, Box, ClickUp, Confluence, Dropbox, Github, Gitlab, Gmail, Google Calendar, Google Docs, Google Drive, Hubspot, Jira, Linear, Notion, Onedrive, Salesforce, Sharepoint, Slack, Stripe, Trello, Zendesk + sources visible in `backend/contextd/platform/sources/`: Airtable, Asana, Attio, Bitbucket, Box, Clickhouse, ClickUp, Confluence, ctti, Dropbox, Excel, GitHub, GitLab, Gmail, Google Calendar/Docs/Drive/Slides, HubSpot, Jira, Linear, Monday, Notion, OneDrive, OneNote, Outlook Calendar/Mail, Pipedrive, PostgreSQL, Salesforce, SharePoint, Shopify, Slack, Stripe, Teams, Todoist, Trello, Word, Zendesk, Zoho CRM (~40 active sources).

---

## 11.5 Context Forge — The Pre-Pipeline Mapping Layer

> **Critical missing piece in the original flow.** Before any context graph can be built from a structured enterprise source (Postgres, MySQL, Snowflake, BigQuery, Salesforce, HubSpot, etc.), Context Forge runs to ingest schema + data + business logic, propose a deterministic mapping into ContextD primitives, surface it in a curation UI for the customer to review and edit, and emit a versioned mapping artifact that configures the 10-step pipeline. Without this layer, the pipeline tries to LLM-extract everything — expensive, unreliable, and disrespectful of the analyst team's existing dbt / LookML / SQL / metric work. **Detailed in `06-context-forge.md`**.

### 11.5.1 Why Context Forge exists

Three failure modes the original architecture had:

1. **Ignores schema knowledge that already exists.** Customer arrives with 47 tables, 218 FKs, a 150-model dbt project, and 100+ LookML measures. Re-deriving via LLM discards their work and probably gets it wrong.
2. **Business logic isn't passive metadata.** dbt formulas like `LTV = AVG(monthly_revenue) / NULLIF(1 - retention_rate, 0)` produce derived facts that no LLM can re-discover from a single row.
3. **Enterprises don't trust black-box ingestion.** Regulated industries require an auditable mapping from source data to derived data. "Trust me, the LLM figured it out" is unacceptable.

### 11.5.2 The four-stage flow

```
INTROSPECTION → INFERENCE → CURATION → COMMIT
```

1. **Introspection.** Source Introspector (DDL, FKs, indexes, views, stored procedures, comments via `INFORMATION_SCHEMA` / `pg_catalog` / `sys.*` / etc.) + Data Profiler (HyperLogLog cardinalities, top-K via Count-Min Sketch, regex patterns, PII heuristics, cross-column correlations) + Business Logic Ingester (dbt manifest, LookML, MetricFlow YAML, Cube.dev, SQL views via SQLGlot, stored procedures, Tableau / Power BI calculated fields, plain-language metric definitions LLM-assisted).
2. **Inference.** Mapping Inference Engine runs seven passes: (1) table → entity-type, (2) FK → relationship-type, (3) junction-table detector, (4) column → fact-predicate, (5) time-series / audit-table recognizer, (6) derived-metric translator, (7) confidence scorer. Outputs candidate Forge Mapping with confidence per inference + reasoning trail.
3. **Curation.** Forge Studio: three-pane review/edit UI (source schema | proposed mapping | graph preview). Inline edits, bulk operations, validation panel, sample-data trace, smoke-test queries, version diff. Customer reviews and approves rather than the system silently committing.
4. **Commit.** Forge Mapping serialized as msgpack + SHA-256 content-addressed (consistent with Context Cores machinery). Versioned (v1, v2, ...), immutable, diffable, rollbackable.

### 11.5.3 Components

| Component | Purpose |
|-----------|---------|
| **Source Introspector** | Adapters for Postgres, MySQL, SQL Server, Oracle, Snowflake, BigQuery, Databricks, ClickHouse, Salesforce, HubSpot, NetSuite, Workday, Dynamics, Zuora |
| **Data Profiler** | HyperLogLog cardinality, Count-Min Sketch top-K, length distributions, regex pattern fits, Presidio-based PII detection, mutual-information cross-column correlation |
| **Business Logic Ingester** | dbt project, dbt Semantic Layer / MetricFlow YAML, LookML, Cube.dev, OpenLineage / DataHub, Tableau .tds, Power BI DAX, SQL views + stored procedures, custom YAML/JSON, plain-language LLM-assisted |
| **Mapping Inference Engine** | Seven inference passes with confidence scoring; combines schema + profiles + business logic + ontology hints |
| **Forge Studio** | Three-pane UI with inline edits, bulk operations, validation warnings, smoke-test queries, sample-data trace, diff between versions |
| **Forge Mapping** | Versioned, content-addressed, msgpack-serialized, SHA-256-hashed artifact (immutable once applied) |
| **Forge Profiles** | Pre-built mappings for Salesforce, HubSpot, Stripe, Shopify, Zendesk, Jira/Linear, dbt-Snowflake (Fivetran-modeled), generic OLTP Postgres |
| **Forge-to-Pipeline Bridge** | Pipeline reads Forge Mapping at runtime; deterministic extraction for Forge-covered structures, LLM extraction reserved for unstructured fields; derived facts computed via customer formulas |

### 11.5.4 Architectural placement (Layer 1.5)

```
LAYER 5: INTEGRATION (SDK / MCP / REST / 6 Wire Protocols)
LAYER 4: RBAC & AUTH
LAYER 3: CONTEXTD ENGINE (10-step ingestion now Forge-aware, hybrid retrieval, cores, ...)
LAYER 2: UNIFIED MULTI-MODEL STORAGE SUBSTRATE
LAYER 1.5: CONTEXT FORGE  ◄── pre-pipeline mapping layer
LAYER 1: CONNECTOR LAYER
```

### 11.5.5 Net effect on ingestion economics

For enterprises with significant structured data, **LLM extraction cost drops 60-80%** vs LLM-only ingestion. Determinstic extraction replaces LLM calls for known structures; LLM extraction is preserved only for genuinely unstructured fields (free-text columns, message bodies, Gmail content). The customer's analyst-team work is honored end-to-end — every dbt metric, LookML measure, and SQL view definition produces a corresponding derived fact in the graph.

### 11.5.6 Defensibility

Context Forge requires **simultaneously** owning (a) the ingestion pipeline, (b) the graph schema, and (c) the customer-facing curation UX. Existing players own one or two: ETL tools (Airbyte, Fivetran) own ingestion; data catalogs (DataHub, Atlan, Collibra) own metadata; graph DBs (Neo4j, Neptune) own graph. Context Forge is the integration of all three — and the multi-format business-logic parser (dbt + LookML + MetricFlow + Cube.dev + DAX + SQL views via SQLGlot) is itself a multi-quarter engineering investment.

Differentiator score (see `11-technical-capabilities.md`): structural depth 5/5, compounding 5/5, distribution 4/5 = **14/15** total. Joint-highest moat alongside Context Cores.

---

## 12. Architecture — Five Layers (Future-state, ContextD on its own substrate)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: INTEGRATION                                                     │
│ Python SDK · MCP Server (stdio/SSE/HTTP) · REST API (FastAPI) · GraphQL  │
│ Wire Protocols: Bolt · PostgreSQL · MongoDB · Redis · gRPC · HTTP        │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: RBAC & AUTH                                           │
│ API Keys (SHA-256) · OAuth 2.0 · Role Scoping · Append-Only Audit Logs   │
│ 6 Roles: Owner · Admin · Editor · Viewer · Agent · Connector             │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: CONTEXTD ENGINE (LIVE + BUILDING)                               │
│ 10-Step Ingestion · 5-Phase Entity Resolution · Hybrid Query Engine      │
│ 7-Step Context Assembly · Context Cores · Feedback EMA · Ontology Engine │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: UNIFIED STORAGE SUBSTRATE (FUTURE — ArcadeDB-style)             │
│ Graph + Document + KV + Vector (HNSW/PQ) + Full-Text (BM25)              │
│ + Time-Series (Gorilla XOR) · 70+ SIMD Algorithms · ACID Transactions    │
├──────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: CONNECTOR LAYER                                          │
│ Airbyte Engine (600+ sources) · Custom SDK Connectors (6 P0 + SDK)       │
│ OAuth2 Service (30+ providers) · Incremental Sync                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### 12.1 What ContextD builds vs what the substrate provides

| Substrate provides (storage primitives) | ContextD builds (intelligence layer) |
|-----------------------------------------|--------------------------------------|
| Graph engine (Cypher, Gremlin, SQL) | 10-step ingestion pipeline |
| Vector indexes (HNSW + PQ) | 5-phase entity resolution |
| Full-text search (Lucene BM25) | Ontology-constrained extraction |
| Document storage (JSON) | Streaming EMA feedback engine |
| Key-value store | 7-step context assembly |
| Time-series (Gorilla XOR) | Bitemporal schema |
| Native graph algorithms (PageRank, Louvain, ...) | Context Cores (versioning) |
| Wire protocols (Bolt, PG, Mongo, Redis, gRPC) | MCP/API integration surface |
| HA clustering, WAL, ACID | Connector SDK + quality layer |
| Built-in MCP server | Decision lineage model |

### 12.2 The closed loop

```
CONNECTOR               INGESTION PIPELINE                     QUERY ENGINE
Gmail ──┐           ┌─ Step 1: Create Episode                  Natural Language Query
Slack ──┤           ├─ Step 2: Retrieve Context                       │
SFDC ──┼── Eps ──►├─ Step 3: Extract Nodes ◄── Ontology              ▼
GitHub─┤           ├─ Step 4: Resolve (deterministic)          1. Parse Intent
  ...  │           ├─ Step 5: Resolve (semantic+LLM)           2. Hybrid Search ◄── feedback_weight
       │           ├─ Step 6: Extract Edges ◄── Ontology       3. Rerank ◄── feedback_weight
       │           ├─ Step 7: Dedup/Invalidate Edges           4. Apply Feedback Weights
       │           ├─ Step 8: Generate Embeddings              5. Budget-Aware Pruning
       │           ├─ Step 9: Save to Graph ─────────────────► 6. Temporal Enrichment
       │           └─ Step 10: Community Detection             7. Assemble Context Window
       │                                                              │
       │           CONTEXT CORES                                      │
       │           Build ◄── Snapshot ◄── Graph Storage               │
       │           Test ◄── Query Suite                               │
       │           Promote ──► Production                             ▼
       │           Rollback ◄── Previous Version              ASSEMBLED CONTEXT
       │                                                              │
       │           FEEDBACK LOOP                                      ▼
       └───── Agent rates response (1-5) ───────────────► EMA Weight Update
                    used_entities/edges ─────────────────► per node & edge
                    idempotent processing ──────────────► ──► Graph Storage
```

---

## 13. Integration Surface

### 13.1 Four integration paths

| Mode | Latency | How to start | Use case |
|------|---------|--------------|----------|
| **Embedded** | [TARGET] <10ms | `pip install contextd` (Java 21 via jpype) | Local agents, edge, prototyping |
| **Server** | [TARGET] <50ms | `docker compose up` | Team usage, shared instance |
| **Cloud** | [TARGET] <300ms | Sign up at contextd.ai | Production, fully managed |
| **Enterprise** | [TARGET] <50ms | On-prem / air-gapped K8s | HA clustering, compliance |

### 13.2 Two-layer MCP architecture

| Layer | What it provides | Tools |
|-------|------------------|-------|
| **Layer 1: Substrate built-in** | Raw DB operations | execute_command, get_schema, list_databases, query, server_status |
| **Layer 2: ContextD** | Context-specific tools | query_context, get_entity, get_timeline, get_decision_lineage, get_saga_summary, submit_feedback, ingest_episode |

| Transport | Use case |
|-----------|----------|
| `stdio` | Claude Code, Cursor, Windsurf |
| `SSE` | Web agent frameworks, real-time streaming |
| `HTTP` | REST integrations, serverless functions |

### 13.3 REST API endpoints

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

### 13.4 Wire protocol polyglot (substrate-provided)

A single instance speaks 6 protocols simultaneously:

| Protocol | Drivers | Use case |
|----------|---------|----------|
| **Bolt** | Neo4j Python/Java/Node/Go/.NET | Cypher, existing Neo4j code |
| **PostgreSQL** | psql, pgAdmin, JDBC, SQLAlchemy | SQL teams, BI tools |
| **MongoDB** | PyMongo, Mongoose | Document access |
| **Redis** | redis-py, Jedis | KV, sessions |
| **gRPC** | Custom (any language) | High-perf inter-service |
| **HTTP/REST** | curl, any HTTP client | Universal |

> **Caveat from benchmark:** the PostgreSQL wire protocol implementation in ArcadeDB has a `CodeUtils.sleep(100)` polling bug (`PostgresNetworkExecutor.java:1515`) that adds 100ms floor per query — **must be patched** in our fork before shipping PG-protocol access.

---

## 14. Observability — OTEL + Prometheus

### 14.1 What gets traced

| Operation | Spans created |
|-----------|---------------|
| Ingestion pipeline | 1 parent + 1 child per step (all 10) |
| Entity resolution | 1 span per stage (normalize, entropy, minhash, cosine, llm) |
| Search | 1 parent + child per method (BM25, cosine, BFS) + reranker |
| Context assembly | 1 span covering token optimization + packaging |
| Feedback | 1 span per weight update batch |
| Connector sync | 1 parent + children for auth, extract, transform, load |

### 14.2 Semantic span attributes

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

### 14.3 Prometheus metrics

| Metric | Type |
|--------|------|
| `contextd_queries_total` | Counter |
| `contextd_query_latency_seconds` | Histogram |
| `contextd_ingestion_episodes_total` | Counter |
| `contextd_ingestion_latency_seconds` | Histogram |
| `contextd_entity_resolution_accuracy` | Gauge |
| `contextd_feedback_scores` | Histogram |
| `contextd_context_tokens_saved` | Counter |

### 14.4 Graceful fallback

When OTEL not installed, uses `NullSpan` — all tracing calls become no-ops. Zero overhead, zero errors.

---

## 15. Security, RBAC, Compliance

### 15.1 Six roles

| Role | Description |
|------|-------------|
| **Owner** | Full access; can delete graph |
| **Admin** | Manage connectors, users, roles; no deletion |
| **Editor** | Read/write data, trigger syncs; no user/connector mgmt |
| **Viewer** | Read-only, scoped (source / entity-type / tags) |
| **Agent** | Programmatic, scoped read + feedback submit |
| **Connector** | Write-only to own source |

### 15.2 Permission matrix

| Permission | Owner | Admin | Editor | Viewer | Agent | Connector |
|-----------|:-----:|:-----:|:------:|:------:|:-----:|:---------:|
| Read entities/relationships/facts | Y | Y | Y | scoped | scoped | N |
| Read decision lineage | Y | Y | Y | scoped | scoped | N |
| Read episodes (raw data) | Y | Y | Y | N | N | N |
| Write entities/facts | Y | Y | Y | N | N | own source |
| Submit feedback | Y | Y | Y | N | Y | N |
| Manage connectors | Y | Y | N | N | N | N |
| Manage context cores | Y | Y | N | N | N | N |
| Natural language query | Y | Y | Y | scoped | scoped | N |
| Direct Cypher/SQL | Y | Y | Y | N | N | N |
| Delete graph | Y | N | N | N | N | N |

### 15.3 Three scoping dimensions

```json
// Sales agent: only sees Gmail + Salesforce data
{"role": "agent", "name": "sales-agent",
 "scopes": {"sources": ["salesforce", "gmail"]}}

// Marketing analyst: only sees companies, deals, campaigns
{"role": "viewer", "name": "marketing-analyst",
 "scopes": {"entity_types": ["company", "deal", "campaign"]}}

// Project-scoped agent: only sees Project Atlas
{"role": "agent", "name": "atlas-agent",
 "scopes": {"tags": ["project:atlas"]}}
```

### 15.4 Multi-tenancy

Each tenant gets a **separate database** (no cross-tenant data access). Separate connector auth per tenant. Audit logs append-only, immutable, queryable.

```
Organization (Tenant)
├── Graph (isolated database)
│   ├── Connectors
│   ├── Entities, Relationships, Facts, Episodes, Sagas, Communities
│   └── Context Cores (versioned snapshots)
├── Users
├── API Keys
└── Audit Log (append-only, immutable, queryable)
```

### 15.5 Audit log entry

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

### 15.6 Encryption + compliance roadmap

- In transit: TLS 1.3
- At rest: AES-256 (cloud)
- API keys: SHA-256 hashed, never plaintext, revocable
- PII: optional auto-detect with redaction or tagging
- Right to deletion: cascade delete

| Standard | Timeline | Scope |
|----------|----------|-------|
| **GDPR** | Launch (P0) | Data residency, right to deletion, consent tracking |
| **SOC 2 Type I** | Month 9 | Controls documentation, audit readiness |
| **SOC 2 Type II** | Month 15 | Full audit, 6-month observation |
| **ISO 27001** | Month 18 | ISMS |

---

## 16. Deployment & Scalability

### 16.1 Performance profiles

| Profile | Page cache | Workers | Use case |
|---------|-----------|---------|----------|
| `high-performance` | Unlimited (50% RAM) | 50% cores | Production, benchmarking |
| `default` | 4GB | Auto | General |
| `low-ram` | 16MB | Auto | Edge, constrained |
| `low-cpu` | Standard | 1 thread | Background processing |

### 16.2 High availability

Substrate (ArcadeDB) supports leader-replica clustering with synchronous replication, automatic leader election, WAL with configurable flush (no-flush / flush / fsync).

### 16.3 [TARGET] Scalability targets

| Dimension | v1 | v2 |
|-----------|----|----|
| Entities per graph | 10M | 100M |
| Relationships per graph | 50M | 500M |
| Facts per graph | 100M | 1B |
| Episodes per graph | 10M | 100M |
| Connectors per tenant | 30 | 100 |
| Concurrent queries | 100 QPS | 500 QPS |
| Cloud tenants | 1,000 | 10,000 |

> **Caveat:** the benchmark report shows ArcadeDB caps hybrid throughput at ~137 ops/sec on a single 16-vCPU instance with 475K entities. To hit v1's 100 QPS target across millions of entities, the architecture requires read replicas behind a load balancer + a separate vector search service horizontally scalable. See Section 17 for the engineering roadmap.

---

## 17. Benchmark — Real Performance on the ArcadeDB Substrate

> **This is the engineering ground-truth.** All numbers below are **measured**, not aspirational.

### 17.1 Test environment

| | |
|---|---|
| **DB Host** | Azure Standard_D16s_v5 — 16 vCPU, 64 GB RAM, 240 GB Premium SSD |
| **Client Host** | Azure Standard_D4s_v5 — 4 vCPU, 16 GB RAM |
| **Network** | Same VNet, private IPs, ~0.73ms HTTP RTT |
| **ArcadeDB** | v26.4.2, JVM heap 48 GB, G1GC, production mode |
| **Protocol** | HTTP/JSON API (port 2480) |

### 17.2 Dataset

| Metric | Count |
|--------|-------|
| **Vertices (Entity)** | 475,191 |
| **Edges (Relation)** | 1,373,872 |
| **Avg edges per vertex** | 2.89 |
| **Embedding dimensions** | 1,024 (Cohere `embed-english-v3.0`, float32) |
| **Text abstracts** | 463,584 entities (97.6%) |
| **Type-classified** | 366,589 entities (77.1%) |

Source: DBpedia 2022-12 entity graph joined with Cohere Wikipedia embeddings.

### 17.3 Indexes

| Index | Property | Configuration |
|-------|----------|---------------|
| Unique (LSM_TREE) | `Entity.uri` | Unique B-tree |
| Vector (LSM_VECTOR) | `Entity.embedding` | HNSW, 1024 dims, cosine |
| Full-Text | `Entity.abstract` | BM25 Lucene-based |

### 17.4 Throughput scaling (ops/sec)

| Query Type | 1T | 4T | 8T | 16T | 32T | 64T | 128T | Peak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Point Lookup** | 1,206 | 1,423 | 1,443 | **1,456** | 1,414 | 1,340 | 1,200 | 1,456 @ 16T |
| **Full-Text Search** | 279 | 784 | 1,246 | 1,425 | **1,480** | 1,439 | 1,288 | 1,480 @ 32T |
| **Graph 1-hop** | 303 | **591** | 596 | 583 | 549 | 531 | 534 | 596 @ 8T |
| **Vector Search** | 23 | 91 | **157** | 155 | 144 | 145 | 140 | 157 @ 8T |
| **Full Hybrid** | 21 | 78 | 133 | 135 | **137** | 132 | 129 | 137 @ 32T |

### 17.5 Single-thread latencies (best case)

| Query | p50 | p95 | p99 |
|---|---:|---:|---:|
| Point Lookup | **0.77** | 0.83 | 0.90 |
| Graph 1-hop | **1.90** | 10.5 | 17.7 |
| FTS | **3.96** | 7.3 | 8.4 |
| Vector Search | **42.3** | 55.1 | 62.9 |
| Hybrid | **47.3** | 59.2 | 66.9 |

### 17.6 Latency degradation under load

| Query | p50 @ 1T | p50 @ 8T | p50 @ 32T | p50 @ 128T |
|---|---:|---:|---:|---:|
| Point Lookup | 0.77 | 4.6 | 17.9 | 82.1 |
| FTS | 3.96 | 6.2 | 19.9 | 86.2 |
| Graph 1-hop | 1.90 | 9.8 | 55.0 | 228.3 |
| Vector Search | 42.3 | 49.9 | 218.9 | **871.1** |
| Hybrid | 47.3 | 58.0 | 230.4 | **975.6** |

Vector search latency degrades **20× at 128T** while throughput remains flat — classic internal lock contention, not useful parallelism.

### 17.7 Bottleneck analysis

**Bottleneck #1: Point Lookup ceiling (~1,450 ops/sec).** Sub-millisecond queries (0.77ms p50) but throughput barely scales beyond 4 threads. Not network-bound (0.73ms RTT). Serialization point in ArcadeDB's HTTP server or LSM-tree read path. Implication: **need a Redis caching tier above ~1,500 ops/sec**.

**Bottleneck #2: Graph traversal lock contention (~595 ops/sec @ 4T).** Most concerning — graph expansion is part of every GraphRAG query. `expand(out())` likely acquires page-level locks on adjacency-list segments. Implication: **investigate ArcadeDB's CSR-based Graph Analytical View (lock-free traversals introduced in 26.3.x)**.

**Bottleneck #3: Vector search is CPU-bound, not parallelizable (157 ops/sec @ 8T).** Single-thread latency 42ms; at 128T latency balloons to 871ms while throughput drops. HNSW graph traversal contends on read locks. Memory not the issue (1.9 GB graph fits in 48 GB heap). Implication: **at 6M vectors, single-query latency grows to ~100-200ms; need horizontal scaling via read replicas + a dedicated vector service**.

**Bottleneck #4: Hybrid query ceiling (137 ops/sec).** 89% of latency is the vector component (42ms of 47ms). Graph expansion is minimal at 1-2 hops; 2-3 hops would reintroduce graph contention.

### 17.8 Protocol findings

**PostgreSQL wire protocol — unusable in current form.** `CodeUtils.sleep(100)` polling loop in `PostgresNetworkExecutor.java:1515` adds a 100ms floor to every query — **~50× slower than HTTP API**. Fix: replace with blocking I/O (`channel.read()`).

**Network impact: 8× improvement with private VNet.** Public IPs (cross-region): 5.71ms RTT. Private VNet: 0.73ms. Network was 88% of point-lookup latency on public IPs.

**Bulk ingestion: `/batch` API is 20× faster than SQL.** SQL INSERT per-row: 67/sec. HTTP `/batch` JSONL: 1,828/sec. Index build times (475K entities post-ingest): unique 9.8s, HNSW vector 150.5s, full-text 600s.

### 17.9 Recommendations for ContextD architecture

1. **Vector search must be independently scalable.** Short-term: read replicas behind LB. Medium-term: dedicated vector service (jvector or similar) horizontally scalable. Long-term: PQ + pre-filtering to reduce HNSW search cost.
2. **Graph traversal needs lock-free reads.** Investigate CSR-based analytical view; cache hot subgraphs in CSR on the query side; profile contention at page-level vs record-level.
3. **Separate hot path from substrate.** Cache frequently-accessed entities in-process (Caffeine/LRU). Use substrate as persistent store, not hot query path. Read replicas for scaling reads linearly.
4. **Fix the PG protocol before shipping.** Patch the 100ms sleep upstream in our fork.

---

## 18. Differentiators (13 Total)

| # | Differentiator | What it means | Status | Why hard to replicate |
|---|----------------|---------------|--------|----------------------|
| 1 | **Database-native** | Single ACID engine, 6 data models | LIVE (substrate) | Must build on multi-model from day one |
| 2 | **Bitemporal by design** | Every fact tracks event time + transaction time | | Can't be retrofitted — must be in data model |
| 3 | **Feedback-weighted retrieval** | Graph improves via EMA learning (α=0.1) | | Must integrate feedback into every query path |
| 4 | **Ontology-grounded extraction** | Ontology actively constrains LLM output | | Not post-hoc validation — semantic routing during prompts |
| 5 | **Context Cores** | CI/CD for knowledge graphs | | Content-addressed snapshotting + embeddings + weights |
| 6 | **Decision lineage** | First-class auditable, traceable entities | | Purpose-built schema, not just graph traversal |
| 7 | **10-step episodic ingestion** | Full provenance, integrated across the cascade | | Entity resolution + ontology constraint + supersession + EMA feedback unified into one pipeline |
| 8 | **Hybrid retrieval composability** | 3 methods × 5 rerankers = 15 strategies | | Requires BM25 + vectors + graph in same engine |
| 9 | **Wire protocol polyglot** | 6 protocols (Bolt/PG/Mongo/Redis/gRPC/HTTP), 1 engine | Substrate | No competitor has this breadth |
| 10 | **80% [TARGET] token reduction** | Structured context vs chunk-based RAG | Eng target | Only via entity dedup + temporal filter + feedback |
| 11 | **Apache 2.0 substrate** | No SSPL, Commons Clause, or BSL | | True open-source — embed, modify, distribute freely |
| 12 | **Context Forge** | Analyst-aware pre-pipeline mapping module (introspection + data profiling + dbt/LookML/SQL/MetricFlow ingestion + 7-pass inference + Forge Studio UI + versioned msgpack/SHA-256 Forge Mapping artifact) | BUILDING (Phase 2 of roadmap) | Requires simultaneous ownership of ingestion, graph schema, and curation UX. Multi-format business-logic parser is multi-quarter eng investment. **60-80% LLM cost reduction** for enterprise sources. |
| 13 | **Context Resolver** | Cross-source identity stitching module: six-stage pipeline (HNSW + LSH blocking + Fellegi-Sunter + DITTO cross-encoder + CDCR coreference + PSL transitive closure + active-learning + LLM adjudication); bitemporal Identity Graph artifact; Resolver Studio review surface; per-entity-type Resolver Profiles | BUILDING (Phase 4 of roadmap) | Requires simultaneous ownership of multi-source ingestion + vector blocking index + fine-tuneable cross-encoder + coreference + NER stack + PSL engine + bitemporal storage + active-learning UI. Each is multi-quarter eng; combination is the moat. **Technical core of ContextD's cross-source unification claim.** |

---

## 19. Module inventory

The complete set of subsystems in the unified ContextD design — described in detail across files `04` through `13` and indexed here as a single reference list:

- Core data models — Entity, Relationship, Fact, Episode, Saga, Community, Decision (`06-context-forge.md`, `08-core-technology.md`).
- Substrate driver and schema layer (`05-contextd-native-db-implementation.md` §1–§2).
- 10-step episodic ingestion pipeline (`08-core-technology.md` §3).
- Resolution Engine — five-phase cascade plus six-stage probabilistic pipeline (`07-context-resolver.md`).
- Context Forge — schema introspection, data profiling, business-logic ingestion, mapping inference, Forge Studio (`06-context-forge.md`).
- Bitemporal storage layer with four-timestamp schema and four index designs per fact predicate (`08-core-technology.md` §2; `05-contextd-native-db-implementation.md` §5).
- Hybrid retrieval — BM25 + cosine + BFS with five reranker strategies (`08-core-technology.md` §6).
- Seven-step context assembly with token budgeting (`08-core-technology.md` §7).
- Streaming EMA feedback engine (`08-core-technology.md` §8; `05-contextd-native-db-implementation.md` §18).
- Ontology Engine — OWL-like JSON schema, semantic routing per chunk, prompt injection, validation (`08-core-technology.md` §5).
- Context Cores — versioned, content-addressed, msgpack-serialized graph snapshots (`08-core-technology.md` §9; `05-contextd-native-db-implementation.md` §17).
- Identity Graph — canonical entities linked to source-record IDs by confidence-weighted bitemporal edges (`07-context-resolver.md` Component 2).
- Connector layer — six deep-extract first-party connectors plus broad-tier connectors via the Airbyte quality layer (`13-integration-deployment-security.md`).
- OAuth2 service — 30+ providers with token rotation (`13-integration-deployment-security.md`).
- FastAPI REST API and Python SDK (`13-integration-deployment-security.md`).
- MCP server — two-layer registry, three transports (`13-integration-deployment-security.md`; `05-contextd-native-db-implementation.md` §22).
- Wire-protocol polyglot — Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP (`05-contextd-native-db-implementation.md` §21).
- Audit log — append-only sealed-segment, hash-chained (`05-contextd-native-db-implementation.md` §8).
- RBAC — six roles, three scoping dimensions, file-access-map compilation (`13-integration-deployment-security.md`; `05-contextd-native-db-implementation.md` §9).
- Multi-tenancy — database-per-tenant isolation with shared page cache and per-tenant quotas (`05-contextd-native-db-implementation.md` §10).
- Replication — Raft consensus with five state-machine entry types (`05-contextd-native-db-implementation.md` §23).
- Observability — OpenTelemetry traces, Prometheus metrics (`13-integration-deployment-security.md`).
- Time-series engine — sharded design with delta-of-delta + Gorilla XOR + dictionary codecs (`05-contextd-native-db-implementation.md` §14, §24).

---

## 20. Use Cases (Concrete Examples)

### 20.1 AI Agent Memory — Customer 360

```python
context = db.get_context(
    query="Prepare me for a call with Acme Corp",
    max_tokens=2000,
    include_lineage=True,
)
# Returns: deal status, ALL touchpoints (CRM + support + marketing + comms),
# sentiment trajectory, open issues, key stakeholders, decision history.
# Feedback-weighted: most useful context from prior calls ranked highest.
```

Without ContextD: agent hits CRM, doesn't see the 3 angry support tickets last week, the marketing email promising a feature that doesn't exist, the Slack message where the CEO said they're evaluating competitors.

### 20.2 Compliance & Audit — Decision Lineage

```cypher
MATCH (d:Decision {decision_type: "discount"})
WHERE d.outcome > "15%"
  AND d.decided_at >= datetime("2026-01-01")
  AND d.decided_at <  datetime("2026-04-01")
OPTIONAL MATCH (d)-[:DECIDED_BY]->(approver)
OPTIONAL MATCH (d)-[:APPLIED_POLICY]->(policy)
RETURN d.subject, d.outcome, approver.name, policy.name, d.exception, d.justification
ORDER BY d.decided_at
```

Every discount links back to its inputs, policy, exception status. **Impossible with vector search** — needs graph lineage, bitemporal tracking, decision entities.

### 20.3 Audience Activation — Cross-System Behavioral Query

"High-usage companies with urgent tickets, not contacted in 14 days" — churn risk cohort:

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

CRM + support + marketing in a **single graph query** with bitemporal filtering. Impossible across separate databases.

### 20.4 RAG Enhancement — 80% [TARGET] Token Reduction

```python
context = db.get_context(
    query="What's our current security posture for the AWS deployment?",
    max_tokens=1500,
    search_recipe=COMBINED_HYBRID_SEARCH_RRF,
)
# Target: ~847 tokens (vs ~3,400 from chunk RAG)
# Connected facts: architecture docs, security review, Jira tickets, pen test results, compliance policy
```

### 20.5 Context Core CI/CD

```bash
contextd core build  --name "customer-context" --graph "production"
contextd core test   --core "customer-context:v5" --queries "test-suite.yaml"  # 50/50 pass
contextd core promote --core "customer-context:v5" --target "production"
contextd core rollback --target "production" --to "customer-context:v4"
contextd core diff   --from "customer-context:v4" --to "customer-context:v5"
```

### 20.6 Worked queries (full Data 360 example)

```python
result = db.query("Give me the full picture on Acme Corp")
```

Returns primary entities (Acme Corp with industry/employees/revenue/HQ), relationships (HAS_DEAL, WORKS_FOR Sarah Chen, EVALUATING Infrastructure Migration, COMPETES_WITH Beta Corp), facts (industry, annual_budget, churn_risk, nps_score), saga summary ("$250M technology company, 5,000 employees, negotiating 500-seat enterprise deal..."), sources (Salesforce, Confluence, Gmail), metadata (1,847 tokens used, 7,353 saved).

```python
result = db.get_timeline(entity_id="entity_acme_001")
```

Returns chronological event list across all sources: account created, contact added, deal created, stage change, sentiment shift, pricing change, risk flag, decision (15% discount approved + net-60 exception), agreement, objection, support ticket.

```python
result = db.get_decision_lineage(entity_id="decision_discount_15pct")
```

Returns the decision, who decided (Jordan Blake, VP Sales), what informed it (Acme economics spreadsheet, competitor pricing analysis showing VendorX 18%, customer sentiment report), policy applied (volume_discount_policy_v3, v3.2), exception (net-60 vs standard net-30), justification ("Strategic account with active competitive pressure"), downstream impact (pricing revised $45→$38, Q2 revenue forecast reduced by $15K, procurement extended timeline).

---

## 21. Build Guide Highlights (from contextD.md §29)

The full implementation reference exists in `contextD.md` §29. Key phases:

| Phase | Weeks | Stack | What ships |
|-------|-------|-------|-----------|
| **1. Storage Foundation** | 1-3 | Substrate Docker, httpx, Pydantic v2 | DB driver, schema, vertex/edge types, HNSW vector index, Lucene FTS index |
| **2. Ingestion Pipeline** | 4-7 | OpenAI SDK, Pydantic structured output, Jinja2 | LLM client (function calling), 10-step pipeline runner, entity extraction, 5-phase resolution (datasketch MinHash/LSH + numpy cosine), edge extraction + supersession |
| **3. Retrieval Engine** | 8-11 | Substrate FTS + vector + Cypher BFS | BM25/cosine/BFS search methods, RRF/MMR/NodeDistance/EpisodeMentions rerankers, 7-step context assembly with tiktoken token budgeting |
| **4. Feedback & Learning** | 12-13 | Custom EMA engine, substrate UPDATE | Streaming EMA (α=0.1), idempotency via memify_metadata flag, audit logging |
| **5. Ontology Engine** | 14-15 | Jinja2, numpy, Pydantic | Semantic routing, embedding ontology elements, prompt injection, validation (class filter, domain/range, cardinality, disjoint) |
| **6. Context Cores** | 16-17 | msgpack, hashlib SHA-256 | Build, test, diff, promote, rollback content-addressed snapshots |
| **7. API & Connectors** | 18-21 | FastAPI, google-api-python-client, httpx | REST endpoints (`/context`, `/ingest/episode`, `/feedback`), OAuth2 connectors, MCP server |
| **8. Observability & RBAC** | 22-24 | opentelemetry-sdk, prometheus-client, hashlib | OTEL spans + NullSpan fallback, Prometheus metrics, RBAC middleware (SHA-256 API keys), audit log |

Total estimated build: ~24 weeks for a single-team effort to ship a v1 unified ContextD on a chosen substrate.

---

## 22. Key Numbers Reference

| Metric | Value | Source |
|--------|-------|--------|
| Data models in one engine | 6 (graph, vector, full-text, document, KV, time-series) | [TARGET] |
| Graph algorithms (SIMD) | 70+ | substrate-provided |
| Token reduction vs chunk RAG | ~80% (~847 vs ~3,400 tokens) | [TARGET] |
| Graph traversal latency, single-thread | 1.90ms p50 | [BENCH] |
| Graph traversal peak throughput | 596 ops/sec @ 8T | [BENCH] |
| Vector search peak throughput | 157 ops/sec @ 8T | [BENCH] |
| Hybrid query peak throughput | 137 ops/sec @ 32T | [BENCH] |
| Hybrid query latency, single-thread | 47.3ms p50 | [BENCH] |
| Bulk ingestion rate | 1,828 vertices/sec via /batch API | [BENCH] |
| HNSW vector index build (475K × 1024-dim) | 150.5s | [BENCH] |
| Ingestion pipeline steps | 10 | spec |
| Entity resolution phases | 5 | spec |
| Search methods (parallel) | 3 (BM25, cosine, BFS) | spec |
| Reranking strategies | 5 | spec |
| Context assembly steps | 7 | spec |
| Data connectors | 6 P0 custom + 600+ via Airbyte; ~40 active in repo | spec + repo |
| Wire protocols | 6 (Bolt, PG, Mongo, Redis, gRPC, HTTP) | substrate |
| RBAC roles | 6 | spec |
| Scoping dimensions | 3 (source, entity type, tags) | spec |
| Feedback learning rate (α) | 0.1 | spec |
| Feedback cold start weight | 0.5 (neutral) | spec |
| MinHash permutations | 32 | spec |
| MinHash LSH band size | 4 | spec |
| Cosine similarity threshold | 0.6 | spec |
| Jaccard similarity threshold | 0.9 | spec |
| Entropy gate threshold | 1.5 bits | spec |
| Ontology selection threshold | 0.3 cosine, top-k 10 | spec |
| OAuth2 providers | 30+ | spec |
| Audit log retention | 1 year (free), 7 years (enterprise) | spec |
| Scalability v1 entities/graph | 10M | [TARGET] |
| Scalability v1 concurrent QPS | 100 | [TARGET] |
| Scalability v2 entities/graph | 100M | [TARGET] |

---

## 23. Tech Stack Reference

### 23.1 Today (in this repo)

- **Frontend:** React + TypeScript + ShadCN
- **Backend:** FastAPI (Python 3.13)
- **Databases:** PostgreSQL (metadata) + Neo4j (graph + Lucene full-text) + Milvus (vectors)
- **Workers:** Temporal (orchestration) + Redis (pub/sub, cache)
- **Deployment:** Docker Compose
- **Connectors:** ~40 sources (P0 custom + Airbyte-style)
- **LLMs:** OpenAI (gpt-4o, embed-text-3-small) + Anthropic (Claude Sonnet 4.6)
- **Observability:** OpenTelemetry + Prometheus + PostHog

### 23.2 Tomorrow (the unified ContextD on a multi-model substrate)

| Component | Tech | License | Why |
|-----------|------|---------|-----|
| **Unified Storage** | ArcadeDB (or equivalent Apache 2.0 multi-model) | Apache 2.0 | Only multi-model DB doing graph + vector + full-text + doc + KV + time-series in one ACID engine |
| **Vector Search** | LSMVector (jvector HNSW) + PQ | Apache 2.0 | Native HNSW with PQ compression; no external vector DB |
| **Full-Text** | Lucene BM25 | Apache 2.0 | Battle-tested, native to substrate |
| **Entity Resolution** | Custom | MIT | 5-phase cascade — exact → entropy → MinHash → cosine → LLM |
| **Ontology Engine** | Custom | Apache 2.0 | OWL-like JSON, semantic routing, Jinja2 prompt injection |
| **Feedback Engine** | Custom | Apache 2.0 | Streaming EMA (α=0.1), idempotent, session-aware |
| **Connectors** | Airbyte + Custom SDK | Apache 2.0 | 600+ pre-built + custom P0 |
| **API Server** | FastAPI | MIT | Async, auto-OpenAPI |
| **MCP Server** | Custom (multi-transport) | MIT | stdio/SSE/HTTP |
| **Observability** | OpenTelemetry + Prometheus | Apache 2.0 | NullSpan graceful fallback |
| **Graph Algorithms** | Substrate native (70+ SIMD) | Apache 2.0 | PageRank, Louvain, Label Propagation, shortest path; Java 21 Vector API |
| **LLM Providers** | OpenAI + Anthropic + extensible | — | Extraction, dedup, summarization, reranking |
| **Deployment** | Docker / Kubernetes | — | Compose for dev, K8s HA for prod, jpype for embedded |

---

## 24. Footer & Credits

- **Built on:** ArcadeDB (Apache 2.0) — chosen as the unified storage substrate
- **Reference tools & prior art:** consolidated in 
- **Founders:** Nikhil Reddy & Bhavik
- **© 2026 ContextD Inc.**
- **Public site:** https://contextd-tech.vercel.app

---

*End of master source document. The topic-wise files (`01` through `14`) refine and structure this material per concern.*
