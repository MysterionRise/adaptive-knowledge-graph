# Scripted demo

This folder holds the material for a guided, scripted demo of Adaptive
Knowledge Graph: presenter scripts, a readiness gate, slides, a pilot outline
and a case study. None of it is needed for a normal local setup; for that,
follow the [Quickstart](../../README.md#quickstart).

## Demo scope

- **Content:** OpenStax material only (US History and Economics), unless the
  audience provides sample content together with written permission to use it.
- **Learners:** synthetic profiles only. No real student data.
- **Runtime:** the local stack (Neo4j, OpenSearch, Ollama, FastAPI and Next.js)
  on one machine.
- **Evidence:** live readiness checks plus the golden-set evaluation report.
- **Boundaries:** no LMS or LTI integration, no tenant model, no compliance
  certification and no psychometrically calibrated IRT.

## What the demo shows

| Area | Current state |
| --- | --- |
| Grounded tutoring | KG-aware answers with citations, source snippets, expanded concepts and streaming |
| Knowledge graph | Neo4j concepts and modules with prerequisite, related-concept and coverage edges |
| Retrieval | OpenSearch hybrid BM25 + vector retrieval with an optional reranker |
| Local-first LLM | Ollama by default; with `PRIVACY_LOCAL_ONLY=true` remote providers cannot be used |
| Adaptive practice | LLM-generated quizzes, synthetic mastery state, target difficulty and recommendations |
| Demo operations | `/demo-status` page, strict `make demo-client-check`, reset script, Node version pinned in `.node-version` |
| Evaluation | 53 OpenStax golden cases comparing KG-expanded retrieval with plain retrieval |

## Workflow

Install the [prerequisites](../../README.md#1-install-the-prerequisites) and
pull the Ollama model first.

1. Prepare services and seed the OpenStax data. If there is no `.env` yet, this
   creates one from `.env.demo.example`:

   ```bash
   make demo-client-prep
   ```

2. Start the API:

   ```bash
   make run-api
   ```

3. Start the frontend in another terminal:

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

4. Generate the live evaluation report, then run the strict readiness gate:

   ```bash
   make demo-eval
   make demo-client-check
   ```

5. Between rehearsals, reset the synthetic learner state:

   ```bash
   make demo-client-reset
   ```

Pages to have open:

- Frontend: <http://localhost:3000>
- Demo readiness: <http://localhost:3000/demo-status>
- API docs (development mode): <http://localhost:8000/docs>
- Backend readiness: <http://localhost:8000/health/ready>

After `make demo-client-check` passes, capture screenshots and a short
walkthrough with the [asset capture checklist](DEMO_ASSET_CAPTURE.md).

## Evaluation caveat

`docs/evals/latest.json` and `docs/evals/latest.md` only count as evidence after
a live, seeded run succeeds and `environment_valid` is `true`. The demo gate
deliberately fails when the latest report is missing or invalid, or has zero
successful KG or plain cases.

## Documents in this folder

| Document | Use it for |
| --- | --- |
| [CLIENT_DEMO_30MIN.md](CLIENT_DEMO_30MIN.md) | 30-minute presenter script with fallback paths |
| [DEMO_5MIN.md](DEMO_5MIN.md) | 5-minute version of the same demo |
| [DEMO_PLAYBOOK.md](DEMO_PLAYBOOK.md) | Technical walkthrough for engineering audiences |
| [DEMO_PLAN.md](DEMO_PLAN.md) | 15-minute talk with the [slides](../../demo-slides/index.html) and live API calls |
| [DEMO_ASSET_CAPTURE.md](DEMO_ASSET_CAPTURE.md) | Screenshot and recording checklist |
| [CLIENT_LEAVE_BEHIND.md](CLIENT_LEAVE_BEHIND.md) | One-page project brief |
| [CLIENT_PILOT_PROPOSAL.md](CLIENT_PILOT_PROPOSAL.md) | Outline for a 4–6 week pilot |
| [TRUST_AND_PRIVACY.md](TRUST_AND_PRIVACY.md) | Data posture, privacy caveats and claims to avoid |
| [PORTFOLIO_CASE_STUDY.md](PORTFOLIO_CASE_STUDY.md) | Case study: problem, design decisions, evidence and gaps |
