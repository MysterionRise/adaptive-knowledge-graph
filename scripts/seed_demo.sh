#!/usr/bin/env bash
# ============================================================
# Demo data seeder: Neo4j knowledge graph + OpenSearch chunks + demo learner profile.
#
# Usage:
#   bash scripts/seed_demo.sh                    # us_history + economics
#   bash scripts/seed_demo.sh economics          # one subject
#   bash scripts/seed_demo.sh --reset [subject]  # re-ingest, rebuild the graph, recreate the index
#
# Subjects that already have concepts in Neo4j and chunks in OpenSearch are skipped unless
# --reset is given. Starts the compose databases when they are not reachable and waits until
# they accept requests (a running container is not necessarily a ready one).
#
# Environment: NEO4J_BOLT_PORT / OPENSEARCH_PORT (host ports, see infra/compose/compose.yaml),
# DATA_PROCESSED_DIR, STUDENT_PROFILES_DB (backend settings), KG_COOCCURRENCE_THRESHOLD[_<SUBJECT>]
# and KG_PREREQ_PATTERNS=1 (graph tuning, see scripts/build_knowledge_graph.py).
# ============================================================

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$AKG_ROOT"

usage() {
    # The header comment, up to its closing "# ====" line
    awk 'NR > 2 && /^# ====/ { exit } NR > 2 { sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
}

RESET=false
SUBJECTS=()
for arg in "$@"; do
    case "$arg" in
        --reset) RESET=true ;;
        -h | --help)
            usage
            exit 0
            ;;
        -*) die "Unknown option: $arg (see --help)" ;;
        *) SUBJECTS+=("$arg") ;;
    esac
done
if [ ${#SUBJECTS[@]} -eq 0 ]; then
    SUBJECTS=("${AKG_DEMO_SUBJECTS[@]}")
fi

echo ""
echo "========================================"
echo "  Adaptive Knowledge Graph - Demo Seeder"
echo "========================================"

step "Checking prerequisites"
require_command poetry "https://python-poetry.org/docs/#installation"
poetry_env_ready || die "Backend dependencies are not installed; run: make install"
ensure_databases
info "Will seed subjects: ${SUBJECTS[*]}"

for subj in "${SUBJECTS[@]}"; do
    step "[$subj] Seeding"
    jsonl="$AKG_PROCESSED_DIR/books_${subj}.jsonl"

    if [ "$RESET" = true ] || [ ! -f "$jsonl" ]; then
        info "[$subj] Ingesting books..."
        poetry run python scripts/ingest_books.py --subject "$subj"
        [ -f "$jsonl" ] || die "[$subj] Ingest did not create $jsonl"
    else
        ok "[$subj] Using $jsonl"
    fi

    status="$(poetry run python scripts/stack_check.py seed-status --subject "$subj")"
    concepts="${status%% *}"
    chunks="${status##* }"
    case "$concepts$chunks" in
        '' | *[!0-9]*) die "[$subj] Unexpected seed-status output: '$status'" ;;
    esac

    if [ "$RESET" = true ] || [ "$concepts" -eq 0 ]; then
        info "[$subj] Building the knowledge graph..."
        poetry run python scripts/build_knowledge_graph.py --subject "$subj" --clear
    else
        ok "[$subj] Graph already has $concepts concepts (use --reset to rebuild)"
    fi

    # Idempotent: fulltext concept index (concept search, KG expansion) and vector/lookup indexes
    poetry run python scripts/create_neo4j_indexes.py --subject "$subj" --skip-tests

    if [ "$RESET" = true ] || [ "$chunks" -eq 0 ]; then
        info "[$subj] Indexing chunks into OpenSearch (embeds every chunk; the first run downloads BAAI/bge-m3)..."
        index_args=(--subject "$subj" --skip-tests)
        if [ "$RESET" = true ]; then
            index_args+=(--recreate)
        fi
        poetry run python scripts/index_to_opensearch.py "${index_args[@]}"
    else
        ok "[$subj] OpenSearch already has $chunks chunks (use --reset to reindex)"
    fi
done

step "Seeding the demo learner profile"
poetry run python scripts/seed_student_profile.py --student-id default --output "$AKG_STUDENT_DB"

API_URL="${API_URL:-http://localhost:${API_PORT:-8000}}"
if curl -sf --max-time 5 "$API_URL/health" > /dev/null 2>&1; then
    ok "API is running at $API_URL"
else
    info "API is not running yet (start it with: make run-api)"
fi

echo ""
echo "========================================"
echo "  ${C_GREEN}Demo data seeded${C_RESET}: ${SUBJECTS[*]}"
echo "========================================"
echo ""
echo "  Next steps:"
echo "  1. Start API:       make run-api"
echo "  2. Start frontend:  make run-frontend"
echo "  3. Open browser:    http://localhost:${FRONTEND_PORT:-3000}"
echo "  4. API docs:        $API_URL/docs"
echo ""
