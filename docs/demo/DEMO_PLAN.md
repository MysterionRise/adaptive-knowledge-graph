# Demo Plan: 15-Minute Talk

A talk-style demo that combines the [slides](../../demo-slides/index.html) with
live API calls. For the standard workflow and readiness gate, see
[README.md](README.md).

## Pre-demo checklist

| Service | URL | Status command |
| --- | --- | --- |
| Neo4j | http://localhost:7474 | `docker compose -f infra/compose/compose.yaml ps neo4j` |
| OpenSearch | http://localhost:9200 | `curl localhost:9200` |
| Ollama | http://localhost:11434 | `curl localhost:11434/api/tags` |
| FastAPI | http://localhost:8000/docs | `curl localhost:8000/health` |
| Frontend | http://localhost:3000 | `cd frontend && npm run dev` |

### Quick start

```bash
# 1. Start Neo4j and OpenSearch
make up

# 2. Check that Ollama has llama3.1:8b-instruct-q4_K_M
curl http://localhost:11434/api/tags

# 3. In .env, enable the features the talk shows:
#    RERANKER_ENABLED=true
#    STUDENT_BKT_ENABLED=true
#    RERANKER_DEVICE=cpu

# 4. Start the API (restart it after changing .env)
make run-api

# 5. Reset the learner profile for a clean demo
curl -X POST http://localhost:8000/api/v1/student/reset

# 6. Start the frontend
cd frontend && npm run dev
```

### Data available

US History and Economics are seeded, with about 19,000 chunks in total. For the
current concept, module and relationship counts, call
`curl http://localhost:8000/api/v1/graph/stats` (they change whenever the
knowledge-graph pipeline changes).

---

## Demo flow (15 minutes)

### Slides 1–3: Problem, KG-aware RAG, architecture (3 min)

Open `demo-slides/index.html` in a browser and walk through slides 1–3.

Talking points per slide:

- **Slide 1:** why: expensive APIs, generic content, privacy concerns.
- **Slide 2:** how: regular RAG (5 steps) compared with KG-aware RAG, which
  adds concept extraction, graph traversal and cross-encoder reranking.
- **Slide 3:** architecture, all local: Next.js, FastAPI, Neo4j, OpenSearch
  and Ollama, with two seeded subjects.

### Step 1: Ask a question (3 min)

Switch to the live app at http://localhost:3000.

**Recommended question:** "What was the Stamp Act and how did it lead to
colonial resistance?"

> This question works well because the retriever finds relevant chunks and the
> LLM produces a substantive answer with citations. Very broad questions such as
> "What caused the American Revolution?" can pull in tangential chunks.

What happens behind the scenes:

1. Concept extraction identifies key terms in the question.
2. Graph traversal finds related concepts in Neo4j.
3. OpenSearch retrieves 20 candidate chunks (hybrid kNN + BM25).
4. **The BGE cross-encoder reranks** the 20 candidates and keeps the top 5.
5. Ollama (llama3.1:8b) generates an answer with source citations.

**Response fields to highlight:**

- `retrieved_count: 20` confirms that 20 chunks were fetched for reranking.
- `sources` shows the 5 reranked chunks sent to the LLM.
- `expanded_concepts` lists the concepts found through the graph.
- `model` shows the model that produced the answer, running locally.

**API call** (if you show a terminal):

```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What was the Stamp Act and how did it lead to colonial resistance?","subject":"us_history","top_k":5}'
```

The API log shows `Reranked 20 chunks, kept top 5`.

**Economics example:**

```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"How does supply and demand determine market prices?","subject":"economics","top_k":5}'
```

### Step 2: Explore the knowledge graph (2 min)

Open the graph page and show:

- concept nodes and the edges between them
- a clicked concept and its connections
- how the graph structure informs the query expansion from step 1

**Graph data API:**

```bash
curl 'http://localhost:8000/api/v1/graph/data?subject=us_history&limit=50'
# Returns the nodes and edges used by the Cytoscape.js view
```

### Step 3: Take an adaptive quiz (3 min)

Generate a quiz. The endpoint takes **query parameters**, not a JSON body:

```bash
# Check the starting difficulty (a fresh learner has 0.30 mastery, so "easy")
curl 'http://localhost:8000/api/v1/student/target-difficulty?concept=The+Civil+War'
# -> {"concept":"The Civil War","mastery_level":0.3,"target_difficulty":"easy"}

# Generate an adaptive quiz
curl -X POST 'http://localhost:8000/api/v1/quiz/generate-adaptive?topic=The+Civil+War&subject=us_history&num_questions=3'
```

- The starting difficulty is "easy" (default mastery 0.30).
- The quiz returns multiple-choice questions with options, the correct answer
  and an explanation.
