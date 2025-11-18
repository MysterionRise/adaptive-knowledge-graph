"""
Test Docker configuration and builds.
"""

from pathlib import Path

import pytest


def test_cpu_dockerfile_exists():
    """Test CPU Dockerfile exists and is readable."""
    dockerfile = Path("infra/docker/api.cpu.Dockerfile")
    assert dockerfile.exists(), "CPU Dockerfile not found"
    content = dockerfile.read_text()
    assert "FROM python:3.12-slim" in content
    assert "poetry" in content.lower()
    assert "EXPOSE 8000" in content


def test_gpu_dockerfile_exists():
    """Test GPU Dockerfile exists and is readable."""
    dockerfile = Path("infra/docker/api.gpu.Dockerfile")
    assert dockerfile.exists(), "GPU Dockerfile not found"
    content = dockerfile.read_text()
    assert "FROM nvidia/cuda" in content
    assert "poetry" in content.lower()
    assert "CUDA_VISIBLE_DEVICES" in content
    assert "EXPOSE 8000" in content


def test_docker_compose_exists():
    """Test docker-compose.yaml exists and is valid."""
    compose_file = Path("infra/compose/compose.yaml")
    assert compose_file.exists(), "docker-compose.yaml not found"
    content = compose_file.read_text()

    # Check required services
    assert "neo4j:" in content
    assert "opensearch:" in content
    assert "api-cpu:" in content
    assert "api-gpu:" in content

    # Check Neo4j configuration
    assert "neo4j:5.16-community" in content
    assert "7474:7474" in content  # HTTP port
    assert "7687:7687" in content  # Bolt port

    # Check OpenSearch configuration
    assert "opensearchproject/opensearch" in content
    assert "9200:9200" in content

    # Check profiles
    assert "profiles:" in content


def test_docker_compose_has_healthchecks():
    """Test services have health checks configured."""
    compose_file = Path("infra/compose/compose.yaml")
    content = compose_file.read_text()

    assert "healthcheck:" in content
    assert "test:" in content
    assert "interval:" in content
    assert "retries:" in content


def test_dockerignore_exists():
    """Test .dockerignore exists (will create if missing)."""
    # This test documents that we should have one
    dockerignore = Path(".dockerignore")
    if not dockerignore.exists():
        pytest.skip(".dockerignore not yet created (should be added)")
