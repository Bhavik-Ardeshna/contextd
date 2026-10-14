# 07 — Context Resolver: Cross-Source Identity Stitching

> **What this file is.** The deep-dive on Context Resolver — the architectural block that turns raw, multi-source records into canonical entities. Context Resolver is **how the same person, company, or asset is reliably stitched together when it appears across Snowflake, Salesforce, Gmail, Slack, GitHub, Zendesk, Confluence, and free-text mentions, with no shared unique ID.**
>
> **Why this matters.** Cross-source unification is the single most claim-heavy promise enterprise data platforms make and the single most common place they fail. Without a productized resolution module, every cross-source query is a forensic exercise. Context Resolver makes cross-source identity a first-class, queryable, auditable artifact of the platform.
>
> **One-line summary.** Context Resolver consumes records from every connected source, runs a six-stage probabilistic pipeline grounded in well-established information-retrieval and modern neural techniques, and emits a bitemporal **Identity Graph** that maps every source-record-ID to a `canonical_id` with confidence scores, evidence traces, and audit-traceable resolution events.

---

## Why Context Resolver exists

There are two completely different identity-resolution problems hiding inside what enterprise vendors call "entity resolution":

### Problem A — structured-with-stable-IDs: trivial

Snowflake `customer_id`, Salesforce `Id`, Stripe `cus_*`, GitHub `node_id`, HubSpot object IDs. The same source-ID always refers to the same entity. **This is a deterministic join.** Context Forge handles it as a configuration-time decision (the Forge Mapping declares which column is the natural key). No probabilistic work needed. No Resolver invocation needed.

### Problem B — heterogeneous / unstructured / no-shared-ID: hard

The same person:

```
Salesforce      contact_id = 003GA0000045X9z       (clean ID)
Gmail           From: alice.chen@acme.com           (email header — no link to salesforce)
Slack           user_id = U023BECGF, display="@alice"
Zendesk         requester_id = 3478291              (different ID)
GitHub          author = "a-chen", email = a.chen@acme.com
Confluence      author_key = ldap:achen, "Alice C." in body text
Free text       email body: "...as Alice mentioned yesterday..."
```

Same person — **zero shared identifier across these seven appearances.** A naive system creates seven different entities. A "fuzzy-string-matching" system creates four entities and merges three of them incorrectly. **A correct system runs probabilistic record linkage, neural pairwise matching, cross-document coreference, and constraint-propagation logic to converge on one canonical entity, with audit-traceable confidence per stitch.**

Context Resolver is the productized solution to Problem B. It is invoked by every ingestion event, runs continuously, and maintains the Identity Graph as a persistent artifact in the substrate.

---

## Two paths

| Source profile | Path | Mechanism | Where it lives |
|----------------|------|-----------|----------------|
| Structured-with-stable-ID (warehouse PKs/FKs, SaaS object IDs) | **Deterministic** | Context Forge FK graph + source-record-ID equality | Resolved at ingestion via Forge Mapping configuration |
| Heterogeneous / unstructured / no shared ID | **Probabilistic** | Context Resolver — six-stage pipeline | Lives as a discrete module in Layer 3 of the architecture |

The two paths feed the same Identity Graph artifact. A single canonical entity may have a deterministic edge from Salesforce (confidence 1.0) and a probabilistic edge from a Slack mention (confidence 0.91) coexisting on the same `canonical_id`.

---

## Module architecture

