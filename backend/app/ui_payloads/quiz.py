from typing import Literal

from pydantic import BaseModel


class QuizOption(BaseModel):
    id: str
    text: str


class QuizQuestion(BaseModel):
    id: str
    text: str
    options: list[QuizOption]
    correct_option_id: str
    explanation: str
    source_chunk_id: str | None = None
    related_concept: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    difficulty_score: float | None = None  # 0.0-1.0 IRT-style difficulty


class Quiz(BaseModel):
    id: str
    title: str
    questions: list[QuizQuestion]
    average_difficulty: float | None = None  # Average difficulty across questions


class AdaptiveQuiz(Quiz):
    """Quiz with adaptation metadata for personalized learning."""

    student_mastery: float  # Student's current mastery level for the topic (0.0-1.0)
    target_difficulty: Literal["easy", "medium", "hard"]  # Difficulty level targeted
    adapted: bool = True  # Whether this quiz was adapted to student's level