- After each answer, the mastery update sets the difficulty of the next quiz.

### Step 4: BKT mastery progression (3 min)

Show Bayesian mastery updates live:

```bash
# Answer 1 (correct): 0.30 -> 0.646, a large Bayesian jump
curl -X POST http://localhost:8000/api/v1/student/mastery \
  -H 'Content-Type: application/json' \
  -d '{"concept":"The Civil War","correct":true}'
# -> {"previous_mastery":0.3,"new_mastery":0.646,"bkt_p_known":0.6461,"target_difficulty":"medium"}

# Answer 2 (correct): 0.646 -> 0.881
# Answer 3 (correct): 0.881 -> 0.967
# Answer 4 (incorrect): 0.967 -> 0.819, a clear drop
curl -X POST http://localhost:8000/api/v1/student/mastery \
  -H 'Content-Type: application/json' \
  -d '{"concept":"The Civil War","correct":false}'

# Answer 5 (correct): 0.819 -> 0.948, recovers but not fully
```

**Recorded trace** from a test run:

```text
Answer 1 (correct): 0.300 → 0.646 | bkt=0.6461 | difficulty=medium
Answer 2 (correct): 0.646 → 0.881 | bkt=0.8811 | difficulty=hard
Answer 3 (correct): 0.881 → 0.967 | bkt=0.9675 | difficulty=hard
Answer 4 (incorrect): 0.967 → 0.819 | bkt=0.8188 | difficulty=hard
Answer 5 (correct): 0.819 → 0.948 | bkt=0.9479 | difficulty=hard
```

**Talking points:**

- The earlier model was linear (+0.15 / −0.10) and could not model guessing or
  slipping.
- BKT uses four parameters: P(L), P(Transit) = 0.1, P(Slip) = 0.1 and
  P(Guess) = 0.25.
- The response includes `bkt_p_known`, the Bayesian probability that the
  learner knows the skill.
- Three correct answers reach near-mastery (0.97); one wrong answer drops it to
  0.82 because the model accounts for slips and guesses.
- BKT is a standard model from the learning-science literature (Corbett and
  Anderson, 1994). The parameters here are fixed defaults, not fitted to
  learner data.
- `STUDENT_BKT_ENABLED=false` switches back to the linear model.

### Slide 5: What's next (1 min)

Return to the slides. BKT and the reranker are marked as shipped. The
remaining roadmap covers more subjects and deeper evaluation.

---

## Warm-up commands (5 minutes before the demo)

```bash
# 1. Reset the profile for a clean state
curl -X POST http://localhost:8000/api/v1/student/reset

# 2. Warm up OpenSearch, Neo4j, the reranker and Ollama with one call.
#    The first call downloads the reranker model and can take a minute or more;
#    later calls take seconds.
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What was the Stamp Act?","subject":"us_history","top_k":5}'

# 3. Reset the profile again after the warm-up
curl -X POST http://localhost:8000/api/v1/student/reset

# 4. Check that everything is healthy
curl http://localhost:8000/health/ready
curl http://localhost:8000/api/v1/graph/stats
```

---

## Fallback options

| Issue | Fallback |
| --- | --- |
| Ollama not responding | Restart Ollama and warm it up again. Only if the audience has approved remote calls: set `PRIVACY_LOCAL_ONLY=false`, `LLM_MODE=remote` and `OPENROUTER_API_KEY` in `.env`, then restart the API |
| Reranker model download slow | Set `RERANKER_ENABLED=false` and demo without it |
| Frontend not starting | Demo entirely through the Swagger UI at `localhost:8000/docs` |
| Neo4j down | KG expansion is skipped automatically; hybrid search still works |
| OpenSearch down | Q&A cannot be shown (core dependency) |

## Key API endpoints

| Endpoint | Method | Parameters | Purpose |
| --- | --- | --- | --- |
| `/api/v1/ask` | POST | JSON: question, subject, top_k | Q&A with KG-aware RAG and the reranker |
| `/api/v1/ask/stream` | POST | JSON: same as `/ask` | Streaming answer (SSE) |
| `/api/v1/student/mastery` | POST | JSON: concept, correct | BKT mastery update |
| `/api/v1/student/profile` | GET | none | Mastery levels |
| `/api/v1/student/target-difficulty` | GET | query: concept | Difficulty for a concept |
| `/api/v1/student/reset` | POST | none | Reset the profile for a demo |
| `/api/v1/quiz/generate-adaptive` | POST | query: topic, subject, num_questions | Adaptive quiz generation |
| `/api/v1/graph/stats` | GET | none | Knowledge-graph statistics |
| `/api/v1/graph/data` | GET | query: subject, limit | Graph visualization data |
| `/api/v1/subjects` | GET | none | Available subjects |
