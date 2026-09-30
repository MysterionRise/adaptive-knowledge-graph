# Architecture

Adaptive Knowledge Graph is a knowledge-graph-enhanced RAG prototype for
learning over open textbooks. This document explains how requests flow through
the system, how subjects are isolated, what the security model is and which
trade-offs were made. For setup, see the [README](../README.md).

## System shape

```text
Browser / Next.js
  - graph explorer (Cytoscape.js)
  - chat with SSE streaming
  - KG-RAG vs plain RAG comparison
  - adaptive quiz, mastery and recommendations
  - demo readiness page

FastAPI (all routes under /api/v1 except health)
  - /ask and /ask/stream
  - /quiz/* and /student/*
  - /graph/*, /concepts/* and /learning-path/*
  - /subjects/*
  - /demo/status
  - /health, /health/ready and /health/live

Data and model services
  - Neo4j: concepts and modules with PREREQ, RELATED and COVERS
    relationships; chunk nodes linked by NEXT only when window retrieval
    is set up
  - OpenSearch: BM25 + vector retrieval over textbook chunks
  - Ollama (default) or OpenRouter (opt-in): answers, quizzes, graph queries
  - SQLite: learner mastery profiles
```

## Request flow

### KG-RAG answer

Both `POST /api/v1/ask` and `POST /api/v1/ask/stream` use the same retrieval
helper, so blocking and streaming answers cannot drift apart.

1. Validate the question, subject, `top_k` and retrieval options. Invalid
   input, including questions with HTML markup, returns `422` without echoing
   the input.
2. Resolve the subject from `config/subjects.yaml`, falling back to
   `default_subject` when none is given. An unknown subject returns `404`.
3. Extract concepts from the question (spaCy NER and YAKE) and expand them with
   their Neo4j neighbours, up to `RAG_KG_EXPANSION_HOPS`. If Neo4j fails, the
   request continues without expansion.
4. Retrieve chunks from the subject's OpenSearch index. The default
   `RETRIEVAL_MODE=hybrid` runs BM25 and kNN queries and fuses them with
   reciprocal rank fusion; `knn` uses vectors only.
5. Optionally add window context: neighbouring chunks reached through `NEXT`
   relationships in Neo4j (see below).
6. Optionally rerank the candidates with the cross-encoder
   (`RERANKER_ENABLED=true`). The retriever then fetches
   `RAG_RETRIEVAL_TOP_K` candidates and the reranker keeps `top_k`. If
   reranking fails, the original order is used.
7. Generate the answer with a subject-specific prompt that restricts the model
   to the retrieved context and asks for numbered citations.
8. Return the answer, sources with scores, expanded concepts, model,
   attribution and counts. On `/ask`, an unreachable LLM returns `503` and an
   empty or invalid LLM answer returns `502`. `/ask/stream` returns `503` only
   when the LLM is unreachable before streaming starts; a later failure or an
   empty answer is sent as an SSE `error` event.

#### Window retrieval is opt-in

Window retrieval adds the chunks before and after each hit to give the model
more context. It only runs when all of these hold:

- `VECTOR_BACKEND` is `neo4j` or `hybrid` (the default, `opensearch`, skips
  it),
- `RAG_WINDOW_RETRIEVAL` is `true` and the request does not turn off
  `use_window_retrieval`,
- the chunks exist in Neo4j with `NEXT` relationships between them. The
  standard seeding does not create these; after seeding, run
  `make build-windows SUBJECT=<id>` for each subject (without `SUBJECT` it
  builds only the default subject).

The request's `window_size` (default 1, from 0 to 3) sets how many neighbours
are added on each side. `RAG_WINDOW_SIZE` is only the default for callers that
do not pass a size; the Q&A endpoints always pass one.

### Adaptive assessment

1. Validate the topic (HTML markup is rejected with `422`) and retrieve content
   for it; a topic with no content returns `404`.
2. Ask the LLM for multiple-choice questions with difficulty labels and
   explanations at the learner's target difficulty (easy below 0.4 mastery,
   medium up to 0.7, hard above).
3. After each answer, update the concept's mastery. With
   `STUDENT_BKT_ENABLED=true` (the default) this is a four-parameter Bayesian
   Knowledge Tracing update with fixed parameters; otherwise a simple linear
   update.
4. Recommend prerequisites to review for weak concepts and further topics for
   strong ones.

