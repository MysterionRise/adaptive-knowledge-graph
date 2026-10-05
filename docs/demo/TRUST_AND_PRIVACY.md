# Trust and Privacy Notes for the Demo

This page supports a local demo. It is not a legal compliance certification.
The full data-handling description is in
[docs/COMPLIANCE.md](../COMPLIANCE.md), and the threat model is in
[SECURITY.md](../../SECURITY.md).

## Demo data posture

- The demo uses OpenStax content only.
- Demo learner profiles are synthetic.
- No real student data is needed.
- Local-only LLM mode is the default: with `PRIVACY_LOCAL_ONLY=true` the API
  refuses to start in a remote LLM mode, with a remote or cloud Ollama, or with
  LangSmith tracing on.
- **Pseudonymous learner IDs only** until per-learner identity lands
  ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)).
  The frontend's API key is public, so anyone who can load the frontend can
  read or change any learner profile. Never use names, emails or student
  numbers as learner IDs.
- Remote LLM providers are not part of the demo.

## Data flow

```text
Browser
  -> FastAPI
      -> Neo4j for the concept graph and prerequisite traversal
      -> OpenSearch for lexical and vector retrieval
      -> Ollama for local answer and quiz generation
      -> SQLite for synthetic learner mastery
```

## Education privacy caveats

- The project is designed so learner data stays on the machine, but it has no
  compliance certification. Readiness for FERPA, COPPA, GDPR or similar rules
  requires a legal and security review of the specific deployment; see
  [COMPLIANCE.md](../COMPLIANCE.md).
- A production pilot needs role boundaries, tenant isolation, a retention
  policy, a deletion workflow, audit logs and a documented list of
  subprocessors.
- Student data should not be sent to remote model providers without explicit
  approval and a contractual review.

## AI safety controls in the demo

- The prompt instructs the model to use only the retrieved source context.
- Every answer returns its citations.
- The golden evaluation set includes unsupported claims and prompt-injection
  attempts.
- `/demo-status` reports whether the latest evaluation is valid before a
  rehearsal.

## Accessibility target

The target is WCAG 2.2 AA. Treat the current UI as a prototype until keyboard
navigation, contrast, screen-reader behaviour and responsive layouts have been
formally audited.

## Claims that are accurate

- Local demo.
- OpenStax-based prototype.
- Synthetic learner data.
- Local-first architecture: designed so learner data stays on the machine.
- Evaluation-backed KG-RAG experiment.

## Claims to avoid

- Any regulatory compliance or certification (FERPA, COPPA, GDPR). There is
  no compliance certification.
- Production-ready.
- Certification-grade assessment.
- Psychometrically validated difficulty.
- Hallucination-free answers.
