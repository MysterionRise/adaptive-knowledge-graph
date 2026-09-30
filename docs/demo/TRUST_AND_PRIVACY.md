# Trust And Privacy Notes

This document supports a controlled local client demo. It is not a legal
compliance certification.

## Demo Data Posture

- The first client demo uses OpenStax content only.
- Demo learner profiles are synthetic.
- No real student PII is required.
- Local-only LLM mode is the default.
- Remote LLM fallback is not part of the main client demo.

## Data Flow

```text
Browser
  -> FastAPI
      -> Neo4j for concept graph and prerequisite traversal
      -> OpenSearch for lexical/vector retrieval
      -> Ollama for local answer and quiz generation
      -> SQLite for synthetic learner mastery
```

## Education Privacy Caveats

- FERPA/COPPA/GDPR readiness requires client-specific legal and security review.
- A production pilot needs role boundaries, tenant isolation, retention policy,
  deletion workflow, audit logs, and subprocessors documented.
- Student data should not be sent to remote model providers without explicit
  approval and contractual review.

## AI Safety Controls In Demo

- Answers are instructed to use only retrieved source context.
- Citations are returned with each answer.
- The golden eval set includes unsupported claims and prompt-injection attempts.
- `/demo-status` reports whether the latest eval is valid before rehearsal.

## Accessibility Target

The client-facing target is WCAG 2.2 AA. The current demo UI should be treated
as a prototype until keyboard navigation, contrast, screen-reader behavior, and
responsive layouts are formally audited.

## Claims To Use

- Controlled local demo.
- OpenStax-based prototype.
- Synthetic learner data.
- Local-first architecture.
- Evaluation-backed KG-RAG experiment.

## Claims To Avoid

- FERPA compliant.
- COPPA compliant.
- Production-ready.
- Certification-grade assessment.
- Psychometrically validated difficulty.
- Hallucination-free answers.
