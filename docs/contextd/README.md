# ContextD — Technical Documentation

> **What this folder is.** The complete technical specification of ContextD — vision, architecture, engine implementation, productized modules, benchmarks, roadmap, capabilities, application surface, references. Written as a definitive reference, not as marketing material.
>
> **5-minute read:** `01-executive-summary.md`.
> **30-minute read:** `01` → `02` → `04` → `05` → `06` → `07`.
> **Full deep-dive:** in numerical order. The substrate-level engine description (`05`) sits right after the architecture overview, then the productized modules (Forge, Resolver), then the conceptual subsystems, benchmarks, roadmap, capabilities, application surface, and references.
> **Source of truth:** `contextd-master.md` — every claim and number aggregated.

---

## Files

### Overview (the *what* and *why*)

| # | File | Scope |
|---|------|-------|
| 01 | [Executive Summary](./01-executive-summary.md) | One-page overview: what ContextD is, why now, the technical thesis |
| 02 | [Vision & Category](./02-vision-and-category.md) | The Context Graph Database thesis. Why this is a new database category |
| 03 | [Problem & Market](./03-problem-and-market.md) | What current AI context infrastructure misses; where the category fits |

### Architecture & engine implementation (the *what's inside* + *how it's built*)

| # | File | Scope |
|---|------|-------|
| 04 | [Product & Architecture](./04-product-and-architecture.md) | What ContextD is. Six-layer architecture. Today's stack vs the unified substrate. End-to-end Snowflake + dbt walkthrough |
| 05 | [ContextD-Native Database Implementation](./05-contextd-native-db-implementation.md) | Engine-level deep dive: page format, MVCC, WAL, LSM dual-index, HNSW + PQ vector indexing, Gorilla time-series codecs, Raft state-machine bridge, RBAC compilation, Identity Graph storage, Context Cores serialization. The substrate techniques required to build a context-first database |

### Productized modules (the *architectural blocks*)

| # | File | Scope |
|---|------|-------|
| 06 | [Context Forge — Pre-Pipeline Mapping Module](./06-context-forge.md) | Source introspection, data profiling, business-logic ingestion, seven-pass mapping inference, Forge Studio, versioned Forge Mapping artifact, Forge-to-Pipeline Bridge |
| 07 | [Context Resolver — Cross-Source Identity Stitching](./07-context-resolver.md) | Two-path resolution, six-stage probabilistic pipeline, Identity Graph, Resolver Studio, Resolver Profiles, Resolver-to-Pipeline Bridge |

### Engine subsystems & validation (the *intelligence layer* + *measured performance*)

| # | File | Scope |
|---|------|-------|
| 08 | [Core Technology](./08-core-technology.md) | Six data primitives, bitemporal model, 10-step ingestion pipeline, hybrid retrieval, 7-step context assembly, feedback EMA, Context Cores, ontology engine |
| 09 | [Benchmarks & Validation](./09-benchmarks-and-validation.md) | Engineering ground-truth. Real numbers on real hardware. Bottlenecks and the engineering responses |

### Plan & defensibility (the *what's coming* + *what's hard to copy*)

| # | File | Scope |
|---|------|-------|
| 10 | [Roadmap & Build Plan](./10-roadmap-and-build-plan.md) | Phase plan from today's stack to the unified substrate. Each phase as a technical milestone with scope, validation, exit criteria |
| 11 | [Distinguishing Technical Capabilities](./11-technical-capabilities.md) | The structural commitments that make the design hard to retrofit onto existing graph or vector databases |

### Application surface (the *how it's used* + *how it's deployed*)

| # | File | Scope |
|---|------|-------|
| 12 | [Use Cases](./12-use-cases.md) | Concrete query and ingestion scenarios with code, queries, and assembled context |
| 13 | [Integration, Deployment, Security](./13-integration-deployment-security.md) | SDK, MCP, REST, six wire protocols, deployment modes, RBAC matrix, multi-tenancy, compliance roadmap |

### Reference

| # | File | Scope |
|---|------|-------|
| 14 | [References](./14-references.md) | Substrate dependencies, open-source libraries, academic citations, prior-art projects, comparable systems, standards & specifications, license inventory, further reading |
| — | [contextd-master.md](./contextd-master.md) | Single-file aggregated source-of-truth dump |

---

## How to read this pack

Pick a path based on what you need:

| Reader | Path |
|--------|------|
| Anyone, first contact | `01` (5 min) |
| The thesis | `01` → `02` → `03` |
| The technical architecture (with engine internals) | `04` → `05` → `06` → `07` → `08` |
| Validation evidence | `09` |
| Forward-looking plan | `10` |
| Defensibility analysis | `11` |
| Application examples | `12` → `13` |
| Citations and prior art | `14` |

---

## Authoritative claims discipline

Two tags appear throughout the technical documentation:

- **[BENCH]** — measured number from the internal benchmark report (see `09-benchmarks-and-validation.md`).
- **[TARGET]** — engineering target. Achievable structurally, not yet measured at the stated scale.

Never confuse the two.

---

*Compiled 2026-04-28. Source materials: `docs/BENCHMARK_REPORT.md`, `docs/contextD.md`, `docs/example-queries-just intuition-based.md`, https://contextd-tech.vercel.app/.*
