"""
Tests for the StudentService class.

Tests cover:
- Profile creation and retrieval (get_profile, get_profile_response)
- Mastery updates (correct/incorrect, clamping, attempt tracking, overall_ability)
- Target difficulty computation (easy/medium/hard ranges, unknown concepts)
- Profile reset
- SQLite persistence: round-trips, read-through across instances, atomic updates
- Storage failures raise StudentStorageError
- Concept validation (injectable validator, knowledge-graph default, opt-in wiring)
- Batch target difficulties (get_all_target_difficulties)
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core.exceptions import Neo4jConnectionError
from backend.app.student import student_service as student_service_module
from backend.app.student.models import (
    ConceptMastery,
    MasteryUpdateResponse,
    StudentProfile,
    StudentProfileResponse,
    TargetDifficultyResponse,
)
from backend.app.student.student_service import (
    StudentService,
    StudentStorageError,
    UnknownConceptError,
    get_student_service,
    kg_concept_exists,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path, **kwargs) -> StudentService:
    """Create a StudentService backed by a temporary SQLite file."""
    return StudentService(storage_path=str(tmp_path / "profiles.sqlite3"), **kwargs)


def _row_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0]


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

    def test_reading_an_unknown_student_does_not_write(self, tmp_path):
        svc = _make_service(tmp_path)
        svc.get_profile("ghost")
        svc.get_profile_response("ghost")

        assert _row_count(tmp_path / "profiles.sqlite3") == 0

    def test_repeated_reads_return_the_stored_profile(self, tmp_path):
        svc = _make_service(tmp_path)
        svc.update_mastery("topic", correct=True, student_id="bob")

        first = svc.get_profile("bob")
        second = svc.get_profile("bob")

        assert first.model_dump() == second.model_dump()

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

    def test_initial_mastery_follows_settings(self, tmp_path, monkeypatch):
        from backend.app.core.settings import settings

        monkeypatch.setattr(settings, "student_initial_mastery", 0.5)
        svc = _make_service(tmp_path)

        assert svc.get_target_difficulty("unseen").mastery_level == pytest.approx(0.5)
        resp = svc.update_mastery("topic", correct=True)
        assert resp.previous_mastery == pytest.approx(0.5)


# ===========================================================================
# TestGetTargetDifficulty
# ===========================================================================


@pytest.mark.unit
class TestGetTargetDifficulty:
    """Tests for get_target_difficulty method."""

    def _save_mastery(self, svc: StudentService, concept: str, level: float) -> None:
        profile = svc.get_profile("default")
        profile.mastery_map[concept] = ConceptMastery(concept_name=concept, mastery_level=level)
        svc.save_profile(profile)

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
        svc.update_mastery("other_concept", correct=True)  # ensure profile exists
        resp = svc.get_target_difficulty("never_seen_concept")

        assert resp.mastery_level == pytest.approx(0.3)
        assert resp.target_difficulty == "easy"

    def test_boundary_at_0_4(self, tmp_path):
        """Mastery exactly 0.4 should be medium (<=0.7 boundary)."""
        svc = _make_service(tmp_path)
        self._save_mastery(svc, "topic", 0.4)
        resp = svc.get_target_difficulty("topic")
        assert resp.target_difficulty == "medium"

    def test_boundary_at_0_7(self, tmp_path):
        """Mastery exactly 0.7 should be medium (<=0.7)."""
        svc = _make_service(tmp_path)
        self._save_mastery(svc, "topic", 0.7)
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
        """After reset, a new service instance also sees a clean profile."""
        storage = str(tmp_path / "profiles.sqlite3")
        svc = StudentService(storage_path=storage)
        svc.update_mastery("topic", correct=True)
        svc.reset_profile("default")

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
    """Tests for SQLite round-trip persistence."""

    def test_save_and_reload(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic_a", correct=True, student_id="student1")
        svc.update_mastery("topic_b", correct=False, student_id="student1")

        svc2 = StudentService(storage_path=storage)
        profile = svc2.get_profile("student1")

        assert "topic_a" in profile.mastery_map
        assert "topic_b" in profile.mastery_map
        assert profile.mastery_map["topic_a"].mastery_level == pytest.approx(0.45)
        assert profile.mastery_map["topic_b"].mastery_level == pytest.approx(0.2)

    def test_database_created_on_init(self, tmp_path):
        storage = tmp_path / "profiles.sqlite3"
        assert not storage.exists()

        StudentService(storage_path=str(storage))

        assert storage.exists()
        assert _row_count(storage) == 0

    def test_parent_directories_created(self, tmp_path):
        storage = tmp_path / "deep" / "nested" / "dir" / "profiles.sqlite3"
        svc = StudentService(storage_path=str(storage))
        svc.update_mastery("topic", correct=True)

        assert storage.exists()

    def test_any_file_name_is_a_sqlite_database(self, tmp_path):
        """The JSON backend is gone: a .json path is just a SQLite file name."""
        storage = tmp_path / "profiles.json"
        svc = StudentService(storage_path=str(storage))
        svc.update_mastery("topic", correct=True)

        assert _row_count(storage) == 1

    def test_multiple_students_persisted(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True, student_id="alice")
        svc.update_mastery("topic", correct=False, student_id="bob")

        svc2 = StudentService(storage_path=storage)
        assert "topic" in svc2.get_profile("alice").mastery_map
        assert "topic" in svc2.get_profile("bob").mastery_map
        assert _row_count(Path(storage)) == 2

    def test_timestamps_survive_round_trip(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True)
        original = svc.get_profile("default")
        original_updated = original.updated_at

        svc2 = StudentService(storage_path=storage)
        reloaded = svc2.get_profile("default")

        delta = abs((reloaded.updated_at - original_updated).total_seconds())
        assert delta < 1.0

    def test_attempt_counts_survive_round_trip(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        svc = StudentService(storage_path=storage)

        svc.update_mastery("topic", correct=True)
        svc.update_mastery("topic", correct=False)

        svc2 = StudentService(storage_path=storage)
        profile = svc2.get_profile("default")
        mastery = profile.mastery_map["topic"]

        assert mastery.attempts == 2
        assert mastery.correct_attempts == 1

    def test_loads_rows_written_by_seed_script(self, tmp_path):
        """Rows written like scripts/seed_student_profile.py (json.dumps) load correctly."""
        storage = tmp_path / "profiles.sqlite3"
        svc = StudentService(storage_path=str(storage))
        seeded = {
            "student_id": "demo",
            "mastery_map": {
                "Cold War": {
                    "concept_name": "Cold War",
                    "mastery_level": 0.42,
                    "attempts": 5,
                    "correct_attempts": 2,
                    "last_assessed": "2025-06-01T10:00:00",
                }
            },
            "overall_ability": 0.42,
            "created_at": "2025-01-01T12:00:00",
            "updated_at": "2025-06-01T10:00:00",
        }
        with sqlite3.connect(storage) as conn:
            conn.execute(
                "INSERT INTO student_profiles (student_id, profile_json, updated_at) "
                "VALUES (?, ?, ?)",
                ("demo", json.dumps(seeded), seeded["updated_at"]),
            )

        profile = svc.get_profile("demo")

        assert profile.mastery_map["Cold War"].mastery_level == pytest.approx(0.42)
        assert profile.mastery_map["Cold War"].attempts == 5
        assert profile.created_at.year == 2025


# ===========================================================================
# TestReadThroughAndAtomicity
# ===========================================================================


@pytest.mark.unit
class TestReadThroughAndAtomicity:
    """Instances sharing one database see each other's writes and never lose updates."""

    def test_instances_see_each_others_writes(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        worker_a = StudentService(storage_path=storage)
        worker_b = StudentService(storage_path=storage)

        # worker_b reads first, as a long-running worker would
        assert worker_b.get_profile("alice").mastery_map == {}

        worker_a.update_mastery("topic", correct=True, student_id="alice")

        assert worker_b.get_profile("alice").mastery_map["topic"].attempts == 1

    def test_updates_from_two_instances_accumulate(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        worker_a = StudentService(storage_path=storage)
        worker_b = StudentService(storage_path=storage)

        worker_a.update_mastery("topic", correct=True, student_id="alice")
        worker_b.update_mastery("topic", correct=False, student_id="alice")
        worker_a.update_mastery("topic", correct=True, student_id="alice")

        mastery = worker_b.get_profile("alice").mastery_map["topic"]
        assert mastery.attempts == 3
        assert mastery.correct_attempts == 2

    def test_concurrent_updates_from_two_instances_are_not_lost(self, tmp_path):
        storage = str(tmp_path / "profiles.sqlite3")
        services = [StudentService(storage_path=storage) for _ in range(2)]
        errors: list[str] = []

        def answer(service: StudentService) -> None:
            try:
                for _ in range(10):
                    service.update_mastery("topic", correct=True, student_id="shared")
            except Exception as e:  # pragma: no cover - reported by the assertion below
                errors.append(repr(e))

        threads = [
            threading.Thread(target=answer, args=(svc,)) for svc in services for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert services[0].get_profile("shared").mastery_map["topic"].attempts == 40

    def test_schema_created_once_and_updates_use_one_transaction(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path)
        statements: list[str] = []
        open_connection = svc._open_connection

        def traced_connection() -> sqlite3.Connection:
            conn = open_connection()
            conn.set_trace_callback(statements.append)
            return conn

        monkeypatch.setattr(svc, "_open_connection", traced_connection)

        svc.update_mastery("topic", correct=True)
        svc.update_mastery("topic", correct=False)
        svc.reset_profile("default")

        assert not any("CREATE TABLE" in s or "journal_mode" in s for s in statements)
        assert sum(s.startswith("BEGIN IMMEDIATE") for s in statements) == 3
        assert all(
            "ON CONFLICT(student_id) DO UPDATE" in s
            for s in statements
            if s.lstrip().startswith("INSERT")
        )


# ===========================================================================
# TestStorageErrors
# ===========================================================================


@pytest.mark.unit
class TestStorageErrors:
    """Storage failures raise StudentStorageError instead of being swallowed."""

    def test_non_sqlite_file_raises(self, tmp_path):
        storage = tmp_path / "profiles.sqlite3"
        storage.write_text('{"legacy": "json profiles"}')

        with pytest.raises(StudentStorageError):
            StudentService(storage_path=str(storage))

    def test_corrupt_profile_row_raises(self, tmp_path):
        storage = tmp_path / "profiles.sqlite3"
        svc = StudentService(storage_path=str(storage))
        with sqlite3.connect(storage) as conn:
            conn.execute(
                "INSERT INTO student_profiles (student_id, profile_json, updated_at) "
                "VALUES ('broken', 'not json', '2025-01-01T00:00:00')"
            )

        with pytest.raises(StudentStorageError, match="broken"):
            svc.get_profile("broken")
        with pytest.raises(StudentStorageError):
            svc.update_mastery("topic", correct=True, student_id="broken")

    def test_unavailable_database_raises_on_update(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path)

        def fail_to_connect() -> sqlite3.Connection:
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr(svc, "_open_connection", fail_to_connect)

        with pytest.raises(StudentStorageError, match="unable to open database file"):
            svc.update_mastery("topic", correct=True)
        with pytest.raises(StudentStorageError):
            svc.get_profile("default")

    def test_failed_save_raises_and_rolls_back(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path)
        svc.update_mastery("topic", correct=True)

        def fail_to_write(conn, profile) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(svc, "_write_profile", fail_to_write)

        with pytest.raises(StudentStorageError, match="disk I/O error"):
            svc.update_mastery("topic", correct=True)

        monkeypatch.undo()
        mastery = svc.get_profile("default").mastery_map["topic"]
        assert mastery.attempts == 1  # the failed update left no partial write

    def test_storage_error_is_not_a_value_error(self):
        # Routes map ValueError to 404; a storage failure must surface as a server error
        assert not issubclass(StudentStorageError, ValueError)


# ===========================================================================
# TestConceptValidation
# ===========================================================================


@pytest.mark.unit
class TestConceptValidation:
    """Concept validation with an injectable validator."""

    def test_no_validator_accepts_any_concept(self, tmp_path):
        svc = _make_service(tmp_path)

        resp = svc.update_mastery("anything at all", correct=True)

        assert resp.total_attempts == 1

    def test_validator_rejects_unknown_concept(self, tmp_path):
        svc = _make_service(tmp_path, concept_validator=lambda concept, subject_id: False)

        with pytest.raises(UnknownConceptError, match="NOT_A_CONCEPT"):
            svc.update_mastery("NOT_A_CONCEPT", correct=True, student_id="eve")

        assert "NOT_A_CONCEPT" not in svc.get_profile("eve").mastery_map
        assert _row_count(tmp_path / "profiles.sqlite3") == 0

    def test_validator_receives_concept_and_subject(self, tmp_path):
        calls: list[tuple[str, str | None]] = []

        def validator(concept: str, subject_id: str | None) -> bool:
            calls.append((concept, subject_id))
            return True

        svc = _make_service(tmp_path, concept_validator=validator)
        svc.update_mastery("Supply", correct=True, subject_id="economics")
        svc.update_mastery("Civil War", correct=False)

        assert calls == [("Supply", "economics"), ("Civil War", None)]

    def test_validator_errors_propagate_without_writing(self, tmp_path):
        def unavailable(concept: str, subject_id: str | None) -> bool:
            raise Neo4jConnectionError("graph down")

        svc = _make_service(tmp_path, concept_validator=unavailable)

        with pytest.raises(Neo4jConnectionError):
            svc.update_mastery("topic", correct=True)
        assert _row_count(tmp_path / "profiles.sqlite3") == 0

    def test_kg_validator_checks_the_subject_graph(self):
        adapter = MagicMock()
        adapter.concept_exists.return_value = True

        with patch.object(
            student_service_module, "get_neo4j_adapter", return_value=adapter
        ) as factory:
            assert kg_concept_exists("The Civil War", "us_history") is True
            assert kg_concept_exists("Supply", None) is True

        assert [c.args for c in factory.call_args_list] == [("us_history",), (None,)]
        adapter.concept_exists.assert_any_call("The Civil War")

    def test_kg_validator_reports_missing_concepts(self):
        adapter = MagicMock()
        adapter.concept_exists.return_value = False

        with patch.object(student_service_module, "get_neo4j_adapter", return_value=adapter):
            assert kg_concept_exists("TOTALLY_FAKE", "us_history") is False

    def test_kg_validator_wraps_graph_errors(self):
        adapter = MagicMock()
        adapter.concept_exists.side_effect = RuntimeError("ServiceUnavailable")

        with patch.object(student_service_module, "get_neo4j_adapter", return_value=adapter):
            with pytest.raises(Neo4jConnectionError, match="ServiceUnavailable"):
                kg_concept_exists("Civil War", "us_history")

    def test_kg_validator_rejects_unknown_subject(self):
        with pytest.raises(KeyError):
            kg_concept_exists("Civil War", "no_such_subject")

    @pytest.mark.parametrize("enabled", [False, True])
    def test_get_student_service_validation_is_opt_in(self, tmp_path, monkeypatch, enabled):
        from backend.app.core.settings import settings

        monkeypatch.setattr(settings, "student_profiles_db", str(tmp_path / "app.sqlite3"))
        monkeypatch.setattr(settings, "student_validate_concepts", enabled)
        monkeypatch.setattr(student_service_module, "_student_service", None)

        service = get_student_service()

        assert service is get_student_service()
        assert service.storage_path == tmp_path / "app.sqlite3"
        if enabled:
            assert service.concept_validator is kg_concept_exists
        else:
            assert service.concept_validator is None


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
        svc.save_profile(profile)
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

    def test_round_trip_preserves_bkt(self, tmp_path):
        """BKT fields survive SQLite serialization and reload."""
        storage = str(tmp_path / "profiles.sqlite3")
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
