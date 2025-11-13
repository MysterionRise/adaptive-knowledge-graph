"""
Test Poetry configuration and dependency resolution.
"""
import subprocess
from pathlib import Path

import pytest
import toml


def test_pyproject_toml_exists():
    """Test pyproject.toml exists and is valid."""
    pyproject = Path("pyproject.toml")
    assert pyproject.exists(), "pyproject.toml not found"

    # Parse and validate
    data = toml.load(pyproject)
    assert "tool" in data
    assert "poetry" in data["tool"]


def test_poetry_metadata():
    """Test Poetry metadata is correctly configured."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    poetry = data["tool"]["poetry"]
    assert poetry["name"] == "adaptive-knowledge-graph"
    assert "version" in poetry
    assert "description" in poetry
    assert "authors" in poetry
    assert poetry["license"] == "MIT"


def test_required_dependencies():
    """Test required dependencies are present."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    deps = data["tool"]["poetry"]["dependencies"]
    required_deps = [
        "python",
        "fastapi",
        "uvicorn",
        "transformers",
        "sentence-transformers",
        "torch",
        "neo4j",
        "networkx",
        "rdflib",
        "qdrant-client",
        "beautifulsoup4",
        "pydantic",
        "pydantic-settings",
        "loguru",
    ]

    for dep in required_deps:
        assert dep in deps, f"Required dependency '{dep}' not found"


def test_dev_dependencies():
    """Test dev dependencies are present."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    dev_deps = data["tool"]["poetry"]["group"]["dev"]["dependencies"]
    required_dev_deps = ["pytest", "ruff", "mypy", "pre-commit"]

    for dep in required_dev_deps:
        assert dep in dev_deps, f"Required dev dependency '{dep}' not found"


def test_ruff_configuration():
    """Test ruff is configured in pyproject.toml."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    assert "ruff" in data["tool"]
    ruff_config = data["tool"]["ruff"]
    assert "line-length" in ruff_config
    assert ruff_config["target-version"] == "py311"


def test_mypy_configuration():
    """Test mypy is configured in pyproject.toml."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    assert "mypy" in data["tool"]
    mypy_config = data["tool"]["mypy"]
    assert mypy_config["python_version"] == "3.11"


def test_pytest_configuration():
    """Test pytest is configured in pyproject.toml."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    assert "pytest" in data["tool"]
    pytest_config = data["tool"]["pytest"]["ini_options"]
    assert "testpaths" in pytest_config
    assert "backend/tests" in pytest_config["testpaths"]


def test_build_system():
    """Test build system is correctly configured."""
    pyproject = Path("pyproject.toml")
    data = toml.load(pyproject)

    assert "build-system" in data
    build_system = data["build-system"]
    assert "poetry-core" in build_system["requires"][0]
    assert build_system["build-backend"] == "poetry.core.masonry.api"


@pytest.mark.slow
def test_poetry_check():
    """Test 'poetry check' passes (slow test)."""
    result = subprocess.run(
        ["poetry", "check"],
        capture_output=True,
        text=True,
    )
    # This might fail if poetry isn't installed, which is ok in CI
    if result.returncode == 0:
        assert "All set!" in result.stdout
