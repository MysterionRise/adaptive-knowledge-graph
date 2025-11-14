# Docker Compose Setup

This directory contains Docker Compose configurations for running the Adaptive Knowledge Graph services.

## Services

- **neo4j**: Graph database for storing the knowledge graph
- **qdrant**: Vector database for semantic search
- **api-cpu**: FastAPI backend (CPU-only)
- **api-gpu**: FastAPI backend (GPU-enabled for RTX 4070)

## Usage

### Option 1: CPU-only mode (no GPU required)

```bash
# Start Neo4j and Qdrant + CPU API
docker compose -f infra/compose/compose.yaml --profile cpu up -d

# Or from project root using Makefile
make docker-up
```

### Option 2: GPU mode (requires NVIDIA GPU + nvidia-docker)

```bash
# Start Neo4j and Qdrant + GPU API
docker compose -f infra/compose/compose.yaml --profile gpu up -d

# Check GPU is accessible
docker exec adaptive-kg-api-gpu nvidia-smi
```

### Option 3: Just databases (run API locally)

```bash
# Start only Neo4j and Qdrant
docker compose -f infra/compose/compose.yaml up -d neo4j qdrant

# Then run API locally
poetry run uvicorn backend.app.main:app --reload
```

## Service URLs

- **Neo4j Browser**: http://localhost:7474
  - Username: `neo4j`
  - Password: `password`
- **Qdrant Dashboard**: http://localhost:6333/dashboard
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Managing Services

```bash
# View logs
docker compose -f infra/compose/compose.yaml logs -f

# Stop all services
docker compose -f infra/compose/compose.yaml down

# Stop and remove volumes (⚠️ deletes all data)
docker compose -f infra/compose/compose.yaml down -v

# Check service status
docker compose -f infra/compose/compose.yaml ps
```

## GPU Requirements

For GPU mode, ensure:
1. NVIDIA drivers installed
2. nvidia-docker2 installed
3. Docker Compose v2.3+ with GPU support

Test GPU access:
```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```
