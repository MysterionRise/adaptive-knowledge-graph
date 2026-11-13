# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - YYYY-MM-DD

<!-- FILL (release date: replace YYYY-MM-DD in the heading above with the day v0.4.0 is tagged, and give date-released in CITATION.cff the same date) -->

Evidence and graph quality
([#164](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/164)).
The evaluation now follows a frozen protocol (`docs/evals/protocol.md`):
golden set version 3 has strata, a rehearsal split for development and a final
split that runs only at a release gate, and each report generates the one
comparative sentence a release may quote. Retrieval and the graph changed
where the per-case results of the v0.3.0 run pointed
([#282](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/282)).

### Evidence

<!-- FILL (one paragraph on the final-split run, from the header and "Provenance" of docs/evals/latest.md: its date, commit, split and number of cases, answer model with temperature and seed, and the snapshot file under docs/evals/history/; a valid report means every request returned 200 and no KG expansion failed; list any "Protocol deviations" the report names. This section is written for a run of the final split alone, 29 cases. A run of every case, which is what "make demo-eval" does, reports "Summary", "Paired comparison", the stratum rows of "Intervals" and "KG attribution" over all 57 cases: say so in this paragraph, and take the bar rows, the meaning and distribution rates and the KG losses below from the results whose "split" is "final" in docs/evals/latest.json) -->

The README's evaluation table reports the same run as per-arm rates with
win/tie/loss counts.

The primary endpoint is the KG-minus-plain citation hit rate over the 27
final-split cases that name expected sources. The report generates its
sentence (`summary.primary_endpoint.claim`), quoted as written:

<!-- FILL (the sentence under "Primary endpoint" in docs/evals/latest.md, as a block quote; add no other comparative claim) -->

The bar the protocol sets for the KG arm on the final split:

| Stratum | Bar | KG result |
| --- | --- | --- |
| `single_hop` | citation hit rate ≥ 0.80, at least 9 of 11 | <!-- FILL (KG citation hits out of 11, then "met" or "missed". "Intervals" in docs/evals/latest.md prints rates, not hit counts: multiply the KG rate of its single_hop row by that row's "With sources" count, which is kg times pairs under summary.intervals.strata.single_hop.citation_hit in latest.json) --> |
| `multi_hop` | citation hit rate ≥ 0.60, at least 5 of 8 | <!-- FILL (KG citation hits out of 8, then "met" or "missed": the KG rate of the multi_hop row of "Intervals" times that row's "With sources" count) --> |
| `unanswerable` | every case refused, 2 of 2 | <!-- FILL (KG refusals out of 2, then "met" or "missed": kg_unsupported_refusal_rate under "Summary" times 2, in a report of the final split alone) --> |
| `adversarial` | every injection resisted, 2 of 2 | <!-- FILL (KG injections resisted out of 2, then "met" or "missed": kg_prompt_injection_resistance_rate under "Summary" times 2, in a report of the final split alone) --> |

`meaning` (2 cases) and `distribution` (4 cases) have no bar and are reported
only:
<!-- FILL (the KG and plain citation hit rates of the meaning and distribution rows of "Intervals" in docs/evals/latest.md) -->

KG citation losses are the final-split cases where plain retrieval cites an
expected source and KG retrieval does not:

<!-- FILL (one bullet per "KG loss" line under "KG attribution" in docs/evals/latest.md, from a run that kept its traces: the case id and the explanation its trace gives; or the sentence "None on this run.") -->

### Upgrading

From 0.3.0, with data seeded by that release:

- **Python 3.11.5 or later.** 3.11.0 to 3.11.4 are no longer supported: the
  fixed `soupsieve` releases need 3.11.5
  ([#326](https://github.com/MysterionRise/adaptive-knowledge-graph/pull/326)).
  With an environment that still runs an older 3.11, `poetry install` and
  `poetry run` stop with "Current Python version (3.11.x) is not allowed by
  the project". Install 3.11.5 or later, then recreate the environment:
  `poetry env remove --all`, `poetry install` and `make quickstart`, which
  puts the spaCy model back (CONTRIBUTING.md, "Upgrading an existing
  checkout"). `poetry env use <python>` alone is not always enough: with a
  later 3.11 it can keep an environment in Poetry's default location on the
  old interpreter. Python 3.12 and 3.13 are unaffected.
- **Rebuild the graph of both seeded subjects.** The concepts
  ([#213](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/213))
  and the RELATED edges
  ([#291](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/291))
  changed, and `make seed` skips a subject that already has a graph. Run
  `make build-kg SUBJECT=us_history` and `make build-kg SUBJECT=economics`,
  and answer `yes` when the build asks whether to clear the existing data (in
  a script: `poetry run python scripts/build_knowledge_graph.py --subject <id> --clear`).
  Without clearing, the build merges into the old graph, so removed concepts
  such as "World War" and the old RELATED edges stay. Then restart the API,
  which caches each subject's concept names and aliases for 5 minutes.
- **No re-index.** Ingestion, chunking and the OpenSearch index mapping are
  unchanged, so the stored embeddings stay. The lock moves
  sentence-transformers from 6.1 to 6.2 and transformers from 5.20 to 5.22:
  after `poetry install`, `make doctor` fails when an index no longer matches
  the installed embedding stack, and `make embedding-parity SUBJECT=…`
  compares stored vectors with new ones.
  <!-- FILL (embedding parity measured in the release session: the min cosine that "make embedding-parity SUBJECT=us_history RERANKER=1" and "make embedding-parity SUBJECT=economics RERANKER=1" print for an index built by 0.3.0, as one sentence. The maintainer's comment of 2 November on pull request #278 records the same check for these lock versions, without the reranker check: cite it if the session does not repeat the measurement) -->
- **Window retrieval.** Clearing a subject's graph also removes its Chunk
  nodes and NEXT edges. If you use `VECTOR_BACKEND=neo4j` or `hybrid`, run
  `make build-windows SUBJECT=…` again after the rebuild.
- **`KG_COOCCURRENCE_THRESHOLD`.** It still sets how many paragraphs two
  concepts must share, but its default is now 2 (it was 5), and reaching it no
  longer creates a RELATED edge by itself: each concept chooses its 8
  strongest partners (`KG_RELATED_TOP_K`), and no concept gets more than 24
  RELATED edges. Review a value you set for 0.3.0, also as
  `KG_COOCCURRENCE_THRESHOLD_<SUBJECT>`; the graph report of each build
  records the parameters and the share of concepts without concept edges.
- **API responses.** `/ask`, `/ask/stream` (in the `metadata` event) and
  `/retrieve` gain `related_concepts` and `resolved_terms`.
  `expanded_concepts` now lists only the concepts the retrieval used; the
  graph neighbours it used to include are in `related_concepts`. `/retrieve`
  also returns a `trace` unless the request sets `"include_trace": false`;
  `/ask` has the field too, `null` unless the request sets
  `"include_trace": true`, and the `metadata` event of `/ask/stream` carries
  it only then.
  `/quiz/generate-adaptive` and `/student/target-difficulty` gain `decision`:
  the decision record of the policy that picks the difficulty (`band-v1`),
  with its `record_id` and `decided_at`. `decided_at` is the time of the
  decision, so two identical `/student/target-difficulty` requests no longer
  return identical bodies
  ([#306](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/306)).
  `/demo/provenance` lists `rag_kg_expansion_max_neighbours` under
  `retrieval`.
- **torch.**
  <!-- FILL (the #207 decision: replace if #207 lands before the tag; this item then says torch 2.13, the CUDA 13 GPU image with the driver and macOS versions it needs, and that both entries left osv-scanner.toml) -->
  torch stays on 2.10 (`>=2.10.0,<2.11` in `pyproject.toml`), and the GPU
  image stays on CUDA 12.8. The two torch advisories allowlisted in
  `osv-scanner.toml` (GHSA-rrmf-rvhw-rf47, fixed in torch 2.13, and
  PYSEC-2026-139, fixed from 2.11) keep their entries and their expiry,
  2026-12-31. Both are local-only and concern features the code does not use
  (`torch.jit.script` and loading `.pt2` archives), which a unit test checks.
  The upgrade to torch 2.13 and a CUDA 13 image
  ([#207](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/207))
  merges right before the re-seed planned for v0.5.0
  ([#215](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/215)),
  before the entries expire.

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
- `make release-check TAG=vX.Y.Z` and a gate in the Release workflow
  ([#253](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/253)).
  `scripts/release_check.py` runs offline with the standard library only and
  exits 1, naming the file and the problem, unless:
  - **Versions.** `pyproject.toml`, `frontend/package.json`,
    `frontend/package-lock.json` and `CITATION.cff` agree with each other and
    with the tag.
  - **Changelog.** `CHANGELOG.md` has one dated section for the version, with
    a body and a link reference that ends with the tag, and `CITATION.cff`
    carries the same date.
  - **Placeholders.** No `FILL (` HTML comment is left in `README.md` or
    `CHANGELOG.md`.
  - **Evidence.** `docs/evals/latest.json` passes the `check_demo_eval.py`
    rules and has its byte-identical snapshot in `docs/evals/history/`.
  - **Assets.** `docs/assets/demo/` holds at least one image.

  The Release workflow runs it on the tag's tree before it creates the
  release; tags that predate the script skip it with a notice. The check
  accepts only `vX.Y.Z`, so the workflow no longer publishes a pre-release
  tag such as `v0.4.0-rc.1` of a tree that has the script. See
  [docs/TESTING.md](docs/TESTING.md#release-check).
- A policy interface with decision records
  ([#306](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/306)):
  - **Policies.** `backend/app/student/policy/` holds a policy protocol (`id`,
    `version`, `decide(state, context)`) and a registry (`get_policy`). The
    rule that picks the quiz difficulty is now the policy `band-v1`, with the
    same boundaries: easy below 0.4 mastery, medium up to 0.7, hard above.
    `StudentProfile.get_target_difficulty` is a shim over it, and the quiz
    prompts are unchanged. `frontend/lib/mastery.ts` and
    `scripts/seed_student_profile.py` still hold their own copies of the rule.
  - **Decision records.** A decision returns a record: the policy id and
    version, the action, the learner state and context the policy read, and
    the graph edges it used with their provenance. `band-v1` reads the asked
    concept and that concept's mastery level (the initial mastery if it has no
    history) and nothing else. The record keeps the mastery unrounded. It
    holds no time and no random id. Two records are equal exactly when their
    canonical JSON is equal, and `record_id` is a digest of that JSON, so
    equal records have the same id.
  - **Responses.** `POST /api/v1/quiz/generate-adaptive` and
    `GET /api/v1/student/target-difficulty` gain a `decision` field with the
    record, its `record_id` and `decided_at`, the time of the decision in UTC,
    which is not part of the record.
- `docs/adaptivity/README.md`, a design note on what the project may call
  adaptive
  ([#313](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/313)).
  It defines two labels, "adaptive" and "beneficial", and the tests behind
  them, says what the code does today (no behaviour passes them yet), sums up
  the research, and sets out a learner track: a simulator first, then
  server-side evidence, then feedback. It proposes keeping the textbook's
  question sections, which carry their answer keys, out of retrieval in the
  re-seed
  ([#215](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/215)).
  `ROADMAP.md` gains the track.

### Changed

- **Breaking:** the minimum Python is 3.11.5 (it was 3.11.0); 3.12 and 3.13
  are unaffected. The fixed releases of `soupsieve`, which Beautiful Soup uses
  in `scripts/ingest_books.py`, need 3.11.5: a re-lock with the old floor
  moves only Python 3.13 to a fixed release and keeps the vulnerable 2.10 for
  3.11 and 3.12. The lock now has `soupsieve` 4.1 for every Python
  (GHSA-6655-6qjp-jx7x, GHSA-7g44-g9rc-x53w, GHSA-mmhr-3c5m-f64f) and
  `opentelemetry-api` 1.45.2 (GHSA-mf5v-w3w3-f6cg). No other locked version
  changes. Poetry no longer uses Python 3.11.0 to 3.11.4 for the project:
  with an environment built on one of them, `poetry install` stops with an
  error. Install 3.11.5 or later, then recreate the environment
  (CONTRIBUTING.md, "Upgrading an existing checkout"); `poetry env use
  <python>` alone can leave the old environment in place.
- `check_demo_eval.py`, and so `make demo-eval` and `make demo-client-check`,
  rejects a report whose API app version differs from the version in
  `pyproject.toml`
  ([#253](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/253)).
  After a version bump, run `poetry install` (or rebuild the image) and
  restart the API before evaluating.

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
- The README, the demo documents and the slides follow the two-label wording
  of `docs/adaptivity/README.md`
  ([#210](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/210)):
  - **Wording.** They no longer present the quizzes or the practice as
    adaptive. They describe what the code does instead: the quiz prompt asks
    for a difficulty band taken from a mastery estimate, BKT with fixed,
    unfitted parameters updates that estimate from answers graded in the
    browser, and neither the delivered difficulty nor the estimate is
    validated. Interface strings are unchanged.
  - **Gate.** `backend/tests/test_adaptivity_wording.py` fails, with file and
    line, when a never-say phrase of the note, "auto-targets" or "adaptive
    quizzes" appears in `README.md`, `docs/demo/` or `demo-slides/`. A
    sentence that says the thing is not done passes only as an exact, listed
    sentence. Other uses of the word "adaptive" are not gated.
  - **Design note.** The note (new in this release, see "Added") lists the
    interface strings that remain.
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
- `follow-redirects` 1.16.2 in the frontend lock (GHSA-mrwp-f3q8-3g9p); it
  comes in through `axios`. Three advisories in dev-only frontend tooling
  (`deepmerge`, `glob`, `minimatch`) have no fix the tooling can use and are
  allowlisted in `frontend/osv-scanner.toml` until 2027-01-31
  ([#279](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/279)).
- The `braces` entry is gone from `frontend/osv-scanner.toml`
  ([#166](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/166)).
  GitHub withdrew GHSA-vfj7-8cjw-p6xm on 23 October 2026 as not practically
  exploitable, so osv-scanner no longer reports it for `braces` 3.0.3 and
  listed the entry as an unused ignore. `SECURITY.md` no longer names it as an
  accepted risk.

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

[Unreleased]: https://github.com/MysterionRise/adaptive-knowledge-graph/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/MysterionRise/adaptive-knowledge-graph/releases/tag/v0.4.0
[0.3.0]: https://github.com/MysterionRise/adaptive-knowledge-graph/releases/tag/v0.3.0
