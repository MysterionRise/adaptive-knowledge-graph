# 5-Minute Demo Script

Purpose: show a credible KG-RAG AI platform prototype, not a production
certification product.

## 0:00-0:45 - Positioning

Open `http://localhost:3000`.

Say:

> This is a production-shaped KG-RAG learning prototype. The signal is not a
> chatbot wrapper; it is graph-aware retrieval, citations, streaming UX,
> adaptive assessment, local-first LLM support, and measurable evaluation hooks.

## 0:45-1:45 - Knowledge Graph

Open `/graph`.

Show:

- concept nodes
- relationship highlighting
- subject switcher
- graph statistics

Say:

> The graph drives query expansion and recommendations. It is not just a visual.

## 1:45-3:00 - KG-RAG Chat

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- streaming answer
- expanded concepts
- citations
- source scores

Say:

> The system exposes what it retrieved and why. The evaluator can compare this
> KG-expanded path against plain retrieval.

## 3:00-4:15 - Adaptive Quiz

Open `/assessment`.

Generate a quiz, answer one question, and show:

- explanation
- mastery update
- recommendations

Say:

> This is adaptive practice infrastructure. BKT-style mastery updates are
> implemented; full psychometric calibration is future work.

## 4:15-5:00 - Engineering Evidence

Flash README or terminal:

```bash
make test-fast
cd frontend && npm run type-check
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
```

Say:

> The repo now separates implemented features from roadmap claims, has stricter
> CI boundaries, SQLite-backed local persistence, secure TLS defaults for remote
> LLM calls, and a small golden-set evaluation harness.

## Pre-Demo Commands

```bash
cp .env.demo.example .env
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch
bash scripts/seed_demo.sh
make run-api
cd frontend && npm run dev
```
