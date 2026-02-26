"""
Tests for the quiz generator module.

Tests cover:
- Difficulty parsing and score-to-label conversion
- JSON response cleaning (markdown blocks)
- System/user prompt construction with difficulty targeting
- Full quiz generation flow with mocked LLM and retriever
- Edge cases: no content, LLM failure, invalid JSON
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_generator():
    """Create a QuizGenerator with mocked dependencies."""
    with patch("backend.app.student.quiz_generator.get_llm_client") as mock_llm, patch(
        "backend.app.student.quiz_generator.get_retriever"
    ) as mock_retriever:
        from backend.app.student.quiz_generator import QuizGenerator

        mock_llm_instance = AsyncMock()
        mock_llm.return_value = mock_llm_instance

        mock_retriever_instance = MagicMock()
        mock_retriever.return_value = mock_retriever_instance

        gen = QuizGenerator(subject_id="us_history")
        return gen, mock_llm_instance, mock_retriever_instance


@pytest.mark.unit
class TestParseDifficulty:
    """Tests for _parse_difficulty method."""

    def _generator(self):
        gen, _, _ = _make_generator()
        return gen

    def test_easy(self):
        gen = self._generator()
        level, score = gen._parse_difficulty("easy")
        assert level == "easy"
        assert score == 0.25

    def test_medium(self):
        gen = self._generator()
        level, score = gen._parse_difficulty("medium")
        assert level == "medium"
        assert score == 0.5

    def test_hard(self):
        gen = self._generator()
        level, score = gen._parse_difficulty("hard")
        assert level == "hard"
        assert score == 0.75

    def test_case_insensitive(self):
        gen = self._generator()
        level, score = gen._parse_difficulty("  HARD  ")
        assert level == "hard"
        assert score == 0.75

    def test_unknown_defaults_to_medium(self):
        gen = self._generator()
        level, score = gen._parse_difficulty("expert")
        assert level == "medium"
        assert score == 0.5


@pytest.mark.unit
class TestScoreToDifficulty:
    """Tests for _score_to_difficulty method."""

    def _generator(self):
        gen, _, _ = _make_generator()
        return gen

    def test_easy_range(self):
        gen = self._generator()
        assert gen._score_to_difficulty(0.0) == "easy"
        assert gen._score_to_difficulty(0.2) == "easy"
        assert gen._score_to_difficulty(0.34) == "easy"

    def test_medium_range(self):
        gen = self._generator()
        assert gen._score_to_difficulty(0.35) == "medium"
        assert gen._score_to_difficulty(0.5) == "medium"
        assert gen._score_to_difficulty(0.64) == "medium"

    def test_hard_range(self):
        gen = self._generator()
        assert gen._score_to_difficulty(0.65) == "hard"
        assert gen._score_to_difficulty(0.9) == "hard"
        assert gen._score_to_difficulty(1.0) == "hard"


@pytest.mark.unit
class TestCleanJsonResponse:
    """Tests for _clean_json_response method."""

    def _generator(self):
        gen, _, _ = _make_generator()
        return gen

    def test_plain_json(self):
        gen = self._generator()
        raw = '{"questions": []}'
        assert gen._clean_json_response(raw) == '{"questions": []}'

    def test_json_markdown_block(self):
        gen = self._generator()
        raw = '```json\n{"questions": []}\n```'
        assert gen._clean_json_response(raw) == '{"questions": []}'

    def test_generic_markdown_block(self):
        gen = self._generator()
        raw = '```\n{"questions": []}\n```'
        assert gen._clean_json_response(raw) == '{"questions": []}'

    def test_whitespace_stripping(self):
        gen = self._generator()
        raw = '  {"questions": []}  '
        assert gen._clean_json_response(raw) == '{"questions": []}'

    def test_surrounding_text(self):
        gen = self._generator()
        raw = 'Here is the JSON:\n```json\n{"questions": []}\n```\nDone.'
        assert gen._clean_json_response(raw) == '{"questions": []}'


@pytest.mark.unit
class TestBuildPrompts:
    """Tests for prompt construction."""

    def _generator(self):
        gen, _, _ = _make_generator()
        return gen

    def test_system_prompt_no_target(self):
        gen = self._generator()
        prompt = gen._build_system_prompt()
        assert "expert exam creator" in prompt
        assert "difficulty_score" in prompt

    def test_system_prompt_easy(self):
        gen = self._generator()
        prompt = gen._build_system_prompt(target_difficulty="easy")
        assert "EASY" in prompt
        assert "0.1 and 0.3" in prompt

    def test_system_prompt_hard(self):
        gen = self._generator()
        prompt = gen._build_system_prompt(target_difficulty="hard")
        assert "HARD" in prompt
        assert "synthesis" in prompt.lower()

    def test_user_prompt_with_target(self):
        gen = self._generator()
        prompt = gen._build_user_prompt(3, "Sample context text", target_difficulty="medium")
        assert "3 multiple-choice" in prompt
        assert "MEDIUM" in prompt
        assert "Sample context text" in prompt

    def test_user_prompt_without_target(self):
        gen = self._generator()
        prompt = gen._build_user_prompt(5, "Sample context text")
        assert "5 multiple-choice" in prompt
        assert "varying difficulty" in prompt


@pytest.mark.unit
class TestGenerateFromTopic:
    """Tests for the full quiz generation flow."""

    @pytest.mark.asyncio
    async def test_success_with_llm_scores(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "The American Revolution began in 1775.", "id": "chunk_1"},
        ]
        llm_response = json.dumps(
            {
                "questions": [
                    {
                        "text": "When did the American Revolution begin?",
                        "options": [
                            {"id": "a", "text": "1775"},
                            {"id": "b", "text": "1776"},
                            {"id": "c", "text": "1774"},
                            {"id": "d", "text": "1777"},
                        ],
                        "correct_option_id": "a",
                        "explanation": "It began in 1775.",
                        "difficulty": "easy",
                        "difficulty_score": 0.2,
                    }
                ]
            }
        )
        mock_llm.generate.return_value = llm_response

        quiz = await gen.generate_from_topic("American Revolution", num_questions=1)

        assert quiz.title == "Assessment: American Revolution"
        assert len(quiz.questions) == 1
        assert quiz.questions[0].difficulty == "easy"
        assert quiz.questions[0].difficulty_score == 0.2
        assert quiz.questions[0].source_chunk_id == "chunk_1"
        assert quiz.questions[0].related_concept == "American Revolution"
        assert quiz.average_difficulty == 0.2

    @pytest.mark.asyncio
    async def test_success_without_llm_scores(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "The Constitution was ratified in 1788.", "id": "chunk_2"},
        ]
        llm_response = json.dumps(
            {
                "questions": [
                    {
                        "text": "When was the Constitution ratified?",
                        "options": [
                            {"id": "a", "text": "1788"},
                            {"id": "b", "text": "1789"},
                            {"id": "c", "text": "1787"},
                            {"id": "d", "text": "1790"},
                        ],
                        "correct_option_id": "a",
                        "explanation": "Ratified in 1788.",
                        "difficulty": "hard",
                    }
                ]
            }
        )
        mock_llm.generate.return_value = llm_response

        quiz = await gen.generate_from_topic("Constitution")
        assert quiz.questions[0].difficulty == "hard"
        assert quiz.questions[0].difficulty_score == 0.75

    @pytest.mark.asyncio
    async def test_no_content_raises_value_error(self):
        gen, _, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = []

        with pytest.raises(ValueError, match="No content found"):
            await gen.generate_from_topic("Unknown Topic")

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "Some text.", "id": "chunk_1"},
        ]
        mock_llm.generate.return_value = "This is not JSON at all"

        with pytest.raises(json.JSONDecodeError):
            await gen.generate_from_topic("Test Topic")

    @pytest.mark.asyncio
    async def test_markdown_wrapped_json(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "Some text.", "id": "chunk_1"},
        ]
        llm_response = '```json\n{"questions": [{"text": "Q?", "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}, {"id": "c", "text": "C"}, {"id": "d", "text": "D"}], "correct_option_id": "a", "explanation": "Because.", "difficulty": "medium"}]}\n```'
        mock_llm.generate.return_value = llm_response

        quiz = await gen.generate_from_topic("Test")
        assert len(quiz.questions) == 1

    @pytest.mark.asyncio
    async def test_target_difficulty_easy(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "Context.", "id": "chunk_1"},
        ]
        llm_response = json.dumps(
            {
                "questions": [
                    {
                        "text": "Easy Q?",
                        "options": [
                            {"id": "a", "text": "A"},
                            {"id": "b", "text": "B"},
                            {"id": "c", "text": "C"},
                            {"id": "d", "text": "D"},
                        ],
                        "correct_option_id": "a",
                        "explanation": "Easy.",
                        "difficulty": "easy",
                        "difficulty_score": 0.15,
                    }
                ]
            }
        )
        mock_llm.generate.return_value = llm_response

        await gen.generate_from_topic("Test", target_difficulty="easy")
        # Verify prompt included easy difficulty guidance
        call_args = mock_llm.generate.call_args
        assert "easy" in call_args[1]["system_prompt"].lower() or "EASY" in call_args[1].get(
            "system_prompt", call_args[1].get("prompt", "")
        )

    @pytest.mark.asyncio
    async def test_multiple_questions_average_difficulty(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "Context text.", "id": "chunk_1"},
        ]
        llm_response = json.dumps(
            {
                "questions": [
                    {
                        "text": "Q1?",
                        "options": [
                            {"id": "a", "text": "A"},
                            {"id": "b", "text": "B"},
                            {"id": "c", "text": "C"},
                            {"id": "d", "text": "D"},
                        ],
                        "correct_option_id": "a",
                        "explanation": "E1.",
                        "difficulty": "easy",
                        "difficulty_score": 0.2,
                    },
                    {
                        "text": "Q2?",
                        "options": [
                            {"id": "a", "text": "A"},
                            {"id": "b", "text": "B"},
                            {"id": "c", "text": "C"},
                            {"id": "d", "text": "D"},
                        ],
                        "correct_option_id": "b",
                        "explanation": "E2.",
                        "difficulty": "hard",
                        "difficulty_score": 0.8,
                    },
                ]
            }
        )
        mock_llm.generate.return_value = llm_response

        quiz = await gen.generate_from_topic("Test", num_questions=2)
        assert quiz.average_difficulty == 0.5  # (0.2 + 0.8) / 2
