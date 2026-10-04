# TRIBUNAL WITNESS REPORT

## Codebase Exploration Date: 2026-02-26

This report contains only factual observations about the system's actual behavior, structure, and test results. No opinions or recommendations are included.

---

## 1. PROJECT STRUCTURE

### Backend (FastAPI - Python 3.11)

The backend is located at `backend/app/` and contains the following modules:

| Module | Files | Purpose |
|--------|-------|---------|
| `api/routes/` | `ask.py`, `graph.py`, `quiz.py`, `learning_path.py`, `subjects.py` | REST API endpoints |
| `api/` | `deps.py` | FastAPI dependency injection providers |
| `core/` | `settings.py`, `auth.py`, `middleware.py`, `rate_limit.py`, `exceptions.py`, `logging.py`, `subjects.py` | Configuration, auth, middleware |
| `kg/` | `neo4j_adapter.py`, `builder.py`, `schema.py`, `cypher_qa.py` | Knowledge graph operations |
| `nlp/` | `llm_client.py`, `embeddings.py`, `concept_extractor.py` | LLM and NLP |
| `rag/` | `retriever.py`, `kg_expansion.py`, `chunker.py`, `window_retriever.py`, `unified_retriever.py` | RAG pipeline |
| `student/` | `student_service.py`, `quiz_generator.py`, `recommendation_service.py`, `models.py` | Adaptive learning |
| `ui_payloads/` | `quiz.py`, `recommendations.py` | Response models |

### Frontend (Next.js)

Located at `frontend/`. Pages: home, chat, assessment, graph, comparison, about. Components: KnowledgeGraph (Cytoscape.js), Quiz, LearningPath, MasteryIndicator, PostQuizRecommendations, SubjectPicker, Skeleton, ErrorBoundary, Providers.

### Infrastructure

- Docker Compose at `infra/compose/compose.yaml` defines: Neo4j 5.16-community, OpenSearch (latest), API (CPU/GPU profiles)
- Scripts at `scripts/`: pipeline scripts (fetch, parse, normalize, build-kg, index), migration scripts, seed scripts

### Configuration

- 4 subjects configured in `config/subjects.yaml`: us_history (default), biology, economics, world_history
- Settings in `backend/app/core/settings.py`: 70+ configuration parameters via Pydantic BaseSettings

---

## 2. INFRASTRUCTURE STATUS

Docker services checked at time of observation:

| Service | Container | Status | Ports |
|---------|-----------|--------|-------|
| Neo4j | adaptive-kg-neo4j | Up 8 days (healthy) | 7474, 7687 |
| OpenSearch | opensearch | Up 8 days | 9200, 9600 |

Both services were running and healthy.

---

## 3. TEST SUITE RESULTS

Command: `poetry run pytest backend/tests/ -v --tb=short`

**Result: 346 tests passed in 8.28 seconds. Zero failures.**

### Test File Breakdown

| Test File | Tests | Status |
|-----------|-------|--------|
| `test_api_ask.py` | 12 | All pass |
| `test_api_graph.py` | 19 | All pass |
| `test_api_quiz.py` | 11 | All pass |
| `test_docker.py` | 5 | All pass |
| `test_kg_expansion.py` | 16 | All pass |
| `test_llm_client.py` | 30 | All pass |
| `test_logging.py` | 3 | All pass |
| `test_main.py` | 9 | All pass |
| `test_makefile.py` | 8 | All pass |
| `test_neo4j_adapter.py` | 34 | All pass |
| `test_poetry.py` | 8 | All pass |
| `test_quiz_generator.py` | 14 | All pass |
| `test_recommendation_service.py` | 14 | All pass |
| `test_retriever.py` | 8 | All pass |
| `test_settings.py` | 3 | All pass |
| `test_streaming.py` | 8 | All pass |
| `test_student_service.py` | 25 | All pass |

### Code Coverage

Total coverage: **63%** (1821 of 2893 statements covered)

