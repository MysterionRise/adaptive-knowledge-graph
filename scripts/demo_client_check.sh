#!/usr/bin/env bash
#
# Validate local client-demo readiness before rehearsal.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

API_URL="${API_URL:-http://localhost:8000}"
API_URL="${API_URL%/}"
API_KEY="${API_KEY:-}"

HEALTH_JSON="/tmp/adaptive_kg_demo_health.json"
GRAPH_JSON="/tmp/adaptive_kg_demo_graph_stats.json"
ASK_JSON="/tmp/adaptive_kg_demo_ask.json"
QUIZ_JSON="/tmp/adaptive_kg_demo_quiz.json"
PROFILE_JSON="/tmp/adaptive_kg_demo_profile.json"
STATUS_JSON="/tmp/adaptive_kg_demo_status.json"
STATUS_PRETTY_JSON="/tmp/adaptive_kg_demo_status.pretty.json"

echo "== Client demo check =="

fail() {
    echo "ERROR: $1" >&2
    exit 1
}

pass() {
    echo "OK: $1"
}

require_command() {
    if ! command -v "$1" > /dev/null 2>&1; then
        fail "Missing required command: $1"
    fi
}

json_headers=(-H "Content-Type: application/json")
auth_headers=()
if [ -n "$API_KEY" ]; then
    json_headers+=(-H "X-API-Key: $API_KEY")
    auth_headers+=(-H "X-API-Key: $API_KEY")
fi

require_command curl
require_command poetry
require_command node

NODE_MAJOR="$(node -p "Number(process.versions.node.split('.')[0])")"
if [ "$NODE_MAJOR" -lt 20 ]; then
    fail "Node 20+ is required for the client demo. Current version: $(node --version)"
fi
pass "Node version is demo-compatible: $(node --version)"

bash scripts/validate_setup.sh

echo "Checking API readiness..."
curl -sf --max-time 30 "$API_URL/health/ready" > "$HEALTH_JSON" \
    || fail "API readiness failed at $API_URL/health/ready"
poetry run python - "$HEALTH_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = data.get("status")
services = data.get("services", {})
errors = [
    name for name, service in services.items()
    if isinstance(service, dict) and service.get("status") == "error"
]
if status not in {"healthy", "degraded"} or errors:
    raise SystemExit(f"API readiness is not acceptable: status={status}, errors={errors}")
PY
pass "API readiness endpoint is healthy/degraded without service errors"

echo "Checking US History graph stats..."
curl -sf --max-time 30 "$API_URL/api/v1/graph/stats?subject=us_history" > "$GRAPH_JSON" \
    || fail "Graph stats endpoint failed"
poetry run python - "$GRAPH_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
concept_count = int(data.get("concept_count") or data.get("Concept_count") or 0)
relationship_count = int(data.get("relationship_count") or 0)
if concept_count <= 0:
    raise SystemExit(f"Graph has no indexed concepts: concept_count={concept_count}")
if relationship_count <= 0:
    raise SystemExit(f"Graph has no relationships: relationship_count={relationship_count}")
PY
pass "US History graph has concepts and relationships"

echo "Checking protected synthetic student profile..."
curl -sf --max-time 30 "${auth_headers[@]}" "$API_URL/api/v1/student/profile" > "$PROFILE_JSON" \
    || fail "Student profile endpoint failed. If API_KEY is configured, export API_KEY before running this check."
poetry run python - "$PROFILE_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("student_id") != "default":
    raise SystemExit(f"Unexpected student profile: {data.get('student_id')}")
if not isinstance(data.get("mastery_levels"), dict):
    raise SystemExit("Student profile is missing mastery_levels")
PY
pass "Protected student profile is reachable"

echo "Checking KG-RAG chat endpoint..."
ASK_PAYLOAD='{"question":"What caused the American Revolution?","subject":"us_history","top_k":3,"use_kg_expansion":true}'
curl -sf --max-time 120 "${json_headers[@]}" -d "$ASK_PAYLOAD" "$API_URL/api/v1/ask" > "$ASK_JSON" \
    || fail "KG-RAG ask endpoint failed"
poetry run python - "$ASK_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
answer = data.get("answer") or ""
sources = data.get("sources") or []
expanded = data.get("expanded_concepts") or []
if len(answer.strip()) < 40:
    raise SystemExit("KG-RAG answer is missing or too short")
if not sources:
    raise SystemExit("KG-RAG answer returned no citations")
if not expanded:
    raise SystemExit("KG-RAG answer returned no expanded concepts")
PY
pass "KG-RAG chat endpoint returns answer, citations, and expanded concepts"

echo "Checking quiz endpoint..."
curl -sf --max-time 120 -X POST \
    "${json_headers[@]}" \
    "$API_URL/api/v1/quiz/generate?topic=American%20Revolution&num_questions=1&subject=us_history" \
    > "$QUIZ_JSON" || fail "Quiz generation endpoint failed"
poetry run python - "$QUIZ_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
questions = data.get("questions") or []
if not questions:
    raise SystemExit("Quiz response returned no questions")
first = questions[0]
if not first.get("text") or not first.get("options"):
    raise SystemExit("Quiz question is missing text or options")
PY
pass "Quiz endpoint returns a usable question"

echo "Checking demo readiness endpoint..."
curl -sf --max-time 30 "$API_URL/api/v1/demo/status" > "$STATUS_JSON" \
    || fail "Demo readiness endpoint failed"
poetry run python -m json.tool "$STATUS_JSON" > "$STATUS_PRETTY_JSON"
cat "$STATUS_PRETTY_JSON"

echo "Checking latest eval gate..."
poetry run python scripts/check_demo_eval.py

poetry run python - "$STATUS_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("status") != "ready":
    actions = data.get("next_actions") or []
    detail = "; ".join(actions) if actions else "No next_actions returned"
    raise SystemExit(f"Demo status is not ready: {data.get('status')}. {detail}")
PY
pass "Demo readiness endpoint reports ready"

echo "Client demo check passed."
