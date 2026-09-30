# Manual Testing Checklist for the Frontend

Use this checklist before a release or a demo to walk through every page by
hand. Automated coverage is described in [docs/TESTING.md](../docs/TESTING.md).

The app has no mock-data fallback: every page needs the backend and seeded
data. When the backend is down, pages must show a clear error instead of
invented numbers.

## Pre-test setup

- [ ] `make doctor` reports no problems
- [ ] Neo4j and OpenSearch are running and seeded (`make up`, `make seed`)
- [ ] Ollama is running with the configured model
- [ ] The API is running on `http://localhost:8000` (`make run-api`)
- [ ] The frontend dev server is running on `http://localhost:3000`
- [ ] The browser DevTools console is open

---

## 1. Home page (`/`)

- [ ] The page loads without console errors
- [ ] Graph statistics (concepts, modules, relationships) come from the API
- [ ] The statistics cards (Concepts, Modules, Relationships) show API values
- [ ] The subject picker lists every configured subject; subjects without seeded data show "Coming soon" and cannot be selected
- [ ] Switching subject updates the statistics, and the choice survives a reload (browser storage key `akg-preferences`)
- [ ] The OpenStax attribution is visible and its links open in a new tab

## 2. Knowledge graph (`/graph`)

- [ ] The graph renders nodes and edges for the selected subject
- [ ] Nodes are sized by importance
- [ ] Edges are coloured by relationship type, matching the legend
- [ ] Clicking a node selects it, highlights its neighbours and shows its details
- [ ] Clicking the background clears the selection
- [ ] Dragging pans, scrolling zooms, and "Zoom in", "Zoom out", "Fit to view" and "Reset view" work
- [ ] "Ask AI Tutor About This" on a selected concept opens Chat with the question filled in
- [ ] The graph loads within a few seconds and interactions stay smooth

## 3. AI Tutor (`/chat`)

- [ ] The example questions match the selected subject (for US History, for example, "What caused the American Revolution?")
- [ ] Sending is disabled for an empty input; Enter and the Send button both submit
- [ ] The answer streams in, then shows citations, source snippets with scores and the model name
- [ ] With KG expansion on, expanded concepts are listed; turning it off removes them
- [ ] The answer shows the textbook attribution
- [ ] `/chat?question=...` asks the question on page load
- [ ] If the API fails, an error appears in the conversation and the next question still works

## 4. Comparison (`/comparison`)

- [ ] Example questions fill the input; an empty question disables "Compare"
- [ ] Both panels (KG-expanded and plain retrieval) show loading states, then answers rendered as Markdown (lists and emphasis display correctly)
- [ ] The KG panel lists the expanded concepts; both panels show retrieval counts and sources
- [ ] Differences between the two answers are easy to see

## 5. Assessment (`/assessment`)

- [ ] Generating a quiz for a topic returns questions with options
- [ ] Answering shows whether the answer was correct, with the explanation
- [ ] Mastery updates after each answer and the next quiz targets the new difficulty
- [ ] Recommendations appear after the quiz (prerequisites to review or topics to explore)
- [ ] Resetting the profile returns mastery to its initial state
- [ ] With `API_KEY` set on the backend, these calls work when `NEXT_PUBLIC_API_KEY` matches and fail clearly when it does not

## 6. Demo Status (`/demo-status`)

- [ ] Neo4j, OpenSearch and Ollama report their real state
- [ ] Seeded subject data is listed with counts
- [ ] The latest evaluation shows as valid only after a successful `make demo-eval`

## 7. About (`/about`)

- [ ] The overview, technology stack, attribution and license sections render
- [ ] External links open in new tabs

## 8. Navigation

- [ ] The shared navigation bar (Graph, AI Tutor, Compare, Assessment, Demo Status, About) appears on every page and highlights the current one
- [ ] The logo returns to Home
- [ ] Browser back and forward buttons work and the URL updates on each navigation
- [ ] An unknown URL shows "Page not found" with a link to the home page
- [ ] An unexpected error shows the error page, and "Try again" recovers

## 9. Accessibility

- [ ] All interactive elements can be reached with Tab and have a visible focus indicator
- [ ] Forms submit with Enter
- [ ] Images have alt text and icon-only buttons have accessible labels
- [ ] Headings are in a logical order
- [ ] Text contrast meets WCAG AA (check with the browser DevTools)

## 10. Responsive layout

- [ ] Desktop (1920×1080)
- [ ] Tablet (768×1024)
- [ ] Mobile (375×667)

## 11. Edge cases

- [ ] **API down:** stop the API and reload each page. Each page shows an error or empty state and does not crash
- [ ] **Network drop:** disconnect mid-request. An error appears and a retry works after reconnecting
- [ ] **Empty data:** with an unseeded subject, the graph and chat explain that no data is available
- [ ] **Long content:** long answers, long concept names and many expanded concepts do not break the layout

## 12. Browsers

- [ ] Chrome
- [ ] Firefox
- [ ] Safari (macOS)
- [ ] Edge
- [ ] Mobile Safari (iOS)
- [ ] Mobile Chrome (Android)

---

## Sign-off

- No crashes, blank pages or broken navigation
- Graph, chat, comparison and assessment work end to end for every seeded subject
- No console errors during normal use
- Pages fail visibly and recover when the backend is unavailable

Record the date, the commit (`git rev-parse --short HEAD`), the browser and OS,
and screenshots of any bug in the pull request or issue.
