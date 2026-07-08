#!/usr/bin/env bash
#
# Reset transient client-demo learner state without deleting source content.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

API_URL="${API_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-}"

echo "== Client demo reset =="

echo "Clearing transient demo check artifacts..."
rm -f \
    /tmp/adaptive_kg_demo_health.json \
    /tmp/adaptive_kg_demo_graph_stats.json \
    /tmp/adaptive_kg_demo_ask.json \
    /tmp/adaptive_kg_demo_quiz.json \
    /tmp/adaptive_kg_demo_profile.json \
    /tmp/adaptive_kg_demo_status.json \
    /tmp/adaptive_kg_demo_status.pretty.json

if curl -sf "$API_URL/health" > /dev/null 2>&1; then
    echo "API is running; resetting API-visible default profile..."
    CURL_ARGS=(-sf -X POST "$API_URL/api/v1/student/reset")
    if [ -n "$API_KEY" ]; then
        CURL_ARGS=(-sf -X POST -H "X-API-Key: $API_KEY" "$API_URL/api/v1/student/reset")
    fi
    if curl "${CURL_ARGS[@]}" > /dev/null; then
        echo "API profile reset."
    else
        echo "API profile reset failed. If API_KEY is configured, export API_KEY and retry."
        exit 1
    fi
else
    echo "API is not running; reseeding SQLite profile for the next API start."
    poetry run python scripts/seed_student_profile.py \
        --student-id default \
        --output data/processed/student_profiles.sqlite3
fi

echo "Demo learner state reset."
