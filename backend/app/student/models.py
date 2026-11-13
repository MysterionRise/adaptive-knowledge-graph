"""
Student profile and mastery models for adaptive learning.

These models track student proficiency levels per concept
and enable personalized quiz difficulty targeting.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.core.settings import settings
from backend.app.student.policy import (
    DecisionContext,
    DecisionRecord,
    LearnerState,
    difficulty_of,
    get_policy,
)
from backend.app.ui_payloads.decisions import DecisionRecordPayload

DIFFICULTY_POLICY = "band-v1"
"""Registry key of the policy that chooses the target difficulty."""


class ConceptMastery(BaseModel):
    """Mastery level for a single concept."""

    concept_name: str = Field(..., max_length=200)
    mastery_level: float = Field(default=0.3, ge=0.0, le=1.0)
    attempts: int = 0
    correct_attempts: int = 0
    last_assessed: datetime | None = None

    # BKT (Bayesian Knowledge Tracing) fields
    bkt_p_known: float | None = None
    bkt_p_transit: float = 0.1
    bkt_p_slip: float = 0.1
    bkt_p_guess: float = 0.25

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
        """Get mastery level for a concept (STUDENT_INITIAL_MASTERY if it has no history)."""
        if concept in self.mastery_map:
            return self.mastery_map[concept].mastery_level
        return settings.student_initial_mastery

    def learner_state(self, concept: str) -> LearnerState:
        """
        The view of this learner that a policy gets for one concept.

        It holds the mastery level stored for the concept (nothing if the concept has no
        history) and the initial mastery (STUDENT_INITIAL_MASTERY). No other field of the
        profile is in it: no attempts, dates or BKT values, and no other concept's mastery.
        """
        record = self.mastery_map.get(concept)
        mastery = {} if record is None else {concept: record.mastery_level}
        return LearnerState(mastery=mastery, initial_mastery=settings.student_initial_mastery)

    def decide_difficulty(self, concept: str) -> DecisionRecord:
        """The target-difficulty decision for a concept, as the policy's decision record."""
        policy = get_policy(DIFFICULTY_POLICY)
        return policy.decide(self.learner_state(concept), DecisionContext(concept=concept))

    def get_target_difficulty(self, concept: str) -> Literal["easy", "medium", "hard"]:
        """
        Determine target difficulty based on mastery level.

        A shim: it returns the action of ``decide_difficulty``. The rule is the policy
        band-v1 (``backend/app/student/policy/band.py``):
        - mastery < 0.4 -> "easy" questions
        - mastery 0.4-0.7 -> "medium" questions
        - mastery > 0.7 -> "hard" questions
        """
        return difficulty_of(self.decide_difficulty(concept))


class MasteryUpdate(BaseModel):
    """Request model for updating mastery after an answer."""

    concept: str = Field(..., min_length=1, max_length=200)
    correct: bool
    subject: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Subject whose knowledge graph must contain the concept when concept "
            "validation is enabled (defaults to the default subject)"
        ),
    )


class MasteryUpdateResponse(BaseModel):
    """Response model for mastery update."""

    concept: str
    previous_mastery: float
    new_mastery: float
    target_difficulty: Literal["easy", "medium", "hard"]
    total_attempts: int
    bkt_p_known: float | None = None


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
    decision: DecisionRecordPayload | None = Field(
        default=None,
        description=(
            "The decision record behind target_difficulty: the policy, its action and the "
            "inputs it read"
        ),
    )
