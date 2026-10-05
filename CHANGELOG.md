# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The full list of changes from the v0.3.0 open-source quality sprint
([#105](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/105))
is compiled in the release pull request
([#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104)).

### Changed

- **Breaking:** `PRIVACY_LOCAL_ONLY=true`, the default, now requires
  `LLM_MODE=local`. The API refuses to start with `LLM_MODE=remote` or
  `LLM_MODE=hybrid` unless you also set `PRIVACY_LOCAL_ONLY=false`
  ([#89](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/89)).
- The Docker Compose project is now named `adaptive-kg`, so volumes from an
  older checkout (`compose_*`) are no longer used automatically. Set
  `COMPOSE_PROJECT_NAME=compose` to keep them, or re-seed with `make seed`
  ([#102](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/102)).
- `LICENSE` is now the plain MIT text. OpenStax attribution and the trademark
  notice moved to `NOTICE`
  ([#99](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/99)).
- The README was rewritten for open-source users. Demo material moved to
  `docs/demo/`, the adversarial review transcripts to
  `docs/archive/tribunal-2026-02/`, and `TESTING.md` and `COMPLIANCE.md` to
  `docs/`. `ROADMAP_2026.md` is now `ROADMAP.md`
  ([#98](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/98)).
- Natural-language graph queries (`/api/v1/graph/query`) run on langchain-core
  1.x and langchain-neo4j 0.10, with `langchain-ollama` and `langchain-openai`
  for the chat models. `langchain` and `langchain-community` are no longer
  installed. Schema introspection, which langchain-neo4j now runs outside
  `Neo4jGraph.query()`, still runs in READ transactions, and an unreachable
  Ollama or OpenRouter answers 503
  ([#72](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/72)).

### Added

- Community health files: code of conduct, security policy, support guide,
  issue forms, citation metadata, `CODEOWNERS`, `.editorconfig` and
  `.gitattributes`
  ([#99](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/99)).

### Removed

- Unused Python dependencies
  ([#93](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/93)).
  Recreate an existing virtual environment after upgrading
  (`poetry env remove --all && poetry install --without pyirt,pybkt`, then
  `make quickstart` to reinstall the spaCy model); syncing it in place can
  break `import spacy`. See CONTRIBUTING.md, "Upgrading an existing checkout".
- `.env.demo` is no longer tracked. Copy `.env.demo.example` instead
  ([#99](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/99)).

### Fixed

- KG expansion no longer stores each request's concept names on the shared
  concept extractor, so concurrent questions for different subjects cannot be
  matched against each other's concepts. Concept names are cached per subject
  for 5 minutes instead of being loaded from Neo4j on every question; restart
  the API after re-seeding to use the new names at once
  ([#157](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/157)).

## Earlier history

No versions were tagged before 0.3.0. These are the main milestones in the Git
history:

- **2026-07: demo readiness.** Demo readiness endpoint and `/demo-status` page,
  scripted `make demo-*` workflow with a strict readiness gate, and a golden
  evaluation set of 53 US History and Economics cases comparing KG-expanded and
  plain retrieval
  ([#64](https://github.com/MysterionRise/adaptive-knowledge-graph/pull/64),
  [#65](https://github.com/MysterionRise/adaptive-knowledge-graph/pull/65),
  [#66](https://github.com/MysterionRise/adaptive-knowledge-graph/pull/66)).
- **2026-03: learner model and reranker.** Bayesian Knowledge Tracing mastery
  updates (`STUDENT_BKT_ENABLED`) and an opt-in cross-encoder reranker
  (`RERANKER_ENABLED`, `BAAI/bge-reranker-v2-m3`).
- **2026-02: adversarial review.** A structured review of the codebase (archived
  in `docs/archive/tribunal-2026-02/`), fixes for its critical findings, and a
  `tribunal` test suite that tracks the rest.
- **2026-02: hybrid retrieval and streaming.** BM25 + kNN hybrid retrieval with
  reciprocal rank fusion, streamed answers over server-sent events, adaptive
  quizzes, LLM retries and request IDs.
- **2026-02: multi-subject architecture.** Subjects defined in
  `config/subjects.yaml`, isolated with Neo4j label prefixes and per-subject
  OpenSearch indices; Economics added next to US History.
- **2025-11: initial proof of concept.** FastAPI backend, Neo4j knowledge graph,
  local LLM through Ollama and a Next.js frontend; OpenSearch replaced Qdrant as
  the vector store.

[Unreleased]: https://github.com/MysterionRise/adaptive-knowledge-graph/commits/main
