# Roadmap

Adaptive Knowledge Graph is a proof of concept and pilot prototype. From
October 2026 the work follows a domain-at-a-time knowledge method: each body
of knowledge (a "domain"; a `subject` in the configuration) goes through one
cycle of define, map, implement and validate, and evidence, correctness and
operational basics stay ahead of broad new features. Work is tracked in
[GitHub issues](https://github.com/MysterionRise/adaptive-knowledge-graph/issues)
with the
[`program`](https://github.com/MysterionRise/adaptive-knowledge-graph/issues?q=is%3Aissue+is%3Aopen+label%3Aprogram)
label and one tracker issue per milestone; issues labelled
[help wanted](https://github.com/MysterionRise/adaptive-knowledge-graph/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
are good places to contribute.

## The method in one paragraph

Answers fail on two information problems: *distribution* (facts spread across
systems and documents) and *meaning* (the same thing under different names,
and the same name for different things). Each domain cycle (1) defines the
taxonomy: golden questions and a reviewed domain dictionary with synonyms;
(2) maps the ontology: a source inventory and relationships grounded in the
sources; (3) implements: the knowledge structure on the real sources, a
conversational layer whose answers trace to their source, and governance with
a person in the loop; (4) validates on unseen questions against an accuracy
bar set before building, then folds the domain in and picks the next one.
`docs/method/` (from v0.6.0) describes the cycle, the vocabulary and the pilot
playbook.

## Done

- The golden evaluation set covers 53 questions across US History and
  Economics, including unsupported-claim and prompt-injection cases.
- The adversarial (tribunal) tests run as their own suite (`-m tribunal`,
  `make test-tribunal`) and CI job, separate from the regular tests.
- Documentation claims about IRT, teacher editing, a mock-data fallback and
  production readiness were removed or corrected.
- The workstreams of the v0.3.0 quality sprint
  ([#105](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/105))
  merged: patched dependencies with both lockfiles scanned in CI, production mode and
  enforced `PRIVACY_LOCAL_ONLY`, read-only graph queries, correct API
  contracts, a one-command local stack, the frontend platform upgrade, a 75%
  backend coverage floor, evaluation provenance and `make eval-compare`,
  transformers 5 and langchain 1.x.
- **v0.3.0, the first tagged release (November 2026,
  [#104](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/104)):**
  a scorer that counts refusals correctly
  ([#202](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/202)),
  per-arm rates with win/tie/loss counts instead of a bare delta
  ([#203](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/203)),
  the stale committed graph files retired
  ([#204](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/204)),
  CPU-only torch in CI
  ([#205](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/205)),
  the first valid evaluation run on golden set v2 reported in the README,
  containers that report their version, and the tribunal, E2E, link-check and
  shellcheck jobs promoted to required checks.

## Now: v0.4.0 (November 2026)

Wave W2, tracked in
[#164](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/164).

- **v0.4.0, tagged by 22 November:** golden set v3 with strata, a
  rehearsal/final split and a frozen protocol
  ([#206](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/206));
  torch 2.13 and the CUDA 13 image, gated on embedding parity
  ([#207](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/207));
  the evidence-state index and the advisory evaluation-delta check
  ([#208](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/208));
  bootstrap intervals and a noise-floor rule
  ([#209](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/209));
  the remaining dev-only frontend advisories re-justified
  ([#166](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/166),
  [#186](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/186));
  the Cypher QA smoke test
  ([#72](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/72)).
  All five advisory allowlist entries are resolved before 31 December 2026.

## Next: v0.5.0, meaning and lineage (December 2026)

Waves W3 and W4, tracked in
[#236](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/236).

- Versioned domain artifacts: dictionary, relationship map and source
  inventory with a validated loader and an idempotent overlay
  ([#211](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/211)).
- Aliases and senses resolved at query time, no more generic-word matching
  ([#212](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/212)),
  and builder fixes
  ([#213](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/213)),
  closing
  [#158](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/158).
- Curated US History and Economics dictionaries, AI-drafted and
  steward-reviewed
  ([#214](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/214)).
- A source inventory with licences and content hashes, chunk-level lineage
  and an origin per citation
  ([#215](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/215)),
  the one planned re-seed.
- A request-scoped answer trace with KG-attributable accounting
  ([#216](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/216)).
- Positioning docs
  ([#217](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/217)),
  learner-state counterfactual tests
  ([#210](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/210))
  and the review log with governance docs
  ([#218](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/218)).

## Next: v0.6.0, showcase domain and playbook (January 2027)

Waves W5 to W7, tracked in
[#237](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/237).

- Local-file connectors
  ([#219](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/219))
  and the `knowledge_base` subject kind
  ([#220](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/220)).
- A synthetic research-and-patent showcase domain with planted meaning and
  distribution conflicts, validated against a bar set before the final run
  ([#221](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/221)).
- The domain-cycle docs
  ([#222](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/222)),
  the pilot playbook with a handover export
  ([#225](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/225)),
  the per-domain validation gate
  ([#224](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/224))
  and the curated prerequisite layer
  ([#223](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/223)).
- "Why these sources?" in the chat and per-domain status on the Demo Status
  page
  ([#226](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/226)),
  structured definitional answers
  ([#227](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/227))
  and the five-step demo narrative
  ([#228](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/228)).

## Later: v0.7.0, assessment integrity and governance (February 2027)

Waves W8 and W9, tracked in
[#238](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/238).

- Quiz topics from the dictionary with concept validation on
  ([#108](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/108));
  server-side grading and an answer-submission endpoint
  ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)).
- The 0 to 4 answer rubric with a calibrated judge
  ([#229](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/229))
  and the quiz quality audit
  ([#230](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/230)).
- The review queue with an append-only audit log
  ([#231](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/231))
  and its page
  ([#232](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/232),
  after
  [#77](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/77)),
  incremental re-ingestion
  ([#233](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/233)),
  platform hygiene
  ([#234](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/234))
  and the decisions-and-limitations case study
  ([#235](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/235)).

## Later: unscheduled

- Per-learner identity, roles and scoped permissions
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)),
  required before any pilot with learners.
- Biology 2e
  ([#75](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/75))
  and World History
  ([#160](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/160))
  as the next textbook domains, run through the playbook; a connector for a
  real public research or patent source as the next knowledge-base domain.
- Async Neo4j and OpenSearch clients
  ([#78](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/78)),
  Python 3.14
  ([#76](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/76)),
  Tailwind 4, OpenTelemetry spans, tenant and cohort data boundaries,
  database migrations and backups, browser tests against a live staging stack.

## Explicit non-goals for now

- No production certification issuance.
- No proctoring.
- No enterprise dashboard until identity, tenancy and audit logging exist.
- No claim that LLM-estimated difficulty equals psychometric calibration.
- No "expert-validated" claim for a domain without a recorded steward review.
- No accuracy figure without a final-split run on the published golden set.
- No "enterprise-ready", multi-tenant or compliance claim.
- "Living" means re-ingestion on demand; there is no automatic source sync.
- No claim that the knowledge graph improves answers in general: only
  per-domain, per-case deltas, with the cases where it was worse listed.
