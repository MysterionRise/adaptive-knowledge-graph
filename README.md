# Adaptive Knowledge Graph

Production-shaped KG-RAG learning platform prototype for AI engineering portfolio review.

This project demonstrates how to combine a knowledge graph, hybrid retrieval,
local-first LLM inference, streaming answers, and adaptive assessment workflows
in one end-to-end system. It is intentionally positioned as a serious prototype:
real architecture, real tests, real data pipelines, and explicit production gaps.

## Current Portfolio Rating

- Engineering portfolio project: 7/10
- Real AI platform prototype: 6/10
- Production readiness: 4/10

The repo is not a toy shell. It has FastAPI, Next.js, Neo4j, OpenSearch,
Ollama/OpenRouter support, KG-aware RAG, SSE streaming, multi-subject config,
Docker Compose, data ingestion scripts, and broad tests. The remaining work is
mostly hardening: evaluation depth, auth, persistence, observability, CI
strictness, and deployment discipline.

## What Is Implemented

| Area | Current state |
| --- | --- |
| KG-RAG Q&A | FastAPI endpoint with KG expansion, OpenSearch retrieval, optional reranking, citations, and streaming |
| Knowledge graph | Neo4j concept/module/chunk schema, subject label isolation, graph visualization payloads |
| Retrieval | OpenSearch kNN and hybrid BM25 + vector retrieval with reciprocal rank fusion |
| LLM layer | Ollama local mode, OpenRouter remote mode, hybrid fallback, streaming support |
| Frontend | Next.js app with graph, chat, comparison, assessment, learning path, and subject picker views |
| Adaptive assessment | LLM-generated MCQs, BKT-inspired mastery updates, target difficulty, post-quiz recommendations |
| Multi-subject | `config/subjects.yaml` drives subject prompts, indices, labels, themes, and attribution |
| Local infrastructure | Docker Compose for Neo4j, OpenSearch, CPU/GPU API containers |
| Evaluation | Lightweight golden-set RAG evaluator in `scripts/evaluate_rag.py` |

## What Is Not Yet Production-Grade

- Authentication is API-key based and intended as a local/deployment boundary,
  not a full user identity system.
- Student profile persistence now defaults to SQLite, but there is no tenant,
  role, or institutional data model.
- BKT is implemented as an in-app Bayesian update; IRT is not calibrated with
  real learner response data.
- LLM-generated quiz difficulty is useful for demos, but not psychometrically
  validated.
- Some integrations use synchronous clients inside async routes. This is
  acceptable for the demo path, but not for high concurrency.
- CI has been tightened for core checks, while full browser E2E is manual until
  a reliable demo backend is provisioned in CI.

## Architecture

```text
Next.js UI
  -> FastAPI API
      -> Neo4j knowledge graph
      -> OpenSearch hybrid/vector retrieval
      -> Ollama local LLM or OpenRouter fallback
      -> SQLite student mastery store
```

Important design choices:

- Neo4j is used because prerequisite chains and concept expansion are naturally
  graph-shaped.
- OpenSearch is used because the prototype needs both lexical BM25 and dense
  vector retrieval in one service.
- Local-first LLM mode is the default privacy posture; remote fallback is a demo
  reliability option.
- Multi-subject support uses label/index isolation rather than separate Neo4j
  databases so it works on Neo4j Community Edition.

## Quick Start

Prerequisites:

- Python 3.11-3.13
- Poetry
- Docker and Docker Compose
- Node.js 20+
- Optional: Ollama with a local model

```bash
poetry install --without pyirt,pybkt
cd frontend && npm ci && cd ..
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch
poetry run uvicorn backend.app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

Open:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- Readiness: `http://localhost:8000/health/ready`

## Demo Path

Use the demo env template and seed script:

```bash
cp .env.demo.example .env
make demo-seed
make run-api
cd frontend && npm run dev
```

Expected demo flow:

1. Load graph statistics and visualize concepts.
2. Ask a KG-RAG question with citations.
3. Compare KG-RAG against plain retrieval.
4. Generate an adaptive quiz.
5. Show mastery update and post-quiz recommendations.

## Evaluation

Run the lightweight RAG evaluator against a live backend:

```bash
make eval-rag-api
```

Inputs live in `data/evals/golden_qa.yaml`; reports are written to
`docs/evals/latest.json` and `docs/evals/latest.md`.

Tracked signals:

- answer term recall
- citation hit rate
- expected-source MRR
- KG-vs-plain retrieval deltas
- KG expansion concepts
- latency
- failure count
- approximate answer token count

## Test Commands

Backend fast suite:

```bash
make test-fast
```

Backend adversarial/risk-register suite:

```bash
make test-tribunal
```

Frontend:

```bash
cd frontend
npm run type-check
npm test -- --ci --runInBand
npm run test:e2e -- --project=chromium
```

Demo acceptance:

```bash
make demo-check
```

## Security Posture

- `API_KEY` is empty by default for local development.
- When `API_KEY` is configured, protected endpoints require `X-API-Key`.
- OpenRouter TLS verification is enabled by default.
- OpenSearch defaults to local HTTP in Compose; production should use managed
  TLS, auth, snapshots, and network isolation.
- `/health/ready` returns 503 when critical dependencies are unavailable.
- Error messages are redacted before they are exposed through health surfaces.
- `X-Forwarded-For` is ignored for rate limiting unless trusted proxy headers
  are explicitly enabled.

## CTO Notes

Tradeoffs made intentionally:

- Chose Neo4j + OpenSearch over a simpler single-database stack because the
  portfolio signal is graph-aware RAG, not just a chatbot.
- Kept local-first LLM support despite hardware cost because student data
  privacy is central to the domain.
- Kept the frontend as a real Next.js app rather than Streamlit because graph
  visualization, streaming, and repeated workflows matter for the demo.
- Kept demo-grade adaptive learning, but documented the psychometric limits
  instead of pretending the system is certification-ready.

Next production steps:

- Replace API-key auth with real identity, roles, and tenant boundaries.
- Add managed deployment manifests and observability dashboards.
- Expand the evaluation set and require eval deltas in pull requests.
- Move blocking graph/search calls off the event loop or adopt async clients.
- Add signed assessment attempts and a real question bank before using the
  platform for credentials.

## License and Attribution

Project code is MIT licensed. OpenStax content is CC BY 4.0 and is attributed in
API responses, docs, and UI flows. This project is not affiliated with or
endorsed by OpenStax or Rice University.
