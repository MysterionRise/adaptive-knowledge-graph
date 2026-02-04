# Architecture Documentation

This document describes the technical architecture of the Adaptive Knowledge Graph platform.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                        │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                      Next.js Frontend (Port 3000)                          │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐  │  │
│  │  │ KnowledgeGraph│ │  Quiz.tsx   │ │ LearningPath │ │    Chat Interface   │  │  │
│  │  │  (Cytoscape) │ │             │ │    .tsx      │ │                     │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘  │  │
│  │                           ↓ HTTP/REST ↓                                    │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               API LAYER                                          │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                    FastAPI Backend (Port 8000)                              │  │
│  │                                                                             │  │
│  │  ┌──────────────────────────────────────────────────────────────────────┐  │  │
│  │  │ MIDDLEWARE: CORS │ Rate Limiting (slowapi) │ API Key Auth (optional) │  │  │
│  │  └──────────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                             │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐  │  │
│  │  │  /api/v1/ask │ │/api/v1/quiz │ │/api/v1/graph│ │/api/v1/learning-path│  │  │
│  │  │  (Q&A RAG)   │ │ (Generate)  │ │  (Stats)    │ │   (Prerequisites)   │  │  │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └─────────┬───────────┘  │  │
│  │         │               │               │                   │              │  │
│  │         ▼               ▼               ▼                   ▼              │  │
│  │  ┌──────────────────────────────────────────────────────────────────────┐  │  │
│  │  │              BUSINESS LOGIC LAYER (backend/app/)                      │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │  │
│  │  │  │ RAG      │ │ NLP      │ │ KG       │ │ Student  │ │ Quiz     │   │  │  │
│  │  │  │ Retriever│ │ LLM      │ │ Adapter  │ │ Model    │ │ Generator│   │  │  │
│  │  │  │          │ │ Client   │ │          │ │ (BKT/IRT)│ │          │   │  │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │  │
│  │  └──────────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                    │                   │                   │
                    ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                             DATA LAYER                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │     Neo4j        │  │   OpenSearch      │  │         Ollama                │  │
│  │  (Port 7474)     │  │   (Port 9200)     │  │       (Port 11434)            │  │
│  │                  │  │                   │  │                               │  │
│  │  • Concepts      │  │  • Chunk vectors  │  │  • Llama 3.1 8B (4-bit)       │  │
│  │  • Modules       │  │  • BGE-M3 1024d   │  │  • Structured output          │  │
│  │  • PREREQUISITE  │  │  • Hybrid search  │  │  • Answer generation          │  │
│  │  • RELATED_TO    │  │    (kNN + BM25)   │  │  • Quiz MCQ creation          │  │
│  │  • NEXT (chunks) │  │                   │  │                               │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Frontend (Next.js)

**Location:** `frontend/`

| Component | File | Purpose |
|-----------|------|---------|
| KnowledgeGraph | `components/KnowledgeGraph.tsx` | Cytoscape.js graph visualization |
| Quiz | `components/Quiz.tsx` | Interactive quiz with mastery tracking |
| LearningPath | `components/LearningPath.tsx` | Prerequisite chain visualization |
| ErrorBoundary | `components/ErrorBoundary.tsx` | Graceful error handling |
| Providers | `components/Providers.tsx` | Client-side context providers |

**State Management:** Zustand store (`lib/store.ts`) for:
- Mastery tracking per concept
- Quiz answers and scores
- User preferences

### 2. API Layer (FastAPI)

**Location:** `backend/app/api/`

#### Route Modules

| Module | Endpoints | Purpose |
|--------|-----------|---------|
| `routes/ask.py` | `POST /api/v1/ask` | KG-aware RAG Q&A |
| `routes/quiz.py` | `POST /api/v1/quiz/generate` | LLM quiz generation |
| `routes/graph.py` | `GET /api/v1/graph/*` | Graph operations |
| `routes/learning_path.py` | `GET /api/v1/learning-path/*` | Prerequisite chains |

#### Middleware Stack

1. **CORS** - Allow frontend origins
2. **Rate Limiting** (slowapi) - Prevent abuse
   - `/ask`: 10 req/min
   - `/quiz`: 5 req/min
   - `/graph/*`: 30 req/min
3. **API Key Auth** (optional) - Protect sensitive endpoints

#### Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Basic liveness (always healthy if running) |
| `GET /health/live` | Kubernetes liveness probe |
| `GET /health/ready` | Readiness with dependency checks |

### 3. Business Logic Layer

**Location:** `backend/app/`

#### RAG Pipeline (`rag/`)

```
Question → KG Expansion → Retrieval → Reranking → LLM Generation → Answer
    │           │             │            │             │
    │           ▼             ▼            ▼             ▼
    │      Neo4j:       OpenSearch:   BGE-Reranker:  Ollama:
    │      Extract      Hybrid kNN    Score & filter Generate
    │      concepts     + BM25        top-k          with context
    │           │             │            │             │
    └───────────┴─────────────┴────────────┴─────────────┘
                    Window Retrieval (NEXT relationships)
```

**Key Components:**

