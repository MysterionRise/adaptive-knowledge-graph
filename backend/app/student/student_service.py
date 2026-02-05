"""
Student service for managing student profiles and mastery tracking.

Implements a simple JSON file-based persistence for student profiles,
suitable for demos and small-scale deployments.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from loguru import logger

from backend.app.core.settings import settings
from backend.app.student.models import (
    ConceptMastery,
    MasteryUpdateResponse,
    StudentProfile,
    StudentProfileResponse,
    TargetDifficultyResponse,
)


class StudentService:
    """
    Service for managing student profiles and mastery tracking.

    Uses JSON file persistence at data/processed/student_profiles.json.
    Thread-safe for single-process usage (demo/dev scenarios).
    """

    # Mastery update parameters
    CORRECT_DELTA = 0.15  # Increase on correct answer
    INCORRECT_DELTA = 0.10  # Decrease on incorrect answer (absolute value)
    MIN_MASTERY = 0.1  # Floor for mastery level
    MAX_MASTERY = 1.0  # Cap for mastery level

    def __init__(self, storage_path: str | None = None):
        """Initialize student service with optional custom storage path."""
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path(settings.data_processed_dir) / "student_profiles.json"

        self._profiles: dict[str, StudentProfile] = {}
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Load profiles from JSON file."""
        try:
            if self.storage_path.exists():
                with open(self.storage_path) as f:
                    data = json.load(f)
                    for student_id, profile_data in data.items():
                        # Convert mastery_map entries to ConceptMastery objects
                        if "mastery_map" in profile_data:
                            mastery_map = {}
                            for concept, mastery_data in profile_data["mastery_map"].items():
                                if isinstance(mastery_data, dict):
                                    mastery_map[concept] = ConceptMastery(**mastery_data)
                                else:
                                    # Legacy format: just a float
                                    mastery_map[concept] = ConceptMastery(
                                        concept_name=concept,
                                        mastery_level=mastery_data,
                                    )
                            profile_data["mastery_map"] = mastery_map

                        # Parse datetime fields
                        for dt_field in ["created_at", "updated_at"]:
                            if dt_field in profile_data and isinstance(profile_data[dt_field], str):
                                profile_data[dt_field] = datetime.fromisoformat(
                                    profile_data[dt_field]
                                )

                        self._profiles[student_id] = StudentProfile(**profile_data)
                logger.info(f"Loaded {len(self._profiles)} student profiles")
            else:
                logger.info("No existing profiles file, starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load profiles, starting fresh: {e}")
            self._profiles = {}

    def _save_profiles(self) -> None:
        """Save profiles to JSON file."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to serializable format
            data = {}
            for student_id, profile in self._profiles.items():
                profile_dict = profile.model_dump()
                # Convert datetime to ISO format
                for dt_field in ["created_at", "updated_at"]:
                    if profile_dict.get(dt_field):
                        profile_dict[dt_field] = profile_dict[dt_field].isoformat()
                # Convert mastery map
                mastery_map_serialized = {}
                for concept, mastery in profile_dict.get("mastery_map", {}).items():
                    if isinstance(mastery, dict) and mastery.get("last_assessed"):
                        mastery["last_assessed"] = (
                            mastery["last_assessed"].isoformat()
                            if isinstance(mastery["last_assessed"], datetime)
                            else mastery["last_assessed"]
                        )
                    mastery_map_serialized[concept] = mastery
                profile_dict["mastery_map"] = mastery_map_serialized
                data[student_id] = profile_dict

            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

            logger.debug(f"Saved {len(self._profiles)} profiles to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save profiles: {e}")

    def get_profile(self, student_id: str = "default") -> StudentProfile:
        """Get or create a student profile."""
        if student_id not in self._profiles:
            self._profiles[student_id] = StudentProfile(
                student_id=student_id,
                overall_ability=settings.student_initial_mastery,
            )
            self._save_profiles()

        return self._profiles[student_id]

    def get_profile_response(self, student_id: str = "default") -> StudentProfileResponse:
        """Get student profile as API response format."""
        profile = self.get_profile(student_id)

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

    def update_mastery(
        self,
        concept: str,
        correct: bool,
        student_id: str = "default",
    ) -> MasteryUpdateResponse:
        """
        Update mastery level after an answer.

        Algorithm:
        - Correct answer: +0.15 (capped at 1.0)
        - Incorrect answer: -0.10 (floor at 0.1)
        """
        profile = self.get_profile(student_id)

        # Get or create concept mastery
        if concept not in profile.mastery_map:
            profile.mastery_map[concept] = ConceptMastery(
                concept_name=concept,
                mastery_level=settings.student_initial_mastery,
            )

        mastery = profile.mastery_map[concept]
        previous_mastery = mastery.mastery_level

        # Update mastery level
        if correct:
            delta = self.CORRECT_DELTA
            mastery.correct_attempts += 1
        else:
            delta = -self.INCORRECT_DELTA

        new_level = max(self.MIN_MASTERY, min(self.MAX_MASTERY, mastery.mastery_level + delta))

        mastery.mastery_level = new_level
        mastery.attempts += 1
        mastery.last_assessed = datetime.now()

        # Update overall ability (running average of all concepts)
        if profile.mastery_map:
            total_mastery = sum(m.mastery_level for m in profile.mastery_map.values())
            profile.overall_ability = total_mastery / len(profile.mastery_map)

        profile.updated_at = datetime.now()

        # Persist changes
        self._save_profiles()

        # Get new target difficulty
        target_difficulty = profile.get_target_difficulty(concept)

        logger.info(
            f"Updated mastery for {concept}: {previous_mastery:.2f} -> {new_level:.2f} "
            f"(correct={correct}, target_difficulty={target_difficulty})"
        )

        return MasteryUpdateResponse(
            concept=concept,
            previous_mastery=round(previous_mastery, 3),
            new_mastery=round(new_level, 3),
            target_difficulty=target_difficulty,
            total_attempts=mastery.attempts,
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
        self._profiles[student_id] = StudentProfile(
            student_id=student_id,
            overall_ability=settings.student_initial_mastery,
        )
        self._save_profiles()

        logger.info(f"Reset profile for student {student_id}")

        return self.get_profile_response(student_id)

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
    """Get global student service instance."""
    global _student_service
    if _student_service is None:
        _student_service = StudentService()
    return _student_service
