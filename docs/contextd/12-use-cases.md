# 12 — Use Cases

> Five concrete use cases with full code, queries, and assembled context output. Each demonstrates a capability that is impossible (not just inconvenient) with chunk-based RAG, vector search alone, or graph DB alone.

---

## Use Case 1 — AI Agent Memory: Customer 360

**The scenario.** An AI sales assistant needs to prepare a sales rep for a customer call. The agent must understand: deal status, who's involved, sentiment trajectory, recent changes, open issues, decision history.

### Without ContextD

Agent searches CRM for deal info. Gets the basic deal record. Doesn't see:

- Three angry support tickets filed last week (separate Zendesk DB)
- A marketing email that promised a feature that doesn't exist (separate Marketo DB)
- A Slack conversation where the CEO mentioned evaluating competitors (separate Slack DB)
- A pricing exception approved last month with net-60 terms (buried in approval email thread)
- A recent sentiment shift from a Zoom call transcript (separate transcription system)

The rep walks into the call blind to half the relevant context.

### With ContextD

```python
context = db.get_context(
    query="Prepare me for a call with Acme Corp",
    max_tokens=2000,
    include_lineage=True,
)
```

Returns structured JSON:

```json
{
  "primary_entities": [
    {"name": "Acme Corp", "type": "organization",
     "key_attrs": {"industry": "Technology", "revenue": "$250M", "nps": 72}},
    {"name": "Sarah Chen", "type": "person",
     "key_attrs": {"role": "VP Engineering", "sentiment": "positive"}},
    {"name": "Marcus Rivera", "type": "person",
     "key_attrs": {"role": "Dir. Procurement", "sentiment": "neutral"}},
    {"name": "Lisa Wong", "type": "person",
     "key_attrs": {"role": "CFO", "sentiment": "skeptical"}}
  ],
  "facts": [
    "Deal stage: Negotiation — pricing agreed at $38/seat (15% discount, net-60 terms)",
    "Sarah Chen confirmed agreement on revised pricing (positive sentiment)",
    "Marcus Rivera requested 2 more weeks for procurement review",
    "Lisa Wong raised budget concerns in Q1 business review",
    "VendorX is offering 18% discount — competitive pressure"
  ],
  "decision_history": [
    {"subject": "Acme discount", "outcome": "15% + net-60",
     "decided_by": "Jordan Blake (VP Sales)",
     "exception": "net-60 vs standard net-30"}
  ],
  "temporal_context": {
    "as_of": "2026-04-24",
    "current_facts": 5,
    "superseded_facts": 1,
    "note": "1 prior fact superseded: deal_stage was 'Discovery' before 2026-03-01"
  },
  "saga_summary": "500-seat enterprise deal in Negotiation. Discount approved Apr 2nd. Pricing agreed Apr 10th. Marcus Rivera requested extended review. Lisa Wong skeptical on budget. Next step: contract legal review.",
  "metadata": {
    "tokens_used": 1847,
    "tokens_saved": 7353,
    "reduction": "80%"
  }
}
```

The rep walks in **knowing every relevant touchpoint, sentiment, decision, and exception** — across CRM, support, marketing, comms.

### What's hard to replicate

