#!/usr/bin/env bash
#
# Prepare a local OpenStax client-demo environment.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "== Client demo prep =="

require_command() {
    if ! command -v "$1" > /dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

require_command docker
require_command poetry
require_command bash
require_command curl

if [ ! -f ".env" ] && [ -f ".env.demo.example" ]; then
    cp .env.demo.example .env
    echo "Created .env from .env.demo.example"
fi

echo "Starting Neo4j and OpenSearch..."
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch

echo "Seeding OpenStax demo data..."
bash scripts/seed_demo.sh

echo "Seeding synthetic student profile in SQLite..."
poetry run python scripts/seed_student_profile.py \
    --student-id default \
    --output data/processed/student_profiles.sqlite3

echo ""
echo "Client demo prep complete."
echo "Next:"
echo "  1. Start API:      make run-api"
echo "  2. Start frontend: cd frontend && npm run dev"
echo "  3. Check demo:     make demo-client-check"
echo "  4. Open status:    http://localhost:3000/demo-status"
