# THE TRIBUNAL VERDICT

**Case: Adaptive Knowledge Graph -- Fitness for Purpose as a Proof of Concept**

**Judge: The Tribunal**
**Date: 2026-02-26**

---

## I. CONTESTED DESIGN DECISIONS

For each point of disagreement between the Devil's Advocate and the Angel's Advocate, I render the following rulings.

---

### Decision 1: Neo4j Community Edition with Label-Prefix Isolation

**Devil's Argument**: Neo4j Community Edition lacks multi-database support, forcing a label-prefix hack. A single unscoped `MATCH (n) DETACH DELETE n` would nuke all subjects. Cross-subject contamination is one missed f-string away.

**Angel's Counter**: Educational knowledge is inherently graph-shaped. Variable-length path traversal for KG expansion is natural in Cypher and would require recursive CTEs elsewhere. The label-prefix pattern is pragmatic for a PoC, and `_get_label()` encapsulates it consistently.

**Evidence**: The Witness confirms multi-subject isolation via label prefixes is implemented (`us_history_Concept`, `biology_Concept`). The Prosecutor confirms (H2: `test_graph_query_destructive_cypher`) that destructive Cypher is not blocked on the `/graph/query` endpoint.

**RULING: SUSTAIN with conditions.** Neo4j is the correct choice for a graph-centric PoC. The label-prefix pattern is acceptable *if* the Cypher QA endpoint runs in read-only transactions. The real risk is not the isolation pattern itself -- it is the unprotected Cypher execution endpoint. Fix the Cypher QA endpoint; the label-prefix pattern can remain.

---

### Decision 2: OpenSearch for Hybrid Search

**Devil's Argument**: OpenSearch is overkill for ~5000 chunks. A single-node cluster with security disabled and `latest` tag is operationally unsound. SQLite with FTS5 or Chroma would suffice.

**Angel's Counter**: OpenSearch provides both dense vector search (HNSW via FAISS engine with tuned parameters) and sparse lexical search (BM25) in a single service. The hybrid search with RRF is a proven technique. Alternatives lack built-in BM25 + kNN fusion.

**Evidence**: The Witness confirms HNSW parameters are deliberately tuned (`ef_construction=128, m=24`), not defaults. The BM25 field boosting (`text^3, module_title^2`) shows domain-aware configuration. The Prosecutor confirms the `latest` tag issue and security plugin being disabled.

**RULING: SUSTAIN with conditions.** The hybrid search capability justifies OpenSearch's presence. The tuned HNSW and field-boosted BM25 demonstrate real value. However, the Docker image MUST be pinned to a specific version, and the security plugin should not be explicitly disabled even in dev. These are cheap fixes.

---

### Decision 3: Ollama for Local LLM Inference

**Devil's Argument**: Requires ~13-15GB total RAM across all services. Inaccessible to most developers. Impossible to demo on conference laptops.

**Angel's Counter**: Educational platforms process student data, creating FERPA/COPPA concerns with external APIs. The hybrid fallback mode provides graceful degradation. Local inference has zero ongoing cost and zero data leakage.

**Evidence**: The Witness confirms the hybrid mode exists and falls back to remote on failure. The `PRIVACY_LOCAL_ONLY=true` default and the tri-state `llm_mode` are implemented.

**RULING: SUSTAIN.** The local-first approach is philosophically correct for an educational PoC handling student data. The hybrid fallback mitigates the hardware wall. The Angel is right that the *option* of local inference is a feature, not a bug. The Devil's concern about resource requirements is real but is a deployment concern, not an architectural flaw.

---

### Decision 4: FastAPI + Next.js Dual Stack

**Devil's Argument**: Two servers, two build systems, two runtimes for one demo. A Streamlit UI would be simpler.

**Angel's Counter**: The ML pipeline requires Python. FastAPI's async support is load-bearing (health checks, SSE streaming). Next.js enables Cytoscape.js visualization, real-time SSE, and Zustand state management that Streamlit cannot match.

**Evidence**: The Witness confirms SSE streaming is implemented, the Cytoscape.js visualization is a 440-line polished component, and the API has full OpenAPI documentation at `/docs`.

**RULING: SUSTAIN.** The interactive graph visualization alone justifies Next.js. Streamlit would be incapable of the Cytoscape.js integration and SSE streaming. The two-server cost is real but manageable with Docker Compose.