Context Resolver is one of ContextD's discrete architectural blocks, sitting alongside Context Forge and Context Cores in Layer 3 (the intelligence layer). Five components:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CONTEXT RESOLVER                                                        │
│                                                                          │
│   1. Resolver Engine        — six-stage probabilistic pipeline           │
│      (the runtime that processes every ingestion event + batch jobs)     │
│                                                                          │
│   2. Identity Graph         — the persistent artifact                    │
│      (stored in substrate; bitemporal; queryable via Cypher / SQL / MCP) │
│                                                                          │
│   3. Resolver Studio        — review surface                             │
│      (active-learning queue + identity-graph explorer + conflict review) │
│                                                                          │
│   4. Resolver Profiles      — pre-tuned matching configurations          │
│      (Person / Organization / Account / Device / Asset entity types,     │
│       with domain-fine-tuned cross-encoder weights)                      │
│                                                                          │
│   5. Resolver-to-Pipeline Bridge                                         │
│      (the integration point with the 10-step ingestion pipeline)         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Component 1 — Resolver Engine

The Resolver Engine is a streaming pipeline that processes every entity-extraction event the ingestion pipeline emits. Six stages, ordered by cost:

```
                Heterogeneous record  +  source provenance
                                  │
                                  ▼
   ┌──────────────────────── Stage A — Blocking ─────────────────────────┐
   │  Reduce O(N²) candidate space to O(N log N) before any pairwise     │
   │  comparison runs.                                                    │
   │                                                                      │
   │   ─ HNSW vector ANN over entity-embedding space (substrate-native    │
   │     LSMVector index)                                                 │
   │   ─ DeepBlocker-style learned blocking on tabular attributes         │
   │     (Thirumuruganathan et al. VLDB 2021)                             │
   │   ─ 3-gram MinHash + LSH on textual fields via `datasketch`          │
   │   ─ q-gram blocking + sorted-neighborhood for high-volume streams    │
   │                                                                      │
   │  Output: top-k candidates per record (typically k = 50)              │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage B — Probabilistic record linkage ─────┐
   │  Fellegi-Sunter framework — the academic gold standard for ER.       │
   │                                                                      │
   │   ─ Per-attribute m-probability  P(agree | match)                    │
   │     and u-probability            P(agree | non-match)                │
   │   ─ Match weight = log₂(m / u)                                       │
   │   ─ EM (Expectation-Maximization) learns m, u from unlabeled data    │
   │     per source domain (Winkler 1988 algorithm)                       │
   │   ─ Aggregate match weight across attributes (email, phone, name,    │
   │     domain, employer, geographic prior, behavioral signals)          │
   │   ─ Calibrated thresholds via Platt scaling / isotonic regression    │
   │   ─ Implementation: extends the open-source Splink approach with     │
   │     ContextD's schema and bitemporal annotations                     │
   │                                                                      │
   │  Output: pairs above match threshold; rest pass to Stage C only if   │
   │  scoring is uncertain                                                │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage C — Neural pairwise matching ─────────┐
   │  Cross-encoder transformer architecture (DITTO-family).              │
   │                                                                      │
   │   ─ Serializes a record-pair into a single sequence:                 │
   │     "[CLS] <record A attrs> [SEP] <record B attrs> [SEP]"            │
   │   ─ RoBERTa-base or DeBERTa-v3-base; ~110M parameters                │
   │   ─ Fine-tuned per entity-type via Resolver Profiles                 │
   │   ─ Training objective: supervised contrastive loss + triplet        │
   │     margin loss                                                      │
   │   ─ Reaches > 95% F1 on standard ER benchmarks (Walmart-Amazon,      │
   │     DBLP-ACM, Magellan suite)                                        │
   │   ─ Bi-encoder fast-path for high-volume streams (sentence-          │
   │     transformer-style); cross-encoder reserved for ambiguous         │
   │     candidates                                                       │
   │   ─ Batched on GPU; ~5,000 pairs/sec sustained                       │
   │                                                                      │
   │  Reference: Li et al. VLDB 2020 (DITTO); SOTA on Magellan benchmarks │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage D — Coreference for unstructured text ┐
   │  When the entity appears as a free-text mention (email body, Slack   │
   │  thread, ticket description, Confluence doc), traditional ER doesn't │
   │  apply — there's no record. We run a coreference stack:              │
   │                                                                      │
   │   ─ NER via transformer:                                             │
   │       • GLiNER (zero-shot for novel entity types in custom domains)  │
   │       • RoBERTa-NER (high-precision, fine-tuned per business domain) │
   │   ─ Within-document coreference: end-to-end neural coref             │
   │     (e2e-coref / SpanBERT-coref / MaverickCoref 2024)                │
   │   ─ Cross-Document Coreference Resolution (CDCR): aligns mentions    │
   │     across documents using contextualized mention embeddings         │
   │     (Cattan et al. 2021; Caciularu et al. CDLM 2021)                 │
   │   ─ Mention-to-canonical linking: each cluster head is matched       │
   │     against the existing Identity Graph via Stages B/C               │
   │                                                                      │
   │  Output: mention clusters → linked to canonical_ids                  │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage E — Identity Graph stitching ─────────┐
   │  Persist the result.                                                 │
   │                                                                      │
   │   ─ Each canonical_id is a vertex; each source-record-ID links via   │
   │     a confidence-weighted edge with provenance                       │
   │   ─ Probabilistic Soft Logic (PSL) — Bach et al. JMLR 2017 — for     │
   │     transitive closure with confidence multiplication:               │
   │       A↔B (0.95) + B↔C (0.92) ⇒ A↔C (0.87)                           │
   │   ─ Conflict detection: contradictory non-match constraints          │
   │     (e.g., two contacts with the same email at different employers)  │
   │     raise to the active-learning queue rather than silent merge      │
   │   ─ Soft-link mode: low-confidence stitches retained as candidate    │
   │     edges (`canonical_id` + `candidate_canonical_id`), not hard      │
   │     merges, until corroborating evidence arrives                     │
   │   ─ Bitemporal annotations on every edge: valid_at / invalid_at +    │
   │     created_at / expired_at (consistent with §2 of core technology)  │
   └──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────── Stage F — Active learning + LLM adjudication┐
   │  Residual hard cases — typically 5-10% of candidates near the        │
   │  decision threshold, plus ~1-2% of structurally ambiguous records.   │
   │                                                                      │
   │   ─ Uncertainty sampling surfaces near-threshold matches             │
   │     (Settles 2009; query-by-committee variant — Seung et al. 1992)   │
   │   ─ Two routes from there:                                           │
   │       (a) Human label via Resolver Studio review queue → cross-      │
   │           encoder fine-tune loop. Labels feed back into Stage C      │
   │           training data per-entity-type.                             │
   │       (b) LLM final adjudication via few-shot or chain-of-thought    │
   │           pairwise prompting. Reserved for the hardest 1-2%.         │
   │           Reference: AnyMatch, MatchGPT, "Can LLMs Solve Entity      │
   │           Matching?" 2024                                            │
   └──────────────────────────────────────────────────────────────────────┘
```

