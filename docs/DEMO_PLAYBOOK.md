# Demo Playbook

Audience: CTO, VP Engineering, AI platform lead, technical founder.

Goal: show a credible KG-RAG platform prototype and the engineering judgment
behind it. Do not present it as production-ready certification infrastructure.

## Pre-Demo Checklist

Run 20-30 minutes before the demo:

```bash
cp .env.demo.example .env
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch
bash scripts/seed_demo.sh
poetry run uvicorn backend.app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

Verify:

```bash
curl -s http://localhost:8000/health/ready | python -m json.tool
curl -s "http://localhost:8000/api/v1/graph/stats?subject=us_history"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What caused the American Revolution?", "subject": "us_history"}'
```

Open:

- `http://localhost:3000`
- `http://localhost:3000/graph`
- `http://localhost:3000/chat`
- `http://localhost:3000/comparison`
- `http://localhost:3000/assessment`
- `http://localhost:8000/docs`

## 30-Minute Script

### 0-3 min: Positioning

Say:

> This is a production-shaped KG-RAG learning platform prototype. It is not a
> production certification product. The portfolio signal is architecture
> judgment: graph-aware retrieval, local-first LLMs, streaming UX, adaptive
> assessment, evaluation hooks, and explicit hardening gaps.

Show README sections:

- implemented vs not production-grade
- CTO notes
- evaluation command

### 3-8 min: Architecture

Show API docs and `docs/ARCHITECTURE.md`.

Talking points:

- FastAPI coordinates RAG, graph, quiz, and student profile workflows.
- Neo4j stores concepts and relationships.
- OpenSearch provides hybrid BM25 + vector retrieval.
- Ollama is the local-first inference path; remote fallback is optional.
- SQLite now stores local student mastery state.
- `/health/ready` checks critical dependencies and returns 503 when they are down.

### 8-13 min: Graph

Open `/graph`.

Actions:

1. Show concept count and relationship count.
2. Click a high-importance node.
3. Explain prerequisite/related relationships.
4. Switch subjects and explain config-driven isolation.

CTO framing:

> The graph is not decoration. It is used to expand queries, explain learning
> paths, and drive remediation/advancement recommendations.

### 13-18 min: KG-RAG Chat

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- streaming tokens
- expanded concepts
- citations and scores
- request ID / response-time headers if using network tools

Then toggle KG expansion off or use `/comparison`.

CTO framing:

> The important thing is not that KG-RAG is always better. The important thing
> is that the system exposes the retrieval path and now has an evaluation harness
> for ablations.

### 18-23 min: Adaptive Assessment

Open `/assessment`.

Actions:

1. Select a topic.
2. Generate an adaptive quiz.
3. Answer one question correctly and one incorrectly.
4. Show mastery update and recommendations.

Say:

> This is adaptive-learning infrastructure, not a validated psychometric exam.
> BKT-style updates are implemented; IRT calibration is a future step requiring
> real learner response data.

### 23-26 min: Evaluation

Show:

```bash
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
```

Explain outputs:

- `docs/evals/latest.json`
- `docs/evals/latest.md`
- answer term recall
- citation hit rate
- expected-source MRR
- KG vs plain retrieval deltas for recall, citation hit rate, MRR, and latency

### 26-30 min: Hardening and Roadmap

Show:

- CI no longer suppresses core type/test failures.
- Jest and Playwright suites are separated.
- OpenRouter TLS verification defaults to true.
- OpenSearch image is pinned.
- protected student/graph-query endpoints enforce API key when configured.
- SQLite replaces default JSON student persistence.

Close with:

> The next 90 days are not about adding flashy features. They are about identity,
> tenant isolation, observability, eval expansion, deployment, and assessment
> integrity.

## 5-Minute Variant

1. README positioning and architecture diagram: 45 seconds.
2. Graph visualization and subject switch: 60 seconds.
3. Chat with KG expansion and citations: 90 seconds.
4. Adaptive quiz and recommendations: 90 seconds.
5. Evaluation/hardening summary: 45 seconds.

## Fallbacks

If Neo4j fails:

- Show API docs, README, architecture, and eval harness.
- Explain graph-dependent flows are intentionally unavailable when readiness is
  unhealthy.

If OpenSearch fails:

- Show graph and architecture.
- Explain retrieval-dependent flows require the vector/lexical index.

If LLM fails:

- Switch `LLM_MODE=hybrid` with an OpenRouter key or show mocked API contracts
  and evaluator design.

If frontend fails:

- Demo with `curl` against `/api/v1/ask`, `/graph/stats`, and `/health/ready`.

## Claims To Avoid

- Do not say production-ready.
- Do not say full IRT is implemented.
- Do not say teacher mode is implemented unless showing actual graph editing.
- Do not say CI proves deployability while browser E2E is manual.
- Do not imply remote LLM calls are privacy-preserving by default.