---

### Decision 5: 512-Character Chunking

**Devil's Argument**: 512 characters is roughly 100 words, barely a paragraph. Historical narratives are butchered. Character-based, not token-based.

**Angel's Counter**: 512 chars is calibrated for the 8K context window of Llama 3.1 with 5 chunks. Sentence boundary detection prevents mid-sentence splits. The window retriever compensates by fetching surrounding chunks via NEXT relationships.

**Evidence**: The Witness confirms sentence boundary detection is implemented and sequential chunk linking (previous/next) powers the window retrieval system. However, the Witness also notes: "window retrieval requires `vector_backend` to be 'neo4j' or 'hybrid' -- the default `vector_backend` is 'opensearch', meaning **window retrieval is effectively disabled by default**."

**RULING: REMAND.** The chunking strategy *would* be defensible if the window retriever actually worked by default. Since the default configuration disables window retrieval, users get 512-character fragments with no surrounding context. Either change the default `vector_backend` to enable window retrieval, or increase the default chunk size. The current state is an architecture that compensates for small chunks via a mechanism that is off by default.

---

### Decision 6: KG-Aware Query Expansion

**Devil's Argument**: Expansion appends raw concept names to queries, polluting the semantic signal. Substring matching (`concept.lower() in query_lower`) causes false positives. "united" matches "United States", "United Nations", etc.

**Angel's Counter**: The ensemble strategy (NER + YAKE + embedding + fulltext) is sophisticated. The fallback architecture is robust. KG expansion addresses the vocabulary mismatch problem that plagues vanilla RAG.

**Evidence**: The Witness confirms both the simple substring matching fallback and the ensemble strategy exist. No direct evidence of expansion quality was gathered.

**RULING: SUSTAIN with notation.** The multi-strategy concept extraction is genuinely sophisticated, and the fallback chain is well-designed. The Devil's concern about raw text concatenation is valid but is a refinement issue, not a fundamental flaw. The substring matching fallback is a reasonable last resort. Note for future work: separate BM25 and kNN queries for expansion terms.

---

### Decision 7: Hybrid Search with RRF

**Devil's Argument**: Fixed k=60, equal weighting, no tuning capability. Suboptimal for both terminology-heavy and conceptual queries.

**Angel's Counter**: RRF with k=60 is the standard parameterization from the original Cormack et al. paper. Field boosting on BM25 shows domain awareness.

**Evidence**: The Witness confirms `k=60` and the field boosting configuration.

**RULING: SUSTAIN.** The standard RRF parameterization is correct for a PoC. Making weights configurable is a legitimate enhancement but does not invalidate the current implementation. The field boosting already provides some domain-specific tuning.

---

### Decision 8: Reranker Configuration Without Implementation

**Devil's Argument**: Settings define `reranker_model` and `reranker_top_k` but no code invokes a reranker. CLAUDE.md claims "BGE-Reranker filtering" -- this is vaporware.

**Angel's Counter**: The Angel describes this as "appropriate staging" -- configured but not yet wired.

**Evidence**: The Witness confirms no reranker is in the retrieval pipeline. The CLAUDE.md documentation claims it exists.

**RULING: REVERSE.** The Angel's defense is weak here. Configured-but-not-implemented is acceptable; *documented as if it works* is not. The CLAUDE.md claim of "BGE-Reranker filtering" is misleading. Either implement it or remove the false claim. This is a documentation integrity issue.

---

### Decision 9: Linear Mastery Model (+0.15/-0.10)

**Devil's Argument**: The docstring claims "BKT/IRT" but this is a simple linear accumulator. Settings mention `student_bkt_enabled` and `student_irt_enabled` but these flags are never read. Getting the hardest question right gives the same delta as the easiest.

**Angel's Counter**: Full BKT/IRT requires calibration data that does not exist yet. The linear model provides directionally correct behavior from the first interaction. The asymmetric delta creates a gentle upward bias. The floor at 0.1 ensures no student is told they know nothing.

**Evidence**: The Witness confirms the algorithm exactly as described. The Prosecutor confirms (M1: `test_mastery_spam_to_max`) that 5 correct answers instantly max out mastery with no cooldown or diminishing returns.

**RULING: SUSTAIN with conditions.** The Angel is correct that full BKT/IRT is premature for a PoC without calibration data. The linear model is directionally correct. However: (1) remove or update any claims of BKT/IRT in docstrings and settings that suggest these are implemented, (2) add a note in documentation that this is simplified mastery tracking. Honesty about what is implemented matters.

