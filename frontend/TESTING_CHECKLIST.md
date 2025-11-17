# Manual Testing Checklist for Adaptive Knowledge Graph Frontend

This checklist helps ensure all features work correctly before demo/deployment.

## Pre-Test Setup

- [ ] Backend API is running on `http://localhost:8000`
- [ ] Neo4j is running with populated knowledge graph
- [ ] Qdrant vector database is running with indexed chunks
- [ ] Frontend dev server is running on `http://localhost:3000`
- [ ] Browser DevTools console is open for error checking

---

## 1. Home Page (`/`)

### Visual/Layout
- [ ] Page loads without errors
- [ ] Header displays "Adaptive Knowledge Graph" title
- [ ] Navigation buttons ("Explore Graph", "Ask Questions") are visible
- [ ] Statistics dashboard displays 3 cards (Concepts, Modules, Relationships)
- [ ] Feature cards (4 total) are displayed in grid layout
- [ ] "How It Works" section with 3 steps is visible
- [ ] OpenStax attribution footer is present

### Functionality
- [ ] Statistics load from API (or show mock data with warning)
- [ ] Clicking "Explore Graph" navigates to `/graph`
- [ ] Clicking "Ask Questions" navigates to `/chat`
- [ ] Clicking feature cards navigates to correct pages
- [ ] OpenStax links open in new tab
- [ ] All icons render correctly

### Responsive Design
- [ ] Page looks good on desktop (1920x1080)
- [ ] Page looks good on tablet (768x1024)
- [ ] Page looks good on mobile (375x667)

### Error Handling
- [ ] If API is down, shows warning message
- [ ] Statistics still display (using mock data)

---

## 2. Knowledge Graph Page (`/graph`)

### Visual/Layout
- [ ] Page loads without errors
- [ ] Graph visualization container is visible
- [ ] Legend shows all relationship types (Prerequisite, Covers, Related, Highlighted)
- [ ] Control buttons (Fit to View, Center) are visible
- [ ] Sidebar shows "How to Use" instructions
- [ ] Graph stats (Nodes, Edges count) display correctly

### Graph Interaction
- [ ] Graph renders with nodes and edges
- [ ] Nodes are sized by importance (larger = more important)
- [ ] Nodes are colored by importance (gradient)
- [ ] Clicking a node highlights it (green border)
- [ ] Clicking a node shows selected concept info at bottom-left
- [ ] Connected nodes are highlighted when node is selected
- [ ] Edges are colored by type:
  - Red = Prerequisite
  - Blue = Covers
  - Purple = Related
- [ ] Can drag to pan the graph
- [ ] Can scroll to zoom in/out
- [ ] "Fit to View" button resets zoom to see all nodes
- [ ] "Center" button centers the graph
- [ ] Clicking background deselects node

### Functionality
- [ ] Clicking "Ask AI Tutor About This" navigates to chat with pre-filled question
- [ ] Back button navigates to home page
- [ ] Graph stats show correct numbers

### Performance
- [ ] Graph loads within 3 seconds
- [ ] Interactions are smooth (no lag)
- [ ] No console errors

---

## 3. Chat Page (`/chat`)

### Visual/Layout
- [ ] Page loads without errors
- [ ] Header shows "AI Tutor Chat" title
- [ ] KG Expansion toggle is visible and ON by default
- [ ] Welcome message with 4 example questions is displayed
- [ ] Input field and Send button are visible
- [ ] Messages area is empty initially

### Chat Functionality
- [ ] Typing in input field works
- [ ] Send button is disabled when input is empty
- [ ] Send button is enabled when text is entered
- [ ] Clicking Send or pressing Enter submits question
- [ ] User message appears in blue bubble (right-aligned)
- [ ] Loading indicator ("Thinking...") appears while waiting
- [ ] AI response appears in white bubble (left-aligned)
- [ ] Multiple messages stack correctly in conversation

### KG Expansion Toggle
- [ ] Toggle is ON (checked) by default
- [ ] Clicking toggle turns it OFF
- [ ] Visual indicator changes when toggled
- [ ] Questions asked with toggle ON show expanded concepts
- [ ] Expanded concepts appear in blue box with badges

### AI Response Features
- [ ] Answer text is displayed
- [ ] Expanded concepts (if KG ON) are shown with badges
- [ ] "Show/Hide Sources" button appears
- [ ] Clicking "Show Sources" reveals source citations
- [ ] Sources show chapter/section, text snippet, and relevance score
- [ ] Attribution footer shows OpenStax CC BY 4.0
- [ ] Model name is displayed

### Example Questions
- [ ] Clicking any example question fills input and sends
- [ ] "What is photosynthesis?" works
- [ ] "Explain cellular respiration" works
- [ ] "How does DNA replication work?" works
- [ ] "What is the difference between mitosis and meiosis?" works

### Pre-filled Questions (from URL)
- [ ] Navigate to `/chat?question=What+is+photosynthesis?`
- [ ] Question is automatically asked on page load
- [ ] Response appears correctly

### Error Handling
- [ ] If API fails, error message is shown in chat
- [ ] User can continue asking questions after error

---

## 4. Comparison Page (`/comparison`)

### Visual/Layout
- [ ] Page loads without errors
- [ ] Header shows "KG-RAG vs Regular RAG Comparison" title
- [ ] Question input field is visible
- [ ] 3 example question buttons are visible
- [ ] "Compare Approaches" button is visible
- [ ] Two result panels (With KG, Regular RAG) are ready

