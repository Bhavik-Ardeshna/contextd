# ContextD — Query Examples & Outputs

Real-world queries organized by three core use cases: **Data 360**, **Audience Activation / Cohort Analysis**, and **Decision Auditing with Temporal Knowledge**.

---

## 1. Data 360 — Unified Entity View

360-degree visibility into any entity: current state, full relationship graph, timeline, and cross-source context assembly.

### 1.1 Entity Profile with Live Relationships

```python
result = db.query("Give me the full picture on Acme Corp")
```

```json
{
  "primary_entities": [
    {
      "rid": "#5:0",
      "entity_type": "organization",
      "name": "Acme Corp",
      "labels": ["enterprise", "technology"],
      "metadata": {"industry": "Technology", "employees": 5000, "revenue": "$250M", "hq": "San Francisco"},
      "feedback_weight": 0.91,
      "valid_at": "2026-01-05T08:00:00Z",
      "invalid_at": null,
      "is_current": true
    }
  ],
  "relationships": [
    {"from": "Acme Corp", "to": "Acme Enterprise Deal", "type": "HAS_DEAL", "fact": "Enterprise deal for 500 seats", "feedback_weight": 0.88},
    {"from": "Sarah Chen", "to": "Acme Corp", "type": "WORKS_FOR", "fact": "Sarah Chen is VP Engineering at Acme", "feedback_weight": 0.93},
    {"from": "Acme Corp", "to": "Infrastructure Migration", "type": "EVALUATING", "fact": "Acme is evaluating our platform for internal migration", "feedback_weight": 0.74},
    {"from": "Acme Corp", "to": "Beta Corp", "type": "COMPETES_WITH", "fact": "Acme and Beta Corp compete in the same vertical", "feedback_weight": 0.67}
  ],
  "facts": [
    {"subject": "Acme Corp", "predicate": "industry", "object": "Technology"},
    {"subject": "Acme Corp", "predicate": "annual_budget", "object": "$2.1M (estimated)"},
    {"subject": "Acme Corp", "predicate": "churn_risk", "object": "low"},
    {"subject": "Acme Corp", "predicate": "nps_score", "object": "72"}
  ],
  "saga_summary": "Acme Corp is a $250M technology company with 5,000 employees. Currently negotiating a 500-seat enterprise deal. Key contacts: Sarah Chen (VP Eng, champion), Marcus Rivera (Dir. Procurement, neutral), Lisa Wong (CFO, skeptical). NPS score 72, low churn risk. Also evaluating platform for internal infrastructure migration.",
  "sources": [
    {"name": "Salesforce Account Sync", "source": "salesforce", "date": "2026-04-20"},
    {"name": "Q1 Business Review", "source": "confluence", "date": "2026-03-28"},
    {"name": "Email: Re partnership discussion", "source": "gmail", "date": "2026-04-15"}
  ],
  "metadata": {
    "tokens_used": 1847,
    "tokens_saved": 7353,
    "avg_feedback_weight": 0.84,
    "query_latency_ms": 45
  }
}
```

### 1.2 Cross-Source Timeline — Full Audit Trail

Every touchpoint across CRM, email, Slack, support tickets, and internal docs in chronological order.

```python
result = db.get_timeline(entity_id="entity_acme_001")
```

```json
{
  "entity": "Acme Corp",
  "timeline": [
    {"date": "2026-01-05", "event": "created", "detail": "Account imported from Salesforce", "source": "salesforce"},
    {"date": "2026-01-10", "event": "contact_added", "detail": "Sarah Chen added via LinkedIn sync", "source": "salesforce"},
    {"date": "2026-02-15", "event": "deal_created", "detail": "Enterprise Deal created — $500K, 500 seats", "source": "salesforce"},
    {"date": "2026-02-20", "event": "contact_added", "detail": "Marcus Rivera added from Slack #acme channel", "source": "slack"},
    {"date": "2026-03-01", "event": "stage_change", "detail": "Deal moved from Discovery → Negotiation", "source": "gmail"},
    {"date": "2026-03-10", "event": "sentiment_shift", "detail": "Sarah Chen's sentiment: neutral → positive after demo", "source": "zoom"},
    {"date": "2026-03-12", "event": "pricing_change", "detail": "$45 → $38/user/month proposed", "source": "gmail"},
    {"date": "2026-03-28", "event": "risk_flag", "detail": "Lisa Wong (CFO) raised budget concerns", "source": "confluence"},
    {"date": "2026-04-02", "event": "decision", "detail": "Approved 15% discount + net-60 terms (exception to net-30 policy)", "source": "internal"},
    {"date": "2026-04-10", "event": "agreement", "detail": "Acme agreed to revised pricing structure", "source": "gmail"},
    {"date": "2026-04-18", "event": "objection", "detail": "Marcus Rivera requested 2 more weeks for procurement review", "source": "zoom"},
    {"date": "2026-04-22", "event": "support_ticket", "detail": "Acme reported integration issue with their SSO provider", "source": "zendesk"}
  ],
  "total_events": 12,
  "date_range": "2026-01-05 → 2026-04-22"
}
```

### 1.3 Decision Lineage — Trace Why Something Was Decided

```python
result = db.get_decision_lineage(entity_id="decision_discount_15pct")
```

```json
{
  "decision": {
    "subject": "Acme 15% volume discount",
    "outcome": "Approved 15% discount with net-60 payment terms",
    "reasoning": "Acme qualifies for volume discount on 500+ seats. Competitive pressure from VendorX justifies extended terms. Customer sentiment is positive, reducing churn risk.",
    "decided_at": "2026-04-02T11:00:00Z"
  },
  "decided_by": {
    "name": "Jordan Blake",
    "role": "VP Sales"
  },
  "informed_by": [
    {"name": "Acme deal economics spreadsheet", "type": "document", "feedback_weight": 0.92},
    {"name": "Competitor pricing analysis — VendorX offering 18% discount", "type": "report", "feedback_weight": 0.87},
    {"name": "Customer sentiment report Q1 — positive trend", "type": "report", "feedback_weight": 0.79}
  ],
  "applied_policy": {
    "name": "volume_discount_policy_v3",
    "version": "3.2",
    "effective_date": "2025-09-01"
  },
  "exception": "Extended payment terms to net-60 (standard policy is net-30)",
  "justification": "Strategic account with active competitive pressure from VendorX",
  "downstream_impact": [
    {"entity": "Acme Enterprise Deal", "impact": "Pricing revised from $45 to $38/user/month"},
    {"entity": "Q2 Revenue Forecast", "impact": "Reduced by $15K for this account"},
    {"entity": "Procurement Review", "impact": "Marcus Rivera requested extended review timeline"}
  ]
}
```

