"""
API Key authentication middleware.

Provides simple API key authentication for protecting endpoints.
Keys are validated against environment variables or a configurable source.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from loguru import logger

from backend.app.core.settings import settings

# API Key header name
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key: Annotated[str | None, Security(API_KEY_HEADER)],
) -> str:
    """
    Verify the API key from the request header.

    Args:
        api_key: The API key from X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: 401 if key is missing or invalid
    """
    # If no API key is configured, allow all requests (development mode)
    if not settings.api_key:
        logger.debug("No API key configured, allowing request")
        return "development"

    if not api_key:
        logger.warning("Missing API key in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Use secrets.compare_digest for timing-safe comparison
    if not secrets.compare_digest(api_key, settings.api_key):
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


def get_optional_api_key(
    api_key: Annotated[str | None, Security(API_KEY_HEADER)],
) -> str | None:
    """
    Get the API key if provided, but don't require it.

    Useful for endpoints that have different behavior for authenticated vs anonymous.

    Args:
        api_key: The API key from X-API-Key header (optional)

    Returns:
        The API key if valid, None if not provided, raises if invalid
    """
    if not api_key:
        return None

    if settings.api_key and not secrets.compare_digest(api_key, settings.api_key):
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


# Type alias for dependency injection
RequireApiKey = Annotated[str, Depends(verify_api_key)]
OptionalApiKey = Annotated[str | None, Depends(get_optional_api_key)]
