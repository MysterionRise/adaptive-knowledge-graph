#!/usr/bin/env bash
#
# make doctor: report the state of every local dependency of the stack.
#
#   bash scripts/doctor.sh
#
# Checks tools (Docker, Compose, Python, Poetry, Node), resources (disk, memory), the host ports
# the compose file publishes, the databases and the API, the seeded data, the Ollama model (with a
# 1-token generation probe) and the spaCy model. Exits 1 when a check fails; warnings do not fail.
#
# Environment: SKIP_OLLAMA_CHECK=1 skips the Ollama probe, SKIP_FRONTEND=1 the Node checks.

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$AKG_ROOT"

PASSED=0
FAILED=0
WARNINGS=0

check_pass() {
    printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$1"
    PASSED=$((PASSED + 1))
}
check_fail() {
    printf '  %s✗%s %s\n' "$C_RED" "$C_RESET" "$1"
    FAILED=$((FAILED + 1))
}
check_warn() {
    printf '  %s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$1"
    WARNINGS=$((WARNINGS + 1))
}
detail() {
    printf '      %s\n' "$@"
}
section() {
    printf '\n%s%s%s\n' "$C_BOLD" "$1" "$C_RESET"
}

# report_probe <fail|warn> <exit code> <output>: first output line is the summary
report_probe() {
    local severity="$1" rc="$2" output="$3" summary rest
    summary="${output%%$'\n'*}"
    rest=""
    if [ "$summary" != "$output" ]; then
        rest="${output#*$'\n'}"
    fi
    if [ "$rc" -eq 0 ]; then
        check_pass "$summary"
    elif [ "$severity" = fail ]; then
        check_fail "$summary"
    else
        check_warn "$summary"
    fi
    if [ -n "$rest" ]; then
        printf '%s\n' "$rest" | sed 's/^ */      /'
    fi
}

port_open() {
    (exec 3<> "/dev/tcp/127.0.0.1/$1") 2> /dev/null
}

echo "=========================================="
echo "Adaptive Knowledge Graph - doctor"
echo "=========================================="

# ---------------------------------------------------------------------------
section "Tools"
DOCKER_OK=false
if ! have docker; then
    check_fail "Docker is not installed (https://docs.docker.com/get-docker/)"
elif ! docker info > /dev/null 2>&1; then
    check_fail "Docker is installed but the daemon is not reachable (start Docker Desktop / Rancher Desktop / dockerd)"
else
    DOCKER_OK=true
    check_pass "Docker $(docker version --format '{{.Server.Version}}' 2> /dev/null || echo '?') (daemon running)"
    compose_v="$(compose_version)"
    if [ -z "$compose_v" ]; then
        DOCKER_OK=false
        check_fail "Docker Compose v2 plugin is missing ('docker compose'); install >= $AKG_MIN_COMPOSE_VERSION"
    elif version_ge "$compose_v" "$AKG_MIN_COMPOSE_VERSION"; then
        check_pass "Docker Compose $compose_v (>= $AKG_MIN_COMPOSE_VERSION)"
    else
        DOCKER_OK=false
        check_fail "Docker Compose $compose_v is too old; infra/compose/compose.yaml needs >= $AKG_MIN_COMPOSE_VERSION"
    fi
fi

# Poetry needs an interpreter in the project's range (python = ">=3.11,<3.14")
py_found=""
for candidate in python3.13 python3.12 python3.11 python3; do
    have "$candidate" || continue
    py_version="$("$candidate" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2> /dev/null || true)"
    if [ -n "$py_version" ] && version_ge "$py_version" 3.11.0 && ! version_ge "$py_version" 3.14.0; then
        py_found="$candidate ($py_version)"
        break
    fi
done
if [ -n "$py_found" ]; then
    check_pass "Python for the backend: $py_found"
elif poetry_env_ready; then
    check_warn "No Python 3.11-3.13 on PATH (the existing Poetry environment still works)"
else
    check_fail "No Python 3.11-3.13 on PATH (python3.13/3.12/3.11); Poetry needs one for the backend"
fi
if ! have python3; then
    check_fail "python3 is missing (the checks in scripts/stack_check.py need it)"
fi

if have poetry; then
    check_pass "$(poetry --version 2>&1 | head -1)"
    if poetry_env_ready; then
        venv_python="$(poetry run python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2> /dev/null || echo '?')"
        check_pass "Backend dependencies installed (Python $venv_python, $(poetry env info --path 2> /dev/null))"
    else
        check_warn "Backend dependencies are not installed"
        detail "hint: make install   (or make quickstart)"
    fi
else
    check_fail "Poetry is not installed (https://python-poetry.org/docs/#installation)"
fi

if [ "${SKIP_FRONTEND:-}" = "1" ]; then
    check_pass "Frontend checks skipped (SKIP_FRONTEND=1)"
