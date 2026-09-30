# Roadmap

The project is currently a production-shaped AI platform prototype, not a
production certification product. The roadmap focuses on credibility,
evaluation, and operational maturity before adding broad enterprise features.

## Next 30 Days: Evidence and Stability

- Expand `data/evals/golden_qa.yaml` to 50+ questions across subjects.
- Add eval report snapshots for retrieval/prompt changes.
- Keep CI strict for backend fast tests, frontend unit tests, and type checks.
- Split tribunal/adversarial tests into a separate risk-register job.
- Clean remaining docs claims around IRT, teacher mode, mock fallback, and
  production readiness.
- Add screenshots or a short demo video to the portfolio case study.

## Next 60 Days: Platform Hardening

- Replace API-key-only access with identity, roles, and scoped permissions.
- Add tenant and cohort data boundaries.
- Add OpenTelemetry spans for KG expansion, retrieval, reranking, LLM generation,
  and student updates.
- Move blocking graph/search calls behind executors or adopt async clients.
- Add database migrations and backup/restore documentation for SQLite/Neo4j.
- Add staging-backed browser E2E instead of manual-only Playwright runs.

## Next 90 Days: Assessment Integrity

- Add a persistent question bank with versioned generated questions.
- Add assessment attempt ledger with signed attempt records.
- Calibrate difficulty with learner response data before making IRT claims.
- Add human-review workflow for generated questions.
- Add instructor/admin dashboards only after role boundaries exist.
- Produce a deployment runbook covering secrets, TLS, backups, observability, and
  incident response.

## Explicit Non-Goals For Now

- No claim of production certification issuance.
- No full proctoring product.
- No enterprise dashboard until identity, tenancy, and audit logging are real.
- No claim that LLM-generated difficulty equals psychometric calibration.