| Component | File | Purpose |
|-----------|------|---------|
| Retriever | `rag/retriever.py` | OpenSearch hybrid search |
| KG Expander | `rag/kg_expansion.py` | Query enhancement via graph |
| Window Retriever | `rag/window_retriever.py` | NEXT relationship traversal |
| Chunker | `rag/chunker.py` | 512-token overlapping chunks |

#### Knowledge Graph (`kg/`)

| Component | File | Purpose |
|-----------|------|---------|
| Neo4jAdapter | `kg/neo4j_adapter.py` | Graph CRUD operations |
| Schema | `kg/schema.py` | Node/edge type definitions |
| CypherQA | `kg/cypher_qa.py` | Natural language → Cypher |

#### NLP Services (`nlp/`)

| Component | File | Purpose |
|-----------|------|---------|
| LLM Client | `nlp/llm_client.py` | Ollama + OpenRouter wrapper |
| Embeddings | `nlp/embeddings.py` | BGE-M3 encoding |
| Concept Extractor | `nlp/concept_extractor.py` | YAKE + KeyBERT extraction |

### 4. Data Layer

#### Neo4j Graph Schema

```cypher
// Nodes
(:Concept {name, importance_score, key_term, chapter})
(:Module {id, title, chapter})
(:Chunk {id, text, embedding})

// Relationships
(:Concept)-[:PREREQUISITE]->(:Concept)
(:Concept)-[:RELATED_TO]->(:Concept)
(:Module)-[:CONTAINS]->(:Concept)
(:Chunk)-[:NEXT]->(:Chunk)  // Window retrieval
```

#### OpenSearch Index

```json
{
  "mappings": {
    "properties": {
      "text": { "type": "text" },
      "embedding": {
        "type": "knn_vector",
        "dimension": 1024
      },
      "module_id": { "type": "keyword" },
      "chapter": { "type": "keyword" }
    }
  }
}
```

## Request Flow Examples

### 1. Q&A Request (`POST /api/v1/ask`)

```
1. User asks: "What caused the American Revolution?"

2. KG Expansion (if enabled):
   - Extract concepts: ["American Revolution"]
   - Query Neo4j for related concepts
   - Expand to: ["American Revolution", "Taxation", "Boston Tea Party", "Independence"]

3. Retrieval:
   - Hybrid search in OpenSearch (kNN + BM25)
   - Retrieve top 20 chunks
   - BGE-Reranker filters to top 5

4. Window Expansion (if enabled):
   - For each chunk, traverse NEXT relationships
   - Include surrounding context chunks

5. LLM Generation:
   - Format context + question as prompt
   - Generate answer via Ollama
   - Include source citations

6. Response with sources, expanded concepts, model info
```

### 2. Quiz Generation (`POST /api/v1/quiz/generate`)

```
1. User requests quiz on "American Revolution"

2. Content Retrieval:
   - Search for chunks mentioning topic
   - Select diverse content for question variety

3. LLM Generation:
   - For each chunk, generate MCQ with:
     - Question text
     - 4 options (1 correct, 3 distractors)
     - Explanation
     - Related concept

4. Response with quiz questions, metadata
```

## Security Considerations

### Authentication

- **API Key Auth**: Optional, configured via `API_KEY` env var
- **Development Mode**: Auth disabled when no key configured
- **Timing-safe comparison**: Prevents timing attacks

### Rate Limiting

- Prevents DOS and abuse
- Per-IP tracking with X-Forwarded-For support
- Configurable limits per endpoint type

### Data Privacy

- **Local-first**: Default mode runs entirely on-device
- **No telemetry**: No usage data sent externally
- **Opt-in remote**: OpenRouter fallback is explicit opt-in

## Deployment Options

### Development

```bash
docker compose -f infra/compose/compose.yaml --profile cpu up -d
poetry run uvicorn backend.app.main:app --reload
cd frontend && npm run dev
```

### Production (Docker Compose)

```bash
docker compose -f infra/compose/compose.yaml --profile gpu up -d
```

### Production (Kubernetes)

See `infra/k8s/` for:
- Deployment manifests
- Service definitions
- ConfigMaps and Secrets
- Horizontal Pod Autoscaler

## Performance Characteristics

| Operation | Typical Latency | Notes |
|-----------|-----------------|-------|
| Q&A (local LLM) | 2-5s | Depends on context length |
| Q&A (remote LLM) | 1-3s | Network dependent |
| Quiz generation | 5-10s | 3 questions default |
| Graph visualization | <500ms | Limited to 100 nodes |
| Health check | <100ms | Cached connections |

## Monitoring

### Metrics (Prometheus)

- Request latency (p50, p95, p99)
- Error rates by endpoint
- LLM token usage
- Database connection pool

### Logging (Loguru)

- Structured JSON logs
- Request tracing
- Error stack traces
- Performance timing

---

## Further Reading

- [Testing Guide](../TESTING.md) - How to run and write tests
- [Compliance](../COMPLIANCE.md) - OpenStax licensing compliance
- [Contributing](../CONTRIBUTING.md) - How to contribute
