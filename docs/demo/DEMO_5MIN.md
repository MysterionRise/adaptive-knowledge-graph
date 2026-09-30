# 5-Minute Demo Script

Purpose: executive cutdown of the local OpenStax client demo. This is a
controlled pilot prototype, not a production certification product.

## Pre-Demo Commands

Run before the meeting:

```bash
make demo-client-prep
make run-api
```

In another terminal:

```bash
cd frontend
npm run dev
```

Then:

```bash
make demo-eval
make demo-client-check
```

## 0:00-0:45 - Positioning

Open `http://localhost:3000` and `/demo-status`.

Say:

> This is a controlled local demo for AI over approved course content:
> citations, graph-aware retrieval, adaptive practice, and measurable quality
> checks over OpenStax material.

## 0:45-1:35 - Knowledge Graph

Open `/graph`.

Show:

- US History concept graph
- selected concept details
- prerequisite and related-concept edges

Say:

> The graph drives query expansion and remediation. It is not just a visual.

## 1:35-2:45 - KG-RAG Chat

Open `/chat`.

Ask:

```text
What caused the American Revolution?
```

Show:

- citations
- expanded concepts
- KG expansion state

Say:

> The system exposes what it retrieved and why, then evals compare the KG path
> against plain retrieval.

## 2:45-3:50 - Adaptive Practice

Open `/assessment`.

Generate a quiz for `The American Revolution` and show:

- question and explanation
- mastery update
- recommendation direction

Say:

> This is adaptive practice infrastructure. A production pilot would add
> reviewed question banks and learner-response calibration.

## 3:50-5:00 - Evidence And Pilot Path

Show `/demo-status` and `docs/evals/latest.md`.

Say:

> The next step is a 4-6 week pilot over one approved content slice, with
> success metrics for citation quality, learner usefulness, author review
> effort, refusal behavior, and latency.
