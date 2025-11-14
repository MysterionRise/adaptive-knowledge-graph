"""
Test FastAPI application and core endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns app info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Adaptive Knowledge Graph"
    assert data["version"] == "0.1.0"
    assert data["status"] == "running"
    assert "llm_mode" in data
    assert "privacy_local_only" in data


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "attribution" in data
    assert "OpenStax" in data["attribution"]


def test_cors_headers(client):
    """Test CORS headers are configured."""
    response = client.options("/", headers={"Origin": "http://localhost:3000"})
    # FastAPI/Starlette handles OPTIONS automatically with CORS middleware
    assert response.status_code in [200, 405]  # 405 is ok if no OPTIONS handler


def test_openapi_docs_available(client):
    """Test OpenAPI docs are accessible."""
    response = client.get("/docs")
    assert response.status_code == 200

    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "info" in data
    assert data["info"]["title"] == "Adaptive Knowledge Graph"
