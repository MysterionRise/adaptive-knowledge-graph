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

The evaluator paces its requests to the `/api/v1/ask` rate limit
(`RATE_LIMIT_ASK`, 10 per minute by default, so one request every 6.25
seconds) and retries `429` responses. A full run of 106 requests therefore
takes about 11 minutes. Useful options:

| Option | Effect |
| --- | --- |
| `--subject us_history` | Only cases for that subject (repeatable or comma-separated) |
| `--limit 3` | At most N cases |
| `--delay 2` | Minimum seconds between requests, overriding the pacing |
| `--max-retries 5` | Retries per request after `429` |

With Make, pass them through `EVAL_ARGS`:

```bash
make eval-rag EVAL_ARGS="--subject economics --limit 3"
```

`check_demo_eval.py` rejects partial reports (for example from `--limit`)
unless you pass `--allow-partial`.

## What is measured

- **Answer term recall:** the share of expected terms that appear in the answer.
- **Citation hit rate:** whether a returned source is one of the case's
  `expected_sources`.
- **Expected-source MRR:** how high the first expected source ranks.
- **Unsupported refusal rate:** for questions tagged `unsupported_claim`,
  whether the answer declines instead of asserting the claim.
- **KG-versus-plain deltas** for each of the above, plus latency.
- Failure counts per mode, expanded concepts and approximate answer length.

### How sources are matched

Each source returned by `/ask` names a `chapter`, a `section` (the module's
own title) and a `module_title` (`"<chapter> - <section>"`). A source matches
an expected source when one of these three titles equals it, ignoring case,
curly versus straight quotes, en dashes and extra whitespace. The 200-character
text preview is never matched, so a citation counts only when it is the
expected section, not when its text happens to mention the topic.

Every `expected_sources` entry in the golden set is a real title from
`data/processed/books_<subject>.jsonl`, usually a section title, and
`backend/tests/test_citations.py` checks that each one matches between one and
three ingested modules. A chapter title matches all of that chapter's modules,
so it only qualifies for chapters with three modules or fewer; to expect a
chapter's introduction, use its full module title, such as
`"Monopoly - Introduction to a Monopoly"`. After changing the books or the
ingest, regenerate the processed data and re-check the golden set with:

```bash
poetry run pytest backend/tests/test_citations.py
```

Reports from before v0.4.0 matched titles and text previews as substrings and
used looser expected sources, so their citation metrics are not comparable
with current ones.

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