### What we explicitly avoid

- **String-distance heuristics as primary signals** (Levenshtein, Jaro-Winkler, edit distance). These are famously brittle on real enterprise data — typos in source X don't predict typos in source Y. They're fine as auxiliary features inside the cross-encoder; they are not the system.
- **Graph-only ER without coreference for unstructured text.** Most graph-DB-with-ER bolt-ons can stitch records but not mentions. ~30% of enterprise entity references live in free text; ignoring them caps cross-source coverage.
- **One-shot LLM extraction.** LLM-based ER alone is too expensive at scale and produces inconsistent results without fine-tuning. The Resolver uses LLMs only at Stage F as the residual adjudicator.

---

## Component 2 — The Identity Graph (the artifact)

The Resolver Engine's persistent output. Lives in the substrate. Queryable via Cypher, SQL, or MCP.

### Vertex shape

Every canonical entity carries an array of source identifiers + a reconciled attribute view + a complete audit trail.

```yaml
canonical_id: 1f8e4a2c-9b3d-4f7c-aaf1-2e8d6c5b9a0f
canonical_type: customer
identifiers:
  - source: salesforce
    source_id: "003GA0000045X9z"
    confidence: 1.00
    evidence: deterministic_pk
    valid_at: 2025-06-15T09:14:00Z
    invalid_at: null
  - source: gmail
    source_id: "alice.chen@acme.com"
    confidence: 0.99
    evidence: email_exact + domain_match (Stage B)
    valid_at: 2025-06-15T09:14:00Z
    invalid_at: null
  - source: slack
    source_id: "U023BECGF"
    confidence: 0.94
    evidence: cross_encoder + display_name + workspace_email_match (Stage C)
    valid_at: 2025-08-22T10:00:00Z
    invalid_at: null
  - source: zendesk
    source_id: "3478291"
    confidence: 0.91
    evidence: fellegi_sunter (0.87) + LLM_adjudication (Stage F)
    valid_at: 2025-09-04T14:30:00Z
    invalid_at: null
  - source: github
    source_id: "a-chen"
    confidence: 0.88
    evidence: email_match + commit_metadata
    valid_at: 2025-10-01T08:00:00Z
    invalid_at: null
  - source: confluence
    source_id: "ldap:achen"
    confidence: 0.97
    evidence: ldap_directory + author_resolution
    valid_at: 2025-06-15T09:14:00Z
    invalid_at: null
  - source: gmail_mention   # free-text mention from Stage D
    source_id: "msg_45fe22:span_178"
    confidence: 0.86
    evidence: cdcr_mention_cluster + stage_c_match
    valid_at: 2026-04-15T14:30:00Z
    invalid_at: null

attribute_consensus:
  name:           { value: "Alice Chen",        provenance: salesforce,  confidence: 1.00 }
  email_primary:  { value: "alice.chen@acme.com", provenance: salesforce,  confidence: 1.00 }
  title_current:  { value: "VP of Engineering", provenance: confluence,  confidence: 0.97, valid_at: 2025-06-15 }
  employer:       { value: "Acme Corp",         provenance: salesforce,  confidence: 1.00 }

audit_trail:
  - 2025-06-15T09:14:00Z  CREATE  canonical_id  evidence: salesforce_ingest
  - 2025-06-15T09:14:01Z  STITCH  gmail+confluence  evidence: deterministic_email_match
  - 2025-08-22T10:00:00Z  STITCH  slack             evidence: cross_encoder 0.94
  - 2025-09-04T14:30:00Z  STITCH  zendesk           evidence: stage_F LLM adjudication
  - 2025-10-01T08:00:00Z  STITCH  github            evidence: email_match
  - 2026-04-15T14:30:00Z  STITCH  gmail_mention     evidence: cdcr_cluster
```

