# Adaptive Knowledge Graph Frontend

Next.js 14 interface for the Adaptive Knowledge Graph client demo.

The app is designed for a local OpenStax walkthrough: demo readiness, KG-RAG
chat with citations, graph exploration, KG/plain comparison, and adaptive
assessment over synthetic learner state.

## Prerequisites

- Node.js 20
- npm
- FastAPI backend running on `http://localhost:8000`

The repo includes `.node-version` at the project root. Use your Node manager to
select Node 20 before running demo checks.

## Quick Start

```bash
npm ci
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

For the full client demo path, run the root-level commands first:

```bash
make demo-client-prep
make run-api
make demo-eval
make demo-client-check
```

## Environment

```env
NEXT_PUBLIC_API_URL=http://localhost:8000

# Optional. Set to backend API_KEY when protected demo endpoints are enabled.
NEXT_PUBLIC_API_KEY=
```

`NEXT_PUBLIC_API_KEY` is sent as `X-API-Key` by the shared API client, streaming
chat requests, quiz/recommendation requests, and student profile calls.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Client-demo home page and graph summary |
| `/demo-status` | Readiness dashboard for services, seeded data, and latest eval |
| `/chat` | KG-aware tutor with citations and expanded concepts |
| `/graph` | Cytoscape knowledge graph visualization |
| `/comparison` | KG-expanded retrieval vs plain retrieval |
| `/assessment` | Adaptive quiz and mastery workflow |
| `/about` | Project overview |

## Key UI Surfaces

### Demo Status

`/demo-status` calls `GET /api/v1/demo/status` and shows Neo4j, OpenSearch,
Ollama, subject data, latest eval validity, and next actions.

### Chat

The chat view exposes KG expansion, streaming responses, citations, source
scores, and expanded concepts.

### Graph

The graph view uses Cytoscape.js. Relationship coloring includes `PREREQ`,
`RELATED_TO`, and content/module edges returned by the backend.

### Assessment

The assessment flow generates topic-based questions, updates synthetic mastery,
and requests recommendations from protected backend endpoints when API-key
protection is enabled.

## Scripts

```bash
npm run dev          # Start dev server
npm run build        # Build production bundle
npm run start        # Start production server
npm run lint         # Run Next lint
npm run type-check   # Run TypeScript checks
npm test             # Run Jest tests
npm run test:e2e     # Run Playwright tests
```

Current CI-style frontend verification:

```bash
npm run type-check
npm test -- --ci --runInBand --forceExit
```

The Jest suite reports all tests before force-exiting; some existing tests keep
asynchronous handles open after completion.

## Project Structure

```text
frontend/
├── app/
│   ├── page.tsx
│   ├── demo-status/
│   ├── graph/
│   ├── chat/
│   ├── comparison/
│   ├── assessment/
│   └── about/
├── components/
├── lib/
│   ├── api-client.ts
│   ├── store.ts
│   └── types.ts
└── tests/
    ├── unit/
    └── e2e/
```

## Backend Contract

The frontend expects a running FastAPI backend. Unit tests use explicit mocks;
the app itself does not silently switch to mock data for demo-critical flows.

Useful backend endpoints:

- `GET /health/ready`
- `GET /api/v1/demo/status`
- `GET /api/v1/graph/stats`
- `POST /api/v1/ask`
- `POST /api/v1/ask/stream`
- `POST /api/v1/quiz/generate`
- `GET /api/v1/student/profile`

## Troubleshooting

### API client cannot reach the server

1. Confirm backend health: `curl http://localhost:8000/health`.
2. Confirm `NEXT_PUBLIC_API_URL` in `.env.local`.
3. Restart the frontend after changing environment variables.

### Protected student/profile calls fail

If backend `API_KEY` is configured, set the same value in
`NEXT_PUBLIC_API_KEY` for the local demo.

### Graph is empty

Run the root-level setup:

```bash
make demo-client-prep
make demo-client-check
```

### Next.js refuses to start

Check `node --version`. The demo path expects Node 20.
