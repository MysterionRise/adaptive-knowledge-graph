#!/usr/bin/env bash
#
# Run Full Data Pipeline for Adaptive Knowledge Graph
#
# This script executes all steps to populate the knowledge graph:
# 1. Fetch OpenStax Biology 2e textbook
# 2. Parse HTML to structured JSON
# 3. Normalize content with attribution
# 4. Build knowledge graph in Neo4j
# 5. Index chunks to Qdrant for RAG
#
# Prerequisites:
# - Neo4j running on localhost:7687
# - Qdrant running on localhost:6333
# - Ollama with llama3.1 model (optional, for LLM features)
# - Poetry environment activated
#
# Usage:
#   ./run_pipeline.sh              # Run all steps
#   ./run_pipeline.sh --skip-fetch # Skip download (if already done)
#   ./run_pipeline.sh --step 3     # Run only step 3 and onwards

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR="${PROJECT_ROOT}/data"
SCRIPTS_DIR="${PROJECT_ROOT}/scripts"
LOG_FILE="${PROJECT_ROOT}/pipeline.log"

# Parse arguments
SKIP_FETCH=false
START_STEP=1

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-fetch)
      SKIP_FETCH=true
      shift
      ;;
    --step)
      START_STEP="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --skip-fetch    Skip downloading OpenStax textbook (use existing data)"
      echo "  --step N        Start from step N (1-5)"
      echo "  --help          Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

check_service() {
    local service_name=$1
    local service_url=$2

    log_info "Checking $service_name at $service_url..."

    if curl -s -f "$service_url" > /dev/null 2>&1; then
        log_success "$service_name is running"
        return 0
    else
        log_error "$service_name is not accessible at $service_url"
        return 1
    fi
}

run_step() {
    local step_num=$1
    local step_name=$2
    local script_name=$3
    local duration_est=$4

    if [ "$START_STEP" -gt "$step_num" ]; then
        log_info "Skipping Step $step_num: $step_name (starting from step $START_STEP)"
        return 0
    fi

    echo ""
    log_info "=========================================="
    log_info "Step $step_num: $step_name"
    log_info "Estimated time: $duration_est"
    log_info "=========================================="

    local start_time=$(date +%s)

    if poetry run python "$SCRIPTS_DIR/$script_name" 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_success "Step $step_num completed in ${duration}s"
        return 0
    else
        log_error "Step $step_num failed!"
        return 1
    fi
}

# Main pipeline execution
main() {
    log_info "Starting Adaptive Knowledge Graph Data Pipeline"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Log file: $LOG_FILE"
    echo "" | tee -a "$LOG_FILE"

    # Create data directories
    mkdir -p "$DATA_DIR/raw"
    mkdir -p "$DATA_DIR/processed"

    # Check prerequisites
    log_info "Checking prerequisites..."

    # Check Neo4j
    if ! check_service "Neo4j" "http://localhost:7474"; then
        log_warning "Neo4j not running. Start with: docker compose -f infra/compose/compose.yaml up -d neo4j"
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Check Qdrant
    if ! check_service "Qdrant" "http://localhost:6333"; then
        log_warning "Qdrant not running. Start with: docker compose -f infra/compose/compose.yaml up -d qdrant"
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Check Poetry
    if ! command -v poetry &> /dev/null; then
        log_error "Poetry is not installed. Install from: https://python-poetry.org/docs/#installation"
        exit 1
    fi

    log_success "Prerequisites checked"
    echo ""

    # Pipeline steps
    local pipeline_start=$(date +%s)

    # Step 1: Fetch OpenStax Biology 2e
    if [ "$SKIP_FETCH" = true ]; then
        log_info "Skipping Step 1 (--skip-fetch flag set)"
    else
        if ! run_step 1 "Fetch OpenStax Biology 2e" "fetch_openstax.py" "~10 minutes"; then
            exit 1
        fi
    fi

    # Step 2: Parse sections
    if ! run_step 2 "Parse HTML to JSON" "parse_sections.py" "~20 minutes"; then
        exit 1
    fi

    # Step 3: Normalize book
    if ! run_step 3 "Normalize and add attribution" "normalize_book.py" "~5 minutes"; then
        exit 1
    fi

    # Step 4: Build knowledge graph
    if ! run_step 4 "Build knowledge graph" "build_knowledge_graph.py" "~60 minutes"; then
        exit 1
    fi

    # Step 5: Index to Qdrant
    if ! run_step 5 "Index chunks to Qdrant" "index_to_qdrant.py" "~60 minutes"; then
        exit 1
    fi

    # Pipeline complete
    local pipeline_end=$(date +%s)
    local total_duration=$((pipeline_end - pipeline_start))
    local hours=$((total_duration / 3600))
    local minutes=$(((total_duration % 3600) / 60))
    local seconds=$((total_duration % 60))

    echo ""
    log_info "=========================================="
    log_success "Pipeline completed successfully!"
    log_info "Total time: ${hours}h ${minutes}m ${seconds}s"
    log_info "=========================================="
    echo ""

    # Verify results
    log_info "Verifying results..."

    # Check if data files exist
    if [ -d "$DATA_DIR/raw" ] && [ "$(ls -A $DATA_DIR/raw)" ]; then
        log_success "Raw data directory populated"
    else
        log_warning "Raw data directory is empty"
    fi

    if [ -d "$DATA_DIR/processed" ] && [ "$(ls -A $DATA_DIR/processed)" ]; then
        log_success "Processed data directory populated"
    else
        log_warning "Processed data directory is empty"
    fi

    echo ""
    log_info "Next steps:"
    log_info "1. Verify graph stats: curl http://localhost:8000/api/v1/graph/stats"
    log_info "2. Start frontend: cd frontend && npm run dev"
    log_info "3. Open browser: http://localhost:3000"
    log_info "4. Test graph visualization: http://localhost:3000/graph"
    echo ""
    log_success "Ready for demo! 🚀"
}

# Run main pipeline
main
