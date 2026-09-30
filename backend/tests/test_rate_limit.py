"""
Tests for rate limiting: client identity and the pre-auth default-limit middleware.
"""

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from backend.app.core.rate_limit import (
    DEFAULT_RATE_LIMIT,
    RateLimitMiddleware,
    get_rate_limit_key,
    limiter,
    rate_limit_exceeded_handler,
)
from backend.app.core.settings import Settings, settings


def _request_with_forwarded_for(*values: bytes, app: object | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", value) for value in values]
        or [(b"x-forwarded-for", b"198.51.100.10, 198.51.100.11")],
        "client": ("203.0.113.20", 4567),
    }
    if app is not None:
        scope["app"] = app
    return Request(scope)


def test_rate_limit_ignores_forwarded_for_by_default(monkeypatch):
    """Direct local deployments should not trust spoofable X-Forwarded-For headers."""
    monkeypatch.setattr(settings, "trust_proxy_headers", False)

    assert get_rate_limit_key(_request_with_forwarded_for()) == "203.0.113.20"


def test_rate_limit_uses_rightmost_forwarded_for_when_trusted(monkeypatch):
    """Behind a trusted proxy, the right-most hop is the address the proxy saw.

    The left-most entries are whatever the client sent, so keying on them let a client
    pick a fresh identity per request.
    """
    monkeypatch.setattr(settings, "trust_proxy_headers", True)

    assert get_rate_limit_key(_request_with_forwarded_for()) == "198.51.100.11"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ((b"10.0.0.1", b"198.51.100.7, 198.51.100.8"), "198.51.100.8"),
        ((b"198.51.100.9:443",), "198.51.100.9"),
        ((b"[2001:db8::1]:443",), "2001:db8::1"),
        ((b"2001:DB8::2",), "2001:db8::2"),
        ((b"10.0.0.1, not-an-ip",), "203.0.113.20"),
        ((b" , ",), "203.0.113.20"),
    ],
)
def test_forwarded_for_parsing(monkeypatch, headers, expected):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)

    assert get_rate_limit_key(_request_with_forwarded_for(*headers)) == expected


def test_trust_proxy_headers_comes_from_the_app_settings(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    app = SimpleNamespace(
        state=SimpleNamespace(settings=Settings(_env_file=None, trust_proxy_headers=True))
    )

    assert get_rate_limit_key(_request_with_forwarded_for(app=app)) == "198.51.100.11"


def _limited_app(default_limit: str = "2/minute", **settings_overrides) -> tuple[FastAPI, Limiter]:
    """A small app wired like the real one, with its own limiter and a low default limit."""
    test_limiter = Limiter(
        key_func=get_rate_limit_key, default_limits=[default_limit], key_style="endpoint"
    )
    app = FastAPI()
    app.state.limiter = test_limiter
    app.state.settings = Settings(_env_file=None, **settings_overrides)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(RateLimitMiddleware)

    def require_api_key():
        raise HTTPException(status_code=401, detail="Missing API key")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected():
        return {"ok": True}

    @app.get("/decorated", dependencies=[Depends(require_api_key)])
    @test_limiter.limit("5/minute")
    def decorated(request: Request):
        return {"ok": True}

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"item": item_id}

    return app, test_limiter


class TestRateLimitMiddleware:
    def test_unauthenticated_requests_are_counted(self):
        client = TestClient(_limited_app()[0])

        codes = [client.get("/protected").status_code for _ in range(3)]

        assert codes == [401, 401, 429]

    def test_429_response_shape(self):
        client = TestClient(_limited_app()[0])
        for _ in range(2):
            client.get("/protected")

        response = client.get("/protected")

        assert response.status_code == 429
        assert response.json()["detail"] == "Rate limit exceeded"
        assert response.headers["Retry-After"] == "60"

    def test_default_limit_applies_to_decorated_routes_before_dependencies(self):
        """slowapi's own middleware skips decorated routes; ours counts them too."""
        client = TestClient(_limited_app()[0])

        codes = [client.get("/decorated").status_code for _ in range(3)]

        assert codes == [401, 401, 429]

    def test_path_parameters_share_one_bucket(self):
        client = TestClient(_limited_app()[0])

        codes = [client.get(f"/items/{item_id}").status_code for item_id in ("a", "b", "c")]

        assert codes == [200, 200, 429]

    def test_unmatched_paths_are_not_counted(self):
        client = TestClient(_limited_app()[0])

        assert {client.get("/does-not-exist").status_code for _ in range(5)} == {404}

    def test_disabled_limiter_is_a_no_op(self):
        app, test_limiter = _limited_app()
        test_limiter.enabled = False
        client = TestClient(app)

        assert {client.get("/protected").status_code for _ in range(5)} == {401}

    def test_spoofed_leftmost_hops_share_the_proxy_bucket(self):
        client = TestClient(_limited_app(trust_proxy_headers=True)[0])

        codes = [
            client.get(
                "/items/x", headers={"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.1"}
            ).status_code
            for i in range(3)
        ]
        other_client = client.get("/items/x", headers={"X-Forwarded-For": "198.51.100.2"})

        assert codes == [200, 200, 429]
        assert other_client.status_code == 200


def test_real_app_counts_unauthenticated_requests(production_client):
    """The production app rate-limits a key-less flood instead of answering 401 forever."""
    limiter.enabled = True
    allowed = int(DEFAULT_RATE_LIMIT.split("/")[0])

    codes = [production_client.get("/api/v1/student/profile").status_code for _ in range(allowed)]
    blocked = production_client.get("/api/v1/student/profile")

    assert set(codes) == {401}
    assert blocked.status_code == 429
