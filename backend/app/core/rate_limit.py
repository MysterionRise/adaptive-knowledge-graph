"""
Rate limiting using slowapi.

Two layers protect the API:

- ``enforce_default_rate_limit``, an app-wide dependency (``FastAPI(dependencies=...)``),
  applies the default limit (``RATE_LIMIT_DEFAULT``, from the app's settings) to every
  route. App-wide dependencies run before a route's own ones, such as
  ``verify_api_key``, so requests that go on to fail authentication are counted too.
  Endpoints marked ``@limiter.exempt`` (the health checks) are skipped. Only requests
  whose JSON body cannot be decoded are rejected (422) before any dependency runs.
- ``@limiter.limit(...)`` decorators add stricter per-endpoint limits. They run inside
  the endpoint wrapper, after dependencies.

Clients are identified by IP address (see ``get_rate_limit_key``), and limits are
counted per endpoint, so varying a path parameter does not open a fresh bucket.

slowapi's own ``SlowAPIMiddleware`` is not used: it leaves decorated endpoints to their
decorators, which run after authentication, and (like any middleware running before
routing) it cannot see which endpoint FastAPI >= 0.142 will pick for an included router.

The limiter is process-wide: its on/off switch (``RATE_LIMIT_ENABLED``) and the
per-route decorators are bound from the process settings when this module is imported.
Per-app settings (``create_app(settings)``) choose the default limit and how clients are
identified (``TRUST_PROXY_HEADERS``).
"""

import ipaddress
from functools import lru_cache

from limits import RateLimitItem, parse_many
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

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


# Create the limiter instance. The default limit is applied by enforce_default_rate_limit,
# not through slowapi's default_limits, so that it can follow the app's settings.
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


class DefaultRateLimitExceeded(Exception):
    """A client went over ``RATE_LIMIT_DEFAULT`` on an endpoint."""

    def __init__(self, limit: RateLimitItem) -> None:
        super().__init__(str(limit))
        self.limit = limit


def default_rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """429 for ``DefaultRateLimitExceeded``, with the same body as the per-route limits."""
    if isinstance(exc, DefaultRateLimitExceeded):
        return _too_many_requests(exc.limit)
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


async def enforce_default_rate_limit(request: Request) -> None:
    """App-wide dependency: count the request against the default limit.

    Registered with ``FastAPI(dependencies=[...])``, it runs before every route's own
    dependencies (``verify_api_key`` included), so an unauthenticated flood is counted.
    Endpoints with ``@limiter.limit`` decorators are counted too; the decorators apply
    their own limits on top. Endpoints marked ``@limiter.exempt`` are skipped.

    Raises:
        DefaultRateLimitExceeded: the client is over the limit for this endpoint.
    """
    app_limiter: Limiter = request.app.state.limiter
    endpoint = getattr(request.scope.get("route"), "endpoint", None)
    if not app_limiter.enabled or endpoint is None:
        return

    endpoint_name = f"{endpoint.__module__}.{endpoint.__name__}"
    # The registry filled by @limiter.exempt, which slowapi consults the same way.
    if endpoint_name in app_limiter._exempt_routes:
        return

    client = get_rate_limit_key(request)
    for limit in parse_rate_limit(get_request_settings(request).rate_limit_default):
        if not app_limiter.limiter.hit(limit, client, f"default:{endpoint_name}"):
            raise DefaultRateLimitExceeded(limit)


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
