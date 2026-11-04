# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Golden set version 3
  ([#206](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/206)):
  every case has a `stratum` and a `split` (24 rehearsal, 29 final), drawn by
  `scripts/split_golden.py` from a recorded seed and stratified by subject and
  stratum. `docs/evals/protocol.md` fixes the bar per stratum, the primary
  endpoint (KG minus plain citation hit rate on the final split) and how cases
  are added, and pins the final split by case hash.
- `evaluate_rag.py --split rehearsal|final|all` and `make eval-rehearsal`.
  Rehearsal runs write `latest-rehearsal.*`, and `check_demo_eval.py` and the
  demo status page do not accept them as release evidence. Reports record the
  split, the split seed and the protocol's hash.
- Uncertainty in every evaluation report
  ([#209](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/209)):
  - **Intervals.** KG-minus-plain differences in citation hit rate, MRR and
    non-echo term recall come with seeded 95% paired bootstrap intervals
    (2000 resamples, standard library only), overall and per stratum
    (`summary.intervals` and a table in `latest.md`).
  - **Primary endpoint.** The report generates the sentence a release may
    quote: the rates, the interval, the case counts and non-inferiority at the
    −0.10 margin.
  - **Noise floor.** `make eval-noise-floor` records it from two repeat runs
    in `docs/evals/noise-floor.json`. Reports apply it when the LLM, embedding
    and reranker match.
  - **Protocol deviations.** A full report flags a temperature other than 0 or
    a missing seed.

  `compare_evals.py` prints each run's intervals and says whether the two runs
  are repeats. The re-scoring fixture gains the new summary fields; scores are
  unchanged.

- A retrieval trace per request
  ([#216](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/216)):
  - **Stages.** `resolve`, `expand`, `knn`, `bm25`, `fuse`, `window`, `rerank`
    and `select`, each with its timing, keyed by `X-Request-ID`. `fuse` lists
    every candidate's rank in each channel and each channel's contribution to
    its score; `expand` records the concept, edge types and provenance behind
    each graph neighbour.
  - **Access.** `include_trace` on `/retrieve` (default on), `/ask` and
    `/ask/stream` (default off; the stream sends it in the `metadata` event).
    A serialised trace keeps an allowlist of fields: no prompt, no chunk text
    beyond the 200-character preview, no hosts or keys. Tracing does not change
    the retrieval.
  - **Evaluation.** Reports gain a KG attribution section per subject: the
    cases whose citation the graph caused or cost, and expansion specificity
    (the mean Jaccard similarity of the expanded-concept sets across cases).
    `evaluate_rag.py --trace` keeps the traces and explains each of those
    cases; `compare_evals.py` names the first stage where a traced flip
    starts. The re-scoring fixture gains the new summary field; scores are
    unchanged.

### Changed

- Concepts in a question are resolved against the subject's concept names and
  their stored aliases
  ([#212](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/212)).
  - **What matches:** "GDP" now finds "Gross Domestic Product", "recessions"
    finds "Recession", and "the Stamp Act of 1765" finds "Stamp Act".
  - **What no longer matches:** a single generic word, so "war" no longer
    pulls in "Civil War" and "American" no longer pulls in "American River".
  - **Ambiguity:** an alias shared by several concepts is left out of the
    expansion.
  - **Reporting:** `/ask`, `/ask/stream` and `/retrieve` report each span and
    what it resolved to as `resolved_terms`.
- KG expansion feeds the keyword channel only
  ([#282](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/282)).
  It used to append every recognised concept and all their graph neighbours
  (a median of 21 terms, led by the same hub concepts on most questions) to the
  text that drove both BM25 and the query embedding, which lowered citation
  hits below plain retrieval. Now the kNN channel embeds the question, BM25
  gets the question plus the recognised concepts, and the neighbours come back
  as `related_concepts` in `/ask`, `/ask/stream` and `/retrieve`.
  `RAG_KG_EXPANSION_MAX_NEIGHBOURS` (default 0) adds some of them to the
  keyword query, and reports record it.
- The AI Tutor's Knowledge graph panel lists the concepts used for retrieval
  and, separately, the related concepts (the first eight, then "Show N more"),
  and View on Graph highlights both. Compare explains how expansion works now
  instead of claiming that it adds prerequisite and related concepts.
- The case hash leaves out `stratum` and `split`, so every case keeps the hash
  it had in version 2 and earlier reports stay comparable.
- RELATED edges link each concept to its strongest associations
  ([#291](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/291)):
  - **Scoring.** A pair of concepts is scored by normalised pointwise mutual
    information over paragraphs, no longer by a raw count of five shared
    paragraphs. A pair needs two shared paragraphs (`KG_COOCCURRENCE_THRESHOLD`
    keeps that meaning; its default drops from 5 to 2). Each concept chooses
    its 8 strongest partners (`--related-top-k`, `KG_RELATED_TOP_K[_<SUBJECT>]`),
    and no concept gets more than 24 RELATED edges. The edge weight is the
    score, and the edge records the method and the shared paragraph count.
  - **Seeded books.** In US History, concepts without concept edges fall from
    40% to 8%, and "American Revolution" has related concepts and enters
    `/graph`'s top 100. In Economics, the largest hub falls from 127 neighbours
    to 37 (RELATED plus glossary PREREQ edges), and "Price" leads with
    "Quantity Demanded" and "Demand Curve" instead of "Aggregate Demand" and
    "Asset".
  - **Neighbour order.** Graph neighbours, and so `related_concepts`, follow
    RELATED and PREREQ edges only and come strongest association first;
    neighbours linked only as prerequisites follow, by importance. "Demand"
    now leads with "Supply", "Elasticity" and "Demand Curve", where it led
    with "Price", "Firm" and "Market".
  - **Build report.** It records the builder's parameters, the share of
    concepts without concept edges and the median degree.

### Fixed

- Graph builder quality
  ([#213](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/213)):
  - **Numbered names.** YAKE never ends a keyword with "I" or "II", so both
    world wars were one concept, "World War". A keyword the text mostly
    follows with a Roman numeral now becomes each numbered name ("World War
    I", "World War II"), in the graph and in questions, so "World War II" in
    a question no longer also matches "World War I".
  - **Headings.** Title Case lines (headings, captions, table labels) no
    longer count in the statistics that decide whether a single word is a
    proper noun.
  - **Name fragments.** A single word marked as a key term only with the
    `no-emphasis` class, and mostly written as part of a longer name, is
    judged as an ordinary keyword. "Townshend" (from "Charles Townshend")
    leaves the US History graph. Unemphasised terms such as "Stamp Act"
    stay key terms.

  On the seeded books, US History swaps "World War" and "Townshend" for "World
  War I" and "World War II"; Economics keeps the same 200 concepts. Four
  pending golden cases cover the world wars, the end of the Cold War and GDP.
- Hosted Claude 5.x models through Anthropic's OpenAI-compatible endpoint
  answered every request with HTTP 400 ("`temperature` is deprecated for this
  model"), so answers, quizzes, recommendations and graph queries all failed
  with 503. `OPENROUTER_SEND_TEMPERATURE=false` leaves `temperature` out of
  remote requests; the default (`true`) keeps today's behaviour.

## [0.3.0] - 2026-10-29

The first tagged release: the open-source quality sprint
([#105](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/105))
and the first wave of the domain-at-a-time program, released through
[#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104).
The README's evaluation table reports the first valid run of the golden set
(version 2, 53 cases) as per-arm rates with win/tie/loss counts; see
`docs/evals/README.md`, "Reporting a comparison", for how to read it.

### Changed

- The tribunal suite, the Playwright E2E suite, the offline link check and
  shellcheck are now required checks: `All Checks Passed` fails when any of
  them does. The full osv-scanner scan and `npm audit` stay advisory, because
  a newly published advisory would otherwise block unrelated pull requests
  ([#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104)).
- On Linux x86_64 the lock now takes torch from the PyTorch CPU index
  (`pytorch-cpu`, an explicit source in `pyproject.toml`; wheel `2.10.0+cpu`)
  instead of the PyPI wheel, which pulled the CUDA 12.8 runtime (fifteen
  `nvidia-*` wheels, several GB) that CI and the CPU image never used. Every
  other platform keeps PyPI. CI asserts after each install that torch is not a
  CUDA build and no `nvidia-*` wheel is present, and the runner disk-cleanup
  workaround is gone. The GPU image reinstalls the same torch version from the
  PyTorch CUDA 12.8 index after `poetry install`; Linux machines with a GPU do
  the same (see CONTRIBUTING.md) ([#205](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/205), [#79](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/79)).
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

- Every knowledge-graph build writes a graph quality report to
  `data/processed/build/graph_report_<subject>.md`: the concept count with the
  shares that carry a glossary definition, aliases or a single-word name,
  relationship counts by type and provenance, the top 20 concepts by degree, a
  PREREQ cycle check and the 20 concepts mentioned in the fewest modules (noise
  candidates). `scripts/build_knowledge_graph.py --no-persist` writes the JSON
  copy and the report without Neo4j. `GET /api/v1/demo/provenance` adds
  per-subject `prereq_count` and `definition_count`, read in the same query as
  the concept count, so evaluation reports carry them ([#204](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/204)).
- Evaluation reports carry a paired KG-versus-plain comparison
  (`summary.paired`): per metric, the cases where KG mode did better, the same
  or worse, the discordant pairs and an exact two-sided sign test, plus an
  overall per-case verdict. `latest.md` prints them as a table, and
  `make eval-compare` prints the same counts for head versus base (`--json`
  exposes them as `paired` and `within_run`); its regression gates are
  unchanged. `docs/evals/README.md` sets the wording rule for the README table
  and release notes: per-arm rates plus win/tie/loss, no "beats by X %" and no
  delta column
  ([#203](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/203)).
- `scripts/rescore_eval.py` (`make eval-rescore REPORT=…`) re-scores an
  evaluation report from the answers and sources it stores, using the golden
  set named in its provenance, and prints the metrics the current scorer
  changes; `--check` exits 1 when any did and `--out` writes the re-scored
  report. Reports gain `answer_term_recall_non_echo`, term recall over the
  expected terms the question does not already name (93 of the 197 expected
  terms occur in their own question), which is the recall figure to quote
  ([#202](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/202)).
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

- The optional `pyirt` and `pybkt` dependency groups (`py-irt` and `pyBKT`
  from git, Python 3.11 only). Nothing imported them: mastery uses the
  in-tree BKT update. `poetry install` no longer needs
  `--without pyirt,pybkt` ([#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104)).
- The stale `data/processed/knowledge_graph_us_history.json` and
  `knowledge_graph_economics.json` (2.9 and 3.4 MB, built before the current
  builder: no PREREQ edges, definitions or aliases, and noise concepts such as
  "Data-Type"). Nothing read them. `make seed` builds the graph from
  `books_<subject>.jsonl` and writes its JSON copy and report to the ignored
  `data/processed/build/`, and the pattern is now gitignored ([#204](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/204)).
- Unused Python dependencies
  ([#93](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/93)).
  Recreate an existing virtual environment after upgrading
  (`poetry env remove --all && poetry install`, then
  `make quickstart` to reinstall the spaCy model); syncing it in place can
  break `import spacy`. See CONTRIBUTING.md, "Upgrading an existing checkout".
- `.env.demo` is no longer tracked. Copy `.env.demo.example` instead
  ([#99](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/99)).

### Fixed

- The Docker images now report the package version (`app_version`, the
  OpenAPI `info.version` and `GET /api/v1/demo/provenance`). Both Dockerfiles
  register the project after copying its sources, where the images used to
  report `0.0.0+unknown`; the Docker Build workflow checks the version the
  built image reports ([#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104)).
- The evaluation's refusal detector no longer counts the phrase "provided
  context" as a refusal: the subject prompts tell the model to answer from
  "the provided context", so answers to the unsupported-claim cases that
  began "Based on the provided context, ..." scored as refusals. A refusal
  now has to name what is missing (the context does not contain or mention
  it, not enough information, cannot be answered from the context).
  Unsupported refusal rates in reports from before this change are not
  comparable; re-score them with `scripts/rescore_eval.py`
  ([#202](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/202)).
- When Neo4j or OpenSearch cannot start because a host port is taken,
  `make quickstart`, `make up`, `make seed` and `make doctor` now name the
  container (with its image and compose project) or the process that holds it,
  and how to free it, instead of only pointing at the container logs. A
  container left by a checkout from before the compose project rename (project
  `compose`) is called out.
- An `.nvmrc` now pins the same Node version as `.node-version`, so
  `nvm install` and `nvm use` pick it up (nvm does not read `.node-version`).
  When the Node check in `make quickstart`, `make doctor` or
  `make demo-client-check` fails, its hint names the command for fnm, nvm and
  Volta instead of claiming that all three read `.node-version`.
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

[Unreleased]: https://github.com/MysterionRise/adaptive-knowledge-graph/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/MysterionRise/adaptive-knowledge-graph/releases/tag/v0.3.0
