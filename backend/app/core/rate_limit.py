"""
Rate limiting using slowapi.

Two layers protect the API:

- ``RateLimitMiddleware`` applies the default limit (``RATE_LIMIT_DEFAULT``, from the
  app's settings) to every routed request before FastAPI resolves dependencies, so
  requests that go on to fail authentication are counted as well. Endpoints marked
  ``@limiter.exempt`` (the health checks) are skipped.
- ``@limiter.limit(...)`` decorators add stricter per-endpoint limits. They run inside
  the endpoint wrapper, after dependencies.

Clients are identified by IP address (see ``get_rate_limit_key``), and limits are
counted per endpoint, so varying a path parameter does not open a fresh bucket.

The limiter is process-wide: its on/off switch (``RATE_LIMIT_ENABLED``) and the
per-route decorators are bound from the process settings when this module is imported.
Per-app settings (``create_app(settings)``) choose the default limit and how clients are
identified (``TRUST_PROXY_HEADERS``).
"""

import ipaddress
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from limits import RateLimitItem, parse_many
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.core.auth import get_request_settings
from backend.app.core.settings import settings


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


@lru_cache(maxsize=32)
def parse_rate_limit(value: str) -> tuple[RateLimitItem, ...]:
    """Parse a limit string such as ``"100/minute"`` or ``"100/minute;1000/hour"``.

    Raises:
        ValueError: if ``value`` is not a valid rate limit string.
    """
    items = tuple(parse_many(value))
    if not items:
        raise ValueError(f"Invalid rate limit: {value!r}")
    return items


# Create the limiter instance. The default limit is applied by RateLimitMiddleware, not
# through slowapi's default_limits, so that it can follow the app's settings.
limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=settings.rate_limit_enabled,
    key_style="endpoint",
)


def _too_many_requests(limit: RateLimitItem, description: str | None = None) -> JSONResponse:
    """The 429 response for a request over ``limit``."""
    window = str(limit)
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "error": description or window,
            "retry_after": window.split("per ")[1] if "per " in window else "1 minute",
        },
        headers={"Retry-After": str(limit.get_expiry())},
    )


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors raised by ``@limiter.limit`` decorators.

    Args:
        request: The incoming request
        exc: The rate limit exception

    Returns:
        JSONResponse with 429 status, error details and a Retry-After header
    """
    if exc.limit is None:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "error": str(exc.detail),
                "retry_after": "1 minute",
            },
        )
    return _too_many_requests(exc.limit.limit, str(exc.detail))


def _route_endpoint(app: Any, scope: Scope) -> Callable[..., Any] | None:
    """Endpoint of the first route that fully matches ``scope``, as the router picks it."""
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "endpoint", None)
    return None


class RateLimitMiddleware:
    """Apply the default limit to every routed HTTP request, before dependencies run.

    slowapi's own ``SlowAPIMiddleware`` skips endpoints that carry a ``@limiter.limit``
    decorator and leaves them to the decorator, which only runs once FastAPI has resolved
    dependencies such as ``verify_api_key``: a flood of unauthenticated requests was never
    counted. This middleware counts those endpoints too; their decorators still apply their
    own limits on top. Requests that match no route (404, 405) and endpoints marked
    ``@limiter.exempt`` are not counted.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            response = _over_default_limit(scope, receive)
            if response is not None:
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _over_default_limit(scope: Scope, receive: Receive) -> JSONResponse | None:
    """Count the request against the default limit; a 429 response if it is over."""
    app = scope["app"]
    app_limiter: Limiter = app.state.limiter
    if not app_limiter.enabled:
        return None

    endpoint = _route_endpoint(app, scope)
    if endpoint is None:
        return None
    endpoint_name = f"{endpoint.__module__}.{endpoint.__name__}"
    # The registry filled by @limiter.exempt, which slowapi's own middleware consults too.
    if endpoint_name in app_limiter._exempt_routes:
        return None

    request = Request(scope, receive)
    client = get_rate_limit_key(request)
    for limit in parse_rate_limit(get_request_settings(request).rate_limit_default):
        if not app_limiter.limiter.hit(limit, client, f"default:{endpoint_name}"):
            return _too_many_requests(limit)
    return None


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