else
    rc=0
    out="$(stack_check node 2>&1)" || rc=$?
    report_probe fail "$rc" "$out"
    if [ -d frontend/node_modules ]; then
        check_pass "Frontend dependencies installed (frontend/node_modules)"
    else
        check_warn "Frontend dependencies are not installed"
        detail "hint: cd frontend && npm ci   (or make quickstart)"
    fi
fi

# ---------------------------------------------------------------------------
section "Resources"
free_gb="$(df -Pk "$AKG_ROOT" | awk 'NR == 2 { printf "%d", $4 / 1048576 }')"
if [ "${free_gb:-0}" -ge 20 ]; then
    check_pass "Free disk space: ${free_gb} GB"
else
    check_warn "Free disk space: ${free_gb:-?} GB (20+ GB recommended: images, Python env, embedding and LLM models)"
fi

mem_bytes=""
case "$(uname -s)" in
    Darwin) mem_bytes="$(sysctl -n hw.memsize 2> /dev/null || true)" ;;
    Linux) mem_bytes="$(awk '/^MemTotal:/ { printf "%d", $2 * 1024 }' /proc/meminfo 2> /dev/null || true)" ;;
esac
if [ -n "$mem_bytes" ]; then
    mem_gb=$((mem_bytes / 1073741824))
    if [ "$mem_gb" -ge 16 ]; then
        check_pass "Host memory: ${mem_gb} GB"
    else
        check_warn "Host memory: ${mem_gb} GB (16+ GB recommended for the databases, BGE-M3 and an 8B model)"
    fi
fi

if [ "$DOCKER_OK" = true ]; then
    docker_mem="$(docker info --format '{{.MemTotal}}' 2> /dev/null || echo 0)"
    docker_gb=$((docker_mem / 1073741824))
    if [ "$docker_gb" -ge 6 ]; then
        check_pass "Docker memory: ${docker_gb} GB"
    else
        check_warn "Docker memory: ${docker_gb} GB (Neo4j + OpenSearch need about 5 GB; give Docker 6+ GB)"
    fi
fi

if [ "$(uname -s)" = Linux ]; then
    map_count="$(sysctl -n vm.max_map_count 2> /dev/null || echo 0)"
    if [ "$map_count" -ge 262144 ]; then
        check_pass "vm.max_map_count = $map_count"
    else
        check_warn "vm.max_map_count = $map_count (OpenSearch needs >= 262144)"
        detail "fix: sudo sysctl -w vm.max_map_count=262144"
    fi
fi

# ---------------------------------------------------------------------------
section "Ports (published on 127.0.0.1)"
running_services=""
if [ "$DOCKER_OK" = true ]; then
    running_services=" $(compose --profile '*' ps --status running --services 2> /dev/null | tr '\n' ' ') "
    ports="$(compose --profile '*' config --format json 2> /dev/null | python3 -c '
import json, sys
config = json.load(sys.stdin)
for name, service in config.get("services", {}).items():
    for port in service.get("ports") or []:
        print(name, port.get("published"), port.get("target"))
' 2> /dev/null || true)"
    if [ -z "$ports" ]; then
        check_warn "Could not read the published ports from infra/compose/compose.yaml"
    fi
    seen_ports=" "
    while read -r service published target; do
        [ -n "${service:-}" ] || continue
        # api-cpu and api-gpu publish the same port; report it once
        case "$seen_ports" in *" $published "*) continue ;; esac
        seen_ports="$seen_ports$published "
        label="$published -> $service:$target"
        if [ "${running_services#* "$service" }" != "$running_services" ]; then
            check_pass "$label (in use by this stack)"
        elif ! port_open "$published"; then
            check_pass "$label (free)"
        elif { [ "$service" = api-cpu ] || [ "$service" = api-gpu ]; } \
            && curl -sf --max-time 3 "http://127.0.0.1:$published/health" 2> /dev/null | grep -q healthy; then
            check_pass "$label (in use by a local API, e.g. make run-api)"
        elif [ "$service" = frontend ] && curl -s --max-time 3 "http://127.0.0.1:$published" > /dev/null 2>&1; then
            check_pass "$label (in use, probably make run-frontend)"
        elif [ "$service" = ollama ]; then
            check_pass "$label (in use, probably a host Ollama; only matters for --profile ollama)"
        elif [ "$service" = neo4j ] || [ "$service" = opensearch ]; then
            check_fail "$label is taken by another process or compose project"
            detail "hint: stop it (e.g. an older checkout: docker compose -p compose -f infra/compose/compose.yaml down)" \
                "      or pick another host port (NEO4J_HTTP_PORT, NEO4J_BOLT_PORT, OPENSEARCH_PORT)"
        else
            check_warn "$label is taken by another process (set API_PORT / FRONTEND_PORT to move it)"
        fi
    done <<< "$ports"
else
    check_warn "Skipped: Docker is not available"
fi

