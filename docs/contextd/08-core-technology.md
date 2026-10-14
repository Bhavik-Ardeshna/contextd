# 08 — Core Technology

> Deep technical dive on every subsystem. For the architectural overview, see `04-product-and-architecture.md`. For measured performance, see `09-benchmarks-and-validation.md`.

---

## 1. The six data primitives

Everything in ContextD is one of six types. These are the atoms of the knowledge graph. Each carries bitemporal metadata, provenance stamps, and feedback weights.

### 1.1 Entity — "the nouns"

Represents a thing: a person, company, project, ticket, deal, document.

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

`canonical_id` is what unifies "John Smith" (Salesforce), "john@acme.com" (Gmail), "john.smith" (Slack) into one resolved person.

### 1.2 Relationship — "the verbs"

Typed, directed, temporally-tracked edges ("Alice **works_at** Acme Corp").

```
Relationship {
  source_entity_id → target_entity_id: UUID
  relationship_type: STRING
  fact:              STRING      — natural-language description (BM25-searchable)
  fact_embedding:    [FLOAT]     — for semantic relationship search
  weight / feedback_weight: FLOAT
  episodes:          [UUID]      — every episode that mentioned this
  valid_at, invalid_at, created_at, expired_at
  reference_time, source, extraction_method, source_pipeline, source_task
}
```

The `fact` field carries the natural-language form ("Alice has been VP of Engineering at Acme Corp since 2023"), making relationships first-class searchable objects, not just typed edges.

### 1.3 Fact — "the claims"

A single, time-bounded, verifiable statement.

```
Fact {
  subject_entity_id: UUID
  predicate:         STRING       — has_budget | decided_to | committed_to | ...
  object:            STRING|UUID  — value or link to entity
  valid_at, invalid_at, created_at, expired_at
  confidence, feedback_weight
  source_episode_id
  extraction_method
}
```

**Critical: supersession.** When a new fact contradicts an old one (budget $2.4M → $3.1M), the old fact is **never deleted**. Old fact: `expired_at = now()`, `invalid_at = when_new_fact_became_true`. New fact: created alongside. Both coexist. This preserves complete history and enables all four temporal query types.

### 1.4 Episode — "the raw material"

The unprocessed source event. Everything else is *extracted from* episodes — full provenance.

```
Episode {
  episode_type:  STRING      — message | json | text
  source:        STRING      — gmail | slack | github | salesforce | ...
  content:       TEXT
  metadata:      JSON
  entity_edges:  [UUID]      — entities/edges extracted from this episode
  valid_at:      TIMESTAMP   — when the event occurred
  created_at:    TIMESTAMP   — when ingested
}
```

### 1.5 Saga — "the storyline"

A storyline spanning multiple episodes — e.g., "Acme deal negotiation: 47 emails over 3 months."

```
Saga { name; summary (incrementally LLM-updated);
       first_episode_id; last_episode_id; last_summarized_at }

Saga ──HAS_EPISODE──▶ Episode ──NEXT_EPISODE──▶ Episode  (temporal linked list)
```

Incremental summarization avoids re-reading the entire history; LLM receives `existing_summary + new_episode` → updated summary.

### 1.6 Community — "the neighborhood"

Auto-discovered clusters via Louvain or Label Propagation.

```
Community { name; name_embedding; summary (LLM-generated) }
```

Communities provide macro-level structure for navigating large graphs — instead of searching 100K entities, search 500 communities first.

### 1.7 Decision — "first-class auditability"

Most systems treat decisions as invisible side-effects buried in event logs. ContextD makes them searchable, traceable, auditable.

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

### 1.8 Schema relationships

```
Episode ──extracts──▶ Entity · Fact · Relationship
Entity ──has_fact──▶ Fact
Entity ──related_to──▶ Entity (via Relationship)
Saga ──has_episode──▶ Episode ──next_episode──▶ Episode
Community ──has_member──▶ Entity
Fact ──superseded_by──▶ Fact (temporal chain)
Decision ──informed_by──▶ Fact · Episode
Decision ──decided_by──▶ Entity
Decision ──applied_policy──▶ Entity
Decision ──affected──▶ Entity
Ontology ──constrains──▶ Ingestion Pipeline (steps 3 and 6)
```

