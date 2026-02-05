"""
Student profile and mastery models for adaptive learning.

These models track student proficiency levels per concept
and enable personalized quiz difficulty targeting.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConceptMastery(BaseModel):
    """Mastery level for a single concept."""

    concept_name: str
    mastery_level: float = Field(default=0.3, ge=0.0, le=1.0)
    attempts: int = 0
    correct_attempts: int = 0
    last_assessed: datetime | None = None

    @property
    def accuracy(self) -> float:
        """Calculate accuracy rate for this concept."""
        if self.attempts == 0:
            return 0.0
        return self.correct_attempts / self.attempts


class StudentProfile(BaseModel):
    """Complete student profile with mastery tracking."""

    student_id: str = "default"
    mastery_map: dict[str, ConceptMastery] = Field(default_factory=dict)
    overall_ability: float = Field(default=0.3, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def get_mastery(self, concept: str) -> float:
        """Get mastery level for a concept (default: initial mastery)."""
        if concept in self.mastery_map:
            return self.mastery_map[concept].mastery_level
        return 0.3  # Initial mastery from settings

    def get_target_difficulty(self, concept: str) -> Literal["easy", "medium", "hard"]:
        """
        Determine target difficulty based on mastery level.

        Difficulty Targeting:
        - mastery < 0.4 -> "easy" questions
        - mastery 0.4-0.7 -> "medium" questions
        - mastery > 0.7 -> "hard" questions
        """
        mastery = self.get_mastery(concept)

        if mastery < 0.4:
            return "easy"
        elif mastery <= 0.7:
            return "medium"
        else:
            return "hard"


class MasteryUpdate(BaseModel):
    """Request model for updating mastery after an answer."""

    concept: str
    correct: bool


class MasteryUpdateResponse(BaseModel):
    """Response model for mastery update."""

    concept: str
    previous_mastery: float
    new_mastery: float
    target_difficulty: Literal["easy", "medium", "hard"]
    total_attempts: int


class StudentProfileResponse(BaseModel):
    """API response model for student profile."""

    student_id: str
    overall_ability: float
    mastery_levels: dict[str, float]
    updated_at: datetime


class TargetDifficultyResponse(BaseModel):
    """Response model for difficulty targeting."""

    concept: str
    mastery_level: float
    target_difficulty: Literal["easy", "medium", "hard"]
