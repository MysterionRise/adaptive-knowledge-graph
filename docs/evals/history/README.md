# Evaluation history

`scripts/evaluate_rag.py` saves every report here as
`<date>-<content hash>.json`, next to `../latest.json`. The name comes from the
report's content, not from a branch SHA, so a squash merge cannot orphan it.

Commit the snapshots that serve as evidence, such as a release baseline, and
compare any two reports with:

```bash
make eval-compare BASE=docs/evals/history/<base>.json HEAD=docs/evals/latest.json
```

See [../README.md](../README.md) for the report format and the validity rules.