- Cross-source unification (entity resolution across Salesforce + Gmail + Slack + Zendesk + Zoom transcripts)
- Sentiment as a queryable fact (not text to be re-analyzed each time)
- Decision lineage queryable inline ("15% discount with net-60 exception")
- Temporal awareness (saga summary tracks "what changed when")
- Feedback-weighted ranking (agents learn what context preps best — Sarah's relationship matters more than HQ address)

---

## Use Case 2 — Compliance & Audit: Decision Lineage

**The scenario.** Legal needs every discount approval over 15% in Q1, who approved each, what policy was cited, and whether exceptions were justified.

### Without ContextD

A team digs through:
- Email threads (Gmail) — search for "discount" keyword
- Approval forms (DocuSign / internal app)
- Salesforce custom fields (often inconsistent)
- Slack channels (`#approvals`, `#deals`)
- Sales-Ops spreadsheets

Reconstruction takes days, is incomplete, and is unreproducible at the next audit.

### With ContextD

```cypher
MATCH (d:Decision {decision_type: "discount"})
WHERE d.outcome > "15%"
  AND d.decided_at >= datetime("2026-01-01")
  AND d.decided_at <  datetime("2026-04-01")
OPTIONAL MATCH (d)-[:DECIDED_BY]->(approver)
OPTIONAL MATCH (d)-[:APPLIED_POLICY]->(policy)
RETURN d.subject, d.outcome, approver.name, policy.name,
       d.exception, d.justification
ORDER BY d.decided_at
```

Returns a clean table:

```
┌─────────────────────────┬───────────────────────────────┬──────────────┬────────────────────────────┬────────────┬──────────────────────────────────────┐
│ subject                 │ outcome                       │ approver     │ policy                     │ exception  │ justification                        │
├─────────────────────────┼───────────────────────────────┼──────────────┼────────────────────────────┼────────────┼──────────────────────────────────────┤
│ Acme 15% discount       │ Approved 15% + net-60 terms   │ Jordan Blake │ volume_discount_v3.2       │ net-60     │ Strategic account, VendorX pressure  │
│ Beta 18% discount       │ Approved 18% + std terms      │ Pat Ortiz    │ volume_discount_v3.2       │ amount     │ Multi-year commitment + 800 seats    │
│ Gamma 22% (rejected)    │ Rejected — exceeds policy     │ Pat Ortiz    │ volume_discount_v3.2       │ —          │ —                                    │
│ Omega 16% discount      │ Approved 16% + std terms      │ Jordan Blake │ volume_discount_v3.2       │ amount     │ Consolidation deal across 3 sites    │
└─────────────────────────┴───────────────────────────────┴──────────────┴────────────────────────────┴────────────┴──────────────────────────────────────┘
```

Every discount links back to its inputs, policy, exception status, justification.

### What's impossible elsewhere

This query requires:
- Decisions as **first-class entities** (not text in email subjects)
- **Bitemporal filtering** (decisions made between dates, with the policies *that were in effect at decision time*)
- **Graph lineage** (decision → applied policy → exception → affected deal)
- **Cross-source unification** (same approver linked across Salesforce CRM and Slack `#approvals`)

Vector search returns email threads with the word "discount." Graph DB returns a relationship without temporal grounding. Document store returns approval records without lineage. Only ContextD returns the audit-ready table.

### Decision lineage drilldown

```python
result = db.get_decision_lineage(entity_id="decision_discount_15pct")
```

Returns the full causal chain:

```json
{
  "decision": {
    "subject": "Acme 15% volume discount",
    "outcome": "Approved 15% discount with net-60 payment terms",
    "decided_by": "Jordan Blake (VP Sales)",
    "decided_at": "2026-04-02T11:00:00Z"
  },
  "informed_by": [
    {"fact": "Opportunity: 500 seats, $500K ARR",
     "source": "salesforce", "recorded_at": "2026-02-15", "feedback_weight": 0.92},
    {"fact": "VendorX offering 18% discount",
     "source": "competitive_intel", "recorded_at": "2026-03-25", "feedback_weight": 0.87},
    {"fact": "Sarah Chen (VP Eng) sentiment: positive",
     "source": "zoom", "recorded_at": "2026-03-10", "feedback_weight": 0.84}
  ],
  "applied_policy": {
    "name": "volume_discount_policy_v3",
    "version": "3.2",
    "effective_date": "2025-09-01"
  },
  "exception": {
    "policy": "Standard payment terms: net-30",
    "exception_granted": "net-60",
    "justification": "Strategic account with active competitive pressure from VendorX"
  },
  "downstream_impact": [
    {"entity": "Acme Enterprise Deal", "impact": "Pricing revised $45 → $38/user/month"},
    {"entity": "Q2 Revenue Forecast", "impact": "Reduced by $15K for this account"},
    {"entity": "Marcus Rivera (Procurement)", "impact": "Requested extended timeline"}
  ],
  "what_we_didnt_know_at_decision_time": [
    "Lisa Wong's $1.8M budget ceiling was recorded April 8th — AFTER the discount decision was made April 2nd. Had we known, we might have structured pricing differently."
  ]
}
```

The "what_we_didn't_know" line — only possible with **bitemporal knowledge state** queries — is gold for post-mortem analysis.

---

## Use Case 3 — Audience Activation: Cross-System Behavioral Cohort

**The scenario.** Customer success needs a cohort of "high-usage companies with urgent tickets, not contacted in 14 days" — likely churn-risk accounts.

### With ContextD

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
RETURN c.name, c.attributes.arr, count(t) AS open_tickets
ORDER BY c.attributes.arr DESC
```

Crosses **CRM + support + marketing + comms** in a single graph query with bitemporal filtering. Returns a ranked list of churn-risk accounts with $/ARR + ticket count.

### What's hard to replicate

- The query joins facts (product usage), entities (tickets, outreach events), and bitemporal predicates (`> NOW - P30D`, `> NOW - P14D`)
- Three source systems unified into one graph
- Existing CDPs (Segment, Hightouch) can compute cohorts but not against decision-lineage or relationship-aware graphs

### Other audience-activation queries naturally available

```python
# All decision-makers with positive sentiment toward us, current
db.query("List all decision-makers across accounts who have positive sentiment toward us")

# Deals in negotiation stage with no activity in 7+ days
db.query("Show all deals in negotiation stage that haven't had activity in 7+ days")

# Recently reactivated dormant contacts
db.query("Which contacts became active in the last 30 days after being dormant for 60+ days?")

# Build audience for Q2 enterprise upsell campaign
db.get_context(query="Build audience for Q2 enterprise upsell campaign", max_tokens=3000)
```

Each of these would require a 3-5 system join in a current CDP architecture; in ContextD they're a single Cypher query or context call.

---

## Use Case 4 — RAG Enhancement: Structured Context Window

**The scenario.** A security analyst's AI assistant needs to answer: "What's our current security posture for the AWS deployment?"

### Without ContextD (chunk-based RAG)

Vector search over chunks of architecture docs, security reviews, Jira tickets, pen test reports, compliance policy. Returns top-15 chunks (~3,400 tokens). Many chunks overlap (architecture doc and security review both describe the AWS VPC layout). Some chunks are stale (last quarter's pen test). The agent must reason over the redundancy.

### With ContextD

```python
from contextd.search import COMBINED_HYBRID_SEARCH_RRF

context = db.get_context(
    query="What's our current security posture for the AWS deployment?",
    max_tokens=1500,
    search_recipe=COMBINED_HYBRID_SEARCH_RRF,
)
```

Returns ~847 tokens (vs ~3,400 from chunk RAG):

```
primary_entities:    AWS Production VPC, IAM Configuration, Network Security Groups
relationships:       AWS VPC → has_security_review → SR-2026-Q1,
                     AWS VPC → has_pen_test → PT-2026-04-15,
                     IAM Config → enforces_policy → ZeroTrust-v3
relevant_facts:      [current-state filtered]
                     - SR-2026-Q1 found 2 medium-severity issues, both remediated 2026-03-15
                     - PT-2026-04-15 confirmed remediation, no open findings
                     - ZeroTrust-v3 in effect since 2025-11-01
                     - SOC 2 controls aligned (Type II observation period: 2025-09 → 2026-03)
saga_summary:        "AWS deployment hardening Q1 2026 — completed Mar 15. Q2 focus is observability."
sources:             ["confluence", "jira", "security-tooling", "soc2-evidence"]
metadata:            tokens_used: 847, tokens_saved_vs_chunk_rag: 2553 (75% reduction)
```

Same coverage, dramatically smaller context window. **Connected facts** instead of redundant chunks. Stale facts (last quarter's findings already remediated) are temporally pruned.

### The mechanics of the reduction

| Mechanism | Tokens saved |
|-----------|-------------|
| Entity dedup (one record per entity, not 5 chunk-mentions) | ~30-40% |
| Temporal filtering (superseded facts dropped) | ~15-25% |
| Feedback pruning (low-weight elements excluded) | ~10-20% |
| Structured format (no NL prose padding) | ~10-15% |
| **Total typical reduction** | **~75-80%** |

Reduction is workload-dependent. Early queries see smaller savings; well-trained graphs approach the target.

---

## Use Case 5 — Context Core CI/CD: Test Before Deploy

**The scenario.** A team has been ingesting customer support data into ContextD for 4 months. They want to enable a new connector (Confluence). The team wants to test the impact on existing queries before promoting the change to production.

### The workflow

```bash
# 1. Build snapshot of current production graph
contextd core build --name "customer-context" --graph "production"
# → customer-context:v4 (12.4 MB, 57s, sha256:a4f8e2c91d3b7...)

# 2. Test against golden query suite
contextd core test --core "customer-context:v4" --queries "test-suite.yaml"
# → 47/50 pass (3 missing relationships from stale support sync)

# 3. Fix stale support sync, rebuild
contextd core build --name "customer-context" --graph "production"
# → customer-context:v5

# 4. Re-test
contextd core test --core "customer-context:v5" --queries "test-suite.yaml"
# → 50/50 pass | avg latency 42ms | avg tokens 1,420

# 5. Diff to confirm what changed
contextd core diff --from "customer-context:v4" --to "customer-context:v5"
# → +147 entities, +389 edges, +412 facts, latency -7%

# 6. Promote v5 to production
contextd core promote --core "customer-context:v5" --target "production"
# → Live. Rollback available: contextd core rollback --target production --to customer-context:v4

# 7. (Later) something breaks → rollback in seconds
contextd core rollback --target "production" --to "customer-context:v4"
# → Restored. Total downtime: <1s.
```

This is **CI/CD for knowledge graphs** — a workflow that doesn't exist in any other graph DB or vector DB. Test environments for code are standard; test environments for knowledge are about to be.

### Why this matters

For production AI systems, the question isn't *"is the model good?"* — it's *"is the data the model sees correct?"* When a connector breaks, when an ontology changes, when a feedback loop produces unexpected drift, customers need:

1. The ability to *snapshot* the current state
2. The ability to *test* that snapshot against expected behavior
3. The ability to *roll back* to a known-good state in seconds

Context Cores deliver all three. No competitor has this capability today.

---

## Use Case 6 — Compliance Audit: Data Retention Decision

**The scenario.** General Counsel decides to reduce data retention from 7 years to 3 years for cost savings, with an exception for financial records (SOX). Six months later, an auditor asks: "Show me the decision, who made it, what informed it, what exceptions were applied, and the downstream impact."

```python
result = db.get_decision_lineage(entity_id="decision_data_retention_update")
```

```json
{
  "decision": {
    "subject": "Reduce data retention from 7 years to 3 years",
    "outcome": "Approved with exception: financial records retain 7-year retention per SOX",
    "decided_by": "Rachel Torres (General Counsel)",
    "decided_at": "2026-03-15T14:00:00Z",
    "policy_applied": "GDPR compliance framework v4"
  },
  "informed_by": [
    {"fact": "GDPR audit: 3-year minimum retention is compliant",
     "source": "legal_audit", "recorded_at": "2026-02-28", "feedback_weight": 0.92},
    {"fact": "Storage cost analysis: $1.2M/year savings with 3-year retention",
     "source": "finops_report", "recorded_at": "2026-03-01", "feedback_weight": 0.88},
    {"fact": "SOX requirement: financial records 7-year minimum",
     "source": "compliance_policy", "recorded_at": "2025-01-01", "feedback_weight": 0.95}
  ],
  "exception": {
    "policy": "Default 3-year retention",
    "exception": "Financial records: 7-year retention",
    "justification": "SOX compliance requirement",
    "scope": "All financial transaction records, audit logs, tax documents"
  },
  "downstream_impact": [
    {"entity": "Data Retention Policy v2.1",
     "impact": "Published with dual retention schedule"},
    {"entity": "Storage Infrastructure",
     "impact": "$1.2M/year cost reduction effective Q3 2026"},
    {"entity": "Engineering Team",
     "impact": "Backlog item: implement tiered retention by data classification"}
  ]
}
```

The auditor gets a complete, verifiable, single-call answer. **This is what regulated industries pay for.**

---

## Use Case 7 — Incident Postmortem: What Did We Know?

**The scenario.** An auth-service outage on April 12th caused 45 minutes of 502 errors and 12,547 affected requests. Root cause analysis must answer: what did the team know *before* the outage that should have prevented it?

```python
result = db.query("What did we know about the auth-service issues before the April 12th incident?")
```

```json
{
  "as_of": "2026-04-12T00:00:00Z",
  "known_before_incident": [
    {"fact": "auth-service memory at 80% after config change on April 8th",
     "source": "monitoring", "severity": "WARNING"},
    {"fact": "Config change increased cache from 2GB to 4GB on April 8th",
     "source": "deploy_log", "severity": "INFO"},
    {"fact": "Peer code review approved the config change",
     "source": "github", "severity": "INFO"}
  ],
  "known_after_incident": [
    {"fact": "auth-service OOM caused cascading 502 errors for 45 minutes",
     "source": "incident_report", "severity": "P1"},
    {"fact": "12,547 requests affected during outage",
     "source": "monitoring", "severity": "P1"},
    {"fact": "Root cause: cache size exceeded available memory after traffic spike",
     "source": "postmortem", "severity": "P1"}
  ],
  "what_we_missed": {
    "warning_signal": "Memory usage at 80% on April 8th was flagged but not escalated to P2",
    "gap": "No alerting threshold configured for cache-to-memory ratio",
    "recommendation": "Implement memory pressure alerting and circuit breaker for cache eviction"
  },
  "decision_lineage": [
    {
      "decision": "Approved config change to increase cache from 2GB to 4GB",
      "decided_by": "Alex Thompson (Lead Engineer)",
      "decided_at": "2026-04-08T09:15:00Z",
      "based_on": "Peer code review approved, assumed headroom in memory",
      "exception": "No load testing performed for new cache size under peak traffic"
    }
  ]
}
```

**Knowledge state queries** make this trivial. Without bitemporal storage, you have to reconstruct "what we knew" from event logs — error-prone and time-consuming.

---

## Use Case 8 — Enterprise Data Warehouse Onboarding via Context Forge

**The scenario.** Acme Corp wants to plug their entire Snowflake-based analytics stack into ContextD. They have a 47-table production warehouse, a 150-model dbt project encoding years of business logic, 30 dbt-Semantic-Layer metrics, and a LookML model with 100+ measures. Their analytics team's CTO is on the call: "If you make us re-do all this in your tool, this conversation is over."

### Without Context Forge (the failure mode)

ContextD's pipeline starts from scratch. LLM extraction processes each row of every table. Three weeks later:

- Cost report: $47,000 spent on LLM extraction for the initial backfill
- Result: missing LTV metric (formula not reproduced); inconsistent entity types (`customer` vs `Customer` vs `Person`); junction table `account_contacts` mistakenly created as a `AccountContact` entity
- Customer's analytics team can't find any of their dbt-defined business metrics in the resulting graph
- Customer's CTO terminates the engagement

### With Context Forge

```
Hour 0:00   Customer connects Snowflake source via Atlas Source Introspector
            (read-only role, 47 tables, 218 declared FKs)
Hour 0:05   Customer uploads or links their dbt project (manifest.json + 
            sources.yml + schema.yml). Atlas Business Logic Ingester parses
            150 models, 30 metrics, full lineage.
Hour 0:08   Customer also links their LookML repo. Atlas parses 8 explores,
            106 measures, 198 dimensions.
Hour 0:15   Atlas Data Profiler completes 10K-row sampling per table.
            Cardinalities, top-K values, regex patterns, PII heuristics
            attached to every column.
Hour 0:30   Forge Mapping Inference Engine runs all seven inference passes
            (table→entity, FK→relationship, junction-detection, column→fact,
            time-series recognition, derived-metric translation, confidence
            scoring). Outputs candidate mapping:
              • 12 entities (Customer, Account, Contact, Deal, Subscription,
                Product, Invoice, Payment, Ticket, Address, Campaign, Tag)
              • 18 relationships (15 from FKs, 3 from junction-tables)
              • 94 fact predicates (one per non-FK column on entity tables)
              • 30 derived facts (one per dbt metric, formula preserved)
              • 3 episodes (login_events, subscription_events, support_messages)
              • 1 warning ("legacy_orders has no PK")
              • 2 items needing review (self-referencing FK ambiguity)

Hour 0:45   Forge Studio opens. Customer's CTO walks through the three-pane
            view (source schema | proposed mapping | graph preview).
            
Hour 1:30   CTO accepts most inferences. Edits 2 ambiguous self-references
            (manager_id is "reports_to" not "manages"). Bulk-applies a rule:
            "all *_log tables → episodes". Adds a custom override for the
            internal `pricing_decisions` table (treats it as Decision entities,
            not Facts).
            
Hour 2:00   CTO runs smoke-test queries directly in Forge Studio:
              "Show top 10 customers by LTV"  →  works, uses dbt formula
              "Customers churned in Q1"       →  works, uses dbt definition
              "Account → has_contact → Contact (M:M)"  →  works, junction
                                                          table detected
              "Decision lineage for pricing"  →  works, custom override applied
            
Hour 2:15   CTO hits Apply. Forge Mapping v1 saved (sha256:e8a91f2c...).
            Forge-to-Pipeline Bridge configures the 10-step pipeline.

Hour 2:20   Backfill begins. Pipeline ingests deterministically for 
            Forge-covered tables; LLM only for free-text columns 
            (notes, descriptions, ticket bodies).

Day 1:      Backfill complete. Cost report:
              • LLM extraction: $4,800 (90% reduction vs LLM-only)
              • All 30 dbt metrics appear as derived facts in the graph
              • All entity types match the customer's existing definitions
              • Junction tables correctly detected as relationships

Day 1:      CTO queries: "Show top customers by LTV" — returns correct LTV
            from the customer's own dbt formula. CTO renews engagement
            and signs the multi-year enterprise contract.

Week 4:     Analytics team adds 3 new dbt metrics. Atlas re-introspects on
            schedule, surfaces a candidate mapping update in Forge Studio
            ("3 new derived facts proposed"). CTO accepts; Forge Mapping
            v2 created with diff vs v1. Pipeline reads v2 going forward;
            old graph data still references v1 (full provenance).
```

### What's hard to replicate

- Parsing dbt manifest.json + LookML view files + MetricFlow YAML simultaneously
- Detecting junction tables vs entity tables from schema + data profile
- Translating SQL/LookML/DAX formulas into ContextD derived facts (formula preservation, dependency resolution, recompute-on-ingest)
- Versioning the Forge Mapping with content-addressed hashing (msgpack + SHA-256)
- Surfacing all of this in a three-pane Studio UI that an enterprise CTO can actually approve in 90 minutes
- Bridging the mapping into the 10-step pipeline so Forge-covered tables get deterministic extraction (cheap, fast) while unstructured fields still get LLM extraction (high-quality)

This is the most complex use case in the system because it touches every layer. It's also the one that **converts enterprise sales** — the difference between "interesting demo" and "let's sign the contract."

### Why this use case matters strategically

Without Atlas, ContextD competes with vector DBs and graph DBs on a feature-by-feature basis. With Atlas, ContextD is the only system that respects an enterprise's analytics investment end-to-end. **That's not a feature — it's a category.** Enterprises with mature data teams won't sign with anyone else.

---

## Cross-cutting capabilities demonstrated

| Capability | Used in use cases |
|-----------|---------------------|
| Bitemporal knowledge state | 1, 2, 6, 7 |
| Decision lineage | 2, 6, 7 |
| Cross-source entity unification | 1, 3, 4 |
| Feedback-weighted retrieval | 1, 3, 4 |
| Cypher temporal queries | 2, 3, 6, 7 |
| Context assembly with token budgeting | 1, 4 |
| Context Cores (CI/CD) | 5 |
| Saga summaries | 1, 4 |
| Context Forge (analyst-aware schema mapping) | 8 |
| Forge-derived facts (dbt/LookML formulas as derived facts) | 8 |

Every use case touches multiple primitives. The full value is the product of the parts — which is exactly why a unified database, not a stitched stack, makes this possible.

---

## Advanced query patterns

The use cases above demonstrate point-in-time capabilities. Production workloads also exercise deeper patterns: bitemporal joins, multi-hop graph traversals with temporal filters, decision-lineage walks, and cross-source unification with confidence-weighted ranking. The patterns below are written in Cypher; equivalent expressions in SQL (PG wire protocol) and the natural-language `db.query(...)` API exist for each.

### Pattern A — Bitemporal join with confidence threshold

Retrieve the *current state* of a customer plus the *most recent change* within a time window, weighted by feedback score, with provenance preserved:

```cypher
MATCH (c:Entity {entity_type: "customer", canonical_id: $cid})
OPTIONAL MATCH (c)-[:HAS_FACT]->(f_now:Fact)
  WHERE f_now.invalid_at IS NULL AND f_now.expired_at IS NULL
OPTIONAL MATCH (c)-[:HAS_FACT]->(f_recent:Fact)
  WHERE f_recent.created_at >= datetime($since)
    AND f_recent.invalid_at IS NULL
    AND f_recent.feedback_weight > $min_weight
WITH c,
     collect(DISTINCT f_now) AS current_state,
     collect(DISTINCT f_recent) AS recent_changes
RETURN c.canonical_id,
       [f IN current_state | {predicate: f.predicate, value: f.object, confidence: f.confidence}],
       [f IN recent_changes | {predicate: f.predicate, value: f.object,
                               recorded_at: f.created_at,
                               valid_from: f.valid_at,
                               source_episode: f.source_episode_id}]
```

**Execution plan.** The planner uses the `(canonical_id)` index on Entity, then expands `HAS_FACT` via the in-edges adjacency-list segments for the matched vertex. The two `OPTIONAL MATCH` clauses become parallel index scans on the bitemporal indexes (Section 5.3 of `05-contextd-native-db-implementation.md`): the partial index on `(subject_entity_id, predicate, expired_at IS NULL)` for the current-state filter, and the composite index on `(subject_entity_id, predicate, created_at desc, expired_at desc)` for the time-range query. Both terminate at the first matching row per predicate. The feedback-weight filter reads the inline 4-byte field from the record header (no additional I/O). End-to-end latency at 100M-fact scale: typically 5–15 ms.

### Pattern B — Decision lineage walk with policy version reconciliation

Trace every decision affecting a target entity in a quarter, joined with the policy version active at the time of each decision:

```cypher
MATCH (d:Decision)-[:AFFECTED]->(e:Entity {canonical_id: $entity_id})
WHERE d.decided_at >= datetime("2026-01-01")
  AND d.decided_at <  datetime("2026-04-01")
  AND d.expired_at IS NULL
MATCH (d)-[:DECIDED_BY]->(person:Entity)
MATCH (d)-[:APPLIED_POLICY]->(p:Entity {entity_type: "policy"})
  // Reconcile to the policy version active at decision time:
  WHERE p.valid_at <= d.decided_at
    AND (p.invalid_at IS NULL OR p.invalid_at > d.decided_at)
OPTIONAL MATCH (d)-[:INFORMED_BY]->(input)
WITH d, person, p, collect(input) AS inputs
RETURN d.subject, d.outcome,
       person.canonical_id AS decided_by,
       p.canonical_id AS policy, p.attributes.version AS policy_version,
       d.exception, d.justification,
       [i IN inputs | {kind: labels(i)[0], rid: i.id}] AS inputs
ORDER BY d.decided_at
```

**Execution plan.** The planner enters via the time-range index on Decision `(decision_type, decided_at desc, expired_at IS NULL)` and filters by the affected-entity edge after type-restriction. The `APPLIED_POLICY` traversal joins with the bitemporal predicate on Policy, requiring the planner to use the historical-state index on policies. The `INFORMED_BY` traversal enumerates inputs via the adjacency-list segment for the decision vertex; typical decisions have 3–8 inputs, so the segment fits in a single page. End-to-end latency: typically 10–30 ms for ~100 decisions in the quarter.

### Pattern C — Cross-source canonical-entity unification with evidence

For a single canonical entity, return every source identifier with its provenance, sorted by confidence:

```cypher
MATCH (c:Entity {canonical_id: $canonical_id})-[r:HAS_IDENTIFIER]->(id:Identifier)
WHERE r.invalid_at IS NULL
OPTIONAL MATCH (c)-[:HAS_FACT]->(f:Fact {predicate: "name"})
  WHERE f.expired_at IS NULL
RETURN c.canonical_id,
       collect(DISTINCT f.object)[0] AS reconciled_name,
       collect({source: id.source,
                source_id: id.source_id,
                confidence: r.confidence,
                evidence: r.evidence,
                added: r.created_at}) AS identifiers
ORDER BY confidence DESC
```

**Execution plan.** The Identity Graph's edge index `(canonical_id, source)` (Section 5.1 of `07-context-resolver.md`) returns identifiers in source order; the engine post-sorts by confidence. The `HAS_FACT` `OPTIONAL MATCH` for the name reconciliation hits the partial index on `expired_at IS NULL`. End-to-end latency: ~3–8 ms for an entity with 5–10 source identifiers.

### Pattern D — Audience cohort with cross-system behavioral filter

A churn-risk cohort: companies with high product usage, recent urgent support tickets, and no outreach in the last 14 days:

```cypher
MATCH (c:Entity {entity_type: "company"})-[:HAS_FACT]->(usage:Fact)
WHERE usage.predicate = "product_usage"
  AND usage.expired_at IS NULL
  AND usage.object IN ["high", "very_high"]
  AND EXISTS {
    MATCH (c)-[:FILED]->(t:Entity {entity_type: "ticket"})
    WHERE t.attributes.priority IN ["high", "urgent"]
      AND t.valid_at > datetime() - duration("P30D")
      AND t.invalid_at IS NULL
  }
  AND NOT EXISTS {
    MATCH (c)-[:CONTACTED_BY]->(o)
    WHERE o.valid_at > datetime() - duration("P14D")
      AND o.invalid_at IS NULL
  }
RETURN c.canonical_id, c.name, c.attributes.arr,
       count {
         MATCH (c)-[:FILED]->(t:Entity {entity_type: "ticket"})
         WHERE t.attributes.priority IN ["high", "urgent"]
           AND t.valid_at > datetime() - duration("P30D")
       } AS open_tickets
ORDER BY c.attributes.arr DESC
LIMIT 50
```

**Execution plan.** The planner uses the type-scoped index on `entity_type = "company"` to bound the outer scan, then the partial index on facts `expired_at IS NULL` to filter usage, then the existence-subquery clauses become anti-joins / semi-joins planned via the appropriate adjacency-list traversals. The `count {...}` subquery shares the same traversal as the existence check (single physical scan). End-to-end latency at 1 M-company scale: typically 50–200 ms depending on selectivity.

### Pattern E — Hybrid retrieval with cross-encoder reranking

A natural-language query that cannot be expressed in Cypher alone — combining BM25, cosine, and BFS with cross-encoder reranking and an explicit token budget:

```python
context = db.get_context(
    query="Acme renewal call: who, status, recent changes, decisions",
    max_tokens=1500,
    search_recipe="COMBINED_HYBRID_SEARCH_CROSS_ENCODER",
    rerank_top_k=50,
    include_lineage=True,
    feedback_weight_floor=0.4,
)
```

**Execution plan.** Three searches fan out concurrently: BM25 over the full-text inverted index for the literal "Acme renewal", cosine over the HNSW vector index against the query embedding, BFS from the seed entity *Acme Corp* with `max_depth=2`. Three result lists are RRF-fused into a single ranked list (Section 19.2 of `05-contextd-native-db-implementation.md`); the top-50 candidates are batched to the cross-encoder model server which returns relevance scores in ~1–2 ms RTT per batch. Final ranking multiplies the cross-encoder score by each item's inline feedback weight (Section 18.5). The token-budget pruner fills the 1500-token budget in priority order: primary entities, relationships, current facts, saga summary, decision lineage. Cross-encoder reranking adds ~5–10 ms versus pure RRF; total latency: ~80–150 ms p50 at 100M-entity scale.

### Pattern F — Contextual aggregation over the time-series engine

Retrieve a customer's per-day attribute-change rate over a window, with sub-second aggregation across N shards:

```python
result = db.timeseries.query(
    series="attribute_changes_by_canonical",
    canonical_id="cust_acme",
    from_ts=datetime(2026, 1, 1),
    to_ts=datetime(2026, 4, 28),
    aggregation="count",
    bucket="1d",
    tag_filter={"source": ["salesforce", "snowflake"]},
)
```

**Execution plan.** The query is fanned out across all shards (Section 14.1 of `05-contextd-native-db-implementation.md`); each shard scans its sealed segments whose timestamp range intersects the query window. SIMD-accelerated aggregation processes 256-512 samples per instruction. Mutable-bucket samples (those not yet sealed) are scanned linearly. Per-shard results are merge-sorted by timestamp and returned. End-to-end latency: typically 20–80 ms for a 4-month window across 4 shards.

---

## Performance characteristics summary

| Use case | Primary indexes used | Bitemporal? | LLM-touch on read | Typical p50 latency |
|----------|---------------------|:-----------:|:-----------------:|--------------------:|
| Customer 360 | name HNSW; canonical_id; bitemporal partial | yes | no | 100–200 ms |
| Decision audit (range query) | `(decision_type, decided_at desc, expired_at IS NULL)`; bitemporal policy index | yes | no | 5–30 ms per quarter window |
| Audience cohort | type-scoped + bitemporal + existence anti-joins | yes | no | 50–200 ms at 1 M company scale |
| RAG context window | BM25 + HNSW + BFS hybrid; cross-encoder rerank | yes | optional (cross-encoder) | 80–150 ms |
| Context Core CI/CD | content-addressed snapshot | n/a | no | seconds (build); ms (rollback pointer-swap) |
| Bitemporal supersession history | composite `(subject, predicate, valid_at desc)` | yes | no | ~5 ms per attribute |
| Incident postmortem | knowledge-state composite | yes | no | 10–40 ms |
| Forge-onboarded enterprise warehouse | deterministic Forge dispatch + LLM only on free-text | yes | yes (free-text only) | hours for full backfill of 1.2 B rows; ~5 ms p50 read after ingest |

---

*Continue to `13-integration-deployment-security.md` for SDK, MCP, wire protocols, deployment modes, and security details.*
