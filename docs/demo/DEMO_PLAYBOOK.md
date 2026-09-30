# Technical Demo Playbook

Use this for CTO, VP Engineering, AI platform lead, or technical-founder
walkthroughs. For the default client conversation, use
`docs/CLIENT_DEMO_30MIN.md`.

Goal: show a credible KG-RAG learning platform prototype and the engineering
judgment behind it. Do not present it as production-ready certification
infrastructure.

## Pre-Demo Checklist

Run before rehearsal:

```bash
make demo-client-prep
make run-api
```

In another terminal:

```bash
cd frontend
npm run dev
```

Then generate live evidence and run the strict gate:

```bash
make demo-eval
make demo-client-check
```

Open:

- `http://localhost:3000`
- `http://localhost:3000/demo-status`
- `http://localhost:3000/graph`
- `http://localhost:3000/chat`
- `http://localhost:3000/comparison`
- `http://localhost:3000/assessment`
- `http://localhost:8000/docs`

## 30-Minute Technical Flow

### 0-3 min: Positioning

Say:

> This is a controlled local OpenStax KG-RAG prototype for education clients.
> The signal is architecture judgment: graph-aware retrieval, local-first LLMs,
> streaming UX, adaptive practice, live readiness checks, and honest production
> boundaries.

Show:

- `README.md`
- `/demo-status`
- `docs/ARCHITECTURE.md`

### 3-8 min: Architecture

Talking points:

- FastAPI coordinates RAG, graph, quiz, and student profile workflows.
- Neo4j stores concepts, modules, chunks, prerequisites, and related concepts.
- OpenSearch provides hybrid BM25 + vector retrieval.
- Ollama is the local-first inference path for the main client demo.
- SQLite stores synthetic learner mastery state.
- `/health/ready` and `/api/v1/demo/status` separate service health from demo
  readiness.

### 8-13 min: Graph

Open `/graph`.

Actions:

1. Select US History.
2. Show concept and relationship counts.
3. Click a high-importance node.
4. Explain prerequisite and related-concept relationships.

Framing:

> The graph is not decoration. It supports query expansion, learning-path
> explanation, and remediation/advancement recommendations.

### 13-18 min: KG-RAG Chat

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- streaming tokens
- KG expansion on/off
- expanded concepts
- citations and scores

Framing:

> KG-RAG is not claimed to win every query. The important engineering point is
> that retrieval behavior is inspectable and evaluated against plain retrieval.

### 18-23 min: Adaptive Assessment

Open `/assessment`.

Actions:

1. Use `The American Revolution` or `The Constitution`.
2. Generate an adaptive quiz.
3. Answer one item.
4. Show mastery and recommendation changes.

Say:

> This is adaptive-learning infrastructure. It is not a validated psychometric
> exam or certification engine.

### 23-26 min: Evaluation

Show:

- `docs/evals/latest.md`
- `data/evals/golden_qa.yaml`
- `scripts/evaluate_rag.py`
- `scripts/check_demo_eval.py`

Explain:

- answer term recall
- citation hit rate
- expected-source MRR
- unsupported refusal rate
- KG vs plain retrieval deltas
- latency
- known heuristic limits

### 26-30 min: Hardening Roadmap

Show known gaps:

- identity and tenant isolation
- async graph/search clients
- OpenTelemetry traces
- reviewed question bank
- assessment attempt ledger
- LMS/LTI integration
- production deployment controls

Close with:

> A pilot should constrain scope to one content slice, approved source material,
> synthetic or consented users, human review, and agreed success metrics.

## 5-Minute Variant

Use `docs/DEMO_5MIN.md`.

## Fallbacks

- Neo4j unavailable: show architecture, API docs, and eval harness.
- OpenSearch unavailable: show graph and explain retrieval dependency.
- Ollama unavailable: show `/demo-status`, API contracts, and docs; do not use
  remote mode unless the audience has explicitly approved it.
- Frontend unavailable: demo with `/docs` and curl requests against
  `/api/v1/ask`, `/api/v1/graph/stats`, and `/health/ready`.

## Claims To Avoid

- Production-ready.
- FERPA/COPPA/GDPR compliant.
- Certification-grade.
- Full IRT or psychometric validation.
- Teacher authoring workflow unless that UI is implemented.
- Remote LLM calls as privacy-preserving by default.
