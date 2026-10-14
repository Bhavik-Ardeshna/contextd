# 13 — Integration, Deployment, Security

> How customers actually access ContextD: SDK, MCP, REST API, six wire protocols. Four deployment modes from embedded to enterprise. Multi-tenant RBAC with three scoping dimensions, full audit trail, GDPR/SOC 2/ISO 27001 compliance roadmap.

---

## Integration paths

### 1. Python SDK

```python
from contextd import ContextD
from contextd.search import COMBINED_HYBRID_SEARCH_RRF

# Embedded mode — DB runs in-process, [TARGET] <10ms latency
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

# Hybrid query
result = db.query("Who are the decision makers for Project Atlas?",
                  config=COMBINED_HYBRID_SEARCH_RRF)

# Temporal query
result = db.query("What did we know about Atlas on March 15th?",
                  as_of="2026-03-15")

# Assemble context for an AI agent
context = db.get_context(query="Draft a follow-up email", max_tokens=2000)

# Submit feedback
await db.feedback(session_id="sess_1", query_id="q_1", score=4,
                  used_entities=["e_789"], used_edges=["edge_456"])

# Context Core operations
core = db.core.build(name="acme-context", graph="production")
db.core.promote(core="acme-context:v3", target="production")
```

### 2. MCP Server (two-layer architecture)

ContextD is **MCP-native**, with a layered design that maximizes reuse and exposure:

| Layer | Provided by | Tools |
|-------|-------------|-------|
| **Layer 1: Substrate built-in** | ArcadeDB native MCP | `execute_command`, `get_schema`, `list_databases`, `query`, `server_status`, `profiler` |
| **Layer 2: ContextD context tools** | ContextD engine | `query_context`, `get_entity`, `get_timeline`, `get_decision_lineage`, `get_saga_summary`, `submit_feedback`, `ingest_episode` |

| Transport | Use case |
|-----------|----------|
| `stdio` | Claude Code, Cursor, Windsurf — local AI tool integration |
| `SSE` | Web agent frameworks, real-time streaming |
| `HTTP` | REST integrations, serverless functions |

A Claude Code session can connect to a local ContextD via stdio MCP and call `query_context("prepare me for the Acme call")` — the MCP standard makes this a one-line integration.

### 3. REST API (FastAPI)

Auto-generated OpenAPI documentation. Full endpoint surface:

```
POST   /query                       # Natural-language query
POST   /cypher                      # Direct Cypher query
POST   /search                      # Hybrid search with config
GET    /entities/:id                # Get entity by ID
GET    /entities/:id/relationships  # Get relationships
GET    /entities/:id/timeline       # Bitemporal timeline
GET    /decisions/:id/lineage       # Full decision chain
GET    /sagas/:id/summary           # Saga narrative
POST   /context                     # Assemble context for an agent
POST   /ingest/episode              # Ingest raw data
POST   /feedback                    # Submit feedback rating
POST   /cores/build                 # Build Context Core
POST   /cores/:id/promote           # Promote to production
POST   /cores/:id/rollback          # Rollback
```

### 4. Wire protocol polyglot — substrate-provided

A single ContextD instance speaks **six protocols simultaneously**:

| Protocol | Drivers | Use case |
|----------|---------|----------|
| **Bolt** | Neo4j Python/Java/Node/Go/.NET | Cypher queries, existing Neo4j code |
| **PostgreSQL** | psql, pgAdmin, JDBC, SQLAlchemy | SQL queries, BI tool integration |
| **MongoDB** | PyMongo, Mongoose, any MongoDB driver | Document queries, JSON ops |
| **Redis** | redis-py, Jedis, any Redis client | KV ops, caching |
| **gRPC** | Custom gRPC clients (any language) | High-performance service-to-service |
| **HTTP/REST** | curl, any HTTP client | Universal access, web integrations |

Customers connect with whichever driver their team already has. **Reduces buyer friction massively.**

> **Caveat from benchmark.** The PostgreSQL wire protocol implementation in ArcadeDB has a `CodeUtils.sleep(100)` polling bug (`PostgresNetworkExecutor.java:1515`) that adds 100ms floor per query. We patch this in our fork before shipping PG-protocol customer access. See `09-benchmarks-and-validation.md`.

---

## Deployment modes

| Mode | Latency | Setup | Use case |
|------|---------|-------|----------|
| **Embedded** | [TARGET] <10ms | `pip install contextd` (Java 21 via jpype) | Local agents, edge, prototyping |
| **Server** | [TARGET] <50ms | `docker compose up` | Team usage, shared instance |
| **Cloud** | [TARGET] <300ms | Sign up at contextd.ai | Production, fully managed |
| **Enterprise** | [TARGET] <50ms | On-prem / air-gapped K8s | HA clustering, compliance |

