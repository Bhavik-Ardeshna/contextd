# 14 — References & Open-Source Dependencies

> Single consolidated home for every external citation: the substrate ContextD builds on, the open-source libraries it depends on, the academic literature it draws from, the prior-art projects it acknowledges, the standards and specifications it implements, and recommended further reading.
>
> Where a specific tool or paper informs a design choice, the technical document linking here will reference the relevant section by short tag (for example, *"see §A.2 — substrate"*).

---

## A. Substrate and storage technology

### A.1 The multi-model substrate

ContextD's unified storage layer is built on **ArcadeDB** (Apache License 2.0), the only open-source multi-model database that combines a graph engine, native vector search (HNSW with product-quantization compression), full-text search, document storage, key-value storage, and time-series storage in a single ACID-transactional engine. Choice driver: a permissive license without SSPL / Commons Clause / BSL entanglement, allowing embedded use, fork, and distribution; first-class wire-protocol polyglot (Bolt, PostgreSQL, MongoDB, Redis, gRPC, HTTP); built-in MCP server. Repository: https://github.com/ArcadeData/arcadedb.

Performance characteristics on representative workloads are documented in `09-benchmarks-and-validation.md`.

### A.2 Vector index

The HNSW (Hierarchical Navigable Small World) graph index is provided by the substrate's vector subsystem (jvector-derived). HNSW gives logarithmic-time approximate-nearest-neighbor search on high-dimensional embeddings; product-quantization compression reduces memory residency by roughly 64× at acceptable recall.

Reference paper: **Malkov, Y. A. and Yashunin, D. A. (2018).** *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs.* IEEE Transactions on Pattern Analysis and Machine Intelligence.

### A.3 Full-text search

Apache **Lucene** (Apache 2.0) is used for the BM25 inverted-index leg of hybrid retrieval and for full-text search over entity attributes and free-text content. Lucene is the canonical text-search library in the JVM ecosystem.

### A.4 Compression layer

- **LZ4** (BSD 2-Clause): block compression for archive blobs (Context Cores, audit-log segments). Optimized for decompression speed.
- **Delta-of-delta + Gorilla XOR encoding** for time-series data — see Facebook's Gorilla paper in §C.

---

## B. Engineering libraries and tooling

### B.1 NLP / ML

- **datasketch** (Apache 2.0) — MinHash and LSH primitives used in the Resolver Engine's blocking stage.
- **OpenAI / Anthropic API clients** — LLM access for extraction, ontology routing, and final-tier resolution adjudication.
- Cross-encoder neural matching follows the **DITTO** architecture (Section §C); model checkpoints are derivatives of **RoBERTa** and **DeBERTa-v3** transformer base models, fine-tuned per entity type.
- **GLiNER** (zero-shot named-entity recognition) and fine-tuned **RoBERTa-NER** are used in coreference resolution.
- End-to-end neural coreference uses architectures derived from **e2e-coref** and **MaverickCoref**.
- Cross-document coreference resolution uses architectures derived from **CDLM**.

### B.2 Engine and API

- **FastAPI** (MIT) — REST API framework.
- **Pydantic** v2 (MIT) — data validation and structured-output serialization.
- **Jinja2** (BSD-3-Clause) — prompt templating for ontology injection.
- **httpx** (BSD-3-Clause) — async HTTP client for substrate access.
- **msgpack** (Apache 2.0) — serialization format for Forge Mappings, Context Cores, audit segments.
- **OpenTelemetry SDK** (Apache 2.0) — distributed tracing.
- **Prometheus client** (Apache 2.0) — metrics exposition.
- **tiktoken** (MIT) — token counting for budget-aware context assembly.

### B.3 Connectors and ingestion

- **Airbyte** Open Source (Elastic License v2 / MIT for connectors) — used as the underlying connector engine for the broad-tier (P1) connector wave; ContextD adds a quality layer on top (LLM extraction, ontology constraints, deduplication, provenance stamping). Six in-house deep-extraction connectors (Gmail, Salesforce, Slack, GitHub, Zendesk, HubSpot) are first-party.
- **chonkie** (Apache 2.0) — semantic and code chunking for unstructured text.

### B.4 Workers and orchestration

- **Temporal** (MIT) — durable workflow orchestration for connector sync jobs and long-running ingestion tasks.
- **Redis** (BSD until 7.4 / SSPL after; ContextD pins to permissive-licensed builds) — pub/sub and hot-path caching.

---

## C. Academic references

Algorithms and design choices in ContextD's modules trace back to the following research literature.

### C.1 Entity resolution and record linkage