### 1.4 Context Assembly for AI Agent — Token-Efficient 360

```python
context = db.get_context(
    query="Draft a follow-up email to Acme after the pricing agreement",
    max_tokens=2000,
    include_lineage=True,
)
```

```json
{
  "primary_entities": [
    {"name": "Acme Corp", "type": "organization", "key_attrs": {"industry": "Technology", "revenue": "$250M", "nps": 72}},
    {"name": "Sarah Chen", "type": "person", "key_attrs": {"role": "VP Engineering", "sentiment": "positive"}},
    {"name": "Marcus Rivera", "type": "person", "key_attrs": {"role": "Dir. Procurement", "sentiment": "neutral"}},
    {"name": "Lisa Wong", "type": "person", "key_attrs": {"role": "CFO", "sentiment": "skeptical"}}
  ],
  "facts": [
    "Deal stage: Negotiation — pricing agreed at $38/seat (15% discount, net-60 terms)",
    "Sarah Chen confirmed agreement on revised pricing (positive sentiment)",
    "Marcus Rivera requested 2 more weeks for procurement review",
    "Lisa Wong raised budget concerns in Q1 business review",
    "VendorX is offering 18% discount — competitive pressure"
  ],
  "decision_history": [
    {"subject": "Acme discount", "outcome": "15% + net-60", "decided_by": "Jordan Blake (VP Sales)", "exception": "net-60 vs standard net-30"}
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

---

## 2. Audience Activation / Cohort Analysis

Segment, activate, and analyze groups of entities by behavior, attributes, temporal state, and feedback signals.

### 2.1 Find High-Value Accounts at Risk of Churn

```python
result = db.query("Which enterprise accounts are most likely to churn this quarter?")
```

```json
{
  "primary_entities": [
    {
      "name": "Beta Corp",
      "type": "organization",
      "key_attrs": {
        "churn_risk": "high",
        "contract_renewal": "2026-06-01",
        "nps": 31,
        "seat_count": 200,
        "arr": "$840K"
      },
      "feedback_weight": 0.72
    },
    {
      "name": "Gamma Industries",
      "type": "organization",
      "key_attrs": {
        "churn_risk": "high",
        "contract_renewal": "2026-07-15",
        "nps": 28,
        "seat_count": 140,
        "arr": "$560K"
      },
      "feedback_weight": 0.68
    },
    {
      "name": "Delta Systems",
      "type": "organization",
      "key_attrs": {
        "churn_risk": "medium",
        "contract_renewal": "2026-08-30",
        "nps": 45,
        "seat_count": 85,
        "arr": "$340K"
      },
      "feedback_weight": 0.61
    }
  ],
  "facts": [
    "Beta Corp: VP Engineering expressed frustration with API latency in March — 3 support tickets open",
    "Gamma Industries: Reduced seat count from 200 to 140 in Q1 (30% contraction)",
    "Delta Systems: Mixed signals — positive on product, negative on support response time"
  ],
  "relationships": [
    {"from": "Beta Corp", "to": "API Latency Investigation", "type": "REPORTED_ISSUE", "fact": "3 open P2 tickets on API latency"},
    {"from": "Gamma Industries", "to": "Seat Contraction", "type": "CONTRACT_CHANGE", "fact": "Reduced from 200 to 140 seats effective 2026-03-01"},
    {"from": "Delta Systems", "to": "Support Escalation", "type": "REPORTED_ISSUE", "fact": "Average support response time 48hrs vs SLA 24hrs"}
  ]
}
```

### 2.2 Cohort: All Decision-Makers with Positive Sentiment

```python
result = db.query("List all decision-makers across accounts who have positive sentiment toward us", config=NODE_HYBRID_SEARCH_RRF)
```

```json
{
  "primary_entities": [
    {"name": "Sarah Chen", "type": "person", "key_attrs": {"role": "VP Engineering", "company": "Acme Corp", "sentiment": "positive", "influence": "high"}},
    {"name": "James Park", "type": "person", "key_attrs": {"role": "CTO", "company": "Omega Labs", "sentiment": "positive", "influence": "high"}},
    {"name": "Aisha Patel", "type": "person", "key_attrs": {"role": "VP Product", "company": "Nova Digital", "sentiment": "positive", "influence": "medium"}},
    {"name": "Robert Kim", "type": "person", "key_attrs": {"role": "Director of Engineering", "company": "Sigma AI", "sentiment": "positive", "influence": "medium"}}
  ],
  "facts": [
    "Sarah Chen confirmed agreement on pricing — strong champion",
    "James Park presented our solution at their internal tech summit",
    "Aisha Patel requested a roadmap session — engaged but not yet committed",
    "Robert Kim's team completed a successful POC — awaiting board approval"
  ],
  "metadata": {
    "cohort_size": 4,
    "avg_feedback_weight": 0.86,
    "search_recipe": "node_hybrid_rrf",
    "query_latency_ms": 29
  }
}
```

### 2.3 Cohort: Accounts in Negotiation Stage Needing Attention

```python
result = db.query("Show all deals in negotiation stage that haven't had activity in 7+ days")
```

```json
{
  "primary_entities": [
    {
      "name": "Acme Enterprise Deal",
      "type": "deal",
      "key_attrs": {"stage": "Negotiation", "amount": "$500K", "last_activity": "2026-04-18", "days_inactive": 6},
      "feedback_weight": 0.82
    },
    {
      "name": "Omega Labs Expansion",
      "type": "deal",
      "key_attrs": {"stage": "Negotiation", "amount": "$320K", "last_activity": "2026-04-10", "days_inactive": 14},
      "feedback_weight": 0.71
    },
    {
      "name": "Gamma Industries Renewal",
      "type": "deal",
      "key_attrs": {"stage": "Negotiation", "amount": "$560K", "last_activity": "2026-04-08", "days_inactive": 16},
      "feedback_weight": 0.55
    }
  ],
  "facts": [
    "Omega Labs: No response to follow-up email sent Apr 10th — James Park (champion) is OOO",
    "Gamma Industries: Contracted 30% in Q1. Marcus Rivera equivalent requested extended review. Risk of non-renewal.",
    "Acme: Stable but Marcus Rivera requested 2-week procurement review extension"
  ],
  "suggested_actions": [
    "Omega Labs: Reach out to James Park's backup contact (Angela Torres, VP Eng Ops)",
    "Gamma Industries: Schedule executive sponsor call — consider retention offer",
    "Acme: Follow up on procurement review timeline with Marcus Rivera"
  ]
}
```

### 2.4 Cohort by Temporal Behavior — Recently Activated Users

```python
result = db.query("Which contacts became active in the last 30 days after being dormant for 60+ days?")
```

```json
{
  "primary_entities": [
    {
      "name": "Lisa Wong",
      "type": "person",
      "key_attrs": {"role": "CFO", "company": "Acme Corp"},
      "temporal_state": {
        "dormant_from": "2025-11-01",
        "dormant_until": "2026-03-10",
        "reactivated_at": "2026-03-10",
        "dormancy_days": 129,
        "reactivation_trigger": "Q1 business review — raised budget concerns"
      }
    },
    {
      "name": "Derek Hassan",
      "type": "person",
      "key_attrs": {"role": "Head of Security", "company": "Beta Corp"},
      "temporal_state": {
        "dormant_from": "2025-12-15",
        "dormant_until": "2026-04-05",
        "reactivated_at": "2026-04-05",
        "dormancy_days": 111,
        "reactivation_trigger": "Security posture review — requested compliance documentation"
      }
    }
  ],
  "facts": [
    "Lisa Wong: Active Nov 2025 → dormant → reactivated Mar 2026. Initially raised pricing concerns, now raising budget alignment questions.",
    "Derek Hassan: Active until Dec 2025, went dormant after trial phase. Reactivated after their security audit found compliance gaps."
  ]
}
```

### 2.5 Audience Activation — Cohort for Campaign

```python
context = db.get_context(
    query="Build audience for Q2 enterprise upsell campaign",
    max_tokens=3000,
    include_lineage=False,
)
```

```json
{
  "primary_entities": [
    {
      "cohort_id": "q2_enterprise_upsell",
      "criteria": "Enterprise accounts, NPS > 50, active in last 30 days, contract renewal in next 90 days",
      "size": 23,
      "total_arr": "$8.4M"
    }
  ],
  "segments": [
    {
      "segment": "Expansion Ready",
      "size": 8,
      "signal": "Champion actively engaged + POC completed + positive sentiment",
      "avg_nps": 72,
      "accounts": ["Acme Corp", "Omega Labs", "Nova Digital"]
    },
    {
      "segment": "Nurture Required",
      "size": 10,
      "signal": "Mixed signals or neutral sentiment + recent activity",
      "avg_nps": 55,
      "accounts": ["Delta Systems", "Epsilon Group", "Zeta Cloud"]
    },
    {
      "segment": "At Risk",
      "size": 5,
      "signal": "Negative sentiment + seat contraction or open support tickets",
      "avg_nps": 31,
      "accounts": ["Beta Corp", "Gamma Industries"]
    }
  ],
  "activation_signals": [
    "Acme Corp: Sarah Chen (VP Eng) confirmed pricing — ready for contract close",
    "Omega Labs: James Park (CTO) presented solution internally — expansion opportunity",
    "Beta Corp: 3 open P2 tickets — resolve before upsell outreach"
  ],
  "metadata": {
    "tokens_used": 2840,
    "tokens_saved": 11360,
    "query_latency_ms": 78
  }
}
```

### 2.6 Cypher: Feedback-Weighted Cohort Ranking

```cypher
MATCH (p:Entity {entity_type: "person"})-[r:STAKEHOLDER]->(d:Entity {entity_type: "deal"})
WHERE p.feedback_weight > 0.7 AND d.metadata.stage = "Negotiation"
RETURN p.name, p.metadata.role, p.metadata.sentiment, p.feedback_weight, d.name AS deal
ORDER BY p.feedback_weight DESC
```

```
┌─────────────────┬─────────────────────────┬───────────┬──────────────────┬──────────────────────┐
│ p.name          │ role                    │ sentiment │ feedback_weight   │ deal                 │
├─────────────────┼─────────────────────────┼───────────┼──────────────────┼──────────────────────┤
│ Sarah Chen      │ VP Engineering          │ positive  │ 0.91             │ Acme Enterprise Deal │
│ Jordan Blake    │ Account Executive        │ positive  │ 0.86             │ Acme Enterprise Deal │
│ James Park      │ CTO                     │ positive  │ 0.84             │ Omega Labs Expansion │
│ Marcus Rivera   │ Dir. Procurement        │ neutral   │ 0.73             │ Acme Enterprise Deal │
└─────────────────┴─────────────────────────┴───────────┴──────────────────┴──────────────────────┘
4 rows (feedback_weight > 0.7, deal stage = Negotiation)
```

---

## 3. Decision Auditing with Temporal Knowledge

Bitemporal queries that answer: What was true? When did we know it? Who decided based on what information? When did facts change?

### 3.1 Current State vs. Historical vs. Knowledge State

Three temporal perspectives on the same question.

**Current State — Who owns this account right now?**

```python
result = db.query("Who is the current account owner for Acme?")
```

```json
{
  "result": {
    "name": "Jordan Blake",
    "role": "Account Executive",
    "valid_at": "2026-03-01T09:00:00Z",
    "invalid_at": null,
    "expired_at": null,
    "is_current": true
  },
  "temporal_filter": "invalid_at IS NULL AND expired_at IS NULL"
}
```

**Historical State — Who owned this account on March 15th?**

```python
result = db.query("Who was the account owner for Acme on March 15th, 2026?")
```

```json
{
  "result": {
    "name": "Priya Sharma",
    "role": "Account Executive",
    "valid_at": "2026-01-05T10:00:00Z",
    "invalid_at": "2026-03-20T16:00:00Z",
    "expired_at": "2026-03-20T16:00:00Z",
    "note": "Priya owned the account until March 20th. After that, Jordan Blake took over."
  },
  "temporal_filter": "valid_at <= '2026-03-15' AND (invalid_at IS NULL OR invalid_at > '2026-03-15')",
  "superseded_by": {
    "name": "Jordan Blake",
    "valid_from": "2026-03-20T16:00:00Z"
  }
}
```

**Knowledge State — What did we know about Acme's budget before the CFO email?**

```python
result = db.query("What did we know about Acme's budget before the CFO email on April 8th?")
```

```json
{
  "result": {
    "facts_known_before_april_8": [
      {"fact": "Acme estimated annual budget: $2.1M (from prior year public filing)", "recorded_at": "2026-02-20T08:00:00Z", "source": "salesforce"},
      {"fact": "Deal size discussed: $500K for 500 seats", "recorded_at": "2026-02-15T10:30:00Z", "source": "salesforce"}
    ],
    "facts_recorded_after": [
      {"fact": "CFO Lisa Wong stated budget ceiling is $1.8M, not $2.1M", "recorded_at": "2026-04-08T14:30:00Z", "source": "gmail"},
      {"fact": "Budget concerns raised about per-seat pricing exceeding $40/user", "recorded_at": "2026-04-08T14:30:00Z", "source": "gmail"}
    ],
    "impact": "Decision to offer 15% discount was made AFTER the CFO's email revealed the true budget. Without this knowledge, we would have proposed $45/user/month instead of $38.",
    "temporal_filter": "created_at <= '2026-04-08T00:00:00Z'",
    "total_facts_at_that_time": 2,
    "total_facts_now": 4
  }
}
```

### 3.2 Audit Trail — When Did We First Record This Pricing Change?

```python
result = db.query("When was the Acme pricing change from $45 to $38 first recorded?")
```

```json
{
  "result": {
    "fact": "Pricing changed from $45 to $38 per user per month",
    "subject": "Acme Enterprise Deal",
    "predicate": "pricing_change",
    "first_recorded_at": "2026-03-12T14:30:00Z",
    "recorded_by": "gmail_connector",
    "source_episode": "Email: Re: Updated Pricing for Enterprise Plan",
    "extraction_method": "llm_gpt4",
    "superseded_fact": {
      "previous_value": "$45/user/month",
      "superseded_at": "2026-03-12T14:30:00Z"
    }
  }
}
```

### 3.3 Decision Audit — Full Provenance Chain

Trace every decision: what information was available, what policy was applied, whether exceptions were made, and what downstream impact occurred.

```python
result = db.get_decision_lineage(entity_id="decision_discount_15pct")
```

```json
{
  "decision": {
    "subject": "Acme 15% volume discount",
    "outcome": "Approved 15% discount with net-60 payment terms",
    "reasoning": "Acme qualifies for volume discount on 500+ seats. Competitive pressure from VendorX justifies extended terms. Customer sentiment is positive, reducing churn risk.",
    "decided_by": "Jordan Blake (VP Sales)",
    "decided_at": "2026-04-02T11:00:00Z",
    "policy_applied": "volume_discount_policy_v3 (v3.2, effective 2025-09-01)"
  },
  "information_available_at_decision_time": [
    {
      "fact": "Opportunity size: 500 seats, $500K ARR",
      "source": "salesforce_connector",
      "recorded_at": "2026-02-15T10:30:00Z",
      "feedback_weight": 0.92
    },
    {
      "fact": "VendorX offering 18% discount to same account",
      "source": "competitive_intel",
      "recorded_at": "2026-03-25T09:00:00Z",
      "feedback_weight": 0.87
    },
    {
      "fact": "Sarah Chen (VP Eng) sentiment: positive",
      "source": "zoom_connector",
      "recorded_at": "2026-03-10T16:00:00Z",
      "feedback_weight": 0.84
    },
    {
      "fact": "CFO Lisa Wong raised budget concerns — ceiling is $1.8M",
      "source": "gmail_connector",
      "recorded_at": "2026-04-08T14:30:00Z — Recorded AFTER the discount decision, not available at decision time",
      "feedback_weight": 0.79
    }
  ],
  "exception": {
    "policy": "Standard payment terms: net-30",
    "exception_granted": "net-60",
    "justification": "Strategic account with active competitive pressure from VendorX",
    "approved_by": "Jordan Blake (VP Sales)"
  },
  "downstream_impact": [
    {"entity": "Acme Enterprise Deal", "impact": "Pricing revised from $45 to $38/user/month"},
    {"entity": "Q2 Revenue Forecast", "impact": "Reduced by $15K for this account"},
    {"entity": "Marcus Rivera (Dir. Procurement)", "impact": "Requested extended procurement review timeline"}
  ],
  "what_we_didnt_know": [
    "Lisa Wong's $1.8M budget ceiling was recorded AFTER the decision. Had we known, we might have structured pricing differently."
  ]
}
```

### 3.4 Temporal Comparison — How Has This Account Changed?

```python
result = db.query("How has the Acme deal changed from January to now?")
```

```json
{
  "entity": "Acme Enterprise Deal",
  "temporal_comparison": [
    {
      "as_of": "2026-01-15",
      "snapshot": {
        "stage": "Discovery",
        "amount": "$500K",
        "pricing": "$45/user/month",
        "contacts_known": 1,
        "sentiment": "neutral",
        "open_items": ["Initial discovery meeting scheduled"]
      }
    },
    {
      "as_of": "2026-02-15",
      "snapshot": {
        "stage": "Discovery",
        "amount": "$500K",
        "pricing": "$45/user/month (proposed)",
        "contacts_known": 3,
        "sentiment": "neutral → mixed",
        "open_items": ["Sarah Chen added as stakeholder", "Marcus Rivera added from Slack"]
      }
    },
    {
      "as_of": "2026-03-15",
      "snapshot": {
        "stage": "Negotiation",
        "amount": "$500K",
        "pricing": "$45/user/month (under negotiation)",
        "contacts_known": 4,
        "sentiment": "positive (Sarah), neutral (Marcus), skeptical (Lisa)",
        "open_items": ["Pricing revision proposed", "Lisa Wong raised budget concerns"]
      }
    },
    {
      "as_of": "2026-04-24",
      "snapshot": {
        "stage": "Negotiation",
        "amount": "$380K (after 15% discount)",
        "pricing": "$38/user/month (agreed)",
        "contacts_known": 4,
        "sentiment": "positive (Sarah), neutral (Marcus), skeptical (Lisa)",
        "open_items": ["Contract legal review pending", "Marcus Rivera's procurement review due May 2nd", "SSO integration issue open"]
      }
    }
  ],
  "key_transitions": [
    {"date": "2026-03-01", "change": "Stage: Discovery → Negotiation"},
    {"date": "2026-03-12", "change": "Pricing: $45 → $38/user/month proposed"},
    {"date": "2026-04-02", "change": "Discount: 15% approved with net-60 exception"},
    {"date": "2026-04-10", "change": "Pricing agreement: Acme agreed to revised structure"}
  ]
}
```

### 3.5 Audit: Who Knew What and When?

Critical for compliance, legal disputes, and post-incident reviews.

```python
result = db.query("What information was available to the team before the discount was approved on April 2nd?")
```

```json
{
  "as_of": "2026-04-02T11:00:00Z",
  "facts_known_at_decision_time": [
    {"fact": "Opportunity: 500 seats, $500K ARR", "source": "salesforce", "recorded": "2026-02-15"},
    {"fact": "Sarah Chen sentiment: positive", "source": "zoom", "recorded": "2026-03-10"},
    {"fact": "Marcus Rivera sentiment: neutral", "source": "slack", "recorded": "2026-02-20"},
    {"fact": "VendorX offering 18% discount", "source": "competitive_intel", "recorded": "2026-03-25"},
    {"fact": "Volume discount policy allows up to 20% for 500+ seats", "source": "confluence", "recorded": "2025-09-01"},
    {"fact": "Previous deal with Acme had net-30 terms", "source": "salesforce", "recorded": "2025-06-15"}
  ],
  "facts_NOT_known_at_decision_time": [
    {
      "fact": "CFO budget ceiling is $1.8M, not $2.1M",
      "source": "gmail",
      "recorded": "2026-04-08 — 6 days AFTER the decision",
      "impact": "Deal is actually at $380K after discount, well within the true budget"
    },
    {
      "fact": "Marcus Rivera requested extended procurement review",
      "source": "zoom",
      "recorded": "2026-04-18 — 16 days AFTER the decision"
    }
  ],
  "decision": {
    "made_on": "2026-04-02T11:00:00Z",
    "based_on": "6 facts available at that time",
    "gaps": "2 material facts recorded later — CFO budget ceiling and procurement delay"
  }
}
```

### 3.6 Superseded Fact Chain — How Knowledge Evolved

```python
result = db.query("Trace how the deal stage for Acme has changed over time")
```

```json
{
  "entity": "Acme Enterprise Deal",
  "fact_chain": [
    {
      "predicate": "deal_stage",
      "value": "Discovery",
      "valid_from": "2026-02-15T10:30:00Z",
      "superseded_at": "2026-03-01T09:00:00Z",
      "source": "salesforce",
      "superseded_by": "fact_chain[1]"
    },
    {
      "predicate": "deal_stage",
      "value": "Negotiation",
      "valid_from": "2026-03-01T09:00:00Z",
      "superseded_at": null,
      "source": "gmail",
      "superseded_by": null,
      "is_current": true
    }
  ],
  "pricing_chain": [
    {
      "predicate": "pricing",
      "value": "$45/user/month (proposed)",
      "valid_from": "2026-02-15T10:30:00Z",
      "superseded_at": "2026-03-12T14:30:00Z",
      "source": "salesforce"
    },
    {
      "predicate": "pricing",
      "value": "$38/user/month (proposed)",
      "valid_from": "2026-03-12T14:30:00Z",
      "superseded_at": "2026-04-10T08:30:00Z",
      "source": "gmail"
    },
    {
      "predicate": "pricing",
      "value": "$38/user/month (agreed)",
      "valid_from": "2026-04-10T08:30:00Z",
      "superseded_at": null,
      "is_current": true,
      "source": "gmail"
    }
  ],
  "account_ownership_chain": [
    {
      "predicate": "account_owner",
      "value": "Priya Sharma",
      "valid_from": "2026-01-05T10:00:00Z",
      "invalid_at": "2026-03-20T16:00:00Z",
      "source": "salesforce"
    },
    {
      "predicate": "account_owner",
      "value": "Jordan Blake",
      "valid_from": "2026-03-20T16:00:00Z",
      "invalid_at": null,
      "is_current": true,
      "source": "salesforce"
    }
  ]
}
```

### 3.7 Compliance Audit — Decision Trail for Data Retention Policy

```python
result = db.get_decision_lineage(entity_id="decision_data_retention_update")
```

```json
{
  "decision": {
    "subject": "Reduce data retention from 7 years to 3 years",
    "outcome": "Approved with exception: financial records retain 7-year retention per SOX",
    "reasoning": "Reduced storage costs ($1.2M/year savings) with GDPR-compliant 3-year default. Financial exception required for SOX compliance.",
    "decided_by": "Rachel Torres (General Counsel)",
    "decided_at": "2026-03-15T14:00:00Z",
    "policy_applied": "GDPR compliance framework v4"
  },
  "informed_by": [
    {"fact": "GDPR compliance audit results: 3-year minimum retention is compliant", "source": "legal_audit", "recorded": "2026-02-28", "feedback_weight": 0.92},
    {"fact": "Storage cost analysis: $1.2M/year savings with 3-year retention", "source": "finops_report", "recorded": "2026-03-01", "feedback_weight": 0.88},
    {"fact": "Legal risk assessment: low risk with financial exception", "source": "legal_review", "recorded": "2026-03-10", "feedback_weight": 0.91},
    {"fact": "SOX requirement: financial records must retain 7-year minimum", "source": "compliance_policy", "recorded": "2025-01-01", "feedback_weight": 0.95}
  ],
  "exception": {
    "policy": "Default 3-year retention",
    "exception": "Financial records: 7-year retention",
    "justification": "SOX compliance requirement",
    "scope": "All financial transaction records, audit logs, and tax documents"
  },
  "downstream_impact": [
    {"entity": "Data Retention Policy v2.1", "impact": "Published with dual retention schedule"},
    {"entity": "Storage Infrastructure", "impact": "$1.2M/year cost reduction effective Q3 2026"},
    {"entity": "Engineering Team", "impact": "Backlog item: implement tiered retention by data classification"}
  ]
}
```

### 3.8 Incident Postmortem Audit — What Did We Know Before the Outage?

```python
result = db.query("What did we know about the auth-service issues before the April 12th incident?")
```

```json
{
  "as_of": "2026-04-12T00:00:00Z",
  "known_before_incident": [
    {"fact": "auth-service memory limit at 80% after config change on April 8th", "source": "monitoring", "recorded": "2026-04-08T10:00:00Z", "severity": "WARNING"},
    {"fact": "Config change increased cache from 2GB to 4GB on April 8th", "source": "deploy_log", "recorded": "2026-04-08T09:30:00Z", "severity": "INFO"},
    {"fact": "Peer code review approved the config change", "source": "github", "recorded": "2026-04-08T09:15:00Z", "severity": "INFO"}
  ],
  "known_after_incident": [
    {"fact": "auth-service OOM caused cascading 502 errors for 45 minutes", "source": "incident_report", "recorded": "2026-04-12T14:45:00Z", "severity": "P1"},
    {"fact": "12,547 requests affected during outage", "source": "monitoring", "recorded": "2026-04-12T15:00:00Z", "severity": "P1"},
    {"fact": "Root cause: cache size exceeded available memory after traffic spike", "source": "postmortem", "recorded": "2026-04-14T10:00:00Z", "severity": "P1"}
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
      "based_on": "Peer code review approved, assumed headroom in memory allocation",
      "exception": "No load testing was performed for the new cache size under peak traffic conditions"
    }
  ]
}
```

---

## 4. Ingestion — Feeding the Context Graph

How data enters ContextD from different sources. Each ingestion triggers a 10-step pipeline: entity extraction, resolution, edge extraction, fact extraction, community detection, ontology validation, embedding generation, feedback initialization, and index update.

### 4.1 Email Ingestion

```python
result = await db.ingest_episode(
    name="Client Email Thread",
    content="Subject: Re: Q2 Proposal... Hi Acme team, we've reviewed the updated pricing and would like to proceed with the 500-seat enterprise plan...",
    source="gmail",
    reference_time=datetime(2026, 4, 18),
    saga="acme-deal-negotiation",
)
```

```json
{
  "success": true,
  "episode_id": "#55:40",
  "nodes_created": 6,
  "edges_created": 4,
  "facts_extracted": 8,
  "entities": [
    {"rid": "#12:3", "entity_type": "person", "name": "Sarah Chen", "extraction_method": "existing_resolved"},
    {"rid": "#14:15", "entity_type": "concept", "name": "Q2 Proposal", "extraction_method": "llm_gpt4"},
    {"rid": "#14:17", "entity_type": "event", "name": "Intent to Proceed", "extraction_method": "llm_gpt4"}
  ],
  "relationships": [
    {"from": "Sarah Chen", "to": "Q2 Proposal", "type": "DISCUSSED", "fact": "Sarah Chen confirmed interest in proceeding"},
    {"from": "Q2 Proposal", "to": "Acme Enterprise Deal", "type": "RELATES_TO", "fact": "Q2 proposal is part of the enterprise deal"}
  ],
  "facts": [
    "Acme reviewed updated pricing — positive signal",
    "Intent to proceed with 500-seat enterprise plan",
    "Sarah Chen confirmed on behalf of Acme engineering team"
  ],
  "processing_time_ms": 2850
}
```

### 4.2 Slack Ingestion

```python
result = await db.ingest_episode(
    name="#engineering Standup",
    content="<@alex> The deployment is blocked on the DB migration. Payment-service staging is ready but can't go live until the migration completes.",
    source="slack",
    reference_time=datetime(2026, 4, 20, 9, 0),
    saga="infrastructure-migration",
)
```

```json
{
  "success": true,
  "episode_id": "#55:42",
  "nodes_created": 5,
  "edges_created": 3,
  "facts_extracted": 6,
  "entities": [
    {"rid": "#18:3", "entity_type": "person", "name": "Alex Thompson", "extraction_method": "existing_resolved"},
    {"rid": "#18:7", "entity_type": "service", "name": "payment-service", "extraction_method": "existing_resolved"},
    {"rid": "#17:5", "entity_type": "concept", "name": "DB migration blocker", "extraction_method": "llm_gpt4"}
  ],
  "relationships": [
    {"from": "Alex Thompson", "to": "DB migration blocker", "type": "REPORTED", "fact": "Alex reported deployment blocked on DB migration"},
    {"from": "DB migration blocker", "to": "payment-service", "type": "BLOCKS", "fact": "DB migration is blocking payment-service from going live"}
  ],
  "facts": [
    "Deployment is blocked on DB migration",
    "Payment-service staging is ready but blocked",
    "Alex Thompson reported the blocker at standup"
  ],
  "processing_time_ms": 1920
}
```

### 4.3 Jira Incident Ingestion

```python
result = await db.ingest_episode(
    name="BUG-4521: Auth timeout causing 502 errors",
    content="Users reporting 502 errors during peak hours. Root cause: auth-service OOM after config change increased cache to 4GB. Impact: 45 min downtime, 12K affected requests.",
    source="jira",
    reference_time=datetime(2026, 4, 12),
    saga="incident-auth-oom",
)
```

```json
{
  "success": true,
  "episode_id": "#55:46",
  "nodes_created": 5,
  "edges_created": 4,
  "facts_extracted": 7,
  "entities": [
    {"rid": "#18:5", "entity_type": "service", "name": "auth-service", "extraction_method": "existing_resolved"},
    {"rid": "#16:20", "entity_type": "vulnerability", "name": "auth-service OOM incident", "extraction_method": "llm_gpt4"},
    {"rid": "#16:22", "entity_type": "event", "name": "502 error reports", "extraction_method": "llm_gpt4"}
  ],
  "relationships": [
    {"from": "auth-service OOM incident", "to": "auth-service", "type": "AFFECTS", "fact": "OOM incident affected auth-service"},
    {"from": "502 error reports", "to": "auth-service OOM incident", "type": "CAUSED_BY", "fact": "502 errors were caused by the OOM incident"}
  ],
  "facts": [
    "auth-service experienced OOM after cache size increase to 4GB",
    "45 minute downtime, 12,547 affected requests",
    "Root cause: config change on April 8th increased cache from 2GB to 4GB"
  ],
  "processing_time_ms": 1650
}
```

### 4.4 Confluence Decision Record Ingestion

```python
result = await db.ingest_episode(
    name="ADR-012: Migration to Event-Driven Architecture",
    content="Decision: We will migrate from synchronous microservices to event-driven architecture using Kafka. Rationale: Current sync calls create cascading failures. Approved by: Sarah Chen (VP Eng). Exception: Payment service stays synchronous until Q3 audit.",
    source="confluence",
    reference_time=datetime(2026, 3, 28),
    saga="infrastructure-migration",
)
```

```json
{
  "success": true,
  "episode_id": "#55:48",
  "nodes_created": 8,
  "edges_created": 5,
  "facts_extracted": 12,
  "entities": [
    {"rid": "#25:10", "entity_type": "policy", "name": "ADR-012: Event-Driven Architecture Migration", "extraction_method": "llm_gpt4"},
    {"rid": "#18:0", "entity_type": "project", "name": "Infrastructure Migration to Kubernetes", "extraction_method": "existing_resolved"}
  ],
  "relationships": [
    {"from": "ADR-012", "to": "Infrastructure Migration", "type": "INFORMS", "fact": "ADR-012 informs the infrastructure migration strategy"},
    {"from": "Sarah Chen", "to": "ADR-012", "type": "APPROVED", "fact": "Sarah Chen approved the architecture decision"}
  ],
  "facts": [
    "Decision: Migrate to event-driven architecture using Kafka",
    "Rationale: Synchronous calls create cascading failures",
    "Approved by: Sarah Chen (VP Engineering)",
    "Exception: Payment service stays synchronous until Q3 audit"
  ],
  "processing_time_ms": 4200
}
```

---

## 5. Feedback — Making the Graph Smarter Over Time

### 5.1 Submit Feedback After Receiving Results

```python
await db.feedback(
    session_id="session_abc123",
    query_id="q_456",
    score=4,
    used_entities=["#12:3", "#12:7"],
    used_edges=["#45:1", "#45:5"],
)
```

```json
{
  "success": true,
  "updated_weights": {
    "#12:3": {"old_weight": 0.88, "new_weight": 0.91, "delta": "+0.03"},
    "#12:7": {"old_weight": 0.70, "new_weight": 0.73, "delta": "+0.03"},
    "#45:1": {"old_weight": 0.85, "new_weight": 0.87, "delta": "+0.02"},
    "#45:5": {"old_weight": 0.65, "new_weight": 0.68, "delta": "+0.03"}
  },
  "ema_calculation": {
    "normalized_score": 0.75,
    "alpha": 0.3,
    "formula": "new_weight = (1 - α) × old_weight + α × normalized_score"
  }
}
```

### 5.2 Negative Feedback — Less Relevant Results

```python
await db.feedback(
    session_id="session_abc123",
    query_id="q_789",
    score=1,
    used_entities=["#14:55"],
    used_edges=["#45:30"],
)
```

```json
{
  "success": true,
  "updated_weights": {
    "#14:55": {"old_weight": 0.50, "new_weight": 0.35, "delta": "-0.15"},
    "#45:30": {"old_weight": 0.48, "new_weight": 0.33, "delta": "-0.15"}
  }
}
```

### 5.3 Feedback Impact — Entities Now Surface Higher

Before feedback (score=4 on Sarah Chen):

```
Query: "Who are stakeholders for the Acme deal?"
Results: [Marcus Rivera (0.70), Sarah Chen (0.88), David Kim (0.62)]
```

After feedback (Sarah Chen boosted to 0.91):

```
Query: "Who are stakeholders for the Acme deal?"
Results: [Sarah Chen (0.91), Marcus Rivera (0.73), David Kim (0.67)]
                                         ↑ boosted      ↑ mildly boosted
