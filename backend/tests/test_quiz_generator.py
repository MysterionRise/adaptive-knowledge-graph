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

from backend.app.core.exceptions import ContentNotFoundError, QuizGenerationError


def _make_generator():
    """Create a QuizGenerator with mocked dependencies."""
    with (
        patch("backend.app.student.quiz_generator.get_llm_client") as mock_llm,
        patch("backend.app.student.quiz_generator.get_retriever") as mock_retriever,
    ):
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
        assert "educator" in prompt
        assert "students learn" in prompt
        assert "certification" not in prompt.lower()
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
    async def test_no_content_raises_content_not_found(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = []

        with pytest.raises(ContentNotFoundError, match="No content found"):
            await gen.generate_from_topic("Unknown Topic")
        mock_llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [
            {"text": "Some text.", "id": "chunk_1"},
        ]
        mock_llm.generate.return_value = "This is not JSON at all"

        with pytest.raises(QuizGenerationError, match="invalid JSON") as exc_info:
            await gen.generate_from_topic("Test Topic")

        # Not a ValueError: routes must not turn an LLM failure into "topic not found"
        assert not isinstance(exc_info.value, ValueError)
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

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


def _question(**overrides):
    """A valid LLM question dict, with optional overrides (None removes a key)."""
    question = {
        "text": "Q?",
        "options": [
            {"id": "a", "text": "A"},
            {"id": "b", "text": "B"},
            {"id": "c", "text": "C"},
            {"id": "d", "text": "D"},
        ],
        "correct_option_id": "a",
        "explanation": "Because.",
        "difficulty": "medium",
    }
    for key, value in overrides.items():
        if value is None:
            question.pop(key)
        else:
            question[key] = value
    return question


@pytest.mark.unit
class TestInvalidLLMOutput:
    """Anything that is not valid quiz JSON raises QuizGenerationError."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "llm_response",
        [
            pytest.param("[1, 2, 3]", id="not-an-object"),
            pytest.param('{"items": []}', id="no-questions-key"),
            pytest.param('{"questions": "Q1, Q2"}', id="questions-not-a-list"),
            pytest.param('{"questions": []}', id="empty-questions"),
            pytest.param(json.dumps({"questions": ["What is X?"]}), id="question-not-an-object"),
            pytest.param(
                json.dumps({"questions": [_question(options=None)]}), id="missing-options"
            ),
            pytest.param(json.dumps({"questions": [_question(text=None)]}), id="missing-text"),
            pytest.param(
                json.dumps({"questions": [_question(options=["a", "b"])]}), id="options-not-objects"
            ),
            pytest.param(
                json.dumps({"questions": [_question(options=[{"id": "a"}])]}),
                id="option-missing-text",
            ),
            pytest.param(
                json.dumps({"questions": [_question(correct_option_id="z")]}),
                id="correct-option-not-offered",
            ),
            pytest.param(
                json.dumps({"questions": [_question(difficulty_score="very hard")]}),
                id="difficulty-score-not-a-number",
            ),
            pytest.param(json.dumps({"questions": [_question(text=42)]}), id="text-not-a-string"),
        ],
    )
    async def test_malformed_reply_raises_quiz_generation_error(self, llm_response):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [{"text": "Some text.", "id": "chunk_1"}]
        mock_llm.generate.return_value = llm_response

        with pytest.raises(QuizGenerationError):
            await gen.generate_from_topic("Test Topic")

    @pytest.mark.asyncio
    async def test_error_names_the_malformed_question(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [{"text": "Some text.", "id": "chunk_1"}]
        mock_llm.generate.return_value = json.dumps(
            {"questions": [_question(), _question(explanation=None)]}
        )

        with pytest.raises(QuizGenerationError, match="#2"):
            await gen.generate_from_topic("Test Topic")

    @pytest.mark.asyncio
    async def test_llm_errors_propagate_unchanged(self):
        from backend.app.core.exceptions import LLMConnectionError

        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [{"text": "Some text.", "id": "chunk_1"}]
        mock_llm.generate.side_effect = LLMConnectionError("Ollama down")

        with pytest.raises(LLMConnectionError):
            await gen.generate_from_topic("Test Topic")

    @pytest.mark.asyncio
    async def test_difficulty_score_is_clamped(self):
        gen, mock_llm, mock_retriever = _make_generator()
        mock_retriever.retrieve.return_value = [{"text": "Some text.", "id": "chunk_1"}]
        mock_llm.generate.return_value = json.dumps(
            {"questions": [_question(difficulty_score=1.7), _question(difficulty_score=-0.4)]}
        )

        quiz = await gen.generate_from_topic("Test Topic", num_questions=2)

        assert [q.difficulty_score for q in quiz.questions] == [1.0, 0.0]
        assert [q.difficulty for q in quiz.questions] == ["hard", "easy"]
        assert quiz.average_difficulty == 0.5


@pytest.mark.unit
class TestGetQuizGenerator:
    """get_quiz_generator(None) uses default_subject and its prefixed index."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from backend.app.student.quiz_generator import clear_quiz_generators

        clear_quiz_generators()
        yield
        clear_quiz_generators()

    def test_none_resolves_default_subject(self):
        from backend.app.core.subjects import get_default_subject_id
        from backend.app.student.quiz_generator import get_quiz_generator

        default_id = get_default_subject_id()
        with (
            patch("backend.app.student.quiz_generator.get_llm_client"),
            patch("backend.app.student.quiz_generator.get_retriever") as mock_get_retriever,
        ):
            generator = get_quiz_generator()
            assert generator.subject_id == default_id
            assert get_quiz_generator(default_id) is generator

        mock_get_retriever.assert_called_once_with(default_id)

    def test_generators_are_cached_per_subject(self):
        from backend.app.student.quiz_generator import get_quiz_generator

        with (
            patch("backend.app.student.quiz_generator.get_llm_client"),
            patch("backend.app.student.quiz_generator.get_retriever"),
        ):
            economics = get_quiz_generator("economics")
            history = get_quiz_generator("us_history")

        assert economics is not history
        assert economics.subject_id == "economics"

    def test_unknown_subject_raises_key_error(self):
        from backend.app.student.quiz_generator import get_quiz_generator

        with pytest.raises(KeyError):
            get_quiz_generator("no_such_subject")