### Bitemporal semantics

Every identifier link is bitemporal. When a customer's email changes after a re-org:

```
Old identifier (gmail / alice.chen@acme.com)
  → valid_at:    2025-06-15
  → invalid_at:  2026-07-01    (when she actually changed it in the world)
  → expired_at:  2026-07-03    (when we picked up the change)

New identifier (gmail / alice.chen@newco.com)
  → valid_at:    2026-07-01
  → invalid_at:  null
  → created_at:  2026-07-03
```

Both edges coexist on the canonical_id. Auditors can reconstruct who-was-stitched-to-whom at any past date.

### Queryability

The Identity Graph is queryable like any other entity in ContextD:

```cypher
-- All canonical entities matched to a Slack ID
MATCH (e:Entity)-[:HAS_IDENTIFIER]->(id:Identifier {source: "slack"})
WHERE id.source_id = "U023BECGF"
RETURN e

-- Audit: which sources contributed identifiers for this canonical entity
-- and at what confidence?
MATCH (e:Entity {canonical_id: "1f8e4a2c-..."})-[:HAS_IDENTIFIER]->(id)
RETURN id.source, id.confidence, id.evidence, id.valid_at
ORDER BY id.confidence DESC

-- Which canonical entities have low-confidence stitches (review candidates)?
MATCH (e:Entity)-[:HAS_IDENTIFIER]->(id)
WHERE id.confidence < 0.85 AND id.confidence > 0.65
RETURN e.canonical_id, count(id) AS weak_links
ORDER BY weak_links DESC
```