```

---

## 6. Cypher — Advanced Temporal & Audit Queries

### 6.1 All Decisions About an Entity Over Time

```cypher
MATCH (d:Decision)-[:DECIDED_ABOUT]->(e:Entity {name: "Acme Enterprise Deal"})
RETURN d.subject, d.outcome, d.decided_by, d.valid_at, d.exception
ORDER BY d.valid_at DESC
```

```
┌────────────────────────────┬───────────────────────────────────────────┬──────────────────┬─────────────────────────┬────────────────────────────────┐
│ subject                    │ outcome                                  │ decided_by       │ valid_at                │ exception                      │
├────────────────────────────┼───────────────────────────────────────────┼──────────────────┼─────────────────────────┼────────────────────────────────┤
│ Acme 15% discount          │ Approved 15% + net-60 terms             │ Jordan Blake     │ 2026-04-02T11:00:00Z   │ net-60 instead of net-30       │
│ Enterprise pricing tier     │ Classified as Tier 1 (500+ seats)      │ Jordan Blake     │ 2026-02-20T10:00:00Z   │ None                           │
│ Account reassignment        │ Transferred from Priya to Jordan        │ Sales Ops         │ 2026-03-20T16:00:00Z   │ None                           │
└────────────────────────────┴───────────────────────────────────────────┴──────────────────┴─────────────────────────┴────────────────────────────────┘
3 rows
```

### 6.2 Facts That Were True at a Specific Point in Time

```cypher
MATCH (f:Fact {subject_id: "entity_acme_001"})
WHERE f.valid_at <= datetime("2026-03-01") AND (f.invalid_at IS NULL OR f.invalid_at > datetime("2026-03-01"))
RETURN f.predicate, f.object_value, f.valid_at, f.invalid_at
ORDER BY f.valid_at
```

```
┌──────────────────┬────────────────────────────────┬──────────────────────────┬──────────────────────────┐
│ predicate        │ object_value                   │ valid_at                 │ invalid_at               │
├──────────────────┼────────────────────────────────┼──────────────────────────┼──────────────────────────┤
│ deal_stage       │ Discovery                      │ 2026-02-15T10:30:00Z    │ 2026-03-01T09:00:00Z    │
│ pricing          │ $45/user/month (proposed)      │ 2026-02-15T10:30:00Z    │ 2026-03-12T14:30:00Z    │
│ deal_amount      │ $500,000                       │ 2026-02-15T10:30:00Z    │ NULL                     │
│ seat_count       │ 500                            │ 2026-02-15T10:30:00Z    │ NULL                     │
│ sentiment_avg    │ neutral                        │ 2026-02-15T10:30:00Z    │ 2026-03-10T16:00:00Z    │
└──────────────────┴────────────────────────────────┴──────────────────────────┴──────────────────────────┘
5 rows (facts true on March 1st — note: pricing was still $45, stage was still Discovery)
```

### 6.3 Cohort: All Accounts with Expiring Contracts in 90 Days

```cypher
MATCH (e:Entity {entity_type: "organization"})-[:HAS_CONTRACT]->(c:Entity {entity_type: "contract"})
WHERE c.metadata.renewal_date <= datetime("2026-07-24")
  AND e.feedback_weight > 0.5
