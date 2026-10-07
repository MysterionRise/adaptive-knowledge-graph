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

- `make doctor` now reads the backend Python requirement from `pyproject.toml`
  and discovers versioned Python executables on PATH, avoiding stale
  hard-coded bounds when the supported range changes.

- **Breaking:** `PRIVACY_LOCAL_ONLY=true`, the default, now requires
  `LLM_MODE=local`. The API refuses to start with `LLM_MODE=remote` or
  `LLM_MODE=hybrid` unless you also set `PRIVACY_LOCAL_ONLY=false`
  ([#89](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/89)).
- **Breaking:** `PRIVACY_LOCAL_ONLY=true` now also refuses to start when a
  LangSmith tracing variable (`LANGSMITH_TRACING`, `LANGSMITH_TRACING_V2`,
  `LANGCHAIN_TRACING`, `LANGCHAIN_TRACING_V2`) is on, when `LLM_OLLAMA_HOST`
  is not a loopback or private address (`localhost`, `ollama`,
  `host.docker.internal`, `host.containers.internal`, a private IP, or a name
  that resolves only to those), or when `LLM_LOCAL_MODEL` is an Ollama cloud
  model (`-cloud`, `:cloud`). The error names the setting: unset the tracing
  variable, point `LLM_OLLAMA_HOST` at a local Ollama, pick a local model, or
  set `PRIVACY_LOCAL_ONLY=false` if that traffic is approved. The API also
  disables LangSmith tracing at runtime, sets `HF_HUB_DISABLE_TELEMETRY=1`,
  runs the Hugging Face Hub offline (`HF_HUB_OFFLINE=1`) once its models are
  cached, and Compose turns Neo4j usage reporting off
  ([#159](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/159)).
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
- **Re-seed required:** ingestion now keeps each module's real title and
  chapter (`chapter`, `section`, and `module_title` as
  `"<chapter> - <section>"`) instead of `"<book> - <module id>"`. Retrieval
  boosts these titles, `/ask` and `/ask/stream` sources carry `chapter` and
  `section`, and the chat shows them. Rebuild existing data with
  `make pipeline-all` (it re-ingests, rebuilds the graph and recreates the
  index; `make seed` keeps a graph and index that already exist), then
  `make build-windows` if you use window retrieval. Data seeded before this
  change has no chapters and only module IDs as titles. The evaluation
  harness matches expected sources on titles only (no longer on the text
  preview), and the golden set's `expected_sources` now name real sections,
  so citation hit rate and MRR are not comparable with earlier reports
  ([#154](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/154)).
- Natural-language graph queries (`/api/v1/graph/query`) run on langchain-core
  1.x and langchain-neo4j 0.10, with `langchain-ollama` and `langchain-openai`
  for the chat models. `langchain` and `langchain-community` are no longer
  installed. Schema introspection, which langchain-neo4j now runs outside
  `Neo4jGraph.query()`, still runs in READ transactions, and an unreachable
  Ollama or OpenRouter answers 503
  ([#72](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/72)).
- Embeddings and reranking run on transformers 5 and sentence-transformers
  6.1 (with huggingface-hub 1.x, tokenizers 0.23 and safetensors 0.8). This
  clears the transformers 4.x advisories, including the remote-code-execution
  ones, and removes their 6 entries from `osv-scanner.toml`. The models and
  their configuration are unchanged; after upgrading an existing install, run
  `make embedding-parity` against the seeded index to confirm the stored
  vectors still match
  ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71)).
- BGE-M3 now loads a pinned Hugging Face commit (`5617a9f6`) unless
  `EMBEDDING_MODEL_REVISION` is set, so an upstream model update cannot
  change the vectors of an existing index. Set `EMBEDDING_MODEL_REVISION=main`
  to follow the branch. Offline mode (`HF_HUB_OFFLINE=1`) now starts only once
  the revision the API loads is cached, so a cache that holds another BGE-M3
  commit fetches the pinned one on the next start. Another `EMBEDDING_MODEL`
  is not pinned, and the reranker still follows its default branch
  ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71)).

### Added

- Index fingerprints: a new OpenSearch index records the embedding model, its
  revision, the vector dimension and the vector of a fixed probe text in its
  mapping's `_meta`. `make doctor` (`scripts/stack_check.py index-fingerprint`)
  re-embeds the probe with the installed stack and fails when the model
  differs or the probe's cosine similarity drops below 0.999, naming the
  command that rebuilds the index (`make index-rag SUBJECT=… RECREATE=1`;
  `RECREATE=1` is new and drops the index first). It warns about an index
  built before fingerprints (rebuild it to enable the check) and one built
  with another revision whose probe still matches
  ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71)).

- `make embedding-parity` (`scripts/check_embedding_parity.py`) re-embeds a
  fixed sample of 50 indexed chunks with the installed embedding stack and
  compares them with the stored vectors. It exits 1 when any cosine
  similarity is below 0.999, which means the index needs new embeddings;
  `RERANKER=1` also smoke-tests the cross-encoder. Run it after upgrading
  transformers, sentence-transformers or torch
  ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71)).

- Community health files: code of conduct, security policy, support guide,
  issue forms, citation metadata, `CODEOWNERS`, `.editorconfig` and
  `.gitattributes`
  ([#99](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/99)).
- Evaluation provenance and comparison: `/ask`, `/ask/stream` and the new
  retrieval-only `POST /api/v1/retrieve` report `kg_expansion_status`;
  `GET /api/v1/demo/provenance` reports the git SHA, models, devices,
  allowlisted retrieval settings and per-subject counts, and requires the API
  key when one is configured (`evaluate_rag.py` sends `API_KEY`, or
  `--api-key`); reports record that provenance, the Ollama digest, golden-set
  and per-case hashes, answers and sources, score prompt injection and are
  saved to `docs/evals/history/`; `check_demo_eval.py` and the demo status page
  share one rule set: complete provenance, a `200` for every request, zero
  KG-expansion failures, a server on the harness's commit and an unchanged
  golden set; `make eval-compare BASE=… HEAD=…` compares two reports of the
  same run mode and gates only cases whose definition is unchanged; `LLM_SEED`
  and model revision settings make runs reproducible
  ([#155](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/155)).

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

- GitHub book-content downloads now use a 30-second request timeout and an
  identifying User-Agent, with at most three attempts and 1/2-second backoff
  for HTTP 429/5xx, timeouts and connection failures. Other HTTP failures are
  not retried
  ([#161](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/161)).
- KG expansion no longer stores each request's concept names on the shared
  concept extractor, so concurrent questions for different subjects cannot be
  matched against each other's concepts. Concept names are cached per subject
  for 5 minutes instead of being loaded from Neo4j on every question; restart
  the API after re-seeding to use the new names at once
  ([#157](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/157)).
- KG expansion builds the same expanded query in every API process: the
  question's concepts first, then their neighbours in graph order. The order
  used to follow per-process set ordering, and the expanded query is embedded
  for retrieval, so the same question could retrieve different chunks after a
  restart
  ([#155](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/155)).
- Prompt-injection scoring no longer counts a refusal that repeats the
  injected claim ("I can't say that markets always work perfectly") as a
  successful injection: such cases now list `forbidden_claims`, which count
  only in a sentence without a negation or refusal
  ([#155](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/155)).

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
