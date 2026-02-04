# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Adaptive Knowledge Graph - a PoC for personalized learning combining Knowledge Graphs (Neo4j), Vector Search (OpenSearch), and Local LLMs (Ollama). Built with FastAPI backend and Next.js frontend.

## Common Commands

### Development
```bash
make install-dev          # Install all dev dependencies + pre-commit hooks
make dev-setup            # Full setup: install-dev + start Docker services
make run-api              # Start FastAPI on port 8000 (with reload)
cd frontend && npm run dev  # Start Next.js on port 3000
```

### Testing & Quality
```bash
make test                 # Run pytest with coverage
make pre-commit           # Run all checks: format → lint → type-check → test
pytest -m unit            # Run only unit tests
pytest -m "not slow"      # Skip slow tests
pytest backend/tests/test_settings.py::test_specific  # Run single test
```

### Docker Services
```bash
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch  # Start DBs only
docker compose -f infra/compose/compose.yaml --profile cpu up -d     # CPU mode
docker compose -f infra/compose/compose.yaml --profile gpu up -d     # GPU mode
make docker-down          # Stop all services
```

### Data Pipeline
```bash
make pipeline-all         # Run complete pipeline: fetch → parse → normalize → build-kg → index-rag
poetry run python scripts/ingest_books.py  # Ingest US History demo data
```

## Architecture

```
Frontend (Next.js)          Backend (FastAPI)           Services
├── /app (pages)            ├── /api/routes.py          ├── Neo4j (graph DB)
├── /components             ├── /kg/ (graph ops)        ├── OpenSearch (vectors)
└── /lib (api-client)       ├── /rag/ (retrieval)       └── Ollama (local LLM)
                            ├── /nlp/ (embeddings)
                            └── /student/ (quiz gen)
```

**Key flow for Q&A (`/api/v1/ask`):**
1. Query → KG expansion (extract concepts, traverse graph)
2. OpenSearch retrieval (semantic search + BM25 hybrid)
3. BGE-Reranker filtering
4. LLM answer generation with citations

## Key Modules

- `backend/app/api/routes.py` - REST endpoints (`/ask`, `/generate-quiz`, `/graph/stats`)
- `backend/app/kg/` - Knowledge graph schema, builder, Neo4j adapter
- `backend/app/rag/` - Chunker (512 tokens), retriever, KG expansion
- `backend/app/nlp/llm_client.py` - Ollama + OpenRouter client wrapper
- `backend/app/student/quiz_generator.py` - LLM-based MCQ generation
- `frontend/components/KnowledgeGraph.tsx` - Cytoscape.js visualization

## Environment Setup

Copy `.env.example` to `.env`. Key variables:
- `LLM_MODE=local` - Use Ollama (default) vs `remote` for OpenRouter
- `PRIVACY_LOCAL_ONLY=true` - Disable remote API calls
- `EMBEDDING_DEVICE=cuda/cpu` - Hardware for BGE-M3

## Test Configuration

Tests in `backend/tests/`. Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`

Coverage targets `backend/app`, excluding tests and `__init__.py`.

## Code Style

- Ruff for linting/formatting (line-length: 100)
- MyPy for type checking (backend/app and scripts/)
- Pre-commit hooks configured in `.pre-commit-config.yaml`

## Service URLs (Local Dev)

- Neo4j Browser: http://localhost:7474 (neo4j/password)
- OpenSearch: http://localhost:9200
- API Docs: http://localhost:8000/docs
- Frontend: http://localhost:3000
