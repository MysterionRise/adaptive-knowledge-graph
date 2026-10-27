# Demo Script: 30 Minutes

Audience: education publishers, institutional leaders and technical
evaluators.

Scope: a local OpenStax demo of a pilot prototype. It is not production
certification infrastructure, and the script says so.

## Before the demo

Run these 30–45 minutes before the session (see [README.md](README.md) for the
full workflow):

```bash
node --version  # should match .node-version (24)
make demo-client-prep
make run-api
cd frontend && npm run dev
```

In another terminal:

```bash
make demo-eval
make demo-client-check
```

After the check passes, capture screenshots and a short recording with the
[asset capture checklist](DEMO_ASSET_CAPTURE.md).

Open:

- `http://localhost:3000`
- `http://localhost:3000/demo-status`
- `http://localhost:3000/chat`
- `http://localhost:3000/graph`
- `http://localhost:3000/assessment`
- `http://localhost:8000/docs`

## Model

The answers come from the language model named in `.env`. Two configurations
are rehearsed:

- **Local (default):** `LLM_MODE=local` and `PRIVACY_LOCAL_ONLY=true`. Ollama
  runs `llama3.1:8b-instruct-q4_K_M` on the laptop and the API refuses any
  remote call.
- **Hosted:** `LLM_MODE=remote`, `PRIVACY_LOCAL_ONLY=false`,
  `OPENROUTER_BASE_URL` pointing at an OpenAI-compatible endpoint, plus
  `OPENROUTER_MODEL` and `OPENROUTER_API_KEY`. Questions and retrieved excerpts
  go to that provider. `/demo-status` names the model that answers, and so
  should you.

Switching is one edit to `.env` and an API restart (about ten seconds).
Retrieval, the graph, the quizzes and the evaluation evidence are the same in
both. The evaluation report itself is always produced in local mode: the gate
requires the local model digest, so run `make demo-eval` before switching.

## Script

### 0–3 min: The problem

Say:

> Education teams do not need another generic chatbot. They need AI over
> approved learning content: traceable citations, inspectable concept
> relationships, adaptive practice, and quality metrics they can review.

Show the home page and `/demo-status`.

### 3–8 min: Architecture

Show [ARCHITECTURE.md](../ARCHITECTURE.md) and the API docs.

Talking points:

- Neo4j models concepts, prerequisites, related ideas and the textbook
  modules that cover them.
- OpenSearch provides hybrid lexical and vector retrieval.
- The language model is a configuration choice: Ollama runs it locally by
  default, and `PRIVACY_LOCAL_ONLY=true` then refuses any remote call. A hosted
  model is one variable away; retrieval, graph and evidence do not change.
- SQLite stores synthetic learner mastery for the demo.
- Evaluation reports separate evidence from claims.

### 8–14 min: Content and citations

Open the **AI Tutor** (`/chat`).

Ask:

```text
What was the Stamp Act and how did it lead to colonial resistance?
```

Then, if time allows, the broader question (it pulls in more tangential
passages, which is a good moment to show the sources):

```text
What caused the American Revolution?
```

Show:

- citations and source snippets
- expanded KG concepts
- model and attribution

Say:

> For anyone who owns content, the important control point is approved source
> material. Each answer can be traced back to licensed text, and the graph
> makes the retrieval path inspectable.

### 14–19 min: The knowledge graph

Open the **Graph** (`/graph`).

Actions:

1. Select US History.
2. Click a high-importance concept.
3. Show connected concepts and relationship types.
4. Explain how prerequisite and related edges support remediation and query
   expansion.

Say:

> The graph is not decoration. It drives query expansion, prerequisite
> explanations and post-assessment recommendations.

### 19–24 min: Adaptive practice

Open **Assessment** (`/assessment`).

Actions:

1. Use `The American Revolution` or `The Constitution`.
2. Generate an adaptive quiz.
3. Answer one question correctly and one incorrectly.
4. Show how mastery and recommendations change.

Say:

> This is not a validated certification engine. It is adaptive-learning
> infrastructure. A real pilot would add reviewed question banks and
> calibration on learner responses before any high-stakes use.

### 24–28 min: Engineering evidence

Show `/demo-status`, `docs/evals/latest.md` and the CI and test summary.

Talking points:

- local-only LLM mode by default, a hosted model by configuration
- readiness checks
- KG versus plain retrieval evaluation: quote the per-arm rates with the
  paired win, tie and loss counts from `docs/evals/latest.md`, not a headline
  difference. When the sign test does not support a difference (as on the
  October 2026 run), say so: the harness exists to show exactly that
- refusal rate on unsupported questions
- clear limitations

### 28–30 min: Pilot options

Describe what a constrained pilot would look like (see the
[pilot outline](CLIENT_PILOT_PROPOSAL.md)):

- one course or module
- approved content only
- synthetic or consented users
- human review of generated questions
- success metrics: citation hit rate, learner satisfaction, author review
  effort and remediation quality

## Fallbacks

- **Neo4j unavailable:** show the architecture, API docs and evaluation design.
- **OpenSearch unavailable:** show the graph and explain the retrieval
  dependency.
- **Hosted model unavailable:** set `LLM_MODE=local` and
  `PRIVACY_LOCAL_ONLY=true` in `.env`, restart the API and continue with the
  local model. Say so.
- **Ollama unavailable (local mode):** show `/demo-status`, the docs and the
  API contracts. Switch to a hosted model only if the audience accepts that
  questions and excerpts leave the machine, and say which model answers.
- **Frontend unavailable:** use `/docs` and the `curl` examples in the
  [technical playbook](DEMO_PLAYBOOK.md).

## Claims to avoid

- Production-ready
- Any regulatory compliance or certification (FERPA, COPPA, GDPR). Say
  instead: "designed so learner data stays on the machine; no compliance
  certification" (see [COMPLIANCE.md](../COMPLIANCE.md))
- Psychometrically validated
- Certification-grade
- Hallucination-free
- Ready to integrate with an existing content platform without a discovery
  phase
