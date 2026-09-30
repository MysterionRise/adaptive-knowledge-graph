"""
Request validation helpers shared by the API routes.

- Constrained string and identifier types (defined in ``backend.app.ui_payloads.constraints``)
- Subject lookups that answer 404 for unknown subjects
- A markup guard for free text that is echoed back to clients
- Lucene escaping for user input sent to Neo4j fulltext indexes
- OpenAPI declarations for the error responses routes can return
"""

import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from backend.app.core.subjects import SubjectConfig, get_subject
from backend.app.ui_payloads.constraints import (
    DEFAULT_STUDENT_ID,
    STUDENT_ID_PATTERN,
    SUBJECT_ID_PATTERN,
    ConceptStr,
    NonBlankStr,
    QuestionStr,
    SearchQueryStr,
    StudentId,
    SubjectId,
    TopicStr,
)

__all__ = [
    "DEFAULT_STUDENT_ID",
    "STUDENT_ID_PATTERN",
    "SUBJECT_ID_PATTERN",
    "SUBJECT_NOT_FOUND",
    "ConceptStr",
    "ErrorResponse",
    "NonBlankStr",
    "QuestionStr",
    "RateLimitResponse",
    "SearchQueryStr",
    "StudentId",
    "SubjectId",
    "SubjectParam",
    "TopicStr",
    "contains_markup",
    "ensure_no_markup",
    "ensure_subject_exists",
    "error_responses",
    "escape_lucene",
    "get_subject_or_404",
    "resolve_subject",
]

SUBJECT_NOT_FOUND = "Subject not found"


# =============================================================================
# Subjects
# =============================================================================


def get_subject_or_404(subject_id: str | None) -> SubjectConfig:
    """
    Resolve a subject configuration; ``None`` means the configured default subject.

    Only the ``KeyError`` that ``get_subject`` raises for an unknown, explicitly requested
    subject becomes a 404. A broken default-subject configuration is a server error and
    propagates unchanged.
    """
    if subject_id is None:
        return get_subject(None)
    try:
        return get_subject(subject_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=SUBJECT_NOT_FOUND) from None


def ensure_subject_exists(subject_id: str | None) -> None:
    """Respond 404 when an explicitly requested subject is not configured."""
    if subject_id is not None:
        get_subject_or_404(subject_id)


def resolve_subject(
    subject: Annotated[
        SubjectId | None,
        Query(
            description=(
                "Subject ID (e.g. 'us_history', 'biology'). "
                "Defaults to the configured default subject."
            ),
        ),
    ] = None,
) -> str | None:
    """
    FastAPI dependency for the optional ``subject`` query parameter.

    Malformed IDs fail validation (422) and unknown subjects answer 404. The ID is returned
    unchanged; ``None`` lets downstream services use their default subject.
    """
    ensure_subject_exists(subject)
    return subject


SubjectParam = Annotated[str | None, Depends(resolve_subject)]


# =============================================================================
# Markup guard
# =============================================================================

# "<" directly followed by a letter, "/", "!" or "?" opens an HTML tag, closing tag,
# comment/doctype or processing instruction. "x < y" (space after "<") is plain text.
_MARKUP_PATTERN = re.compile(r"<[A-Za-z!/?]")


def contains_markup(text: str) -> bool:
    """Return True when the text contains HTML or script markup."""
    return _MARKUP_PATTERN.search(text) is not None


def ensure_no_markup(value: str, *, field: str, location: str = "body") -> None:
    """
    Reject HTML or script markup in a free-text field.

    Raises a standard 422 validation error. The rejected value is never echoed back:
    the error's ``input`` is ``None``.
    """
    if contains_markup(value):
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": (location, field),
                    "msg": f"Value error, {field} must not contain HTML or script markup",
                    "input": None,
                }
            ]
        )


# =============================================================================
# Lucene escaping
# =============================================================================

# Lucene query-syntax characters (the set escaped by Lucene's QueryParser.escape).
_LUCENE_SPECIAL_CHARS = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')
# Upper-case boolean operators are keywords for the classic query parser.
_LUCENE_OPERATORS = re.compile(r"\b(AND|OR|NOT)\b")


def escape_lucene(text: str) -> str:
    """
    Escape Lucene query syntax so user input is matched literally.

    Special characters are backslash-escaped and ``AND``/``OR``/``NOT`` are lower-cased
    (fulltext analyzers lower-case terms anyway), so ``*:*`` cannot match every node.
    """
    escaped = _LUCENE_SPECIAL_CHARS.sub(r"\\\1", text)
    return _LUCENE_OPERATORS.sub(lambda match: match.group(1).lower(), escaped)


# =============================================================================
# OpenAPI error responses
# =============================================================================


class ErrorResponse(BaseModel):
    """Error body returned by the API."""

    detail: str


class RateLimitResponse(ErrorResponse):
    """Error body returned when a rate limit is exceeded."""

    error: str
    retry_after: str


_ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {
        "model": ErrorResponse,
        "description": "Rejected by a safety guard (only read-only graph queries are allowed)",
    },
    401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    404: {"model": ErrorResponse, "description": "Unknown subject, or no matching content"},
    429: {"model": RateLimitResponse, "description": "Rate limit exceeded"},
    502: {
        "model": ErrorResponse,
        "description": "The language model returned an invalid or empty response",
    },
    503: {
        "model": ErrorResponse,
        "description": "A backing service (LLM, Neo4j or OpenSearch) is unavailable",
    },
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Build the OpenAPI ``responses`` entries for the given error status codes."""
    return {code: _ERROR_RESPONSES[code] for code in status_codes}
