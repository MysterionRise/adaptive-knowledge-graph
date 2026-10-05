# Tribunal review, February 2026 (archived)

This folder archives an adversarial review of the codebase carried out in
February 2026 (the verdict is dated 2026-02-26). The review was run as a
"tribunal": several reviewers each argued one side, and a final verdict weighed
their arguments against the evidence.

These documents are a historical snapshot. File paths, line numbers, test counts
and coverage figures describe the code as it was then, and many findings have
since been fixed. They are kept for context, not as current documentation.

## Documents

| File | Role |
| --- | --- |
| [TRIBUNAL_PROSECUTION_CHARGES.md](TRIBUNAL_PROSECUTION_CHARGES.md) | Security and correctness charges, each backed by a test |
| [TRIBUNAL_WITNESS_REPORT.md](TRIBUNAL_WITNESS_REPORT.md) | Factual observations about structure, behaviour and test results |
| [TRIBUNAL_DEVIL_ARGUMENTS.md](TRIBUNAL_DEVIL_ARGUMENTS.md) | The case against the design, argued deliberately one-sidedly |
| [TRIBUNAL_ANGEL_ARGUMENTS.md](TRIBUNAL_ANGEL_ARGUMENTS.md) | The case for the design, argued deliberately one-sidedly |
| [TRIBUNAL_VERDICT.md](TRIBUNAL_VERDICT.md) | Rulings on each contested decision, severity of each charge, and the must-fix list |

The two advocate documents are arguments, not verified facts. Organisation and
product names, and unsourced comparisons with other products, were replaced
with neutral wording when the documents were archived; nothing else was
changed.

## Where the findings went

- The prosecution charges live on as the `tribunal` test suite in
  [`backend/tests/test_tribunal_prosecution.py`](../../../backend/tests/test_tribunal_prosecution.py).
  Run it with `make test-tribunal` or `poetry run pytest -m tribunal`. See
  [docs/TESTING.md](../../TESTING.md) for how it runs in CI.
- The five must-fix items were addressed right after the review.
- The remaining findings are tracked as GitHub issues. The v0.3.0 sprint
  ([#105](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/105))
  addresses most of them, for example input validation
  ([#85](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/85)),
  API error contracts
  ([#86](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/86)),
  production mode
  ([#87](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/87)),
  the read-only graph query
  ([#88](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/88)),
  privacy enforcement
  ([#89](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/89))
  and learner storage
  ([#90](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/90)).
- Two design-level gaps stay open and are kept as strict expected failures in
  the suite: per-learner identity
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73))
  and server-side quiz grading
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).
