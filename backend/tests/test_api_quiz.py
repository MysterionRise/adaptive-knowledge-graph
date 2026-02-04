"""
Tests for the /quiz endpoints.

Tests cover:
- Quiz generation with mocked LLM
- Parameter validation
- Error handling (content not found, generation errors)
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.core.exceptions import ContentNotFoundError, QuizGenerationError
from backend.app.ui_payloads.quiz import Quiz, QuizOption, QuizQuestion


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
        assert "No content found" in response.json()["detail"]

    def test_generate_quiz_value_error(self, client):
        """Test 404 when ValueError raised (no content)."""
        failing_generator = AsyncMock()
        failing_generator.generate_from_topic.side_effect = ValueError(
            "Topic not covered in knowledge base"
        )

        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=failing_generator
        ):
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": "Unknown Topic"},
            )

        assert response.status_code == 404

    def test_generate_quiz_generation_error(self, client):
        """Test 503 when quiz generation fails."""
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

        assert response.status_code == 503
        assert "Quiz generation failed" in response.json()["detail"]

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
        """Test that empty topic is handled."""
        with patch(
            "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
        ):
            # FastAPI should still accept empty string (validation is in the generator)
            response = client.post(
                "/api/v1/quiz/generate",
                params={"topic": ""},
            )

        # The endpoint doesn't validate topic length, so it passes through
        # Generator would handle the empty topic
        assert response.status_code == 200


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
