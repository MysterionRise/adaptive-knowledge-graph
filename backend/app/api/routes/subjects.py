"""
Subject management endpoints.

Provides endpoints for listing and getting subject configurations.
"""

import asyncio
import time

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.api.validators import SUBJECT_NOT_FOUND, error_responses
from backend.app.core.exceptions import safe_error_message
from backend.app.core.subjects import (
    SubjectConfig,
    get_all_subjects,
    get_default_subject_id,
    get_subject,
    get_subject_ids,
)

router = APIRouter(prefix="/subjects", tags=["Subjects"])

# Whether a subject has graph data is cached briefly, so listing subjects does not
# query Neo4j on every page load.
AVAILABILITY_CACHE_TTL_SECONDS = 60.0
_availability_cache: dict[str, tuple[float, bool]] = {}


def clear_subject_availability_cache() -> None:
    """Clear cached subject availability (used in tests and after reseeding)."""
    _availability_cache.clear()


def _subject_has_concepts(subject_id: str) -> bool:
    """Return True when the subject's graph has at least one concept (blocking: Neo4j)."""
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        stats = get_neo4j_adapter(subject_id).get_graph_stats()
        return int(stats.get("Concept_count", 0)) > 0
    except Exception as e:
        logger.warning(
            "Could not check graph data for subject '{}': {}", subject_id, safe_error_message(e)
        )
        return False


async def _subject_availability(subject_ids: list[str]) -> dict[str, bool]:
    """Availability per subject, from the cache or Neo4j (subjects are checked concurrently)."""
    now = time.monotonic()
    availability: dict[str, bool] = {}
    stale: list[str] = []
    for subject_id in subject_ids:
        cached = _availability_cache.get(subject_id)
        if cached is not None and now - cached[0] < AVAILABILITY_CACHE_TTL_SECONDS:
            availability[subject_id] = cached[1]
        else:
            stale.append(subject_id)

    if stale:
        results = await asyncio.gather(
            *(run_in_threadpool(_subject_has_concepts, subject_id) for subject_id in stale)
        )
        checked_at = time.monotonic()
        for subject_id, available in zip(stale, results, strict=True):
            _availability_cache[subject_id] = (checked_at, available)
            availability[subject_id] = available

    return availability


def _find_subject(subject_id: str) -> SubjectConfig:
    """Look up a subject; only the unknown-subject KeyError becomes a 404."""
    try:
        return get_subject(subject_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=SUBJECT_NOT_FOUND) from None


class SubjectSummary(BaseModel):
    """Summary of a subject for listing."""

    id: str
    name: str
    description: str
    is_default: bool = False
    available: bool = Field(
        default=False,
        description=(
            "True when the subject's knowledge graph has at least one concept. "
            "Checked in Neo4j and cached for 60 seconds; false when Neo4j is unreachable."
        ),
    )


class SubjectListResponse(BaseModel):
    """Response for listing all subjects."""

    subjects: list[SubjectSummary]
    default_subject: str


class SubjectDetailResponse(BaseModel):
    """Detailed response for a single subject."""

    id: str
    name: str
    description: str
    attribution: str
    opensearch_index: str
    book_count: int
    is_default: bool = False


class SubjectThemeResponse(BaseModel):
    """Theme response for frontend styling."""

    subject_id: str
    primary_color: str
    secondary_color: str
    accent_color: str
    chapter_colors: dict[str, str]


@router.get("", response_model=SubjectListResponse)
async def list_subjects():
    """
    List all available subjects.

    Returns a list of subject summaries with the default subject indicated.
    `available` tells whether the subject has knowledge graph data, so clients can
    disable subjects that have not been seeded yet.
    """
    try:
        subjects = get_all_subjects()
        default_id = get_default_subject_id()
        availability = await _subject_availability([s.id for s in subjects])

        summaries = [
            SubjectSummary(
                id=s.id,
                name=s.name,
                description=s.description,
                is_default=(s.id == default_id),
                available=availability.get(s.id, False),
            )
            for s in subjects
        ]

        return SubjectListResponse(
            subjects=summaries,
            default_subject=default_id,
        )
    except Exception as e:
        logger.exception("Error listing subjects: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/ids", response_model=list[str])
async def list_subject_ids():
    """
    List all available subject IDs.

    Returns a simple list of subject identifiers.
    """
    try:
        return get_subject_ids()
    except Exception as e:
        logger.exception("Error listing subject IDs: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get(
    "/{subject_id}",
    response_model=SubjectDetailResponse,
    responses=error_responses(404),
)
async def get_subject_detail(subject_id: str):
    """
    Get detailed information about a specific subject.

    Args:
        subject_id: The subject identifier (e.g., "us_history", "biology")

    Returns:
        Detailed subject information including attribution and book count
    """
    try:
        subject = _find_subject(subject_id)
        default_id = get_default_subject_id()

        return SubjectDetailResponse(
            id=subject.id,
            name=subject.name,
            description=subject.description,
            attribution=subject.attribution,
            opensearch_index=subject.database.opensearch_index,
            book_count=len(subject.books),
            is_default=(subject.id == default_id),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting subject {}: {}", subject_id, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get(
    "/{subject_id}/theme",
    response_model=SubjectThemeResponse,
    responses=error_responses(404),
)
async def get_subject_theme(subject_id: str):
    """
    Get the theme configuration for a subject.

    Returns colors and chapter color mappings for frontend styling.

    Args:
        subject_id: The subject identifier (e.g., "us_history", "biology")

    Returns:
        Theme configuration with colors
    """
    try:
        subject = _find_subject(subject_id)

        return SubjectThemeResponse(
            subject_id=subject.id,
            primary_color=subject.theme.primary_color,
            secondary_color=subject.theme.secondary_color,
            accent_color=subject.theme.accent_color,
            chapter_colors=subject.theme.chapter_colors,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting theme for {}: {}", subject_id, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get(
    "/{subject_id}/books",
    response_model=list[dict],
    responses=error_responses(404),
)
async def get_subject_books(subject_id: str):
    """
    Get the list of books for a subject.

    Args:
        subject_id: The subject identifier (e.g., "us_history", "biology")

    Returns:
        List of book configurations
    """
    try:
        subject = _find_subject(subject_id)

        result = []
        for book in subject.books:
            entry: dict = {
                "title": book.title,
                "source_type": book.source_type,
            }
            if book.source_type == "openstax_web":
                entry["openstax_slug"] = book.openstax_slug
            else:
                entry["repo_url_raw"] = book.repo_url_raw
                entry["summary_path"] = book.summary_path
                entry["content_path"] = book.content_path
                entry["branch"] = book.branch
            result.append(entry)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting books for {}: {}", subject_id, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
