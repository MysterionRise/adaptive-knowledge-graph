# docker compose on infra/compose/compose.yaml, plus the repository-root .env (ports and
# passwords set there reach the containers) and, on a native Linux engine, compose.linux.yaml.
# Choose the profile of the containerised stack with PROFILE=cpu|gpu|full.
COMPOSE := bash scripts/compose.sh
PROFILE ?= cpu
SUBJECT ?=
API_HOST ?= 127.0.0.1
# The environment wins, then API_PORT in the repository .env (read by scripts/lib.sh), then 8000
API_PORT ?= $(or $(shell bash -c '. scripts/lib.sh && printf %s "$${API_PORT:-}"' 2> /dev/null),8000)
API_URL ?= http://localhost:$(API_PORT)
EVAL_ARGS ?=

.DEFAULT_GOAL := help

.PHONY: help quickstart doctor up down seed build-windows \
	install install-dev \
	test test-fast test-tribunal test-integration test-integration-ui \
	lint format type-check pre-commit clean \
	docker-build docker-up docker-down docker-logs docker-ps \
	ingest-books build-kg index-rag pipeline-all \
	run-api run-frontend dev-setup \
	eval-rag eval-rag-api \
	demo-seed demo-check demo-client-prep demo-client-check demo-client-reset demo-eval

help: ## Show this help message
	@echo 'Usage: make [target] [SUBJECT=economics] [PROFILE=cpu|gpu|full]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Getting started
quickstart: ## Fresh clone to seeded stack: deps, Ollama check, databases, seed US History + Economics
	bash scripts/quickstart.sh

doctor: ## Check every local dependency (Docker, ports, Ollama generation, spaCy model, Node, disk/RAM)
	bash scripts/doctor.sh

up: ## Start Neo4j + OpenSearch and wait until both are healthy
	$(COMPOSE) up -d --wait --wait-timeout 300 neo4j opensearch

down: ## Stop and remove the stack's containers, all profiles (data volumes are kept)
	$(COMPOSE) --profile '*' down

seed: ## Seed demo data into Neo4j + OpenSearch (all demo subjects, or SUBJECT=...)
	bash scripts/seed_demo.sh $(SUBJECT)

build-windows: ## Build Neo4j chunk windows (NEXT edges) from the seeded data (SUBJECT=...)
	poetry run python scripts/build_chunk_windows.py $(if $(SUBJECT),--subject $(SUBJECT))

# Installation
install: ## Install runtime dependencies (no dev tools)
	poetry install --only main

install-dev: ## Install all dependencies including dev tools, and the pre-commit hooks
	poetry install --without pyirt,pybkt
	poetry run pre-commit install

# Tests and code quality
test: ## Run tests with coverage
	poetry run pytest

test-fast: ## Run non-adversarial backend tests with per-test timeout
	PYTEST_TEST_TIMEOUT_SECONDS=60 poetry run pytest -m "not tribunal"

test-tribunal: ## Run adversarial/risk-register tests separately (no coverage gate)
	PYTEST_TEST_TIMEOUT_SECONDS=60 poetry run pytest -m tribunal --no-cov

test-integration: ## Run Playwright integration tests against live services
	cd frontend && npx playwright test --project=integration

test-integration-ui: ## Run integration tests with Playwright UI
	cd frontend && npx playwright test --project=integration --ui

lint: ## Run linting checks
	poetry run ruff check backend/ scripts/

format: ## Format code with ruff
	poetry run ruff format backend/ scripts/
	poetry run ruff check --fix backend/ scripts/

type-check: ## Run type checking with mypy
	poetry run mypy backend/app scripts/

pre-commit: format lint type-check test ## Run all pre-commit checks

clean: ## Clean up generated files
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Containerised stack (the databases alone: make up / make down)
docker-build: ## Build the images of PROFILE (cpu: API, gpu: CUDA API, full: API + frontend)
	$(COMPOSE) --profile $(PROFILE) build

docker-up: ## Start databases + PROFILE services (default cpu: containerised API) and wait
	$(COMPOSE) --profile $(PROFILE) up -d --build --wait --wait-timeout 600

docker-down: down ## Alias for down

docker-logs: ## Follow the logs of every running service
	$(COMPOSE) --profile '*' logs -f

docker-ps: ## Show the stack's containers
	$(COMPOSE) --profile '*' ps

# Data pipeline (multi-subject; SUBJECT defaults to us_history)
ingest-books: ## Fetch and normalise the books of SUBJECT into data/processed/books_<subject>.jsonl
	poetry run python scripts/ingest_books.py $(if $(SUBJECT),--subject $(SUBJECT))

build-kg: ## Build the knowledge graph of SUBJECT in Neo4j (asks before clearing)
	poetry run python scripts/build_knowledge_graph.py $(if $(SUBJECT),--subject $(SUBJECT))

index-rag: ## Chunk, embed and index the text of SUBJECT into OpenSearch
	poetry run python scripts/index_to_opensearch.py $(if $(SUBJECT),--subject $(SUBJECT))

pipeline-all: ## Rebuild from scratch: re-ingest, rebuild graph, recreate index (SUBJECT or both demo subjects)
	bash scripts/seed_demo.sh --reset $(SUBJECT)

# Run services
run-api: ## Run the FastAPI backend locally with reload (API_HOST=127.0.0.1, API_PORT=8000)
	poetry run uvicorn backend.app.main:app --reload --host $(API_HOST) --port $(API_PORT)

run-frontend: ## Run the Next.js dev server (frontend/)
	cd frontend && npm run dev

dev-setup: install-dev up ## Dev environment: install-dev + databases
	@echo "Development environment ready. Next: make seed, then make run-api and make run-frontend."

# Evaluation (EVAL_ARGS passes options, e.g. EVAL_ARGS="--subject economics --limit 3")
eval-rag: ## Run the live API KG-RAG evaluation (paced to the /ask rate limit)
	poetry run python scripts/evaluate_rag.py --api-url $(API_URL) $(EVAL_ARGS)

eval-rag-api: eval-rag ## Alias for eval-rag

# Demo acceptance
demo-seed: ## Seed local demo data into Neo4j and OpenSearch (same as make seed)
	bash scripts/seed_demo.sh $(SUBJECT)

demo-check: ## Check local demo readiness (same as make doctor)
	bash scripts/doctor.sh

demo-client-prep: ## Prepare the OpenStax client demo: Ollama and spaCy checks, databases, seed
	bash scripts/demo_client_prep.sh

demo-client-check: ## Validate client demo readiness end to end and the latest eval gate
	bash scripts/demo_client_check.sh

demo-client-reset: ## Reset transient client demo learner state
	bash scripts/demo_client_reset.sh

demo-eval: ## Run the full live eval and validate the report
	poetry run python scripts/evaluate_rag.py --api-url $(API_URL)
	poetry run python scripts/check_demo_eval.py
