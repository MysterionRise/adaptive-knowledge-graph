# Adaptive Knowledge Graph

Controlled client-demo and AI engineering portfolio prototype for grounded,
adaptive learning over approved course content.

The project combines a knowledge graph, hybrid retrieval, local-first LLM
inference, citations, adaptive practice, and live evaluation checks. It is built
to support a 30-minute education-client demo using OpenStax content and
synthetic learner data.

Position this as a **controlled local demo and pilot prototype**, not as a
production certification platform.

## Demo Scope

- Content: OpenStax demo material only unless a client provides approved sample
  content under written permission.
- Learners: synthetic profiles only; no real student PII in the demo.
- Runtime: local laptop stack with Neo4j, OpenSearch, Ollama, FastAPI, and
  Next.js.
- Evidence: live readiness checks plus a golden-set KG-RAG evaluation report.
- Boundaries: no LMS/LTI integration, no tenant model, no production compliance
  certification, and no psychometrically calibrated IRT.

## What It Demonstrates

| Area | Current state |
| --- | --- |
| Grounded tutoring | KG-aware RAG answers with citations, source snippets, expanded concepts, and streaming support |
| Knowledge graph | Neo4j concept/module/chunk schema with prerequisite and related-concept edges |
| Retrieval | OpenSearch hybrid BM25 + vector retrieval with optional reranking |
| Local-first LLM | Ollama local mode by default; remote fallback exists but is not the main client-demo posture |
| Adaptive practice | LLM-generated quizzes, synthetic mastery state, target difficulty, and recommendations |
| Demo operations | `/demo-status`, strict `make demo-client-check`, reset scripts, and Node 20 pinning |
| Evaluation | 50+ OpenStax golden cases comparing KG-expanded retrieval with plain retrieval |

## Architecture

```text
Next.js UI
  -> FastAPI API
      -> Neo4j knowledge graph
      -> OpenSearch hybrid retrieval
      -> Ollama local LLM
      -> SQLite synthetic learner profile
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for implementation tradeoffs
and production gaps.

## Client Demo Workflow

Prerequisites:

- Python 3.11-3.13
- Poetry
- Docker and Docker Compose
- Node.js 20
- Ollama with the configured local model

Prepare local services and seed OpenStax demo data:

```bash
make demo-client-prep
```

Start the API:

```bash
make run-api
```

Start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

Generate the live evaluation report, then run the strict rehearsal gate:

```bash
make demo-eval
make demo-client-check
```

Open:

- Frontend: `http://localhost:3000`
- Demo readiness: `http://localhost:3000/demo-status`
- API docs: `http://localhost:8000/docs`
- Backend readiness: `http://localhost:8000/health/ready`

After `make demo-client-check` passes, capture screenshots and a short local
walkthrough using [docs/DEMO_ASSET_CAPTURE.md](docs/DEMO_ASSET_CAPTURE.md).

## Important Eval Caveat

`docs/evals/latest.json` and `docs/evals/latest.md` are only demo-quality
evidence after a live seeded run succeeds and `environment_valid` is `true`.
The demo gate intentionally fails when the latest report is missing, invalid, or
has zero successful KG/plain cases.

## Documentation Map

- [docs/CLIENT_DEMO_30MIN.md](docs/CLIENT_DEMO_30MIN.md): primary client demo
  script and fallback paths.
- [docs/CLIENT_PILOT_PROPOSAL.md](docs/CLIENT_PILOT_PROPOSAL.md): 4-6 week
  pilot shape, success metrics, and responsibilities.
- [docs/TRUST_AND_PRIVACY.md](docs/TRUST_AND_PRIVACY.md): local-only posture,
  PII boundaries, and compliance caveats.
- [docs/CLIENT_LEAVE_BEHIND.md](docs/CLIENT_LEAVE_BEHIND.md): one-page client
  brief with architecture snapshot.
- [docs/PORTFOLIO_CASE_STUDY.md](docs/PORTFOLIO_CASE_STUDY.md): AI engineering
  portfolio narrative and roadmap.
- [docs/evals/README.md](docs/evals/README.md): evaluation harness notes.

## Development Commands

Install dependencies:

```bash
poetry install --without pyirt,pybkt
cd frontend
npm ci
```

Run backend checks:

```bash
make lint
make type-check
make test
```

Run frontend checks:

```bash
cd frontend
npm run type-check
npm test -- --ci --runInBand --forceExit
```

The frontend Jest suite currently needs `--forceExit` because existing tests
leave asynchronous handles open after reporting all suites complete.

## Security And Privacy Posture

- `API_KEY` is empty by default for local development.
- When `API_KEY` is configured, protected endpoints require `X-API-Key`.
- The frontend can send that header via `NEXT_PUBLIC_API_KEY`.
- `/health/ready` returns 503 when critical dependencies are unavailable.
- Demo-status responses avoid secrets, local paths, and raw exception details.
- OpenRouter support exists, but the client demo should stay local-only unless
  a client explicitly approves remote calls.

## Known Gaps

- No full identity, role, or tenant model.
- No LMS/LTI integration.
- No production deployment manifests or SOC2-style controls.
- No calibrated psychometric question bank.
- Browser E2E is manual until a live demo backend is provisioned in CI.
- Evaluation metrics are heuristic and require human review before production
  use.

## License And Attribution

Project code is MIT licensed. OpenStax content is CC BY 4.0 and is attributed in
API responses, docs, and UI flows. This project is not affiliated with or
endorsed by OpenStax or Rice University.