> Latency targets are workload-dependent. The benchmark report (`09-benchmarks-and-validation.md`) shows hybrid retrieval at 47ms p50 single-thread on the substrate — the Server mode target is achievable, while Cloud's <300ms reflects multi-region network overhead.

### Performance profiles (substrate-provided)

| Profile | Page cache | Workers | Use case |
|---------|-----------|---------|----------|
| `high-performance` | Unlimited (50% RAM) | 50% cores | Production, benchmarking |
| `default` | 4 GB | Auto | General use |
| `low-ram` | 16 MB | Auto | Edge, constrained |
| `low-cpu` | Standard | 1 thread | Background processing |

### High availability

The substrate (ArcadeDB) supports **leader-replica clustering** with synchronous replication (configurable), automatic leader election, and Write-Ahead Log (WAL) with configurable flush modes (no-flush / flush / fsync). Production deployments use leader-replica replication for zero-downtime failover.

### Scalability targets

| Dimension | v1 (Cloud GA) | v2 (Cloud maturity) |
|-----------|--------------|---------------------|
| Entities per graph | 10M | 100M |
| Relationships per graph | 50M | 500M |
| Facts per graph | 100M | 1B |
| Episodes per graph | 10M | 100M |
| Connectors per tenant | 30 | 100 |
| Concurrent queries | 100 QPS | 500 QPS |
| Cloud tenants | 1,000 | 10,000 |

> **Cross-reference.** The benchmark report shows the substrate caps hybrid throughput at ~137 ops/sec on a single 16-vCPU instance with 475K entities. To hit v1's 100 QPS at scale, the architecture combines (a) horizontal vector-search replicas behind a load balancer, (b) substrate's CSR-based analytical view for lock-free graph traversals, (c) Redis hot-path caching, (d) per-tenant database isolation. See `10-roadmap-and-build-plan.md`.

---

## RBAC — Six roles with three scoping dimensions

### Roles

| Role | Description |
|------|-------------|
| **Owner** | Full access; can delete graph |
| **Admin** | Manage connectors, users, roles; no deletion |
| **Editor** | Read/write data, trigger syncs; no user/connector mgmt |
| **Viewer** | Read-only, scoped (source / entity-type / tags) |
| **Agent** | Programmatic, scoped read + feedback submit |
| **Connector** | Write-only to own source |

### Permission matrix

| Permission | Owner | Admin | Editor | Viewer | Agent | Connector |
|-----------|:-----:|:-----:|:------:|:------:|:-----:|:---------:|
| Read entities/relationships/facts | Y | Y | Y | scoped | scoped | N |
| Read decision lineage | Y | Y | Y | scoped | scoped | N |
| Read episodes (raw data) | Y | Y | Y | N | N | N |
| Write entities/facts | Y | Y | Y | N | N | own source |
| Submit feedback | Y | Y | Y | N | Y | N |
| Manage connectors | Y | Y | N | N | N | N |
| Manage Context Cores | Y | Y | N | N | N | N |
| Natural-language query | Y | Y | Y | scoped | scoped | N |
| Direct Cypher / SQL | Y | Y | Y | N | N | N |
| Delete graph | Y | N | N | N | N | N |

### Three scoping dimensions

Viewer and Agent roles are scoped along three independent axes:

```json
// Sales agent: only sees Gmail + Salesforce data
{
  "role": "agent",
  "name": "sales-agent",
  "scopes": {
    "sources": ["salesforce", "gmail"],
    "sources_denied": ["slack"]
  }
}

// Marketing analyst: only sees companies, deals, campaigns
{
  "role": "viewer",
  "name": "marketing-analyst",
  "scopes": {
    "entity_types": ["company", "deal", "campaign"],
    "entity_types_denied": ["person_internal"]
  }
}

// Project-scoped agent: only sees Project Atlas
{
  "role": "agent",
  "name": "project-atlas-agent",
  "scopes": {
    "tags": ["project:atlas"]
  }
}
```

Combinatorially, this gives fine-grained access control without role explosion. **Every query enforces these scopes server-side** — no client-side filtering.

---

## Multi-tenancy architecture

