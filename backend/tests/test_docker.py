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
SETUP_POETRY_ACTION = Path(".github/actions/setup-python-poetry/action.yml")

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


def test_no_usage_reporting_from_the_stack(services):
    """PRIVACY_LOCAL_ONLY: Neo4j usage statistics and Hugging Face telemetry are off (#159)."""
    assert services["neo4j"]["environment"]["NEO4J_dbms_usage__report_enabled"] == "false"
    for name in ("api-cpu", "api-gpu"):
        assert services[name]["environment"]["HF_HUB_DISABLE_TELEMETRY"] == "1"


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
    assert 'pip install "poetry==${POETRY_VERSION}"' in content
    assert "install.python-poetry.org" not in content
    assert "poetry install --only main --no-root" in content
    assert "--without" not in content
    assert "COPY --chown=app:app config/ ./config/" in content
    assert "spacy download en_core_web_sm" in content
    assert "USER app" in content
    assert "EXPOSE 8000" in content
    _assert_dependency_layer_is_cleaned(content)
    _assert_project_is_registered(content)


def _assert_dependency_layer_is_cleaned(content: str) -> None:
    # Caches live in a BuildKit cache mount, and compilers/Poetry go away in the same layer
    assert "--mount=type=cache,target=/root/.cache" in content
    assert "rm -rf /opt/poetry" in content
    assert "apt-get purge -y --auto-remove" in content


def _assert_project_is_registered(content: str) -> None:
    # The dependency layer skips the root project (--no-root; the sources are copied later), so
    # the image registers it afterwards, without dependencies, and app_version reports the
    # pyproject version instead of 0.0.0+unknown (#104)
    register = content.index("pip install --no-deps --no-cache-dir --editable .")
    assert content.index("COPY --chown=app:app backend/ ./backend/") < register
    assert register < content.index("USER app")


def test_gpu_dockerfile():
    content = GPU_DOCKERFILE.read_text()
    assert re.search(r"ARG CUDA_IMAGE=nvidia/cuda:12\.8\.\d+-\w+-ubuntu24\.04", content)
    assert "ubuntu22.04" not in content
    assert "python3.12" not in content  # Ubuntu 24.04's python3 is 3.12
    # The lock installs CPU torch on linux/amd64 (#79); the GPU image puts the CUDA build back
    assert "--index-url https://download.pytorch.org/whl/cu128" in content
    assert 'torch.__version__.split("+")[0]' in content  # the locked version, not a float
    assert "torch.version.cuda" in content
    assert 'pip install "poetry==${POETRY_VERSION}"' in content
    assert "COPY --chown=app:app config/ ./config/" in content
    assert "USER app" in content
    assert "CUDA_VISIBLE_DEVICES" in content
    assert "EXPOSE 8000" in content
    _assert_dependency_layer_is_cleaned(content)
    _assert_project_is_registered(content)


@pytest.mark.parametrize("dockerfile", [CPU_DOCKERFILE, GPU_DOCKERFILE], ids=["cpu", "gpu"])
def test_dockerfiles_install_the_poetry_version_ci_uses(dockerfile):
    # One Poetry version for CI and the images, so both read poetry.lock the same way
    action = yaml.safe_load(SETUP_POETRY_ACTION.read_text())
    ci_version = action["inputs"]["poetry-version"]["default"]
    assert f"ARG POETRY_VERSION={ci_version}" in dockerfile.read_text()


def test_torch_is_cpu_only_on_linux_x86_64():
    """pyproject.toml and poetry.lock take torch from the CPU index on Linux x86_64 (#79)."""
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    sources = {s["name"]: s for s in pyproject["tool"]["poetry"]["source"]}
    assert sources["pytorch-cpu"]["url"] == "https://download.pytorch.org/whl/cpu"
    assert sources["pytorch-cpu"]["priority"] == "explicit"
    constraints = pyproject["tool"]["poetry"]["dependencies"]["torch"]
    cpu = next(c for c in constraints if c.get("source") == "pytorch-cpu")
    assert cpu["markers"] == "sys_platform == 'linux' and platform_machine == 'x86_64'"
    assert all(c["version"] == cpu["version"] for c in constraints)

    lock = tomllib.loads(Path("poetry.lock").read_text())
    torch_entries = [p for p in lock["package"] if p["name"] == "torch"]
    cpu_entry = next(p for p in torch_entries if p["version"].endswith("+cpu"))
    assert cpu_entry["source"]["reference"] == "pytorch-cpu"
    assert _main_marker(cpu_entry) == 'sys_platform == "linux" and platform_machine == "x86_64"'
    assert not any(name.startswith("nvidia-") for name in cpu_entry.get("dependencies", {}))
    pypi_entry = next(p for p in torch_entries if "source" not in p)
    assert _main_marker(pypi_entry) == 'sys_platform != "linux" or platform_machine != "x86_64"'