RETURN e.name, c.metadata.renewal_date, e.feedback_weight, c.metadata.arr, c.metadata.stage
ORDER BY c.metadata.renewal_date ASC
```

```
┌──────────────────┬─────────────────────────┬──────────────────┬─────────────┬─────────────────┐
│ e.name           │ renewal_date            │ feedback_weight  │ arr         │ stage            │
├──────────────────┼─────────────────────────┼──────────────────┼─────────────┼─────────────────┤
│ Beta Corp        │ 2026-06-01              │ 0.72             │ $840K       │ at_risk          │
│ Gamma Industries │ 2026-07-15              │ 0.55             │ $560K       │ contracting      │
│ Acme Corp        │ 2026-06-30              │ 0.82             │ $500K       │ negotiation      │
│ Omega Labs       │ 2026-07-01              │ 0.84             │ $320K       │ expansion_ready  │
└──────────────────┴─────────────────────────┴──────────────────┴─────────────┴─────────────────┘
4 rows ($2.22M total ARR at risk in next 90 days)
```

### 6.4 Feedback-Weighted Stakeholder Ranking

```cypher
MATCH (p:Entity {entity_type: "person"})-[r:STAKEHOLDER]->(d:Entity {entity_type: "deal"})
WHERE p.feedback_weight > 0.7 AND d.invalid_at IS NULL
RETURN p.name, p.metadata.role, p.metadata.sentiment, p.feedback_weight, d.name AS deal
ORDER BY p.feedback_weight DESC
```

```
┌─────────────────┬─────────────────────────┬───────────┬──────────────────┬──────────────────────┐
│ p.name          │ role                    │ sentiment │ feedback_weight   │ deal                 │
├─────────────────┼─────────────────────────┼───────────┼──────────────────┼──────────────────────┤
│ Sarah Chen      │ VP Engineering          │ positive  │ 0.91             │ Acme Enterprise Deal │
│ Jordan Blake    │ Account Executive        │ positive  │ 0.86             │ Acme Enterprise Deal │
│ James Park      │ CTO                     │ positive  │ 0.84             │ Omega Labs Expansion │
│ Marcus Rivera   │ Dir. Procurement        │ neutral   │ 0.73             │ Acme Enterprise Deal │
└─────────────────┴─────────────────────────┴───────────┴──────────────────┴──────────────────────┘
4 rows (feedback_weight > 0.7, current deals only)
```

---

## 7. REST API — Quick Reference

### Assemble Context (for AI Agents)

```bash
curl -X POST http://localhost:8000/context/assemble \
  -d '{"query": "Acme deal status", "max_depth": 3, "include_types": ["person", "deal", "organization"]}'
