# Testing

How the test suites are organised, how to run them, and what CI checks.

## Backend (pytest)

Backend tests live in [`backend/tests/`](../backend/tests/): the test modules
in the table below plus shared fixtures in `conftest.py`. The fixtures provide FastAPI test
clients (`client`, plus `production_client` and `development_client` for the
two `APP_ENV` modes), captured logs, and mocks for the Neo4j adapter and
driver, the OpenSearch retriever, the LLM client, the KG expander, the quiz
generator and the Cypher QA service. The suite runs without the Docker stack,
Ollama or model downloads.

| Area | Modules |
| --- | --- |
| API routes and contracts | `test_api_ask.py`, `test_api_graph.py`, `test_api_quiz.py`, `test_api_student.py`, `test_api_subjects.py`, `test_api_subjects_availability.py`, `test_api_validators.py`, `test_api_error_logging.py`, `test_streaming.py`, `test_demo_status.py`, `test_main.py` |
| Security and rate limits | `test_auth.py`, `test_exceptions.py`, `test_privacy.py`, `test_rate_limit.py`, `test_api_rate_limits.py` |
| Retrieval, embeddings and graph | `test_retriever.py`, `test_window_retriever.py`, `test_kg_expansion.py`, `test_reranker.py`, `test_embeddings.py`, `test_neo4j_adapter.py`, `test_cypher_qa.py`, `test_chunker.py` |
| Knowledge-graph building and concept extraction | `test_kg_builder.py`, `test_kg_schema.py`, `test_concept_extractor.py` |
| LLM, quizzes and learner model | `test_llm_client.py`, `test_quiz_generator.py`, `test_student_service.py`, `test_student_counterfactual.py`, `test_student_bkt_properties.py`, `test_student_policy.py`, `test_recommendation_service.py` |
| Configuration and tooling | `test_settings.py`, `test_subjects.py`, `test_logging.py`, `test_docker.py`, `test_makefile.py`, `test_poetry.py`, `test_dx_scripts.py`, `test_release_check.py` |
| Documentation wording ([adaptivity/README.md](adaptivity/README.md)) | `test_adaptivity_wording.py` |
| Adversarial review | `test_tribunal_prosecution.py` |

### Running the tests

```bash
make test                 # every backend test, with coverage
make test-fast            # everything except the tribunal suite
make test-tribunal        # only the tribunal suite
make pre-commit           # format, lint, type-check, then test

poetry run pytest backend/tests/test_settings.py                           # one module
poetry run pytest backend/tests/test_settings.py::test_settings_defaults   # one test
poetry run pytest -m unit                                                   # by marker
poetry run pytest -x --pdb                                                  # stop and debug on the first failure
```

### Markers

Markers are registered in [`pyproject.toml`](../pyproject.toml):

| Marker | Meaning |
| --- | --- |
| `unit` | Fast, isolated tests of a single unit |
| `integration` | Tests that combine several components |
| `slow` | Slow tests; skip them with `-m "not slow"` |
| `tribunal` | The adversarial-review suite |

### Timeouts

An autouse fixture in `conftest.py` fails any test that runs longer than
`PYTEST_TEST_TIMEOUT_SECONDS` (60 seconds by default; `0` turns it off). It
uses `SIGALRM`, so it has no effect on Windows.

### Network guard

Another autouse fixture, `network_guard`, fails any test that tries to connect
to a non-loopback address or to resolve a non-loopback host name. It removes
the proxy variables for the test (a proxy on loopback would tunnel past it),
and it records every attempt, so a test also fails when library code or a
background thread swallows the error. Request the fixture to read the
attempts; `test_privacy.py` uses it to prove `PRIVACY_LOCAL_ONLY` keeps
startup, `/ask` and `/graph/query` local.

### Coverage

`pytest` always measures coverage of `backend/app` (see `addopts` in
`pyproject.toml`), excluding the tests and `__init__.py` files. The regular
(non-tribunal) suite must keep coverage at 75% or more: the CI Tests job and
`make test-fast` pass `--cov-fail-under=75`. For an HTML report:

```bash
poetry run pytest --cov=backend/app --cov-report=html
open htmlcov/index.html
```

### The tribunal suite

`test_tribunal_prosecution.py` holds the tests written during the
[February 2026 adversarial review](archive/tribunal-2026-02/README.md). Each
test targets one charge, a weakness the review found.

- `xfail_strict = true` is set in `pyproject.toml`. A known defect is marked
  `xfail(strict=True)`. When someone fixes it, the test passes unexpectedly
  and the run fails, so the marker has to be removed together with the fix.
- The remaining expected failures document open design gaps: per-learner
  identity
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73))
  and server-side quiz grading
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).

### Writing backend tests

