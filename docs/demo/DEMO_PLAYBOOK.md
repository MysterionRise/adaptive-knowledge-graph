# Technical Demo Playbook

Use this for engineering audiences: engineering leads, AI platform teams and
technical founders. For a general audience, use the
[30-minute script](CLIENT_DEMO_30MIN.md).

Goal: show a working KG-RAG learning prototype and the engineering decisions
behind it. It is not production-ready certification infrastructure, and the
walkthrough says so.

## Before the demo

Run before the rehearsal (see [README.md](README.md)):

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

## 30-minute technical flow

### 0–3 min: What it is

Say:

> This is a local KG-RAG prototype over OpenStax textbooks. The interesting
> parts are graph-aware retrieval, local-first LLMs, streaming UX, adaptive
> practice, live readiness checks and clearly stated production boundaries.

Show:

- the project [README](../../README.md)
- `/demo-status`
- [ARCHITECTURE.md](../ARCHITECTURE.md)

### 3–8 min: Architecture

Talking points:

- FastAPI coordinates the RAG, graph, quiz and learner-profile workflows.
- Neo4j stores concepts and modules with prerequisite, related-concept and
  coverage relationships.
- OpenSearch provides hybrid BM25 + vector retrieval.
- Ollama is the local inference path; `PRIVACY_LOCAL_ONLY=true` makes the API
  refuse any remote LLM mode.
- SQLite stores synthetic learner mastery.
- `/health/ready` and `/api/v1/demo/status` separate service health from demo
  readiness.

### 8–13 min: Graph

Open `/graph`.

Actions:

1. Select US History.
2. Show concept and relationship counts.
3. Click a high-importance node.
4. Explain prerequisite and related-concept relationships.

Framing:

> The graph is not decoration. It drives query expansion, learning-path
> explanations and remediation or advancement recommendations.

### 13–18 min: KG-RAG chat

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- streaming tokens
- KG expansion on and off
- expanded concepts
- citations and scores

Framing:

> KG-RAG is not claimed to win every query. The point is that retrieval
> behaviour is inspectable and evaluated against plain retrieval.

### 18–23 min: Adaptive assessment

Open `/assessment`.

Actions:

1. Use `The American Revolution` or `The Constitution`.
2. Generate an adaptive quiz.
3. Answer one item.
4. Show how mastery and recommendations change.

Say:

> This is adaptive-learning infrastructure. It is not a validated psychometric
> exam or certification engine.

### 23–26 min: Evaluation

Show:

- `docs/evals/latest.md`
- `data/evals/golden_qa.yaml`
- `scripts/evaluate_rag.py`
- `scripts/check_demo_eval.py`

Explain:

- answer term recall
- citation hit rate
- expected-source MRR
- unsupported-question refusal rate
- KG versus plain retrieval deltas
- latency
- the limits of heuristic metrics

### 26–30 min: Hardening roadmap

Show the known gaps (see [ROADMAP.md](../../ROADMAP.md)):

- per-learner identity and tenant isolation
- server-side quiz grading
- async graph and search clients
- OpenTelemetry traces
- a reviewed question bank and an assessment attempt ledger
- LMS or LTI integration
- production deployment controls

Close with:

> A pilot should constrain scope to one content slice, approved source
> material, synthetic or consented users, human review and agreed success
> metrics.

## 5-minute variant

Use the [5-minute script](DEMO_5MIN.md).

## Fallbacks

- **Neo4j unavailable:** show the architecture, API docs and evaluation
  harness.
- **OpenSearch unavailable:** show the graph and explain the retrieval
  dependency.
- **Ollama unavailable:** show `/demo-status`, the API contracts and the docs.
  Do not switch to a remote model unless the audience has explicitly approved
  it.
- **Frontend unavailable:** demo with `/docs` and `curl` requests against
  `/api/v1/ask`, `/api/v1/graph/stats` and `/health/ready`.

## Claims to avoid

- Production-ready.
- FERPA, COPPA or GDPR compliant.
- Certification-grade.
- Full IRT or psychometric validation.
- A teacher authoring workflow (none is implemented).
- Remote LLM calls as privacy-preserving.
