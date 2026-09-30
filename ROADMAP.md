# Roadmap

Adaptive Knowledge Graph is a proof of concept and pilot prototype. The roadmap
puts evidence, correctness and operational basics ahead of broad new features.
Work is tracked in
[GitHub issues](https://github.com/MysterionRise/adaptive-knowledge-graph/issues);
issues labelled
[help wanted](https://github.com/MysterionRise/adaptive-knowledge-graph/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
are good places to contribute.

## Done

- The golden evaluation set covers 53 questions across US History and
  Economics, including unsupported-claim and prompt-injection cases.
- The adversarial (tribunal) tests run as their own suite (`-m tribunal`,
  `make test-tribunal`) and CI job, separate from the regular tests.
- Documentation claims about IRT, teacher editing, a mock-data fallback and
  production readiness were removed or corrected.

## Now: v0.3.0 open-source quality sprint

Tracked in [#105](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/105):

- Patch vulnerable dependencies, and scan both lockfiles in CI.
- Production mode (`APP_ENV=production`), enforced `PRIVACY_LOCAL_ONLY`,
  read-only graph queries, and correct API input and error contracts.
- A one-command local stack (`make quickstart`, `make doctor`).
- Frontend platform upgrade and Node 24.
- Backend coverage of at least 75%, enforced, and the tribunal suite on every
  pull request.
- A verified quickstart, a real evaluation report, screenshots and a tagged
  v0.3.0 release.

## Next: evidence and stability

- Keep evaluation report snapshots for retrieval and prompt changes, and
  require evaluation deltas in pull requests that touch them.
- Seed the configured Biology 2e and World History subjects
  ([#75](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/75)).
- Upgrade to transformers 5 and sentence-transformers 6
  ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71))
  and langchain 1.x
  ([#72](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/72)).
- Support Python 3.14
  ([#76](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/76))
  and install CPU-only torch wheels in CI
  ([#79](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/79)).
- Generate the frontend API types from the OpenAPI schema
  ([#77](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/77)).

## Later: platform hardening

- Per-learner identity, roles and scoped permissions
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
- Tenant and cohort data boundaries.
- Async Neo4j and OpenSearch clients and a proper application lifecycle
  ([#78](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/78)).
- OpenTelemetry spans for KG expansion, retrieval, reranking, LLM generation
  and learner-model updates.
- Database migrations and backup and restore documentation for SQLite and
  Neo4j.
- Browser tests against a live staging stack, beyond the hermetic Playwright
  suite that runs on every pull request.

## Later: assessment integrity

- Server-side quiz grading and an answer-submission endpoint
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).
- A persistent question bank with versioned generated questions.
- An assessment attempt ledger with signed attempt records.
- Calibrated difficulty from learner response data before any IRT claims.
- A human-review workflow for generated questions.
- Instructor and admin dashboards, only after role boundaries exist.
- A deployment runbook covering secrets, TLS, backups, observability and
  incident response.

## Explicit non-goals for now

- No production certification issuance.
- No proctoring.
- No enterprise dashboard until identity, tenancy and audit logging exist.
- No claim that LLM-estimated difficulty equals psychometric calibration.