---

### Decision 10: LLM-Generated Quiz Difficulty Scores

**Devil's Argument**: LLMs have no reliable calibration for question difficulty. The entire feedback loop is built on unreliable difficulty labels.

**Angel's Counter**: The structured prompting gives clear difficulty bands. Grounding questions in retrieved content ensures factual accuracy. The dual difficulty representation (categorical + numeric) enables future refinement.

**Evidence**: The Witness confirms the difficulty targeting thresholds and the prompt structure. No empirical evidence of difficulty accuracy was gathered.

**RULING: SUSTAIN.** For a PoC, LLM-estimated difficulty is a reasonable starting point. The alternative -- hand-curated question banks -- defeats the purpose of a generative system. The Devil's concern is valid but is the *known limitation of the approach*, not a bug. The system should document this limitation.

---

### Decision 11: JSON File-Based Student Profiles

**Devil's Argument**: No concurrent access safety. Simultaneous writes lose data. No migration strategy.

**Angel's Counter**: (Implicitly accepted as a PoC tradeoff.)

**Evidence**: The Prosecutor confirms (M5: `test_file_based_storage_concurrent_writes`) that concurrent writes cause data loss.

**RULING: SUSTAIN for PoC, REMAND for anything beyond.** JSON file storage is acceptable for a single-user demo. The concurrent write bug is real but only manifests with multiple simultaneous API processes. Document the limitation. For any multi-user deployment, migrate to SQLite at minimum.

---

### Decision 12: Global Mutable Singletons vs. FastAPI DI

**Devil's Argument**: Every service uses global singletons. `deps.py` defines proper DI functions that are never used by routes. Not thread-safe.

**Angel's Counter**: The singleton registry pattern provides lazy initialization and per-subject caching. It is consistent across all services.

**Evidence**: The Witness confirms that `deps.py` has 0% test coverage and is not used by any route handler. The singleton pattern is consistently applied but routes bypass the DI system.

**RULING: REVERSE.** The `deps.py` file is dead code that creates a false impression of proper architecture. Either use FastAPI's DI system as intended, or delete `deps.py`. Dead code that suggests an unused pattern is worse than no code at all.

---

### Decision 13: Blocking Synchronous Calls in Async Endpoints

**Devil's Argument**: Synchronous OpenSearch and Neo4j calls block the FastAPI event loop. Under concurrent load, a single slow query blocks all requests.

**Angel's Counter**: The Angel does not directly address this point.

**Evidence**: The Witness confirms the routes are async but does not directly measure blocking behavior.

**RULING: REMAND.** For a PoC with single-user demos, this is not immediately harmful. However, it undermines the stated benefit of using async FastAPI. Before any multi-user deployment, wrap synchronous I/O in `run_in_executor` or use async client libraries.

---

### Decision 14: Duplicate API Logic (ask.py)

**Devil's Argument**: The `ask_question` endpoint and `_retrieve_context` helper contain nearly identical retrieval logic. Any bug fix must be applied in two places.

**Angel's Counter**: Not directly addressed.

**Evidence**: The Witness confirms both the streaming and non-streaming paths exist.

**RULING: REVERSE.** Code duplication in the core pipeline is a maintenance hazard. The `_retrieve_context` function was clearly intended to deduplicate this logic. Refactor `ask_question` to use it.

---

### Decision 15: Frontend Quiz Component (850 Lines)

**Devil's Argument**: A single component handles topic selection, quiz generation, question display, answer submission, mastery tracking, recommendations, results, learning paths, and profile reset. 15+ `useState` hooks. Untestable monolith.

**Angel's Counter**: The Angel lists the UI features as evidence of completeness rather than addressing the monolith concern.

**Evidence**: The Witness confirms the component's scope.

**RULING: SUSTAIN for PoC.** An 850-line component is not ideal, but for a PoC that is demonstrating functionality rather than shipping to users, this is acceptable technical debt. Decomposition would be the right first step in a production push.

---

### Decision 16: SSL Verification Disabled

**Devil's Argument**: `verify_certs=False` and `verify_ssl=False` everywhere. OpenRouter connections are vulnerable to MITM attacks. Contradicts the "Privacy-First" claim.

