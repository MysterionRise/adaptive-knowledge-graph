# Security Policy

Adaptive Knowledge Graph is a proof of concept and pilot prototype. It is built
to run on one machine for a single user or a small trusted team. Please read the
[threat model](#threat-model) before you deploy it anywhere else.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.3.x | Yes |
| < 0.3 | No |

Security fixes land on `main` and ship in the latest 0.3.x release.

## Reporting a vulnerability

Please do **not** report security problems in public issues, discussions or
pull requests.

Report them privately through GitHub:
<https://github.com/MysterionRise/adaptive-knowledge-graph/security/advisories/new>

Please include:

- the affected version or commit and component (API route, script, frontend page, Compose file)
- steps to reproduce or a proof of concept
- the impact you expect (for example data exposure, code execution, denial of service)
- any fix or mitigation you suggest

This is a small project maintained in spare time, so responses are best effort.
We will acknowledge the report as soon as we can, keep you updated in the
private advisory, and credit you in the advisory and release notes if you want.
Please give us a reasonable amount of time to release a fix before you disclose
the issue publicly.

## Threat model

The project is local-first:

- The Docker Compose stack binds every published port (Neo4j, OpenSearch and
  the optional API and frontend containers) to `127.0.0.1` and ships
  development credentials. Do not expose these ports to other hosts.
- Learner profiles are stored in a local SQLite file, and the demo uses
  synthetic profiles. There is no user identity or tenancy model yet
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
- With `PRIVACY_LOCAL_ONLY=true` (the default) the API refuses to start unless
  `LLM_MODE=local`, so questions, retrieved passages and prompts go only to the
  local Ollama server.
- `APP_ENV=development` (the default) runs without an API key and logs a
  warning at startup. It is meant for a single developer machine.

In scope: vulnerabilities in this repository's code, container images, Compose
files and scripts, including problems that let a remote caller bypass
`APP_ENV=production` protections.

Out of scope: running the development configuration on an untrusted network,
problems in upstream services (Neo4j, OpenSearch, Ollama) or models that you
configure yourself, and the known limitations listed below.

## Hardening a shared deployment

If anyone other than you can reach the API, run it in production mode:

1. Set `APP_ENV=production` and a long random `API_KEY`, for example from
   `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. In
   production mode the API refuses to start without a key of at least 16
   printable ASCII characters (no surrounding whitespace), and the protected
   routes (`/student/*`, `/quiz/generate-adaptive`, `/quiz/recommendations`,
   `/graph/query`) require it
   in the `X-API-Key` header.
2. Keep the interactive API docs off. In production mode `/docs`, `/redoc` and
   `/openapi.json` are disabled unless you set `API_DOCS_ENABLED=true`.
3. Set `CORS_ORIGINS` to your frontend origin. `CORS_ALLOW_METHODS` and
   `CORS_ALLOW_HEADERS` default to short allow-lists, and production mode
   refuses to start if any of the three contains `*`.
4. Keep `PRIVACY_LOCAL_ONLY=true` and `LLM_MODE=local` unless you have approved
   sending questions and textbook excerpts to a remote provider.
5. Change the Neo4j and OpenSearch credentials, and keep both databases on
   `127.0.0.1` or a private network.
6. Terminate TLS in a reverse proxy in front of the API, and run the API
   without auto-reload. Set `TRUST_PROXY_HEADERS=true` only if that proxy
   appends the client IP to `X-Forwarded-For` and is the only way to reach the
   API: rate limits are then keyed on the right-most hop. Without it, every
   client behind the proxy shares one rate-limit bucket per endpoint; raise
   `RATE_LIMIT_DEFAULT` if that is too tight.
7. Only load models you trust through `EMBEDDING_MODEL` and `RERANKER_MODEL`.

## Accepted risks

- **Advisories that need a disruptive upgrade.** A small number of published
  advisories can only be fixed by a major-version upgrade or a change of the
  wheel set. They are allowlisted, each with an expiry date and a reason, in
  [`osv-scanner.toml`](osv-scanner.toml) (Python) and
  [`frontend/osv-scanner.toml`](frontend/osv-scanner.toml) (npm), which are the
  source of truth for exactly which advisories are accepted. Every entry
  expires within 90 days and names its issue; a weekly dependency audit flags
  entries 30 days before they expire, and pull requests fail on any advisory
  they add. Each upgrade has its own issue:
  - `transformers` 4.x, including remote-code-execution advisories, until the
    move to transformers 5 and sentence-transformers 6
    ([#71](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/71)).
    Mitigation: the application only loads the pinned `BAAI/bge-m3` embedding
    model and the optional `BAAI/bge-reranker-v2-m3` reranker.
  - `torch` 2.10, for two local-only advisories in features this project does
    not use (`torch.jit.script` and loading `.pt2` archives). The fixed
    releases switch the Linux wheels to CUDA 13, which is deferred to
    [#79](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/79).
  - `braces` 3.0.3, a dev-only dependency of the frontend build and test
    tooling that is not in the production bundle, until a fixed release
    exists
    ([#166](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/166)).
- **`NEXT_PUBLIC_API_KEY` is public.** Next.js compiles every `NEXT_PUBLIC_*`
  variable into the JavaScript bundle, so anyone who can load the frontend can
  read that key. An API key therefore only gates non-browser clients such as
  scripts and `curl`. It does not protect the endpoints that the browser UI
  calls.

## Known limitations

These are tracked in public issues. Please do not report them as new
vulnerabilities:

- No per-learner identity: a caller that passes the API key can read or change
  any learner profile by `student_id`
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
- Quiz answers are sent to the browser and graded client-side, so quiz results
  are not tamper-proof
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).
