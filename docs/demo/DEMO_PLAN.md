# Demo Plan: Adaptive Knowledge Graph

## Pre-Demo Checklist

| Service     | URL                           | Status Command                     |
|-------------|-------------------------------|------------------------------------|
| Neo4j       | http://localhost:7474         | `docker ps \| grep neo4j`          |
| OpenSearch  | http://localhost:9200         | `curl localhost:9200`              |
| Ollama      | http://localhost:11434        | `curl localhost:11434/api/tags`    |
| FastAPI     | http://localhost:8000/docs    | `curl localhost:8000/health`       |
| Frontend    | http://localhost:3000         | `cd frontend && npm run dev`       |

### Quick Start

```bash
# 1. Verify Docker services
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch

# 2. Check Ollama (must have llama3.1:8b-instruct-q4_K_M)
curl http://localhost:11434/api/tags

# 3. .env should have:
#    RERANKER_ENABLED=true
#    STUDENT_BKT_ENABLED=true
#    RERANKER_DEVICE=cpu

# 4. Start API (restart if .env changed)
make run-api

# 5. Reset student profile for clean demo
curl -X POST http://localhost:8000/api/v1/student/reset

# 6. Start frontend
cd frontend && npm run dev
```

### Data Available

- **US History**: 8,947 chunks, 200 concepts, 176 modules
- **Economics**: 9,929 chunks, 200 concepts, 177 modules
- **Neo4j**: 400 concepts total, 37K relationships (RELATED + COVERS edges)

---

## Demo Flow (15 minutes)

### Slides 1-3: Problem, KG-Aware RAG, Architecture (3 min)

Open `demo-slides/index.html` in browser. Walk through slides 1-3.

Key talking points per slide:
- **Slide 1**: Why — expensive APIs, generic content, privacy concerns
- **Slide 2**: How — compare regular RAG (5-step) vs KG-Aware RAG (8-step with concept extraction, graph traversal, and cross-encoder reranking)
- **Slide 3**: Architecture — all local: Next.js + FastAPI + Neo4j + OpenSearch + Ollama. 400 concepts, 54K relationships, 19K chunks across 2 subjects

### Step 1: Ask a Question (3 min)

Switch to the live app at http://localhost:3000.

**Recommended demo question:** "What was the Stamp Act and how did it lead to colonial resistance?"

> This question works well because the retriever finds relevant chunks and the LLM
> produces a substantive answer with citations. Avoid broad questions like "What
> caused the American Revolution?" — the retriever may pull in tangential chunks.

What happens behind the scenes:
1. Concept extraction identifies key terms in the question
2. KG traversal finds related concepts via RELATED edges in Neo4j
3. OpenSearch retrieves 20 candidate chunks (hybrid: kNN semantic + BM25 keyword)
4. **BGE cross-encoder reranks** all 20 and keeps the top 5
5. Ollama (llama3.1:8b) generates an answer with source citations

**Response fields to highlight:**
- `retrieved_count: 20` — confirms 20 chunks were fetched for reranking
- `sources` — shows the 5 reranked chunks sent to the LLM
- `expanded_concepts` — concepts found via KG traversal
- `model` — llama3.1:8b-instruct-q4_K_M (runs locally)

**API verification** (if showing terminal):
```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What was the Stamp Act and how did it lead to colonial resistance?","subject":"us_history","top_k":5}'
```

API logs will show: `"Reranked 20 chunks, kept top 5"`

**Also try economics:**
```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"How does supply and demand determine market prices?","subject":"economics","top_k":5}'
```

### Step 2: Explore Knowledge Graph (2 min)

Navigate to the graph visualization page. Show:
- Concept nodes with RELATED edges between them
- Click a concept to see its connections
- Note how graph structure informs query expansion in Step 1

**API for graph data:**
```bash
curl 'http://localhost:8000/api/v1/graph/data?subject=us_history&limit=50'
# Returns nodes and edges for Cytoscape.js visualization
```

### Step 3: Take an Adaptive Quiz (3 min)

Generate a quiz. The endpoint uses **query parameters** (not JSON body):

```bash
# Check initial difficulty (fresh student = 0.30 mastery = "easy")
curl 'http://localhost:8000/api/v1/student/target-difficulty?concept=The+Civil+War'
# → {"concept":"The Civil War","mastery_level":0.3,"target_difficulty":"easy"}

# Generate adaptive quiz
curl -X POST 'http://localhost:8000/api/v1/quiz/generate-adaptive?topic=The+Civil+War&subject=us_history&num_questions=3'
```

