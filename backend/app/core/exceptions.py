"""
Custom exceptions for the Adaptive Knowledge Graph application.
"""

import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|password|secret)=([^&\s]+)"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret):\s*([^\s,]+)"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+"),
    re.compile(r"(?i)(sk-[a-z0-9._\-]+)"),
    re.compile(r"(?i)(sk-or-v1-[a-z0-9._\-]+)"),
]


def safe_error_message(error: Exception | str, fallback: str = "Service unavailable") -> str:
    """Return a bounded, redacted message safe for API responses and health checks."""
    message = str(error)
    if not message:
        return fallback

    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(lambda match: match.group(1) + "[REDACTED]", message)

    # Avoid exposing very long driver traces or connection strings in health responses.
    message = message.replace("\n", " ").replace("\r", " ")
    return message[:160]


class AdaptiveKGException(Exception):
    """Base exception for the application."""

    pass


class Neo4jConnectionError(AdaptiveKGException):
    """Failed to connect to Neo4j."""

    pass


class Neo4jQueryError(AdaptiveKGException):
    """Failed to execute Neo4j query."""

    pass


class OpenSearchConnectionError(AdaptiveKGException):
    """Failed to connect to OpenSearch."""

    pass


class OpenSearchQueryError(AdaptiveKGException):
    """Failed to execute OpenSearch query."""

    pass


class LLMGenerationError(AdaptiveKGException):
    """LLM failed to generate response."""

    pass


class LLMConnectionError(AdaptiveKGException):
    """Failed to connect to LLM service."""

    pass


class QuizGenerationError(AdaptiveKGException):
    """Failed to generate quiz."""

    pass


class ContentNotFoundError(AdaptiveKGException):
    """No relevant content found for the query."""

    pass