```

```json
[
  {"id": "#12:0", "content": "Acme Enterprise Deal", "type": "deal", "metadata": {"stage": "Negotiation", "amount": "$500K", "feedback_weight": 0.82}},
  {"id": "#12:3", "content": "Sarah Chen", "type": "person", "metadata": {"role": "VP Eng", "sentiment": "positive", "feedback_weight": 0.91}},
  {"id": "#12:7", "content": "Marcus Rivera", "type": "person", "metadata": {"role": "Dir. Procurement", "sentiment": "neutral", "feedback_weight": 0.73}},
  {"id": "#5:0", "content": "Acme Corp", "type": "organization", "metadata": {"industry": "Technology", "nps": 72, "feedback_weight": 0.91}}
]
```

### Chat with RAG Context (Streaming)

```bash
curl -X POST http://localhost:8000/chat \
  -d '{"message": "What is the current status of the Acme deal?", "include_context": true}'
```

```
data: {"type": "start", "content": ""}
data: {"type": "chunk", "content": "The **Acme Enterprise Deal** is in **Negotiation** for 500 seats ($380K after 15% discount). "}
data: {"type": "chunk", "content": "Sarah Chen (VP Eng, positive) confirmed pricing. Marcus Rivera (Dir. Procurement, neutral) requested extended review. "}
data: {"type": "chunk", "content": "Key concern: CFO Lisa Wong raised budget ceiling of $1.8M. Next step: contract legal review."}
data: {"type": "sources", "sources": [
  {"id": "#12:0", "content": "Acme Enterprise Deal — stage: Negotiation, $380K", "score": 0.94},
  {"id": "#12:3", "content": "Sarah Chen — VP Engineering, positive", "score": 0.91},
  {"id": "#12:7", "content": "Marcus Rivera — Dir. Procurement, neutral", "score": 0.82}
]}
data: {"type": "done"}
```

### Entity Timeline

```bash
curl http://localhost:8000/entities/%2312:0/timeline
```

```json
{
  "entity": "Acme Enterprise Deal",
  "timeline": [
    {"date": "2026-02-15", "event": "created", "detail": "Deal created from Salesforce", "source": "salesforce"},
    {"date": "2026-03-01", "event": "stage_change", "detail": "Discovery → Negotiation", "source": "gmail"},
    {"date": "2026-03-12", "event": "pricing_change", "detail": "$45 → $38/user/month", "source": "gmail"},
    {"date": "2026-04-02", "event": "decision", "detail": "15% discount approved + net-60 terms", "source": "internal"},
    {"date": "2026-04-10", "event": "agreement", "detail": "Acme agreed to revised pricing", "source": "gmail"}
  ]
}
```

### Graph Stats

```bash
curl http://localhost:8000/graph/stats
```

```json
{"entities": 1247, "episodes": 342, "facts": 5623}
```

### Feedback Submission

```bash
curl -X POST http://localhost:8000/feedback \
  -d '{"entity_id": "#12:3", "feedback_type": "relevance", "score": 4.5, "metadata": {"reason": "highly relevant"}}'
