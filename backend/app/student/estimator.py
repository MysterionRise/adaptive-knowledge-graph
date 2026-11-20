"""
The mastery update: one graded answer applied to a learner profile.

``apply_answer`` is the update ``StudentService`` runs inside its write transaction (the
service's ``_apply_answer`` delegates to it): Bayesian Knowledge Tracing with the parameters
stored on the concept's record, or the linear rule when BKT is off, then the mastery floor and
cap, the counters and the profile's overall ability.

The function reads no setting, no clock and no storage. The caller passes the initial
mastery, whether BKT is on and the time to stamp, so the learner simulator
(``backend/app/student/simulation/``) runs the same update as the service without SQLite.
This module imports the learner models only: no Neo4j adapter and no web framework.
"""

from datetime import datetime
from typing import Final

from backend.app.student.models import ConceptMastery, StudentProfile

CORRECT_DELTA: Final = 0.15
"""Linear rule: increase on a correct answer."""

INCORRECT_DELTA: Final = 0.10
"""Linear rule: decrease on an incorrect answer (absolute value)."""

MIN_MASTERY: Final = 0.1
"""Floor of the stored mastery level."""

MAX_MASTERY: Final = 1.0
"""Cap of the stored mastery level."""


def update_mastery_linear(mastery_level: float, correct: bool) -> float:
    """Linear mastery update: +0.15 for correct, -0.10 for incorrect."""
    delta = CORRECT_DELTA if correct else -INCORRECT_DELTA
    return mastery_level + delta


def update_mastery_bkt(mastery: ConceptMastery, correct: bool) -> float:
    """Bayesian Knowledge Tracing update.

    Standard BKT with 4 parameters:
    - P(L) = probability student knows the concept
    - P(T) = probability of learning per attempt
    - P(S) = probability of slipping (wrong despite knowing)
    - P(G) = probability of guessing (right despite not knowing)
    """
    p_l = mastery.bkt_p_known if mastery.bkt_p_known is not None else mastery.mastery_level
    p_t = mastery.bkt_p_transit
    p_s = mastery.bkt_p_slip
    p_g = mastery.bkt_p_guess

    if correct:
        denom = p_l * (1 - p_s) + (1 - p_l) * p_g
        posterior = p_l * (1 - p_s) / denom if denom > 0 else p_l
    else:
        denom = p_l * p_s + (1 - p_l) * (1 - p_g)
        posterior = p_l * p_s / denom if denom > 0 else p_l

    p_l_new = posterior + (1 - posterior) * p_t
    return max(0.01, min(0.99, p_l_new))


def apply_answer(
    profile: StudentProfile,
    concept: str,
    correct: bool,
    *,
    initial_mastery: float,
    bkt_enabled: bool,
    now: datetime,
) -> float:
    """
    Apply one answer to the profile in place.

    Args:
        profile: The learner's profile; its record for ``concept`` is created if missing
        concept: Concept that the answered question tests
        correct: Whether the answer was correct
        initial_mastery: Mastery level of a concept without history (STUDENT_INITIAL_MASTERY)
        bkt_enabled: True for the BKT update, False for the linear rule (STUDENT_BKT_ENABLED)
        now: The time stamped on the record (``last_assessed``) and the profile (``updated_at``)

    Returns:
        The concept's mastery level before the answer
    """
    if concept not in profile.mastery_map:
        profile.mastery_map[concept] = ConceptMastery(
            concept_name=concept,
            mastery_level=initial_mastery,
        )

    mastery = profile.mastery_map[concept]
    previous_mastery = mastery.mastery_level

    if correct:
        mastery.correct_attempts += 1

    if bkt_enabled:
        # Bootstrap bkt_p_known from mastery_level if not yet set
        if mastery.bkt_p_known is None:
            mastery.bkt_p_known = mastery.mastery_level

        mastery.bkt_p_known = update_mastery_bkt(mastery, correct)
        # Map bkt_p_known to mastery_level, clamped to [0.1, 1.0]
        new_level = max(MIN_MASTERY, min(MAX_MASTERY, mastery.bkt_p_known))
    else:
        new_level = max(
            MIN_MASTERY,
            min(MAX_MASTERY, update_mastery_linear(mastery.mastery_level, correct)),
        )

    mastery.mastery_level = new_level
    mastery.attempts += 1
    mastery.last_assessed = now

    # Overall ability is the average mastery across tracked concepts
    total_mastery = sum(m.mastery_level for m in profile.mastery_map.values())
    profile.overall_ability = total_mastery / len(profile.mastery_map)
    profile.updated_at = now

    return previous_mastery