- Show that initial difficulty = "easy" (mastery at default 0.30)
- Quiz returns MCQ questions with options, correct answer, and explanation
- After answering, mastery updates drive the next quiz's difficulty

### Step 4: BKT Mastery Progression (3 min) — NEW FEATURE

This is the key new feature. Show Bayesian mastery updates live:

```bash
# Answer 1 (correct): 0.30 → 0.646 — big Bayesian jump
curl -X POST http://localhost:8000/api/v1/student/mastery \
  -H 'Content-Type: application/json' \
  -d '{"concept":"The Civil War","correct":true}'
# → {"previous_mastery":0.3,"new_mastery":0.646,"bkt_p_known":0.6461,"target_difficulty":"medium"}

# Answer 2 (correct): 0.646 → 0.881
# Answer 3 (correct): 0.881 → 0.967
# Answer 4 (incorrect): 0.967 → 0.819 — significant drop, student may be guessing
curl -X POST http://localhost:8000/api/v1/student/mastery \
  -H 'Content-Type: application/json' \
  -d '{"concept":"The Civil War","correct":false}'

# Answer 5 (correct): 0.819 → 0.948 — recovers but not fully
```

**Verified convergence trace** (from actual test run):
```
Answer 1 (correct): 0.300 → 0.646 | bkt=0.6461 | difficulty=medium
Answer 2 (correct): 0.646 → 0.881 | bkt=0.8811 | difficulty=hard
Answer 3 (correct): 0.881 → 0.967 | bkt=0.9675 | difficulty=hard
Answer 4 (incorrect): 0.967 → 0.819 | bkt=0.8188 | difficulty=hard
Answer 5 (correct): 0.819 → 0.948 | bkt=0.9479 | difficulty=hard
```

**Talking points:**
- Old model: linear +0.15/-0.10 (crude, doesn't model guessing/slipping)
- New BKT model: 4 parameters — P(L), P(Transit)=0.1, P(Slip)=0.1, P(Guess)=0.25
- Response includes `bkt_p_known` — the Bayesian probability of knowing the skill
- 3 correct → near-mastery (0.97), but 1 wrong drops to 0.82 (accounts for slip/guess)
- Same algorithm used in Carnegie Learning / Khan Academy
- Toggled via `STUDENT_BKT_ENABLED` env var — set to `false` to revert to linear model

### Slide 5: What's Next (1 min)

Return to slides. Show that BKT and Reranker are now marked as "Shipped!" (green border).
Remaining roadmap: more subjects, RAGAS evaluation benchmarks.

---

## Pre-Warm Commands (Run 5 min before demo)

```bash
# 1. Reset profile for clean state
curl -X POST http://localhost:8000/api/v1/student/reset

# 2. Pre-warm Ollama + reranker model (first call downloads BGE model ~1GB)
#    This single call warms up: OpenSearch, Neo4j, reranker, and Ollama
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What was the Stamp Act?","subject":"us_history","top_k":5}'
# First call may take ~90s (model download). Subsequent calls: ~10-15s.

# 3. Reset profile again after warm-up
curl -X POST http://localhost:8000/api/v1/student/reset

# 4. Verify everything is healthy
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/graph/stats
```

---

## Fallback Options

| Issue | Fallback |
|-------|----------|
| Ollama not responding | Set `LLM_MODE=remote` + `OPENROUTER_API_KEY` in .env |
| Reranker model download slow | Set `RERANKER_ENABLED=false` (demo without it) |
| Frontend not starting | Demo entirely via Swagger UI at `localhost:8000/docs` |
| Neo4j down | KG expansion auto-disables, hybrid search still works |
| OpenSearch down | Cannot demo Q&A (core dependency) |

## Key API Endpoints

| Endpoint | Method | Params | Purpose |
|----------|--------|--------|---------|
| `/api/v1/ask` | POST | JSON: question, subject, top_k | Q&A with KG-aware RAG + reranker |
| `/api/v1/ask/stream` | POST | JSON: same as /ask | SSE streaming answer |
| `/api/v1/student/mastery` | POST | JSON: concept, correct | BKT mastery update |
| `/api/v1/student/profile` | GET | — | View mastery levels (simplified) |
| `/api/v1/student/target-difficulty` | GET | query: concept | Check difficulty level |
| `/api/v1/student/reset` | POST | — | Reset profile for demo |
| `/api/v1/quiz/generate-adaptive` | POST | query: topic, subject, num_questions | Adaptive quiz generation |
| `/api/v1/graph/stats` | GET | — | KG statistics |
| `/api/v1/graph/data` | GET | query: subject, limit | Graph visualization data |
| `/api/v1/subjects` | GET | — | List available subjects |
