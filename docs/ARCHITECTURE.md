# Architecture

Adaptive Knowledge Graph is a production-shaped KG-RAG prototype. The system is
designed to show CTO-level AI platform judgment: graph-aware retrieval,
local-first inference, transparent citations, adaptive assessment, and explicit
operational tradeoffs.

## System Shape

```text
Browser / Next.js
  - graph visualization
  - chat with SSE streaming
  - KG-RAG vs plain RAG comparison
  - adaptive quiz and recommendations

FastAPI
  - /api/v1/ask and /ask/stream
  - /api/v1/quiz/*
  - /api/v1/graph/*
  - /api/v1/student/*
  - /health/live and /health/ready

Data and model services
  - Neo4j: concepts, modules, prerequisite/related relationships, chunk windows
  - OpenSearch: BM25 + vector retrieval over textbook chunks
  - Ollama/OpenRouter: answer and quiz generation
  - SQLite: local student mastery profiles
```

## Request Flow

### KG-RAG answer

1. Validate question, subject, top-k, and retrieval options.
2. Resolve subject config from `config/subjects.yaml`.
3. Extract query concepts and expand them with Neo4j neighbors when enabled.
4. Retrieve chunks from OpenSearch with kNN or hybrid BM25 + vector search.
5. Optionally add window context when Neo4j chunk windows are enabled.
6. Optionally rerank retrieved chunks.
7. Generate an answer with source-grounded prompt instructions.
8. Return answer, sources, expanded concepts, model, attribution, and counts.

Both blocking and streaming answer endpoints now share the same retrieval helper
so retrieval behavior does not drift between API modes.

### Adaptive assessment

1. Retrieve topic-relevant content.
2. Ask the LLM to generate MCQs with difficulty labels and explanations.
3. Update concept mastery after each answer.
4. Use BKT-inspired Bayesian updates when enabled; otherwise fall back to simple
   linear updates.
5. Generate remediation or advancement recommendations from weak/strong concepts.

This is a credible adaptive-learning demo, not a validated certification engine.
Question difficulty is LLM-estimated and should not be treated as calibrated IRT.

## Data Boundaries

Subjects are isolated by configuration:

- Neo4j labels use a subject prefix such as `us_history_Concept`.
- OpenSearch indices are subject-specific.
- Prompts, theme colors, attribution, and books are subject-specific.

This works on Neo4j Community Edition. A production multi-tenant deployment
should add tenant IDs, role boundaries, and stronger data isolation.

## Security Model

Local development is open by default. When `API_KEY` is configured, protected
student and graph-query endpoints require `X-API-Key`.

Implemented hardening:

- external TLS verification enabled by default
- local OpenSearch uses HTTP in Compose instead of pretending to use TLS
- `/health/ready` returns 503 when Neo4j or OpenSearch are unavailable
- health/error details are redacted before exposure
- OpenSearch image is pinned instead of using `latest`
- `X-Forwarded-For` is ignored for rate limiting unless trusted proxy headers
  are explicitly enabled

Not implemented yet:

- full user identity
- tenant-aware authorization
- audit-grade assessment attempts
- production secret management

## Observability

Every request receives an `X-Request-ID`. The middleware logs method, path,
status code, and elapsed milliseconds, and returns `X-Response-Time-ms` for
simple latency checks.

The next production step is structured tracing across retrieval, graph
expansion, LLM generation, and student-model updates.

## Evaluation

The repo includes a lightweight evaluator:

```bash
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
```

It runs a small golden set with KG expansion on/off and tracks:

- answer term recall
- citation hit rate
- expected-source MRR
- KG-vs-plain metric deltas
- latency
- expanded concepts
- approximate answer tokens

This creates a baseline for AI engineering discipline. A production system would
expand this into a larger human-reviewed and regression-gated evaluation suite.

## Key Tradeoffs

### Neo4j

Chosen because prerequisite traversal, concept neighborhoods, and learning-path
queries are graph-native. The tradeoff is operational weight and a need for
careful Cypher safety.

### OpenSearch

Chosen because the prototype needs lexical BM25 and dense retrieval in one
service. For very small corpora, SQLite FTS or Chroma would be simpler but would
not demonstrate hybrid production retrieval as clearly.

### Local-first LLMs

Chosen because education data has privacy concerns. The tradeoff is hardware
cost and cold-start latency. Remote fallback exists for demo reliability, not as
the preferred privacy posture.

### Next.js frontend

Chosen over Streamlit because graph interaction, streaming chat, and repeated
learning workflows need a real frontend. The tradeoff is a larger build and test
surface.

## Production Gap List

- Replace API-key auth with identity, roles, and tenant-aware access control.
- Move blocking Neo4j/OpenSearch calls off the event loop or use async clients.
- Add OpenTelemetry spans for retrieval and generation.
- Add a persistent question bank and assessment attempt ledger.
- Add database migrations and backups.
- Expand RAG evaluation and require eval deltas in CI.
- Provision a real staging environment for automated browser E2E tests.
