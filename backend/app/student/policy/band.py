"""
The band rule as the policy ``band-v1`` (#306).

The rule maps the mastery level of one concept to the difficulty a quiz prompt asks for:
below 0.4 "easy", up to and including 0.7 "medium", above that "hard". A concept without
history is decided with the initial mastery. These are the boundaries
``StudentProfile.get_target_difficulty`` had before it became a shim over this policy, and
``backend/tests/test_student_counterfactual.py`` pins them.

The difficulty is requested in the prompt only. Nothing here checks the difficulty of the
questions that come back, and the mastery estimate is not validated.

Like ``base.py``, this module imports the standard library only.
"""

from typing import ClassVar, Final, Literal

from backend.app.student.policy.base import DecisionContext, DecisionRecord, LearnerState

Difficulty = Literal["easy", "medium", "hard"]

EASY_BELOW: Final = 0.4
"""Mastery below this value gets "easy"; the value itself gets "medium"."""

MEDIUM_UP_TO: Final = 0.7
"""Mastery up to and including this value gets "medium"; anything above gets "hard"."""

_DIFFICULTIES: Final[tuple[Difficulty, ...]] = ("easy", "medium", "hard")


def band_for(mastery: float) -> Difficulty:
    """The difficulty band of a mastery level."""
    if mastery < EASY_BELOW:
        return "easy"
    if mastery <= MEDIUM_UP_TO:
        return "medium"
    return "hard"


def difficulty_of(record: DecisionRecord) -> Difficulty:
    """The difficulty a decision chose.

    Raises:
        ValueError: If the record's action holds no difficulty
    """
    chosen = record.action.get("difficulty")
    for difficulty in _DIFFICULTIES:
        if chosen == difficulty:
            return difficulty
    raise ValueError(f"The action holds no difficulty: {dict(record.action)!r}")


class BandPolicyV1:
    """``band-v1``: the difficulty band of the asked concept's mastery level.

    Declared inputs: ``context.concept`` and, from the state, the mastery level of that
    concept, or the initial mastery when the concept has no history. The record's
    ``state_used`` holds that one number, unrounded, and ``mastery_source`` says which of the
    two it was ("tracked" or "initial"). Nothing else is read: no other context field and no
    graph edge.
    """

    id: ClassVar[str] = "band"
    version: ClassVar[str] = "v1"

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """Choose the difficulty for ``context.concept``.

        Raises:
            ValueError: If the context names no concept
        """
        concept = context.concept
        if concept is None:
            raise ValueError("band-v1 needs the concept to decide for (context.concept)")

        tracked = concept in state.mastery
        # float(): one number type in the record. The integer 1 and the float 1.0 would be
        # two different records.
        mastery = float(state.mastery[concept] if tracked else state.initial_mastery)

        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": "difficulty", "difficulty": band_for(mastery)},
            state_used={"mastery": mastery, "mastery_source": "tracked" if tracked else "initial"},
            context_used={"concept": concept},
        )


BAND_V1: Final = BandPolicyV1()
"""The one instance of ``band-v1``; ``get_policy("band-v1")`` returns it."""
