"""
Tests for the StudentService class.

Tests cover:
- Profile creation and retrieval (get_profile, get_profile_response)
- Mastery updates (correct/incorrect, clamping, attempt tracking, overall_ability)
- Target difficulty computation (easy/medium/hard ranges, unknown concepts)
- Profile reset
- JSON persistence round-trip
- Loading edge cases (missing file, corrupt JSON, legacy float format)
- Batch target difficulties (get_all_target_difficulties)
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from backend.app.student.models import (
    ConceptMastery,
    MasteryUpdateResponse,
    StudentProfile,
    StudentProfileResponse,
    TargetDifficultyResponse,
)
from backend.app.student.student_service import StudentService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path) -> StudentService:
    """Create a StudentService backed by a temporary JSON file."""
    return StudentService(storage_path=str(tmp_path / "profiles.json"))


@pytest.fixture(autouse=True)
def _disable_bkt(monkeypatch):
    """Disable BKT for all tests by default so existing linear assertions hold."""
    from backend.app.core.settings import settings

    monkeypatch.setattr(settings, "student_bkt_enabled", False)


# ===========================================================================
# TestGetProfile
# ===========================================================================


@pytest.mark.unit
class TestGetProfile:
    """Tests for get_profile (create and retrieve)."""

    def test_creates_new_profile_for_unknown_student(self, tmp_path):
        svc = _make_service(tmp_path)
        profile = svc.get_profile("alice")

        assert isinstance(profile, StudentProfile)
        assert profile.student_id == "alice"
        assert profile.overall_ability == pytest.approx(0.3)
        assert profile.mastery_map == {}

    def test_returns_same_profile_on_second_call(self, tmp_path):
        svc = _make_service(tmp_path)
        first = svc.get_profile("bob")
        second = svc.get_profile("bob")

        assert first is second

    def test_default_student_id(self, tmp_path):
        svc = _make_service(tmp_path)
        profile = svc.get_profile()

        assert profile.student_id == "default"

    def test_different_student_ids_get_separate_profiles(self, tmp_path):
        svc = _make_service(tmp_path)
        alice = svc.get_profile("alice")
        bob = svc.get_profile("bob")

        assert alice is not bob
        assert alice.student_id != bob.student_id

    def test_new_profile_has_timestamps(self, tmp_path):
        svc = _make_service(tmp_path)
        profile = svc.get_profile("new_student")

        assert isinstance(profile.created_at, datetime)
        assert isinstance(profile.updated_at, datetime)


# ===========================================================================
# TestUpdateMastery
# ===========================================================================


@pytest.mark.unit
class TestUpdateMastery:
    """Tests for update_mastery logic."""

    def test_correct_answer_increases_mastery(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("photosynthesis", correct=True)

        assert isinstance(resp, MasteryUpdateResponse)
        assert resp.previous_mastery == pytest.approx(0.3)
        assert resp.new_mastery == pytest.approx(0.45)  # 0.3 + 0.15

    def test_incorrect_answer_decreases_mastery(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("photosynthesis", correct=False)

        assert resp.previous_mastery == pytest.approx(0.3)
        assert resp.new_mastery == pytest.approx(0.2)  # 0.3 - 0.10

    def test_mastery_clamped_at_min(self, tmp_path):
        """Mastery cannot drop below MIN_MASTERY (0.1)."""
        svc = _make_service(tmp_path)

        # Drive mastery down: 0.3 -> 0.2 -> 0.1 -> 0.1 (clamped)
        svc.update_mastery("topic", correct=False)
        svc.update_mastery("topic", correct=False)
        resp = svc.update_mastery("topic", correct=False)

        assert resp.new_mastery == pytest.approx(0.1)

    def test_mastery_clamped_at_max(self, tmp_path):
        """Mastery cannot exceed MAX_MASTERY (1.0)."""
        svc = _make_service(tmp_path)

        # Drive mastery up: 0.3 -> 0.45 -> 0.60 -> 0.75 -> 0.90 -> 1.0 (clamped)
        for _ in range(5):
            resp = svc.update_mastery("topic", correct=True)

        assert resp.new_mastery == pytest.approx(1.0)

        # One more correct answer should still be capped at 1.0
        resp = svc.update_mastery("topic", correct=True)
        assert resp.new_mastery == pytest.approx(1.0)

    def test_new_concept_initialised_at_initial_mastery(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("brand_new_concept", correct=True)

        # Started at 0.3, went to 0.45
        assert resp.previous_mastery == pytest.approx(0.3)
        assert resp.new_mastery == pytest.approx(0.45)

    def test_attempt_counting(self, tmp_path):
        svc = _make_service(tmp_path)

        r1 = svc.update_mastery("concept_a", correct=True)
        assert r1.total_attempts == 1

        r2 = svc.update_mastery("concept_a", correct=False)
        assert r2.total_attempts == 2

        r3 = svc.update_mastery("concept_a", correct=True)
        assert r3.total_attempts == 3

    def test_correct_attempts_tracking(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic", correct=True)
        svc.update_mastery("topic", correct=False)
        svc.update_mastery("topic", correct=True)

        profile = svc.get_profile("default")
        mastery = profile.mastery_map["topic"]

        assert mastery.correct_attempts == 2
        assert mastery.attempts == 3

    def test_overall_ability_recalculation(self, tmp_path):
        """overall_ability is the running average of all concept mastery levels."""
        svc = _make_service(tmp_path)

        # After one correct answer on concept_a: mastery = 0.45
        svc.update_mastery("concept_a", correct=True)
        profile = svc.get_profile("default")
        assert profile.overall_ability == pytest.approx(0.45)

        # Add concept_b with one correct: mastery = 0.45
        svc.update_mastery("concept_b", correct=True)
        profile = svc.get_profile("default")
        # Average of 0.45 and 0.45
        assert profile.overall_ability == pytest.approx(0.45)

        # Wrong answer on concept_b: mastery = 0.45 - 0.10 = 0.35
        svc.update_mastery("concept_b", correct=False)
        profile = svc.get_profile("default")
        # Average of 0.45 and 0.35
        assert profile.overall_ability == pytest.approx(0.4)

    def test_response_contains_target_difficulty(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        assert resp.target_difficulty in ("easy", "medium", "hard")

    def test_update_mastery_with_specific_student_id(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True, student_id="student_42")

        assert resp.new_mastery == pytest.approx(0.45)

        # Ensure this didn't affect the default profile
        default = svc.get_profile("default")
        assert "topic" not in default.mastery_map

    def test_last_assessed_updated(self, tmp_path):
        svc = _make_service(tmp_path)
        before = datetime.now()
        svc.update_mastery("topic", correct=True)
        after = datetime.now()

        profile = svc.get_profile("default")
        last = profile.mastery_map["topic"].last_assessed
        assert last is not None
        assert before <= last <= after


# ===========================================================================
# TestGetTargetDifficulty
# ===========================================================================


@pytest.mark.unit
class TestGetTargetDifficulty:
    """Tests for get_target_difficulty method."""

    def test_easy_range(self, tmp_path):
        """Mastery < 0.4 -> easy."""
        svc = _make_service(tmp_path)
        # Default mastery is 0.3 (< 0.4 -> easy)
        resp = svc.get_target_difficulty("topic")

        assert isinstance(resp, TargetDifficultyResponse)
        assert resp.target_difficulty == "easy"
        assert resp.mastery_level == pytest.approx(0.3)

    def test_medium_range(self, tmp_path):
        """Mastery 0.4-0.7 -> medium."""
        svc = _make_service(tmp_path)

        # Push mastery to 0.45 (one correct answer: 0.3 + 0.15)
        svc.update_mastery("topic", correct=True)
        resp = svc.get_target_difficulty("topic")

        assert resp.target_difficulty == "medium"
        assert resp.mastery_level == pytest.approx(0.45)

    def test_hard_range(self, tmp_path):
        """Mastery > 0.7 -> hard."""
        svc = _make_service(tmp_path)

        # Push mastery to 0.75 (three correct: 0.3 + 3*0.15 = 0.75)
        for _ in range(3):
            svc.update_mastery("topic", correct=True)
        resp = svc.get_target_difficulty("topic")

        assert resp.target_difficulty == "hard"
        assert resp.mastery_level == pytest.approx(0.75)

    def test_unknown_concept_defaults_to_initial_mastery(self, tmp_path):
        """A concept with no history returns the initial mastery level."""
        svc = _make_service(tmp_path)
        svc.get_profile("default")  # ensure profile exists
        resp = svc.get_target_difficulty("never_seen_concept")

        assert resp.mastery_level == pytest.approx(0.3)
        assert resp.target_difficulty == "easy"

    def test_boundary_at_0_4(self, tmp_path):
        """Mastery exactly 0.4 should be medium (<=0.7 boundary)."""
        svc = _make_service(tmp_path)
        # Push to 0.3 + 0.15 = 0.45, then -0.10 = 0.35, then +0.15 = 0.50
        # We need exactly 0.4: start 0.3, wrong => 0.2, correct => 0.35, correct => 0.50
        # Actually, let's manipulate directly
        profile = svc.get_profile("default")
        profile.mastery_map["topic"] = ConceptMastery(concept_name="topic", mastery_level=0.4)
        resp = svc.get_target_difficulty("topic")
        assert resp.target_difficulty == "medium"

    def test_boundary_at_0_7(self, tmp_path):
        """Mastery exactly 0.7 should be medium (<=0.7)."""
        svc = _make_service(tmp_path)
        profile = svc.get_profile("default")
        profile.mastery_map["topic"] = ConceptMastery(concept_name="topic", mastery_level=0.7)
        resp = svc.get_target_difficulty("topic")
        assert resp.target_difficulty == "medium"


# ===========================================================================
# TestResetProfile
# ===========================================================================


@pytest.mark.unit
class TestResetProfile:
    """Tests for reset_profile method."""

    def test_reset_clears_mastery_map(self, tmp_path):
        svc = _make_service(tmp_path)

        # Build up some mastery data
        svc.update_mastery("concept_a", correct=True)
        svc.update_mastery("concept_b", correct=False)

        profile_before = svc.get_profile("default")
        assert len(profile_before.mastery_map) == 2

        resp = svc.reset_profile("default")

        assert isinstance(resp, StudentProfileResponse)
        assert resp.overall_ability == pytest.approx(0.3)
        assert resp.mastery_levels == {}

    def test_reset_returns_fresh_profile(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic", correct=True)
        resp = svc.reset_profile("default")

        assert resp.student_id == "default"
        assert resp.overall_ability == pytest.approx(0.3)
        assert resp.mastery_levels == {}

    def test_reset_persists(self, tmp_path):
        """After reset, reloading from disk also shows a clean profile."""
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)
        svc.update_mastery("topic", correct=True)
        svc.reset_profile("default")

        # Reload from file
        svc2 = StudentService(storage_path=storage)
        profile = svc2.get_profile("default")

        assert profile.mastery_map == {}
        assert profile.overall_ability == pytest.approx(0.3)

    def test_reset_specific_student(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic", correct=True, student_id="alice")
        svc.update_mastery("topic", correct=True, student_id="bob")

        svc.reset_profile("alice")

        alice = svc.get_profile("alice")
        bob = svc.get_profile("bob")

        assert alice.mastery_map == {}
        assert len(bob.mastery_map) == 1


# ===========================================================================
# TestProfilePersistence
# ===========================================================================


@pytest.mark.unit
class TestProfilePersistence:
    """Tests for JSON file round-trip persistence."""

    def test_save_and_reload(self, tmp_path):
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic_a", correct=True, student_id="student1")
        svc.update_mastery("topic_b", correct=False, student_id="student1")

        # Reload from file
        svc2 = StudentService(storage_path=storage)
        profile = svc2.get_profile("student1")

        assert "topic_a" in profile.mastery_map
        assert "topic_b" in profile.mastery_map
        assert profile.mastery_map["topic_a"].mastery_level == pytest.approx(0.45)
        assert profile.mastery_map["topic_b"].mastery_level == pytest.approx(0.2)

    def test_file_created_on_first_save(self, tmp_path):
        storage = tmp_path / "profiles.json"
        assert not storage.exists()

        svc = StudentService(storage_path=str(storage))
        svc.get_profile("default")  # triggers save

        assert storage.exists()

    def test_parent_directories_created(self, tmp_path):
        storage = tmp_path / "deep" / "nested" / "dir" / "profiles.json"
        svc = StudentService(storage_path=str(storage))
        svc.get_profile("default")

        assert storage.exists()

    def test_multiple_students_persisted(self, tmp_path):
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True, student_id="alice")
        svc.update_mastery("topic", correct=False, student_id="bob")

        svc2 = StudentService(storage_path=storage)
        assert "alice" in svc2._profiles
        assert "bob" in svc2._profiles

    def test_timestamps_survive_round_trip(self, tmp_path):
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True)
        original = svc.get_profile("default")
        original_updated = original.updated_at

        svc2 = StudentService(storage_path=storage)
        reloaded = svc2.get_profile("default")

        # Datetimes should be very close (only ISO serialisation precision loss)
        delta = abs((reloaded.updated_at - original_updated).total_seconds())
        assert delta < 1.0

    def test_attempt_counts_survive_round_trip(self, tmp_path):
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True)
        svc.update_mastery("topic", correct=False)

        svc2 = StudentService(storage_path=storage)
        profile = svc2.get_profile("default")
        mastery = profile.mastery_map["topic"]

        assert mastery.attempts == 2
        assert mastery.correct_attempts == 1


# ===========================================================================
# TestLoadProfiles
# ===========================================================================


@pytest.mark.unit
class TestLoadProfiles:
    """Tests for _load_profiles edge cases."""

    def test_missing_file_starts_fresh(self, tmp_path):
        storage = str(tmp_path / "nonexistent.json")
        svc = StudentService(storage_path=storage)

        assert svc._profiles == {}

    def test_corrupt_json_starts_fresh(self, tmp_path):
        storage = tmp_path / "profiles.json"
        storage.write_text("this is not valid json {{{")

        svc = StudentService(storage_path=str(storage))
        assert svc._profiles == {}

    def test_empty_file_starts_fresh(self, tmp_path):
        storage = tmp_path / "profiles.json"
        storage.write_text("")

        svc = StudentService(storage_path=str(storage))
        assert svc._profiles == {}

    def test_legacy_float_format(self, tmp_path):
        """Legacy files stored mastery as plain float values instead of dicts."""
        storage = tmp_path / "profiles.json"
        legacy_data = {
            "student1": {
                "student_id": "student1",
                "mastery_map": {
                    "photosynthesis": 0.65,
                    "mitosis": 0.4,
                },
                "overall_ability": 0.525,
                "created_at": "2025-01-01T12:00:00",
                "updated_at": "2025-01-15T09:30:00",
            }
        }
        storage.write_text(json.dumps(legacy_data))

        svc = StudentService(storage_path=str(storage))
        profile = svc.get_profile("student1")

        assert isinstance(profile.mastery_map["photosynthesis"], ConceptMastery)
        assert profile.mastery_map["photosynthesis"].mastery_level == pytest.approx(0.65)
        assert profile.mastery_map["photosynthesis"].concept_name == "photosynthesis"

        assert isinstance(profile.mastery_map["mitosis"], ConceptMastery)
        assert profile.mastery_map["mitosis"].mastery_level == pytest.approx(0.4)

    def test_legacy_float_format_defaults(self, tmp_path):
        """Legacy float entries should have zero attempts/correct_attempts."""
        storage = tmp_path / "profiles.json"
        legacy_data = {
            "default": {
                "student_id": "default",
                "mastery_map": {
                    "topic": 0.5,
                },
                "overall_ability": 0.5,
                "created_at": "2025-01-01T12:00:00",
                "updated_at": "2025-01-01T12:00:00",
            }
        }
        storage.write_text(json.dumps(legacy_data))

        svc = StudentService(storage_path=str(storage))
        mastery = svc.get_profile("default").mastery_map["topic"]

        assert mastery.attempts == 0
        assert mastery.correct_attempts == 0
        assert mastery.last_assessed is None

    def test_dict_format_loads_correctly(self, tmp_path):
        """Modern dict-format mastery entries should load with all fields."""
        storage = tmp_path / "profiles.json"
        data = {
            "default": {
                "student_id": "default",
                "mastery_map": {
                    "evolution": {
                        "concept_name": "evolution",
                        "mastery_level": 0.7,
                        "attempts": 5,
                        "correct_attempts": 4,
                        "last_assessed": "2025-06-01T10:00:00",
                    }
                },
                "overall_ability": 0.7,
                "created_at": "2025-01-01T12:00:00",
                "updated_at": "2025-06-01T10:00:00",
            }
        }
        storage.write_text(json.dumps(data))

        svc = StudentService(storage_path=str(storage))
        mastery = svc.get_profile("default").mastery_map["evolution"]

        assert mastery.concept_name == "evolution"
        assert mastery.mastery_level == pytest.approx(0.7)
        assert mastery.attempts == 5
        assert mastery.correct_attempts == 4
        assert mastery.last_assessed is not None

    def test_datetime_parsing(self, tmp_path):
        """ISO datetime strings in created_at/updated_at should be parsed."""
        storage = tmp_path / "profiles.json"
        data = {
            "default": {
                "student_id": "default",
                "mastery_map": {},
                "overall_ability": 0.3,
                "created_at": "2025-03-15T14:30:00",
                "updated_at": "2025-06-20T09:15:00",
            }
        }
        storage.write_text(json.dumps(data))

        svc = StudentService(storage_path=str(storage))
        profile = svc.get_profile("default")

        assert isinstance(profile.created_at, datetime)
        assert profile.created_at.year == 2025
        assert profile.created_at.month == 3
        assert isinstance(profile.updated_at, datetime)
        assert profile.updated_at.month == 6


# ===========================================================================
# TestGetProfileResponse
# ===========================================================================


@pytest.mark.unit
class TestGetProfileResponse:
    """Tests for get_profile_response (API response format)."""

    def test_empty_profile(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.get_profile_response("default")

        assert isinstance(resp, StudentProfileResponse)
        assert resp.student_id == "default"
        assert resp.overall_ability == pytest.approx(0.3)
        assert resp.mastery_levels == {}
        assert isinstance(resp.updated_at, datetime)

    def test_mastery_levels_are_simple_floats(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic_a", correct=True)
        svc.update_mastery("topic_b", correct=False)

        resp = svc.get_profile_response("default")

        assert isinstance(resp.mastery_levels, dict)
        assert resp.mastery_levels["topic_a"] == pytest.approx(0.45)
        assert resp.mastery_levels["topic_b"] == pytest.approx(0.2)

    def test_overall_ability_matches_profile(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic_a", correct=True)  # 0.45
        svc.update_mastery("topic_b", correct=True)  # 0.45

        resp = svc.get_profile_response("default")

        # Average of 0.45 and 0.45
        assert resp.overall_ability == pytest.approx(0.45)

    def test_creates_profile_if_missing(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.get_profile_response("brand_new_student")

        assert resp.student_id == "brand_new_student"
        assert resp.overall_ability == pytest.approx(0.3)


# ===========================================================================
# TestGetAllTargetDifficulties
# ===========================================================================


@pytest.mark.unit
class TestGetAllTargetDifficulties:
    """Tests for get_all_target_difficulties method."""

    def test_empty_profile_returns_empty_dict(self, tmp_path):
        svc = _make_service(tmp_path)
        result = svc.get_all_target_difficulties("default")

        assert result == {}

    def test_returns_difficulty_for_all_tracked_concepts(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("easy_topic", correct=False)  # 0.2 -> easy
        svc.update_mastery("medium_topic", correct=True)  # 0.45 -> medium

        # Push hard_topic to 0.75 (3 correct: 0.3 + 3*0.15)
        for _ in range(3):
            svc.update_mastery("hard_topic", correct=True)

        result = svc.get_all_target_difficulties("default")

        assert result["easy_topic"] == "easy"
        assert result["medium_topic"] == "medium"
        assert result["hard_topic"] == "hard"

    def test_only_includes_tracked_concepts(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("tracked", correct=True)
        result = svc.get_all_target_difficulties("default")

        assert "tracked" in result
        assert "untracked" not in result

    def test_per_student_isolation(self, tmp_path):
        svc = _make_service(tmp_path)

        svc.update_mastery("topic_a", correct=True, student_id="alice")
        svc.update_mastery("topic_b", correct=True, student_id="bob")

        alice_diffs = svc.get_all_target_difficulties("alice")
        bob_diffs = svc.get_all_target_difficulties("bob")

        assert "topic_a" in alice_diffs
        assert "topic_b" not in alice_diffs
        assert "topic_b" in bob_diffs
        assert "topic_a" not in bob_diffs


# ===========================================================================
# TestBKTUpdate
# ===========================================================================


@pytest.mark.unit
class TestBKTUpdate:
    """Tests for Bayesian Knowledge Tracing mastery updates."""

    @pytest.fixture(autouse=True)
    def _enable_bkt(self, monkeypatch):
        from backend.app.core.settings import settings

        monkeypatch.setattr(settings, "student_bkt_enabled", True)

    def test_correct_answer_increases_mastery(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        assert resp.new_mastery > resp.previous_mastery
        assert resp.bkt_p_known is not None
        assert resp.bkt_p_known > 0.3

    def test_incorrect_answer_decreases_mastery(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=False)

        assert resp.new_mastery < resp.previous_mastery
        assert resp.bkt_p_known is not None
        assert resp.bkt_p_known < 0.3

    def test_exact_single_correct_from_default(self, tmp_path):
        """Verify exact BKT math for one correct answer from P(L)=0.3."""
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        # P(L)=0.3, P(S)=0.1, P(G)=0.25
        # posterior = 0.3*0.9 / (0.3*0.9 + 0.7*0.25) = 0.27/0.445 ≈ 0.6067
        # P(L_new) = 0.6067 + (1 - 0.6067)*0.1 ≈ 0.6461
        assert resp.bkt_p_known == pytest.approx(0.646, abs=0.001)

    def test_exact_single_incorrect_from_default(self, tmp_path):
        """Verify exact BKT math for one incorrect answer from P(L)=0.3."""
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=False)

        # P(L)=0.3, P(S)=0.1, P(G)=0.25
        # posterior = 0.3*0.1 / (0.3*0.1 + 0.7*0.75) = 0.03/0.555 ≈ 0.05405
        # P(L_new) = 0.05405 + (1 - 0.05405)*0.1 ≈ 0.14865
        assert resp.bkt_p_known == pytest.approx(0.1486, abs=0.001)

    def test_convergence_many_correct(self, tmp_path):
        """15 consecutive correct answers should yield P(L) > 0.9."""
        svc = _make_service(tmp_path)
        for _ in range(15):
            resp = svc.update_mastery("topic", correct=True)

        assert resp.bkt_p_known is not None
        assert resp.bkt_p_known > 0.9

    def test_five_correct_convergence(self, tmp_path):
        """5 correct answers from P(L)=0.3 should yield high mastery (clamped at 0.99)."""
        svc = _make_service(tmp_path)
        for _ in range(5):
            resp = svc.update_mastery("topic", correct=True)

        assert resp.bkt_p_known is not None
        # BKT converges rapidly with these parameters; 5 correct → hits 0.99 clamp
        assert resp.bkt_p_known >= 0.95

    def test_bootstrap_from_existing_mastery(self, tmp_path):
        """bkt_p_known should bootstrap from existing mastery_level."""
        svc = _make_service(tmp_path)
        profile = svc.get_profile("default")
        profile.mastery_map["topic"] = ConceptMastery(
            concept_name="topic",
            mastery_level=0.6,
        )
        # bkt_p_known is None, should bootstrap from 0.6
        resp = svc.update_mastery("topic", correct=True)

        assert resp.bkt_p_known is not None
        assert resp.bkt_p_known > 0.6

    def test_bkt_p_known_clamped(self, tmp_path):
        """bkt_p_known should be clamped to [0.01, 0.99]."""
        svc = _make_service(tmp_path)

        # Many incorrect to drive p_known down
        for _ in range(50):
            resp = svc.update_mastery("topic", correct=False)

        assert resp.bkt_p_known is not None
        assert resp.bkt_p_known >= 0.01

        # Many correct to drive p_known up
        svc2 = _make_service(tmp_path / "sub")
        for _ in range(50):
            resp2 = svc2.update_mastery("topic2", correct=True)

        assert resp2.bkt_p_known is not None
        assert resp2.bkt_p_known <= 0.99

    def test_json_round_trip_preserves_bkt(self, tmp_path):
        """BKT fields survive JSON serialization and reload."""
        storage = str(tmp_path / "profiles.json")
        svc = StudentService(storage_path=storage)
        svc.update_mastery("topic", correct=True)

        svc2 = StudentService(storage_path=storage)
        mastery = svc2.get_profile("default").mastery_map["topic"]

        assert mastery.bkt_p_known is not None
        assert mastery.bkt_p_known == pytest.approx(0.646, abs=0.001)
        assert mastery.bkt_p_transit == 0.1
        assert mastery.bkt_p_slip == 0.1
        assert mastery.bkt_p_guess == 0.25

    def test_response_includes_bkt_p_known(self, tmp_path):
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        assert resp.bkt_p_known is not None
        assert isinstance(resp.bkt_p_known, float)

    def test_mastery_level_maps_from_bkt(self, tmp_path):
        """mastery_level should be clamped to [0.1, 1.0] from bkt_p_known."""
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        assert resp.new_mastery >= 0.1
        assert resp.new_mastery <= 1.0


# ===========================================================================
# TestLinearFallback
# ===========================================================================


@pytest.mark.unit
class TestLinearFallback:
    """Verify the linear model still works when BKT is disabled."""

    def test_correct_answer_linear(self, tmp_path):
        """BKT disabled: correct answer uses +0.15 delta."""
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=True)

        assert resp.new_mastery == pytest.approx(0.45)
        assert resp.bkt_p_known is None

    def test_incorrect_answer_linear(self, tmp_path):
        """BKT disabled: incorrect answer uses -0.10 delta."""
        svc = _make_service(tmp_path)
        resp = svc.update_mastery("topic", correct=False)

        assert resp.new_mastery == pytest.approx(0.2)
        assert resp.bkt_p_known is None

    def test_linear_clamp_min(self, tmp_path):
        svc = _make_service(tmp_path)
        for _ in range(10):
            resp = svc.update_mastery("topic", correct=False)

        assert resp.new_mastery == pytest.approx(0.1)

    def test_linear_clamp_max(self, tmp_path):
        svc = _make_service(tmp_path)
        for _ in range(10):
            resp = svc.update_mastery("topic", correct=True)

        assert resp.new_mastery == pytest.approx(1.0)
