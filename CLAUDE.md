# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Adaptive Knowledge Graph is a local-first proof of concept for adaptive learning over OpenStax textbooks. It combines a Neo4j knowledge graph, OpenSearch hybrid retrieval (BM25 + kNN) and a local LLM served by Ollama, with a FastAPI backend and a Next.js frontend. US History and Economics are seeded by default; subjects are defined in `config/subjects.yaml`.

## Common Commands

### Setup and local stack

```bash
make quickstart             # Install deps, check Ollama + model, start Neo4j/OpenSearch, seed US History + Economics
make doctor                 # Check the local environment
make up                     # Start Neo4j + OpenSearch (waits until healthy)
make down                   # Stop them (volumes are kept)
make seed                   # Seed US History and Economics (SUBJECT=<id> for one)
make install-dev            # Dev dependencies + pre-commit hooks
make run-api                # FastAPI on port 8000 with reload
cd frontend && npm ci && npm run dev   # Next.js on port 3000
```

### Testing and quality

```bash
make test                   # All backend tests with coverage
make test-fast              # Everything except the tribunal suite
make test-tribunal          # Tribunal (adversarial review) suite only
make lint                   # ruff check backend/ scripts/
make format                 # ruff format + ruff check --fix
make type-check             # mypy (paths from [tool.mypy] files: backend/app, scripts)
make pre-commit             # format -> lint -> type-check -> test
poetry run pytest -m unit   # By marker: unit, integration, slow, tribunal
poetry run pytest backend/tests/test_settings.py::test_settings_defaults   # Single test
cd frontend && npm run lint && npm run type-check && npm test -- --ci && npm run build
```

### Data and evaluation

```bash
make ingest-books SUBJECT=economics   # Fetch and normalize a subject's books
make build-kg SUBJECT=economics       # Build that subject's knowledge graph in Neo4j
make index-rag SUBJECT=economics      # Embed and index its chunks in OpenSearch
make build-windows SUBJECT=economics  # Chunk NEXT edges in Neo4j for one subject (only for opt-in window retrieval)
make demo-eval                        # Golden-set evaluation against the running API
```

The scripted demo uses `make demo-client-prep`, `make demo-client-check` and `make demo-client-reset` (see `docs/demo/README.md`).

## Architecture

```text
Frontend (Next.js)          Backend (FastAPI, backend/app/)            Services
├── app/ (pages)            ├── api/routes/ (ask, quiz, graph,          ├── Neo4j (knowledge graph)
├── components/             │   learning_path, subjects, demo)          ├── OpenSearch (BM25 + kNN)
└── lib/ (api-client)       ├── core/ (settings, subjects, auth, ...)   ├── Ollama (local LLM)
                            ├── kg/ (schema, builder, adapter, Cypher)  └── SQLite (learner profiles)
                            ├── rag/ (retriever, KG expansion, reranker)
                            ├── nlp/ (embeddings, concepts, LLM client)
                            └── student/ (quizzes, BKT, recommendations)
```

**Key flow for Q&A (`POST /api/v1/ask`, streaming `POST /api/v1/ask/stream`):**

1. Validate input (markup in questions or invalid fields: 422, without echoing input) and resolve the subject from `config/subjects.yaml` (no subject: `default_subject`; unknown subject: 404).
2. KG expansion: extract concepts (spaCy NER + YAKE), match them in Neo4j, add neighbours within `RAG_KG_EXPANSION_HOPS`.
3. OpenSearch retrieval: hybrid BM25 + kNN fused with reciprocal rank fusion (`RETRIEVAL_MODE=hybrid`, default) or kNN only.
4. Optional window retrieval: opt-in, needs `VECTOR_BACKEND=neo4j` or `hybrid` and NEXT edges between chunks (built by `make build-windows`, not by the standard seed).
5. Optional reranking: `backend/app/rag/reranker.py` (cross-encoder `BAAI/bge-reranker-v2-m3`), opt-in via `RERANKER_ENABLED=true`; retrieves `RAG_RETRIEVAL_TOP_K` candidates and keeps `top_k`.
6. LLM answer with citations and the subject's attribution. On `/ask`: LLM unavailable 503, empty or invalid LLM output 502 (the quiz endpoints use the same contract). `/ask/stream` returns 503 only before streaming starts; later failures and empty answers arrive as an SSE `error` event.

## Key Modules

- `backend/app/api/routes/` - REST endpoints package, mounted under `/api/v1`:
  - `ask.py` - `/ask`, `/ask/stream`
  - `quiz.py` - `/quiz/generate`, `/quiz/generate-adaptive`, `/quiz/recommendations`, `/student/*`
  - `graph.py` - `/graph/stats`, `/graph/data`, `/graph/query`, `/graph/schema`, `/concepts/*`
  - `learning_path.py`, `subjects.py`, `demo.py` (`/demo/status`)
