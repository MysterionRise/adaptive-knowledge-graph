# 5-Minute Demo Script

A short version of the local OpenStax demo. It shows a pilot prototype, not a
production certification product.

## Before the demo

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

## 0:00–0:45: What it is

Open `http://localhost:3000` and `/demo-status`.

Say:

> This is a local demo of AI over approved course content: citations,
> graph-aware retrieval, adaptive practice and measurable quality checks over
> OpenStax material.

## 0:45–1:35: Knowledge graph

Open the **Graph** (`/graph`).

Show:

- the US History concept graph
- the details of a selected concept
- prerequisite and related-concept edges

Say:

> The graph drives query expansion and remediation. It is not just a visual.

## 1:35–2:45: KG-RAG chat

Open the **AI Tutor** (`/chat`).

Ask:

```text
What caused the American Revolution?
```

Show:

- citations
- expanded concepts
- the KG expansion toggle

Say:

> The system shows what it retrieved and why, and the evaluation compares the
> KG path with plain retrieval.

## 2:45–3:50: Adaptive practice

Open **Assessment** (`/assessment`).

Generate a quiz for `The American Revolution` and show:

- a question and its explanation
- the mastery update
- the direction of the recommendations

Say:

> This is adaptive-practice infrastructure. A production pilot would add
> reviewed question banks and calibration on learner responses.

## 3:50–5:00: Evidence and next steps

Show `/demo-status` and `docs/evals/latest.md`.

Say:

> A sensible next step is a 4–6 week pilot on one approved content slice, with
> success metrics for citation quality, learner usefulness, author review
> effort, refusal behaviour and latency.
