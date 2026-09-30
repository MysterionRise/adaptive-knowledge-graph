"""
Student service for managing student profiles and mastery tracking.

Profiles are stored in SQLite (STUDENT_PROFILES_DB). Every call reads the
database, so several workers or service instances sharing one file always see
each other's writes. Mastery updates run as a single read-modify-write
transaction (BEGIN IMMEDIATE), so concurrent updates are never lost. Storage
failures raise StudentStorageError instead of being swallowed.
"""

import contextlib
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import ValidationError

from backend.app.core.exceptions import AdaptiveKGException, Neo4jConnectionError
from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.kg.neo4j_adapter import get_neo4j_adapter
from backend.app.student.models import (
    ConceptMastery,
    MasteryUpdateResponse,
    StudentProfile,
    StudentProfileResponse,
    TargetDifficultyResponse,
)

# (concept, subject_id) -> True if the concept exists; subject_id None = default subject
ConceptValidator = Callable[[str, str | None], bool]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS student_profiles (
    student_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_UPSERT = """
INSERT INTO student_profiles (student_id, profile_json, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(student_id) DO UPDATE SET
    profile_json = excluded.profile_json,
    updated_at = excluded.updated_at
"""


class StudentStorageError(AdaptiveKGException):
    """Reading or writing the learner profile store failed."""


class UnknownConceptError(AdaptiveKGException):
    """The concept is not part of the subject's knowledge graph."""


def kg_concept_exists(concept: str, subject_id: str | None = None) -> bool:
    """
    Default concept validator: check the subject's knowledge graph.

    Matching is case-insensitive and ignores a leading "The".

    Raises:
        KeyError: If subject_id is not a configured subject
        Neo4jConnectionError: If the knowledge graph cannot be queried
    """
    get_subject(subject_id)  # raises KeyError for unknown subjects
    try:
        return get_neo4j_adapter(subject_id).concept_exists(concept)
    except Exception as e:
        raise Neo4jConnectionError(f"Could not validate concept against the graph: {e}") from e


class StudentService:
    """
    Service for managing student profiles and mastery tracking.

    Args:
        storage_path: SQLite database file (defaults to STUDENT_PROFILES_DB)
        concept_validator: Called as ``validator(concept, subject_id)`` before a mastery
            update; returning False raises UnknownConceptError. None disables validation.
    """

    # Mastery update parameters
    CORRECT_DELTA = 0.15  # Increase on correct answer
    INCORRECT_DELTA = 0.10  # Decrease on incorrect answer (absolute value)
    MIN_MASTERY = 0.1  # Floor for mastery level
    MAX_MASTERY = 1.0  # Cap for mastery level

    BUSY_TIMEOUT_SECONDS = 10.0  # How long a writer waits for another writer's lock

    def __init__(
        self,
        storage_path: str | Path | None = None,
        concept_validator: ConceptValidator | None = None,
    ):
        """Initialize the service and create the SQLite schema if needed."""
        self.storage_path = Path(storage_path or settings.student_profiles_db)
        self.concept_validator = concept_validator
        self._initialize_storage()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        # isolation_level=None: autocommit; write transactions are explicit (BEGIN IMMEDIATE)
        return sqlite3.connect(
            self.storage_path, timeout=self.BUSY_TIMEOUT_SECONDS, isolation_level=None
        )

    @contextmanager
    def _connect(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Open a connection; with write=True the block runs in one IMMEDIATE transaction."""
        conn: sqlite3.Connection | None = None
        try:
            conn = self._open_connection()
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.execute("COMMIT")
        except sqlite3.Error as e:
            self._rollback(conn)
            raise StudentStorageError(
                f"Learner profile storage failed ({self.storage_path}): {e}"
            ) from e
        except BaseException:
            self._rollback(conn)
            raise
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _rollback(conn: sqlite3.Connection | None) -> None:
        if conn is not None and conn.in_transaction:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")

    def _initialize_storage(self) -> None:
        """Create the database file and schema once per service instance."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StudentStorageError(
                f"Cannot create learner profile directory {self.storage_path.parent}: {e}"
            ) from e
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_SCHEMA)

    @staticmethod
    def _read_profile(conn: sqlite3.Connection, student_id: str) -> StudentProfile | None:
        row = conn.execute(
            "SELECT profile_json FROM student_profiles WHERE student_id = ?", (student_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return StudentProfile.model_validate_json(row[0])
        except ValidationError as e:
            raise StudentStorageError(f"Stored profile for {student_id!r} is invalid: {e}") from e

    @staticmethod
    def _write_profile(conn: sqlite3.Connection, profile: StudentProfile) -> None:
        conn.execute(
            _UPSERT,
            (profile.student_id, profile.model_dump_json(), profile.updated_at.isoformat()),
        )

    @staticmethod
    def _new_profile(student_id: str) -> StudentProfile:
        return StudentProfile(
            student_id=student_id,
            overall_ability=settings.student_initial_mastery,
        )

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def get_profile(self, student_id: str = "default") -> StudentProfile:
        """
        Read a student's profile from storage.

        Unknown students get a fresh profile; it is only persisted once it changes.
        """
        with self._connect() as conn:
            profile = self._read_profile(conn, student_id)
        return profile if profile is not None else self._new_profile(student_id)

    def save_profile(self, profile: StudentProfile) -> None:
        """Insert or replace a whole profile in one atomic upsert."""
        with self._connect(write=True) as conn:
            self._write_profile(conn, profile)
        logger.debug(f"Saved profile {profile.student_id} to {self.storage_path}")

    def get_profile_response(self, student_id: str = "default") -> StudentProfileResponse:
        """Get student profile as API response format."""
        return self._to_response(self.get_profile(student_id))

    @staticmethod
    def _to_response(profile: StudentProfile) -> StudentProfileResponse:
        # Extract mastery levels as simple dict
        mastery_levels = {
            concept: mastery.mastery_level for concept, mastery in profile.mastery_map.items()
        }

        return StudentProfileResponse(
            student_id=profile.student_id,
            overall_ability=profile.overall_ability,
            mastery_levels=mastery_levels,
            updated_at=profile.updated_at,
        )

    # ------------------------------------------------------------------
    # Mastery
    # ------------------------------------------------------------------

    @staticmethod
    def _update_mastery_linear(mastery_level: float, correct: bool) -> float:
        """Linear mastery update: +0.15 for correct, -0.10 for incorrect."""
        if correct:
            delta = StudentService.CORRECT_DELTA
        else:
            delta = -StudentService.INCORRECT_DELTA
        return mastery_level + delta

    @staticmethod
    def _update_mastery_bkt(mastery: ConceptMastery, correct: bool) -> float:
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

    def _apply_answer(self, profile: StudentProfile, concept: str, correct: bool) -> float:
        """Apply one answer to the profile in place; returns the previous mastery level."""
        if concept not in profile.mastery_map:
            profile.mastery_map[concept] = ConceptMastery(
                concept_name=concept,
                mastery_level=settings.student_initial_mastery,
            )

        mastery = profile.mastery_map[concept]
        previous_mastery = mastery.mastery_level

        if correct:
            mastery.correct_attempts += 1

        if settings.student_bkt_enabled:
            # Bootstrap bkt_p_known from mastery_level if not yet set
            if mastery.bkt_p_known is None:
                mastery.bkt_p_known = mastery.mastery_level

            mastery.bkt_p_known = self._update_mastery_bkt(mastery, correct)
            # Map bkt_p_known to mastery_level, clamped to [0.1, 1.0]
            new_level = max(self.MIN_MASTERY, min(self.MAX_MASTERY, mastery.bkt_p_known))
        else:
            new_level = max(
                self.MIN_MASTERY,
                min(self.MAX_MASTERY, self._update_mastery_linear(mastery.mastery_level, correct)),
            )

        mastery.mastery_level = new_level
        mastery.attempts += 1
        mastery.last_assessed = datetime.now()

        # Overall ability is the average mastery across tracked concepts
        total_mastery = sum(m.mastery_level for m in profile.mastery_map.values())
        profile.overall_ability = total_mastery / len(profile.mastery_map)
        profile.updated_at = datetime.now()

        return previous_mastery

    def update_mastery(
        self,
        concept: str,
        correct: bool,
        student_id: str = "default",
        subject_id: str | None = None,
    ) -> MasteryUpdateResponse:
        """
        Update mastery level after an answer.

        Dispatches to BKT or linear model based on settings.student_bkt_enabled.

        Args:
            concept: Concept that the answered question tests
            correct: Whether the answer was correct
            student_id: Student identifier
            subject_id: Subject whose knowledge graph the validator checks
                (None = default subject)

        Raises:
            UnknownConceptError: If the concept validator rejects the concept
            StudentStorageError: If the profile cannot be read or saved
        """
        if self.concept_validator is not None and not self.concept_validator(concept, subject_id):
            raise UnknownConceptError(
                f"Concept {concept!r} is not in the knowledge graph "
                f"(subject: {subject_id or 'default'})"
            )

        # Read, update and save in one IMMEDIATE transaction: concurrent writers
        # (threads, workers or other instances) are serialised and no update is lost.
        with self._connect(write=True) as conn:
            profile = self._read_profile(conn, student_id) or self._new_profile(student_id)
            previous_mastery = self._apply_answer(profile, concept, correct)
            self._write_profile(conn, profile)

        mastery = profile.mastery_map[concept]
        target_difficulty = profile.get_target_difficulty(concept)

        logger.info(
            f"Updated mastery for {concept}: {previous_mastery:.2f} -> "
            f"{mastery.mastery_level:.2f} (correct={correct}, "
            f"target_difficulty={target_difficulty})"
        )

        return MasteryUpdateResponse(
            concept=concept,
            previous_mastery=round(previous_mastery, 3),
            new_mastery=round(mastery.mastery_level, 3),
            target_difficulty=target_difficulty,
            total_attempts=mastery.attempts,
            bkt_p_known=round(mastery.bkt_p_known, 4) if mastery.bkt_p_known is not None else None,
        )

    def get_target_difficulty(
        self,
        concept: str,
        student_id: str = "default",
    ) -> TargetDifficultyResponse:
        """Get recommended difficulty for a concept based on student mastery."""
        profile = self.get_profile(student_id)
        mastery = profile.get_mastery(concept)
        target = profile.get_target_difficulty(concept)

        return TargetDifficultyResponse(
            concept=concept,
            mastery_level=round(mastery, 3),
            target_difficulty=target,
        )

    def reset_profile(self, student_id: str = "default") -> StudentProfileResponse:
        """Reset a student profile to initial state (for demo purposes)."""
        profile = self._new_profile(student_id)
        self.save_profile(profile)

        logger.info(f"Reset profile for student {student_id}")

        return self._to_response(profile)

    def get_all_target_difficulties(
        self,
        student_id: str = "default",
    ) -> dict[str, Literal["easy", "medium", "hard"]]:
        """Get target difficulties for all tracked concepts."""
        profile = self.get_profile(student_id)

        return {concept: profile.get_target_difficulty(concept) for concept in profile.mastery_map}


# Global singleton instance
_student_service: StudentService | None = None


def get_student_service() -> StudentService:
    """
    Get the application's student service.

    Concept validation against the knowledge graph is enabled with
    STUDENT_VALIDATE_CONCEPTS=true.
    """
    global _student_service
    if _student_service is None:
        _student_service = StudentService(
            concept_validator=kg_concept_exists if settings.student_validate_concepts else None
        )
    return _student_service
