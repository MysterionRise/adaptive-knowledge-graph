# Demo Asset Capture Checklist

Use this after `make demo-client-check` passes on a live local stack.

## Destination

Save screenshots and recordings under:

```text
docs/assets/demo/
```

## Screenshots

- `01-home.png`: the home page.
- `02-demo-status.png`: `/demo-status` with the overall status ready.
- `03-chat-citations.png`: a KG-RAG answer with citations and expanded
  concepts.
- `04-graph-us-history.png`: the US History graph with a selected concept.
- `05-assessment-mastery.png`: an adaptive quiz or a mastery update.
- `06-eval-report.png`: the latest evaluation report or its summary.

## Recording

- `demo-walkthrough.mp4`: a 3–5 minute silent walkthrough covering status,
  chat, graph, assessment and the evaluation report.

## Acceptance criteria

- No real learner data is visible.
- `/demo-status` shows `ready`.
- The chat response includes citations.
- The evaluation report shown was generated after the current seeded run.
- Browser tabs and terminal output show no secrets, API keys or personal
  information.
