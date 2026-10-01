#!/usr/bin/env bash
#
# make quickstart: from a fresh clone to a seeded local stack in one command.
#
#   1. prerequisites: Docker + Compose >= 2.24, Poetry, Node satisfying frontend engines.node
#   2. backend dependencies (poetry install --only main) and the spaCy model en_core_web_sm
#   3. Ollama: server reachable, model pulled, a 1-token generation works
#   4. frontend dependencies (npm ci)
#   5. Neo4j + OpenSearch: docker compose up -d --wait
#   6. seed US History and Economics (subjects that are already seeded are skipped)
#   7. print the next steps
#
# Environment: SKIP_OLLAMA_CHECK=1 (skip step 3), SKIP_FRONTEND=1 (skip Node and step 4),
# plus the host ports and passwords documented in infra/compose/compose.yaml.
# Re-running is safe: installed dependencies and seeded subjects are reused.

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$AKG_ROOT"

SKIP_FRONTEND="${SKIP_FRONTEND:-}"
STARTED_AT=$(date +%s)

echo "=========================================="
echo "Adaptive Knowledge Graph - quickstart"
echo "=========================================="

step "1/6 Checking prerequisites"
require_docker
ok "Docker and Docker Compose $(compose_version)"
require_command poetry "https://python-poetry.org/docs/#installation"
ok "$(poetry --version 2>&1 | head -1)"
require_command curl
if [ "$SKIP_FRONTEND" = "1" ]; then
    info "Skipping the frontend (SKIP_FRONTEND=1)"
else
    require_command node "https://nodejs.org (or fnm/nvm/volta with .node-version)"
    require_command npm
    have python3 || die "python3 is required to check the Node version"
    python3 scripts/stack_check.py node \
        || die "Node $(node --version) cannot install the frontend. Switch Node, or rerun with SKIP_FRONTEND=1."
fi

step "2/6 Installing backend dependencies (first run downloads several GB)"
poetry install --only main --no-interaction
AKG_POETRY_READY=""
poetry_env_ready || die "The Poetry environment is not usable after 'poetry install'."
ensure_spacy_model

step "3/6 Checking Ollama (1-token generation; the first call loads the model)"
check_ollama_or_die

step "4/6 Installing frontend dependencies"
if [ "$SKIP_FRONTEND" = "1" ]; then
    info "Skipped (SKIP_FRONTEND=1)"
elif [ -f frontend/node_modules/.package-lock.json ] \
    && [ frontend/node_modules/.package-lock.json -nt frontend/package-lock.json ]; then
    ok "frontend/node_modules is up to date"
else
    (cd frontend && npm ci --no-audit --no-fund)
fi

step "5/6 Starting Neo4j and OpenSearch"
compose up -d --wait --wait-timeout 300 neo4j opensearch \
    || die "The databases did not become healthy; see: docker compose -f infra/compose/compose.yaml logs neo4j opensearch"
ok "Neo4j and OpenSearch are healthy"

step "6/6 Seeding US History and Economics (embedding every chunk takes a while on CPU)"
bash scripts/seed_demo.sh "${AKG_DEMO_SUBJECTS[@]}"

elapsed=$(($(date +%s) - STARTED_AT))
echo ""
echo "=========================================="
echo "${C_GREEN}Quickstart complete${C_RESET} in $((elapsed / 60))m $((elapsed % 60))s"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  make run-api                  # API on http://localhost:${API_PORT:-8000} (docs at /docs)"
if [ "$SKIP_FRONTEND" != "1" ]; then
    echo "  make run-frontend             # UI on http://localhost:${FRONTEND_PORT:-3000}"
fi
echo "  make doctor                   # re-check every dependency"
echo "  make down                     # stop the containers (data volumes are kept)"
echo ""
echo "Neo4j Browser: http://localhost:${NEO4J_HTTP_PORT:-7474} (user neo4j)"
