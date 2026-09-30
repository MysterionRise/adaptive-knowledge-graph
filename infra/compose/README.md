# Docker Compose stack

[`compose.yaml`](compose.yaml) defines the local services for Adaptive
Knowledge Graph. Most people only need the databases: `make quickstart` and
`make up` start them, and the API and frontend run on the host (`make run-api`,
`npm run dev`).

Requirements: Docker with Compose v2.24 or newer. The API services load the
repository-root `.env` with the `env_file` long syntax, which needs 2.24.

## Services and profiles

| Service | Image | Profile | Host port |
| --- | --- | --- | --- |
| `neo4j` | `neo4j:5.26-community`, APOC restricted to `apoc.meta.*` | default | 7474 (browser), 7687 (Bolt) |
| `opensearch` | `opensearchproject/opensearch:3.9.0`, single node | default | 9200 |
| `api` | API image built from `infra/docker/` | `cpu`, or `gpu` for CUDA | 8000 |
| `frontend` | Next.js app | `full` | 3000 |
| `ollama` | Ollama | `ollama` | none (reached on the Compose network) |

- **Default (no profile):** Neo4j and OpenSearch only. This is what
  `make up` starts.
- **`cpu`:** adds the API container, running on CPU.
- **`gpu`:** adds the API container with CUDA. Needs an NVIDIA GPU, current
  drivers and the NVIDIA Container Toolkit.
- **`full`:** adds the API and the frontend containers.
- **`ollama`:** adds an Ollama container, for machines where you do not want
  to install Ollama on the host.

Container names start with `adaptive-kg-` and volumes with `adaptive-kg_`,
because the Compose project is named `adaptive-kg`.

## Usage

From the repository root:

```bash
make up                  # start Neo4j and OpenSearch and wait until healthy
make down                # stop them; data volumes are kept

# The same with Compose directly:
docker compose -f infra/compose/compose.yaml up -d --wait neo4j opensearch
docker compose -f infra/compose/compose.yaml down

# Optional containers:
docker compose -f infra/compose/compose.yaml --profile cpu up -d --wait      # API on CPU
docker compose -f infra/compose/compose.yaml --profile gpu up -d --wait      # API with CUDA
docker compose -f infra/compose/compose.yaml --profile full up -d --wait     # API and frontend
docker compose -f infra/compose/compose.yaml --profile ollama up -d --wait   # Ollama in a container

# Logs and status:
docker compose -f infra/compose/compose.yaml ps
docker compose -f infra/compose/compose.yaml logs -f

# Delete all data (the knowledge graph and search index must then be seeded again):
docker compose -f infra/compose/compose.yaml down -v
```

The Make targets pass `--env-file .env` to Compose when a repository-root
`.env` exists, so passwords and ports set there reach the databases too. Pass
the same flag when you call Compose directly.

## Configuration

Set these in the repository-root `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEO4J_PASSWORD` | `password` | Neo4j password, shared by the database and the API containers |
| `OPENSEARCH_PASSWORD` | development default | OpenSearch password, shared by the database and the API containers |
| `NEO4J_HTTP_PORT` / `NEO4J_BOLT_PORT` | `7474` / `7687` | Host ports for Neo4j |
| `OPENSEARCH_PORT` | `9200` | Host port for OpenSearch |
| `API_PORT` / `FRONTEND_PORT` | `8000` / `3000` | Host ports for the optional containers |
| `CONTAINER_OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama URL used by the API container; set `http://ollama:11434` with the `ollama` profile |

`make quickstart` also honours `SKIP_OLLAMA_CHECK=1` (skip the Ollama and
model check) and `SKIP_FRONTEND=1` (skip installing the frontend dependencies).

## Security notes

- Every port is bound to `127.0.0.1`, so the services are reachable only from
  your machine.
- The credentials are development defaults, and the OpenSearch security plugin
  is disabled for local use. Change the passwords and keep the ports private
  before anyone else can reach the machine. [SECURITY.md](../../SECURITY.md)
  has the hardening checklist.

## Linux notes

- The API container reaches a host Ollama through `host.docker.internal`.
  On Linux, Ollama must listen on all interfaces for that to work: start it
  with `OLLAMA_HOST=0.0.0.0`.
- OpenSearch needs `vm.max_map_count` of at least 262144:

  ```bash
  sudo sysctl -w vm.max_map_count=262144
  ```

## Upgrading from an older checkout

Earlier versions of this file used the default project name `compose`, so
their volumes are named `compose_*`. To keep using that data, set
`COMPOSE_PROJECT_NAME=compose` in `.env`, or seed the new volumes again with
`make seed`. Back up volumes before upgrading Neo4j to a new major or minor
version.

## Service URLs

- Neo4j Browser: <http://localhost:7474> (user `neo4j`, password from
  `NEO4J_PASSWORD`)
- OpenSearch: <http://localhost:9200>
- API: <http://localhost:8000>, with docs at <http://localhost:8000/docs> in
  development mode
- Frontend: <http://localhost:3000>