| Module | Coverage | Notable Gaps |
|--------|----------|--------------|
| `core/exceptions.py` | 100% | - |
| `core/settings.py` | 100% | - |
| `core/middleware.py` | 100% | - |
| `ui_payloads/quiz.py` | 100% | - |
| `ui_payloads/recommendations.py` | 100% | - |
| `kg/neo4j_adapter.py` | 99% | 1 line |
| `student/recommendation_service.py` | 97% | Factory function |
| `nlp/llm_client.py` | 95% | Streaming hybrid edge case |
| `student/student_service.py` | 95% | Factory function, one storage line |
| `student/models.py` | 94% | `accuracy` property |
| `core/logging.py` | 93% | One unreachable line |
| `student/quiz_generator.py` | 88% | Factory functions |
| `api/routes/graph.py` | 87% | Cache miss paths, error handlers |
| `api/routes/learning_path.py` | 85% | Error handlers |
| `core/subjects.py` | 85% | Some getter functions |
| `api/routes/ask.py` | 79% | Window retrieval path, error handlers |
| `kg/schema.py` | 75% | Schema validation methods |
| `rag/kg_expansion.py` | 64% | Factory functions, get_all_concepts |
| `core/rate_limit.py` | 60% | X-Forwarded-For path, decorators |
| `rag/retriever.py` | 54% | Connect, create_collection, index_chunks, factory |
| `api/routes/quiz.py` | 46% | Adaptive quiz, student profile, recommendations endpoints |
| `api/routes/subjects.py` | 44% | Most subject endpoints |
| `main.py` | 51% | Health ready checks, lifespan |
| `nlp/embeddings.py` | 24% | Most embedding operations |
| `kg/cypher_qa.py` | 24% | LangChain integration |
| `nlp/concept_extractor.py` | 17% | Most extraction logic |
| `kg/builder.py` | 14% | Knowledge graph building |
| `rag/chunker.py` | 10% | Chunking operations |
| `core/auth.py` | 0% | All auth functions |
| `api/deps.py` | 0% | All dependency injection providers |

### Test Infrastructure

- All tests use mocked services (Neo4j, OpenSearch, LLM) via `conftest.py`
- Rate limiting is disabled in tests via `limiter.enabled = False`
- Graph cache is cleared between tests
- `autouse=True` fixture `setup_test_env` sets environment variables

---

## 4. API ENDPOINT DOCUMENTATION

All endpoints are under prefix `/api/v1` (configurable via `settings.api_prefix`).

### 4.1 Root & Health Endpoints (no prefix)

#### `GET /`
- Returns: `{"name": str, "version": str, "status": "running", "llm_mode": str, "privacy_local_only": bool}`

#### `GET /health`
- Returns: `{"status": "healthy", "attribution": str}`
- This endpoint always returns "healthy" if the API process is running.

#### `GET /health/ready`
- Returns: `ReadinessResponse` with `status` ("healthy"/"degraded"/"unhealthy"), `services` dict (neo4j, opensearch, ollama), and `attribution`
- Each service has `status` (ok/degraded/error), optional `message`, optional `latency_ms`
- Neo4j and OpenSearch are critical: if either is ERROR, overall status is "unhealthy"
- Ollama ERROR alone results in "degraded" (not "unhealthy")

#### `GET /health/live`
- Returns: `{"status": "alive"}`

### 4.2 Q&A Endpoints

#### `POST /api/v1/ask`
- **Rate limit**: 10/minute
- **Accepts** (JSON body):
  - `question` (str, required, min_length=3)
  - `subject` (str|null, optional, defaults to us_history internally)
  - `use_kg_expansion` (bool, default True)
  - `use_window_retrieval` (bool, default True)
  - `window_size` (int, default 1, ge=0, le=3)
  - `top_k` (int, default 5, ge=1, le=20)
