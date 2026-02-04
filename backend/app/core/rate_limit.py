"""
Rate limiting middleware using slowapi.

Provides configurable rate limiting for API endpoints to prevent abuse.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.app.core.settings import settings


def get_rate_limit_key(request: Request) -> str:
    """
    Get the rate limit key for a request.

    Uses X-Forwarded-For header if available (for reverse proxies),
    otherwise falls back to remote address.

    Args:
        request: The incoming request

    Returns:
        The client identifier for rate limiting
    """
    # Check for X-Forwarded-For header (reverse proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, use the first one
        return forwarded.split(",")[0].strip()

    return get_remote_address(request)


# Create the limiter instance
limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=settings.rate_limit_enabled,
    default_limits=["100/minute"],  # Default fallback
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a JSON response with helpful error details.

    Args:
        request: The incoming request
        exc: The rate limit exception

    Returns:
        JSONResponse with 429 status and error details
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "error": str(exc.detail),
            "retry_after": exc.detail.split("per ")[1] if "per " in str(exc.detail) else "1 minute",
        },
    )


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