**Angel's Counter**: Not directly addressed as a positive decision; the Angel focuses on the local-first architecture.

**Evidence**: The Witness confirms SSL verification is disabled for both OpenSearch and OpenRouter.

**RULING: REVERSE.** Disabling SSL verification is never defensible, even in a PoC. For local OpenSearch without TLS, the connection does not need verification. For OpenRouter (an external API over the internet), SSL verification MUST be enabled. Change the defaults to `True` and let users who need to disable it do so explicitly.

---

## II. PROSECUTION CHARGES -- SEVERITY CLASSIFICATION

### CRITICAL (must fix before any demo)

| Charge | Description | Classification | Reasoning |
|--------|-------------|----------------|-----------|
| C2 | Error messages leak credentials and internal URIs | **CRITICAL** | A demo where a network error exposes `password: s3cret` or `API_KEY=sk-live-abc123` in the browser is disqualifying. |
| H2-a | Destructive Cypher via `/graph/query` | **CRITICAL** | A demo attendee typing "delete everything" into the natural language query box could wipe the knowledge graph mid-presentation. |

**Total CRITICAL: 2 charges**

### HIGH (must fix before production or public demo)

| Charge | Description | Classification | Reasoning |
|--------|-------------|----------------|-----------|
| C1 | No authentication on student/graph endpoints | **HIGH** | Acceptable for a local-only demo but unacceptable for any networked deployment. |
| H1-a | Whitespace-only questions pass validation | **HIGH** | Sends garbage to the LLM and wastes inference time. |
| H1-b | No max_length on question field | **HIGH** | A >1MB payload is a trivial DoS vector. |
| H1-c | Empty string accepted as quiz topic | **HIGH** | Produces nonsensical quiz generation requests. |
| H1-d | No upper bound on num_questions | **HIGH** | `num_questions=10000` is an LLM DoS. |
| H1-e | num_questions=0 and num_questions=-1 accepted | **HIGH** | Nonsensical input should be rejected at the boundary. |
| H2-b | XSS payloads echoed back verbatim | **HIGH** | If the response is rendered as HTML anywhere, this is exploitable. |
| H2-d | Lucene wildcard injection | **HIGH** | `*:*` against fulltext search is an information disclosure vector. |
| M5 | Concurrent file writes cause data loss | **HIGH** | Elevating from MEDIUM because this is silent data corruption, not just a race condition. |
| L3-b | `/health/ready` returns 200 when unhealthy | **HIGH** | Elevating from LOW because load balancers depend on health check status codes. A 200-when-unhealthy breaks standard deployment patterns. |

**Total HIGH: 10 charges**

### MEDIUM (fix in next iteration)

| Charge | Description | Classification | Reasoning |
|--------|-------------|----------------|-----------|
| H1-f | Empty search query accepted | **MEDIUM** | Low impact; returns all or no results. |
| H1-g | Negative limit causes 500 instead of 422 | **MEDIUM** | Poor UX but not exploitable. |
| H1-h | No upper bound on graph data limit | **MEDIUM** | Could return large payloads but Neo4j is the bottleneck, not the limit value. |
| H1-i | Negative limit on top concepts causes 500 | **MEDIUM** | Same as H1-g. |
| H2-c | NoSQL injection in subject causes 500 | **MEDIUM** | The parameterized Cypher queries protect against actual injection; this is a validation gap, not an injection. |
| M1-a | Mastery spam to max | **MEDIUM** | Gaming concern, not a security vulnerability. |
| M1-b | Mastery for non-existent concepts | **MEDIUM** | Data hygiene issue; does not break functionality. |
| M1-c | Modify other student's mastery | **MEDIUM** | Follows from the authentication gap (C1). |
| M1-d | Reset wipes all data with no confirmation | **MEDIUM** | Follows from the authentication gap (C1). |
| M2-a | Quiz answers leaked in response | **MEDIUM** | Intentional for a PoC (client-side grading). Would need server-side submission for production. |
| M2-b | No quiz submission endpoint | **MEDIUM** | Same as above -- a known architectural gap. |
| M3-a | X-Forwarded-For rate limit bypass | **MEDIUM** | Only relevant behind a reverse proxy that does not strip the header. |
| M3-b | Student endpoints no rate limit | **MEDIUM** | Combined with no auth, this enables spam, but the impact is limited to JSON file writes. |
| M3-c | Graph query no rate limit | **MEDIUM** | Combined with Cypher execution, this is concerning. Partially mitigated if C2-level Cypher fix is applied. |
| M4 | CORS allows all methods | **MEDIUM** | Standard for API development; restrict in production. |
| M6-a | Negative max_depth on learning path | **MEDIUM** | Validation gap. |
| M6-b | max_depth=99999 accepted | **MEDIUM** | Potential DoS but limited by actual graph depth. |

