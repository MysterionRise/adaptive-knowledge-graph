# Demo Asset Capture Checklist

Use this after `make demo-client-check` passes on a live local stack.

## Destination

Save client-demo assets under:

```text
docs/assets/demo/
```

## Required Screenshots

- `01-home.png`: home page showing approved-content positioning.
- `02-demo-status.png`: `/demo-status` with overall status ready.
- `03-chat-citations.png`: KG-RAG answer with citations and expanded concepts.
- `04-graph-us-history.png`: US History graph with a selected concept.
- `05-assessment-mastery.png`: adaptive quiz or mastery update state.
- `06-eval-report.png`: latest eval report or summary view.

## Required Recording

- `client-demo-local.mp4`: 3-5 minute silent walkthrough covering status,
  chat, graph, assessment, and eval report.

## Acceptance Criteria

- No real learner PII is visible.
- `/demo-status` shows `ready`.
- Chat response includes citations.
- Eval report shown was generated after the current seeded run.
- Browser tabs and terminal output do not show secrets.
