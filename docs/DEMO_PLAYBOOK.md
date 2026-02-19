# Demo Playbook — Adaptive Knowledge Graph

**Duration:** 30 minutes
**Audience:** Delivery Leaders, Technical Solution Architects, VPs
**Goal:** Present as a credible production accelerator, not a toy PoC

---

## Pre-Demo Checklist

Run these **30 minutes before the demo** starts:

### 1. Start Services
```bash
# Start Neo4j + OpenSearch
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch

# Wait for services to be healthy (~15s)
sleep 15

# Verify services
curl -sf http://localhost:7474 && echo "Neo4j OK"
curl -sf http://localhost:9200 && echo "OpenSearch OK"

# Ensure Ollama is running with the model
ollama list  # Should show llama3.1:8b-instruct-q4_K_M
```

### 2. Configure Environment
```bash
# Use demo-optimized config
cp .env.demo .env

# IMPORTANT: Set your OpenRouter API key
# Edit .env and set: OPENROUTER_API_KEY=sk-or-v1-...
```

### 3. Seed Demo Data
```bash
# One-command: ingests books, builds KG, indexes OpenSearch, seeds student profile
bash scripts/seed_demo.sh
```

### 4. Start Backend + Frontend
```bash
# Terminal 1: API
make run-api

# Terminal 2: Frontend
cd frontend && npm run dev
```

### 5. Warm-Up Verification
```bash
# Health check (all services green)
curl http://localhost:8000/health/ready | python -m json.tool

# Quick Q&A test (verifies full pipeline)
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What caused the American Revolution?", "subject": "us_history"}'

# Verify graph has data
curl "http://localhost:8000/api/v1/graph/stats?subject=us_history"
curl "http://localhost:8000/api/v1/graph/stats?subject=economics"

# Open browser tabs in advance
open http://localhost:3000          # Frontend
open http://localhost:8000/docs     # API Docs
open http://localhost:7474          # Neo4j Browser (backup)
```

---

## Minute-by-Minute Script

### 0:00–3:00 — Opening (Problem Statement)

**Talking Points:**
- "Traditional e-learning delivers the same content to every student"
- "Knowledge Graphs capture how concepts relate — prerequisites, co-occurrence"
- "RAG alone retrieves text. KG-RAG retrieves *structured understanding*"
- "This PoC demonstrates how KG + RAG + adaptive learning work together"

**Show:** Architecture slide or README diagram

---

### 3:00–7:00 — Architecture Deep Dive

**Show:** `http://localhost:8000/docs` (Swagger UI)

**Talking Points:**
- "FastAPI backend with 25+ endpoints across 5 route groups"
- Point out the tag grouping: Q&A, Quiz & Adaptive Learning, Knowledge Graph, etc.
- "Neo4j for graph storage, OpenSearch for vector search, Ollama/OpenRouter for LLM"
- "Privacy-first: entire stack can run locally with Ollama — no data leaves the machine"
- "For this demo, we use OpenRouter for reliability, but production can be fully local"

**Technical audience hook:** Show the `/health/ready` endpoint — "observability built in, checks all three services"

```bash
curl http://localhost:8000/health/ready | python -m json.tool
```

---

### 7:00–10:00 — Knowledge Graph Visualization

**Navigate:** `http://localhost:3000/graph`

**Actions:**
1. Let the graph load — point out the force-directed layout
2. "Each node is a concept extracted from OpenStax textbooks, sized by PageRank importance"
3. Click on a high-importance node (e.g., "American Revolution")
4. "Notice how it highlights connected concepts — prerequisites, related topics"
5. "Edge colors show relationship types: red = prerequisite, blue = covers, purple = related"
6. Switch subject to **Economics** using the dropdown — "Same visualization, different knowledge domain"
7. Switch back to **US History**

---

### 10:00–15:00 — AI Tutor Chat (Streaming)

**Navigate:** `http://localhost:3000/chat`

**Actions:**
1. Ensure **KG Expansion** toggle is ON
2. Type: "What caused the American Revolution?"
3. **Key moment:** Watch tokens stream in real-time — "Notice the streaming response, no waiting for the full answer"
4. Point out the **KG Expansion** panel: "The system traversed the knowledge graph to find related concepts before searching"
5. Show the **Sources** section — "Every claim is backed by textbook passages with relevance scores"
6. Click **"View on Graph"** — navigates to graph with those concepts highlighted
7. Go back to chat, ask: "How did the Constitution address the failures of the Articles of Confederation?"
8. "Notice it pulls from different chapters but connects the concepts coherently"

---

### 15:00–17:00 — Comparison: KG-RAG vs Plain RAG

**Talking Points (can show via chat):**
- Toggle KG Expansion OFF, ask the same question
- "Without KG expansion, it only searches for literal text matches"
- Toggle KG Expansion ON, ask again
- "With KG expansion, it finds related concepts first, then retrieves more comprehensive context"
- "This is the key differentiator — the knowledge graph provides *structured understanding*"

