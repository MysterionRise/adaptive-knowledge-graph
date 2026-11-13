"""
Tests for the /quiz endpoints.

Tests cover:
- Quiz generation with mocked LLM
- Parameter validation (topic, subject, student_id, recommendation payloads)
- Error handling (content not found 404, invalid LLM output 502, LLM outage 503)
- Adaptive quizzes and post-quiz recommendations
- The decision record in the adaptive quiz and target-difficulty responses (#306)
"""

import json
import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import (
    ContentNotFoundError,
    LLMConnectionError,
    LLMGenerationError,
    QuizGenerationError,
)
from backend.app.core.settings import settings
from backend.app.main import app
from backend.app.student.models import ConceptMastery, StudentProfile, TargetDifficultyResponse
from backend.app.student.policy import BandPolicyV1, DecisionRecord
from backend.app.student.student_service import StudentService
from backend.app.ui_payloads.quiz import Quiz, QuizOption, QuizQuestion
from backend.app.ui_payloads.recommendations import MAX_QUESTION_RESULTS, RecommendationResponse


@pytest.mark.unit
class TestQuizGenerateEndpoint:
    """Tests for POST /api/v1/quiz/generate endpoint."""

    def test_generate_quiz_success(self, client, mock_quiz_generator):
        """Test successful quiz generation."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Photosynthesis", "num_questions": 3},
            )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "id" in data
        assert "title" in data
        assert "questions" in data

        # Verify content
        assert data["title"] == "Photosynthesis Quiz"
        assert len(data["questions"]) == 2  # Mock returns 2 questions

        # Verify question structure
        question = data["questions"][0]
        assert "id" in question
        assert "text" in question
        assert "options" in question
        assert "correct_option_id" in question
        assert "explanation" in question
        assert len(question["options"]) == 4

    def test_generate_quiz_default_num_questions(self, client, mock_quiz_generator):
        """Test quiz generation with default num_questions."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Photosynthesis"},
            )

        assert response.status_code == 200
        # Generator should be called with default num_questions=3
        mock_quiz_generator.generate_from_topic.assert_called_once_with("Photosynthesis", 3)

    def test_generate_quiz_content_not_found(self, client):
        """Test 404 when no content found for topic."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = ContentNotFoundError(
            "No content found for topic: Quantum Chromodynamics"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Quantum Chromodynamics"},
            )

        assert response.status_code == 404
        assert "Topic not found or no content available" in response.json()["detail"]

    def test_generate_quiz_legacy_no_content_value_error(self, client):
        """Test 404 for the generator's legacy ValueError("No content found for ...")."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = ValueError(
            "No content found for Unknown Topic"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Unknown Topic"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Topic not found or no content available"

    def test_generate_quiz_unrelated_value_error_is_500(self, client):
        """Test that other ValueErrors are not reported as a missing topic."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = ValueError(
            "could not convert string to float: 'hard'"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Photosynthesis"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"

    def test_generate_quiz_generation_error(self, client):
        """Test 502 when the LLM output cannot be turned into a quiz."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = QuizGenerationError(
            "LLM failed to parse quiz format"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Photosynthesis"},
            )

        assert response.status_code == 502
        assert response.json()["detail"] == "Quiz generation returned an invalid response"

    def test_generate_quiz_internal_error(self, client):
        """Test 500 on unexpected errors."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = RuntimeError(
            "Unexpected database error"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Photosynthesis"},
            )

        assert response.status_code == 500

    def test_generate_quiz_with_related_concept(self, client):
        """Test that quiz questions include related concept."""
        generator = AsyncMock()
        generator.generate_from_topic.return_value = Quiz(
            id="quiz_test",
            title="Test Quiz",
            questions=[
                QuizQuestion(
                    id="q1",
                    text="Test question?",
                    options=[
                        QuizOption(id="a", text="Option A"),
                        QuizOption(id="b", text="Option B"),
                        QuizOption(id="c", text="Option C"),
                        QuizOption(id="d", text="Option D"),
                    ],
                    correct_option_id="a",
                    explanation="Test explanation",
                    related_concept="Test Concept",
                    source_chunk_id="chunk_123",
                )
            ],
        )

        with patch("backend.app.api.routes.quiz.get_quiz_generator", return_value=generator):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Test"},
            )

        assert response.status_code == 200
        data = response.json()
        question = data["questions"][0]
        assert question["related_concept"] == "Test Concept"
        assert question["source_chunk_id"] == "chunk_123"

    def test_generate_quiz_custom_num_questions(self, client, mock_quiz_generator):
        """Test quiz generation with custom number of questions."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Biology", "num_questions": 10},
            )

        assert response.status_code == 200
        mock_quiz_generator.generate_from_topic.assert_called_once_with("Biology", 10)

    def test_generate_quiz_empty_topic(self, client, mock_quiz_generator):
        """Test that empty topic is rejected by input validation."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": ""},
            )

        # Endpoint validates topic min_length=1, so empty string returns 422
        assert response.status_code == 422


@pytest.mark.unit
class TestQuizResponseModel:
    """Tests for Quiz response model structure."""

    def test_quiz_option_model(self):
        """Test QuizOption model."""
        option = QuizOption(id="a", text="Test option")
        assert option.id == "a"
        assert option.text == "Test option"

    def test_quiz_question_model(self):
        """Test QuizQuestion model."""
        question = QuizQuestion(
            id="q1",
            text="What is 2+2?",
            options=[
                QuizOption(id="a", text="3"),
                QuizOption(id="b", text="4"),
            ],
            correct_option_id="b",
            explanation="Basic arithmetic",
        )
        assert question.id == "q1"
        assert question.correct_option_id == "b"
        assert len(question.options) == 2
        assert question.related_concept is None  # Optional field

    def test_quiz_model(self):
        """Test Quiz model."""
        quiz = Quiz(
            id="quiz_001",
            title="Math Quiz",
            questions=[
                QuizQuestion(
                    id="q1",
                    text="What is 2+2?",
                    options=[
                        QuizOption(id="a", text="3"),
                        QuizOption(id="b", text="4"),
                    ],
                    correct_option_id="b",
                    explanation="Basic arithmetic",
                )
            ],
        )
        assert quiz.id == "quiz_001"
        assert quiz.title == "Math Quiz"
        assert len(quiz.questions) == 1


@pytest.mark.unit
class TestProtectedStudentEndpoints:
    """API-key behavior for protected student demo routes."""

    def test_student_profile_allows_dev_mode_without_configured_api_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        mock_service = MagicMock()
        mock_service.get_profile_response.return_value = {
            "student_id": "default",
            "overall_ability": 0.3,
            "mastery_levels": {"American Revolution": 0.4},
            "updated_at": datetime.now(UTC),
        }

        with patch("backend.app.api.routes.quiz.get_student_service", return_value=mock_service):
            response = client.get("/api/v1/student/profile")

        assert response.status_code == 200
        assert response.json()["mastery_levels"]["American Revolution"] == 0.4

    def test_student_profile_accepts_configured_api_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "demo-secret")
        mock_service = MagicMock()
        mock_service.get_profile_response.return_value = {
            "student_id": "default",
            "overall_ability": 0.3,
            "mastery_levels": {},
            "updated_at": datetime.now(UTC),
        }

        with patch("backend.app.api.routes.quiz.get_student_service", return_value=mock_service):
            response = client.get(
                "/api/v1/student/profile",
                headers={"X-API-Key": "demo-secret"},
            )

        assert response.status_code == 200

    def test_student_profile_rejects_missing_configured_api_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "demo-secret")

        response = client.get("/api/v1/student/profile")

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing API key. Include X-API-Key header."

    def test_student_profile_rejects_invalid_configured_api_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "demo-secret")

        response = client.get(
            "/api/v1/student/profile",
            headers={"X-API-Key": "wrong-key"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid API key"


QUIZ_PATHS = ["/api/v1/quiz/generate", "/api/v1/quiz/generate-adaptive"]
MALFORMED_SUBJECTS = ["US_History", "'; DROP DATABASE neo4j; --", "1history", "a" * 33]


@pytest.fixture
def student_service_stub():
    """Student service returning an 'easy' target for adaptive quizzes."""
    service = MagicMock()
    service.get_target_difficulty.return_value = TargetDifficultyResponse(
        concept="Photosynthesis", mastery_level=0.2, target_difficulty="easy"
    )
    with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
        yield service


def _failing_generator(error: Exception) -> AsyncMock:
    generator = AsyncMock()
    generator.generate_from_topic.side_effect = error
    return generator


@pytest.mark.unit
class TestQuizErrorContracts:
    """Status codes for quiz generation failures, on both quiz endpoints."""

    @pytest.mark.parametrize("path", QUIZ_PATHS)
    @pytest.mark.parametrize(
        ("error", "status_code", "detail"),
        [
            (
                ContentNotFoundError("No content found for Photosynthesis"),
                404,
                "Topic not found or no content available",
            ),
            (
                ValueError("No content found for Photosynthesis"),
                404,
                "Topic not found or no content available",
            ),
            (
                json.JSONDecodeError("Expecting value", "not json", 0),
                502,
                "Quiz generation returned an invalid response",
            ),
            (
                QuizGenerationError("LLM returned a malformed quiz"),
                502,
                "Quiz generation returned an invalid response",
            ),
            (
                LLMConnectionError("Ollama connection failed"),
                503,
                "Quiz generation service temporarily unavailable",
            ),
            (
                LLMGenerationError("Ollama returned HTTP 500"),
                503,
                "Quiz generation service temporarily unavailable",
            ),
            (ValueError("unexpected value"), 500, "An internal error occurred"),
            (RuntimeError("boom"), 500, "An internal error occurred"),
        ],
        ids=[
            "content-not-found",
            "legacy-no-content",
            "invalid-json",
            "invalid-quiz",
            "llm-unreachable",
            "llm-http-error",
            "other-value-error",
            "unexpected",
        ],
    )
    def test_generation_errors_map_to_status_codes(
        self, client, student_service_stub, path, error, status_code, detail
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator",
            return_value=_failing_generator(error),
        ):
            response = client.post(path, params={"topic": "Photosynthesis"})

        assert response.status_code == status_code
        assert response.json()["detail"] == detail

    def test_error_responses_are_declared_in_openapi(self):
        schema = app.openapi()
        for path in QUIZ_PATHS:
            responses = schema["paths"][path]["post"]["responses"]
            assert {"404", "422", "429", "502", "503"} <= set(responses)


@pytest.mark.unit
class TestQuizInputValidation:
    """Topic and subject validation on the quiz endpoints."""

    @pytest.mark.parametrize("path", QUIZ_PATHS)
    def test_unknown_subject_is_404_before_generation(
        self, client, mock_quiz_generator, student_service_stub, path
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ) as factory:
            response = client.post(path, params={"topic": "Biology", "subject": "no_such_subject"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Subject not found"
        factory.assert_not_called()

    @pytest.mark.parametrize("subject", MALFORMED_SUBJECTS)
    def test_malformed_subject_is_422(self, client, mock_quiz_generator, subject):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ) as factory:
            response = client.post(
                "/api/v1/quiz/generate", params={"topic": "Biology", "subject": subject}
            )

        assert response.status_code == 422
        factory.assert_not_called()

    def test_known_subject_is_passed_to_generator(self, client, mock_quiz_generator):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ) as factory:
            response = client.post(
                "/api/v1/quiz/generate", params={"topic": "Mitosis", "subject": "biology"}
            )

        assert response.status_code == 200
        factory.assert_called_once_with(subject_id="biology")

    @pytest.mark.parametrize("topic", ["   ", "x" * 501])
    def test_invalid_topic_is_422(self, client, mock_quiz_generator, topic):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post("/api/v1/quiz/generate", params={"topic": topic})

        assert response.status_code == 422
        mock_quiz_generator.generate_from_topic.assert_not_called()

    def test_topic_is_trimmed(self, client, mock_quiz_generator):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post("/api/v1/quiz/generate", params={"topic": "  Photosynthesis  "})

        assert response.status_code == 200
        mock_quiz_generator.generate_from_topic.assert_called_once_with("Photosynthesis", 3)

    def test_markup_in_topic_is_422_without_echo(self, client, mock_quiz_generator):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "<img src=x onerror=alert(1)>Photosynthesis"},
            )

        assert response.status_code == 422
        assert "<img" not in response.text
        assert response.json()["detail"][0]["loc"] == ["query", "topic"]
        mock_quiz_generator.generate_from_topic.assert_not_called()


@pytest.mark.unit
class TestAdaptiveQuizEndpoint:
    """Tests for POST /api/v1/quiz/generate-adaptive."""

    def test_adaptive_quiz_targets_student_difficulty(
        self, client, mock_quiz_generator, student_service_stub
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ) as factory:
            response = client.post(
                "/api/v1/quiz/generate-adaptive",
                params={
                    "topic": " Photosynthesis ",
                    "num_questions": 2,
                    "student_id": "learner_1",
                    "subject": "biology",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["adapted"] is True
        assert data["student_mastery"] == 0.2
        assert data["target_difficulty"] == "easy"
        assert data["title"] == "Photosynthesis Quiz"
        assert len(data["questions"]) == 2

        student_service_stub.get_target_difficulty.assert_called_once_with(
            "Photosynthesis", "learner_1"
        )
        factory.assert_called_once_with(subject_id="biology")
        mock_quiz_generator.generate_from_topic.assert_called_once_with(
            topic="Photosynthesis", num_questions=2, target_difficulty="easy"
        )

    def test_adaptive_quiz_uses_default_student(
        self, client, mock_quiz_generator, student_service_stub
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive", params={"topic": "Photosynthesis"}
            )

        assert response.status_code == 200
        student_service_stub.get_target_difficulty.assert_called_once_with(
            "Photosynthesis", "default"
        )

    @pytest.mark.parametrize("student_id", ["", "has space", "../etc/passwd", "a" * 65])
    def test_adaptive_quiz_rejects_invalid_student_id(
        self, client, mock_quiz_generator, student_service_stub, student_id
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis", "student_id": student_id},
            )

        assert response.status_code == 422
        student_service_stub.get_target_difficulty.assert_not_called()

    @pytest.mark.parametrize("num_questions", [0, 21])
    def test_adaptive_quiz_bounds_num_questions(
        self, client, mock_quiz_generator, student_service_stub, num_questions
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis", "num_questions": num_questions},
            )

        assert response.status_code == 422

    def test_student_service_failure_is_500(self, client, mock_quiz_generator):
        failing_service = MagicMock()
        failing_service.get_target_difficulty.side_effect = RuntimeError("database is locked")

        with (
            patch("backend.app.api.routes.quiz.get_student_service", return_value=failing_service),
            patch(
                "backend.app.api.routes.quiz.get_quiz_generator",
                return_value=mock_quiz_generator,
            ),
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive", params={"topic": "Photosynthesis"}
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"
        mock_quiz_generator.generate_from_topic.assert_not_called()


@pytest.mark.unit
class TestAdaptiveQuizAuth:
    """The adaptive quiz returns learner mastery, so it requires the API key.

    Uses the production-mode app from conftest (APP_ENV=production, API key set).
    """

    def test_missing_api_key_is_401(
        self, production_client, mock_quiz_generator, student_service_stub
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = production_client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis", "student_id": "another_learner"},
            )

        assert response.status_code == 401
        assert "student_mastery" not in response.text
        student_service_stub.get_target_difficulty.assert_not_called()
        mock_quiz_generator.generate_from_topic.assert_not_called()

    def test_wrong_api_key_is_401(
        self, production_client, mock_quiz_generator, student_service_stub
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = production_client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis"},
                headers={"X-API-Key": "not-the-key"},
            )

        assert response.status_code == 401
        student_service_stub.get_target_difficulty.assert_not_called()

    def test_valid_api_key_is_accepted(
        self, production_client, production_settings, mock_quiz_generator, student_service_stub
    ):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = production_client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis"},
                headers={"X-API-Key": production_settings.api_key},
            )

        assert response.status_code == 200
        assert response.json()["student_mastery"] == 0.2

    def test_non_adaptive_quiz_stays_public(self, production_client, mock_quiz_generator):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = production_client.post(
                "/api/v1/quiz/generate", params={"topic": "Photosynthesis"}
            )

        assert response.status_code == 200

    def test_openapi_declares_401(self):
        responses = app.openapi()["paths"]["/api/v1/quiz/generate-adaptive"]["post"]["responses"]

        assert "401" in responses


def _recommendation_payload(**overrides) -> dict:
    payload = {
        "topic": "Photosynthesis",
        "question_results": [
            {"question_id": "q1", "related_concept": "Chlorophyll", "correct": False},
            {"question_id": "q2", "related_concept": "Photosynthesis", "correct": True},
        ],
        "student_id": "learner_1",
        "subject": "biology",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def recommendation_service():
    service = MagicMock()
    service.generate_recommendations = AsyncMock(
        return_value=RecommendationResponse(
            path_type="mixed",
            score_pct=50.0,
            summary="Review chlorophyll before moving on.",
        )
    )
    with patch(
        "backend.app.api.routes.quiz.get_recommendation_service", return_value=service
    ) as factory:
        service.factory = factory
        yield service


@pytest.mark.unit
class TestQuizRecommendationsEndpoint:
    """Tests for POST /api/v1/quiz/recommendations."""

    def test_recommendations_success(self, client, recommendation_service):
        response = client.post(
            "/api/v1/quiz/recommendations",
            json=_recommendation_payload(topic="  Photosynthesis  "),
        )

        assert response.status_code == 200
        assert response.json()["path_type"] == "mixed"
        recommendation_service.factory.assert_called_once_with("biology")

        kwargs = recommendation_service.generate_recommendations.await_args.kwargs
        assert kwargs["topic"] == "Photosynthesis"
        assert kwargs["student_id"] == "learner_1"
        assert [r.related_concept for r in kwargs["question_results"]] == [
            "Chlorophyll",
            "Photosynthesis",
        ]

    def test_recommendations_accept_fifty_results(self, client, recommendation_service):
        results = [
            {"question_id": f"q{i}", "related_concept": "Photosynthesis", "correct": True}
            for i in range(MAX_QUESTION_RESULTS)
        ]

        response = client.post(
            "/api/v1/quiz/recommendations",
            json=_recommendation_payload(question_results=results),
        )

        assert response.status_code == 200

    def test_recommendations_cap_question_results(self, client, recommendation_service):
        results = [
            {"question_id": f"q{i}", "related_concept": "Photosynthesis", "correct": True}
            for i in range(MAX_QUESTION_RESULTS + 1)
        ]

        response = client.post(
            "/api/v1/quiz/recommendations",
            json=_recommendation_payload(question_results=results),
        )

        assert response.status_code == 422
        recommendation_service.factory.assert_not_called()

    def test_recommendations_unknown_subject_is_404(self, client, recommendation_service):
        response = client.post(
            "/api/v1/quiz/recommendations",
            json=_recommendation_payload(subject="no_such_subject"),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Subject not found"
        recommendation_service.factory.assert_not_called()

    def test_recommendations_default_subject(self, client, recommendation_service):
        payload = _recommendation_payload()
        del payload["subject"]

        response = client.post("/api/v1/quiz/recommendations", json=payload)

        assert response.status_code == 200
        recommendation_service.factory.assert_called_once_with(None)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"subject": "Biology!"},
            {"student_id": "../other-student"},
            {"topic": "   "},
            {"question_results": [{"question_id": "q1", "related_concept": "  ", "correct": True}]},
            {"question_results": [{"question_id": "", "related_concept": "X", "correct": True}]},
        ],
        ids=["subject", "student-id", "blank-topic", "blank-concept", "blank-question-id"],
    )
    def test_recommendations_validate_payload(self, client, recommendation_service, overrides):
        response = client.post(
            "/api/v1/quiz/recommendations", json=_recommendation_payload(**overrides)
        )

        assert response.status_code == 422
        recommendation_service.factory.assert_not_called()

    def test_recommendations_service_failure_is_500(self, client, recommendation_service):
        recommendation_service.generate_recommendations.side_effect = RuntimeError("Neo4j down")

        response = client.post("/api/v1/quiz/recommendations", json=_recommendation_payload())

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"


# =============================================================================
# Decision record (#306)
# =============================================================================

DECIDED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

DECISION_FIELDS = {
    "record_id",
    "policy_id",
    "policy_version",
    "action",
    "state_used",
    "context_used",
    "edges_used",
    "decided_at",
}

ADAPTIVE_QUIZ_FIELDS = {
    "id",
    "title",
    "questions",
    "average_difficulty",
    "student_mastery",
    "target_difficulty",
    "adapted",
    "decision",
}

# (stored mastery, band): the boundaries of the band rule with the nearest floats on either side.
BOUNDARIES = [
    (0.0, "easy"),
    (math.nextafter(0.4, 0.0), "easy"),
    (0.4, "medium"),
    (math.nextafter(0.4, 1.0), "medium"),
    (math.nextafter(0.7, 0.0), "medium"),
    (0.7, "medium"),
    (math.nextafter(0.7, 1.0), "hard"),
    (1.0, "hard"),
]


@pytest.fixture
def learner_store(tmp_path):
    """A real StudentService on a temporary SQLite file, served to the quiz routes.

    Its clock always says DECIDED_AT.
    """
    service = StudentService(storage_path=tmp_path / "profiles.sqlite3", clock=lambda: DECIDED_AT)
    with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
        yield service


def _learner(mastery: float) -> StudentProfile:
    """learner_1 with history on Photosynthesis at the given mastery."""
    return StudentProfile(
        student_id="learner_1",
        mastery_map={
            "Photosynthesis": ConceptMastery(
                concept_name="Photosynthesis", mastery_level=mastery, attempts=4, correct_attempts=3
            )
        },
    )


def _adaptive_quiz(client, generator, **params) -> dict:
    """POST /quiz/generate-adaptive for learner_1 on Photosynthesis; returns the JSON body."""
    with patch("backend.app.api.routes.quiz.get_quiz_generator", return_value=generator):
        response = client.post(
            "/api/v1/quiz/generate-adaptive",
            params={"topic": "Photosynthesis", "student_id": "learner_1", **params},
        )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.unit
class TestDecisionRecord:
    """The record of the band-v1 decision in two responses.

    ``POST /quiz/generate-adaptive`` and ``GET /student/target-difficulty`` carry it.
    ``POST /student/mastery`` also reports a target difficulty and carries no record.
    """

    @pytest.mark.parametrize(
        ("mastery", "difficulty"), [(0.2, "easy"), (0.55, "medium"), (0.75, "hard")]
    )
    def test_adaptive_quiz_carries_the_decision_record(
        self, client, mock_quiz_generator, learner_store, mastery, difficulty
    ):
        profile = _learner(mastery)
        learner_store.save_profile(profile)

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive",
                params={"topic": "Photosynthesis", "student_id": "learner_1"},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["target_difficulty"] == difficulty
        assert data["student_mastery"] == mastery
        assert data["adapted"] is True
        assert data["decision"] == {
            "record_id": profile.decide_difficulty("Photosynthesis").record_id(),
            "policy_id": "band",
            "policy_version": "v1",
            "action": {"kind": "difficulty", "difficulty": difficulty},
            "state_used": {"mastery": mastery, "mastery_source": "tracked"},
            "context_used": {"concept": "Photosynthesis"},
            "edges_used": [],
            "decided_at": "2026-11-11T12:00:00Z",
        }
        # The prompt is asked for the difficulty the record names.
        mock_quiz_generator.generate_from_topic.assert_called_once_with(
            topic="Photosynthesis", num_questions=3, target_difficulty=difficulty
        )

    def test_adaptive_quiz_record_for_a_topic_without_history(
        self, client, mock_quiz_generator, learner_store, monkeypatch
    ):
        monkeypatch.setattr(settings, "student_initial_mastery", 0.5)

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive", params={"topic": " Photosynthesis "}
            )

        assert response.status_code == 200, response.text
        decision = response.json()["decision"]
        assert set(decision) == DECISION_FIELDS
        assert decision["action"] == {"kind": "difficulty", "difficulty": "medium"}
        assert decision["state_used"] == {"mastery": 0.5, "mastery_source": "initial"}
        assert decision["context_used"] == {"concept": "Photosynthesis"}

    def test_adaptive_quiz_record_id_ignores_the_time_of_the_request(
        self, client, mock_quiz_generator, tmp_path
    ):
        """Two requests for the same learner state: one record id, two decided_at values."""
        times = iter([DECIDED_AT, datetime(2026, 11, 12, 8, 30, tzinfo=UTC)])
        service = StudentService(
            storage_path=tmp_path / "profiles.sqlite3", clock=lambda: next(times)
        )
        service.save_profile(_learner(0.55))

        with (
            patch("backend.app.api.routes.quiz.get_student_service", return_value=service),
            patch(
                "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
            ),
        ):
            first, second = (
                client.post(
                    "/api/v1/quiz/generate-adaptive",
                    params={"topic": "Photosynthesis", "student_id": "learner_1"},
                ).json()["decision"]
                for _ in range(2)
            )

        assert first["decided_at"] == "2026-11-11T12:00:00Z"
        assert second["decided_at"] == "2026-11-12T08:30:00Z"
        assert first["record_id"] == second["record_id"]
        assert {**first, "decided_at": None} == {**second, "decided_at": None}

    def test_decision_is_null_when_the_service_gives_none(
        self, client, mock_quiz_generator, student_service_stub
    ):
        """A service stub that returns no record: the field is present and null."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate-adaptive", params={"topic": "Photosynthesis"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "decision" in data
        assert data["decision"] is None
        assert data["target_difficulty"] == "easy"

    def test_target_difficulty_carries_the_decision_record(self, client, learner_store):
        stored = 0.39999999999999997  # the nearest float below 0.4
        profile = _learner(stored)
        learner_store.save_profile(profile)

        response = client.get(
            "/api/v1/student/target-difficulty",
            params={"concept": "Photosynthesis", "student_id": "learner_1"},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "concept": "Photosynthesis",
            "mastery_level": 0.4,
            "target_difficulty": "easy",
            "decision": {
                "record_id": profile.decide_difficulty("Photosynthesis").record_id(),
                "policy_id": "band",
                "policy_version": "v1",
                "action": {"kind": "difficulty", "difficulty": "easy"},
                "state_used": {"mastery": stored, "mastery_source": "tracked"},
                "context_used": {"concept": "Photosynthesis"},
                "edges_used": [],
                "decided_at": "2026-11-11T12:00:00Z",
            },
        }

    def test_target_difficulty_decision_is_null_when_the_service_gives_none(
        self, client, student_service_stub
    ):
        response = client.get(
            "/api/v1/student/target-difficulty", params={"concept": "Photosynthesis"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "concept": "Photosynthesis",
            "mastery_level": 0.2,
            "target_difficulty": "easy",
            "decision": None,
        }

    def test_openapi_documents_the_decision_record(self):
        schemas = app.openapi()["components"]["schemas"]
        record = schemas["DecisionRecordPayload"]

        assert set(record["properties"]) == DECISION_FIELDS
        assert set(record["required"]) == DECISION_FIELDS - {"edges_used"}
        assert record["properties"]["decided_at"]["format"] == "date-time"
        for model in ("AdaptiveQuiz", "TargetDifficultyResponse"):
            decision = schemas[model]["properties"]["decision"]
            assert {"$ref": "#/components/schemas/DecisionRecordPayload"} in decision["anyOf"]
            assert {"type": "null"} in decision["anyOf"]
            assert "decision" not in schemas[model]["required"]

    @pytest.mark.parametrize(("mastery", "difficulty"), BOUNDARIES)
    def test_both_routes_return_the_same_record_at_the_boundaries(
        self, client, mock_quiz_generator, learner_store, mastery, difficulty
    ):
        """The reported mastery is rounded; the record holds the stored value behind the band."""
        profile = _learner(mastery)
        learner_store.save_profile(profile)

        quiz = _adaptive_quiz(client, mock_quiz_generator)
        response = client.get(
            "/api/v1/student/target-difficulty",
            params={"concept": "Photosynthesis", "student_id": "learner_1"},
        )

        assert response.status_code == 200, response.text
        target = response.json()
        assert set(quiz) == ADAPTIVE_QUIZ_FIELDS
        assert set(target) == {"concept", "mastery_level", "target_difficulty", "decision"}
        assert quiz["target_difficulty"] == target["target_difficulty"] == difficulty
        assert quiz["student_mastery"] == target["mastery_level"] == round(mastery, 3)
        assert quiz["decision"] == target["decision"]
        assert quiz["decision"] == {
            "record_id": profile.decide_difficulty("Photosynthesis").record_id(),
            "policy_id": "band",
            "policy_version": "v1",
            "action": {"kind": "difficulty", "difficulty": difficulty},
            "state_used": {"mastery": mastery, "mastery_source": "tracked"},
            "context_used": {"concept": "Photosynthesis"},
            "edges_used": [],
            "decided_at": "2026-11-11T12:00:00Z",
        }
        mock_quiz_generator.generate_from_topic.assert_called_once_with(
            topic="Photosynthesis", num_questions=3, target_difficulty=difficulty
        )

    @pytest.mark.parametrize(
        "params", [{"num_questions": 1}, {"num_questions": 7}, {"subject": "economics"}]
    )
    def test_request_parameters_outside_the_decision_keep_the_record(
        self, client, mock_quiz_generator, learner_store, params
    ):
        learner_store.save_profile(_learner(0.55))

        plain = _adaptive_quiz(client, mock_quiz_generator)
        other = _adaptive_quiz(client, mock_quiz_generator, **params)

        assert other["decision"] == plain["decision"]
        assert other["decision"]["action"] == {"kind": "difficulty", "difficulty": "medium"}

    def test_two_learners_with_the_same_mastery_get_the_same_decision(
        self, client, mock_quiz_generator, learner_store
    ):
        """Who the learner is and how often they answered are not inputs of band-v1."""
        other = _learner(0.71).model_copy(update={"student_id": "learner_2"})
        other.mastery_map["Photosynthesis"].attempts = 40
        other.mastery_map["Photosynthesis"].correct_attempts = 1
        learner_store.save_profile(_learner(0.71))
        learner_store.save_profile(other)

        first = _adaptive_quiz(client, mock_quiz_generator)
        second = _adaptive_quiz(client, mock_quiz_generator, student_id="learner_2")

        assert first["decision"] == second["decision"]
        assert first["decision"]["action"] == {"kind": "difficulty", "difficulty": "hard"}

    def test_routes_take_the_difficulty_from_the_policy(
        self, client, mock_quiz_generator, learner_store, monkeypatch
    ):
        """With the policy replaced by one that always says "hard", both routes say "hard".

        The learner is in the easy band, so a copy of the rule in a route or in the service
        would answer "easy".
        """

        def always_hard(self, state, context):
            return DecisionRecord(
                policy_id="band",
                policy_version="v1",
                action={"kind": "difficulty", "difficulty": "hard"},
                state_used={"mastery": 0.1, "mastery_source": "tracked"},
                context_used={"concept": context.concept},
            )

        learner_store.save_profile(_learner(0.1))
        monkeypatch.setattr(BandPolicyV1, "decide", always_hard)

        quiz = _adaptive_quiz(client, mock_quiz_generator)
        target = client.get(
            "/api/v1/student/target-difficulty",
            params={"concept": "Photosynthesis", "student_id": "learner_1"},
        ).json()

        assert quiz["student_mastery"] == target["mastery_level"] == 0.1
        assert quiz["target_difficulty"] == target["target_difficulty"] == "hard"
        assert quiz["decision"]["action"] == {"kind": "difficulty", "difficulty": "hard"}
        mock_quiz_generator.generate_from_topic.assert_called_once_with(
            topic="Photosynthesis", num_questions=3, target_difficulty="hard"
        )

    def test_non_adaptive_quiz_has_no_decision(self, client, mock_quiz_generator):
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            response = client.post("/api/v1/quiz/generate", params={"topic": "Photosynthesis"})

        assert response.status_code == 200
        assert "decision" not in response.json()

    @pytest.mark.parametrize(
        "concept", ["Révolution française", "Reconstruction (1865-1877)", "x" * 200]
    )
    def test_record_names_the_concept_of_the_request(self, client, learner_store, concept):
        response = client.get("/api/v1/student/target-difficulty", params={"concept": concept})

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["concept"] == concept
        assert data["decision"]["context_used"] == {"concept": concept}
        assert len(data["decision"]["record_id"]) == 16

    def test_concept_with_invalid_utf8_bytes_gets_a_record(self, client, learner_store):
        """The query decoder replaces the bytes; the record names the string the service got."""
        response = client.get("/api/v1/student/target-difficulty?concept=%ED%A0%80")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["decision"]["context_used"] == {"concept": data["concept"]}
        assert len(data["decision"]["record_id"]) == 16

    def test_whole_number_mastery_is_written_as_a_float(self, client, learner_store):
        """1.0 stays "1.0" in the response, as in the canonical JSON the id is a digest of."""
        profile = _learner(1.0)
        learner_store.save_profile(profile)

        response = client.get(
            "/api/v1/student/target-difficulty",
            params={"concept": "Photosynthesis", "student_id": "learner_1"},
        )

        assert response.status_code == 200, response.text
        assert '"mastery":1.0' in response.text.replace(" ", "")
        assert response.json()["decision"]["record_id"] == (
            profile.decide_difficulty("Photosynthesis").record_id()
        )