Everything traces back to Episodes. Full provenance always available.

---

## 2. The bitemporal time model

Every entity, relationship, and fact tracks **two independent time dimensions.**

| Dimension | Fields | What it means | Analogy |
|-----------|--------|---------------|---------|
| **Event Time** | `valid_at` → `invalid_at` | When was this true *in the real world*? | "Alice worked at Acme from January to June" |
| **Transaction Time** | `created_at` → `expired_at` | When did **we** record/learn/supersede this? | "We wrote this in our notebook on March 5th" |

Reality and our knowledge of reality change independently — the same fact can be "true in the world" at a different time than when "we knew it."

### 2.1 Supersession trace

```
t=1 (Jan 15)  Email: "Acme's annual budget is $5M"
              → Fact created: {budget="$5M", valid_at=2026-01-01, invalid_at=NULL,
                               created_at=2026-01-15, expired_at=NULL}

t=2 (Apr 3)   Email: "Acme increased their budget to $7M"
              → Pipeline detects contradiction via semantic search
              → Old fact: expired_at=2026-04-03, invalid_at=2026-04-01
              → New fact: {budget="$7M", valid_at=2026-04-01, invalid_at=NULL,
                           created_at=2026-04-03, expired_at=NULL}

BOTH facts exist. Nothing was deleted.
```

### 2.2 Four temporal queries (Cypher)

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

### 2.3 Why this matters for AI agents

Without bitemporal, an agent can't distinguish "Alice left Acme in March" from "we learned in June that Alice left in March." When making a decision based on what was known *at the time of a past decision*, the agent must query knowledge state, not current state. This is critical for compliance, audit, decision lineage, and post-incident analysis.

**Bitemporal cannot be retrofitted.** It must be in the schema from day one. This is one of ContextD's hardest-to-replicate moats.

---

## 3. The 10-step ingestion pipeline

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

Each step is wrapped in an OpenTelemetry span. Every element stamped with `source_pipeline`, `source_task`, `extraction_method`, `source_episode_id` — full traceability.

### 3.1 Why these 10 steps

The 10-step shape is deliberate. Each step solves a specific failure mode that simpler RAG-style pipelines do not:

- **Steps 1-2** establish provenance and conversational continuity (every fact traces back to its episode; multi-message context is preserved for the LLM).
- **Steps 3-5** keep entity identity stable across sources (the cascade ensures `john@acme.com`, `John Smith`, and `J. Smith` resolve to the same canonical person — and ~80% of resolutions happen before the LLM is invoked).
- **Steps 6-7** maintain a single source of truth across contradictory facts (supersession is bitemporal: nothing is deleted, both old and new coexist with valid_at / invalid_at / created_at / expired_at semantics).
- **Step 8** powers downstream hybrid retrieval (BM25 + cosine + BFS in one engine).
- **Step 9** delivers ACID write across all primitives — atomic with the embeddings, the indexes, and the audit log.
- **Step 10** produces macro-structure for navigating large graphs (community summaries make 100K-entity graphs tractable for retrieval).

ContextD's contribution is the *integration*: bitemporal-at-schema-level + decision lineage + Context Cores layered on top of an ACID multi-model substrate, with ingestion / ontology / feedback / retrieval all sharing a single transactional engine. See  for prior-art references.

### 3.2 Step-by-step details

**Step 1 — Create Episode**. Wrap raw data in an `EpisodicNode` vertex. Store `content`, `metadata`, `valid_at`, `source`, `episode_type`. This is the source of truth from which everything else is derived.

**Step 2 — Retrieve Context**. Fetch previous N episodes (default 10) in same group/saga. The LLM in step 3 needs conversation history — so when an email says "as I mentioned yesterday," the LLM knows what "yesterday" refers to.

