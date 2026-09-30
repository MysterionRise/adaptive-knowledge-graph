"""
Quiz generation and student mastery endpoints.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger

from backend.app.api.validators import (
    DEFAULT_STUDENT_ID,
    ConceptStr,
    StudentId,
    SubjectParam,
    TopicStr,
    ensure_no_markup,
    ensure_subject_exists,
    error_responses,
)
from backend.app.core.auth import verify_api_key
from backend.app.core.exceptions import (
    ContentNotFoundError,
    LLMConnectionError,
    LLMGenerationError,
    QuizGenerationError,
)
from backend.app.core.rate_limit import limiter
from backend.app.core.settings import settings
from backend.app.student.models import (
    MasteryUpdate,
    MasteryUpdateResponse,
    StudentProfileResponse,
    TargetDifficultyResponse,
)
from backend.app.student.quiz_generator import get_quiz_generator
from backend.app.student.recommendation_service import get_recommendation_service
from backend.app.student.student_service import get_student_service
from backend.app.ui_payloads.quiz import AdaptiveQuiz, Quiz
from backend.app.ui_payloads.recommendations import RecommendationRequest, RecommendationResponse

router = APIRouter(tags=["Quiz & Adaptive Learning"])

TOPIC_NOT_FOUND = "Topic not found or no content available"
# Older quiz generators signal "no content" with ValueError("No content found for <topic>")
# instead of ContentNotFoundError.
_NO_CONTENT_MESSAGE_PREFIX = "No content found"

TopicQuery = Annotated[TopicStr, Query(description="Topic to generate the quiz for")]
NumQuestionsQuery = Annotated[int, Query(ge=1, le=20, description="Number of questions")]
StudentIdQuery = Annotated[StudentId, Query(description="Student identifier")]


class MasteryUpdateRequest(MasteryUpdate):
    """Mastery update body; the concept name is trimmed and must not be blank."""

    concept: ConceptStr


@contextmanager
def _quiz_generation_errors(operation: str) -> Iterator[None]:
    """Map quiz generation failures to HTTP errors."""
    try:
        yield
    except HTTPException:
        raise
    except ContentNotFoundError:
        raise HTTPException(status_code=404, detail=TOPIC_NOT_FOUND) from None
    except (json.JSONDecodeError, QuizGenerationError) as e:
        logger.exception("{} failed, the LLM returned an invalid quiz: {}", operation, e)
        raise HTTPException(
            status_code=502, detail="Quiz generation returned an invalid response"
        ) from e
    except (LLMConnectionError, LLMGenerationError) as e:
        logger.exception("{} failed, the LLM service is unavailable: {}", operation, e)
        raise HTTPException(
            status_code=503, detail="Quiz generation service temporarily unavailable"
        ) from e
    except ValueError as e:
        if str(e).startswith(_NO_CONTENT_MESSAGE_PREFIX):
            raise HTTPException(status_code=404, detail=TOPIC_NOT_FOUND) from None
        logger.exception("{} failed: {}", operation, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
    except Exception as e:
        logger.exception("{} failed: {}", operation, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


# =============================================================================
# Quiz Generation Endpoints
# =============================================================================


@router.post(
    "/quiz/generate",
    response_model=Quiz,
    responses=error_responses(404, 429, 502, 503),
)
@limiter.limit(settings.rate_limit_quiz)
async def generate_quiz(
    request: Request,
    topic: TopicQuery,
    subject: SubjectParam,
    num_questions: NumQuestionsQuery = 3,
):
    """
    Generate a quiz for a topic (non-adaptive, mixed difficulty).

    Args:
        topic: Topic to generate quiz for
        num_questions: Number of questions to generate
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.

    Errors: 404 unknown subject or no content for the topic, 502 the LLM returned an
    invalid quiz, 503 the LLM service is unavailable.
    """
    ensure_no_markup(topic, field="topic", location="query")
    with _quiz_generation_errors("Quiz generation"):
        generator = get_quiz_generator(subject_id=subject)
        return await generator.generate_from_topic(topic, num_questions)


@router.post(
    "/quiz/generate-adaptive",
    response_model=AdaptiveQuiz,
    # Returns the learner's mastery, so it is protected like the other learner-data routes
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401, 404, 429, 502, 503),
)
@limiter.limit(settings.rate_limit_quiz)
async def generate_adaptive_quiz(
    request: Request,
    topic: TopicQuery,
    subject: SubjectParam,
    num_questions: NumQuestionsQuery = 3,
    student_id: StudentIdQuery = DEFAULT_STUDENT_ID,
):
    """
    Generate an adaptive quiz based on student's mastery level.

    The difficulty is automatically targeted based on the student's proficiency:
    - mastery < 0.4: easy questions
    - mastery 0.4-0.7: medium questions
    - mastery > 0.7: hard questions

    Args:
        topic: Topic to generate quiz for
        num_questions: Number of questions to generate
        student_id: Student identifier
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.

    The response includes the learner's mastery, so the X-API-Key header is required
    whenever an API key is configured (always in production).

    Errors: 401 missing or invalid API key; otherwise the same as /quiz/generate.
    """
    ensure_no_markup(topic, field="topic", location="query")
    with _quiz_generation_errors("Adaptive quiz generation"):
        # Get student's mastery and target difficulty
        student_service = get_student_service()
        target_info = student_service.get_target_difficulty(topic, student_id)

        # Generate quiz with targeted difficulty
        generator = get_quiz_generator(subject_id=subject)
        quiz = await generator.generate_from_topic(
            topic=topic,
            num_questions=num_questions,
            target_difficulty=target_info.target_difficulty,
        )

        # Return as adaptive quiz with metadata
        return AdaptiveQuiz(
            id=quiz.id,
            title=quiz.title,
            questions=quiz.questions,
            average_difficulty=quiz.average_difficulty,
            student_mastery=target_info.mastery_level,
            target_difficulty=target_info.target_difficulty,
            adapted=True,
        )


# =============================================================================
# Student Profile & Mastery Endpoints
# =============================================================================


@router.get(
    "/student/profile",
    response_model=StudentProfileResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401),
)
async def get_student_profile(student_id: StudentIdQuery = DEFAULT_STUDENT_ID):
    """Get student's current mastery levels for all tracked concepts."""
    try:
        student_service = get_student_service()
        return student_service.get_profile_response(student_id)
    except Exception as e:
        logger.exception("Error getting student profile: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.post(
    "/student/mastery",
    response_model=MasteryUpdateResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401, 429),
)
@limiter.limit(settings.rate_limit_student_write)
async def update_student_mastery(
    request: Request,
    update: MasteryUpdateRequest,
    student_id: StudentIdQuery = DEFAULT_STUDENT_ID,
):
    """
    Update mastery level after answering a question.

    Uses Bayesian Knowledge Tracing (BKT) when `STUDENT_BKT_ENABLED` is true (the default):
    - P(known) starts from the current mastery level
    - The answer updates it with Bayes' rule, using slip (0.1) and guess (0.25) probabilities
    - A learning transition (0.1) is then applied, and P(known) is kept within [0.01, 0.99]
    - The new mastery level is P(known), clamped to [0.1, 1.0]; the response includes
      `bkt_p_known`

    With BKT disabled, a linear update applies instead: +0.15 for a correct answer and
    -0.10 for an incorrect one, clamped to [0.1, 1.0].
    """
    try:
        student_service = get_student_service()
        return student_service.update_mastery(
            concept=update.concept,
            correct=update.correct,
            student_id=student_id,
        )
    except Exception as e:
        logger.exception("Error updating mastery: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get(
    "/student/target-difficulty",
    response_model=TargetDifficultyResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401),
)
async def get_target_difficulty(
    concept: Annotated[ConceptStr, Query(description="Concept name")],
    student_id: StudentIdQuery = DEFAULT_STUDENT_ID,
):
    """
    Get recommended difficulty level for a concept based on student mastery.

    Difficulty Targeting:
    - mastery < 0.4: "easy"
    - mastery 0.4-0.7: "medium"
    - mastery > 0.7: "hard"
    """
    try:
        student_service = get_student_service()
        return student_service.get_target_difficulty(concept, student_id)
    except Exception as e:
        logger.exception("Error getting target difficulty: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.post(
    "/student/reset",
    response_model=StudentProfileResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401, 429),
)
@limiter.limit(settings.rate_limit_student_write)
async def reset_student_profile(
    request: Request,
    student_id: StudentIdQuery = DEFAULT_STUDENT_ID,
):
    """Reset student profile to initial state (for demo purposes)."""
    try:
        student_service = get_student_service()
        return student_service.reset_profile(student_id)
    except Exception as e:
        logger.exception("Error resetting student profile: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


# =============================================================================
# Post-Quiz Recommendations
# =============================================================================


@router.post(
    "/quiz/recommendations",
    response_model=RecommendationResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401, 404, 429),
)
@limiter.limit(settings.rate_limit_recommendations)
async def get_quiz_recommendations(request: Request, body: RecommendationRequest):
    """
    Generate personalized recommendations after a quiz attempt.

    Based on the quiz results, returns:
    - Remediation: prerequisites + reading materials for weak concepts
    - Advancement: advanced topics + deep dive content for strong concepts
    """
    try:
        ensure_subject_exists(body.subject)
        service = get_recommendation_service(body.subject)
        return await service.generate_recommendations(
            topic=body.topic,
            question_results=body.question_results,
            student_id=body.student_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating recommendations: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/student/all-difficulties", responses=error_responses(401))
async def get_all_target_difficulties(
    student_id: StudentIdQuery = DEFAULT_STUDENT_ID,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Literal["easy", "medium", "hard"]]:
    """Get target difficulties for all tracked concepts."""
    try:
        student_service = get_student_service()
        return student_service.get_all_target_difficulties(student_id)
    except Exception as e:
        logger.exception("Error getting all target difficulties: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