### Functionality
- [ ] Typing question enables Compare button
- [ ] Empty question disables Compare button
- [ ] Clicking example question fills input
- [ ] Clicking "Compare Approaches" triggers comparison

### Comparison Results
- [ ] Both panels show loading spinners initially
- [ ] "With KG Expansion" panel has green border/theme
- [ ] "Regular RAG" panel has gray border/theme
- [ ] Both answers are displayed side-by-side
- [ ] KG panel shows expanded concepts with badges
- [ ] Stats show retrieved chunks and concepts used
- [ ] Source count is displayed for each
- [ ] "Why KG Expansion Matters" explanation is visible

### Comparison Quality
- [ ] KG-expanded answer shows MORE concepts
- [ ] KG-expanded answer is typically more comprehensive
- [ ] Visual difference between approaches is clear

---

## 5. About Page (`/about`)

### Visual/Layout
- [ ] Page loads without errors
- [ ] Overview section is readable
- [ ] 4 feature cards (Privacy-First, Knowledge Graph, Local LLMs, Open Source)
- [ ] Technology stack section with Backend/Frontend lists
- [ ] Attribution section with OpenStax links
- [ ] License section

### Functionality
- [ ] Back button navigates to home
- [ ] External links open in new tabs
- [ ] All icons render correctly

---

## 6. Cross-Page Navigation

- [ ] Can navigate from Home → Graph → Back to Home
- [ ] Can navigate from Home → Chat → Back to Home
- [ ] Can navigate from Home → Comparison → Back to Home
- [ ] Can navigate from Home → About → Back to Home
- [ ] Browser back button works correctly
- [ ] URL changes correctly on each navigation

---

## 7. Accessibility

### Keyboard Navigation
- [ ] Can tab through all interactive elements
- [ ] Focus indicators are visible
- [ ] Can submit forms with Enter key
- [ ] Can navigate back with Escape (if applicable)

### Screen Reader
- [ ] All images have alt text
- [ ] Buttons have aria-labels
- [ ] Headings are in logical order
- [ ] Links describe their destination

### Color Contrast
- [ ] Text is readable on all backgrounds
- [ ] Meets WCAG AA standards (test with browser DevTools)

---

## 8. Performance

### Load Times
- [ ] Home page loads in < 2 seconds
- [ ] Graph page loads in < 3 seconds
- [ ] Chat page loads in < 2 seconds
- [ ] Comparison page loads in < 2 seconds

### API Calls
- [ ] No unnecessary duplicate API calls
- [ ] Loading states are shown during API calls
- [ ] Errors are handled gracefully

### Browser Console
- [ ] No JavaScript errors
- [ ] No React warnings
- [ ] No network errors (except expected API failures)

---

## 9. Browser Compatibility

Test on:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest, Mac only)
- [ ] Edge (latest)
- [ ] Mobile Safari (iOS)
- [ ] Mobile Chrome (Android)

---

## 10. Edge Cases

### API Down
- [ ] Navigate to home page with backend stopped
- [ ] Warning message appears
- [ ] Mock data is displayed
- [ ] App doesn't crash

### Network Errors
- [ ] Disconnect network mid-request
- [ ] Error message is shown
- [ ] Can retry after reconnecting

### Empty States
- [ ] Empty chat conversation shows welcome message
- [ ] No graph data shows appropriate message

### Long Content
- [ ] Very long AI answers don't break layout
- [ ] Long concept names in graph don't overflow
- [ ] Many expanded concepts display correctly

---

## Test Scenarios for Demo

### Scenario 1: "Show Me the Magic" (5 min)
1. Start on home page
2. Point out statistics
3. Click "Explore Graph"
4. Click a node (e.g., "Photosynthesis")
5. Click "Ask AI Tutor About This"
6. Show KG expansion toggle (turn ON/OFF)
7. Observe expanded concepts list

### Scenario 2: "Compare the Difference" (3 min)
1. Navigate to Comparison page
2. Enter "What is cellular respiration?"
3. Click "Compare Approaches"
4. Point out KG panel has 8+ concepts
5. Point out Regular RAG panel has 1 concept
6. Explain why KG answer is better

### Scenario 3: "Interactive Exploration" (4 min)
1. Go back to Graph page
2. Zoom and pan around
3. Click multiple nodes
4. Show how relationships are highlighted
5. Explain prerequisite chains
6. Navigate to a concept and ask about it

---

## Success Criteria

**All features pass if:**
- ✅ No critical bugs (crashes, blank pages, broken navigation)
- ✅ All core features work (graph, chat, comparison)
- ✅ Visual design is polished (no misaligned elements)
- ✅ Performance is acceptable (< 3s load times)
- ✅ Accessibility basics are covered (keyboard nav, labels)
- ✅ Error handling works (graceful degradation)

**Ready for demo if:**
- ✅ All above criteria met
- ✅ Mock data works when backend is unavailable
- ✅ Can complete all 3 demo scenarios successfully
- ✅ No console errors during normal use

---

## Notes

- Test with **backend running** for full functionality
- Test with **backend stopped** to verify mock data fallback
- Take screenshots of any bugs found
- Note browser/OS for any compatibility issues

**Last Updated:** {DATE}
**Tested By:** _______________
**Test Environment:** _______________
