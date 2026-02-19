# 5-Minute Demo Script — Adaptive Knowledge Graph

**Duration:** 5 minutes | **Pace:** Fast, visual, no setup on screen
**Pre-req:** All services running (see Pre-Demo Checklist below)

---

## Script

### 0:00–0:30 — Hook (Dashboard)

**Open:** `http://localhost:3000`

> "This is an AI-powered adaptive learning platform that combines Knowledge Graphs, vector search, and LLMs to create personalized learning experiences. Let me show you the three features that make it different."

Point at KG stats (200 concepts, 17K relationships), mastery bars, feature cards.

---

### 0:30–1:30 — Knowledge Graph (60s)

**Navigate:** `http://localhost:3000/graph`

1. Graph loads with force-directed layout — "Each node is a concept from OpenStax textbooks, sized by importance"
2. Click a large node — "See the relationships: related topics, prerequisite chains"
3. Switch subject dropdown to **Economics** — "Entire pipeline works across subjects, config-driven"
4. Switch back to **US History**

---

### 1:30–3:00 — AI Chat with Streaming (90s)

**Navigate:** `http://localhost:3000/chat`

1. Ensure **KG Expansion** is ON
2. Type: **"What caused the American Revolution?"**
3. Watch tokens stream in — "Real-time streaming, no waiting"
4. Point at **KG Expansion** panel: "The system traversed the knowledge graph first to find related concepts like colonial taxation and British Parliament, then retrieved from the vector store"
5. Point at **Sources**: "Every answer has citations with relevance scores from the actual textbook"

---

### 3:00–4:30 — Adaptive Quiz (90s)

**Navigate:** `http://localhost:3000/assessment`

1. "The student has pre-loaded mastery — some topics strong, some weak"
2. Point at mastery indicators
3. Select topic: **"The Civil War"** (~55% mastery)
4. **Adaptive Mode ON** → Generate quiz
5. Answer 1-2 questions quickly
6. "Watch mastery update after each answer"
7. Finish → Show **Results** with score + **Recommendations**: "Remediation for weak areas, advancement for strong areas"

---

### 4:30–5:00 — Wrap-Up

> "In summary: Knowledge Graph provides structured understanding, not just keyword matching. The adaptive student model personalizes difficulty in real-time. The entire stack runs locally — zero data leaves the machine. And adding a new subject is a config change plus a pipeline run."

**Flash:** `http://localhost:8000/docs` — "Full OpenAPI docs, 25+ endpoints, rate-limited, type-checked, 83+ tests passing."

---

## Pre-Demo Checklist

Run **10 minutes before** the demo:

```bash
# 1. Verify all services are running
curl -s http://localhost:8000/health/ready | python3 -m json.tool
# Expect: neo4j=ok, opensearch=ok/degraded(yellow), ollama=ok

# 2. Verify data is populated
curl -s 'http://localhost:8000/api/v1/graph/stats?subject=us_history'
# Expect: concept_count=200, relationship_count=17051

curl -s 'http://localhost:8000/api/v1/graph/stats?subject=economics'
# Expect: concept_count=200, relationship_count=20103

# 3. Verify student profile is seeded
curl -s 'http://localhost:8000/api/v1/student/profile?subject=us_history'
# Expect: overall_ability=0.54, mastery_levels with 12 concepts

# 4. Warm up the LLM (first call is slow)
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the Constitution?", "subject": "us_history"}' > /dev/null

# 5. Open browser tabs
open http://localhost:3000          # Frontend
open http://localhost:3000/graph    # Graph page
open http://localhost:3000/chat     # Chat page
open http://localhost:3000/assessment  # Quiz page
open http://localhost:8000/docs     # API docs
```

## If Something Breaks

| Issue | Quick Fix |
|-------|-----------|
| LLM slow/timeout | LLM was cold — the warm-up call above prevents this |
| Graph page empty | Wrong subject selected, or Neo4j down → `docker compose -f infra/compose/compose.yaml restart neo4j` |
| Chat returns error | Check `curl http://localhost:8000/health/ready` → restart backend if needed |
| Frontend won't load | `cd frontend && npm run dev` |
| Fallback | Demo from terminal with curl commands (impresses technical audience) |
