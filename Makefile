.PHONY: help install install-dev test lint format type-check clean docker-build docker-up docker-down fetch-data build-kg index-rag run-api run-frontend

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies (excluding optional groups)
	poetry install --no-root --only main --without pyirt,pybkt

install-dev: ## Install all dependencies including dev tools (excluding optional groups)
	poetry install --no-root --without pyirt,pybkt
	poetry run pre-commit install

install-student: ## Install optional student modeling dependencies (requires Python 3.11)
	@echo "⚠️  Note: pyBKT and py-irt require Python 3.11 specifically"
	poetry install --no-root --with pybkt --with pyirt

test: ## Run tests with coverage
	poetry run pytest

test-watch: ## Run tests in watch mode
	poetry run pytest-watch

lint: ## Run linting checks
	poetry run ruff check backend/ scripts/

format: ## Format code with ruff
	poetry run ruff format backend/ scripts/
	poetry run ruff check --fix backend/ scripts/

type-check: ## Run type checking with mypy
	poetry run mypy backend/app scripts/

clean: ## Clean up generated files
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Docker operations
docker-build: ## Build Docker images
	docker compose -f infra/compose/compose.yaml build

docker-up: ## Start all services (neo4j, qdrant, api)
	docker compose -f infra/compose/compose.yaml up -d

docker-down: ## Stop all services
	docker compose -f infra/compose/compose.yaml down

docker-logs: ## Show Docker logs
	docker compose -f infra/compose/compose.yaml logs -f

docker-ps: ## Show running containers
	docker compose -f infra/compose/compose.yaml ps

# Data pipeline operations
fetch-data: ## Fetch OpenStax Biology 2e from philschatz
	poetry run python scripts/fetch_openstax.py

parse-data: ## Parse fetched HTML to clean JSON
	poetry run python scripts/parse_sections.py

normalize-data: ## Normalize to JSONL with attribution
	poetry run python scripts/normalize_book.py

# KG operations
build-kg: ## Build knowledge graph (extract concepts, edges, persist to Neo4j)
	poetry run python scripts/build_knowledge_graph.py

export-rdf: ## Export KG to RDF/Turtle
	poetry run python scripts/export_graph_rdf.py

# RAG operations
index-rag: ## Index textbook content to Qdrant
	poetry run python scripts/index_to_qdrant.py

# Run services
run-api: ## Run FastAPI backend locally
	poetry run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

run-frontend: ## Run Next.js frontend (cd to frontend first)
	cd frontend && npm run dev

# Evaluation
eval-rag: ## Run RAGAS evaluation notebook
	poetry run jupyter notebook notebooks/eval_ragas.ipynb

# Complete pipeline
pipeline-all: fetch-data parse-data normalize-data build-kg index-rag ## Run complete data pipeline

# Development workflow
dev-setup: install-dev docker-up ## Complete dev environment setup
	@echo "✅ Development environment ready!"
	@echo "   - Neo4j: http://localhost:7474 (neo4j/password)"
	@echo "   - Qdrant: http://localhost:6333"
	@echo "   - API will run on: http://localhost:8000"

# Quick checks before commit
pre-commit: format lint type-check test ## Run all pre-commit checks
