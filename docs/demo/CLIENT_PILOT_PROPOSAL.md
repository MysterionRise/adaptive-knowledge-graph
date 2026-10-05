# Pilot Outline

A template for a small, time-boxed pilot of Adaptive Knowledge Graph with a
partner organisation. Adjust it to the partner's content and goals.

## Pilot thesis

Use a limited slice of approved educational content to test whether
KG-grounded tutoring, citation traceability and adaptive practice make AI
learning experiences easier to review and more useful.

## Recommended shape

- **Duration:** 4–6 weeks.
- **Content:** one OpenStax-style course module, or one sample provided by the
  partner with written permission.
- **Users:** internal reviewers, instructors, authors or a small consented
  learner cohort.
- **Deployment:** local or private staging, no public launch.
- **LLM mode:** local-only (`PRIVACY_LOCAL_ONLY=true`) by default.
- **Learner IDs:** pseudonymous only (for example `pilot-017`), never names,
  emails or student numbers, until per-learner identity lands
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
  Until then anyone who can load the frontend can read or change any learner
  profile, because the frontend's API key is public.

## Workstreams

1. Content onboarding
   - Confirm source rights and attribution.
   - Normalize chapters and sections.
   - Build the concept graph and the retrieval index.

2. Learning experience
   - Grounded Q&A with citations.
   - Graph exploration.
   - Adaptive quiz generation.
   - Post-quiz remediation and advancement recommendations.

3. Review workflow
   - Human review of generated questions.
   - Flag unsupported or low-confidence answers.
   - Track content gaps and confusing concepts.

4. Evaluation
   - 50–100 golden QA cases.
   - Citation hit rate and expected-source MRR.
   - Unsupported-question refusal rate.
   - Latency and local hardware notes.

## Success metrics

- At least 90% of answerable pilot questions return a citation.
- Unsupported and prompt-injection cases are refused or safely redirected.
- Reviewers can trace generated answers to approved source sections.
- Authors find useful insights about content gaps or remediation.
- The local demo can be reset and replayed without manual database repair.

## Responsibilities

Project team:

- Provide the ingestion pipeline, the KG-RAG service, the demo UI, the
  evaluation harness and a pilot report.
- Keep local-only mode as the default and document any use of remote services.

Pilot partner:

- Provide approved content, or confirm an OpenStax-only scope.
- Supply subject-matter reviewers.
- Define success criteria and excluded use cases.

## Explicit non-goals

- No production processing of student data without a privacy and security
  review.
- No certification issuance.
- No proctoring.
- No calibrated IRT claims without learner response data.
- No LMS or LTI integration unless the pilot scope requires it.