```
Organization (Tenant)
├── Graph (isolated substrate database)
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

**Complete isolation:**
- Separate substrate database per tenant
- No cross-tenant data access possible
- Separate connector OAuth tokens per tenant
- Audit log per tenant; retention 1 year (free) → 7 years (enterprise)

This is enforced at the substrate level, not application code — much harder to misconfigure.

---

## Audit logging

Every data access logged. Append-only, immutable, queryable.

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

Compliance teams can `SELECT * FROM AuditLog WHERE user_id = 'X' AND action = 'query'` to reconstruct any user's complete query history.

---

## Encryption & data security

| Surface | Approach |
|---------|----------|
| **In transit** | TLS 1.3 for all API communication |
| **At rest** | AES-256 for stored data (Cloud) |
| **API keys** | SHA-256 hashed, never stored plaintext, revocable |
| **OAuth tokens** | Encrypted at rest, rotated automatically |
| **PII** | Optional auto-detection on ingestion with redaction or tagging |
| **Right to deletion** | Cascade delete — removing an entity removes all linked relationships, facts, and episode references |

---

## Compliance roadmap

| Standard | Timeline | Scope |
|----------|----------|-------|
| **GDPR** | Cloud launch (Q3 2027) | Data residency, right to deletion, consent tracking |
| **SOC 2 Type I** | Month 9 (Q1 2027) | Controls documentation, audit readiness |
| **SOC 2 Type II** | Month 15 (Q3 2027) | Full audit, 6-month observation period |
| **ISO 27001** | Month 18 (Q4 2027) | Information security management system |
| **HIPAA** (optional) | Q1 2028 if pulled by customers | Healthcare data handling |
| **FedRAMP** (optional) | 2028+ if pulled by gov customers | Federal authorization |

The SOC 2 Type II observation window (6 months) starts as soon as the Type I controls are documented and operating — driving the Q1→Q3 2027 sequencing.

### Data residency (GDPR)

Customers select region at tenant creation:
- `us-east` (Virginia)
- `us-west` (Oregon)
- `eu-west` (Frankfurt) — GDPR data residency
- `ap-southeast` (Singapore) — APAC sovereignty

Each region runs an independent control plane; no cross-region data movement without explicit customer opt-in.

---

## Observability

### What gets traced (OpenTelemetry)

| Operation | Spans created |
|-----------|---------------|
| Ingestion pipeline | 1 parent + 1 child per step (all 10) |
| Entity resolution | 1 span per stage (normalize, entropy, minhash, cosine, llm) |
| Search | 1 parent + child per method (BM25, cosine, BFS) + reranker |
| Context assembly | 1 span covering token optimization + packaging |
| Feedback | 1 span per weight update batch |
| Connector sync | 1 parent + children for auth, extract, transform, load |

### Semantic span attributes

```
contextd.pipeline.name           = "gmail_connector_v1"
contextd.pipeline.task_name      = "extract_nodes"
contextd.pipeline.episode_id     = "ep_456"
contextd.search.type             = "COMBINED_HYBRID_SEARCH_RRF"
contextd.search.query            = "Acme deal status"
contextd.search.result_count     = 23
contextd.resolution.stage        = "minhash"
contextd.session.id              = "sess_abc"
contextd.feedback.score          = 4
```

### Prometheus metrics

| Metric | Type |
|--------|------|
| `contextd_queries_total` | Counter |
| `contextd_query_latency_seconds` | Histogram |
| `contextd_ingestion_episodes_total` | Counter |
| `contextd_ingestion_latency_seconds` | Histogram |
| `contextd_entity_resolution_accuracy` | Gauge |
| `contextd_feedback_scores` | Histogram |
| `contextd_context_tokens_saved` | Counter |

### Graceful fallback

When OpenTelemetry isn't installed, ContextD uses `NullSpan` — all tracing calls become no-ops. Zero overhead, zero errors. Configuration:

```python
db = ContextD(
    path="./my_graph",
    tracing=True,
    otel_service_name="contextd-production",
    otel_exporter_otlp_endpoint="https://otel-collector.internal:4318",
)
# Or via env vars:
#   CONTEXTD_TRACING_ENABLED=true
#   OTEL_SERVICE_NAME=contextd
#   OTEL_EXPORTER_OTLP_ENDPOINT=...
```

---

## Customer integration journey

```
Day 0    docker compose up                              (5 min)
Day 1    Connect first OAuth source (Gmail)             (10 min)
Day 1    First episode ingested                         (~2-3 sec for 1 episode)
Day 1    First context() call returns assembled JSON    (instant)
Week 1   3-5 sources connected; 1K+ episodes ingested
Week 2   Embed Python SDK in customer's agent code
Week 4   First feedback ratings flowing; weights begin to differentiate
Month 2  Second connector wave (CRM, support, comms)
Month 3  Custom ontology configured for the domain
Month 4  First Context Core built and tested
Month 6  Production deployment with HA, audit log, RBAC
```

The "Day 0 → first useful context" path is under an hour. This is the developer-experience commitment.

---

## Connector authentication patterns

Source connectors fall into three authentication tiers. Each is implemented as a pluggable strategy in the connector base class.

### OAuth 2.0 (cloud SaaS — Salesforce, HubSpot, Slack, Gmail, GitHub, Zendesk, Notion, Jira, Atlassian)

The OAuth service handles the full Authorization Code grant with PKCE for confidential clients, rotates refresh tokens on every access-token refresh (per RFC 6749 §6 and Salesforce / Slack-specific rotation rules), and persists encrypted tokens at rest:

```
Token storage row:
   tenant_id (uuid)
   source (string-id)
   access_token (encrypted, AES-256-GCM)
   access_token_expires_at (timestamp)
   refresh_token (encrypted, AES-256-GCM)
   refresh_token_expires_at (timestamp, may be NULL for non-rotating providers)
   scope (string)
   provider_user_id (string)
   created_at, updated_at (timestamps)
