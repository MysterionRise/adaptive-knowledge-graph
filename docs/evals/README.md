# Evaluation

This directory holds the latest KG-RAG evaluation report, used for regression
tracking. The harness compares knowledge-graph-expanded retrieval with plain
retrieval on the golden set in
[`data/evals/golden_qa.yaml`](../../data/evals/golden_qa.yaml): 53 questions,
27 for US History and 26 for Economics.

## Running it

Start the stack, seed it and run the API first (see the
[README quickstart](../../README.md#quickstart)). Then:

```bash
make demo-eval
```

This runs `scripts/evaluate_rag.py` against `http://localhost:8000` and then
`scripts/check_demo_eval.py`, which fails when the report is missing or
invalid, or has zero successful KG or plain cases. To run the steps
separately:

```bash
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
poetry run python scripts/check_demo_eval.py
```

Each question is asked twice, with and without KG expansion. The results are
written to `latest.json` and `latest.md` in this directory.

## What is measured

- **Answer term recall:** the share of expected terms that appear in the answer.
- **Citation hit rate:** whether an expected source section appears among the
  returned sources.
- **Expected-source MRR:** how high the first expected source ranks.
- **Unsupported refusal rate:** for questions tagged `unsupported_claim`,
  whether the answer declines instead of asserting the claim.
- **KG-versus-plain deltas** for each of the above, plus latency.
- Failure counts per mode, expanded concepts and approximate answer length.

The golden set also includes cross-chapter synthesis, ambiguous,
conflicting-source and prompt-injection questions; its `tags` field says which
is which.

## Reading a report

Every report carries an `environment_valid` flag. A report produced without a
live, seeded backend is useful for checking the harness itself, but it is not
evidence of retrieval quality. Only reports with `environment_valid: true` and
non-zero successful case counts count.

## Limitations

The metrics are heuristic: they match keywords and source titles. They show
whether a change helped or hurt this set of questions, not whether the answers
are correct in general, and they do not replace a large external benchmark or
human review. More rigorous evaluation (for example RAGAS or reviewed answer
grading) can build on this harness.
