"""
Quiz generation endpoints.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

from backend.app.core.exceptions import ContentNotFoundError, QuizGenerationError
from backend.app.student.quiz_generator import get_quiz_generator
from backend.app.ui_payloads.quiz import Quiz

router = APIRouter(tags=["Quiz"])


@router.post("/quiz/generate", response_model=Quiz)
async def generate_quiz(topic: str, num_questions: int = 3):
    """Generate an adaptive quiz for a topic."""
    try:
        generator = get_quiz_generator()
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
