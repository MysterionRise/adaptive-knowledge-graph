"""
Rate limiting using slowapi.

Two layers protect the API:

- ``RateLimitMiddleware`` applies the limiter's default limit to every routed request
  before FastAPI resolves dependencies, so requests that go on to fail authentication
  are counted as well.
- ``@limiter.limit(...)`` decorators add stricter per-endpoint limits. They run inside
  the endpoint wrapper, after dependencies.

Clients are identified by IP address (see ``get_rate_limit_key``), and limits are
counted per endpoint, so varying a path parameter does not open a fresh bucket.
"""

import ipaddress
from collections.abc import Callable
from typing import Any

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.core.auth import get_request_settings
from backend.app.core.settings import settings

DEFAULT_RATE_LIMIT = "100/minute"


def _normalize_ip(value: str) -> str | None:
    """Return ``value`` as a canonical IP address (dropping a port), or ``None``."""
    host = value.strip()
    if host.startswith("["):  # [2001:db8::1]:443
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:  # 203.0.113.7:443
        host = host.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _rightmost_forwarded_for(request: Request) -> str | None:
    """The last ``X-Forwarded-For`` hop, i.e. the peer address our reverse proxy saw.

    Each proxy appends the address it received the request from, so every entry to the
    left of the last one was supplied by the client and can be spoofed.
    """
    hops = [
        hop
        for header in request.headers.getlist("x-forwarded-for")
        for hop in header.split(",")
        if hop.strip()
    ]
    return _normalize_ip(hops[-1]) if hops else None


def get_rate_limit_key(request: Request) -> str:
    """
    Get the rate limit key (client identity) for a request.

    Uses the right-most X-Forwarded-For hop only when trusted proxy headers are explicitly
    enabled (``TRUST_PROXY_HEADERS=true``); otherwise, or if that hop is not a valid IP
    address, the direct peer address.

    Args:
        request: The incoming request

    Returns:
        The client identifier for rate limiting
    """
    if get_request_settings(request).trust_proxy_headers:
        forwarded = _rightmost_forwarded_for(request)
        if forwarded:
            return forwarded

    return get_remote_address(request)


# Create the limiter instance
limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=settings.rate_limit_enabled,
    default_limits=[DEFAULT_RATE_LIMIT],
    key_style="endpoint",
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a JSON response with helpful error details.

    Args:
        request: The incoming request
        exc: The rate limit exception

    Returns:
        JSONResponse with 429 status, error details and a Retry-After header
    """
    detail = str(exc.detail)
    headers: dict[str, str] = {}
    if exc.limit is not None:
        headers["Retry-After"] = str(exc.limit.limit.get_expiry())
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "error": detail,
            "retry_after": detail.split("per ")[1] if "per " in detail else "1 minute",
        },
        headers=headers,
    )


def _route_endpoint(app: Any, scope: Scope) -> Callable[..., Any] | None:
    """Endpoint of the first route that fully matches ``scope``, as the router picks it."""
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "endpoint", None)
    return None


class RateLimitMiddleware:
    """Apply the limiter's default limits to every routed HTTP request, before dependencies.

    slowapi's own ``SlowAPIMiddleware`` skips endpoints that carry a ``@limiter.limit``
    decorator and leaves them to the decorator, which only runs once FastAPI has resolved
    dependencies such as ``verify_api_key``: a flood of unauthenticated requests was never
    counted. This middleware checks the default limits for those endpoints too; their
    decorators still apply their own limits on top. Requests that match no route (404,
    405) are not counted.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            app = scope["app"]
            app_limiter: Limiter = app.state.limiter
            endpoint = _route_endpoint(app, scope) if app_limiter.enabled else None
            if endpoint is not None:
                request = Request(scope, receive)
                try:
                    # The same check SlowAPIMiddleware runs: with in_middleware=True only
                    # the application and default limits are evaluated.
                    app_limiter._check_request_limit(request, endpoint, True)
                except RateLimitExceeded as exc:
                    await rate_limit_exceeded_handler(request, exc)(scope, receive, send)
                    return

        await self.app(scope, receive, send)


# Rate limit decorators for different endpoint types
def limit_ask():
    """Rate limit decorator for /ask endpoint."""
    return limiter.limit(settings.rate_limit_ask)


def limit_quiz():
    """Rate limit decorator for /quiz endpoint."""
    return limiter.limit(settings.rate_limit_quiz)


def limit_graph():
    """Rate limit decorator for /graph/* endpoints."""
    return limiter.limit(settings.rate_limit_graph)
