#!/usr/bin/env bash
# ============================================================
# Demo Data Seeder
# ============================================================
# One-command script to load demo data into Neo4j + OpenSearch.
#
# Usage:
#   bash scripts/seed_demo.sh              # Seed all subjects
#   bash scripts/seed_demo.sh us_history   # Seed specific subject
#   bash scripts/seed_demo.sh --reset      # Clear & re-seed everything
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Parse arguments
SUBJECT="${1:-}"
RESET=false
if [ "$SUBJECT" = "--reset" ]; then
    RESET=true
    SUBJECT=""
fi

# Define demo subjects (those with data available)
DEMO_SUBJECTS=("us_history" "economics")

echo ""
echo "========================================"
echo "  Adaptive Knowledge Graph - Demo Seeder"
echo "========================================"
echo ""

# -------------------------------------------------------
# Step 0: Pre-flight checks
# -------------------------------------------------------
info "Checking prerequisites..."

# Check Docker services
if ! docker compose -f infra/compose/compose.yaml ps --format json 2>/dev/null | grep -q "running"; then
    warn "Docker services may not be running. Starting them..."
    docker compose -f infra/compose/compose.yaml up -d neo4j opensearch
    info "Waiting 15s for services to start..."
    sleep 15
fi

# Check Neo4j
if curl -sf http://localhost:7474 > /dev/null 2>&1; then
    ok "Neo4j is reachable"
else
    error "Neo4j is not reachable at localhost:7474"
    echo "  Start it with: docker compose -f infra/compose/compose.yaml up -d neo4j"
    exit 1
fi

# Check OpenSearch
if curl -sf -k https://localhost:9200 -u admin:Admin@123 > /dev/null 2>&1; then
    ok "OpenSearch is reachable"
else
    error "OpenSearch is not reachable at localhost:9200"
    echo "  Start it with: docker compose -f infra/compose/compose.yaml up -d opensearch"
    exit 1
fi

ok "All prerequisites met"
echo ""

# -------------------------------------------------------
# Step 1: Determine which subjects to seed
# -------------------------------------------------------
if [ -n "$SUBJECT" ]; then
    SUBJECTS=("$SUBJECT")
else
    SUBJECTS=("${DEMO_SUBJECTS[@]}")
fi

info "Will seed subjects: ${SUBJECTS[*]}"
echo ""

# -------------------------------------------------------
# Step 2: Ingest books (fetch + parse + normalize)
# -------------------------------------------------------
for subj in "${SUBJECTS[@]}"; do
    info "[$subj] Ingesting book data..."

    JSONL="data/processed/books_${subj}.jsonl"

    if [ -f "$JSONL" ] && [ "$RESET" = false ]; then
        ok "[$subj] JSONL already exists at $JSONL, skipping ingest"
    else
        poetry run python scripts/ingest_books.py --subject "$subj"
        if [ -f "$JSONL" ]; then
            ok "[$subj] Book data ingested -> $JSONL"
        else
            error "[$subj] Ingest failed — $JSONL not created"
            exit 1
        fi
    fi
done

echo ""

# -------------------------------------------------------
# Step 3: Build Knowledge Graphs
# -------------------------------------------------------
for subj in "${SUBJECTS[@]}"; do
    info "[$subj] Building knowledge graph..."
    poetry run python scripts/build_knowledge_graph.py --subject "$subj"
    ok "[$subj] Knowledge graph built"
done

echo ""

# -------------------------------------------------------
# Step 4: Index to OpenSearch
# -------------------------------------------------------
for subj in "${SUBJECTS[@]}"; do
    info "[$subj] Indexing to OpenSearch..."
    poetry run python scripts/index_to_opensearch.py --subject "$subj"
    ok "[$subj] Indexed to OpenSearch"
done

echo ""

# -------------------------------------------------------
# Step 5: Seed student profile
# -------------------------------------------------------
info "Seeding demo student profile..."
poetry run python scripts/seed_student_profile.py
ok "Student profile seeded"

echo ""

# -------------------------------------------------------
# Step 6: Warm-up check
# -------------------------------------------------------
info "Running quick API health check..."
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    ok "API is healthy"
else
    warn "API is not running. Start it with: make run-api"
fi

echo ""
echo "========================================"
echo -e "  ${GREEN}Demo data seeded successfully!${NC}"
echo "========================================"
echo ""
echo "  Next steps:"
echo "  1. Start API:      make run-api"
echo "  2. Start frontend:  cd frontend && npm run dev"
echo "  3. Open browser:   http://localhost:3000"
echo "  4. API docs:       http://localhost:8000/docs"
echo ""
