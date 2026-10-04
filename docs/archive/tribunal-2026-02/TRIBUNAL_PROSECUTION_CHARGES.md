# Tribunal Prosecution Charges

**42 charges filed. 42 vulnerabilities confirmed via failing tests.**

Test file: `backend/tests/test_tribunal_prosecution.py`

Run: `poetry run pytest backend/tests/test_tribunal_prosecution.py -v --tb=short`

---

## Summary by Severity

| Severity | Count | Category |
|----------|-------|----------|
| CRITICAL | 8 | Authentication, Authorization, Credential Leakage |
| HIGH | 14 | Input Validation, Injection, Data Integrity |
| MEDIUM | 12 | Rate Limiting, CORS, Quiz Cheating, Concurrency |
| LOW | 8 | Documentation Exposure, Response Quality, Missing Bounds |

---

## CRITICAL Charges

### C1. No Authentication on Student Endpoints (5 tests)
- `test_student_profile_no_auth` -- Student profiles accessible without any authentication
- `test_student_mastery_update_no_auth` -- Mastery levels can be modified without authentication
- `test_student_reset_no_auth` -- Student progress can be WIPED without authentication
- `test_graph_query_no_auth` -- Natural language Cypher execution requires no authentication
- `test_access_other_student_profile` -- Any user can access any student's profile by guessing student_id

### C2. Credential Leakage in Error Responses (3 tests)
- `test_ask_internal_error_leaks_details` -- 500 errors expose passwords, internal URIs (`bolt://internal-neo4j:7687 (user: admin, password: s3cret)`)
- `test_graph_stats_error_leaks_neo4j_details` -- Graph stats errors expose Neo4j auth credentials in the HTTP response body
- `test_quiz_error_leaks_llm_config` -- Quiz errors expose API keys (`API_KEY=sk-live-abc123`) and internal hostnames

---

## HIGH Charges

### H1. Missing Input Validation on Query Parameters (10 tests)
- `test_ask_whitespace_only_question` -- Whitespace-only strings pass min_length=3 check (e.g. `"   "`)
- `test_ask_extremely_long_question` -- No max_length on question field; accepts >1MB payloads
- `test_quiz_generate_empty_topic` -- Empty string accepted as quiz topic
- `test_quiz_generate_huge_num_questions` -- No upper bound on num_questions (accepts 10,000+)
- `test_quiz_generate_zero_questions` -- num_questions=0 accepted
- `test_quiz_generate_negative_questions` -- num_questions=-1 accepted
- `test_concept_search_empty_query` -- Empty search query accepted
- `test_graph_data_negative_limit` -- Negative limit causes 500 error instead of 422
- `test_graph_data_huge_limit` -- No upper bound on graph data limit (accepts 1,000,000)
- `test_top_concepts_negative_limit` -- Negative limit on top concepts causes 500

### H2. Injection Vulnerabilities (4 tests)
- `test_ask_xss_in_question` -- XSS payloads (`<script>alert("XSS")</script>`) echoed back verbatim in response
- `test_ask_nosql_injection_in_subject` -- Injection payloads in subject cause 500 instead of 404 validation error
- `test_graph_query_destructive_cypher` -- Destructive Cypher queries (DETACH DELETE) not blocked by `/graph/query`
- `test_concept_search_wildcard_injection` -- Lucene wildcard `*:*` passed unsanitized to fulltext search

---

## MEDIUM Charges

### M1. Student Model Manipulation (4 tests)
- `test_mastery_spam_to_max` -- Spamming correct answers instantly maxes mastery (0.3 -> 1.0 in 5 requests); no cooldown or diminishing returns
- `test_mastery_manipulation_via_arbitrary_concept` -- Can create mastery records for concepts that don't exist in the knowledge graph
- `test_mastery_update_for_other_student` -- Can modify any student's mastery by passing arbitrary student_id
- `test_reset_other_student_profile` -- Profile reset wipes ALL mastery data with no confirmation or undo

### M2. Quiz Cheating (2 tests)
- `test_quiz_correct_answer_leaked_in_response` -- `correct_option_id` included in quiz JSON response; client can read answers before submitting
- `test_quiz_no_answer_submission_endpoint` -- No quiz submission endpoint exists; mastery updates are decoupled from quiz completion, enabling cheating