```

```json
{"success": true, "feedback_id": "feedback_2026-04-24T10:30:00Z"}
```

### Ingest Episode

```bash
curl -X POST http://localhost:8000/ingest/episode \
  -d '{"content": "Acme agreed to revised pricing...", "type": "message", "metadata": {"source": "gmail"}}'
```

```json
{"success": true, "entity_id": "#55:35", "nodes_created": 1}
```

---

## 8. Context Core CLI — Versioned Context Snapshots

### Build & Test

```bash
contextd core build --name "acme-context" --graph "production"
```

```
Building context core 'acme-context' from graph 'production'...
  Entities: 1,247 | Edges: 3,891 | Facts: 5,623 | Communities: 18
  Core hash: sha256:a4f8e2c91d3b7...
✓ Core built: acme-context:v1 (12.4 MB, 57s)
```

```bash
contextd core test --core "acme-context:v3" --queries "test-suite.yaml"
```

```
  1. "Who is the Acme account owner?"         ✓ Pass
  2. "What is the deal stage?"                 ✓ Pass
  3. "List stakeholders for Acme"             ✓ Pass (4/4)
  4. "What did we know before Apr 8th?"       ✓ Pass (2 facts)
  5. "Get timeline for Acme deal"              ✓ Pass (6 events)
  6. "Discount decision lineage"               ✓ Pass
  7. "Current security posture"                ✓ Pass
  Results: 7/7 passed | Avg latency: 42ms | Tokens avg: 1,420
```

### Diff & Promote

```bash
contextd core diff --from "acme-context:v2" --to "acme-context:v3"
```

```
  Entities: +147 added, ~23 updated, -8 expired
  Relationships: +389 added, ~45 updated, -12 expired
  Facts: +412 added, ~67 updated, -3 superseded
  Communities: +2 new, ~5 summaries updated
  Tokens: v2 avg 1,380 → v3 avg 1,420 (+3%)
  Latency: v2 avg 45ms → v3 avg 42ms (-7%)
```

```bash
contextd core promote --core "acme-context:v3" --target "production"
```

```
  Switching production: acme-context:v2 → acme-context:v3
  ✓ Live. Rollback: contextd core rollback --target production --to acme-context:v2
```

---

*ContextD replaces similarity-based retrieval with relationship-aware, temporally-grounded, ontology-constrained, feedback-weighted context assembly — reducing tokens by 80% and enabling queries impossible with flat retrieval.*