**Total MEDIUM: 17 charges**

### LOW (acceptable for PoC)

| Charge | Description | Classification | Reasoning |
|--------|-------------|----------------|-----------|
| L1-a | Non-existent subject returns 500 | **LOW** | Error code is wrong but the request correctly fails. |
| L1-b | Non-existent subject in quiz returns 200 (mock) | **LOW** | Test artifact, not a real vulnerability. |
| L2-a/b/c | OpenAPI/Swagger/ReDoc exposed | **LOW** | Standard for development. Disable in production via settings. |
| L3-a | Empty LLM response passed through | **LOW** | Edge case; the LLM rarely returns empty. |

**Total LOW: 4 charges (covering 6 original charges)**

### Charges Corroborated by Witness

The following Prosecutor charges are directly confirmed by the Witness's independent observations:

- **C1 (No auth)**: Witness Section 5 confirms "No endpoint in `routes/` currently uses the auth dependency"
- **C2 (Error leaks)**: Witness Section 8 confirms "All other unhandled errors return 500 with error message in detail"
- **M2-a (Quiz answers leaked)**: Witness Section 7 confirms "`correct_option_id` field" is in response
- **M2-b (No submission endpoint)**: Witness Section 7 confirms "There is no quiz submission endpoint"
- **M3-a (X-Forwarded-For)**: Witness Section 5 confirms "X-Forwarded-For header is trusted without validation"
- **M5 (Concurrent writes)**: Witness Section 6 confirms "No file locking mechanism" and "No concurrent access protection"
- **Window retrieval disabled by default**: Witness Section 10 confirms "window retrieval is effectively disabled by default"
- **deps.py unused**: Witness Section 8 confirms "none of these DI providers are used by the route handlers" with "0% test coverage"

### Passed Defenses (Acknowledged)

The Prosecution fairly documented 22 tests that passed, confirming:
- Pydantic validation works for basic bounds (top_k, window_size, min_length)
- Parameterized Cypher queries protect against injection in concept lookups
- CORS blocks unauthorized origins
- Request ID middleware functions correctly
- The system is robust against prompt injection (does not crash)

These defenses reflect genuine engineering care and should be preserved.

---

## III. OVERALL VERDICT

### Grade: GUILTY WITH PROBATION

**The codebase is fit for purpose as a PoC, contingent on fixing a small number of critical issues.**

The Adaptive Knowledge Graph demonstrates genuine technical sophistication in its core domain: graph-enhanced retrieval-augmented generation for educational content. The KG expansion pipeline, hybrid search with RRF, window retrieval architecture, multi-subject isolation, and adaptive quiz generation form a coherent system that validates real hypotheses about personalized learning.

However, the system has two categories of problems: (1) a handful of issues that would be embarrassing or harmful in any demo, and (2) a larger set of issues that are acceptable for a PoC but must be addressed before any broader deployment.

---

### MUST-FIX (Blocking for any demo -- 5 items)

1. **Sanitize error responses** (C2): Replace `str(e)` in exception handlers with generic messages. Log the full error server-side with the request ID. This prevents credential leakage in error responses. Affects `ask.py`, `graph.py`, `quiz.py`, `learning_path.py`.

2. **Make `/graph/query` read-only** (H2-a): Execute all LangChain-generated Cypher in a read-only Neo4j transaction. This prevents destructive operations through the natural language query interface.

3. **Add max_length to question/topic fields** (H1-b): Add `max_length=2000` (or similar) to the `question` field in `QuestionRequest` and the `topic` parameter in quiz generation. This prevents trivial payload DoS.

4. **Add bounds to num_questions** (H1-d/e): Add `ge=1, le=10` (or similar reasonable bounds) to the `num_questions` parameter. This prevents LLM DoS via `num_questions=10000`.

5. **Fix CLAUDE.md reranker claim** (Decision 8): Remove or qualify the "BGE-Reranker filtering" claim. Replace with "Reranker integration planned" or similar honest language.