### M3. Rate Limiting Bypasses (3 tests)
- `test_rate_limit_bypass_via_x_forwarded_for` -- Rate limiter trusts client-provided X-Forwarded-For header; rotating IPs bypasses all limits
- `test_student_endpoints_no_rate_limit` -- Student mastery endpoints have no rate limiting at all
- `test_graph_query_rate_limit` -- Graph query endpoint (Cypher execution) has no rate limiting

### M4. CORS Misconfiguration (1 test)
- `test_cors_wildcard_methods` -- CORS allows ALL HTTP methods (DELETE, PUT, PATCH) via `allow_methods=["*"]`

### M5. Concurrency Data Loss (1 test)
- `test_file_based_storage_concurrent_writes` -- Two service instances writing to same JSON file causes complete data loss for one student

### M6. Missing Depth/Limit Bounds (2 tests in input validation)
- `test_learning_path_negative_depth` -- Negative max_depth accepted (no ge=0 constraint)
- `test_learning_path_huge_depth` -- max_depth=99999 accepted; could cause expensive graph traversals (DoS vector)

---

## LOW Charges

### L1. Subject Validation Inconsistency (2 tests)
- `test_ask_with_nonexistent_subject` -- Non-existent subject returns 500 instead of 404 with clear message
- `test_quiz_with_nonexistent_subject` -- Non-existent subject in quiz endpoint returns 200 (mock bypasses validation)

### L2. Documentation Exposure (3 tests)
- `test_openapi_schema_exposed` -- `/openapi.json` publicly accessible, exposing all endpoint schemas
- `test_docs_endpoint_exposed` -- Swagger UI (`/docs`) publicly accessible
- `test_redoc_endpoint_exposed` -- ReDoc (`/redoc`) publicly accessible

### L3. Service Failure Handling (2 tests)
- `test_ask_when_llm_returns_empty` -- Empty LLM response passed through to client without validation
- `test_health_ready_returns_200_even_when_unhealthy` -- `/health/ready` returns HTTP 200 even when all services are down; should return 503 for load balancer integration

---

## Passed Tests (22 tests — defenses that held)

These areas were tested and found to be properly defended:

- Empty string question rejected (min_length=3 works)
- Two-character question rejected
- top_k bounds enforced (ge=1, le=20)
- window_size bounds enforced (ge=0, le=3)
- Cypher injection via parameterized queries (concept_name uses $name parameters)
- Subject ID path traversal rejected (../../etc/passwd returns 404)
- SQL injection in subject ID rejected
- CORS blocks unknown origins (evil.example.com)
- CORS custom header filtering works for standard cases
- X-Request-ID header present in responses
- Non-JSON content types properly rejected with 422
- Validation error format consistent across endpoints
- 500 errors include 'detail' field
- Concurrent mastery updates within a single service instance survive (no crashes)
- HEAD and OPTIONS methods handled appropriately
- Prompt injection in quiz topic doesn't crash the system

---

## Key Architectural Findings

1. **Zero authentication on student data** -- The entire student model (profiles, mastery, reset) is completely unauthenticated. Any HTTP client can read, modify, or delete any student's learning progress.

2. **Error messages are too honest** -- Exception `str()` is passed directly to HTTP responses. Internal hostnames, database credentials, and API keys embedded in error messages are forwarded to the client.

3. **Quiz answers shipped to the client** -- The `correct_option_id` field is included in the quiz response body. Any student inspecting network traffic or the browser console can see all correct answers before submitting.

4. **Rate limiting is IP-based and trusts X-Forwarded-For** -- Without a reverse proxy stripping/overwriting this header, any client can bypass rate limits by rotating the header value.

5. **File-based student storage has no concurrency protection** -- Two concurrent processes writing to the same JSON file can corrupt or overwrite each other's data.

6. **Graph query endpoint executes arbitrary Cypher** -- `/graph/query` translates natural language to Cypher and executes it, including destructive operations like `DETACH DELETE`, with no authentication or query validation.
