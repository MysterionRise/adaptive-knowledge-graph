# Docker Compose stack

[`compose.yaml`](compose.yaml) defines the local services for Adaptive
Knowledge Graph. Most people only need the databases: `make quickstart` and
`make up` start them, and the API and frontend run on the host (`make run-api`,
`npm run dev`).

Requirements: Docker with Compose 2.24 or newer. The API services load the
repository-root `.env` through the optional `env_file` syntax, which needs
2.24.

## Services and profiles

| Service | Image | Profiles | Host port (on `127.0.0.1`) |
| --- | --- | --- | --- |
| `neo4j` | `neo4j:5.26-community`, APOC restricted to `apoc.meta.*` | always | 7474 Browser, 7687 Bolt |
| `opensearch` | `opensearchproject/opensearch:3.9.0`, single node | always | 9200 |
| `api-cpu` | API image, CPU (`infra/docker/api.cpu.Dockerfile`) | `cpu`, `full` | 8000 |
| `api-gpu` | API image, CUDA 12.8 (`infra/docker/api.gpu.Dockerfile`) | `gpu` | 8000 |
| `frontend` | Next.js production build (`infra/docker/frontend.Dockerfile`) | `full` | 3000 |
| `ollama` | `ollama/ollama:0.35.0` | `ollama` | 11434 |

- **No profile:** Neo4j and OpenSearch only. This is what `make up` starts.
- **`cpu`:** adds the API container on CPU.
- **`gpu`:** adds the API container with CUDA. It needs an NVIDIA GPU, current
  drivers and the NVIDIA Container Toolkit.
- **`full`:** adds the CPU API and the frontend container.
- **`ollama`:** adds an Ollama container, for machines where you do not want to
  install Ollama on the host.

The API containers wait for healthy databases, have their own health check,
mount `data/` (and `docs/evals/` read-only for the demo status page), and keep
downloaded models in the `hf_cache` volume. The Compose project is named
`adaptive-kg`, so containers are called `adaptive-kg-<service>` and volumes
`adaptive-kg_<name>`.

## Usage

From the repository root:

```bash
make up                  # start Neo4j and OpenSearch and wait until they are healthy
make down                # stop every service; data volumes are kept
make docker-up           # databases plus the PROFILE services (default cpu), built and healthy
make docker-up PROFILE=full
make docker-logs         # follow the logs of all services
make docker-ps           # show container status
```

The Make targets call Compose through `scripts/compose.sh`, which adds the
repository-root `.env` (when it exists) and, on a native Linux Docker Engine,
the `compose.linux.yaml` override. To call Compose directly, pass the same
options yourself:

```bash
docker compose -f infra/compose/compose.yaml --env-file .env up -d --wait neo4j opensearch
docker compose -f infra/compose/compose.yaml --env-file .env --profile cpu up -d --wait

# Delete all data (the knowledge graph and search index must be seeded again):
docker compose -f infra/compose/compose.yaml down -v
```

## Configuration

Set these in the repository-root `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEO4J_PASSWORD` | `password` | Neo4j password, shared by the database and the API containers. Neo4j applies it only when its volume is first created. |
| `OPENSEARCH_PASSWORD` | development default in `compose.yaml` | OpenSearch password, shared with the API containers. Unused while the security plugin is disabled. |
| `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` | `7474`, `7687` | Host ports for Neo4j. |
| `OPENSEARCH_PORT` | `9200` | Host port for OpenSearch; the API reads the same variable. |
| `API_PORT`, `FRONTEND_PORT`, `OLLAMA_PORT` | `8000`, `3000`, `11434` | Host ports for the optional containers. If you change `FRONTEND_PORT`, add the new origin to `CORS_ORIGINS`. |
| `CONTAINER_OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama URL used by the API containers. Use `http://ollama:11434` with the `ollama` profile. |
| `APP_UID`, `APP_GID` | `1000` | User and group of the non-root API container user. On Linux, match your host user so `data/` stays writable. |
| `COMPOSE_PROJECT_NAME` | `adaptive-kg` | Prefix for container and volume names. |

`PROFILE` (default `cpu`) selects the profile for `make docker-up` and
`make docker-build`. `make quickstart` and `make doctor` also honour
`SKIP_OLLAMA_CHECK=1` (skip the Ollama check) and `SKIP_FRONTEND=1` (skip the
Node checks and `npm ci`).

## Security notes

- Every published port is bound to `127.0.0.1`, so the services are reachable
  only from your machine.
- The credentials are development defaults, and the OpenSearch security plugin
  is disabled for local use. Change the passwords and keep the ports private
  before anyone else can reach the machine. [SECURITY.md](../../SECURITY.md)
  has the hardening checklist.

## Linux notes

- On a native Linux Docker Engine, `compose.linux.yaml` maps
  `host.docker.internal` to the host gateway so the API containers can reach a
  host Ollama. The Make targets and scripts add it automatically. Docker
  Desktop, Rancher Desktop, Colima and OrbStack resolve the name themselves and
  do not need it.
- For the API containers to reach a host Ollama on Linux, Ollama must listen on
  the Docker bridge address, for example `OLLAMA_HOST=172.17.0.1:11434 ollama serve`.
  An API running on the host then needs `LLM_OLLAMA_HOST=http://172.17.0.1:11434`
  as well.
- OpenSearch needs `vm.max_map_count` of at least 262144:

  ```bash
  sudo sysctl -w vm.max_map_count=262144
  ```

## Upgrading from an older checkout

Earlier versions of this file used the default project name `compose`, so
their volumes are named `compose_*`. To keep using that data, set
`COMPOSE_PROJECT_NAME=compose` in `.env`; otherwise seed the new volumes with
`make seed`. Neo4j 5.16 volumes open under 5.26. Back up your volumes before
you upgrade anyway, and re-seed if a database cannot open its old data.

## Service URLs

- Neo4j Browser: <http://localhost:7474> (user `neo4j`, password from
  `NEO4J_PASSWORD`)
- OpenSearch: <http://localhost:9200>
- API: <http://localhost:8000>, with docs at <http://localhost:8000/docs> in
  development mode
- Frontend: <http://localhost:3000>