```

Refresh is preemptive: a background task refreshes any access token whose `expires_at` is within 5 minutes of now, so connector sync jobs never face a token-expired race. Failed refresh increments a `consecutive_refresh_failures` counter; after 3 failures, the source connection is marked degraded and the customer is notified via webhook.

Encryption keys live in a separate KMS (AWS KMS, GCP Cloud KMS, HashiCorp Vault, or Azure Key Vault). The token-encryption-key (DEK) is itself encrypted by a master key (KEK) and rotated annually; rotation re-encrypts existing tokens via a background job.

### API key (Stripe, Shopify, Snowflake user-password, Postgres connection strings)

Provider API keys are stored in the same encrypted-at-rest store as OAuth tokens, but lack the refresh / expiry machinery. The customer rotates API keys manually through the source-connection management UI; the system supports zero-downtime rotation by accepting the new key, validating it via a `whoami` probe, then atomically swapping the active key.

### Service-account / private-key (BigQuery, GCP integrations, signed-JWT flows)

For service-account-based providers, the customer uploads a private key during source-connection setup. The key is encrypted at rest with the same DEK/KEK chain as OAuth tokens. Connector workers fetch the key on demand to mint short-lived signed JWTs, which are exchanged for short-lived access tokens at the provider.

### Per-tenant token isolation

Each tenant's tokens live in a separate logical key namespace within the same KMS. A leaked DEK from one tenant cannot decrypt another tenant's tokens. Audit log entries are emitted for every token-fetch and token-refresh operation for compliance reporting.

---

## Network security

| Surface | Protection |
|---------|------------|
| Client → API | TLS 1.3 only; certificates rotated via cert-manager / equivalent; HSTS header on HTTP/REST endpoint |
| Inter-service (intra-cluster) | Optional mTLS — both sides present X.509 certificates issued by an internal CA; certs rotated every 24 hours via SPIFFE/SPIRE-style identity service |
| Wire-protocol listeners (Bolt, PG, Mongo, Redis, gRPC) | Per-protocol TLS support; each listener can be configured with its own certificate or can share a wildcard cert |
| Network ingress (Cloud) | IP allowlist per tenant (CIDR ranges, configurable); regional VPC peering for enterprise customers; private endpoints (AWS PrivateLink / GCP Private Service Connect / Azure Private Link) for high-security tenants |
| MCP transport | stdio (no network exposure); SSE/HTTP behind TLS-terminating proxy with API-key auth |

For air-gapped enterprise deployments, the substrate runs without external network egress. LLM API calls (extraction, fine-tuning) are routed to an on-premises model server; embedding generation uses a self-hosted embedding model (sentence-transformers or fine-tuned domain model) instead of the OpenAI Embeddings API.

---

## Audit log tamper-evidence

The audit log (Section 8 of `05-contextd-native-db-implementation.md`) is hash-chained for tamper-evidence. Each entry holds:

```
   prev_hash (32 bytes)   = SHA-256 of previous entry's bytes
   payload_hash (32 bytes) = SHA-256 of this entry's payload (excluding the hash field)
   entry_hash (32 bytes)   = SHA-256(prev_hash || payload_hash)