- Name files `test_*.py`, functions `test_*` and classes `Test*`.
- Mock external services with the fixtures in `conftest.py` or `pytest-mock`'s
  `mocker`; a test must not need the network, a running database or a model
  download.
- Mark async tests with `@pytest.mark.asyncio` (`pytest-asyncio`).
- Add a marker when it helps people select the test, and a regression test
  for every bug fix.

## Frontend (Jest and Playwright)

Run these from `frontend/`:

```bash
npm run lint            # ESLint
npm run type-check      # TypeScript, no emit
npm test -- --ci        # Jest unit tests
npm run test:coverage   # Jest with coverage
npm run build           # production build
```

| Suite | Location | Needs |
| --- | --- | --- |
| Unit (Jest, React Testing Library) | `frontend/tests/unit/` | Nothing; the API client is mocked |
| End-to-end (Playwright, Chromium) | `frontend/tests/e2e/` | Nothing; the API is stubbed and Playwright builds and starts the app. Run with `npm run test:e2e`; `E2E_PORT` overrides port 3000 |
| Integration (Playwright) | `frontend/tests/integration/` | A running, seeded stack; run with `make test-integration` |

Before a release or demo, walk through the manual
[testing checklist](../frontend/TESTING_CHECKLIST.md).

## Continuous integration

[`.github/workflows/ci.yaml`](../.github/workflows/ci.yaml) runs on every pull
request, on pushes to `main` and on manual dispatch.

Required jobs, all gated by **All Checks Passed** (the required status check
for merging into `main`):

| Job | What it runs |
| --- | --- |
| Lint & Format Check | `ruff check` and `ruff format --check`, plus a `poetry.lock` consistency check |
| Type Check (mypy) | `mypy`, with the paths from `[tool.mypy] files` (`backend/app` and `scripts`) |
| Tests (Python 3.11, 3.12, 3.13) | `pytest -m "not tribunal"`, failing below 75% coverage |
| Frontend (lint, types, tests, build) | `npm run lint`, `npm run type-check`, Jest with coverage, `npm run build` |
| Docker Compose Validation | Starts Neo4j and OpenSearch, waits until they are healthy and checks that they respond |
| Documentation Check | markdownlint on `*.md`, `docs/**`, `frontend/*.md`, `infra/**` and `.github/*.md` |
| Security Scan | bandit, with results uploaded to code scanning |
| Dependency Audit (new advisories) | When a pull request changes a lockfile or an `osv-scanner.toml`: osv-scanner on the change and on the base branch; fails only on advisories the change adds |
| Tribunal Tests | `pytest -m tribunal`, the adversarial risk register (required since v0.3.0) |
| E2E Tests (Playwright) | The hermetic Chromium suite (`npm run test:e2e`, with the API stubbed) on every pull request, push and manual dispatch (required since v0.3.0) |
| Link Check | lychee in offline mode over the same Markdown files as the documentation check (required since v0.3.0) |
| Shellcheck | `shellcheck scripts/*.sh` (required since v0.3.0) |

Advisory jobs (they report but do not block):

- **Dependency Audit (full scan):** osv-scanner over `poetry.lock` and
  `frontend/package-lock.json`, with results uploaded to code scanning. It
  stays advisory, because a newly published advisory would otherwise block
  unrelated pull requests; the required gate is the new-advisories job above.
- **npm audit:** part of the frontend job, advisory for the same reason.