---

## Component 3 — Resolver Studio

A review surface for the cases the Resolver Engine cannot decide automatically. Mirrors Forge Studio's role for the Resolver's responsibilities.

### Three queues

1. **Active-learning queue.** Pairs flagged at Stage F via uncertainty sampling. Reviewer sees both records side-by-side with their attribute alignment, the cross-encoder's confidence, and Stage B's Fellegi-Sunter score breakdown per attribute. Two clicks: *match* / *no match*. Labels feed the Stage C fine-tune loop.

2. **Conflict queue.** PSL constraint violations from Stage E. Example: two records claim to be the same person but have non-overlapping employment histories within the same period (a soft non-match constraint). Reviewer adjudicates and the resolution becomes a constraint that propagates.

3. **Identity-graph explorer.** Navigate canonical entities, see their identifier list, drill into any single edge for evidence trace, query by source-id or canonical-id, view the bitemporal change history of any identifier link.

### Bulk operations

- *"Reject all stitches with confidence < 0.7 from source X."* — useful when a particular source has known data-quality issues.
- *"Re-run Stage C with the latest fine-tuned model."* — after a labeling round.
- *"Lock this canonical entity"* — prevent automatic merges into it (used for VIPs, high-stakes accounts, edge-case identities).

---

## Component 4 — Resolver Profiles

Pre-tuned matching configurations per entity type. Each profile bundles:

- A **fine-tuned cross-encoder model** for Stage C (different attention patterns matter for matching people vs companies vs assets vs IP addresses)
- A **Fellegi-Sunter attribute schema** for Stage B (which attributes carry signal for this entity type, and the m/u prior priors)
- A **NER model selection** for Stage D (GLiNER zero-shot, RoBERTa-NER fine-tuned, custom domain extractor)
- A **decision threshold** calibrated per profile

| Profile | Best for | Includes |
|---------|----------|----------|
| **person-crm** | Customer / contact / lead unification | Cross-encoder fine-tuned on customer-record pairs; FS schema with email + phone + name + employer + role; CDCR for free-text mentions |
| **person-engineering** | Developers / engineering contributors | Fine-tuned on commit metadata + handle patterns + email + LDAP key; emphasis on author identity reconciliation across GitHub / GitLab / Bitbucket / IDE telemetry |
| **organization-account** | Companies / accounts / business entities | Fine-tuned on company records; FS schema includes domain + parent / subsidiary signals + DUNS + industry codes; high domain-match weighting |
| **deal-opportunity** | Sales opportunities across CRM + email + Slack threads | Cross-encoder tuned for deal-stage transitions; CDCR for opportunity mentions in unstructured threads |
| **device-asset** | Devices / endpoints / assets in IT / telemetry contexts | Different attribute set entirely (MAC, IP, device fingerprint, agent ID); higher tolerance for transient identifiers |
| **product-sku** | Product-catalog entities | Standard ER (Magellan-style), high-volume short-attribute matching |

Customers can clone and customize profiles. Customizations are versioned (msgpack + SHA-256, same machinery as Forge Mappings and Context Cores).

---

## Component 5 — Resolver-to-Pipeline Bridge

The integration point with the 10-step ingestion pipeline.

### What the Bridge does

- **Read Forge Mapping** to determine which records are deterministic (skip Resolver) vs probabilistic (invoke Resolver).
- **Invoke the Resolver Engine** at pipeline Steps 4-5 (entity resolution) and Step 7 (edge resolution / dedup).
- **Update the Identity Graph** atomically with the rest of the entity write at Step 9.
- **Surface Resolver Studio queues** alongside Forge Studio review queues — the customer's data team has one unified review surface for both schema-mapping decisions and identity-resolution decisions.

