"""
Test that the Makefile targets exist, are declared .PHONY and point at real scripts.
"""

import re
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path("Makefile")

REQUIRED_TARGETS = [
    # getting started
    "quickstart",
    "doctor",
    "up",
    "down",
    "seed",
    "build-windows",
    # install / quality
    "install",
    "install-dev",
    "test",
    "test-fast",
    "test-tribunal",
    "lint",
    "format",
    "type-check",
    "pre-commit",
    "clean",
    # containerised stack
    "docker-build",
    "docker-up",
    "docker-down",
    "docker-logs",
    "docker-ps",
    # pipeline
    "ingest-books",
    "build-kg",
    "index-rag",
    "pipeline-all",
    # run / eval / demo
    "run-api",
    "run-frontend",
    "dev-setup",
    "eval-rag",
    "eval-rag-api",
    "demo-seed",
    "demo-check",
    "demo-client-prep",
    "demo-client-check",
    "demo-client-reset",
    "demo-eval",
]

REMOVED_TARGETS = [
    "export-rdf",  # pointed at a missing script
    "test-watch",  # needed an uninstalled tool
    "install-student",  # unused git dependencies
    "fetch-data",  # legacy Biology pipeline
    "parse-data",
    "normalize-data",
]


def run_make(*args: str) -> subprocess.CompletedProcess:
    """Dry-run make (-n) and return the result."""
    return subprocess.run(
        ["make", "-n", *args],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )


def makefile_targets() -> set[str]:
    return set(re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]*):", MAKEFILE.read_text(), re.MULTILINE))


def phony_targets() -> set[str]:
    text = MAKEFILE.read_text().replace("\\\n", " ")
    declared: set[str] = set()
    for line in re.findall(r"^\.PHONY:(.*)$", text, re.MULTILINE):
        declared.update(line.split())
    return declared


def test_makefile_exists():
    assert MAKEFILE.exists(), "Makefile not found"


def test_help_lists_getting_started_targets():
    result = subprocess.run(["make", "help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    listed = {
        line.split()[0]
        for line in re.sub(r"\x1b\[[0-9;]*m", "", result.stdout).splitlines()
        if line.startswith("  ") and line.strip()
    }
    for target in ["quickstart", "doctor", "up", "down", "seed", "build-windows"]:
        assert target in listed, f"help misses {target}"


@pytest.mark.parametrize("target", REQUIRED_TARGETS)
def test_required_target_dry_runs(target):
    result = run_make(target)
    assert result.returncode == 0, f"Target '{target}' not found or invalid: {result.stderr}"


@pytest.mark.parametrize("target", REMOVED_TARGETS)
def test_removed_target_is_gone(target):
    assert target not in makefile_targets()


def test_every_target_is_phony():
    missing = makefile_targets() - phony_targets()
    assert not missing, f"targets missing from .PHONY: {sorted(missing)}"


def test_every_target_has_help_text():
    text = MAKEFILE.read_text()
    undocumented = [
        target
        for target in makefile_targets()
        if not re.search(rf"^{re.escape(target)}:.*## ", text, re.MULTILINE)
    ]
    assert not undocumented, f"targets without '## help': {undocumented}"


def test_referenced_scripts_exist():
    scripts = set(re.findall(r"scripts/[\w.-]+\.(?:py|sh)", MAKEFILE.read_text()))
    assert scripts, "no scripts referenced"
    missing = sorted(s for s in scripts if not Path(s).exists())
    assert not missing, f"Makefile references missing scripts: {missing}"


def test_quickstart_runs_the_quickstart_script():
    result = run_make("quickstart")
    assert result.returncode == 0
    assert "bash scripts/quickstart.sh" in result.stdout


def test_up_waits_for_healthy_databases():
    result = run_make("up")
    assert result.returncode == 0
    # scripts/compose.sh wraps infra/compose/compose.yaml (+ .env, + the Linux override)
    assert "bash scripts/compose.sh up -d --wait" in result.stdout
    assert "neo4j opensearch" in result.stdout


def test_down_covers_every_profile():
    result = run_make("down")
    assert result.returncode == 0
    assert "--profile '*' down" in result.stdout


def test_docker_up_starts_the_selected_profile():
    default = run_make("docker-up")
    assert default.returncode == 0
    assert "--profile cpu up" in default.stdout
    gpu = run_make("docker-up", "PROFILE=gpu")
    assert "--profile gpu up" in gpu.stdout


def test_subject_is_forwarded():
    assert "seed_demo.sh economics" in run_make("seed", "SUBJECT=economics").stdout
    windows = run_make("build-windows", "SUBJECT=economics").stdout
    assert "build_chunk_windows.py --subject economics" in windows
    assert "--reset economics" in run_make("pipeline-all", "SUBJECT=economics").stdout


def test_tribunal_run_skips_the_coverage_gate():
    # A tribunal-only run covers far less than the coverage floor
    assert "pytest -m tribunal --no-cov" in run_make("test-tribunal").stdout


def test_run_api_binds_loopback_by_default():
    result = run_make("run-api")
    assert "--host 127.0.0.1" in result.stdout
    assert "--port 8000" in result.stdout