- **Fellegi, I. P. and Sunter, A. B. (1969).** *A theory for record linkage.* Journal of the American Statistical Association, 64(328), 1183–1210. The foundational paper for probabilistic record linkage; the m-probability / u-probability framework used in Stage B of the Resolver Engine.
- **Winkler, W. E. (1988).** *Using the EM algorithm for weight computation in the Fellegi-Sunter model of record linkage.* Proceedings of the Section on Survey Research Methods, ASA.
- **Li, Y., Li, J., Suhara, Y., Doan, A., Tan, W. (2020).** *Deep entity matching with pre-trained language models* (DITTO). VLDB 2020. Cross-encoder transformer architecture for pairwise entity matching used in Stage C.
- **Thirumuruganathan, S. et al. (2021).** *DeepBlocker: A learned blocking framework for entity resolution.* VLDB 2021. Learned blocking on tabular attributes used in Stage A.
- **Recent (2024).** *AnyMatch* and *MatchGPT* explore LLM-based pairwise adjudication; Stage F follows their few-shot / chain-of-thought prompting pattern for the residual hard cases.

### C.2 Coreference resolution

- **Lee, K., He, L., Lewis, M., Zettlemoyer, L. (2017).** *End-to-end neural coreference resolution.* EMNLP 2017. The e2e-coref architecture used for within-document mention clustering.
- **Martinelli, G. et al. (2024).** *MaverickCoref.* Modern within-document coreference architecture.
- **Cattan, A. et al. (2021).** *Cross-document coreference resolution over predicted mentions.* Findings of ACL 2021.
- **Caciularu, A. et al. (2021).** *CDLM: Cross-document language modeling.* Findings of EMNLP 2021. Cross-document mention alignment using contextualized embeddings.

### C.3 Probabilistic constraint propagation

- **Bach, S. H., Broecheler, M., Huang, B., Getoor, L. (2017).** *Hinge-loss Markov random fields and Probabilistic Soft Logic.* Journal of Machine Learning Research, 18(109), 1–67. PSL framework used in Stage E for transitive closure with confidence multiplication.

### C.4 Active learning

- **Settles, B. (2009).** *Active learning literature survey.* University of Wisconsin-Madison Technical Report 1648. Uncertainty-sampling and query-by-committee strategies for the Stage F label-acquisition loop.
- **Seung, H. S., Opper, M., Sompolinsky, H. (1992).** *Query by committee.* COLT 1992.

### C.5 Information retrieval

- **Cormack, G. V., Clarke, C. L. A., Buettcher, S. (2009).** *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods.* SIGIR 2009. Source of the `k = 60` constant in the default RRF reranker.
- **Robertson, S. and Zaragoza, H. (2009).** *The probabilistic relevance framework: BM25 and beyond.* Foundations and Trends in Information Retrieval. The BM25 ranking function used in the full-text index.

### C.6 Vector and similarity search

- **Indyk, P. and Motwani, R. (1998).** *Approximate nearest neighbors: towards removing the curse of dimensionality.* STOC 1998. Original LSH paper; basis for MinHash blocking.
- **Malkov, Y. A. and Yashunin, D. A. (2018).** *HNSW.* (See §A.2.)
- **Jegou, H., Douze, M., Schmid, C. (2011).** *Product quantization for nearest neighbor search.* IEEE TPAMI. Foundational PQ algorithm.

### C.7 Calibration and probabilistic methods

- **Platt, J. (1999).** *Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods.* Advances in Large Margin Classifiers. Platt scaling for probability calibration.
- **Niculescu-Mizil, A. and Caruana, R. (2005).** *Predicting good probabilities with supervised learning.* ICML 2005.

### C.8 Approximate counting and sketches

- **Flajolet, P., Fusy, É., Gandouet, O., Meunier, F. (2007).** *HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm.* AofA 2007. Cardinality estimation used in the Data Profiler.
- **Cormode, G. and Muthukrishnan, S. (2005).** *An improved data stream summary: the count-min sketch and its applications.* Journal of Algorithms. Top-K frequency estimation in the Data Profiler.

### C.9 Time-series compression

- **Pelkonen, T. et al. (2015).** *Gorilla: A fast, scalable, in-memory time series database.* VLDB 2015. Source of the delta-of-delta timestamp encoding and XOR-based float encoding used in the time-series engine.

### C.10 Storage and database internals

- **O'Neil, P., Cheng, E., Gawlick, D., O'Neil, E. (1996).** *The log-structured merge-tree (LSM-tree).* Acta Informatica. Foundational LSM tree design.
- **Bayer, R. and McCreight, E. (1972).** *Organization and maintenance of large ordered indexes.* B-tree foundation.

### C.11 Consensus and replication

- **Ongaro, D. and Ousterhout, J. (2014).** *In search of an understandable consensus algorithm (Raft).* USENIX ATC. Raft consensus protocol used for replication.