### Behavior on the pipeline path

```
Step 3 (Extract Nodes) emits a candidate entity
                         │
            Forge Mapping says: structured-with-stable-ID?
                         │
              ┌──────────┴──────────┐
              │                     │
            yes                    no
              │                     │
              ▼                     ▼
   Deterministic merge       Resolver Engine
   to canonical_id via       Stages A-F (skipping
   source-record-ID equality stages already satisfied)
              │                     │
              └──────────┬──────────┘
                         │
                         ▼
         Step 4-5 produce canonical_id + confidence
                         │
                         ▼
         Identity Graph updated atomically
         alongside entity insert (Step 9)
```

---

## Performance & scale

| Operation | Target | Mechanism |
|-----------|--------|-----------|
| Block O(N²) → O(N log N) | < 10 ms per record at 100M-vector index | HNSW + LSH parallel blocking |
| Pairwise match (Stage C) | ~ 5,000 pairs/sec on a single GPU | Cross-encoder batched inference |
| Coreference resolution (Stage D) | ~ 1,000 documents/sec on a single GPU | Mention extraction + within-doc coref + CDCR pipeline |
| End-to-end resolution (Stages A-E) | ~ 50,000 entities/sec at steady state | Streaming pipeline, async stages |
| Active-learning loop turnaround | < 24 h surface-to-fine-tuned-model-applied | Studio review queue + nightly fine-tune |
| Identity Graph reconciliation | Bitemporal-consistent merges, no orphan records | PSL transitive closure + supersession rules |

---

## Where Context Resolver sits in the architecture

