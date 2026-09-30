#!/usr/bin/env bash
# Shared helpers for the scripts in this directory. Source it; do not run it:
#
#   # shellcheck source=lib.sh
#   source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# Compatible with bash 3.2 (the macOS default): no associative arrays, and arrays that may be
# empty are expanded as ${arr[@]+"${arr[@]}"} because of `set -u`.
# shellcheck shell=bash

if [ -n "${AKG_LIB_LOADED:-}" ]; then
    return 0
fi
AKG_LIB_LOADED=1

AKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AKG_COMPOSE_FILE="$AKG_ROOT/infra/compose/compose.yaml"
# Used by the scripts that source this file
# shellcheck disable=SC2034
{
    # Subjects with tracked source data (data/processed/books_<subject>.jsonl)
    AKG_DEMO_SUBJECTS=(us_history economics)
    # Same defaults as the backend settings DATA_PROCESSED_DIR / STUDENT_PROFILES_DB
    AKG_PROCESSED_DIR="${DATA_PROCESSED_DIR:-data/processed}"
    AKG_STUDENT_DB="${STUDENT_PROFILES_DB:-data/processed/student_profiles.sqlite3}"
}

# --- output -------------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[0;31m'
    C_GREEN=$'\033[0;32m'
    C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[0;34m'
    C_BOLD=$'\033[1m'
    C_RESET=$'\033[0m'
else
    C_RED=''
    C_GREEN=''
    C_YELLOW=''
    C_BLUE=''
    C_BOLD=''
    C_RESET=''
fi

info() { printf '%s[INFO]%s  %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok() { printf '%s[OK]%s    %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[WARN]%s  %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
error() { printf '%s[ERROR]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
die() {
    error "$*"
    exit 1
}
step() { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_RESET"; }

have() { command -v "$1" > /dev/null 2>&1; }

# require_command <command> [install hint]
require_command() {
    if ! have "$1"; then
        die "Missing required command: $1${2:+ ($2)}"
    fi
}

# --- versions -----------------------------------------------------------------------------
# version_ge <have> <need>: true when dotted version <have> >= <need>
version_ge() {
    local have_version="${1#v}" need_version="${2#v}"
    local h1 h2 h3 n1 n2 n3
    IFS=. read -r h1 h2 h3 <<< "$have_version"
    IFS=. read -r n1 n2 n3 <<< "$need_version"
    h1="${h1%%[!0-9]*}" h2="${h2%%[!0-9]*}" h3="${h3%%[!0-9]*}"
    n1="${n1%%[!0-9]*}" n2="${n2%%[!0-9]*}" n3="${n3%%[!0-9]*}"
    h1="${h1:-0}" h2="${h2:-0}" h3="${h3:-0}" n1="${n1:-0}" n2="${n2:-0}" n3="${n3:-0}"
    if [ "$h1" -ne "$n1" ]; then [ "$h1" -gt "$n1" ]; return; fi
    if [ "$h2" -ne "$n2" ]; then [ "$h2" -gt "$n2" ]; return; fi
    [ "$h3" -ge "$n3" ]
}

AKG_MIN_COMPOSE_VERSION=2.24.0

compose_version() {
    docker compose version --short 2> /dev/null | sed 's/^v//'
}

# --- docker compose -------------------------------------------------------------------------
# True for a native Linux Docker Engine, which has no host.docker.internal. Desktop engines
# (Docker Desktop, Rancher Desktop, Colima, OrbStack) resolve it themselves.
needs_linux_override() {
    [ "$(uname -s)" = Linux ] || return 1
    ! docker info --format '{{.OperatingSystem}} {{.Name}}' 2> /dev/null \
        | grep -qiE 'docker desktop|lima|colima|orbstack'
}

# The compose invocation used by the Makefile and the scripts: the repository-root .env (when
# present) feeds interpolation, so ports and passwords set there reach the containers too, and
# compose.linux.yaml is added on a native Linux engine.
compose() {
    local args=()
    if [ -f "$AKG_ROOT/.env" ]; then
        args+=(--env-file "$AKG_ROOT/.env")
    fi
    args+=(-f "$AKG_COMPOSE_FILE")
    if needs_linux_override; then
        args+=(-f "$AKG_ROOT/infra/compose/compose.linux.yaml")
    fi
    docker compose "${args[@]}" "$@"
}

require_docker() {
    require_command docker "https://docs.docker.com/get-docker/"
    if ! docker info > /dev/null 2>&1; then
        die "The Docker daemon is not reachable. Start Docker Desktop / Rancher Desktop / dockerd and retry."
    fi
    local version
    version="$(compose_version)"
    if [ -z "$version" ]; then
        die "Docker Compose v2 is missing ('docker compose'). Install the Compose plugin >= $AKG_MIN_COMPOSE_VERSION."
    fi
    if ! version_ge "$version" "$AKG_MIN_COMPOSE_VERSION"; then
        die "Docker Compose $version is too old; infra/compose/compose.yaml needs >= $AKG_MIN_COMPOSE_VERSION."
    fi
}

# --- host ports from the repository .env --------------------------------------------------
# compose reads the repository-root .env (--env-file) and the backend reads it too, but a shell
# does not: a port set only there would leave the scripts on the defaults. Read just these
# non-secret keys when the environment lacks them. KEY=value lines, optional `export` and
# quotes, inline `# comments`; the file is never sourced or evaluated.
AKG_DOTENV_KEYS="NEO4J_URI NEO4J_BOLT_PORT NEO4J_HTTP_PORT OPENSEARCH_PORT API_PORT FRONTEND_PORT OLLAMA_PORT"

# akg_dotenv_value KEY [FILE]: value of the last KEY=... line of FILE (default: repository .env)
akg_dotenv_value() {
    local key="$1" file="${2:-$AKG_ROOT/.env}" line value
    [ -f "$file" ] || return 0
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$file" 2> /dev/null | tail -n 1)" || true
    [ -n "$line" ] || return 0
    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    case "$value" in
        \"*)
            value="${value#\"}"
            value="${value%%\"*}"
            ;;
        \'*)
            value="${value#\'}"
            value="${value%%\'*}"
            ;;
        *)
            value="${value%%[[:space:]]#*}"
            value="${value%"${value##*[![:space:]]}"}"
            ;;
    esac
    printf '%s' "$value"
}

for akg_key in $AKG_DOTENV_KEYS; do
    if [ -z "${!akg_key:-}" ]; then
        akg_value="$(akg_dotenv_value "$akg_key")"
        if [ -n "$akg_value" ]; then
            export "$akg_key=$akg_value"
        fi
    fi
done
unset akg_key akg_value

# --- python helpers -----------------------------------------------------------------------
# The backend reads NEO4J_URI; when only the compose host port is overridden, derive it.
if [ -n "${NEO4J_BOLT_PORT:-}" ] && [ -z "${NEO4J_URI:-}" ]; then
    export NEO4J_URI="bolt://localhost:${NEO4J_BOLT_PORT}"
fi

# True when the Poetry environment exists and has the backend dependencies installed.
# The answer is cached; reset AKG_POETRY_READY after installing dependencies.
AKG_POETRY_READY=""
poetry_env_ready() {
    if [ -z "$AKG_POETRY_READY" ]; then
        AKG_POETRY_READY=no
        if have poetry \
            && (cd "$AKG_ROOT" && poetry env info --path > /dev/null 2>&1) \
            && (cd "$AKG_ROOT" && poetry run python -c "import neo4j, pydantic_settings" > /dev/null 2>&1); then
            AKG_POETRY_READY=yes
        fi
    fi
    [ "$AKG_POETRY_READY" = yes ]
}

# stack_check <subcommand> [args]: scripts/stack_check.py with the Poetry interpreter when the
# environment is ready (it then sees .env through the backend settings), else python3.
stack_check() {
    if poetry_env_ready; then
        (cd "$AKG_ROOT" && poetry run python scripts/stack_check.py "$@")
    elif have python3; then
        (cd "$AKG_ROOT" && python3 scripts/stack_check.py "$@")
    else
        error "python3 is required for this check"
        return 1
    fi
}

# Ollama reachable, model pulled and a 1-token generation works (SKIP_OLLAMA_CHECK=1 skips).
check_ollama_or_die() {
    if ! stack_check ollama; then
        die "Ollama is not usable (details above). Fix it, or rerun with SKIP_OLLAMA_CHECK=1."
    fi
}

# Install the spaCy model that concept extraction loads (it silently degrades without it).
ensure_spacy_model() {
    if (cd "$AKG_ROOT" && poetry run python scripts/stack_check.py spacy > /dev/null 2>&1); then
        ok "spaCy model en_core_web_sm is installed"
        return 0
    fi
    info "Downloading spaCy model en_core_web_sm..."
    (cd "$AKG_ROOT" && poetry run python -m spacy download en_core_web_sm) \
        || die "Could not download en_core_web_sm; retry with: poetry run python -m spacy download en_core_web_sm"
    ok "spaCy model en_core_web_sm installed"
}

# Make sure Neo4j and OpenSearch accept requests: a quick probe first (the stack may already
# be up), otherwise start the compose databases and wait for them, then probe again. This also
# covers containers that are running but not ready yet (cold start).
ensure_databases() {
    if (cd "$AKG_ROOT" && poetry run python scripts/stack_check.py wait --timeout 5 > /dev/null 2>&1); then
        ok "Neo4j and OpenSearch are ready"
        return 0
    fi
    require_docker
    info "Starting Neo4j and OpenSearch (docker compose up -d --wait)..."
    compose up -d --wait --wait-timeout 300 neo4j opensearch \
        || die "The databases did not become healthy; see: docker compose -f infra/compose/compose.yaml logs neo4j opensearch"
    (cd "$AKG_ROOT" && poetry run python scripts/stack_check.py wait --timeout 180 --verbose) \
        || die "Neo4j/OpenSearch are not reachable with the backend settings (NEO4J_URI, OPENSEARCH_HOST/PORT)."
}
