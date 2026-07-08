# Portfolio Case Study: Adaptive Knowledge Graph

## Problem

Publishers and institutions do not need another generic chatbot over course
material. They need AI experiences over approved learning content: answers that
cite licensed sources, concept relationships that authors can inspect, adaptive
practice that educators can review, and quality metrics that technical teams can
regress.

This project demonstrates that shape as a controlled local OpenStax demo:
KG-aware RAG plus adaptive assessment over open textbook content. It is a
client-demo and pilot prototype, not production certification infrastructure.

## Product Thesis

For adult retraining and certification prep, a useful AI learning system needs:

- grounded answers with citations
- concept relationships, not just vector similarity
- adaptive practice based on mastery
- local-first deployment options for privacy
- measurable retrieval and answer quality
- human-review paths before high-stakes assessment use

## Architecture

```text
Next.js UX -> FastAPI orchestration -> Neo4j + OpenSearch + LLM -> SQLite mastery store
```

Key capabilities:

- KG expansion before retrieval
- hybrid BM25 + vector search
- streaming answers
- multi-subject configuration
- graph visualization
- LLM-generated quizzes
- BKT-inspired mastery updates
- golden-set RAG evaluation harness

## Hard Decisions

### Neo4j instead of only vectors

Vectors retrieve similarity; the graph models prerequisite and related-concept
structure. This makes learning paths and remediation explainable.

### OpenSearch instead of a small local vector library

The project uses OpenSearch because BM25 + dense retrieval is the more
production-relevant shape, even though it adds operational weight.

### Local-first LLM support

Education data has privacy constraints. Ollama mode shows that the architecture
can run locally, while OpenRouter fallback is available for demo reliability.

### Honest adaptive learning

The system implements practical mastery updates and BKT-style probability
updates. It does not claim calibrated IRT without learner response data.

## Evidence

Implemented:

- FastAPI service with OpenAPI docs
- Next.js UI with graph/chat/assessment workflows
- Neo4j graph adapter and schema
- OpenSearch hybrid retriever
- LLM client with local, remote, and hybrid modes
- SQLite student profile persistence
- request IDs and response-time headers
- API-key protection for sensitive endpoints when configured
- golden-set evaluator for KG vs plain retrieval
- client demo status dashboard
- local-only OpenStax client demo scripts

Current validation commands:

```bash
make demo-client-prep
make demo-eval
make demo-client-check
make test-fast
cd frontend && npm run type-check
cd frontend && npm test -- --ci --runInBand --forceExit
```

## Known Gaps

- no full identity or tenant model
- no calibrated psychometric question bank
- no production deployment manifests
- browser E2E is manual until a demo backend exists in CI
- graph/search clients still use synchronous calls in async routes
- evaluation metrics are heuristic and need human review before production use
- no LMS/LTI integration yet

## Next 30/60/90 Days

30 days:

- keep golden QA set at 50+ cases and add client-specific cases per pilot
- require eval report in PRs touching retrieval/prompting
- finish CI split between unit, tribunal, and browser suites
- capture client-demo screenshots and a short local walkthrough recording

60 days:

- add tenant-aware auth model
- add OpenTelemetry spans for graph, retrieval, reranking, and LLM calls
- move blocking graph/search calls behind executors or async clients

90 days:

- provision staging environment for automated E2E
- add assessment attempt ledger and question bank
- add deployment runbook with backups and disaster recovery notes