Context Resolver lives in **Layer 3 (the ContextD Engine)**, alongside the 10-step ingestion pipeline, the 7-step context assembly algorithm, the Feedback Engine, the Ontology Engine, and Context Cores. It is invoked by every ingestion event and runs continuously:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: CONTEXTD ENGINE                                                 │
│                                                                          │
│   10-step ingestion pipeline · 7-step context assembly · Hybrid query    │
│   Feedback Engine · Ontology Engine · Context Cores                      │
│                                                                          │
│   ┌────────────────────── CONTEXT RESOLVER ──────────────────────┐       │
│   │  Resolver Engine · Identity Graph · Resolver Studio          │       │
│   │  Resolver Profiles · Resolver-to-Pipeline Bridge             │       │
│   └──────────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
```

It complements **Context Forge** (Layer 1.5):

| | Context Forge | Context Resolver |
|---|---------------|------------------|
| **Lifecycle** | Once per source-onboarding (then incremental on schema change) | Per-ingestion-event, continuously |
| **Output artifact** | Forge Mapping (schema → primitives configuration) | Identity Graph (canonical entities ↔ source IDs) |
| **Customer surface** | Forge Studio (mapping review + edit) | Resolver Studio (active learning + identity exploration) |
| **Determinism** | Configures deterministic extraction | Runs probabilistic stitching for non-deterministic cases |
| **Versioning** | msgpack + SHA-256 | msgpack + SHA-256 (same machinery) |

A Forge Mapping declares *"this column is the natural key"*; Context Resolver runs whenever that declaration doesn't apply (no shared key, free-text mention, cross-source disambiguation needed).

---

## Why Context Resolver is hard to replicate

A working cross-source resolution module requires **simultaneously**: (a) a multi-source ingestion path, (b) a vector index for blocking, (c) a fine-tuneable neural matching model with labeled training data per entity type, (d) a coreference + NER stack for unstructured text, (e) a probabilistic soft-logic engine for constraint propagation, (f) bitemporal storage for the resulting Identity Graph, and (g) a human-in-the-loop active-learning surface (Resolver Studio).

Each of these is a multi-quarter engineering investment in isolation. The combination is what makes ContextD's cross-source unification claim defensible at enterprise scale — and why no incumbent has shipped this:

| Adjacent player | What they have | What they're missing |
|-----------------|---------------|---------------------|
| **Customer Data Platforms** (Segment, mParticle, Hightouch) | Identity stitching for marketing | Bitemporal storage; coreference for unstructured text; no graph schema |
| **Data catalogs** (DataHub, Atlan, Collibra) | Metadata + glossaries | No ingestion; no probabilistic ER engine; no Identity Graph |
| **Graph DBs** (Neo4j, Neptune, TigerGraph) | Graph storage | No ingestion pipeline; no Resolver; no fine-tuned matching models; SSPL trap on Neo4j |
| **ER libraries** (Splink, Magellan, Dedupe.io, Zingg) | Single-stage Fellegi-Sunter or ML matching | Library, not a productized module; no Identity Graph, no Studio, no integration with bitemporal storage |
| **Memory-for-agents** (Zep, MemGPT, Letta) | Session memory | No cross-source enterprise unification; no Resolver pipeline |

The only way to compete is to ship all seven prerequisites — at which point you've effectively cloned ContextD.

---

## Customer onboarding flow

### Day 1 — first source connects

Customer connects Salesforce. Forge introspects + applies the `salesforce` Forge Profile. Resolver enables the `person-crm` and `organization-account` profiles. All Salesforce records ingest deterministically (Resolver skips Stages A-D for them — source-record-ID is the natural key). Identity Graph populates with one identifier per canonical entity.

### Day 7 — second source connects

Customer connects Gmail. Now Resolver runs. For each Gmail address in headers/bodies:
- Stage A blocks against the existing Identity Graph (HNSW vector ANN on entity-name embeddings)
- Stage B Fellegi-Sunter scores each candidate pair on email + name + domain
- Stage C cross-encoder matches Gmail records → existing canonical entities
- Stage D handles free-text mentions in email bodies (coref + CDCR)
- Stage E stitches matches into the Identity Graph; conflicts queued to Studio

End result: Identity Graph entities now have 1-2 identifiers each. Customer reviews the active-learning queue (typically 30-50 ambiguous matches per 10K records). Labels feed Stage C fine-tuning.

### Day 14 — Slack, Zendesk, GitHub, Confluence

Each new source layers in. By the end of the first month, well-known canonical entities have 4-7 identifiers each, with confidence-weighted edges and full evidence traces.

### Month 3+ — ongoing

The active-learning loop has produced 200-500 labels. The Stage C model has been fine-tuned per entity type. The cross-encoder achieves > 95% F1 on the customer's domain. New source connections ingest cleanly with minimal review-queue surface.

### Six months in — operational steady state

A typical mid-size enterprise tenant has:
- ~38M canonical entities
- ~140M identifier links across 7-12 connected sources
- Average confidence per stitch: 0.93
- Stage F adjudication rate: < 0.5% of new records
- Resolver Studio review queue: ~10-30 items/day at steady state

---

## What's in scope (v1) vs deferred (v2)

### In scope (v1)

- Six-stage Resolver Engine
- HNSW + LSH + DeepBlocker blocking
- Fellegi-Sunter probabilistic record linkage with EM
- DITTO-style cross-encoder for pairwise matching
- GLiNER + RoBERTa-NER for NER
- e2e-coref / MaverickCoref for within-doc coreference
- CDCR for cross-document mention alignment
- PSL-based transitive closure on the Identity Graph
- Active learning via uncertainty sampling
- LLM final adjudication (few-shot or chain-of-thought)
- Resolver Studio v1 (active-learning queue, conflict queue, identity-graph explorer)
- Resolver Profiles for `person-crm`, `person-engineering`, `organization-account`, `deal-opportunity`, `device-asset`, `product-sku`
- Bitemporal Identity Graph stored in substrate
- Resolver-to-Pipeline Bridge (deterministic vs probabilistic routing)

### Deferred (v2)

- **Privacy-preserving record linkage** (PPRL): hashed-token matching for cross-tenant ER without sharing raw PII. Useful for federated CDP scenarios.
- **Streaming bi-encoder Stage C fast-path** at full scale (currently limited to 5K pairs/sec; v2 targets 50K+ on multi-GPU)
- **Customer-defined ER plugins**: customers contribute their own attribute schema or NER models for niche domains
- **Cross-tenant identity portability**: an enterprise group with multiple subsidiary tenants can share canonical entities (with tenant-level audit and consent)
- **Real-time identity resolution at request time** (currently batched into ingestion; v2 supports inline resolution on agent queries for new records)

---

## Roadmap commitment

Context Resolver ships in Phase 4 of the unified-substrate roadmap, in parallel with the early Hybrid Retrieval work. See `10-roadmap-and-build-plan.md` for the integrated plan.

| Phase | Quarter | Scope |
|-------|---------|-------|
| **Phase 4 (Context Resolver)** | Q1 2027 | Resolver Engine (Stages A-E baseline), Identity Graph schema in substrate, Resolver-to-Pipeline Bridge, three Profiles (person-crm, organization-account, person-engineering), Resolver Studio v1, active-learning loop |
| **Phase 5+** | Q2 2027 onwards | Stage F LLM adjudication, additional Profiles, PPRL groundwork, streaming bi-encoder fast-path |

---

## Common technical questions

**Accuracy on real data.** The Stage C cross-encoder reaches > 95% F1 on standard ER benchmarks (Walmart-Amazon, DBLP-ACM, Magellan suite). On enterprise workloads, end-to-end precision after Stages A-E is typically > 0.97; recall is bounded by source coverage. Stage F (active learning + LLM adjudication) closes the gap on the residual 1-3% of ambiguous cases.

**Failure handling when the cross-encoder is wrong.** Two safety nets are built in. *Soft-link mode* retains low-confidence stitches as candidate edges rather than committing them as hard merges, so a wrong match does not overwrite the canonical entity. *PSL conflict detection* raises constraint violations downstream — when a wrong stitch creates a contradiction, the conflict is surfaced to Resolver Studio for adjudication rather than silently propagated.

**Audit trail per stitch.** Every identifier link carries an `evidence` field naming the stage(s) that produced it, the confidence score, and the timestamp. The `audit_trail` field on each canonical entity records every CREATE / STITCH / SUPERSEDE event. Bitemporal annotations on every link enable "who was stitched to whom on date X" queries directly in Cypher.

**Operating cost at scale.** At 100M canonical entities, Stage A blocking is sub-10-millisecond per record (HNSW + LSH parallel). The Stage C cross-encoder is the GPU-bound stage at ~5,000 pairs/sec on a single GPU; throughput scales linearly with GPU count. A 100M-entity tenant runs roughly $400–800/month in GPU and storage on managed cloud at typical ingestion velocity.

**Distinction from marketing-CDP identity stitching.** CDPs target visitor-to-customer identity for marketing, with deterministic hashed-PII matches as the dominant path. The Resolver targets enterprise context — CRM + communications + tickets + commits + free-text mentions — with materially heavier neural and coreference machinery, bitemporal annotations, and an Identity Graph that is itself a queryable artifact in the graph database, not a black-box service.

**Biggest accuracy risk.** Distribution shift in the cross-encoder fine-tuning data. A customer domain meaningfully different from standard benchmarks (e.g., financial entities in non-English languages) will see the baseline cross-encoder under-perform until the active-learning loop applies labels. Mitigation: Resolver Profiles ship pre-tuned per major domain; the active-learning UX is engineered to converge within 200–500 labels for novel domains.

---

*Continue to `04-product-and-architecture.md` for where Context Resolver fits in the layer stack, or `06-context-forge.md` for the complementary pre-pipeline mapping module, or `11-technical-capabilities.md` for the moat analysis.*