---

## D. Prior-art projects

These open-source projects explored ideas adjacent to ContextD's. Their implementations are not used directly in ContextD, but their design patterns influenced specific architectural choices.

- **Graphiti** (open-source temporal knowledge graph for agent memory) — informed the structure of episodic ingestion and the cascading entity-resolution pattern. ContextD's 5-phase cascade (exact → entropy gate → MinHash → cosine → LLM) shares the cost-cascading philosophy, while extending to bitemporal-at-schema-level and decision-lineage primitives that Graphiti does not have.
- **TrustGraph** (LLM-driven knowledge graph builder) — popularized the OntoRAG pattern of injecting ontology constraints into the LLM extraction prompt. ContextD's Ontology Engine generalizes this with semantic routing per chunk, cardinality and disjoint-class validation, and pre-built CRM / Support / Engineering / Marketing ontologies.
- **Cognee** (open-source memory layer with feedback EMA) — demonstrated streaming exponential-moving-average as a feasible feedback-update mechanism. ContextD's Feedback Engine extends this by integrating weights into every retrieval path (not as a post-hoc reranker), per-edge alongside per-node, and idempotent session-aware processing.
- **Splink** (open-source probabilistic record linkage in Python) — reference implementation of the Fellegi-Sunter framework. ContextD's Resolver Engine Stage B follows the same theoretical foundation, integrated with the substrate's transactional graph store rather than as a standalone library.
- **Magellan** (academic ER framework, University of Wisconsin) — reference standard for entity-matching benchmarks (Walmart-Amazon, DBLP-ACM). ContextD's cross-encoder is evaluated against the Magellan benchmark suite.
- **dbt Semantic Layer / MetricFlow** — the metric-definition format that Context Forge's Business Logic Ingester parses.
- **LookML** — the modeling format from Looker that Context Forge's Business Logic Ingester parses.
- **Cube.dev** — open-source semantic-layer format that Context Forge's Business Logic Ingester parses.

---

## E. Comparable systems (positioning context)

ContextD addresses a different problem from each of these but operates in adjacent space.

### E.1 Vector databases

