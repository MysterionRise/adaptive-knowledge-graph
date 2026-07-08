# Client Pilot Proposal

## Pilot Thesis

Use a limited slice of approved educational content to validate whether
KG-grounded tutoring, citation traceability, and adaptive practice improve the
reviewability and usefulness of AI learning experiences.

## Recommended Pilot Shape

- Duration: 4-6 weeks.
- Content: one OpenStax-style course module or one client-provided sample under written permission.
- Users: internal reviewers, instructors, authors, or a small consented learner cohort.
- Deployment: local or private staging, no public launch.
- LLM mode: local-first by default.

## Workstreams

1. Content onboarding
   - Confirm source rights and attribution.
   - Normalize chapters/sections.
   - Build concept graph and retrieval index.

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
   - 50-100 golden QA cases.
   - Citation hit rate and expected-source MRR.
   - Unsupported-question refusal rate.
   - Latency and local hardware notes.

## Success Metrics

- At least 90% of answerable pilot questions return a citation.
- Unsupported and prompt-injection cases are refused or safely redirected.
- Reviewers can trace generated answers to approved source sections.
- Authors identify useful content-gap or remediation insights.
- Local demo can be reset and replayed without manual database repair.

## Responsibilities

Project owner:

- Provide ingestion pipeline, KG-RAG service, demo UI, evaluation harness, and pilot report.
- Maintain local-only default and document any remote-service use.

Client:

- Provide approved content or confirm OpenStax-only evaluation scope.
- Supply subject matter reviewers.
- Define pilot success criteria and excluded use cases.

## Explicit Non-Goals

- No production student-data processing without privacy/security review.
- No certification issuance.
- No proctoring.
- No calibrated IRT claims without learner response data.
- No LMS/LTI integration until a pilot scope requires it.
