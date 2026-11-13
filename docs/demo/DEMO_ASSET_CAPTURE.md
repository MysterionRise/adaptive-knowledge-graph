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
- `05-assessment-mastery.png`: a quiz or a mastery update.
- `06-eval-report.png`: the latest evaluation report or its summary.

## Recording

- `demo-walkthrough.mp4`: a silent walkthrough of 2–5 minutes covering
  status, chat, graph, assessment and the evaluation report. Keep it in
  `docs/assets/demo/` locally (ignored by git, because recordings exceed the
  1,000 KB pre-commit limit) and attach it to the GitHub release:
  `gh release upload v<version> docs/assets/demo/demo-walkthrough.mp4`.

## Capturing with the script

`scripts/capture_demo_assets.cjs` drives the pages with Playwright and writes
the six screenshots at 1440x900 and 2x, plus `05b-assessment-results.png` (the
quiz results dialog, not used in the README). Run it against the production
build (`npm run build && npm run start` in `frontend/`), so no development
overlay shows:

```bash
(cd frontend && npx playwright install chromium)
node scripts/capture_demo_assets.cjs frontend http://localhost:3000 docs/assets/demo
```

With `--video` it records the same walkthrough at 1x, with pauses to talk
over, and answers two of the three quiz questions correctly. Record into a
scratch directory and convert the WebM to H.264:

```bash
node scripts/capture_demo_assets.cjs frontend http://localhost:3000 /tmp/demo-video --video
ffmpeg -i /tmp/demo-video/video/*.webm -c:v libx264 -pix_fmt yuv420p -crf 28 \
  -movflags +faststart docs/assets/demo/demo-walkthrough.mp4
```

The chat answer and the quiz wait for the language model, up to three
minutes each.

## Acceptance criteria

- No real learner data is visible.
- `/demo-status` shows `ready`.
- The chat response includes citations.
- The evaluation report shown was generated after the current seeded run.
- Browser tabs and terminal output show no secrets, API keys or personal
  information.
