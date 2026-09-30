# Client Demo Script: 30 Minutes

Audience: publisher executives, institutional leaders, and technical buyers.

Positioning: controlled local OpenStax demo and pilot prototype. Do not present
this as production certification infrastructure.

## Pre-Demo

Run 30-45 minutes before the meeting:

```bash
node --version  # should be v20.x
make demo-client-prep
make run-api
cd frontend && npm run dev
```

In another terminal:

```bash
make demo-eval
make demo-client-check
```

After the check passes, capture screenshots and a short recording using
`docs/DEMO_ASSET_CAPTURE.md`.

Open:

- `http://localhost:3000`
- `http://localhost:3000/demo-status`
- `http://localhost:3000/chat`
- `http://localhost:3000/graph`
- `http://localhost:3000/assessment`
- `http://localhost:8000/docs`

## Script

### 0-3 min: Buyer Problem

Say:

> Publishers and institutions do not need another generic chatbot. They need AI
> over approved learning content: traceable citations, inspectable concept
> relationships, adaptive practice, and quality metrics they can review.

Show the home page and `/demo-status`.

### 3-8 min: Architecture

Show `docs/ARCHITECTURE.md` and API docs.

Talking points:

- Neo4j models concepts, prerequisites, related ideas, and chunk windows.
- OpenSearch provides hybrid lexical and vector retrieval.
- Ollama keeps the main demo local-only.
- SQLite stores synthetic learner mastery for the demo.
- Eval reports separate evidence from marketing claims.

### 8-14 min: Publisher Track

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- citations and source snippets
- expanded KG concepts
- model and attribution

Say:

> For a publisher, the important control point is approved source content. The
> answer can be traced back to licensed material, and the graph makes the
> retrieval path inspectable.

### 14-19 min: Knowledge Graph Differentiator

Open `/graph`.

Actions:

1. Select US History.
2. Click a high-importance concept.
3. Show connected concepts and relationship types.
4. Explain how prerequisite and related edges support remediation and query expansion.

Say:

> The graph is not a visualization garnish. It supports query expansion,
> prerequisite explanation, and post-assessment recommendations.

### 19-24 min: Institution Track

Open `/assessment`.

Actions:

1. Use `The American Revolution` or `The Constitution`.
2. Generate an adaptive quiz.
3. Answer one question correctly and one incorrectly.
4. Show mastery and recommendation changes.

Say:

> This is not a validated certification engine. It is adaptive-learning
> infrastructure. A real pilot would add reviewed question banks and learner
> response calibration before high-stakes use.

### 24-28 min: Technical Track

Show `/demo-status`, `docs/evals/latest.md`, and CI/test summary.

Talking points:

- local-only LLM mode
- readiness checks
- KG vs plain retrieval eval
- unsupported-question refusal metric
- clear limitations

### 28-30 min: Pilot Close

Offer a constrained pilot:

- one course or module
- approved content only
- synthetic or consented users
- human review of generated questions
- success metrics: citation hit rate, learner satisfaction, author-review effort, and remediation quality

## Fallbacks

- Neo4j unavailable: show architecture, API docs, and eval design.
- OpenSearch unavailable: show graph and explain retrieval dependency.
- Ollama unavailable: show `/demo-status`, cached docs, and API contracts; do not switch to remote mode for this client demo unless explicitly approved.
- Frontend unavailable: use `/docs` and `curl` examples from `docs/DEMO_PLAYBOOK.md`.

## Claims To Avoid

- Production-ready
- FERPA/COPPA/GDPR compliant
- Psychometrically validated
- Certification-grade
- Hallucination-free
- Pearson integration-ready without a pilot discovery phase
