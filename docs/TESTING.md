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
| LLM, quizzes and learner model | `test_llm_client.py`, `test_quiz_generator.py`, `test_student_service.py`, `test_recommendation_service.py` |
| Configuration and tooling | `test_settings.py`, `test_subjects.py`, `test_logging.py`, `test_docker.py`, `test_makefile.py`, `test_poetry.py`, `test_dx_scripts.py` |
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

Advisory jobs (they report but do not block yet; the v0.3.0 release makes them
required):

- **Tribunal Tests:** `pytest -m tribunal`.
- **Dependency Audit:** osv-scanner over `poetry.lock` and
  `frontend/package-lock.json`.
- **Link Check:** lychee in offline mode over the same Markdown files as the
  documentation check.
- **npm audit:** part of the frontend job.
- **E2E Tests (Playwright):** the hermetic Chromium suite (`npm run test:e2e`,
  with the API stubbed) on every pull request, push and manual dispatch.
- **Shellcheck:** `shellcheck scripts/*.sh`.

The live-stack integration suite runs locally with `make test-integration`.
Separate workflows run CodeQL analysis, build the Docker images when their
inputs change, and publish a GitHub Release for `vX.Y.Z` tags on `main`.

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
