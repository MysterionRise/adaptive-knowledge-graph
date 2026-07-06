# Evaluation Notes

This directory stores lightweight KG-RAG evaluation reports for portfolio and
regression tracking.

Run the evaluator against a live backend:

```bash
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
```

The harness compares KG-expanded retrieval with plain retrieval for the golden
set in `data/evals/golden_qa.yaml`.

Tracked signals:

- answer term recall against expected concepts
- citation hit rate against expected source/module hints
- MRR for expected source rank
- KG-vs-plain deltas for recall, citation hit rate, MRR, and latency
- failure counts for each retrieval mode
- KG expansion concepts
- latency and approximate answer token count

Reports include an `environment_valid` flag. A report generated without a live
seeded backend is useful for checking harness behavior, but it is not portfolio
quality evidence until successful KG and plain runs are present.

This is not a replacement for a large external benchmark. It is a compact
smoke/regression suite that demonstrates AI engineering discipline and gives a
place to add deeper RAGAS or human-reviewed evaluation later.
