# Compliance and Privacy

This document describes how Adaptive Knowledge Graph uses licensed content,
where data flows and what the system stores. It is not legal advice and not a
compliance certification. Anyone who deploys the project for real learners
needs their own legal, privacy and security review.

## OpenStax content

### License

Textbook content comes from [OpenStax](https://openstax.org/) and is licensed
under the [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/)
(CC BY 4.0). Two books are seeded by default:

- [US History](https://openstax.org/details/books/us-history)
- [Principles of Economics](https://openstax.org/details/books/principles-economics-3e)

Biology 2e, Concepts of Biology and World History (Volumes 1 and 2) are
configured in [`config/subjects.yaml`](../config/subjects.yaml) but not seeded
by default. [NOTICE](../NOTICE) lists every configured book, where it is
fetched from, which OpenStax material the repository includes and what was
changed.

### How attribution is kept

- Each subject in `config/subjects.yaml` has an attribution line naming the
  book, the license and a link to the original.
- `/api/v1/ask` and `/api/v1/ask/stream` return that line with every answer,
  and the chat UI displays it. The answer prompt also asks the model to end
  its answer with the attribution.
- The README and `NOTICE` state the license, the changes made to the content
  and the trademark notice.

### How the content is used

- To build a search index (chunks and their embeddings in OpenSearch).
- To extract concepts and relationships for the knowledge graph in Neo4j.
- As context for generated answers and quiz questions.

No model is trained or fine-tuned on OpenStax content.

CC BY 4.0 allows commercial use with attribution. It does not cover the
OpenStax name, logo or book covers.

### Trademark

OpenStax is a trademark of Rice University. This project is not affiliated
with, sponsored by or endorsed by OpenStax or Rice University.

## Privacy modes

### Local-only mode (default)

```bash
PRIVACY_LOCAL_ONLY=true   # default
LLM_MODE=local            # default, and required while PRIVACY_LOCAL_ONLY=true
```

- The API refuses to start if `PRIVACY_LOCAL_ONLY=true` is combined with
  `LLM_MODE=remote` or `LLM_MODE=hybrid`, and while the flag is on no code
  path calls OpenRouter, including the hybrid fallback.
- Every LLM call (answers, quizzes, recommendations and natural-language graph
  queries) goes to the Ollama server at `LLM_OLLAMA_HOST`, which must be local:
  the API refuses to start unless it is `localhost`, the Compose service
  `ollama`, `host.docker.internal`, `host.containers.internal`, a loopback or
  private IP address (RFC 1918, IPv6 ULA; not link-local or carrier-grade NAT)
  or a host name that resolves only to such addresses. It also refuses Ollama
  cloud models (`LLM_LOCAL_MODEL` ending in `-cloud` or `:cloud`), which run on
  ollama.com.
- LangSmith tracing would send questions and textbook context to LangSmith.
  The API refuses to start while `LANGSMITH_TRACING`, `LANGSMITH_TRACING_V2`,
  `LANGCHAIN_TRACING` or `LANGCHAIN_TRACING_V2` is on (in the environment or in
  `.env`), and disables tracing at runtime as well. A CI test sets these
  variables and checks that startup, `/ask` and `/graph/query` (through the
  real LangChain Cypher chain) make no non-loopback connection.
- Neo4j, OpenSearch and the SQLite learner store run on your machine, and the
  Compose file turns Neo4j usage reporting off
  (`dbms.usage_report.enabled=false`).
- The application code sends no telemetry or analytics, and it sets
  `HF_HUB_DISABLE_TELEMETRY=1`.

Third-party tools keep their own network behaviour:

- The embedding model, and the reranker when enabled, are downloaded from
  Hugging Face on first use (`make seed` downloads the embedding model). Ollama
  downloads the LLM when you run `ollama pull`. Once the models the API loads
  are in the Hugging Face cache, the API sets `HF_HUB_OFFLINE=1` at startup and
  makes no Hugging Face requests; until then it stays online so the first
  download works. An `HF_HUB_OFFLINE` you set yourself takes precedence. The
  containerised API has its own cache volume, so its first question downloads
  the embedding model unless you pre-populate that volume.
- The Next.js command-line tool collects anonymous usage telemetry unless you
  run `npx next telemetry disable` or set `NEXT_TELEMETRY_DISABLED=1`.
- The optional presentation in `demo-slides/` loads reveal.js from a CDN.

### Remote mode (opt-in)

```bash
PRIVACY_LOCAL_ONLY=false
LLM_MODE=remote            # or hybrid: Ollama first, OpenRouter as fallback
OPENROUTER_API_KEY=...
```

- Prompts are sent to [OpenRouter](https://openrouter.ai/) and the model
  provider behind it. They contain learners' questions and quiz topics,
  retrieved textbook excerpts and, for natural-language graph queries, the
  graph schema.
- In `hybrid` mode this happens whenever the local call fails, so data can
  leave the machine even though Ollama is the primary model.
- OpenRouter's [privacy policy](https://openrouter.ai/privacy) applies, and it
  may log requests.

Use local-only mode whenever questions, learner data or textbook excerpts must
not leave the deployment boundary.

## What the system stores

| Data | Where | Notes |
| --- | --- | --- |
| Learner profiles | SQLite file `data/processed/student_profiles.sqlite3` (set with `STUDENT_PROFILES_DB`) | Per-concept mastery level, BKT probability, attempt and correct counts, last-assessed timestamps, keyed by `student_id` (default `default`). No names, email addresses or other identifiers are collected. |
| Textbook chunks and embeddings | OpenSearch Docker volume | OpenStax text only |
| Knowledge graph | Neo4j Docker volume | Concepts, modules and their relationships (plus chunk nodes if window retrieval is set up) |
| Evaluation reports | `docs/evals/latest.json` and `latest.md` | Per-case metrics and a summary for the golden-set questions |
| Logs | Standard output; `logs/error.log`; `logs/debug.log` when `DEBUG=true` | See below |

The system has no user accounts. Learner profiles are selected by the
`student_id` parameter, so anyone who can call the API can read or change any
profile ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
Use synthetic profiles, as the demo does, unless you add real access control.

### Logs

- Every request is logged with its method, path, status code, duration and a
  request ID.
- `/api/v1/ask` logs the text of each question at `INFO` level, so questions
  appear on standard output.
- `logs/error.log` keeps errors, rotates at 10 MB and keeps one week of files.
  With `DEBUG=true`, `logs/debug.log` records everything at `DEBUG` level and
  keeps three days.

Check logs for personal data before you share them, for example in a bug
report.

### Deleting data

- Learner profiles: delete `data/processed/student_profiles.sqlite3` or call
  `POST /api/v1/student/reset` for a profile.
- Graph and search data: stop the stack and remove the Docker volumes
  (`docker compose -f infra/compose/compose.yaml down -v`).
- Logs: delete the `logs/` directory.

## Education privacy regulations

FERPA, COPPA, GDPR and similar rules depend on who deploys the system, for
whom and how. The project is not certified against any of them. For a
deployment with real learners, at minimum:

1. Host it yourself and keep `PRIVACY_LOCAL_ONLY=true`.
2. Run in production mode (`APP_ENV=production` with an `API_KEY`) and add
   real per-learner access control first; see [SECURITY.md](../SECURITY.md).
3. Do not put names or other personal data into `student_id` values.
4. Define retention for learner profiles and logs, and review logs for
   personal data.

## Security

- Never commit `.env` files; only the `*.example` templates are tracked.
- Change the default Neo4j and OpenSearch passwords outside local development,
  and keep the database ports on `127.0.0.1` or a private network.
- Generated answers are constrained by the prompt to the retrieved context,
  but prompt instructions are not a security boundary. The evaluation set
  includes prompt-injection and unsupported-claim cases to track this.

See [SECURITY.md](../SECURITY.md) for the threat model, production hardening
and how to report vulnerabilities.

## Questions and updates

Open a [documentation issue](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/new?template=documentation.yml)
for compliance questions or corrections. Report anything sensitive privately
as described in [SECURITY.md](../SECURITY.md).

This document is updated when third-party services, stored data or content
licensing change. Last updated: 2026-09-30. For the full history, run
`git log --follow -- docs/COMPLIANCE.md`.