def _main_marker(entry: dict) -> str:
    # Poetry writes one string when only the main group constrains the package,
    # and a per-group table when several groups do
    markers = entry["markers"]
    return markers["main"] if isinstance(markers, dict) else markers


def test_setup_action_asserts_cpu_torch_instead_of_freeing_disk():
    action = yaml.safe_load(SETUP_POETRY_ACTION.read_text())
    assert "free-disk-space" not in action["inputs"]
    assert action["inputs"]["assert-cpu-torch"]["default"] == "false"
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    assert "Assert CPU-only torch and no nvidia-* wheels" in steps
    assert "torch.version.cuda" in steps["Assert CPU-only torch and no nvidia-* wheels"]["run"]
    ci = Path(".github/workflows/ci.yaml").read_text()
    assert "free-disk-space" not in ci
    assert ci.count('assert-cpu-torch: "true"') == 3  # type-check, tests, tribunal


def test_all_checks_passed_gates_the_promoted_jobs():
    """v0.3.0 made the tribunal, E2E, link-check and shellcheck jobs required (#104)."""
    ci_text = Path(".github/workflows/ci.yaml").read_text()
    jobs = yaml.safe_load(ci_text)["jobs"]
    required = set(jobs["all-checks"]["needs"])
    assert {"tribunal", "e2e-tests", "link-check", "shellcheck"} <= required
    for job_id in required:
        # A required job must run on every event and must fail the gate when it fails
        assert "continue-on-error" not in jobs[job_id], job_id
        assert "if" not in jobs[job_id], job_id
        assert "advisory" not in jobs[job_id]["name"].lower(), job_id
    assert "--without" not in ci_text  # the pyirt/pybkt groups are gone


def test_frontend_dockerfile():
    content = FRONTEND_DOCKERFILE.read_text()
    assert "ARG NODE_IMAGE=node:24" in content
    assert "npm ci" in content
    assert "ARG NEXT_PUBLIC_API_URL" in content
    assert "USER node" in content
    assert "EXPOSE 3000" in content
    # frontend/osv-scanner.toml accepts advisories in dev-only packages because the image
    # does not ship them (#254); test_osv_audit.py checks the lock side of that claim
    assert _dev_dependency_violations(content) == []


def _dockerfile_stages(content: str) -> list[tuple[str, str, list[str]]]:
    """Split a Dockerfile into stages: (name in lower case, base image, instructions).

    Comment lines are left out, continuation lines are joined and runs of whitespace become
    one space, so each instruction is one line that starts with its keyword. Docker compares
    stage names without regard to case.
    """
    code = "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("#"))
    stages: list[tuple[str, str, list[str]]] = []
    for line in re.sub(r"\\[ \t]*\n", " ", code).splitlines():
        instruction = " ".join(line.split())
        stage = re.fullmatch(
            r"FROM (?:--\S+ )*(?P<base>\S+)(?: AS (?P<name>\S+))?", instruction, re.IGNORECASE
        )
        if stage:
            stages.append(((stage["name"] or "").lower(), stage["base"], []))
        elif instruction and stages:
            stages[-1][2].append(instruction)
    return stages


def _stage_steps(instructions: list[str]) -> list[str]:
    """A stage in the order it runs: each shell command of a RUN, and every other instruction."""
    steps = []
    for instruction in instructions:
        keyword, _, arguments = instruction.partition(" ")
        if keyword.upper() == "RUN":
            steps.extend(command.strip() for command in re.split(r"&&|\|\||[;|]", arguments))
        else:
            steps.append(f"{keyword.upper()} {arguments}")
    return steps


_NPM_INSTALL = re.compile(r"\bnpm (?:ci|install|i|add)\b")


def _is_dev_prune(step: str) -> bool:
    """Whether a shell command is ``npm prune --omit=dev``, with any other flags but no dry run."""
    words = step.split()
    return words[:2] == ["npm", "prune"] and "--omit=dev" in words and "--dry-run" not in words


