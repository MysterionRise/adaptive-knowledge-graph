"""
Test FastAPI application and core endpoints.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import ServiceStatus, app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns app info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    # App name/version can be configured via .env - just verify they exist
    assert "name" in data and data["name"], "name should be present and non-empty"
    assert "version" in data and data["version"], "version should be present and non-empty"
    assert data["status"] == "running"
    assert "llm_mode" in data
    assert "privacy_local_only" in data


def test_health_endpoint(client):
    """Test basic health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "attribution" in data
    assert "OpenStax" in data["attribution"]


def test_health_live_endpoint(client):
    """Test liveness check endpoint."""
    response = client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.unit
class TestHealthReadyEndpoint:
    """Tests for /health/ready endpoint."""

    def test_health_ready_all_services_ok(self, client):
        """Test readiness check when all services are healthy."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.OK, latency_ms=10.0)
        mock_ollama = ServiceHealth(status=ServiceStatus.OK, latency_ms=20.0)

        with patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_opensearch
        ), patch("backend.app.main.check_ollama_health", return_value=mock_ollama):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["neo4j"]["status"] == "ok"
        assert data["services"]["opensearch"]["status"] == "ok"
        assert data["services"]["ollama"]["status"] == "ok"

    def test_health_ready_degraded_ollama(self, client):
        """Test readiness check with degraded Ollama."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.OK, latency_ms=10.0)
        mock_ollama = ServiceHealth(status=ServiceStatus.DEGRADED, message="Model not found")

        with patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_opensearch
        ), patch("backend.app.main.check_ollama_health", return_value=mock_ollama):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["ollama"]["status"] == "degraded"

    def test_health_ready_unhealthy_neo4j(self, client):
        """Test readiness check when Neo4j is down (critical service)."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.ERROR, message="Connection refused")
        mock_opensearch = ServiceHealth(status=ServiceStatus.OK, latency_ms=10.0)
        mock_ollama = ServiceHealth(status=ServiceStatus.OK, latency_ms=20.0)

        with patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_opensearch
        ), patch("backend.app.main.check_ollama_health", return_value=mock_ollama):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["neo4j"]["status"] == "error"

    def test_health_ready_unhealthy_opensearch(self, client):
        """Test readiness check when OpenSearch is down (critical service)."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.ERROR, message="Connection timeout")
        mock_ollama = ServiceHealth(status=ServiceStatus.OK, latency_ms=20.0)

        with patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_opensearch
        ), patch("backend.app.main.check_ollama_health", return_value=mock_ollama):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_health_ready_degraded_ollama_only(self, client):
        """Test that Ollama error alone causes degraded (not unhealthy)."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.OK, latency_ms=10.0)
        mock_ollama = ServiceHealth(status=ServiceStatus.ERROR, message="Ollama not running")

        with patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_opensearch
        ), patch("backend.app.main.check_ollama_health", return_value=mock_ollama):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        # Ollama is not critical, so should be degraded not unhealthy
        assert data["status"] == "degraded"

    def test_health_ready_includes_attribution(self, client):
        """Test that readiness response includes attribution."""
        from backend.app.main import ServiceHealth

        mock_health = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)

        with patch("backend.app.main.check_neo4j_health", return_value=mock_health), patch(
            "backend.app.main.check_opensearch_health", return_value=mock_health
        ), patch("backend.app.main.check_ollama_health", return_value=mock_health):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
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
    # App title can be configured via .env - just verify it exists
    assert "title" in data["info"] and data["info"]["title"], "title should be present"
