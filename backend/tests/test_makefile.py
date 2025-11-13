"""
Test Makefile commands are valid and executable.
"""
import subprocess
from pathlib import Path

import pytest


def run_make_target(target: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a make target and return the result."""
    return subprocess.run(
        ["make", "-n", target],  # -n for dry run
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=check,
    )


def test_makefile_exists():
    """Test Makefile exists."""
    makefile = Path("Makefile")
    assert makefile.exists(), "Makefile not found"


def test_help_target():
    """Test 'make help' is available."""
    result = run_make_target("help")
    assert result.returncode == 0


def test_install_targets_defined():
    """Test installation targets are defined."""
    targets = ["install", "install-dev", "install-student"]
    for target in targets:
        result = run_make_target(target)
        assert result.returncode == 0, f"Target '{target}' not found or invalid"


def test_test_targets_defined():
    """Test testing targets are defined."""
    targets = ["test", "lint", "format", "type-check", "pre-commit"]
    for target in targets:
        result = run_make_target(target)
        assert result.returncode == 0, f"Target '{target}' not found or invalid"


def test_docker_targets_defined():
    """Test Docker targets are defined."""
    targets = [
        "docker-build",
        "docker-up",
        "docker-down",
        "docker-logs",
        "docker-ps",
    ]
    for target in targets:
        result = run_make_target(target)
        assert result.returncode == 0, f"Target '{target}' not found or invalid"


def test_pipeline_targets_defined():
    """Test data pipeline targets are defined."""
    targets = [
        "fetch-data",
        "parse-data",
        "normalize-data",
        "build-kg",
        "index-rag",
        "pipeline-all",
    ]
    for target in targets:
        result = run_make_target(target)
        assert result.returncode == 0, f"Target '{target}' not found or invalid"


def test_run_targets_defined():
    """Test run targets are defined."""
    targets = ["run-api", "run-frontend", "eval-rag"]
    for target in targets:
        result = run_make_target(target)
        assert result.returncode == 0, f"Target '{target}' not found or invalid"


def test_dev_setup_target():
    """Test dev-setup composite target."""
    result = run_make_target("dev-setup")
    assert result.returncode == 0


def test_clean_target():
    """Test clean target is defined."""
    result = run_make_target("clean")
    assert result.returncode == 0