- **Returns** `QuestionResponse`:
  - `question`, `answer`, `sources` (list of dicts with text/module_title/section/score), `expanded_concepts` (list|null), `retrieved_count`, `window_expanded_count` (int|null), `model`, `attribution`
- **Source text truncation**: Source texts are truncated at 200 chars + "..."
- **Error codes**: 404 (no content), 503 (LLM/service error), 500 (internal error)
- **Behavior**: If KG expansion fails, it continues without expansion (logs warning). If no chunks retrieved, returns 404.

#### `POST /api/v1/ask/stream`
- **Rate limit**: 10/minute
- **Accepts**: Same body as `/ask`
- **Returns**: SSE (Server-Sent Events) `text/event-stream`
  - First event: `{"type": "metadata", "sources": [...], "expanded_concepts": [...], "retrieved_count": int, "window_expanded_count": int|null, "model": str, "attribution": str}`
  - Token events: `{"type": "token", "content": str}`
  - Error events: `{"type": "error", "content": str}`
  - Final event: `[DONE]`
- **Headers**: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`
- **Error codes**: Same as `/ask` for pre-streaming errors. Errors during streaming are sent as SSE error events.

### 4.3 Knowledge Graph Endpoints

#### `GET /api/v1/graph/stats`
- **Rate limit**: 30/minute
- **Accepts**: `subject` (query param, optional)
- **Returns**: `{"concept_count": int, "module_count": int, "relationship_count": int}`
- **Caching**: Results cached for 5 minutes (TTL cache in `_graph_cache` dict)
- **Error codes**: 503 (Neo4j connection), 500 (query/other error)

#### `GET /api/v1/concepts/top`
- **No rate limit**
- **Accepts**: `limit` (query param, default 20), `subject` (query param, optional)
- **Returns**: list of dicts with `name`, `score`, `is_key_term`, `frequency`
- Runs direct Cypher: `MATCH (c:{concept_label}) RETURN ... ORDER BY c.importance_score DESC LIMIT $limit`

#### `GET /api/v1/graph/data`
- **Rate limit**: 30/minute
- **Accepts**: `limit` (query param, default 100), `subject` (query param, optional)
- **Returns**: `{"nodes": [...], "edges": [...]}`
  - Nodes: `{"data": {"id": str, "label": str, "importance": float, "chapter": str|null}}`
  - Edges: `{"data": {"id": str, "source": str, "target": str, "type": str, "label": str}}`
- **Caching**: Results cached for 5 minutes
- Formatted for Cytoscape.js visualization

#### `POST /api/v1/graph/query`
- **No rate limit**
- **Accepts** (JSON body):
  - `question` (str, required)
  - `preview_only` (bool, default False)
- **Returns**: `{"question": str, "cypher": str|null, "result": list|str|null, "answer": str|null, "error": str|null}`
- If `preview_only=True`: generates Cypher but does not execute it
- Uses LangChain's GraphCypherQAChain

#### `POST /api/v1/concepts/search`
- **No rate limit**
- **Accepts** (JSON body):
  - `query` (str, required)
  - `limit` (int, default 10, ge=1, le=50)
- **Accepts** (query param): `subject` (optional)
- **Returns**: list of `{"name": str, "importance_score": float|null, "key_term": bool|null, "score": float}`
- Uses Neo4j fulltext index

#### `GET /api/v1/graph/schema`
- **No rate limit**
- **Returns**: `{"schema": str}`
- Uses LangChain's Neo4jGraph.schema

### 4.4 Quiz & Adaptive Learning Endpoints

#### `POST /api/v1/quiz/generate`
- **Rate limit**: 5/minute
- **Accepts** (query params):
  - `topic` (str, required)
  - `num_questions` (int, default 3)
  - `subject` (str, optional)
- **Returns** `Quiz`:
  - `id`, `title`, `questions` (list of `QuizQuestion`), `average_difficulty`
  - Each `QuizQuestion`: `id`, `text`, `options` (list of `{"id": str, "text": str}`), `correct_option_id`, `explanation`, `source_chunk_id`, `related_concept`, `difficulty`, `difficulty_score`
- **Error codes**: 404 (no content/value error), 503 (quiz generation failed), 500 (internal)
- Retrieves top 2 chunks for the topic, sends to LLM with structured JSON prompt

#### `POST /api/v1/quiz/generate-adaptive`
- **Rate limit**: 5/minute
- **Accepts** (query params):
  - `topic` (str, required)
  - `num_questions` (int, default 3)
  - `student_id` (str, default "default")
  - `subject` (str, optional)
- **Returns** `AdaptiveQuiz` (extends Quiz):
  - All Quiz fields plus: `student_mastery`, `target_difficulty`, `adapted` (always True)
- Difficulty targeting: mastery < 0.4 -> easy, 0.4-0.7 -> medium, > 0.7 -> hard

#### `GET /api/v1/student/profile`
- **No rate limit**
- **Accepts**: `student_id` (query param, default "default")
- **Returns**: `{"student_id": str, "overall_ability": float, "mastery_levels": dict[str, float], "updated_at": datetime}`
- Creates a new profile if student_id not found (initial mastery 0.3)

#### `POST /api/v1/student/mastery`
- **No rate limit**
- **Accepts** (JSON body):
  - `concept` (str, required)
  - `correct` (bool, required)
- **Accepts** (query param): `student_id` (default "default")
- **Returns**: `{"concept": str, "previous_mastery": float, "new_mastery": float, "target_difficulty": str, "total_attempts": int}`
- **Algorithm**: correct -> +0.15 (cap 1.0), incorrect -> -0.10 (floor 0.1)
- Persists to `data/processed/student_profiles.json` on every update

#### `GET /api/v1/student/target-difficulty`
- **No rate limit**
- **Accepts**: `concept` (query param, required), `student_id` (query param, default "default")
- **Returns**: `{"concept": str, "mastery_level": float, "target_difficulty": str}`

#### `POST /api/v1/student/reset`
- **No rate limit**
- **Accepts**: `student_id` (query param, default "default")
- **Returns**: Same as `GET /student/profile`
- Resets mastery_map to empty, overall_ability to initial (0.3)

#### `POST /api/v1/quiz/recommendations`
- **No rate limit**
- **Accepts** (JSON body):
  - `topic` (str), `question_results` (list of `{"question_id": str, "related_concept": str, "correct": bool}`), `student_id` (str, default "default"), `subject` (str|null)
- **Returns** `RecommendationResponse`:
  - `path_type` ("remediation"/"advancement"/"mixed"), `score_pct`, `remediation` (list), `advancement` (list), `summary`
- Path type: score < 50% -> remediation, > 80% -> advancement, else -> mixed

#### `GET /api/v1/student/all-difficulties`
- **No rate limit**
- **Accepts**: `student_id` (query param, default "default")
- **Returns**: `dict[str, "easy"|"medium"|"hard"]`
- Only returns difficulties for concepts already in the student's mastery map

### 4.5 Learning Path Endpoints

#### `GET /api/v1/learning-path/{concept_name}`
- **No rate limit**
- **Accepts**: `concept_name` (path param), `max_depth` (query param, default 3), `subject` (optional)
- **Returns**: `{"target_concept": str, "prerequisites": list[{"id": str, "name": str, "importance": float, "chapter": str|null, "depth": int}], "total_concepts": int}`
- Traverses PREREQUISITE relationships in Neo4j with variable-length paths

#### `GET /api/v1/concepts/{concept_name}/prerequisites`
- **No rate limit**
- **Accepts**: `concept_name` (path param), `depth` (query param, default 2), `subject` (optional)
- **Returns**: `{"concept": str, "prerequisites": list[dict], "depth": int}`

#### `GET /api/v1/concepts/{concept_name}/dependents`
- **No rate limit**
- **Accepts**: `concept_name` (path param), `depth` (query param, default 2), `subject` (optional)
- **Returns**: `{"concept": str, "dependents": list[dict], "depth": int}`

### 4.6 Subject Endpoints

#### `GET /api/v1/subjects`
- **No rate limit**
- **Returns**: `{"subjects": list[{"id": str, "name": str, "description": str, "is_default": bool}], "default_subject": str}`

#### `GET /api/v1/subjects/ids`
- **Returns**: `list[str]`

#### `GET /api/v1/subjects/{subject_id}`
- **Returns**: `{"id": str, "name": str, "description": str, "attribution": str, "opensearch_index": str, "book_count": int, "is_default": bool}`
- **Error**: 404 if subject_id not found

#### `GET /api/v1/subjects/{subject_id}/theme`
- **Returns**: `{"subject_id": str, "primary_color": str, "secondary_color": str, "accent_color": str, "chapter_colors": dict}`
- **Error**: 404 if subject_id not found

#### `GET /api/v1/subjects/{subject_id}/books`
- **Returns**: list of book configuration dicts
- **Error**: 404 if subject_id not found

---

## 5. AUTHENTICATION & SECURITY OBSERVATIONS

### API Key Authentication
- The `auth.py` module defines `verify_api_key` and `get_optional_api_key`
- When `settings.api_key` is empty string (default), all requests are allowed (development mode)
- The `deps.py` file defines `RequireApiKey` and `require_auth()` dependency
- **No endpoint in `routes/` currently uses the auth dependency**. All endpoints are publicly accessible.
- The auth module uses `secrets.compare_digest` for timing-safe comparison
- The `X-API-Key` header scheme is used

### Rate Limiting
- Implemented via `slowapi` library
- Rate limit key is derived from `X-Forwarded-For` header (first IP) or remote address
- The `X-Forwarded-For` header is trusted without validation
- Configured limits: `/ask` 10/minute, `/quiz/generate` 5/minute, `/graph/stats` and `/graph/data` 30/minute
- Several endpoints have NO rate limiting: `/concepts/top`, `/graph/query`, `/concepts/search`, `/graph/schema`, `/student/profile`, `/student/mastery`, `/student/target-difficulty`, `/student/reset`, `/quiz/recommendations`, `/student/all-difficulties`, all `/subjects/*` endpoints, all `/learning-path/*` endpoints
- Rate limiting is globally disabled in tests via `limiter.enabled = False`

### CORS
- Origins set from `CORS_ORIGINS` env var, defaults to `http://localhost:3000,http://localhost:3001`
- `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`

### Input Validation
- `question` field: `min_length=3` via Pydantic Field
- `top_k`: `ge=1, le=20`
- `window_size`: `ge=0, le=3`
- `concept_search.limit`: `ge=1, le=50`
- `MasteryUpdate`: `concept` (str, required), `correct` (bool, required) -- no min/max length on `concept`
- `student_id` parameters: no validation (any string accepted)
- The `question` text is directly included in LLM prompts via f-string interpolation
- Concept names from user input are passed directly to Cypher queries via parameterized queries ($name)

### SSL Configuration
- OpenRouter: `openrouter_verify_ssl` defaults to `False`
- OpenSearch: `opensearch_verify_certs` defaults to `False`
- OpenSearch health check uses `httpx.AsyncClient(verify=False)`

---

## 6. DATA & PERSISTENCE

### Processed Data Files
| File | Size |
|------|------|
| `books_economics.jsonl` | 3.2 MB |
| `books_us_history.jsonl` | 2.8 MB |
| `books.jsonl` | 2.8 MB |
| `chunks_economics.json` | 8.4 MB |
| `chunks_us_history.json` | 7.5 MB |
| `knowledge_graph_economics.json` | 3.4 MB |
| `knowledge_graph_us_history.json` | 2.9 MB |
| `knowledge_graph.json` | 2.9 MB |
| `student_profiles.json` | 4.7 KB |

### Student Profiles
The `student_profiles.json` file contains 2 profiles:
- `"default"`: 19 concepts tracked (mix of US History and Economics), mastery levels ranging from 0.2 to 0.92, overall_ability 0.521
- `"test_student"`: empty mastery_map, overall_ability 0.3

### Student Service Persistence
- Data stored in JSON file at `data/processed/student_profiles.json`
- Profiles loaded into memory (`dict[str, StudentProfile]`) at service initialization
- Saved to disk on every mastery update, reset, or new profile creation
- No file locking mechanism
- No concurrent access protection
- On corrupt JSON file, the service logs a warning and starts with empty profiles

---

## 7. STUDENT SIMULATION OBSERVATIONS

### Mastery Update Algorithm
- Correct answer: mastery += 0.15 (capped at 1.0)
- Incorrect answer: mastery -= 0.10 (floored at 0.1)
- Initial mastery for new concepts: 0.3 (from `settings.student_initial_mastery`)
- Overall ability: simple arithmetic mean of all concept mastery levels

### Repeated Incorrect Answers
Starting from initial mastery 0.3:
- After 1 wrong: 0.2
- After 2 wrong: 0.1 (floor reached)
- All subsequent wrong answers: stays at 0.1 (never reaches 0.0)

### Difficulty Targeting
- mastery < 0.4 -> "easy"
- mastery 0.4-0.7 -> "medium" (note: boundary 0.4 is "medium", not "easy")
- mastery > 0.7 -> "hard" (note: boundary 0.7 is "medium", not "hard")

### Quiz Submission
- There is no quiz submission endpoint. The API generates quizzes and returns them with correct answers included in the response (`correct_option_id` field)
- There is no server-side quiz answer validation
- Mastery is updated via the separate `POST /student/mastery` endpoint
- A student (or client) can submit mastery updates for any concept at any time, independent of quiz generation
- The same mastery update can be submitted multiple times -- each call increments `attempts` and adjusts mastery
- There is no deduplication or idempotency for mastery updates

### Rate Limiting on Student Endpoints
- `POST /student/mastery` has NO rate limit
- `POST /student/reset` has NO rate limit
- `GET /student/profile` has NO rate limit

---

## 8. ARCHITECTURAL PATTERNS OBSERVED

### Singleton / Registry Pattern
The following services use a global singleton or per-subject registry pattern:
- `LLMClient`: global singleton via `get_llm_client()`
- `StudentService`: global singleton via `get_student_service()`
- `OpenSearchRetriever`: per-subject registry via `get_retriever(subject_id)`
- `QuizGenerator`: per-subject registry via `get_quiz_generator(subject_id)`
- `KGExpander`: per-subject registry via `get_kg_expander(subject_id)`
- `Neo4jAdapter`: per-subject registry via `get_neo4j_adapter(subject_id)`
- `RecommendationService`: per-subject registry via `get_recommendation_service(subject)`
- `WindowRetriever`: global singleton via `get_window_retriever()`
- `CypherQAService`: global singleton via `get_cypher_qa_service()`

### Dependency Injection
- `deps.py` defines FastAPI `Depends()` providers for all major services
- However, **none of these DI providers are used by the route handlers**
- Route handlers import factory functions directly: `from backend.app.rag.retriever import get_retriever`
- The `deps.py` dependency injection providers have 0% test coverage

### Multi-Subject Isolation
- Implemented via Neo4j label prefixes (e.g., `us_history_Concept`, `biology_Concept`)
- All subjects share the same Neo4j database (`neo4j`)
- Each subject has its own OpenSearch index (e.g., `textbook_chunks_us_history`)
- Subject configuration loaded from `config/subjects.yaml` and cached via `@lru_cache(maxsize=1)`

### Caching
- Graph stats and data endpoints: in-memory dict with 5-minute TTL
- Subjects config: LRU cache (maxsize=1) -- effectively cached forever unless `clear_subjects_cache()` called
- Service singletons: cached in module-level globals

### Error Handling
- Custom exception hierarchy rooted at `AdaptiveKGException`
- KG expansion failures are caught and silently continued (warning logged)
- Window retrieval failures are caught and silently continued (warning logged)
- LLM errors return 503
- Content-not-found returns 404
- All other unhandled errors return 500 with error message in detail

---

## 9. LLM CLIENT OBSERVATIONS

### Modes
- `local`: Ollama (default)
- `remote`: OpenRouter
- `hybrid`: tries local first, falls back to remote on `LLMConnectionError` or `LLMGenerationError`

### Retry Configuration
- Non-streaming calls: up to 3 retries with exponential backoff (1s to 10s)
- Only `LLMConnectionError` triggers retry (not `LLMGenerationError`)
- Streaming calls: no retry mechanism

### Prompt Construction
- Answer prompts include numbered context passages `[1] text`, `[2] text`
- Quiz prompts request JSON output with structured schema
- Quiz JSON cleaned of markdown code blocks before parsing

---

## 10. RETRIEVER OBSERVATIONS

### Retrieval Modes
- `knn`: Vector-only search using OpenSearch kNN
- `hybrid` (default): BM25 text search + kNN vector search with reciprocal rank fusion (RRF, k=60)

### Hybrid Search
- BM25 fields: `text^3`, `module_title^2`, `section`, `key_terms^2`
- Fuzziness: AUTO
- RRF formula: `score(doc) = sum(1/(k + rank))` where k=60

### Window Retrieval
- Requires `vector_backend` to be "neo4j" or "hybrid" (NOT "opensearch" which is default)
- The default `vector_backend` is "opensearch", meaning window retrieval is effectively disabled by default
- Uses NEXT relationships in Neo4j to get surrounding chunks

---

## 11. FRONTEND API CLIENT OBSERVATIONS

- Uses `axios` with 30-second timeout
- Streaming uses native `fetch()` API (not axios)
- `generateQuiz` sends parameters as query params (not body)
- `askQuestion` sends `subject` in request body
- Error interceptor logs but re-throws all errors
- `healthCheck` accepts both "healthy" and "ok" as healthy statuses
- `getTopConcepts` silently returns empty array on failure

---

## 12. CONFIGURATION OBSERVATIONS

### Subjects Defined but Not All Provisioned
- 4 subjects configured: `us_history`, `biology`, `economics`, `world_history`
- Data files exist for: `us_history` (chunks + KG), `economics` (chunks + KG)
- No data files exist for: `biology`, `world_history`
- `world_history` uses `source_type: "openstax_web"` (different from github_raw used by others)

### Default Values
- `privacy_local_only`: True (default)
- `llm_mode`: "local" (default)
- `embedding_device`: "cuda" (default) -- this would fail on CPU-only machines
- `reranker_device`: "cuda" (default) -- same issue
- `retrieval_mode`: "hybrid" (default)
- `vector_backend`: "opensearch" (default)
- `student_initial_mastery`: 0.3

---

## 13. ADDITIONAL FACTS

### Middleware
- `RequestIDMiddleware`: attaches UUID to every request via `X-Request-ID` header, accepts client-provided IDs

### OpenSearch Connection
- The `OpenSearchRetriever.connect()` is called immediately in `get_retriever()` factory
- If OpenSearch is unreachable, the retriever creation fails and the error propagates

### The `deps.py` Module
- The `get_neo4j_adapter()` dependency is a generator (uses `yield`) for proper cleanup
- Other deps are simple functions that call global singletons
- The `require_auth()` function returns `Depends(verify_api_key)` as a value, which is structurally unusual -- it returns a FastAPI `Depends` object rather than using it as a decorator or parameter default

### Git Status at Observation Time
Untracked files:
- `AGENTIC_TEAM_PROMPT.md`
- `data/processed/chunks_economics.json`
- `data/processed/chunks_us_history.json`

---

*Report generated by The Witness. All statements are factual observations of actual system behavior.*