**Step 3 — Extract Nodes**. Send `episode content + previous episodes + optional ontology subset` to LLM. Receive Pydantic-validated `ExtractedEntities`. If ontology active, only ontology-defined types accepted ("Vehicle" dropped if only Person/Organization defined).

**Step 4 — Resolve Entities (Deterministic)**. Three cheap stages before LLM:
- (a) Normalize: lowercase, collapse whitespace, strip punctuation
- (b) Exact match → merge
- (c) Entropy gate: Shannon entropy < 1.5 bits or name length < 6 chars → skip fuzzy (strings like "Q1", "API", "USA" are too short for reliable fuzzy matching)
- (d) 3-gram MinHash with 32 permutations + LSH banding (band size 4)
- (e) Jaccard similarity ≥ 0.9 → merge

**Step 5 — Resolve Entities (Semantic + LLM)**. For unresolved:
- Cosine similarity on name embeddings ≥ 0.6, top 15 candidates
- LLM final yes/no on ambiguous cases (returns `NodeDuplicate(id, name, duplicate_candidate_id)`)
- Type promotion: merge labels from both resolved entities

**Result: ~80% of resolutions handled before LLM is called.** Saves cost and latency.

**Step 6 — Extract Edges**. LLM extracts relationships with temporal annotations. Self-edges dropped. Edges referencing unknown entities filtered. Ontology domain/range enforced if active.

