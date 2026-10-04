# Case Study: Adaptive Knowledge Graph

## Problem

Education teams do not need another generic chatbot over course material. They
need AI over approved learning content: answers that cite licensed sources,
concept relationships that authors can inspect, adaptive practice that
educators can review, and quality metrics that engineers can track for
regressions.

This project builds that shape as a local OpenStax prototype: KG-aware RAG plus
adaptive assessment over open textbooks. It is a pilot prototype, not
production certification infrastructure.

## Product thesis

For retraining and exam preparation, a useful AI learning system needs:

- grounded answers with citations
- concept relationships, not just vector similarity
- adaptive practice based on mastery
- local-first deployment for privacy
- measurable retrieval and answer quality
- human review before any high-stakes assessment use

## Architecture

```text
Next.js UI -> FastAPI -> Neo4j + OpenSearch + local LLM (Ollama) -> SQLite mastery store
```

Key capabilities:

- KG expansion before retrieval
- hybrid BM25 + vector search with reciprocal rank fusion
- an optional cross-encoder reranker
- streaming answers
- multi-subject configuration
- graph visualization
- LLM-generated quizzes
- Bayesian Knowledge Tracing mastery updates
- a golden-set RAG evaluation harness

## Hard decisions

### Neo4j instead of vectors alone

Vectors retrieve similar text; the graph models prerequisite and
related-concept structure. That makes learning paths and remediation
explainable.

### OpenSearch instead of a small local vector library

BM25 plus dense retrieval in one service is the more realistic production
shape, even though it adds operational weight.

### Local-first LLMs

Education data has privacy constraints. The default Ollama mode shows that the
whole architecture runs locally, and `PRIVACY_LOCAL_ONLY=true` blocks remote
models unless someone deliberately turns it off.

### Honest adaptive learning

The system implements Bayesian Knowledge Tracing with fixed parameters and
LLM-estimated question difficulty. It makes no claims of calibrated IRT
without learner response data.

## Evidence

Implemented:

- FastAPI service with OpenAPI docs
- Next.js UI for graph, chat, comparison and assessment workflows
- Neo4j graph adapter and schema
- OpenSearch hybrid retriever
- LLM client for local, remote and hybrid modes, with local-only enforcement
- SQLite learner profile storage
- request IDs and response-time headers
- a production mode that requires an API key
- a golden-set evaluator for KG versus plain retrieval
- a demo readiness dashboard
- scripted local demo commands

Validation commands:

```bash
make demo-client-prep
make demo-eval
make demo-client-check
make test-fast
cd frontend && npm run type-check && npm test -- --ci
```

## Known gaps

- no per-learner identity or tenant model
- quizzes are graded in the browser
- no calibrated psychometric question bank
- no production deployment manifests
- browser tests against a live stack are manual
- evaluation metrics are heuristic and need human review before production use
- no LMS or LTI integration yet

## What comes next

See the project [roadmap](../../ROADMAP.md). The main themes are:

- evaluation deltas for every retrieval or prompt change
- per-learner identity, server-side grading and tenant boundaries
- tracing for graph, retrieval, reranking and LLM calls
- async graph and search clients
- a reviewed question bank and an assessment attempt ledger
- a deployment runbook with backups and recovery notes
