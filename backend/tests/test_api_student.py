"""
Route tests for the /student/* endpoints.

The student service is mocked; these tests cover request validation, the service
calls the routes make, and error handling.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.app.main import app
from backend.app.student.models import (
    MasteryUpdateResponse,
    StudentProfileResponse,
    TargetDifficultyResponse,
)

INVALID_STUDENT_IDS = ["", "has space", "../../etc/passwd", "a" * 65, "semi;colon", "émile"]


@pytest.fixture
def student_service():
    service = MagicMock()
    with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
        yield service


def _profile(student_id: str = "default", **mastery: float) -> StudentProfileResponse:
    return StudentProfileResponse(
        student_id=student_id,
        overall_ability=0.3,
        mastery_levels=mastery,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.unit
class TestUpdateMasteryEndpoint:
    """Tests for POST /api/v1/student/mastery."""

    def test_update_mastery_returns_bkt_result(self, client, student_service):
        student_service.update_mastery.return_value = MasteryUpdateResponse(
            concept="Photosynthesis",
            previous_mastery=0.3,
            new_mastery=0.484,
            target_difficulty="medium",
            total_attempts=1,
            bkt_p_known=0.4839,
        )

        response = client.post(
            "/api/v1/student/mastery",
            params={"student_id": "learner-1.a"},
            json={"concept": "  Photosynthesis  ", "correct": True},
        )

        assert response.status_code == 200
        assert response.json() == {
            "concept": "Photosynthesis",
            "previous_mastery": 0.3,
            "new_mastery": 0.484,
            "target_difficulty": "medium",
            "total_attempts": 1,
            "bkt_p_known": 0.4839,
        }
        student_service.update_mastery.assert_called_once_with(
            concept="Photosynthesis", correct=True, student_id="learner-1.a"
        )

    def test_update_mastery_defaults_to_default_student(self, client, student_service):
        student_service.update_mastery.return_value = MasteryUpdateResponse(
            concept="Tariffs",
            previous_mastery=0.3,
            new_mastery=0.2,
            target_difficulty="easy",
            total_attempts=1,
            bkt_p_known=None,
        )

        response = client.post(
            "/api/v1/student/mastery", json={"concept": "Tariffs", "correct": False}
        )

        assert response.status_code == 200
        student_service.update_mastery.assert_called_once_with(
            concept="Tariffs", correct=False, student_id="default"
        )

    @pytest.mark.parametrize("concept", ["", "   ", "x" * 201])
    def test_update_mastery_rejects_invalid_concept(self, client, student_service, concept):
        response = client.post(
            "/api/v1/student/mastery", json={"concept": concept, "correct": True}
        )

        assert response.status_code == 422
        student_service.update_mastery.assert_not_called()

    def test_update_mastery_requires_correct_flag(self, client, student_service):
        response = client.post("/api/v1/student/mastery", json={"concept": "Tariffs"})

        assert response.status_code == 422
        student_service.update_mastery.assert_not_called()

    @pytest.mark.parametrize("student_id", INVALID_STUDENT_IDS)
    def test_update_mastery_rejects_invalid_student_id(self, client, student_service, student_id):
        response = client.post(
            "/api/v1/student/mastery",
            params={"student_id": student_id},
            json={"concept": "Tariffs", "correct": True},
        )

        assert response.status_code == 422
        student_service.update_mastery.assert_not_called()

    def test_update_mastery_failure_is_500_without_details(self, client, student_service):
        student_service.update_mastery.side_effect = RuntimeError(
            "disk I/O error at /srv/private/student_profiles.sqlite3"
        )

        response = client.post(
            "/api/v1/student/mastery", json={"concept": "Tariffs", "correct": True}
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "An internal error occurred"}

    def test_docs_describe_bkt_update(self):
        operation = app.openapi()["paths"]["/api/v1/student/mastery"]["post"]

        assert "Bayesian Knowledge Tracing" in operation["description"]
        assert {"401", "422", "429"} <= set(operation["responses"])


@pytest.mark.unit
class TestResetProfileEndpoint:
    """Tests for POST /api/v1/student/reset."""

    def test_reset_profile(self, client, student_service):
        student_service.reset_profile.return_value = _profile("learner_1")

        response = client.post("/api/v1/student/reset", params={"student_id": "learner_1"})

        assert response.status_code == 200
        assert response.json()["student_id"] == "learner_1"
        assert response.json()["mastery_levels"] == {}
        student_service.reset_profile.assert_called_once_with("learner_1")

    def test_reset_defaults_to_default_student(self, client, student_service):
        student_service.reset_profile.return_value = _profile()

        response = client.post("/api/v1/student/reset")

        assert response.status_code == 200
        student_service.reset_profile.assert_called_once_with("default")

    @pytest.mark.parametrize("student_id", INVALID_STUDENT_IDS)
    def test_reset_rejects_invalid_student_id(self, client, student_service, student_id):
        response = client.post("/api/v1/student/reset", params={"student_id": student_id})

        assert response.status_code == 422
        student_service.reset_profile.assert_not_called()

    def test_reset_failure_is_500(self, client, student_service):
        student_service.reset_profile.side_effect = RuntimeError("database is locked")

        response = client.post("/api/v1/student/reset")

        assert response.status_code == 500
        assert response.json() == {"detail": "An internal error occurred"}


@pytest.mark.unit
class TestReadStudentEndpoints:
    """Tests for the read-only student endpoints."""

    def test_profile_passes_student_id(self, client, student_service):
        student_service.get_profile_response.return_value = _profile("learner_1", Tariffs=0.6)

        response = client.get("/api/v1/student/profile", params={"student_id": "learner_1"})

        assert response.status_code == 200
        assert response.json()["mastery_levels"] == {"Tariffs": 0.6}
        student_service.get_profile_response.assert_called_once_with("learner_1")

    @pytest.mark.parametrize("student_id", INVALID_STUDENT_IDS)
    def test_profile_rejects_invalid_student_id(self, client, student_service, student_id):
        response = client.get("/api/v1/student/profile", params={"student_id": student_id})

        assert response.status_code == 422
        student_service.get_profile_response.assert_not_called()

    def test_target_difficulty_trims_concept(self, client, student_service):
        student_service.get_target_difficulty.return_value = TargetDifficultyResponse(
            concept="Tariffs", mastery_level=0.8, target_difficulty="hard"
        )

        response = client.get("/api/v1/student/target-difficulty", params={"concept": "  Tariffs "})

        assert response.status_code == 200
        assert response.json()["target_difficulty"] == "hard"
        student_service.get_target_difficulty.assert_called_once_with("Tariffs", "default")

    @pytest.mark.parametrize("params", [{}, {"concept": "   "}, {"concept": "x" * 201}])
    def test_target_difficulty_requires_valid_concept(self, client, student_service, params):
        response = client.get("/api/v1/student/target-difficulty", params=params)

        assert response.status_code == 422
        student_service.get_target_difficulty.assert_not_called()

    def test_all_difficulties(self, client, student_service):
        student_service.get_all_target_difficulties.return_value = {"Tariffs": "medium"}

        response = client.get(
            "/api/v1/student/all-difficulties", params={"student_id": "learner_1"}
        )

        assert response.status_code == 200
        assert response.json() == {"Tariffs": "medium"}
        student_service.get_all_target_difficulties.assert_called_once_with("learner_1")

    def test_all_difficulties_rejects_invalid_student_id(self, client, student_service):
        response = client.get(
            "/api/v1/student/all-difficulties", params={"student_id": "not valid"}
        )

        assert response.status_code == 422
        student_service.get_all_target_difficulties.assert_not_called()
