"""
API key authentication.

``APP_ENV`` decides what an empty ``API_KEY`` means:

- ``development``: protected endpoints are open, so the local quickstart works without a
  key; the app logs a warning banner at startup.
- ``production``: ``create_app()`` refuses to start without a key, and requests are
  rejected (fail closed) should the key be missing at runtime anyway.

A configured key is always enforced, in both modes.
"""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from loguru import logger

from backend.app.core.settings import Settings, settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

MISSING_API_KEY_DETAIL = "Missing API key. Include X-API-Key header."
INVALID_API_KEY_DETAIL = "Invalid API key"


def get_request_settings(request: Request) -> Settings:
    """Settings of the app serving ``request`` (see ``create_app``), else the global ones."""
    app = request.scope.get("app")
    app_settings = getattr(getattr(app, "state", None), "settings", None)
    return app_settings if isinstance(app_settings, Settings) else settings


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "ApiKey"},
    )


def _keys_match(provided: str, expected: str) -> bool:
    """Constant-time comparison of the UTF-8 bytes.

    ``hmac.compare_digest`` raises ``TypeError`` for ``str`` arguments containing
    non-ASCII characters, which turned a malformed header into a 500.
    """
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def verify_api_key(
    request: Request,
    api_key: Annotated[str | None, Security(API_KEY_HEADER)],
) -> str:
    """
    Verify the API key from the ``X-API-Key`` header.

    Args:
        request: The incoming request (selects the app's settings)
        api_key: The API key from the X-API-Key header

    Returns:
        The validated API key, or ``"development"`` when no key is configured in
        development mode

    Raises:
        HTTPException: 401 if the key is missing or invalid, and for every request in
            production when no key is configured
    """
    app_settings = get_request_settings(request)
    # A whitespace-only key counts as no key (create_app() refuses to start with one).
    expected = app_settings.api_key.strip()

    if not expected and app_settings.app_env == "development":
        logger.debug("No API key configured (development mode), allowing request")
        return "development"

    if not api_key:
        logger.warning("Missing API key in request")
        raise _unauthorized(MISSING_API_KEY_DETAIL)

    if not expected:
        # create_app() refuses to start like this; fail closed if it happens anyway.
        logger.error("Rejecting request: APP_ENV=production but API_KEY is not configured")
        raise _unauthorized(INVALID_API_KEY_DETAIL)

    if not _keys_match(api_key, expected):
        logger.warning("Invalid API key attempt")
        raise _unauthorized(INVALID_API_KEY_DETAIL)

    return api_key


def get_optional_api_key(
    request: Request,
    api_key: Annotated[str | None, Security(API_KEY_HEADER)],
) -> str | None:
    """
    Get the API key if provided, but don't require it.

    Useful for endpoints that have different behavior for authenticated vs anonymous.

    Args:
        request: The incoming request (selects the app's settings)
        api_key: The API key from X-API-Key header (optional)

    Returns:
        The API key if valid, None if not provided, raises if invalid
    """
    if not api_key:
        return None

    app_settings = get_request_settings(request)
    expected = app_settings.api_key.strip()
    if not expected and app_settings.app_env == "development":
        return api_key

    if not expected or not _keys_match(api_key, expected):
        logger.warning("Invalid API key attempt")
        raise _unauthorized(INVALID_API_KEY_DETAIL)

    return api_key


# Type alias for dependency injection
RequireApiKey = Annotated[str, Depends(verify_api_key)]
OptionalApiKey = Annotated[str | None, Depends(get_optional_api_key)]
