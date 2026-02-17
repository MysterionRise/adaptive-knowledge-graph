"""
Quiz generation and student mastery endpoints.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from loguru import logger

from backend.app.core.exceptions import ContentNotFoundError, QuizGenerationError
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

router = APIRouter(tags=["Quiz"])


# =============================================================================
# Quiz Generation Endpoints
# =============================================================================


@router.post("/quiz/generate", response_model=Quiz)
async def generate_quiz(topic: str, num_questions: int = 3, subject: str | None = None):
    """
    Generate a quiz for a topic (non-adaptive, mixed difficulty).

    Args:
        topic: Topic to generate quiz for
        num_questions: Number of questions to generate
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to us_history.
    """
    try:
        generator = get_quiz_generator(subject_id=subject)
        quiz = await generator.generate_from_topic(topic, num_questions)
        return quiz
    except ValueError as e:
        # No content found for topic
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ContentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except QuizGenerationError as e:
        logger.error(f"Quiz generation failed: {e}")
        raise HTTPException(status_code=503, detail=f"Quiz generation failed: {str(e)}") from e
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/quiz/generate-adaptive", response_model=AdaptiveQuiz)
async def generate_adaptive_quiz(
    topic: str,
    num_questions: int = 3,
    student_id: str = "default",
    subject: str | None = None,
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
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to us_history.
    """
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ContentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except QuizGenerationError as e:
        logger.error(f"Adaptive quiz generation failed: {e}")
        raise HTTPException(status_code=503, detail=f"Quiz generation failed: {str(e)}") from e
    except Exception as e:
        logger.error(f"Error generating adaptive quiz: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# Student Profile & Mastery Endpoints
# =============================================================================


@router.get("/student/profile", response_model=StudentProfileResponse)
async def get_student_profile(student_id: str = "default"):
    """Get student's current mastery levels for all tracked concepts."""
    try:
        student_service = get_student_service()
        return student_service.get_profile_response(student_id)
    except Exception as e:
        logger.error(f"Error getting student profile: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/student/mastery", response_model=MasteryUpdateResponse)
async def update_student_mastery(
    update: MasteryUpdate,
    student_id: str = "default",
):
    """
    Update mastery level after answering a question.

    Mastery Update Algorithm:
    - Correct answer: +0.15 (capped at 1.0)
    - Incorrect answer: -0.10 (floor at 0.1)
    """
    try:
        student_service = get_student_service()
        return student_service.update_mastery(
            concept=update.concept,
            correct=update.correct,
            student_id=student_id,
        )
    except Exception as e:
        logger.error(f"Error updating mastery: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/student/target-difficulty", response_model=TargetDifficultyResponse)
async def get_target_difficulty(
    concept: str,
    student_id: str = "default",
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
        logger.error(f"Error getting target difficulty: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/student/reset", response_model=StudentProfileResponse)
async def reset_student_profile(student_id: str = "default"):
    """Reset student profile to initial state (for demo purposes)."""
    try:
        student_service = get_student_service()
        return student_service.reset_profile(student_id)
    except Exception as e:
        logger.error(f"Error resetting student profile: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# Post-Quiz Recommendations
# =============================================================================


@router.post("/quiz/recommendations", response_model=RecommendationResponse)
async def get_quiz_recommendations(request: RecommendationRequest):
    """
    Generate personalized recommendations after a quiz attempt.

    Based on the quiz results, returns:
    - Remediation: prerequisites + reading materials for weak concepts
    - Advancement: advanced topics + deep dive content for strong concepts
    """
    try:
        service = get_recommendation_service(request.subject)
        return await service.generate_recommendations(
            topic=request.topic,
            question_results=request.question_results,
            student_id=request.student_id,
        )
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/student/all-difficulties")
async def get_all_target_difficulties(
    student_id: str = "default",
) -> dict[str, Literal["easy", "medium", "hard"]]:
    """Get target difficulties for all tracked concepts."""
    try:
        student_service = get_student_service()
        return student_service.get_all_target_difficulties(student_id)
    except Exception as e:
        logger.error(f"Error getting all target difficulties: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
