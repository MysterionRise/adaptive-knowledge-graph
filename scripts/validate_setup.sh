#!/usr/bin/env bash
#
# Validate Setup for Adaptive Knowledge Graph Demo
#
# Quick validation script to check if everything is ready for demo.
# Run this before rehearsing your demo scenarios.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
PASSED=0
FAILED=0
WARNINGS=0

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

check_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

echo "=========================================="
echo "Adaptive Knowledge Graph - Setup Validation"
echo "=========================================="
echo ""

# Check Node.js
echo "Checking Node.js..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    check_pass "Node.js installed: $NODE_VERSION"
else
    check_fail "Node.js not installed"
fi
echo ""

# Check npm
echo "Checking npm..."
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    check_pass "npm installed: $NPM_VERSION"
else
    check_fail "npm not installed"
fi
echo ""

# Check Python
echo "Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    check_pass "Python installed: $PYTHON_VERSION"
else
    check_fail "Python not installed"
fi
echo ""

# Check Poetry
echo "Checking Poetry..."
if command -v poetry &> /dev/null; then
    POETRY_VERSION=$(poetry --version)
    check_pass "Poetry installed: $POETRY_VERSION"
else
    check_warn "Poetry not installed (optional for backend)"
fi
echo ""

# Check frontend directory
echo "Checking frontend..."
if [ -d "frontend" ]; then
    check_pass "Frontend directory exists"

    if [ -f "frontend/package.json" ]; then
        check_pass "package.json found"
    else
        check_fail "package.json not found"
    fi

    if [ -d "frontend/node_modules" ]; then
        check_pass "node_modules installed"
    else
        check_warn "node_modules not installed - run: cd frontend && npm install"
    fi

    if [ -f "frontend/.env.local" ]; then
        check_pass ".env.local configured"
    else
        check_warn ".env.local not found - copy from .env.example"
    fi
else
    check_fail "Frontend directory not found"
fi
echo ""

# Check backend directory
echo "Checking backend..."
if [ -d "backend" ]; then
    check_pass "Backend directory exists"

    if [ -f "backend/pyproject.toml" ]; then
        check_pass "pyproject.toml found"
    else
        check_fail "pyproject.toml not found"
    fi
else
    check_fail "Backend directory not found"
fi
echo ""

# Check services
echo "Checking services..."

# Backend API
if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
    check_pass "Backend API running (http://localhost:8000)"
else
    check_warn "Backend API not running - start with: cd backend && poetry run uvicorn app.main:app --reload"
fi

# Frontend dev server
if curl -s -f http://localhost:3000 > /dev/null 2>&1; then
    check_pass "Frontend running (http://localhost:3000)"
else
    check_warn "Frontend not running - start with: cd frontend && npm run dev"
fi

# Neo4j
if curl -s -f http://localhost:7474 > /dev/null 2>&1; then
    check_pass "Neo4j running (http://localhost:7474)"
else
    check_warn "Neo4j not running - start with: docker compose -f infra/compose/compose.yaml up -d neo4j"
fi

# Qdrant
if curl -s -f http://localhost:6333 > /dev/null 2>&1; then
    check_pass "Qdrant running (http://localhost:6333)"
else
    check_warn "Qdrant not running - start with: docker compose -f infra/compose/compose.yaml up -d qdrant"
fi
echo ""

# Check data
echo "Checking data..."
if [ -d "data/raw" ] && [ "$(ls -A data/raw)" ]; then
    check_pass "Raw data directory populated"
else
    check_warn "Raw data directory empty - run: ./scripts/run_pipeline.sh"
fi

if [ -d "data/processed" ] && [ "$(ls -A data/processed)" ]; then
    check_pass "Processed data directory populated"
else
    check_warn "Processed data directory empty - run: ./scripts/run_pipeline.sh"
fi
echo ""

# Check graph data
echo "Checking knowledge graph..."
if curl -s -f http://localhost:8000/api/v1/graph/stats > /dev/null 2>&1; then
    STATS=$(curl -s http://localhost:8000/api/v1/graph/stats)
    CONCEPTS=$(echo "$STATS" | grep -o '"concept_count":[0-9]*' | grep -o '[0-9]*')
    if [ -n "$CONCEPTS" ] && [ "$CONCEPTS" -gt 0 ]; then
        check_pass "Knowledge graph populated: $CONCEPTS concepts"
    else
        check_warn "Knowledge graph empty - run pipeline"
    fi
else
    check_warn "Cannot check graph stats (API not running)"
fi
echo ""

# Summary
echo "=========================================="
echo "Validation Summary"
echo "=========================================="
echo -e "${GREEN}Passed:${NC} $PASSED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "${RED}Failed:${NC} $FAILED"
echo ""

if [ $FAILED -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed! Ready for demo!${NC} 🚀"
    else
        echo -e "${YELLOW}⚠ Setup complete with warnings. Check above for details.${NC}"
        echo ""
        echo "For full functionality:"
        echo "  - Start missing services"
        echo "  - Run data pipeline if graph is empty"
    fi
else
    echo -e "${RED}✗ Some checks failed. Fix issues above before demo.${NC}"
fi
echo ""

# Quick start commands
if [ $WARNINGS -gt 0 ] || [ $FAILED -gt 0 ]; then
    echo "Quick start commands:"
    echo ""
    echo "  # Start services"
    echo "  docker compose -f infra/compose/compose.yaml up -d"
    echo ""
    echo "  # Install frontend"
    echo "  cd frontend && npm install && cp .env.example .env.local"
    echo ""
    echo "  # Start backend"
    echo "  cd backend && poetry install && poetry run uvicorn app.main:app --reload"
    echo ""
    echo "  # Start frontend"
    echo "  cd frontend && npm run dev"
    echo ""
    echo "  # Run data pipeline (if needed)"
    echo "  ./scripts/run_pipeline.sh"
    echo ""
fi
