#!/usr/bin/env bash
#
# Prepare a local OpenStax client-demo environment (expects dependencies to be installed;
# `make quickstart` also installs them).
#
# Environment: SKIP_OLLAMA_CHECK=1 skips the Ollama generation probe.

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$AKG_ROOT"

echo "== Client demo prep =="

require_docker
require_command poetry "https://python-poetry.org/docs/#installation"
require_command curl
poetry_env_ready || die "Backend dependencies are not installed; run: make install"

if [ ! -f ".env" ] && [ -f ".env.demo.example" ]; then
    cp .env.demo.example .env
    info "Created .env from .env.demo.example"
fi

step "Checking Ollama"
check_ollama_or_die

step "Checking the spaCy model"
ensure_spacy_model

step "Starting Neo4j and OpenSearch"
compose up -d --wait --wait-timeout 300 neo4j opensearch

step "Seeding OpenStax demo data and the synthetic learner profile"
bash scripts/seed_demo.sh

echo ""
echo "Client demo prep complete."
echo "Next:"
echo "  1. Start API:      make run-api"
echo "  2. Start frontend: make run-frontend"
echo "  3. Check demo:     make demo-client-check"
echo "  4. Open status:    http://localhost:${FRONTEND_PORT:-3000}/demo-status"
