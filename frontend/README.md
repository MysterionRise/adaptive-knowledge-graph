# Adaptive Knowledge Graph Frontend

The Next.js (App Router) interface for Adaptive Knowledge Graph: KG-RAG chat
with citations, graph exploration, a KG-versus-plain comparison, adaptive
assessment over synthetic learner state, and a demo readiness page.

## Prerequisites

- Node.js 24 LTS, pinned in the repository's [`.node-version`](../.node-version).
  `package.json` accepts Node `^22.13.0 || >=24`, and `npm ci` enforces that
  range (`engine-strict=true` in `.npmrc`), so an unsupported Node version
  fails early.
- npm
- The FastAPI backend running on `http://localhost:8000`. See the
  [README quickstart](../README.md#quickstart).

## Quick start

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>.

## Environment

No environment file is needed for local development. To change the defaults,
copy `.env.example` to `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000

# Optional. Sent as X-API-Key when the backend has API_KEY set.
NEXT_PUBLIC_API_KEY=
```

Next.js compiles every `NEXT_PUBLIC_*` value into the JavaScript bundle, so
anyone who can load the app can read `NEXT_PUBLIC_API_KEY`. It is a convenience
for local and demo setups, not a secret; see [SECURITY.md](../SECURITY.md).
Restart the dev server after changing environment variables.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Home page with the graph summary |
| `/chat` | KG-aware tutor with citations and expanded concepts |
| `/graph` | Cytoscape.js knowledge graph explorer |
| `/comparison` | KG-expanded retrieval versus plain retrieval |
| `/assessment` | Adaptive quiz and mastery workflow |
| `/demo-status` | Readiness of services, seeded data and the latest evaluation |
| `/about` | Project overview and attribution |

## Key UI surfaces

- **Chat** streams answers and shows citations, source scores, expanded
  concepts and a KG expansion toggle.
- **Graph** colours edges by relationship type (`PREREQ`, `RELATED` and
  `COVERS`) and sizes nodes by importance.
- **Assessment** generates topic-based questions, updates synthetic mastery
  and requests recommendations. Those endpoints need `NEXT_PUBLIC_API_KEY` when
  the backend has an API key.
- **Demo status** calls `GET /api/v1/demo/status` and reports Neo4j,
  OpenSearch, Ollama, subject data and the validity of the latest evaluation.

## Scripts

```bash
npm run dev               # development server
npm run build             # production build
npm run start             # serve the production build
npm run lint              # ESLint (eslint .)
npm run type-check        # TypeScript checks (tsc --noEmit)
npm test                  # Jest unit tests
npm run test:coverage     # Jest with coverage
npm run test:e2e          # Playwright end-to-end tests (Chromium, API stubbed, no backend needed)
npm run test:integration  # Playwright tests against a live, seeded stack
```

`npm run test:e2e` builds and starts the app itself (or reuses a server that is
already running outside CI) on port 3000; set `E2E_PORT` to use another port.

The checks CI runs:

```bash
npm run lint
npm run type-check
npm test -- --ci
npm run build
```

## Project structure

```text
frontend/
├── app/            # routes: page.tsx, chat/, graph/, comparison/, assessment/, demo-status/, about/
├── components/     # KnowledgeGraph, Quiz, LearningPath, SubjectPicker, ...
├── lib/
│   ├── api-client.ts
│   ├── store.ts
│   └── types.ts
├── tests/
│   ├── unit/         # Jest + React Testing Library
│   ├── integration/  # Playwright against live services
│   └── e2e/          # Playwright with a stubbed API
└── types/          # type declarations for Cytoscape plugins
```

## Backend contract

The app needs a running backend. It does not fall back to mock data; unit tests
mock the API client explicitly. Useful endpoints:

- `GET /health/ready`
- `GET /api/v1/demo/status`
- `GET /api/v1/subjects`
- `GET /api/v1/graph/stats` and `GET /api/v1/graph/data`
- `POST /api/v1/ask` and `POST /api/v1/ask/stream`
- `POST /api/v1/quiz/generate` and `POST /api/v1/quiz/generate-adaptive`
- `GET /api/v1/student/profile`

## Troubleshooting

- **The app cannot reach the API.** Check `curl http://localhost:8000/health`,
  then `NEXT_PUBLIC_API_URL` in `.env.local`, and restart the dev server.
- **Student or recommendation calls return 401.** The backend has `API_KEY`
  set; put the same value in `NEXT_PUBLIC_API_KEY`.
- **The graph is empty.** The data is not seeded. Run `make seed` in the
  repository root.
- **`npm ci` fails with an engine error.** Switch to the Node version in
  `.node-version`.