---

### 17:00–22:00 — Adaptive Quiz

**Navigate:** `http://localhost:3000/assessment`

**Actions:**
1. "The student profile is pre-loaded with mixed mastery levels"
2. Point out the **Adaptive Mode** toggle is ON
3. Point out the **Mastery Indicator** — shows current mastery for selected topic
4. Select topic: "The Civil War" (medium mastery ~55%)
5. "System targets medium difficulty because this student has partial understanding"
6. Click **Start Adaptive Assessment**
7. **Key moment:** Show the progress steps during generation — "Retrieving from KG, generating with LLM"
8. Answer questions — intentionally get one right and one wrong
9. "Watch the mastery update in real-time after each answer — +15% for correct, -10% for incorrect"
10. Finish quiz — show the **Results Modal** with score ring
11. Point out **Post-Quiz Recommendations**: "For weak areas, it shows prerequisites and reading materials. For strong areas, it suggests advancement topics"

---

### 22:00–25:00 — Recommendations + Learning Path

**Still in quiz results modal:**
1. "Remediation block shows prerequisites the student should review"
2. "Advancement block shows deeper topics for mastered concepts"
3. Click **"View Learning Path"** — navigates to graph with concept highlighted
4. "The learning path shows prerequisite chains — what to study first"

---

### 25:00–27:00 — Multi-Subject

**Actions:**
1. Switch to **Economics** using the subject picker (any page)
2. Navigate to Graph — "Same visualization, different domain"
3. Go to Chat, ask: "What is supply and demand?"
4. "The entire pipeline — KG expansion, retrieval, LLM generation — works across subjects"
5. "Adding a new subject is config-driven: add to `subjects.yaml`, run the pipeline"

---

### 27:00–28:00 — API & Technical Quality

**Quick flash through:**
1. `http://localhost:8000/docs` — "Full OpenAPI documentation with examples"
2. "Rate limiting configured on all endpoints"
3. "83+ tests passing, CI/CD with pre-commit hooks"
4. "Type-checked with MyPy, formatted with Ruff"

**If asked about scalability:**
- "Neo4j scales horizontally with clustering, OpenSearch with sharding"
- "Each subject has isolated graph labels and search indices"
- "LLM layer is swappable — Ollama for local, OpenRouter for cloud, direct API for enterprise"

---

### 28:00–30:00 — Q&A

**Common questions and answers:**

**"How long to add a new subject?"**
> "Config change + pipeline run. Define books in `subjects.yaml`, run `seed_demo.sh`. 15 minutes for a standard OpenStax textbook."

**"What about production hardening?"**
> "Add proper auth (JWT), switch to managed databases (Neo4j Aura, Amazon OpenSearch Service), deploy behind a load balancer. The architecture is designed for this."

**"How does the adaptive model work?"**
> "Currently BKT-inspired: +15% mastery on correct, -10% on incorrect, with difficulty targeting. Production would use full Bayesian Knowledge Tracing or IRT models — the interfaces are already built."

**"What about latency?"**
> "Graph traversal: <50ms. OpenSearch retrieval: <100ms. LLM: depends on model. With streaming, the user sees first tokens in <1s even when total generation takes 5-10s."

---

## Fallback Plan

### If Neo4j goes down:
- Graph pages will fail. Focus on chat (uses OpenSearch only) and quiz features.
- Restart: `docker compose -f infra/compose/compose.yaml restart neo4j`

### If OpenSearch goes down:
- Chat and quiz will fail. Focus on graph visualization and architecture discussion.
- Restart: `docker compose -f infra/compose/compose.yaml restart opensearch`

### If LLM fails (OpenRouter):
- Switch to local: `LLM_MODE=local` in `.env`, restart API
- Have Ollama pre-downloaded: `ollama pull llama3.1:8b-instruct-q4_K_M`

### If frontend crashes:
- Restart: `cd frontend && npm run dev`
- Fallback: demonstrate via curl commands from terminal (looks impressive to technical audience)

### If everything fails:
- Show the codebase: architecture, test suite, CI/CD pipeline
- Show the API docs at `/docs`
- Show the Neo4j Browser directly at `http://localhost:7474`

---

## Key URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | — |
| API Docs | http://localhost:8000/docs | — |
| Health Check | http://localhost:8000/health/ready | — |
| Neo4j Browser | http://localhost:7474 | neo4j / password |
| OpenSearch | http://localhost:9200 | (security disabled) |

## Key curl Commands

```bash
# Ask a question
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What caused the Civil War?", "subject": "us_history"}'

# Generate quiz
curl -X POST "http://localhost:8000/api/v1/quiz/generate-adaptive?topic=The%20Constitution&student_id=default"

# Graph stats
curl "http://localhost:8000/api/v1/graph/stats?subject=us_history"

# Student profile
curl "http://localhost:8000/api/v1/student/profile?student_id=default"

# All subjects
curl http://localhost:8000/api/v1/subjects
```