- `backend/app/main.py` - app setup, middleware, `/health`, `/health/ready`, `/health/live`
- `backend/app/core/settings.py` - all settings (pydantic-settings, reads `.env`)
- `backend/app/core/subjects.py` - loads `config/subjects.yaml`
- `backend/app/kg/` - graph schema, builder, Neo4j adapter (label-prefix isolation per subject), Cypher QA
- `backend/app/rag/` - chunker (512 characters, 128 overlap), retriever (hybrid/RRF), KG expansion, reranker, window retriever
- `backend/app/nlp/llm_client.py` - Ollama + OpenRouter client
- `backend/app/student/` - quiz generator, student service (BKT mastery, SQLite storage), recommendations
- `frontend/components/KnowledgeGraph.tsx` - Cytoscape.js visualization
- `scripts/evaluate_rag.py` - golden-set evaluation over `data/evals/golden_qa.yaml`

## Environment Setup

Defaults work without a `.env`; copy `.env.example` to `.env` to override. Key variables:

- `APP_ENV=development` (default: no API key, loud warning) or `production` (refuses to start without `API_KEY` or with `*` in `CORS_ORIGINS`/`CORS_ALLOW_METHODS`/`CORS_ALLOW_HEADERS`; `/docs`, `/redoc`, `/openapi.json` off unless `API_DOCS_ENABLED=true`). Protected routes (`/student/*`, `/quiz/generate-adaptive`, `/quiz/recommendations`, `/graph/query`) need `X-API-Key` when a key is set. `API_KEY` must be printable ASCII without surrounding whitespace (and at least 16 characters in production), or startup fails; a whitespace-only key counts as no key. `API_DOCS_ENABLED` unset or empty follows the `APP_ENV` default; `true`/`false` force it
- `TRUST_PROXY_HEADERS=true` keys rate limits on the right-most `X-Forwarded-For` hop; only behind a proxy that appends the client IP
- `PRIVACY_LOCAL_ONLY=true` (default) - requires `LLM_MODE=local`, a loopback/private `LLM_OLLAMA_HOST` and a non-cloud `LLM_LOCAL_MODEL`, and refuses LangSmith tracing variables; startup fails otherwise (checks in `backend/app/core/privacy.py`). The API also disables LangSmith tracing at runtime and sets `HF_HUB_OFFLINE=1` once its models are cached
- `LLM_MODE=local` - Ollama (default); `remote` = OpenRouter, `hybrid` = Ollama with OpenRouter fallback
- `EMBEDDING_DEVICE=auto` - picks cuda, then mps, then cpu for BGE-M3 (`RERANKER_DEVICE` accepts the same values)
- `RERANKER_ENABLED=false` - set `true` to enable the cross-encoder reranker
- `STUDENT_PROFILES_DB` - SQLite learner store (the only backend); `STUDENT_VALIDATE_CONCEPTS=true` rejects mastery updates for concepts not in the subject's graph
- `RATE_LIMIT_DEFAULT` (`100/minute`, `;`-separated for several) - every route except the health checks, per client and endpoint, counted before auth; `RATE_LIMIT_ASK`, `RATE_LIMIT_QUIZ`, `RATE_LIMIT_GRAPH`, `RATE_LIMIT_GRAPH_QUERY`, `RATE_LIMIT_STUDENT_WRITE`, `RATE_LIMIT_RECOMMENDATIONS` - stricter per-route limits

Removed backend settings (ignored if still present in an old `.env`): `API_HOST`, `API_PORT`, `LLM_LOCAL_BACKEND`, `LLM_MAX_CONTEXT`, `RERANKER_TOP_K`, `RAG_FINAL_TOP_K`, `STUDENT_IRT_ENABLED`, `STUDENT_STORAGE_BACKEND`, `PRIVACY_NO_TRACKING`, `GRAPH_COMPUTE_CENTRALITY`, `GRAPH_COMPUTE_COMMUNITIES`. (`API_HOST`/`API_PORT` are still read by `make run-api` and Compose, not by the app.)

## Test Configuration

Backend tests are in `backend/tests/` with shared mocks in `conftest.py`; see `docs/TESTING.md`. An autouse `network_guard` fixture fails any non-loopback connection or DNS lookup. Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.tribunal`.

The tribunal suite (`backend/tests/test_tribunal_prosecution.py`) encodes the findings of the archived adversarial review in `docs/archive/tribunal-2026-02/`. `xfail_strict = true`: when a known defect is fixed, remove its `xfail` marker in the same change. The remaining strict xfails are linked to #73 (per-learner identity) and #74 (server-side grading). CI runs the regular suite on Python 3.11-3.13 with `-m "not tribunal"` and the tribunal suite in its own job (advisory until the v0.3.0 release makes it required). The required status check on `main` is `All Checks Passed`; see `docs/TESTING.md` for the job list.

Coverage targets `backend/app`, excluding tests and `__init__.py`; CI's Tests job and `make test-fast` fail below 75% (`--cov-fail-under=75`).

## Code Style

- Ruff for linting/formatting (line-length: 100, pyupgrade rules: use `list[str]` and `X | None`)
- MyPy for type checking (backend/app and scripts/)
- Pre-commit hooks configured in `.pre-commit-config.yaml` mirror the CI checks
- Conventional Commits for commit messages and PR titles; PRs are squash-merged after the required `All Checks Passed` check passes

## Service URLs (Local Dev)

- Neo4j Browser: <http://localhost:7474> (neo4j/password)
- OpenSearch: <http://localhost:9200>
- Ollama: <http://localhost:11434>
- API: <http://localhost:8000> (docs at `/docs` in development mode only)
- Frontend: <http://localhost:3000>