This is an adaptive-practice prototype, not a validated assessment engine.
Question difficulty is estimated by the LLM, and the BKT parameters are not
fitted to learner data. There is no item response theory (IRT) model, and
quizzes are graded in the browser
([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).

## Data boundaries

Subjects are isolated by configuration:

- Neo4j labels carry a subject prefix, such as `us_history_Concept`.
- Each subject has its own OpenSearch index.
- Prompts, theme colours, attribution and books are defined per subject.
- Requests without a subject use `default_subject` from the same file.
- `GET /api/v1/subjects` marks each subject `available` only when its
  knowledge graph has data, so the UI can disable configured but unseeded
  subjects.

This works on Neo4j Community Edition, which has a single database. A
multi-tenant deployment would need tenant IDs, per-learner identity
([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73))
and stronger isolation.

## Security model

The default `APP_ENV=development` is meant for one developer machine: it runs
without an API key and logs a warning at startup. `APP_ENV=production` refuses
to start without `API_KEY` or with `*` in any CORS allow-list
(`CORS_ORIGINS`, `CORS_ALLOW_METHODS`, `CORS_ALLOW_HEADERS`), and disables
`/docs`, `/redoc` and `/openapi.json` unless `API_DOCS_ENABLED=true`. The
protected routes (`/student/*`, `/quiz/generate-adaptive`, `/quiz/recommendations` and
`/graph/query`)
require the `X-API-Key` header whenever a key is configured.

`PRIVACY_LOCAL_ONLY=true` (the default) makes the API refuse to start unless
`LLM_MODE=local`, so no prompt can reach a remote provider.

Other hardening in place:

- The local Compose stack binds service ports to `127.0.0.1`.
- `/health/ready` returns `503` when Neo4j or OpenSearch is unavailable.
- Error details stay in the logs: `/health/ready` reports fixed per-service
  messages such as "Neo4j unavailable", other errors are redacted before they
  are returned, and validation errors do not echo the request input.
- TLS verification for external calls is on by default; the local OpenSearch
  uses plain HTTP instead of pretending to use TLS.
- Container images are pinned to specific versions.
- `RATE_LIMIT_DEFAULT` (100 requests per minute by default) applies per
  client and endpoint to every route, counted before authentication. The
  health checks are exempt, so probes never get `429`. Stricter limits
  (`RATE_LIMIT_*` settings) cover Q&A, quiz generation, graph reads,
  `/graph/query`, learner-profile writes and `/quiz/recommendations`.
- `X-Forwarded-For` is ignored for rate limiting unless
  `TRUST_PROXY_HEADERS=true`; then the right-most hop, the one the trusted
  proxy appended, identifies the client.

Known gaps: no per-learner identity or tenant-aware authorization, no
audit-grade assessment records and no production secret management. Every
`NEXT_PUBLIC_*` value, including `NEXT_PUBLIC_API_KEY`, is visible in the
browser bundle. [SECURITY.md](../SECURITY.md) has the threat model and a
hardening checklist.

## Observability

Every request gets an `X-Request-ID` (taken from the request header when
present). The middleware logs the method, path, status code and elapsed
milliseconds, and returns `X-Response-Time-ms`.

The next step would be structured tracing across graph expansion, retrieval,
reranking, LLM generation and learner-model updates.

## Evaluation

`scripts/evaluate_rag.py` runs the 53-question golden set in
`data/evals/golden_qa.yaml` against a live API, once with KG expansion and
once without, and tracks:

- answer term recall
- citation hit rate and expected-source MRR
- refusal of questions the book cannot support
- KG-versus-plain deltas
- latency, expanded concepts and approximate answer length

`make demo-eval` runs it and validates the report. The metrics are heuristic;
see [evals/README.md](evals/README.md).

## Key trade-offs

### Neo4j

Prerequisite traversal, concept neighbourhoods and learning paths are
graph-native queries. The cost is operational weight and the care needed to run
generated Cypher safely.

### OpenSearch

The project needs lexical BM25 and dense retrieval in one service. For a very
small corpus, SQLite FTS or an embedded vector store would be simpler, but
would not provide hybrid retrieval in one place.

### Local-first LLMs

Education data is sensitive, so the default keeps inference on the local
machine. The cost is hardware and cold-start latency. Remote providers are
available only after explicitly turning off `PRIVACY_LOCAL_ONLY`.

### Next.js frontend

Graph interaction, streaming chat and repeated learning workflows need a real
frontend rather than a notebook-style UI. The cost is a larger build and test
surface.

## Production gap list

- Per-learner identity, roles and tenant-aware access control
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
- Server-side quiz grading and an answer-submission endpoint
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).
- Async Neo4j and OpenSearch clients and a proper application lifecycle
  ([#78](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/78)).
- Tracing for retrieval and generation.
- A persistent, reviewed question bank and an assessment attempt ledger.
- Database migrations and backups.
- Larger, human-reviewed evaluation with deltas checked in CI.
- A staging environment for automated browser tests.
