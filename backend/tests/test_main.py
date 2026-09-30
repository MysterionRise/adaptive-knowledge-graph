"""
Test FastAPI application and core endpoints.
"""

from importlib.metadata import PackageNotFoundError, version
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.exceptions import ConfigurationError
from backend.app.core.settings import Settings
from backend.app.main import (
    PROJECT_URL,
    ServiceHealth,
    ServiceStatus,
    app,
    create_app,
    docs_enabled,
)


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

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j),
            patch("backend.app.main.check_opensearch_health", return_value=mock_opensearch),
            patch("backend.app.main.check_ollama_health", return_value=mock_ollama),
        ):
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

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j),
            patch("backend.app.main.check_opensearch_health", return_value=mock_opensearch),
            patch("backend.app.main.check_ollama_health", return_value=mock_ollama),
        ):
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

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j),
            patch("backend.app.main.check_opensearch_health", return_value=mock_opensearch),
            patch("backend.app.main.check_ollama_health", return_value=mock_ollama),
        ):
            response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["neo4j"]["status"] == "error"

    def test_health_ready_unhealthy_opensearch(self, client):
        """Test readiness check when OpenSearch is down (critical service)."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.ERROR, message="Connection timeout")
        mock_ollama = ServiceHealth(status=ServiceStatus.OK, latency_ms=20.0)

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j),
            patch("backend.app.main.check_opensearch_health", return_value=mock_opensearch),
            patch("backend.app.main.check_ollama_health", return_value=mock_ollama),
        ):
            response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_health_ready_degraded_ollama_only(self, client):
        """Test that Ollama error alone causes degraded (not unhealthy)."""
        from backend.app.main import ServiceHealth

        mock_neo4j = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)
        mock_opensearch = ServiceHealth(status=ServiceStatus.OK, latency_ms=10.0)
        mock_ollama = ServiceHealth(status=ServiceStatus.ERROR, message="Ollama not running")

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_neo4j),
            patch("backend.app.main.check_opensearch_health", return_value=mock_opensearch),
            patch("backend.app.main.check_ollama_health", return_value=mock_ollama),
        ):
            response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        # Ollama is not critical, so should be degraded not unhealthy
        assert data["status"] == "degraded"

    def test_health_ready_includes_attribution(self, client):
        """Test that readiness response includes attribution."""
        from backend.app.main import ServiceHealth

        mock_health = ServiceHealth(status=ServiceStatus.OK, latency_ms=5.0)

        with (
            patch("backend.app.main.check_neo4j_health", return_value=mock_health),
            patch("backend.app.main.check_opensearch_health", return_value=mock_health),
            patch("backend.app.main.check_ollama_health", return_value=mock_health),
        ):
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


def test_openapi_docs_available(development_client):
    """OpenAPI docs are served in development mode (the default APP_ENV)."""
    response = development_client.get("/docs")
    assert response.status_code == 200

    response = development_client.get("/redoc")
    assert response.status_code == 200

    response = development_client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "info" in data
    # App title can be configured via .env - just verify it exists
    assert "title" in data["info"] and data["info"]["title"], "title should be present"


@pytest.mark.asyncio
async def test_opensearch_health_respects_verify_certs(monkeypatch):
    """OpenSearch readiness should use the configured TLS verification setting."""
    from backend.app import main

    captured_kwargs = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "green"}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, auth=None):
            return FakeResponse()

    monkeypatch.setattr(main.settings, "opensearch_verify_certs", True)
    monkeypatch.setattr(main.settings, "opensearch_use_ssl", True)
    monkeypatch.setattr(main.settings, "opensearch_password", "")
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    health = await main.check_opensearch_health()

    assert health.status == ServiceStatus.OK
    assert captured_kwargs["verify"] is True


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.mark.unit
class TestAppEnvironment:
    """APP_ENV=development|production behaviour of create_app()."""

    def test_production_refuses_to_start_without_api_key(self):
        with pytest.raises(ConfigurationError, match="API_KEY must be set"):
            create_app(_settings(app_env="production", api_key=""))

    @pytest.mark.parametrize("field", ["cors_origins", "cors_allow_methods", "cors_allow_headers"])
    def test_production_refuses_wildcard_cors(self, field):
        with pytest.raises(ConfigurationError, match=field.upper()):
            create_app(_settings(app_env="production", api_key="k", **{field: "*"}))

    def test_development_allows_keyless_startup(self):
        assert create_app(_settings(app_env="development", api_key="")).state.settings.api_key == ""

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_production_hides_api_docs(self, production_client, path):
        assert production_client.get(path).status_code == 404

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_production_docs_can_be_enabled(self, path):
        client = TestClient(
            create_app(_settings(app_env="production", api_key="k", api_docs_enabled=True))
        )

        assert client.get(path).status_code == 200

    def test_development_docs_can_be_disabled(self):
        client = TestClient(create_app(_settings(app_env="development", api_docs_enabled=False)))

        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    @pytest.mark.parametrize(
        ("app_env", "flag", "expected"),
        [
            ("development", None, True),
            ("production", None, False),
            ("development", False, False),
            ("production", True, True),
        ],
    )
    def test_docs_enabled(self, app_env, flag, expected):
        assert docs_enabled(_settings(app_env=app_env, api_docs_enabled=flag)) is expected

    def test_keyless_development_startup_logs_a_warning(self):
        with (
            patch("backend.app.main.setup_logging"),
            patch("backend.app.main.logger") as mock_logger,
            TestClient(create_app(_settings(app_env="development", api_key=""))),
        ):
            pass

        warnings = " ".join(str(call.args[0]) for call in mock_logger.warning.call_args_list)
        assert "API_KEY is not set" in warnings

    def test_startup_with_api_key_does_not_warn(self):
        with (
            patch("backend.app.main.setup_logging"),
            patch("backend.app.main.logger") as mock_logger,
            TestClient(create_app(_settings(app_env="production", api_key="k"))),
        ):
            pass

        mock_logger.warning.assert_not_called()

    def test_root_reports_the_app_settings(self):
        client = TestClient(create_app(_settings(app_name="Custom Name")))

        assert client.get("/").json()["name"] == "Custom Name"


@pytest.mark.unit
class TestOpenAPIMetadata:
    def test_title_version_and_contact(self, development_client):
        info = development_client.get("/openapi.json").json()["info"]

        assert info["title"] == Settings.model_fields["app_name"].default
        assert info["title"] == "Adaptive Knowledge Graph"
        assert info["version"] == version("adaptive-knowledge-graph")
        assert info["contact"]["url"] == PROJECT_URL
        assert "Privacy-First" not in info["description"]

    def test_version_falls_back_when_package_metadata_is_missing(self, monkeypatch):
        def missing(name):
            raise PackageNotFoundError(name)

        monkeypatch.setattr("backend.app.core.settings.version", missing)

        assert _settings().app_version == "0.0.0+unknown"


@pytest.mark.unit
class TestCORS:
    def _preflight(self, client, method="POST", headers=None):
        request_headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": method,
        }
        if headers:
            request_headers["Access-Control-Request-Headers"] = headers
        return client.options("/api/v1/ask", headers=request_headers)

    def test_allowed_method_and_headers(self, client):
        response = self._preflight(client, headers="Content-Type, X-API-Key, X-Request-ID")

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        allowed_headers = response.headers["access-control-allow-headers"].lower()
        assert "x-api-key" in allowed_headers and "x-request-id" in allowed_headers

    @pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
    def test_other_methods_are_refused(self, client, method):
        response = self._preflight(client, method=method)

        assert response.status_code == 400
        assert response.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"

    def test_unknown_request_headers_are_refused(self, client):
        response = self._preflight(client, headers="X-Custom-Evil-Header")

        assert response.status_code == 400
        assert "x-custom-evil-header" not in response.headers["access-control-allow-headers"]


@pytest.mark.unit
def test_health_ready_error_messages_are_redacted(client):
    """Unauthenticated readiness output never includes URIs, credentials, hosts or IPs."""
    failure = RuntimeError(
        "Couldn't connect to neo4j://neo4j:s3cret@db.internal.example:7687 (10.1.2.3:7687)"
    )
    ok = ServiceHealth(status=ServiceStatus.OK)

    with (
        patch("backend.app.kg.neo4j_adapter.Neo4jAdapter", side_effect=failure),
        patch("backend.app.main.check_opensearch_health", return_value=ok),
        patch("backend.app.main.check_ollama_health", return_value=ok),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    message = response.json()["services"]["neo4j"]["message"]
    for leak in ("neo4j://", "s3cret", "db.internal", "7687", "10.1.2.3"):
        assert leak not in message


@pytest.mark.unit
def test_validation_errors_do_not_echo_the_payload(client):
    """A 1 MB question used to be reflected in full by the default 422 handler."""
    response = client.post("/api/v1/ask", json={"question": "x" * 1_000_000})

    assert response.status_code == 422
    assert len(response.content) < 1000
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("supplied", "echoed"),
    [
        ("req-123_abc.DEF", True),
        ("x" * 129, False),
        ("has spaces", False),
        ("<script>", False),
    ],
)
def test_request_id_header_is_sanitized(client, supplied, echoed):
    response = client.get("/health/live", headers={"X-Request-ID": supplied})

    assert (response.headers["X-Request-ID"] == supplied) is echoed
    assert 0 < len(response.headers["X-Request-ID"]) <= 128