**Step 7 — Resolve/Dedup Edges**. Match new edges against existing ones via hybrid search (`EDGE_HYBRID_SEARCH_RRF`: BM25 + cosine on fact embeddings). LLM identifies:
- **Duplicate facts** → merge into existing (append episode UUID to edge's `episodes` list)
- **Contradicted facts** → supersede (set `invalid_at` and `expired_at` on old; create new)

**Step 8 — Generate Embeddings**. Batch-embed entity names + relationship facts via OpenAI. Store in HNSW with PQ compression.

**Step 9 — Save to Graph**. Bulk write episodes, entities, relationships, episodic edges. Provenance on every element.

**Step 10 — Community Detection** (BUILDING, optional). Run Label Propagation or Louvain on the affected subgraph. LLM bottom-up hierarchical summarization. Create/update `CommunityNode` vertices.

### 3.3 Saga tracking

```
A. Create or fetch Saga       — by name; or fetch existing
B. Link Episode to Saga       — HAS_EPISODE edge
C. Chain Temporally           — NEXT_EPISODE edge from previous → new
D. Update Summary             — LLM(existing_summary + new_episode) → updated_summary
                                streaming, never re-read history
```

### 3.4 BDD-style behavioral specs (representative)

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

## 4. Context Resolver — cross-source identity stitching

> Entity resolution at ContextD is productized as a discrete architectural module: **Context Resolver**. Two paths, sharing one Identity Graph artifact:
>
> - **Structured sources with stable unique IDs** (Snowflake `customer_id`, Salesforce `Id`, Stripe `cus_*`, GitHub `node_id`) — deterministic join via the Forge Mapping. Same source-ID always resolves to the same `canonical_id`. No probabilistic work.
> - **Heterogeneous, unstructured, no-shared-ID sources** — the same person appearing as `alice.chen@acme.com` (Gmail), `U023BECGF` (Slack), `requester_id=3478291` (Zendesk), `a-chen` (GitHub), `ldap:achen` (Confluence), and a free-text mention *"as Alice mentioned yesterday..."* — runs the six-stage Resolver Engine pipeline.
>
> This section summarizes the techniques. **The full module — components, Identity Graph schema, Resolver Studio review surface, Resolver Profiles, Resolver-to-Pipeline Bridge, performance targets, roadmap, moat analysis — lives in `07-context-resolver.md`.**

The six-stage pipeline (cost-cascading, advanced techniques only — no fuzzy-string heuristics as primary signals):

| Stage | Technique | Reference |
|-------|-----------|-----------|
| **A — Blocking** | HNSW vector ANN + DeepBlocker learned blocking + 3-gram MinHash/LSH; reduces O(N²) → O(N log N) | Malkov & Yashunin 2018; Thirumuruganathan VLDB 2021; Indyk & Motwani 1998 |
| **B — Probabilistic record linkage** | Fellegi-Sunter framework; per-attribute m-probability + u-probability; match weight = log₂(m/u); EM-learned parameters; Platt-scaled / isotonic-calibrated thresholds | Fellegi & Sunter 1969; Winkler 1988; Splink-style implementation |
| **C — Neural pairwise matching** | DITTO-style cross-encoder (RoBERTa / DeBERTa-v3 base, ~110M params); supervised contrastive + triplet loss training; > 95% F1 on Magellan benchmark suite; ~5K pairs/sec on GPU | Li et al. VLDB 2020 |
| **D — Coreference resolution for unstructured text** | NER via GLiNER (zero-shot) + RoBERTa-NER (fine-tuned); within-document coreference via end-to-end neural coref (e2e-coref / MaverickCoref / SpanBERT-coref); Cross-Document Coreference Resolution (CDCR) for mention alignment across documents | Lee et al. 2017; MaverickCoref 2024; Cattan et al. 2021; CDLM 2021 |
| **E — Identity Graph stitching** | Confidence-weighted edges (`source`, `source_id`, `canonical_id`, `confidence`, `evidence`) on a bitemporal graph; **Probabilistic Soft Logic (PSL)** for transitive closure with confidence multiplication; conflict detection raises non-match violations; soft-link mode retains low-confidence stitches as candidate edges | Bach et al. JMLR 2017 |
| **F — Active learning + LLM adjudication** | Uncertainty sampling surfaces near-threshold matches to Resolver Studio's review queue; query-by-committee variant; cross-encoder fine-tune loop; LLM final adjudication via few-shot / chain-of-thought for residual ~1-2% | Settles 2009; AnyMatch / MatchGPT 2024 |

The output is a queryable, bitemporal **Identity Graph**: every canonical entity carries an array of `(source, source_id, confidence, evidence)` identifier links, an attribute-consensus block, and a complete audit trail. When a customer's email changes after a re-org, the new identifier supersedes the old without losing the historical link — auditors can reconstruct who-was-stitched-to-whom at any past date.

**For details** — components (Resolver Engine, Identity Graph, Resolver Studio, Resolver Profiles, Resolver-to-Pipeline Bridge), Identity Graph schema, performance targets at 100M-entity scale, customer onboarding flow, in-scope vs deferred scope, and the common technical questions — see `07-context-resolver.md`.

---

## 5. The ontology engine

The ontology is **optional**. Without it, LLM-only extraction works. With it, you get fewer hallucinated types, consistent naming, and enforceable rules.

### 5.1 Decision guide

| Situation | Recommendation |
|-----------|----------------|
| Prototyping or < 10K entities | Skip — LLM-only works |
| Single data source (e.g., just Gmail) | Probably skip |
| Multiple sources with overlapping types | Use it (Salesforce "Account" ≠ Gmail "Company") |
| Regulated domain (finance, healthcare) | Use it (audit trail) |
| Consistent extraction across teams | Use it (shared schema contract) |

### 5.2 Schema (OWL-like JSON)

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

### 5.3 Four-step semantic routing

1. **Embed ontology** — every class and property → vector embedding (combining identifier + label + comment).
2. **Select subset per chunk** — vector-match against ontology embeddings (threshold 0.3, top-k 10) + dependency resolution (parent classes via `subclass_of`, domain/range types).
3. **Inject into LLM prompt** — relevant subset serialized into extraction prompt via Jinja2 templates.
4. **Validate output** — class filtering, domain/range, cardinality, disjoint classes.

### 5.4 Validation rules

| Rule | Enforces | Example |
|------|----------|---------|
| Class filtering | Only ontology-defined types | "Vehicle" dropped if only Person/Organization defined |
| Domain/range | Relationships connect valid types | "works_at" must go Person → Organization (not reverse) |
| Cardinality | Functional props max 1 value | `ceo_of` functional → one company per person |
| Disjoint classes | Entity can't span conflicts | Person ≠ Organization |

**Pre-built ontologies shipping:** CRM, Support, Engineering, Marketing.

---

## 6. Hybrid retrieval

When an AI agent queries ContextD, three search methods run **in parallel**, then results are merged by a reranker.

### 6.1 Three search methods

| Method | How | Strong at | Misses |
|--------|-----|-----------|--------|
| **BM25** | Lucene keyword search inside substrate | Exact terms, names, IDs, jargon | Paraphrases, synonyms |
| **Cosine** | HNSW nearest-neighbor via vector index | Semantic meaning, paraphrases | Exact names, IDs |
| **BFS** | Breadth-first graph traversal from seed entities | Structural relationships | Entities not connected to seeds |

Why all three: vector search alone misses exact-term queries ("JIRA-1234" returns semantically-similar-but-wrong tickets). BM25 alone misses paraphrases. Graph alone misses semantic neighbors. Hybrid retrieval is the only complete answer.

### 6.2 Five reranking strategies

| Reranker | Logic | Best for |
|----------|-------|----------|
| **RRF** (default) | `score(d) = Σ 1/(k + rank_i(d))`, k=60 | General purpose — balanced across all methods |
| **MMR** | Balances relevance vs diversity (λ=0.7) | Variety, no 10 similar results |
| **Cross-Encoder** | Neural reranking via BGE / OpenAI / Gemini | Maximum accuracy when latency OK |
| **Node Distance** | Closer in graph hops scores higher | Relationship queries ("who works with Alice?") |
| **Episode Mentions** | More/recent episode mentions score higher | Recency queries ("what's new with Acme?") |

3 methods × 5 rerankers = **15 composable strategies**. Plus pre-built recipes (`COMBINED_HYBRID_SEARCH_RRF`, `EDGE_HYBRID_SEARCH_RRF`, `NODE_HYBRID_SEARCH_RRF`).

### 6.3 Why RRF as the default

Scores from BM25, cosine, and BFS live on different scales (BM25: 0-20, cosine: 0-1, BFS: 0-1). Naive averaging skews toward whichever method has the largest range. RRF uses *rank positions* instead — scale-independent. The k=60 constant is the well-tested default from Cormack et al. 2009.

### 6.4 Query flow

```
Natural Language Query
   │
   ▼
[1. Parse Intent] → entity refs, relationship hints, temporal scope, filters
   │
   ├──[BM25 Search]──┐
   ├──[Cosine Search]┤   (parallel via asyncio.gather)
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

### 6.5 Feedback scoring

```
final_score = reranker_score × feedback_weight

Cold start (no feedback yet):
  All weights = 0.5  →  final = reranker × 0.5  (neutral, pure relevance ordering)

After 30 positive interactions:
  Entity A: reranker=0.92, feedback=0.87 → final = 0.80
  Entity B: reranker=0.85, feedback=0.95 → final = 0.8075   ← outranks A
                                              despite lower
                                              initial relevance
```

---

## 7. The 7-step context assembly algorithm

This is the heart of the value proposition.

1. **Parse Intent** — decompose NL query into entity references, relationship type hints, temporal constraints, search filters. Identify seed entities for BFS.
2. **Seed Entity Selection** — BM25 + cosine identify primary entities → BFS starting points.
3. **Hybrid Parallel Search** — BM25 + cosine + BFS simultaneously via `asyncio.gather`.
4. **Rerank & Merge** — dedup by UUID, apply reranker.
5. **Apply Feedback Weights** — `final = reranker × feedback_weight`.
6. **Budget-Aware Temporal Pruning** — fill `max_tokens` in priority order:
   1. Primary entities (always)
   2. Direct relationships between primary entities (current only)
   3. Relevant facts (current-state temporal filter)
   4. Saga summaries
   5. Decision lineage (if `include_lineage=True`)
   Stop when budget exhausted.
7. **Serialize & Package** — structured JSON.

### 7.1 Output JSON

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

### 7.2 Why ~80% [TARGET] fewer tokens than chunk-based RAG

Chunk-based RAG retrieves top-k similar chunks (k=10-20, each ~200-400 tokens) → ~3,400 tokens with massive redundancy. An entity mentioned in 5 chunks appears 5 times.

ContextD retrieves **specific entities, relationships, facts** — structured (entity appears once), temporally filtered (only current facts), feedback-weighted (only proven-useful elements). Target ~800-1,000 tokens for equivalent coverage.

The reduction is workload-dependent — early queries without feedback see smaller reductions; well-trained graphs with months of feedback approach the target.

**How the reduction works mechanically:** deduplication (entity in 5 chunks → 1 record), temporal pruning (superseded facts dropped), feedback pruning (low-weight elements excluded). Relationships and temporal context also reduce hallucination from stale data.

---

## 8. The feedback system — streaming EMA learning

The graph gets smarter with every interaction.

### 8.1 The math

```python
# Step 1: Normalize 1-5 rating to 0.0-1.0
normalized = (score - 1) / 4    # 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0

# Step 2: EMA update (alpha = 0.1)
updated_weight = previous_weight + 0.1 * (normalized - previous_weight)

# Step 3: Clamp + round
updated_weight = round(clamp(updated_weight, 0.0, 1.0), 4)
```

### 8.2 Why α=0.1

Small enough to be stable (no single rating swings the weight from 0.5 to 1.0). Large enough to adapt within ~30 interactions. Higher α (e.g., 0.3) makes recent feedback dominate — risk of oscillation. Lower α (e.g., 0.01) means the system never learns. 0.1 is the sweet spot validated by our empirical tuning across multiple workloads.

### 8.3 Worked example

```
Entity: "Acme Support Tickets"

Week 1 (no feedback):     weight = 0.50  (neutral)
                          Query → reranker=0.90 × 0.50 = 0.45

Week 1 (5/5):             0.50 + 0.1 × (1.0 - 0.50) = 0.55
Week 2 (4/5, 5/5):        0.55 → 0.57 → 0.613
Week 3 (5/5):             0.652
... after 30 positive rounds: ≈ 0.92

Week 4:                   reranker=0.90 × 0.92 = 0.828   ← RANKS HIGH

Compare "Acme Marketing Campaign" (30 rounds at avg 2/5):
weight: 0.50 → 0.31  →  reranker=0.85 × 0.31 = 0.264   ← DEMOTED

The graph learned: support agents need ticket data, not marketing data.
```

### 8.4 What gets weighted

| Element | Field | Impact |
|---------|-------|--------|
| Entity nodes | `feedback_weight` | Entities in highly-rated responses rank higher |
| Relationship edges | `feedback_weight` | Relationships used in good context rank higher |
| Facts | `feedback_weight` | Facts leading to accurate responses rank higher |

### 8.5 Design properties

- **Cold-start safe.** Everything starts at 0.5. System works perfectly without feedback.
- **Purely additive.** Feedback only improves results — never makes them worse than "no feedback."
- **Idempotent.** Duplicate submissions detected via `memify_metadata` flag and skipped.
- **Auditable.** All feedback events logged with timestamps, session IDs, user IDs.

### 8.6 Auto-feedback detection

Beyond explicit 1-5 ratings, the roadmap includes LLM-based analysis of conversation turns for implicit feedback: "that was exactly what I needed" (positive), "no, that's wrong" (negative), "actually the revenue was $50M not $30M" (correction → supersede fact). Continuous learning signal without explicit ratings.

---

## 9. Context Cores — CI/CD for context

Versioned, portable, content-addressed snapshots of entire graph + embeddings + ontology + retrieval policies + feedback weights.

### 9.1 Lifecycle

```
BUILD ──► TEST ──► VERSION ──► PROMOTE ──► PRODUCTION
                                              ▲
                                          ROLLBACK
```

### 9.2 Core contents

| Component | What it contains |
|-----------|------------------|
| Graph data | All entities, relationships, facts, decisions |
| Embeddings | Entity name + relationship fact vectors |
| Ontology | Schema that constrained extraction |
| Source manifests | Which episodes/connectors contributed, timestamps |
| Retrieval policies | Search recipe configs |
| Feedback weights | All learned relevance scores |
| Metadata | SHA-256 content hash, build timestamp, builder identity |

### 9.3 Operations

```bash
# Build snapshot
contextd core build --name "customer-context" --graph "production"
# → acme-context:v5 (12.4 MB, 57s, sha256:a4f8e2c91d3b7...)

# Test against golden query suite
contextd core test --core "customer-context:v5" --queries "test-suite.yaml"
# → 50/50 pass | avg latency 42ms | avg tokens 1,420

# Diff
contextd core diff --from "customer-context:v4" --to "customer-context:v5"
# → +147 entities, +389 edges, +412 facts, latency -7%

# Promote
contextd core promote --core "customer-context:v5" --target "production"

# Rollback (instant — just swap pointer)
contextd core rollback --target "production" --to "customer-context:v4"
```

### 9.4 Serialization choice

**msgpack** + content-addressed SHA-256:
- 30-50% smaller than JSON
- 2-10× faster to serialize/deserialize
- For a 10M-entity graph, the difference is GB of storage and minutes of build time
- SHA-256 of packed bytes ensures immutability — any change produces a different hash, prevents accidental clobbering

### 9.5 Why content-addressed (not incremental diffs)?

Each core is a complete, self-contained snapshot. Trade-off: larger storage per version. Benefit:
1. Any core can be loaded independently (no dependency chain)
2. Diffing is straightforward (compare two complete snapshots)
3. Rollback is instant (swap pointer, no undo operations)

For a 10M-entity graph, msgpack compression makes the per-version cost manageable. We prioritize simplicity and reliability of rollback over storage efficiency.

### 9.6 Why this is hard to replicate

Versioning a graph database is hard because:
- The graph + embeddings + indexes + feedback weights are entangled
- Incremental diffs over a live graph create consistency nightmares
- Content addressing requires deterministic serialization order

ContextD solves this at the schema level (everything tied to versionable canonical IDs) and the substrate level (ACID transactions across all data models means snapshots are consistent by construction). Bolting Context Cores onto Neo4j or Pinecone after the fact is impractical.

---

## 10. Tech stack reference

### 10.1 The intelligence layer (what ContextD builds)

| Component | Tech | License | Why |
|-----------|------|---------|-----|
| **Entity Resolution** | Custom | MIT | 5-phase cascade |
| **Ontology Engine** | Custom | Apache 2.0 | Active extraction constraint |
| **Feedback Engine** | Custom | Apache 2.0 | Streaming EMA, idempotent |
| **API Server** | FastAPI | MIT | Async, OpenAPI |
| **MCP Server** | Custom (multi-transport) | MIT | stdio/SSE/HTTP |
| **Observability** | OpenTelemetry + Prometheus | Apache 2.0 | NullSpan fallback |
| **Connectors** | Airbyte + Custom SDK | Apache 2.0 | 600+ via Airbyte + 6 P0 |
| **LLM Providers** | OpenAI + Anthropic + extensible | — | Structured output via function calling |

### 10.2 The substrate (what we don't rebuild)

| Component | Tech | License | Why |
|-----------|------|---------|-----|
| **Unified Storage** | ArcadeDB | Apache 2.0 | Only multi-model DB doing graph + vector + full-text + doc + KV + time-series in one ACID engine |
| **Vector Search** | LSMVector (jvector HNSW) + PQ | Apache 2.0 | Native; no external vector DB needed |
| **Full-Text** | Lucene BM25 | Apache 2.0 | Native to substrate |
| **Graph Algorithms** | Substrate-native (70+ SIMD) | Apache 2.0 | Java 21 Vector API, no ETL |

---

*Continue to `09-benchmarks-and-validation.md` for measured performance, or `10-roadmap-and-build-plan.md` for the migration timeline.*