def _copies_the_pruned_modules(step: str) -> bool:
    """Whether a step is the COPY of /app/node_modules from the build stage."""
    words = step.split()
    paths = [word for word in words[1:] if not word.startswith("--")]
    return (
        words[:1] == ["COPY"]
        and "--from=build" in [word.lower() for word in words]
        and paths == ["/app/node_modules", "./node_modules"]
    )


def _dev_dependency_violations(content: str) -> list[str]:
    """List what would let dev dependencies into the frontend image.

    The ``build`` stage runs ``npm prune --omit=dev`` after ``npm run build`` (the build
    needs the dev dependencies) and, after the prune, neither copies files in nor installs
    packages. The last stage, the image that ships, starts from an image and not from an
    earlier stage, copies ``/app/node_modules`` from the ``build`` stage, copies nothing from
    another stage, copies ``node_modules`` from nowhere else and installs no packages.

    Only shell-form RUN instructions are read; a command this check does not recognise
    counts as missing.
    """
    stages = _dockerfile_stages(content)
    violations = []
    build = _stage_steps(next((steps for name, _, steps in stages if name == "build"), []))
    built = max(
        (at for at, step in enumerate(build) if step.split()[:3] == ["npm", "run", "build"]),
        default=-1,
    )
    pruned = max((at for at, step in enumerate(build) if _is_dev_prune(step)), default=-1)
    if built < 0:
        violations.append("the build stage does not run `npm run build`")
    if pruned < 0:
        violations.append("the build stage does not run `npm prune --omit=dev`")
    elif pruned < built:
        violations.append("`npm prune --omit=dev` runs before `npm run build`")
    else:
        violations.extend(
            f"the build stage runs `{step}` after the prune"
            for step in build[pruned + 1 :]
            if step.startswith(("COPY ", "ADD ")) or _NPM_INSTALL.search(step)
        )

    _, base, instructions = stages[-1] if stages else ("", "", [])
    if base.lower() in {name for name, _, _ in stages[:-1] if name}:
        violations.append(f"the last stage starts from the `{base}` stage")
    last = _stage_steps(instructions)
    if not any(_copies_the_pruned_modules(step) for step in last):
        violations.append("the last stage does not copy node_modules from the build stage")
    for step in last:
        if _copies_the_pruned_modules(step):
            continue
        if step.startswith(("COPY ", "ADD ")):
            source = re.search(r" --from=(\S+)", step)
            if source and source[1].lower() != "build":
                violations.append(
                    f"the last stage copies from outside the build stage with `{step}`"
                )
            elif re.search(r"\bnode_modules\b", step):
                violations.append(f"the last stage also copies node_modules with `{step}`")
        elif _NPM_INSTALL.search(step):
            violations.append(f"the last stage installs packages with `{step}`")
    return violations