### SHOULD-FIX (Blocking for production -- 10 items)

1. **Enable authentication on sensitive endpoints**: At minimum, protect `/student/reset`, `/student/mastery`, and `/graph/query` with the existing API key mechanism that is already implemented but not wired to routes.

2. **Fix SSL verification defaults**: Change `openrouter_verify_ssl` to `True`. Keep OpenSearch verification off only for local development.

3. **Add whitespace stripping to input validation**: Add a Pydantic validator that strips whitespace and re-checks min_length.

4. **Fix `/health/ready` status code**: Return 503 when services are unhealthy, not 200.

5. **Delete `deps.py` or wire it into routes**: Dead code that implies an unused pattern is misleading. Choose one path and commit.

6. **Deduplicate `ask.py` retrieval logic**: Refactor `ask_question` to use `_retrieve_context`.

7. **Fix window retrieval default**: Either change `vector_backend` default to enable window retrieval, or increase chunk size, or document clearly that window retrieval requires configuration change.

8. **Pin Docker image versions**: Replace `opensearch:latest` with a specific version tag.

9. **Add rate limiting to `/graph/query`**: This endpoint executes Cypher and should have rate limiting.

10. **Remove dead BKT/IRT settings**: Remove `student_bkt_enabled` and `student_irt_enabled` from settings, or clearly document them as "reserved for future use."

### COMMENDATIONS (Things done well -- preserve these)

1. **Multi-strategy concept extraction with fallback chains**: The NER + YAKE + embedding + fulltext ensemble with graceful degradation is genuinely sophisticated and well-engineered.

2. **Hybrid search with tuned HNSW parameters**: The deliberate `ef_construction=128, m=24` tuning and field-boosted BM25 show real IR knowledge.

3. **Multi-subject architecture via YAML configuration**: Adding a new subject requires only a config entry and data. This is excellent extensibility design.

4. **Window retrieval via graph traversal**: The NEXT-relationship-based context expansion is an elegant use of the graph database for RAG enhancement.

5. **Hybrid LLM mode with graceful degradation**: The local-first approach with automatic remote fallback is a thoughtful privacy-respecting design.

6. **Comprehensive Pydantic validation**: Field-level validation on API inputs, structured settings management, and OpenAPI schema generation are production-grade patterns.

7. **Cytoscape.js knowledge graph visualization**: The 440-line interactive graph component with importance-based sizing, relationship coloring, and neighborhood highlighting is polished work.

8. **Pipeline architecture**: The `fetch -> parse -> normalize -> build-kg -> index-rag` pipeline is composable, idempotent, and well-suited to CI/CD integration.

9. **346 passing tests with 63% coverage**: A solid test foundation, especially for a PoC. The conftest.py mocking strategy is clean.

10. **Structured exception hierarchy**: Custom exceptions with proper inheritance and specific error types (LLMConnectionError, LLMGenerationError) enable precise error handling.

### REMANDED (Needs revisiting with more information -- 3 items)

1. **Blocking sync calls in async endpoints**: Measure actual latency impact under concurrent load before deciding whether to add `run_in_executor` wrappers. For single-user demos this is a non-issue; for any multi-user scenario it must be addressed.

2. **Chunk size and window retrieval interaction**: The 512-character chunks are defensible only if window retrieval works. Test the actual retrieval quality with and without window expansion to determine the right defaults.

3. **LLM difficulty calibration**: Gather empirical data on whether LLM-estimated difficulty scores correlate with actual student performance. This is the core hypothesis of the adaptive system and has not been validated.

---

## IV. FINAL STATEMENT

**The single most important thing this project needs is honesty in its documentation.**

The codebase is better than the Devil claims and worse than the Angel admits. The core architecture -- graph-enhanced RAG with adaptive quiz generation -- is sound and demonstrates real technical insight. But the documentation claims features that do not exist (BGE-Reranker filtering), algorithms that are not implemented (BKT/IRT), and a privacy posture that is contradicted by disabled SSL verification.

A PoC earns trust by being transparent about what it does and does not do. Fix the five MUST-FIX items, update the documentation to reflect reality, and this is a compelling demonstration of knowledge-graph-enhanced adaptive learning. Ship it with honest labels.

---

*Verdict rendered by The Tribunal.*
*"A proof of concept proves what it proves -- nothing more, nothing less."*