```

Any retroactive modification of an entry invalidates its `entry_hash`, which propagates forward through every subsequent entry. A periodic verification job (default: hourly) walks each sealed segment, recomputes `entry_hash` from `prev_hash || payload_hash`, and flags any mismatch as a potential tamper event.

For regulated tenants, the chain head (the most recent `entry_hash`) is published to an append-only external attestation service — a private Merkle log, an internal blockchain, or a write-once cloud-storage bucket — at a configurable cadence (default: every 15 minutes). External attestation provides a cryptographic anchor that prevents even root-level operators from rewriting history without external detection.

Sealed-segment files are immutable once renamed from `.active` to `.sealed`; the underlying filesystem is configured with `chattr +i` (Linux) or equivalent immutable-file flags on supported storage backends.

---

## PII detection and handling

PII detection runs as an optional post-extraction pass on every Fact emitted by the ingestion pipeline.

### Detection rules

A library of regex + named-entity-recognition rules tagged by sensitivity class:

| Class | Examples | Detection |
|-------|----------|-----------|
| `pii.email` | RFC 5322 email addresses | Regex on string fields; high precision |
| `pii.phone` | E.164, NANP, common national formats | Regex + post-validation |
| `pii.ssn` | US Social Security Number | Regex + Luhn-style checksum where applicable |
| `pii.credit_card` | Visa, MasterCard, AmEx, Discover | Regex + Luhn checksum |
| `pii.passport` | National passport patterns | Regex per country code |
| `pii.iban` | International Bank Account Numbers | IBAN checksum |
| `pii.ip_address` | IPv4, IPv6 | Regex |
| `phi.medical_record` | Domain-specific patterns (configurable per-tenant) | Regex + NER |
| `phi.diagnosis_code` | ICD-10, SNOMED CT codes | Lookup table |

The detection library is pluggable; tenants can register custom detectors (regex + classifier pairs) for industry-specific patterns.

### Handling policies (configurable per tenant)

| Policy | Effect on the affected fact |
|--------|-----------------------------|
| `tag` | Fact is stored as-is, with a sensitivity tag; queries by users without a `pii.read` permission see the fact redacted |
| `redact` | Fact's `object` value is replaced with a deterministic hash (so equality joins still work) before storage; original value is dropped |
| `tokenize` | Fact's value is replaced with a tokenization-vault reference; the original lives in a separate vault with stricter access control |
| `block` | Fact is dropped entirely, with an audit-log entry recording the block |

The default policy for a fact is determined by its sensitivity class and the tenant's compliance profile (HIPAA-strict, GDPR-strict, SOC 2 baseline, etc.).

### Right to deletion

When a customer requests deletion of a person's data:

1. The Identity Graph is queried for the canonical entity matching the requestor (by email, account ID, or other identifier).
2. All facts, relationships, and edges where the entity appears as `subject`, `target`, or `affected_entity` are marked with `expired_at = now()` and `invalid_at = now()` — bitemporal supersession with no replacement.
3. Episodes referencing the entity are tombstoned: `content` is overwritten with a hash, while metadata (timestamp, source) is retained for the audit chain.
4. The entity vertex itself is tombstoned: all properties except `canonical_id` are cleared.
5. An audit-log entry records the deletion with the requester, the requesting party, the legal basis (GDPR Article 17, etc.), and the affected RID list.
6. Background compaction physically removes the tombstoned data from sealed-segment files within 30 days (compliance window).

The 30-day delay is configurable per tenant; some compliance regimes require immediate physical erasure (use the `eager` deletion mode).

---

## Compliance certification details

| Standard | Implementation evidence |
|----------|-------------------------|
| **GDPR** | Data residency (Section *Data residency*), right to deletion (above), consent tracking via per-source consent records, data-processor agreement template, sub-processor inventory |
| **SOC 2 Type I/II** | Audit log (above), access controls (RBAC matrix), encryption (TLS 1.3 + AES-256), incident-response runbook, change-management via Context Cores promote/rollback, monitoring (OpenTelemetry + Prometheus alerts) |
| **ISO 27001** | Information Security Management System (ISMS) documentation, risk register, supplier-management process, business-continuity plan, internal-audit cadence |
| **HIPAA** (when activated) | PHI-class detection rules enabled by default, BAA-compliant cloud regions, audit-log retention ≥ 6 years, encryption-at-rest via FIPS 140-2 validated cryptography, employee access reviews quarterly |
| **FedRAMP** (when activated) | FedRAMP Moderate/High baseline controls, FIPS 140-2 modules only, deployment in AWS GovCloud or Azure Government, dedicated SCIF-compliant operations team |

---

*Continue to `14-references.md` for the consolidated citation reference, or back to `12-use-cases.md` for concrete query and ingestion scenarios.*