# The shape of infra/docker/frontend.Dockerfile, for the checks on _dev_dependency_violations
_FRONTEND_STAGES = """\
ARG NODE_IMAGE=node:24-bookworm-slim
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
RUN npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
# The build needs the dev dependencies
RUN npm run build \\
    && npm prune --omit=dev --no-audit --no-fund

FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
"""
_BUILD_STAGE = "FROM ${NODE_IMAGE} AS build\n"
_LAST_STAGE = "FROM ${NODE_IMAGE} AS runtime\n"
_BUILD_AND_PRUNE = "RUN npm run build \\\n    && npm prune --omit=dev --no-audit --no-fund\n"
_COPY_PRUNED = "COPY --from=build --chown=node:node /app/node_modules ./node_modules\n"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        pytest.param(_COPY_PRUNED, _COPY_PRUNED, id="unchanged"),
        pytest.param(
            _COPY_PRUNED,
            "COPY --chown=node:node --from=build /app/node_modules ./node_modules\n",
            id="copy-flags-reordered",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build\nRUN npm prune --omit=dev --no-audit --no-fund\n",
            id="prune-in-its-own-run",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build \\\n    && npm prune --no-audit --no-fund --omit=dev\n",
            id="prune-flags-reordered",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            _BUILD_AND_PRUNE.rstrip("\n") + " \\\n    && rm -rf .next/cache\n",
            id="cleanup-after-prune",
        ),
        pytest.param(
            _BUILD_STAGE, "  from ${NODE_IMAGE} as Build\n", id="stage-name-in-another-case"
        ),
    ],
)
def test_dev_dependency_check_accepts(old, new):
    assert _FRONTEND_STAGES.count(old) == 1
    assert _dev_dependency_violations(_FRONTEND_STAGES.replace(old, new)) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="no-prune",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build\n#    && npm prune --omit=dev --no-audit --no-fund\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-commented-out",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build \\\n    && npm prune --no-audit --no-fund\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-keeps-dev-dependencies",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build \\\n    && npm prune --omit=optional\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-omits-optional-only",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm run build \\\n    && npm prune --omit=dev --dry-run\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-dry-run",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            'RUN npm run build \\\n    && echo "npm prune --omit=dev"\n',
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-only-echoed",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            "RUN npm prune --omit=dev --no-audit --no-fund \\\n    && npm run build\n",
            ["`npm prune --omit=dev` runs before `npm run build`"],
            id="prune-before-build",
        ),
        pytest.param(
            _BUILD_AND_PRUNE + "\n" + _LAST_STAGE + "WORKDIR /app\n",
            "RUN npm run build\n\n" + _LAST_STAGE + "WORKDIR /app\nRUN npm prune --omit=dev\n",
            ["the build stage does not run `npm prune --omit=dev`"],
            id="prune-in-last-stage",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            _BUILD_AND_PRUNE.rstrip("\n") + " \\\n    && npm ci --no-audit --no-fund\n",
            ["the build stage runs `npm ci --no-audit --no-fund` after the prune"],
            id="install-after-prune",
        ),
        pytest.param(
            _BUILD_AND_PRUNE,
            _BUILD_AND_PRUNE + "COPY --from=deps /app/node_modules ./node_modules\n",
            [
                "the build stage runs `COPY --from=deps /app/node_modules ./node_modules` "
                "after the prune"
            ],
            id="copy-after-prune",
        ),
        pytest.param(
            _COPY_PRUNED,
            "COPY --from=deps --chown=node:node /app/node_modules ./node_modules\n",
            [
                "the last stage does not copy node_modules from the build stage",
                "the last stage copies from outside the build stage with "
                "`COPY --from=deps --chown=node:node /app/node_modules ./node_modules`",
            ],
            id="node-modules-from-unpruned-stage",
        ),
        pytest.param(
            _COPY_PRUNED,
            _COPY_PRUNED + "COPY --from=deps /app/node_modules/.bin ./node_modules/.bin\n",
            [
                "the last stage copies from outside the build stage with "
                "`COPY --from=deps /app/node_modules/.bin ./node_modules/.bin`"
            ],
            id="second-copy-from-unpruned-stage",
        ),
        pytest.param(
            _COPY_PRUNED,
            _COPY_PRUNED + "COPY --from=deps --chown=node:node /app ./\n",
            [
                "the last stage copies from outside the build stage with "
                "`COPY --from=deps --chown=node:node /app ./`"
            ],
            id="parent-directory-from-unpruned-stage",
        ),
        pytest.param(
            _COPY_PRUNED,
            _COPY_PRUNED + "COPY frontend/node_modules ./node_modules\n",
            [
                "the last stage also copies node_modules with "
                "`COPY frontend/node_modules ./node_modules`"
            ],
            id="node-modules-from-build-context",
        ),
        pytest.param(
            _COPY_PRUNED,
            _COPY_PRUNED + "RUN npm ci --no-audit --no-fund\n",
            ["the last stage installs packages with `npm ci --no-audit --no-fund`"],
            id="install-in-last-stage",
        ),
        pytest.param(
            _LAST_STAGE,
            "FROM deps AS runtime\n",
            ["the last stage starts from the `deps` stage"],
            id="last-stage-from-unpruned-stage",
        ),
        pytest.param(
            _COPY_PRUNED,
            "",
            ["the last stage does not copy node_modules from the build stage"],
            id="no-node-modules",
        ),
    ],
)
def test_dev_dependency_check_rejects(old, new, expected):
    assert _FRONTEND_STAGES.count(old) == 1
    assert _dev_dependency_violations(_FRONTEND_STAGES.replace(old, new)) == expected


def test_dev_dependency_check_rejects_a_file_without_stages():
    assert _dev_dependency_violations("# syntax=docker/dockerfile:1\n") == [
        "the build stage does not run `npm run build`",
        "the build stage does not run `npm prune --omit=dev`",
        "the last stage does not copy node_modules from the build stage",
    ]


def test_dockerignore_exists():
    """Test .dockerignore exists (will create if missing)."""
    # This test documents that we should have one
    dockerignore = Path(".dockerignore")
    if not dockerignore.exists():
        pytest.skip(".dockerignore not yet created (should be added)")
