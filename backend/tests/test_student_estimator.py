"""
Tests for the mastery update as a function without settings, clock or storage (#307).

``backend/app/student/estimator.py`` holds the update ``StudentService`` applies to a
profile after an answer. ``StudentService._apply_answer`` delegates to
``estimator.apply_answer`` and passes the two settings and the time, so the learner simulator
can run the same update without SQLite. The move changes no behaviour: the existing service
tests and the property tests of #210 (``test_student_bkt_properties.py``) run through the
delegate, and this module compares the two paths answer by answer.

Everything here works on in-memory models: no database, no LLM.
"""

import random
from datetime import UTC, datetime

import pytest

from backend.app.core.settings import settings
from backend.app.student import estimator
from backend.app.student.estimator import apply_answer, update_mastery_bkt, update_mastery_linear
from backend.app.student.models import ConceptMastery, StudentProfile
from backend.app.student.student_service import StudentService

pytestmark = pytest.mark.unit

SEED = 307
NOW = datetime(2000, 1, 1, 0, 5, tzinfo=UTC)
CONCEPTS = ("Fresh", "Stored", "No learning")


def _profile(rng: random.Random) -> StudentProfile:
    """Two stored concepts, one of them with transit 0; "Fresh" has no record yet."""
    return StudentProfile(
        student_id="seeded",
        mastery_map={
            "Stored": ConceptMastery(concept_name="Stored", mastery_level=rng.random()),
            "No learning": ConceptMastery(concept_name="No learning", bkt_p_transit=0.0),
        },
    )


def _answers(rng: random.Random, count: int) -> list[tuple[str, bool]]:
    return [(CONCEPTS[int(rng.random() * len(CONCEPTS))], rng.random() < 0.5) for _ in range(count)]


def _levels(profile: StudentProfile) -> dict[str, tuple[float, float | None, int, int]]:
    return {
        concept: (
            record.mastery_level,
            record.bkt_p_known,
            record.attempts,
            record.correct_attempts,
        )
        for concept, record in profile.mastery_map.items()
    }


# ---------------------------------------------------------------------------
# The service runs this function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bkt_enabled", [True, False], ids=["bkt", "linear"])
@pytest.mark.parametrize("initial", [0.3, 0.55])
def test_service_passes_the_settings_and_one_time(monkeypatch, bkt_enabled, initial):
    """The method adds what the function does not read: two settings and the time."""
    monkeypatch.setattr(settings, "student_bkt_enabled", bkt_enabled)
    monkeypatch.setattr(settings, "student_initial_mastery", initial)
    calls = []

    def spy(profile, concept, correct, **keywords):
        calls.append((profile, concept, correct, keywords))
        return 0.42

    monkeypatch.setattr(estimator, "apply_answer", spy)
    profile = StudentProfile()
    before = datetime.now()

    result = StudentService.__new__(StudentService)._apply_answer(profile, "c", True)

    assert result == 0.42
    ((seen_profile, concept, correct, keywords),) = calls
    assert seen_profile is profile
    assert (concept, correct) == ("c", True)
    assert set(keywords) == {"initial_mastery", "bkt_enabled", "now"}
    assert keywords["initial_mastery"] == initial
    assert keywords["bkt_enabled"] is bkt_enabled
    assert before <= keywords["now"] <= datetime.now()
    assert keywords["now"].tzinfo is None  # the naive local time the service always stamped


@pytest.mark.parametrize("bkt_enabled", [True, False], ids=["bkt", "linear"])
def test_function_and_service_give_the_same_profile_answer_by_answer(monkeypatch, bkt_enabled):
    monkeypatch.setattr(settings, "student_bkt_enabled", bkt_enabled)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = StudentService.__new__(StudentService)
    rng = random.Random(SEED)

    for _ in range(50):
        through_service = _profile(rng)
        direct = through_service.model_copy(deep=True)
        for concept, correct in _answers(rng, 40):
            previous_service = service._apply_answer(through_service, concept, correct)
            previous_direct = apply_answer(
                direct, concept, correct, initial_mastery=0.3, bkt_enabled=bkt_enabled, now=NOW
            )

            assert previous_direct == previous_service
            assert _levels(direct) == _levels(through_service)
            assert direct.overall_ability == through_service.overall_ability


