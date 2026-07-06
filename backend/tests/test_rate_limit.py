"""
Tests for rate-limit client identity behavior.
"""

from starlette.requests import Request

from backend.app.core.rate_limit import get_rate_limit_key
from backend.app.core.settings import settings


def _request_with_forwarded_for() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"198.51.100.10, 198.51.100.11")],
            "client": ("203.0.113.20", 4567),
        }
    )


def test_rate_limit_ignores_forwarded_for_by_default(monkeypatch):
    """Direct local deployments should not trust spoofable X-Forwarded-For headers."""
    monkeypatch.setattr(settings, "trust_proxy_headers", False)

    assert get_rate_limit_key(_request_with_forwarded_for()) == "203.0.113.20"


def test_rate_limit_uses_forwarded_for_when_trusted(monkeypatch):
    """Trusted reverse-proxy deployments can opt into X-Forwarded-For identity."""
    monkeypatch.setattr(settings, "trust_proxy_headers", True)

    assert get_rate_limit_key(_request_with_forwarded_for()) == "198.51.100.10"