- **Pinecone** — managed vector database. Closed source, hybrid-search retrofit.
- **Weaviate** — open-core vector database with knowledge-graph features added.
- **Qdrant** — Rust-native open-source vector database.
- **Milvus** — open-source vector database (used in ContextD's current production stack pending substrate migration).
- **Chroma** — embedded open-source vector database.
- **pgvector** — Postgres vector-search extension.

### E.2 Graph databases

- **Neo4j** — established graph database; SSPL licensing limits embedded use.
- **Amazon Neptune** — managed graph service from AWS.
- **TigerGraph** — distributed graph analytics.
- **Apache AGE** — graph extension for Postgres.

### E.3 Memory layers for AI agents

- **Zep** — productized agent memory based on Graphiti.
- **MemGPT / Letta** — agent memory with tiered storage.

### E.4 Knowledge-graph platforms

- **Stardog** — RDF/SPARQL knowledge-graph platform.
- **Ontotext** — RDF/SPARQL platform with text-extraction features.
- **Diffbot** — large-scale public knowledge graph.

### E.5 Customer Data Platforms

- **Segment** (Twilio), **mParticle**, **Hightouch** — identity stitching and activation for marketing use cases. Different problem from cross-source enterprise context.

### E.6 RAG orchestration frameworks

- **LangChain**, **LlamaIndex**, **Haystack** — orchestration libraries that compose retrieval, prompting, and LLM calls. Strong complements for ContextD; not competitors.

### E.7 AI agent platforms (channels for ContextD via MCP)

- **Anthropic Claude** + **MCP** — first-class MCP support.
- **Cursor**, **Windsurf**, **Claude Code** — local agent tooling that consumes MCP via stdio.
- **OpenAI Operator**, **LangGraph**, **CrewAI**, **Cognition** — agent frameworks at the application tier.

---

## F. Standards and specifications

### F.1 Wire protocols

- **Bolt** — Neo4j's binary protocol over TCP and WebSocket. PackStream serialization. Specification at https://neo4j.com/docs/bolt/current/.
- **PostgreSQL frontend/backend protocol** — extended-query protocol with Parse / Bind / Execute / Sync messages. Documented in the Postgres manual.
- **MongoDB Wire Protocol** — BSON-encoded message format. Specification published by MongoDB.
- **RESP** (Redis Serialization Protocol) — text-based command/response protocol.
- **gRPC** — Google's RPC framework with protobuf-defined service maps.
- **HTTP/REST** — standard JSON-over-HTTP.

### F.2 Agent and integration protocols

- **Model Context Protocol (MCP)** — Anthropic's specification for agent-to-tool communication. JSON-RPC 2.0 over stdio, Server-Sent Events, or HTTP. Specification at https://modelcontextprotocol.io.
- **JSON-RPC 2.0** — request/response protocol used by MCP and other ContextD APIs.
- **Server-Sent Events (SSE)** — W3C-recommended protocol for server-to-client streaming.
- **OpenAPI** — REST API specification standard.
- **GraphQL** — query language and runtime.

### F.3 Cryptographic and identity

- **SHA-256** — FIPS PUB 180-4. Used for content addressing of Forge Mappings, Context Cores, audit-log entries, and API key hashes.
- **TLS 1.3** — RFC 8446. Transport encryption for all external connections.
- **AES-256** — encryption at rest for cloud deployments.
- **OAuth 2.0** — RFC 6749. Authorization framework for source-system OAuth flows.

### F.4 Observability and monitoring

- **OpenTelemetry** — CNCF specification for distributed tracing and metrics.
- **Prometheus exposition format** — text-based metric format.
- **PromQL** — Prometheus query language, exposed via the time-series engine for telemetry queries.
- **InfluxDB Line Protocol** — text-based ingestion format for time-series points.

### F.5 Compliance frameworks

- **SOC 2** (AICPA Trust Services Criteria) — Type I and Type II audit standards.
- **ISO/IEC 27001:2022** — information security management standard.
- **GDPR** (Regulation EU 2016/679) — data protection regulation; data residency, right to deletion, consent tracking.
- **HIPAA** (45 CFR Parts 160 and 164) — healthcare data handling (optional, customer-driven).

### F.6 Data formats

- **msgpack** — binary serialization specification used for Forge Mappings, Context Cores, sealed time-series segments. Specification at https://msgpack.org.
- **Apache Arrow** — columnar in-memory format used in time-series aggregation paths.
- **Protocol Buffers** (protobuf) — binary serialization used for gRPC services.

### F.7 Semantic-layer formats

The Business Logic Ingester (Section 11.5 of `contextd-master.md` and Component 3 of `06-context-forge.md`) parses:

- **dbt** project files: `manifest.json`, `sources.yml`, `schema.yml`, semantic-layer YAML.
- **LookML** view files, model files, explores, measures, dimensions.
- **MetricFlow** YAML.
- **Cube** schema files.
- **OpenLineage** events and **DataHub** metadata.
- SQL views and stored procedures via SQL AST parsing.
- Tableau workbook calculated fields.
- Power BI / DAX measures.

---

## G. Recommended further reading

For technical reviewers who want background on the design choices.

### G.1 Database internals

- **Petrov, A.** *Database Internals: A Deep Dive into How Distributed Data Systems Work.* O'Reilly, 2019. The standard modern reference for storage engines, B-trees, LSM trees, replication, and transactions.
- **Kleppmann, M.** *Designing Data-Intensive Applications.* O'Reilly, 2017. Required reading for the architectural reasoning behind every choice in this document.
- **Hellerstein, J. M. and Stonebraker, M. (eds.).** *Readings in Database Systems* (the "Red Book"). Public-domain compilation of seminal database papers.

### G.2 Specific implementations to read

- The **PostgreSQL** documentation on MVCC (https://www.postgresql.org/docs/current/mvcc.html) — the canonical multi-version concurrency control reference.
- The **RocksDB** wiki — production LSM-tree engine, source of practical optimization patterns.
- The **Redis source code** — reference implementation of in-memory data structures and persistence.
- The **Apache Lucene** documentation — inverted-index internals, BM25 implementation, posting-list compression.

### G.3 AI agent design

- **Anthropic Engineering** blog posts on Model Context Protocol and tool use.
- **OpenAI Cookbook** examples for structured output, function calling, and retrieval-augmented generation.
- The **LangChain documentation** for understanding how external orchestration layers compose with persistent context stores.

---

## H. License inventory

Every dependency in ContextD's stack is permissively licensed (Apache 2.0, MIT, BSD, or compatible). No SSPL, no Commons Clause, no Business Source License in the critical path. A dependency audit is run on every release; deviations are flagged and either vendored under a permissive license or replaced.

The intelligence layer (the ContextD code on top of the substrate) is published under Apache 2.0 / MIT in the open-core distribution.

The substrate (ArcadeDB) is genuinely Apache 2.0 — confirmed via the `LICENSE` file at the project root and verified for every transitive dependency via the substrate's `ATTRIBUTIONS.md`.

---

*This file is the consolidated reference for every external technology, paper, and project mentioned in the technical documentation. Documents `04` through `13` reference back here by short tag rather than re-stating citations inline.*