The live-stack integration suite runs locally with `make test-integration`.
Separate workflows run CodeQL analysis, build the Docker images when their
inputs change, and publish a GitHub Release for `vX.Y.Z` tags on `main` once
the [release check](#release-check) passes. A
weekly dependency audit scans `main` and keeps one tracking issue up to date
with the advisories outside the allowlists and the allowlist entries that
expire within 30 days.

The allowlists are `osv-scanner.toml` (Python) and `frontend/osv-scanner.toml`
(npm): osv-scanner applies the file next to each lockfile. Every entry needs a
reason that names an issue and an `ignoreUntil` date at most 90 days out;
`backend/tests/test_osv_audit.py` enforces both and checks that the torch
features the reasons call unused stay unused. It also keeps transformers
remote code, model saving, training and the `kernels` package out of the
project. Both files hold only `[[IgnoredVulns]]` tables with the keys `id`,
`ignoreUntil` and `reason`, which the same test file checks: what backs an
entry goes into its reason.

Every npm entry is accepted because its package is dev-only. Its reason starts
with the package and every version the lock has of it (`braces 3.0.3 is a
dev-only dependency ...`, or `glob 10.5.0 and 13.0.6 are dev-only dependencies
...`) and says that the package is not in the production bundle. The same test
file checks each reason:

- **Lock.** In `frontend/package-lock.json`, every copy of the package, nested
  ones included, is marked `"dev": true`, the locked versions are exactly the
  stated ones, and the package is not a direct production dependency.
- **Named tools.** A devDependency of the project that the reason names with a
  version (`jest 30`, `tailwindcss 3`, `ESLint 9`) is locked at that version,
  and installing it installs the package.
- **Imports.** No file under `frontend/app`, `frontend/components`,
  `frontend/lib` or `frontend/types` imports the package, because Next.js
  bundles what the application imports.

`backend/tests/test_docker.py` checks the image in
`infra/docker/frontend.Dockerfile`. The build stage runs `npm prune
--omit=dev` after `npm run build`, and after the prune it neither copies files
in nor installs packages. The runtime stage starts from a base image, copies
`/app/node_modules` from the build stage, copies nothing from another stage
and installs no packages.

A dependency update that changes a locked version of one of these packages, or
the major version of a tool a reason names, fails the test until the reason is
updated. Three things are not checked: whether the advisory is about the
package its reason names (the suite is offline, so check that when you add an
entry), code that a production dependency ships inside its own package (the
lock lists packages, not their contents), and a build of the image.

## Release check

`make release-check TAG=vX.Y.Z` runs `scripts/release_check.py`, an offline
gate for the tree that is about to be tagged. The script needs only the
Python standard library (3.11 or later), no network and no git, so
`python3 -I scripts/release_check.py --tag vX.Y.Z` also works on a fresh
checkout. It prints one `ok` or `FAIL` line per check, lists every problem
with the file it is in, and exits 1 when any check fails. Nothing is
advisory.

| Check | Passes when |
| --- | --- |
| `versions` | `pyproject.toml`, `frontend/package.json`, the two root entries of `frontend/package-lock.json` and `CITATION.cff` carry the same `MAJOR.MINOR.PATCH` version. With `TAG`, the tag is exactly `v` plus that version; a pre-release or build tag such as `v0.4.0-rc.1` fails |
| `changelog` | `CHANGELOG.md` has exactly one `## [X.Y.Z] - YYYY-MM-DD` section with a calendar date and a body, `## [Unreleased]` is still above it, the target of the `[X.Y.Z]:` link reference ends with the tag (`.../releases/tag/vX.Y.Z`, or a compare range that ends `...vX.Y.Z`), and `date-released` in `CITATION.cff` is the same date |
| `placeholders` | `README.md` and `CHANGELOG.md` contain no `FILL (` HTML comment |
| `evidence` | `docs/evals/latest.json` passes the rules of `scripts/check_demo_eval.py` (a valid full run, the API's app version is the `pyproject.toml` version, the golden set is unchanged since the run), and its snapshot in `docs/evals/history/` exists with identical bytes |
| `assets` | `docs/assets/demo/` holds at least one non-empty image file (`.png`, `.jpg`, `.jpeg`, `.gif` or `.webp`) |

The Release workflow runs the same script on the tag's tree, after it has
checked that the tag is on `main` and before it creates anything. The step
gets no token, and the workflow's permissions are unchanged. Because the
check accepts only `vX.Y.Z`, the workflow no longer publishes a pre-release
or build tag of a tree that has the script; its pre-release handling is
reached only by tags that predate the script.

Three things to know before a release:

- **Bump the version before the final-split run.** `check_demo_eval.py`
  compares the app version the API reported during the run with the version
  in `pyproject.toml`, so `make demo-eval` and the `evidence` check both
  reject a report from an API that still ran the previous version. A
  final-split run made before the bump therefore has to be repeated, and the
  [evaluation protocol](evals/protocol.md) allows one final-split run per
  release gate and reports a second one as such. Bump every file the
  `versions` check reads, run `poetry install` (or rebuild the image) and
  restart the API, then run the evaluation.
- **The commit in the report need not be on `main`.** Evidence produced on a
  release branch records that branch's commit, and a squash merge leaves it
  unreachable from `main`. The check does not look at git and does not
  compare the recorded commit with the tag. It requires only that the API and
  the harness ran the same commit. What ties the evidence to the release is
  the app version, the golden-set hash and the snapshot's bytes.
- **Tags that predate the script skip the gate.** The workflow runs the
  script from the tag's own tree. A tree without `scripts/release_check.py`
  (`v0.3.0` and earlier) skips the step with a notice, so an old tag can
  still be re-published by hand.

## Evaluation

The retrieval and answer-quality evaluation is not a unit test: it runs the
golden question set against a live, seeded API. See
[evals/README.md](evals/README.md).

## Troubleshooting

- **Import errors.** Run the tests from the repository root with
  `poetry run`, after `poetry install`.
- **A test hits the timeout.** Something is waiting on a real service; mock it.
- **Passes locally, fails in CI.** Check for missing environment variables,
  dependencies that are only installed locally, or path assumptions; the CI
  job environment is defined in `.github/workflows/ci.yaml`.
