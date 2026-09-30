"""
Custom exceptions and error-response helpers for the Adaptive Knowledge Graph application.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

_REDACTED = "[REDACTED]"
_MAX_SAFE_MESSAGE_CHARS = 160
# Only the start of a message is ever shown; bounding the scanned text also keeps the
# regexes below linear-time on pathological inputs.
_MAX_SCANNED_CHARS = 2000
_MAX_VALIDATION_MESSAGE_CHARS = 200

# Applied in order. Whole URIs go first, so the credentials, hosts and paths inside them
# are replaced in one piece before the narrower patterns run.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # URIs and DSNs: bolt://, neo4j+s://, http(s)://, postgresql://user:pass@host/db, ...
    (re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s'\"<>]*", re.IGNORECASE), _REDACTED),
    # user:password@host without a scheme
    (re.compile(r"[^\s'\"<>@/:()]+:[^\s'\"<>@]*@[^\s'\"<>,;()]+"), _REDACTED),
    # key=value / key: value secrets, including auth=(user, password) tuples. Not anchored
    # to a word start, so prefixed names (NEO4J_PASSWORD=, OPENROUTER_API_KEY=,
    # db_password:) match too, and the value runs to the next whitespace.
    (
        re.compile(
            r"(api[_-]?key|token|password|passwd|pwd|secret|user(?:name)?|auth)"
            r"([\"']?\s*[=:]\s*[\"']?)(\([^)]*\)|\S+)",
            re.IGNORECASE,
        ),
        r"\1\2" + _REDACTED,
    ),
    (re.compile(r"(bearer\s+)[a-z0-9._~+/\-]+=*", re.IGNORECASE), r"\1" + _REDACTED),
    (re.compile(r"sk-[a-z0-9._\-]+", re.IGNORECASE), _REDACTED),
    # Absolute file-system paths (POSIX and Windows)
    (re.compile(r"(?<![\w.:/])/(?:[\w.\-]+/)+[\w.\-]*"), _REDACTED),
    (re.compile(r"\b[a-z]:\\[^\s'\"<>]*", re.IGNORECASE), _REDACTED),
    # IPv6 (loose: two or more colons between hex groups, optional brackets, zone and port)
    (
        re.compile(
            r"(?<![\w:.])\[?(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:%\w+)?\]?(?::\d{1,5})?(?![\w:])",
            re.IGNORECASE,
        ),
        _REDACTED,
    ),
    # IPv4, optionally with a port
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b"), _REDACTED),
    # host:port
    (
        re.compile(
            r"\b[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)*:\d{2,5}\b",
            re.IGNORECASE,
        ),
        _REDACTED,
    ),
    # Dotted host names (anything shaped like one: over-redaction is acceptable here)
    (
        re.compile(r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9\-]{1,62}\b", re.I),
        _REDACTED,
    ),
    (re.compile(r"\blocalhost\b", re.IGNORECASE), _REDACTED),
)


def safe_error_message(error: Exception | str, fallback: str = "Service unavailable") -> str:
    """Return a bounded, single-line error message that is safe to show to API clients.

    Secrets (``key=value`` pairs, bearer tokens, ``sk-`` keys), URIs and DSNs, host names,
    IP addresses and absolute paths are replaced with ``[REDACTED]``. Callers should log
    the original error for operators; this is only for response bodies such as the
    unauthenticated ``/health/ready`` and ``/api/v1/demo/status``.
    """
    message = str(error)
    if len(message) > _MAX_SCANNED_CHARS:
        head = message[:_MAX_SCANNED_CHARS]
        if not message[_MAX_SCANNED_CHARS].isspace():
            # The bound cuts a token in half: drop its start, so no partial secret survives.
            head = re.sub(r"\S+\Z", "", head)
        message = head

    for pattern, replacement in _REDACTIONS:
        message = pattern.sub(replacement, message)

    message = " ".join(message.split())
    return message[:_MAX_SAFE_MESSAGE_CHARS] if message else fallback


def public_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Reduce pydantic validation errors to their ``loc``, ``msg`` and ``type``.

    FastAPI's default 422 body also carries ``input`` and ``ctx``: the submitted value is
    echoed back in full (a 1 MB field came back as 1 MB) and ``ctx`` can hold internal
    objects.
    """
    public: list[dict[str, Any]] = []
    for error in errors:
        # Route code may raise RequestValidationError itself, with hand-built entries.
        if not isinstance(error, Mapping):
            error = {"msg": str(error), "type": "value_error"}
        loc = [part if isinstance(part, str | int) else str(part) for part in error.get("loc", ())]
        public.append(
            {
                "loc": loc,
                "msg": str(error.get("msg", ""))[:_MAX_VALIDATION_MESSAGE_CHARS],
                "type": str(error.get("type", "")),
            }
        )
    return public


async def request_validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 response for invalid requests that never echoes the submitted input."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(status_code=422, content={"detail": public_validation_errors(errors)})


class AdaptiveKGException(Exception):
    """Base exception for the application."""

    pass


class ConfigurationError(AdaptiveKGException):
    """The settings are unsafe for the selected APP_ENV, so the app refuses to start."""

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
