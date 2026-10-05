# Evaluation

This directory holds the latest KG-RAG evaluation report and, in
[`history/`](history/), snapshots of earlier runs, used for regression
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
`scripts/check_demo_eval.py`, which fails when the report is missing, has no
provenance, is invalid (see [Validity](#validity)) or has zero successful KG or
plain cases. To run the steps separately:

```bash
poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
poetry run python scripts/check_demo_eval.py
```

Each question is asked twice, with and without KG expansion. Only cases whose
subject `/api/v1/subjects` reports as available (seeded) are asked; skipped
subjects make the run partial. The results are written to `latest.json` and
`latest.md` in this directory, and the JSON is also saved as
`history/<date>-<content hash>.json`. Snapshots are named after their content,
not a branch SHA, so squash merges cannot orphan them.

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
| `--retrieval-only` | Call `POST /api/v1/retrieve` instead of `/ask`: no LLM, citation metrics only, written to `latest-retrieval.json`/`.md` |
| `--ollama-url URL` | Where to read the model digest (default `LLM_OLLAMA_HOST`; only a loopback URL while `PRIVACY_LOCAL_ONLY=true`) |
| `--no-history` | Do not write a `history/` snapshot |

With Make, pass them through `EVAL_ARGS`:

```bash
make eval-rag EVAL_ARGS="--subject economics --limit 3"
```

`check_demo_eval.py` rejects partial reports (for example from `--limit`)
unless you pass `--allow-partial`, and always rejects retrieval-only reports.

## Reproducible runs

Answers depend on sampling, so run evaluations with a fixed seed and
temperature 0. Start the API with:

```bash
LLM_TEMPERATURE=0 LLM_SEED=42 make run-api
```

`LLM_SEED` is sent to Ollama as `options.seed`. Knowledge-graph neighbours are
ordered by importance and then by name, so expansion is deterministic too. Two
runs on the same seed and data should show no retrieval flips in
`make eval-compare`. Pin the embedding and reranker models with
`EMBEDDING_MODEL_REVISION` and `RERANKER_MODEL_REVISION` (a Hugging Face
commit) when you need byte-identical retrieval across machines.

`make run-api` passes the checkout's commit to the API as `GIT_SHA`
(`scripts/compose.sh` does the same for containers). Set `GIT_SHA` yourself
when you start the API another way, or the report records `unknown` and
`check_demo_eval.py` rejects it.

For a pull request that changes retrieval, a retrieval-only run is enough and
needs no LLM:

```bash
make eval-rag EVAL_ARGS="--retrieval-only"
make eval-compare BASE=docs/evals/history/<baseline>.json HEAD=docs/evals/latest-retrieval.json
```

## Provenance

Every report (`schema_version` 2) has a `provenance` block:

- `server`: the API's `GET /api/v1/demo/provenance`: app version, `git_sha`,
  embedding and reranker models with their revision (`null` when not pinned)
  and devices, the LLM mode, model, temperature and seed, an allowlist of
  retrieval settings (never credentials or hosts) and the concept and chunk
  counts of each subject;
- `llm`: the answer model and its Ollama digest from Ollama's `/api/tags`;
- `golden_set`: the path and SHA-256 of the golden-set file;
- `harness`: the commit of the checkout that ran the evaluation.

Each case also records a `case_hash` (SHA-256 of its golden definition) and,
per mode, the full answer and the returned sources, so a run can be re-scored
later without asking the API again.

## Validity

A report is valid (`environment_valid: true`) only when:

- the provenance and the available subjects could be read from the API;
- every request, in both modes, for every selected case returned `200`;
- every KG-mode answer reports a KG expansion status other than `failed` (or
  `disabled`, which would make KG mode equal to plain mode).

`check_demo_eval.py` recomputes these rules from the per-case results and
also requires complete provenance: a known server git SHA, the golden-set
hash, the LLM model and Ollama digest, the embedding and reranker models with
their revision fields and devices, the retrieval settings and counts for every
evaluated subject.

## Comparing runs

```bash
make eval-compare BASE=docs/evals/history/<base>.json HEAD=docs/evals/latest.json
```

`scripts/compare_evals.py` compares the case IDs both reports share. It lists
flips per case and mode (citation hit, expected-source rank, KG expansion
status, refusal and prompt-injection results, HTTP status), new and removed
cases and cases whose definition changed. It exits `1` when either report is
partial or invalid, when KG citation hits on the shared cases drop by 2 or
more, or when the KG expected-source MRR drops by 0.03 or more. Add
`--out delta.md` to save the comparison or `--json` for machine-readable
output.

## What is measured

- **Answer term recall:** the share of expected terms that appear in the answer.
- **Citation hit rate:** whether an expected source section appears among the
  returned sources.
- **Expected-source MRR:** how high the first expected source ranks.
- **Unsupported refusal rate:** for questions tagged `unsupported_claim`,
  whether the answer declines instead of asserting the claim.
- **Prompt-injection resistance rate:** for cases with `forbidden_terms` (the
  four `prompt_injection` cases), whether the answer contains none of them
  (case-insensitive), for example the system prompt or the claim the injection
  asks for.
- **KG expansion status counts** and the number of KG expansion failures.
- **KG-versus-plain deltas** for each of the above, plus latency.
- Failure counts per mode, expanded concepts and approximate answer length.

The golden set also includes cross-chapter synthesis, ambiguous,
conflicting-source and prompt-injection questions; its `tags` field says which
is which.

## Reading a report

Every report carries an `environment_valid` flag and a `validity.reasons`
list. A report produced without a live, seeded backend is useful for checking
the harness itself, but it is not evidence of retrieval quality. Only reports
with `environment_valid: true`, complete provenance and non-zero successful
case counts count. `latest.json` may still be an older report without
provenance until the next full run.

## Limitations

The metrics are heuristic: they match keywords and source titles. They show
whether a change helped or hurt this set of questions, not whether the answers
are correct in general, and they do not replace a large external benchmark or
human review. More rigorous evaluation (for example RAGAS or reviewed answer
grading) can build on this harness.
