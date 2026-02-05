"""
Subject management endpoints.

Provides endpoints for listing and getting subject configurations.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from backend.app.core.subjects import (
    get_all_subjects,
    get_default_subject_id,
    get_subject,
    get_subject_ids,
)

router = APIRouter(prefix="/subjects", tags=["Subjects"])


class SubjectSummary(BaseModel):
    """Summary of a subject for listing."""

    id: str
    name: str
    description: str
    is_default: bool = False


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
    """
    try:
        subjects = get_all_subjects()
        default_id = get_default_subject_id()

        summaries = [
            SubjectSummary(
                id=s.id,
                name=s.name,
                description=s.description,
                is_default=(s.id == default_id),
            )
            for s in subjects
        ]

        return SubjectListResponse(
            subjects=summaries,
            default_subject=default_id,
        )
    except Exception as e:
        logger.error(f"Error listing subjects: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/ids", response_model=list[str])
async def list_subject_ids():
    """
    List all available subject IDs.

    Returns a simple list of subject identifiers.
    """
    try:
        return get_subject_ids()
    except Exception as e:
        logger.error(f"Error listing subject IDs: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{subject_id}", response_model=SubjectDetailResponse)
async def get_subject_detail(subject_id: str):
    """
    Get detailed information about a specific subject.

    Args:
        subject_id: The subject identifier (e.g., "us_history", "biology")

    Returns:
        Detailed subject information including attribution and book count
    """
    try:
        subject = get_subject(subject_id)
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
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting subject {subject_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{subject_id}/theme", response_model=SubjectThemeResponse)
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
        subject = get_subject(subject_id)

        return SubjectThemeResponse(
            subject_id=subject.id,
            primary_color=subject.theme.primary_color,
            secondary_color=subject.theme.secondary_color,
            accent_color=subject.theme.accent_color,
            chapter_colors=subject.theme.chapter_colors,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting theme for {subject_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{subject_id}/books", response_model=list[dict])
async def get_subject_books(subject_id: str):
    """
    Get the list of books for a subject.

    Args:
        subject_id: The subject identifier (e.g., "us_history", "biology")

    Returns:
        List of book configurations
    """
    try:
        subject = get_subject(subject_id)

        return [
            {
                "title": book.title,
                "repo_url_raw": book.repo_url_raw,
                "summary_path": book.summary_path,
                "content_path": book.content_path,
                "branch": book.branch,
            }
            for book in subject.books
        ]
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting books for {subject_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