def test_service_constants_and_updates_are_the_estimator_s():
    assert StudentService.CORRECT_DELTA is estimator.CORRECT_DELTA == 0.15
    assert StudentService.INCORRECT_DELTA is estimator.INCORRECT_DELTA == 0.10
    assert StudentService.MIN_MASTERY is estimator.MIN_MASTERY == 0.1
    assert StudentService.MAX_MASTERY is estimator.MAX_MASTERY == 1.0

    rng = random.Random(SEED)
    for _ in range(200):
        prior, correct = rng.random(), rng.random() < 0.5
        record = ConceptMastery(concept_name="c", mastery_level=prior, bkt_p_known=prior)

        assert StudentService._update_mastery_bkt(record, correct) == update_mastery_bkt(
            record, correct
        )
        assert StudentService._update_mastery_linear(prior, correct) == update_mastery_linear(
            prior, correct
        )


# ---------------------------------------------------------------------------
# The function reads no setting and no clock
# ---------------------------------------------------------------------------


def test_function_uses_the_arguments_not_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "student_initial_mastery", 0.9)
    monkeypatch.setattr(settings, "student_bkt_enabled", False)
    profile = StudentProfile()

    previous = apply_answer(profile, "c", True, initial_mastery=0.3, bkt_enabled=True, now=NOW)

    record = profile.mastery_map["c"]
    assert previous == 0.3
    # BKT from 0.3 with the defaults: 0.27 / 0.445, then the learning step.
    assert record.bkt_p_known == pytest.approx(115 / 178, abs=1e-12)
    assert record.mastery_level == record.bkt_p_known


def test_linear_rule_when_bkt_is_off(monkeypatch):
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    profile = StudentProfile()

    apply_answer(profile, "c", True, initial_mastery=0.3, bkt_enabled=False, now=NOW)
    apply_answer(profile, "c", False, initial_mastery=0.3, bkt_enabled=False, now=NOW)

    record = profile.mastery_map["c"]
    assert record.mastery_level == pytest.approx(0.35, abs=1e-12)
    assert record.bkt_p_known is None


def test_the_given_time_is_stamped_on_record_and_profile():
    created = datetime(1999, 12, 31, tzinfo=UTC)
    profile = StudentProfile(created_at=created, updated_at=created)

    apply_answer(profile, "c", False, initial_mastery=0.3, bkt_enabled=True, now=NOW)

    assert profile.mastery_map["c"].last_assessed == NOW
    assert profile.updated_at == NOW
    assert profile.created_at == created


def test_counters_and_overall_ability():
    profile = StudentProfile(mastery_map={"a": ConceptMastery(concept_name="a", mastery_level=0.9)})

    apply_answer(profile, "b", True, initial_mastery=0.3, bkt_enabled=True, now=NOW)
    apply_answer(profile, "b", False, initial_mastery=0.3, bkt_enabled=True, now=NOW)

    record = profile.mastery_map["b"]
    assert (record.attempts, record.correct_attempts) == (2, 1)
    assert profile.overall_ability == pytest.approx((0.9 + record.mastery_level) / 2, abs=1e-12)


def test_mastery_floor_of_0_1_holds_in_the_function():
    """With transit 0, two wrong answers take p_known to 2/37 and then to the 0.01 clamp."""
    record = ConceptMastery(concept_name="c", mastery_level=0.3, bkt_p_transit=0.0)
    profile = StudentProfile(mastery_map={"c": record})

    apply_answer(profile, "c", False, initial_mastery=0.3, bkt_enabled=True, now=NOW)
    assert record.bkt_p_known == pytest.approx(2 / 37, abs=1e-12)
    assert record.mastery_level == 0.1

    apply_answer(profile, "c", False, initial_mastery=0.3, bkt_enabled=True, now=NOW)
    assert record.bkt_p_known == 0.01
    assert record.mastery_level == 0.1


def test_linear_rule_stops_at_the_floor_and_the_cap():
    profile = StudentProfile(
        mastery_map={
            "low": ConceptMastery(concept_name="low", mastery_level=0.15),
            "high": ConceptMastery(concept_name="high", mastery_level=0.95),
        }
    )

    apply_answer(profile, "low", False, initial_mastery=0.3, bkt_enabled=False, now=NOW)
    apply_answer(profile, "high", True, initial_mastery=0.3, bkt_enabled=False, now=NOW)

    assert profile.mastery_map["low"].mastery_level == 0.1
    assert profile.mastery_map["high"].mastery_level == 1.0
