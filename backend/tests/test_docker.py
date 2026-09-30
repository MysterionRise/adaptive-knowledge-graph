"""
Test the Docker Compose stack and the Dockerfiles.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

COMPOSE_FILE = Path("infra/compose/compose.yaml")
LINUX_OVERRIDE = Path("infra/compose/compose.linux.yaml")
CPU_DOCKERFILE = Path("infra/docker/api.cpu.Dockerfile")
GPU_DOCKERFILE = Path("infra/docker/api.gpu.Dockerfile")
FRONTEND_DOCKERFILE = Path("infra/docker/frontend.Dockerfile")

# Host port variables and their defaults (documented in the compose header and the README)
PORT_VARIABLES = {
    "neo4j": {"7474": ("NEO4J_HTTP_PORT", "7474"), "7687": ("NEO4J_BOLT_PORT", "7687")},
    "opensearch": {"9200": ("OPENSEARCH_PORT", "9200")},
    "api-cpu": {"8000": ("API_PORT", "8000")},
    "api-gpu": {"8000": ("API_PORT", "8000")},
    "frontend": {"3000": ("FRONTEND_PORT", "3000")},
    "ollama": {"11434": ("OLLAMA_PORT", "11434")},
}


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE_FILE.exists(), "compose file not found"
    return yaml.safe_load(COMPOSE_FILE.read_text())


@pytest.fixture(scope="module")
def services(compose) -> dict:
    return compose["services"]


def test_project_name_and_services(compose, services):
    assert compose["name"] == "adaptive-kg"
    assert set(services) == {"neo4j", "opensearch", "api-cpu", "api-gpu", "frontend", "ollama"}


def test_container_names_are_project_scoped(services):
    for name, service in services.items():
        # Isolated projects (COMPOSE_PROJECT_NAME=...) must never reuse the default names
        assert service["container_name"] == f"${{COMPOSE_PROJECT_NAME:-adaptive-kg}}-{name}"


def test_images_are_pinned(services):
    assert services["neo4j"]["image"] == "neo4j:5.26-community"
    assert services["opensearch"]["image"] == "opensearchproject/opensearch:3.9.0"
    for service in services.values():
        if "image" in service:
            assert not service["image"].endswith(":latest")
            assert ":" in service["image"]


def test_ports_bind_loopback_with_configurable_host_ports(services):
    port_re = re.compile(
        r"^(?P<ip>[^:]+):(?P<published>\$\{[A-Z0-9_]+:-\d+\}|\d+):(?P<target>\d+)$"
    )
    seen = 0
    for name, service in services.items():
        for port in service.get("ports", []):
            match = port_re.match(str(port))
            assert match, f"{name}: unexpected port syntax {port!r}"
            assert match["ip"] == "127.0.0.1", f"{name} publishes {port} on all interfaces"
            variable, default = PORT_VARIABLES[name][match["target"]]
            assert match["published"] == f"${{{variable}:-{default}}}", port
            seen += 1
    assert seen == 7


def test_databases_have_healthchecks(services):
    for name in ("neo4j", "opensearch"):
        healthcheck = services[name]["healthcheck"]
        assert healthcheck["start_period"]
        assert healthcheck["retries"] >= 5
    opensearch_test = " ".join(services["opensearch"]["healthcheck"]["test"])
    assert "_cluster/health?wait_for_status=yellow" in opensearch_test
    neo4j_test = " ".join(services["neo4j"]["healthcheck"]["test"])
    assert "cypher-shell" in neo4j_test


def test_neo4j_apoc_is_restricted_and_gds_dropped(services):
    env = services["neo4j"]["environment"]
    assert env["NEO4J_PLUGINS"] == '["apoc"]'
    assert env["NEO4J_dbms_security_procedures_allowlist"] == "apoc.meta.*"
    # The image would otherwise default unrestricted to apoc.*
    assert env["NEO4J_dbms_security_procedures_unrestricted"] == "apoc.meta.*"
    assert env["NEO4J_apoc_import_file_enabled"] == "false"
    assert "graph-data-science" not in COMPOSE_FILE.read_text()


def test_passwords_are_shared_between_databases_and_api(services):
    neo4j_env = services["neo4j"]["environment"]
    opensearch_env = services["opensearch"]["environment"]
    assert neo4j_env["NEO4J_AUTH"] == "neo4j/${NEO4J_PASSWORD:-password}"
    opensearch_password = opensearch_env["OPENSEARCH_INITIAL_ADMIN_PASSWORD"]
    assert opensearch_password.startswith("${OPENSEARCH_PASSWORD:-")
    for name in ("api-cpu", "api-gpu"):
        env = services[name]["environment"]
        assert env["NEO4J_PASSWORD"] == "${NEO4J_PASSWORD:-password}"
        assert env["OPENSEARCH_PASSWORD"] == opensearch_password


def test_api_services_reach_the_stack_and_host_ollama(services):
    for name in ("api-cpu", "api-gpu"):
        service = services[name]
        env = service["environment"]
        assert env["NEO4J_URI"] == "bolt://neo4j:7687"
        assert env["OPENSEARCH_HOST"] == "opensearch"
        assert env["LLM_OLLAMA_HOST"] == (
            "${CONTAINER_OLLAMA_HOST:-http://host.docker.internal:11434}"
        )
        # Desktop engines resolve host.docker.internal themselves; host-gateway would point at
        # the VM on Rancher Desktop/Colima, so only the Linux override adds it.
        assert "extra_hosts" not in service
        assert service["env_file"] == [{"path": "../../.env", "required": False}]
        assert service["depends_on"]["neo4j"]["condition"] == "service_healthy"
        assert service["depends_on"]["opensearch"]["condition"] == "service_healthy"
        assert "healthcheck" in service


def test_profiles(services):
    assert "profiles" not in services["neo4j"]
    assert "profiles" not in services["opensearch"]
    assert services["api-cpu"]["profiles"] == ["cpu", "full"]
    assert services["api-gpu"]["profiles"] == ["gpu"]
    assert services["frontend"]["profiles"] == ["full"]
    assert services["ollama"]["profiles"] == ["ollama"]


def test_linux_override_maps_host_gateway_for_the_api():
    override = yaml.safe_load(LINUX_OVERRIDE.read_text())
    assert set(override["services"]) == {"api-cpu", "api-gpu"}
    for service in override["services"].values():
        assert service["extra_hosts"] == ["host.docker.internal:host-gateway"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
@pytest.mark.parametrize(
    ("profile", "linux"),
    [(None, False), ("cpu", False), ("gpu", False), ("full", False), ("ollama", False)]
    + [("cpu", True), ("gpu", True)],
)
def test_compose_config_is_valid(profile, linux):
    version = subprocess.run(
        ["docker", "compose", "version", "--short"], capture_output=True, text=True, check=False
    )
    if version.returncode != 0:
        pytest.skip("docker compose plugin not installed")
    command = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    if linux:
        command += ["-f", str(LINUX_OVERRIDE)]
    if profile:
        command += ["--profile", profile]
    result = subprocess.run([*command, "config", "-q"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cpu_dockerfile():
    content = CPU_DOCKERFILE.read_text()
    assert "ARG PYTHON_IMAGE=python:3.12-slim" in content
    assert "ARG POETRY_VERSION=2.4.1" in content
    assert 'pip install "poetry==${POETRY_VERSION}"' in content
    assert "install.python-poetry.org" not in content
    assert "poetry install --only main --no-root" in content
    assert "--without" not in content
    assert "COPY --chown=app:app config/ ./config/" in content
    assert "spacy download en_core_web_sm" in content
    assert "USER app" in content
    assert "EXPOSE 8000" in content
    _assert_dependency_layer_is_cleaned(content)


def _assert_dependency_layer_is_cleaned(content: str) -> None:
    # Caches live in a BuildKit cache mount, and compilers/Poetry go away in the same layer
    assert "--mount=type=cache,target=/root/.cache" in content
    assert "rm -rf /opt/poetry" in content
    assert "apt-get purge -y --auto-remove" in content


def test_gpu_dockerfile():
    content = GPU_DOCKERFILE.read_text()
    assert re.search(r"ARG CUDA_IMAGE=nvidia/cuda:12\.8\.\d+-\w+-ubuntu24\.04", content)
    assert "ubuntu22.04" not in content
    assert "python3.12" not in content  # Ubuntu 24.04's python3 is 3.12
    assert "download.pytorch.org" not in content  # the locked torch wheel ships CUDA 12.8
    assert 'pip install "poetry==${POETRY_VERSION}"' in content
    assert "COPY --chown=app:app config/ ./config/" in content
    assert "USER app" in content
    assert "CUDA_VISIBLE_DEVICES" in content
    assert "EXPOSE 8000" in content
    _assert_dependency_layer_is_cleaned(content)


def test_frontend_dockerfile():
    content = FRONTEND_DOCKERFILE.read_text()
    assert "ARG NODE_IMAGE=node:24" in content
    assert "npm ci" in content
    assert "ARG NEXT_PUBLIC_API_URL" in content
    assert "USER node" in content
    assert "EXPOSE 3000" in content


def test_dockerignore_exists():
    """Test .dockerignore exists (will create if missing)."""
    # This test documents that we should have one
    dockerignore = Path(".dockerignore")
    if not dockerignore.exists():
        pytest.skip(".dockerignore not yet created (should be added)")
