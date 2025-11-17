# Adaptive Knowledge Graph in Education

**PoC: Personalized Learning with Knowledge Graphs, Local LLMs, and OpenStax Content**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11--3.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com)
[![CI](https://github.com/yourusername/adaptive-knowledge-graph/workflows/CI/badge.svg)](https://github.com/yourusername/adaptive-knowledge-graph/actions)

**📚 [Testing Guide](./TESTING.md) | 🤝 [Contributing](./CONTRIBUTING.md) | 🔒 [Compliance](./COMPLIANCE.md)**

---

## Overview

This is a **proof-of-concept Adaptive Knowledge Graph** that combines:
- **Knowledge Graph construction** from OpenStax Biology 2e textbooks
- **Local-first LLM execution** optimized for NVIDIA RTX 4070 (12GB VRAM)
- **KG-aware Retrieval-Augmented Generation (RAG)** with semantic search
- **Adaptive learning** using Bayesian Knowledge Tracing (BKT) and Item Response Theory (IRT)
- **Privacy-focused design** with opt-in remote LLM fallback (OpenRouter)

Built for educators, researchers, and developers exploring **personalized education technology** with **transparent, reusable, and production-ready components**.

---

## Features

### 📚 Knowledge Graph Construction
- Automatic concept extraction from textbook content (YAKE, KeyBERT, BGE-M3)
- Relationship mining: PREREQ, COVERS, ASSESS, RELATED edges
- Neo4j graph database with RDF/Turtle export for interoperability

### 🤖 Local-First LLM Stack
- **Primary**: Llama 3.1 8B / Qwen2.5 7B (4-bit quantized) via Ollama
- **Fallback**: OpenRouter API for optional cloud models
- Structured output with Outlines/Instructor for JSON generation
- RTX 4070 optimized (runs smoothly with 4-bit models)

### 🔍 KG-Aware RAG
- BGE-M3 embeddings + BGE-Reranker v2-m3 for high-precision retrieval
- Knowledge graph expansion: query "photosynthesis" → auto-includes prereq concepts
- Qdrant vector database with optional GPU indexing
- Citation tracking with OpenStax CC BY 4.0 attribution

### 🎓 Adaptive Learning
- **BKT (pyBKT)**: Track mastery per concept over time
- **IRT (py-irt)**: Model exercise difficulty and student ability
- **Next-Best-Action policy**: Recommend optimal next concepts based on:
  - Mastery gaps
  - Prerequisite requirements
  - Optimal difficulty zone

### 🎨 Interactive UI (Next.js + Cytoscape.js)
- **Concept Map**: Navigable graph with mastery visualization
- **Adaptive Path**: Recommended learning sequence with rationale
- **Tutor Chat**: KG-aware Q&A with citations
- **Practice Panel**: Adaptive exercises with instant feedback
- **Teacher Mode**: Inspect/edit KG edges and recommendation logic

---

## Attribution & Licensing

### OpenStax Content
> **Content adapted from OpenStax Biology 2e**
> Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
> OpenStax™ is a trademark of Rice University. This project is not affiliated with or endorsed by OpenStax.

**Compliance Notes**:
- ✅ We **attribute OpenStax** in UI footers and all exports
- ✅ We do **NOT train models** on OpenStax content
- ✅ Remote LLM calls are **opt-in** via `PRIVACY_LOCAL_ONLY=true` (default)
- ✅ API prompts are minimal and transformative (concept extraction, not reproduction)

### Project License
This software is licensed under the [MIT License](./LICENSE). See [LICENSE](./LICENSE) for details.

---

## Architecture

```
┌─────────────────┐         ┌──────────────────┐
│   Next.js UI    │────────▶│   FastAPI API    │
│  (Cytoscape.js) │  HTTP   │  (REST/WebSocket)│
└─────────────────┘         └────────┬─────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
              │   Neo4j   │   │  Qdrant   │   │  Ollama   │
              │    (KG)   │   │ (Vectors) │   │  (Local)  │
              └───────────┘   └───────────┘   └───────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.11-3.13 (recommended: 3.11 or 3.12)
- Docker & Docker Compose
- (Optional) NVIDIA GPU with 12GB+ VRAM and nvidia-docker for GPU mode

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/adaptive-knowledge-graph.git
cd adaptive-knowledge-graph

# Install Poetry if not already installed
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# (Optional) Install student modeling libraries
poetry install --with pybkt --with pyirt

# Set up pre-commit hooks
poetry run pre-commit install
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings (Neo4j password, OpenRouter API key if using remote)
```

### 3. Start Services

```bash
# Option A: CPU-only mode
docker compose -f infra/compose/compose.yaml --profile cpu up -d

# Option B: GPU mode (RTX 4070)
docker compose -f infra/compose/compose.yaml --profile gpu up -d

# Option C: Just databases (run API locally)
docker compose -f infra/compose/compose.yaml up -d neo4j qdrant
poetry run uvicorn backend.app.main:app --reload
```

### 4. Verify Services

- **Neo4j Browser**: http://localhost:7474 (user: `neo4j`, pass: `password`)
- **Qdrant Dashboard**: http://localhost:6333/dashboard
- **API Health**: http://localhost:8000/health
- **API Docs**: http://localhost:8000/docs

---

## Development Workflow

### Run Data Pipeline

```bash
# Fetch OpenStax Biology 2e (from philschatz GitHub mirror)
make fetch-data

# Parse HTML to structured JSON
make parse-data

# Normalize with attribution
make normalize-data

# Build knowledge graph (extract concepts, mine edges, persist to Neo4j)
make build-kg

# Index content to Qdrant for RAG
make index-rag

# Or run entire pipeline
make pipeline-all
```

### Run Tests

```bash
make test              # Run pytest with coverage
make lint              # Run ruff linting
make format            # Auto-format with ruff
make type-check        # Run mypy type checking
make pre-commit        # Run all pre-commit checks
```

### Start Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
# Visit http://localhost:3000
```

---

## Project Structure

```
adaptive-kg/
├── backend/
│   ├── app/
│   │   ├── api/              # REST + WebSocket routes
│   │   ├── core/             # Settings, logging, config
│   │   ├── kg/               # Graph schema, builders, Neo4j adapter
│   │   ├── nlp/              # Extractors, embeddings, rerankers
│   │   ├── rag/              # Chunking, retriever, QA
│   │   ├── student/          # BKT, IRT, recommendation policy
│   │   └── ui_payloads/      # API DTOs
│   └── tests/
├── frontend/                 # Next.js UI (Concept Map, Chat, Practice)
├── data/
│   ├── raw/                  # Downloaded textbook HTML
│   └── processed/            # Normalized JSON + chunks
├── infra/
│   ├── docker/               # CPU/GPU Dockerfiles
│   └── compose/              # docker-compose.yaml
├── scripts/                  # Data pipeline & graph build scripts
├── notebooks/                # RAGAS evaluation notebooks
├── pyproject.toml            # Poetry dependencies
├── Makefile                  # Dev commands
└── README.md
```

---

## Configuration

Key settings in `.env`:

```bash
# LLM Mode
LLM_MODE=local              # local, remote, or hybrid
LLM_LOCAL_MODEL=llama3.1:8b-instruct-q4_K_M
OPENROUTER_API_KEY=sk-...  # Only if using remote

# Privacy
PRIVACY_LOCAL_ONLY=true     # Disable all remote API calls

# Hardware
EMBEDDING_DEVICE=cuda       # cuda or cpu
RERANKER_DEVICE=cuda

# RAG
RAG_KG_EXPANSION=true       # Enable KG-aware query expansion
RAG_RETRIEVAL_TOP_K=20
RAG_FINAL_TOP_K=5

# Student Model
STUDENT_BKT_ENABLED=true
STUDENT_IRT_ENABLED=true
```

---

## Evaluation

Run RAGAS metrics to evaluate RAG quality:

```bash
make eval-rag
# Opens Jupyter notebook with:
# - Contextual Precision/Recall
# - Faithfulness
# - Answer Relevance
```

Compare configurations:
- **KG-expanded vs plain RAG**: Does graph expansion improve retrieval?
- **With vs without reranker**: Does BGE-Reranker improve precision?

---

## Hardware Requirements

### Minimum (CPU-only)
- 16GB RAM
- 50GB disk space

### Recommended (GPU)
- NVIDIA RTX 4070 (12GB VRAM) or better
- 32GB RAM
- 100GB SSD

**LLM Sizing for RTX 4070 (12GB)**:
- ✅ Llama 3.1 8B (4-bit): ~4.5GB VRAM
- ✅ Qwen2.5 7B (4-bit): ~4GB VRAM
- ✅ BGE-M3 embeddings: ~1GB VRAM
- ✅ BGE-Reranker v2-m3: ~1GB VRAM
- **Total**: ~6-7GB (comfortable headroom)

---

## Roadmap

### PoC Complete (Current)
- ✅ Data ingestion (OpenStax Biology 2e)
- ✅ KG construction (Neo4j + RDF export)
- ✅ KG-aware RAG (Qdrant + BGE-M3)
- ✅ Adaptive learning (BKT + IRT)
- ✅ Demo UI (Next.js + Cytoscape.js)
- ✅ Local-first runtime (RTX 4070 optimized)

### 2026 Production Goals
- [ ] Multi-book support (all OpenStax subjects)
- [ ] SPARQL endpoint for interoperability
- [ ] Multilingual support (BGE-M3 multi-lang)
- [ ] Teacher authoring tools (graph editing UI)
- [ ] Assessment generation (LLM-based MCQ creation)
- [ ] A/B testing framework
- [ ] Production deployment (Kubernetes + GPU cluster)

---

## Contributing

Contributions welcome! This is an educational PoC designed for **reuse and extension**.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## Acknowledgments

- **OpenStax** for open educational resources
- **philschatz** for GitHub textbook mirrors
- **BAAI** for BGE embeddings/rerankers
- **Ollama** for local LLM runtime
- **Neo4j**, **Qdrant** for graph/vector databases

---

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/adaptive-knowledge-graph/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/adaptive-knowledge-graph/discussions)

---

## License

MIT License - see [LICENSE](./LICENSE) for details.

**OpenStax content** is licensed under CC BY 4.0 - see attribution notices in the application.

