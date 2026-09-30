# Contributing to Adaptive Knowledge Graph

Thanks for your interest in improving the project. This guide covers the
development setup, the quality gates every change must pass and how pull
requests are merged.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Report security problems privately as described in [SECURITY.md](SECURITY.md),
never in a public issue.

## Where to start

- Browse the
  [good first issues](https://github.com/MysterionRise/adaptive-knowledge-graph/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  and the
  [help wanted issues](https://github.com/MysterionRise/adaptive-knowledge-graph/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22).
- Comment on an issue before you start, so nobody duplicates the work.
- For larger changes, open an issue or a thread in
  [Discussions](https://github.com/MysterionRise/adaptive-knowledge-graph/discussions)
  first and agree on the approach.
- Questions about setup go to
  [Discussions: Q&A](https://github.com/MysterionRise/adaptive-knowledge-graph/discussions/categories/q-a).

## Development setup

You need Python 3.11–3.13, Poetry 2.x, Node.js 24 LTS, Docker with Compose
v2.24 or newer, and Ollama. The [README quickstart](README.md#quickstart) lists them with
hardware requirements.

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/<your-username>/adaptive-knowledge-graph.git
cd adaptive-knowledge-graph
git remote add upstream https://github.com/MysterionRise/adaptive-knowledge-graph.git

ollama pull llama3.1:8b-instruct-q4_K_M
make quickstart          # dependencies, local stack and seeded data
make install-dev         # dev dependencies and the pre-commit hooks

cd frontend && npm ci    # frontend dependencies
```

Most backend work does not need the full stack: the test suite mocks Neo4j,
OpenSearch and the LLM. You need the running stack only to try changes end to
end (`make run-api` and `npm run dev`).

## Project layout

```text
adaptive-knowledge-graph/
├── backend/
│   ├── app/
│   │   ├── api/routes/     # FastAPI routers: ask, quiz, graph, learning_path, subjects, demo
│   │   ├── core/           # settings, subject config loader, auth, rate limiting, logging, middleware
│   │   ├── kg/             # graph schema, builder, Neo4j adapter, Cypher QA
│   │   ├── nlp/            # embeddings, concept extraction, LLM client
│   │   ├── rag/            # chunker, retriever, KG expansion, reranker, window retrieval
│   │   ├── student/        # quiz generation, learner model, recommendations
│   │   ├── ui_payloads/    # response models for quiz and recommendation payloads
│   │   └── main.py         # app setup, middleware and health endpoints
│   └── tests/              # pytest suite (see docs/TESTING.md)
├── config/subjects.yaml    # subject definitions: books, prompts, indices, theme, attribution
├── data/                   # OpenStax source text, processed data, evaluation golden set
├── docs/                   # architecture, testing, compliance, evaluation, demo, archive
├── frontend/               # Next.js app: app/, components/, lib/, tests/
├── infra/                  # Docker Compose stack and Dockerfiles
└── scripts/                # ingestion, knowledge-graph build, indexing, evaluation, demo scripts
```

## Making a change

1. Sync with upstream and create a branch:

   ```bash
   git fetch upstream
   git checkout -b fix/short-description upstream/main
   ```

2. Make the change, with tests. Keep pull requests focused: one logical change
   per PR is easier to review and to revert.
3. Run the quality gates (next section).
4. Update the documentation when behaviour, configuration or commands change,
   and add a line under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for
   user-visible changes.
5. Push to your fork and open a pull request against `main`. The pull request
   template lists what reviewers look for.

## Quality gates

CI runs these checks on every pull request. Run them locally before you push.

Backend, from the repository root:

```bash
make format        # ruff format + ruff check --fix
make lint          # ruff check
make type-check    # mypy on backend/app and scripts/
make test          # pytest with coverage
make pre-commit    # all of the above in order
```

Frontend, from `frontend/`:

```bash
npm run lint
npm run type-check
npm test -- --ci
npm run build
```

Documentation, from the repository root:

```bash
npx --yes markdownlint-cli2 "*.md" "docs/**/*.md" "frontend/*.md" "infra/**/*.md" ".github/*.md"
```

CI also checks relative links in those files with
[lychee](https://github.com/lycheeverse/lychee) in offline mode.

If you installed the hooks with `make install-dev`, `pre-commit` runs the
formatters, ruff and mypy on each commit. See [docs/TESTING.md](docs/TESTING.md)
for the full list of CI jobs, test markers, the tribunal suite and coverage.

## Coding standards

### Python

- Ruff handles linting and formatting (line length 100). Its rule set includes
  pyupgrade (`UP`), so use modern syntax.
- Type-hint public functions. Use built-in generics and `X | None`, not
  `typing.List` or `Optional`.
- Write Google-style docstrings for public functions and classes.
- Read settings through `backend.app.core.settings.settings`; never hard-code
  hosts, credentials or model names.
- Log with `loguru`, and never log secrets. API error responses must not leak
  exception details.

```python
def extract_concepts(text: str, max_concepts: int = 10) -> list[dict[str, float]]:
    """Extract key concepts from text.

    Args:
        text: Input text to analyze.
        max_concepts: Maximum number of concepts to return.

    Returns:
        Concept dictionaries with scores, highest score first.
    """
    ...


def find_subject(subject_id: str | None = None) -> str | None:
    """Return the subject ID to use, or None when no subject is configured."""
    ...
```

### TypeScript

- ESLint and TypeScript strict checks must pass.
- Call the backend through the shared client in `frontend/lib/api-client.ts`
  and keep `frontend/lib/types.ts` in sync with the API models.

### Tests

- Add unit tests for new functions and route tests for new or changed
  endpoints, and a regression test for every bug fix.
- Tests must not depend on the network, a running database or model
  downloads; use the fixtures in `backend/tests/conftest.py`.
- Keep coverage from going down; CI enforces a minimum.

### Content and privacy

- Keep the OpenStax attribution for any new or changed content, and do not
  use OpenStax content to train models.
- New outbound network calls must be blocked when `PRIVACY_LOCAL_ONLY=true`.
- Never commit secrets, `.env` files, real learner data or personal data.

## Common tasks

**Add an API endpoint.** Add the route to the matching module in
`backend/app/api/routes/`. A new module must be exported from
`backend/app/api/routes/__init__.py` and `backend/app/api/__init__.py` and
included in `backend/app/main.py`. Put request and response models next to the
route (or in `backend/app/ui_payloads/` when the frontend shares them), and add
tests in `backend/tests/test_api_*.py`. FastAPI generates the OpenAPI docs.

**Add a setting.** Add the field to `backend/app/core/settings.py`, document it
in `.env.example`, and add it to the README configuration table if users need
to know about it.

**Add a subject.** Add an entry to `config/subjects.yaml`, then build its data
with `make ingest-books SUBJECT=<id>`, `make build-kg SUBJECT=<id>` and
`make index-rag SUBJECT=<id>`. A step-by-step tutorial is tracked in
[#84](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/84).

**Change the knowledge-graph schema.** Update `backend/app/kg/schema.py`, the
builder in `backend/app/kg/builder.py` and the queries in
`backend/app/kg/neo4j_adapter.py`, then add tests.

## Commit messages and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/) for commit
messages and pull request titles:

```text
feat: add a learning-path endpoint for prerequisites
fix: return 404 for unknown subjects
docs: explain window retrieval settings
test: cover the reranker fallback
refactor: split the quiz generator prompts
chore: bump ruff
ci: cache the Poetry virtualenv
```

Mark breaking changes with `!` (for example `feat!: require LLM_MODE=local in
privacy mode`) and describe the migration in the pull request.

## Review and merge

- `main` is protected. The required status check is **All Checks Passed**,
  which succeeds only when every required CI job passes, and the branch must be
  up to date with `main` before it can merge.
- Approving reviews are not required by branch protection, but maintainers
  review pull requests and may ask for changes.
- Pull requests are squash-merged, so the pull request title becomes the commit
  message on `main`.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE). Content derived from OpenStax stays under CC BY 4.0 and
must keep its attribution; see [NOTICE](NOTICE).
