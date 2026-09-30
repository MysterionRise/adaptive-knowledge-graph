"""
Tests for API key authentication (backend/app/core/auth.py).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.core.auth import get_optional_api_key, get_request_settings, verify_api_key
from backend.app.core.settings import Settings, settings

pytestmark = pytest.mark.unit

NON_ASCII_KEY = "clé-🔑".encode()


def _client(**overrides) -> TestClient:
    """Client for a minimal app whose routes use the auth dependencies."""
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, **overrides)

    @app.get("/protected")
    def protected(api_key: str = Depends(verify_api_key)):
        return {"api_key": api_key}

    @app.get("/optional")
    def optional(api_key: str | None = Depends(get_optional_api_key)):
        return {"api_key": api_key}

    return TestClient(app)


class TestVerifyApiKey:
    def test_development_without_key_allows_requests(self):
        response = _client(app_env="development", api_key="").get("/protected")

        assert response.status_code == 200
        assert response.json() == {"api_key": "development"}

    @pytest.mark.parametrize("app_env", ["development", "production"])
    def test_configured_key_is_enforced(self, app_env):
        client = _client(app_env=app_env, api_key="s3cret")

        missing = client.get("/protected")
        wrong = client.get("/protected", headers={"X-API-Key": "wrong"})
        right = client.get("/protected", headers={"X-API-Key": "s3cret"})

        assert missing.status_code == 401
        assert missing.json()["detail"] == "Missing API key. Include X-API-Key header."
        assert missing.headers["WWW-Authenticate"] == "ApiKey"
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "Invalid API key"
        assert right.status_code == 200
        assert right.json() == {"api_key": "s3cret"}

    @pytest.mark.parametrize("api_key", ["", "   ", "\t"])
    def test_production_without_key_fails_closed(self, api_key):
        """create_app() refuses this configuration; the dependency rejects it anyway."""
        client = _client(app_env="production", api_key=api_key)

        assert client.get("/protected").status_code == 401
        assert client.get("/protected", headers={"X-API-Key": "anything"}).status_code == 401

    def test_whitespace_only_key_in_development_means_keyless(self):
        response = _client(app_env="development", api_key="   ").get("/protected")

        assert response.json() == {"api_key": "development"}

    @pytest.mark.parametrize("app_env", ["development", "production"])
    def test_non_ascii_key_is_rejected_not_a_server_error(self, app_env):
        """compare_digest used to raise TypeError on non-ASCII str input (HTTP 500)."""
        client = _client(app_env=app_env, api_key="s3cret")

        response = client.get("/protected", headers={"X-API-Key": NON_ASCII_KEY})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid API key"


class TestGetOptionalApiKey:
    def test_no_key_is_anonymous(self):
        response = _client(app_env="production", api_key="s3cret").get("/optional")

        assert response.status_code == 200
        assert response.json() == {"api_key": None}

    def test_valid_key_is_returned(self):
        client = _client(app_env="production", api_key="s3cret")

        response = client.get("/optional", headers={"X-API-Key": "s3cret"})

        assert response.json() == {"api_key": "s3cret"}

    @pytest.mark.parametrize("header", ["wrong", NON_ASCII_KEY])
    def test_invalid_key_is_rejected(self, header):
        client = _client(app_env="production", api_key="s3cret")

        assert client.get("/optional", headers={"X-API-Key": header}).status_code == 401

    def test_production_without_key_rejects_any_key(self):
        client = _client(app_env="production", api_key="")

        assert client.get("/optional", headers={"X-API-Key": "anything"}).status_code == 401

    def test_development_without_key_passes_a_supplied_key_through(self):
        client = _client(app_env="development", api_key="")

        response = client.get("/optional", headers={"X-API-Key": "anything"})

        assert response.json() == {"api_key": "anything"}


def test_request_settings_fall_back_to_global_settings():
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    assert get_request_settings(request) is settings


class TestProductionApp:
    """The real app in production mode (create_app with APP_ENV=production)."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/v1/student/profile"),
            ("post", "/api/v1/student/reset"),
            ("get", "/api/v1/student/all-difficulties"),
            ("post", "/api/v1/graph/query"),
        ],
    )
    def test_protected_routes_require_the_key(self, production_client, method, path):
        response = getattr(production_client, method)(path)

        assert response.status_code == 401

    def test_non_ascii_key_on_a_protected_route_is_401(self, production_client):
        response = production_client.get(
            "/api/v1/student/profile", headers={"X-API-Key": NON_ASCII_KEY}
        )

        assert response.status_code == 401

    def test_valid_key_is_accepted(self, production_client, production_settings):
        service = MagicMock()
        service.get_profile_response.return_value = {
            "student_id": "default",
            "overall_ability": 0.3,
            "mastery_levels": {},
            "updated_at": datetime.now(UTC),
        }

        with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
            response = production_client.get(
                "/api/v1/student/profile", headers={"X-API-Key": production_settings.api_key}
            )

        assert response.status_code == 200

    def test_development_app_stays_keyless(self, development_client):
        service = MagicMock()
        service.get_profile_response.return_value = {
            "student_id": "default",
            "overall_ability": 0.3,
            "mastery_levels": {},
            "updated_at": datetime.now(UTC),
        }

        with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
            response = development_client.get("/api/v1/student/profile")

        assert response.status_code == 200