# ---------------------------------------------------------------------------
section "Stack"
DB_READY=false
if [ "$DOCKER_OK" = true ]; then
    healthy=0
    for service in neo4j opensearch; do
        cid="$(compose ps -q "$service" 2> /dev/null || true)"
        if [ -z "$cid" ]; then
            check_warn "$service is not running (make up)"
            continue
        fi
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2> /dev/null || echo unknown)"
        name="$(docker inspect --format '{{.Name}}' "$cid" 2> /dev/null | sed 's|^/||')"
        case "$health" in
            healthy)
                check_pass "$service is healthy ($name)"
                healthy=$((healthy + 1))
                ;;
            starting) check_warn "$service is starting ($name); rerun in a minute" ;;
            *)
                check_fail "$service is $health ($name)"
                detail "logs: docker compose -f infra/compose/compose.yaml logs $service"
                ;;
        esac
    done
    if [ "$healthy" -eq 2 ]; then
        DB_READY=true
    fi
fi

if [ "$DB_READY" = true ] && poetry_env_ready; then
    for subj in "${AKG_DEMO_SUBJECTS[@]}"; do
        rc=0
        status="$(poetry run python scripts/stack_check.py seed-status --subject "$subj" 2> /dev/null)" || rc=$?
        concepts="${status%% *}"
        chunks="${status##* }"
        if [ "$rc" -ne 0 ]; then
            check_warn "$subj: could not read the seed status (are NEO4J_URI / OPENSEARCH_PORT pointing at this stack?)"
        elif [ "$concepts" -gt 0 ] && [ "$chunks" -gt 0 ]; then
            check_pass "$subj seeded: $concepts concepts in Neo4j, $chunks chunks in OpenSearch"
        else
            check_warn "$subj not seeded ($concepts concepts, $chunks chunks); run: make seed SUBJECT=$subj"
        fi
    done
fi

API_URL="${API_URL:-http://localhost:${API_PORT:-8000}}"
ready_json="$(curl -s --max-time 30 "$API_URL/health/ready" 2> /dev/null || true)"
if [ -z "$ready_json" ]; then
    check_warn "API is not running at $API_URL (make run-api, or make docker-up)"
else
    api_status="$(printf '%s' "$ready_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
bad = [name + "=" + str(svc.get("status")) for name, svc in data.get("services", {}).items() if svc.get("status") != "ok"]
print(data.get("status", "unknown"), " ".join(bad))
' 2> /dev/null || echo "unknown")"
    case "$api_status" in
        healthy*) check_pass "API at $API_URL is healthy" ;;
        degraded*) check_warn "API at $API_URL is degraded: ${api_status#degraded }" ;;
        *) check_fail "API at $API_URL is ${api_status}" ;;
    esac
fi

FRONTEND_URL="http://localhost:${FRONTEND_PORT:-3000}"
if curl -s --max-time 5 "$FRONTEND_URL" > /dev/null 2>&1; then
    check_pass "Frontend is running at $FRONTEND_URL"
else
    check_warn "Frontend is not running at $FRONTEND_URL (make run-frontend)"
fi

# ---------------------------------------------------------------------------
section "Models"
echo "  (the Ollama probe generates one token; the first call loads the model and can take a minute)"
rc=0
out="$(stack_check ollama 2>&1)" || rc=$?
report_probe fail "$rc" "$out"

# Native Linux engine: containers reach the host Ollama through the docker0 gateway
if [ "$DOCKER_OK" = true ] && needs_linux_override && have ss; then
    listen="$(ss -ltnH 2> /dev/null | awk '$4 ~ /:11434$/ { print $4 }')"
    if [ -n "$listen" ] && ! printf '%s\n' "$listen" | grep -qvE '^(127\.0\.0\.1|\[::1\]):11434$'; then
        check_warn "Ollama listens on loopback only; the API containers (make docker-up) cannot reach it"
        detail "hint: OLLAMA_HOST=172.17.0.1:11434 for the Ollama service (see infra/compose/compose.linux.yaml)"
    fi
fi

if poetry_env_ready; then
    rc=0
    out="$(poetry run python scripts/stack_check.py spacy 2>&1)" || rc=$?
    report_probe warn "$rc" "$out"
else
    check_warn "spaCy model not checked (backend dependencies are not installed)"
fi

# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "${C_GREEN}Passed:${C_RESET} $PASSED   ${C_YELLOW}Warnings:${C_RESET} $WARNINGS   ${C_RED}Failed:${C_RESET} $FAILED"
echo "=========================================="
if [ "$FAILED" -ne 0 ]; then
    echo "Fix the failed checks above. From a fresh clone, 'make quickstart' installs and seeds everything."
    exit 1
fi
if [ "$WARNINGS" -ne 0 ]; then
    echo "Ready with warnings: 'make up' starts the databases, 'make seed' loads the demo data."
fi
