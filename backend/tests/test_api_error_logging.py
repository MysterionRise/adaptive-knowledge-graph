"""
Error paths must log safely.

loguru formats a message with ``str.format()`` whenever arguments are passed. An
f-string message combined with a keyword argument (such as the unsupported
``exc_info=True``) therefore raises ``KeyError`` as soon as the error text contains
braces - Ollama reports errors as JSON - and the intended 5xx turns into an unhandled
500. These tests send such errors through every error path and check that the mapped
status is returned and the traceback is logged.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from backend.app.core.exceptions import (
    LLMConnectionError,
    LLMGenerationError,
    Neo4jConnectionError,
    QuizGenerationError,
)
from backend.app.kg.cypher_qa import GeneratedCypherError
from backend.app.student.models import TargetDifficultyResponse

BRACED = 'Ollama error: {"error": "x"}'
ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
LOG_METHODS = {"trace", "debug", "info", "success", "warning", "error", "critical", "exception"}


@pytest.fixture
def error_records():
    """Capture ERROR-level loguru records emitted during the test."""
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="ERROR")
    yield records
    logger.remove(sink_id)


def _logged_with_traceback(records: list[dict]) -> bool:
    return any(BRACED in r["message"] and r["exception"] is not None for r in records)


def _failing_adapter_factory(error: Exception) -> MagicMock:
    return MagicMock(side_effect=error)


@pytest.mark.unit
class TestAskErrorLogging:
    """/ask and /ask/stream with brace-containing upstream errors."""

    @pytest.mark.parametrize("error", [LLMGenerationError(BRACED), LLMConnectionError(BRACED)])
    def test_llm_error_is_503(self, client, mock_retriever, error_records, error):
        llm = AsyncMock()
        llm.answer_question.side_effect = error

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=llm),
        ):
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 503
        assert response.json()["detail"] == "LLM service temporarily unavailable"
        assert _logged_with_traceback(error_records)

    def test_unexpected_error_is_500(self, client, error_records):
        retriever = MagicMock()
        retriever.retrieve.side_effect = RuntimeError(BRACED)

        with patch("backend.app.api.routes.ask.get_retriever", return_value=retriever):
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 500
        assert response.json() == {"detail": "An internal error occurred"}
        assert _logged_with_traceback(error_records)

    def test_stream_retrieval_llm_error_is_503(self, client, error_records):
        retriever = MagicMock()
        retriever.retrieve.side_effect = LLMConnectionError(BRACED)

        with patch("backend.app.api.routes.ask.get_retriever", return_value=retriever):
            response = client.post(
                "/api/v1/ask/stream",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 503
        assert _logged_with_traceback(error_records)

    def test_stream_generation_error_becomes_error_event(
        self, client, mock_retriever, error_records
    ):
        llm = MagicMock()
        llm.model_name = "test-model"

        async def failing_stream(*_args, **_kwargs):
            yield "partial"
            raise RuntimeError(BRACED)

        llm.answer_question_stream = failing_stream

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=llm),
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        assert response.status_code == 200
        assert '"type": "error"' in response.text
        assert BRACED not in response.text
        assert response.text.rstrip().endswith("data: [DONE]")
        assert _logged_with_traceback(error_records)


@pytest.mark.unit
class TestQuizErrorLogging:
    """Quiz routes with brace-containing upstream errors."""

    @pytest.mark.parametrize("path", ["/api/v1/quiz/generate", "/api/v1/quiz/generate-adaptive"])
    @pytest.mark.parametrize(
        ("error", "status_code"),
        [
            (LLMConnectionError(BRACED), 503),
            (LLMGenerationError(BRACED), 503),
            (QuizGenerationError(BRACED), 502),
            (ValueError(BRACED), 500),
            (RuntimeError(BRACED), 500),
        ],
        ids=["llm-unreachable", "llm-http-error", "invalid-quiz", "value-error", "unexpected"],
    )
    def test_generation_error_keeps_its_status(
        self, client, error_records, path, error, status_code
    ):
        generator = AsyncMock()
        generator.generate_from_topic.side_effect = error
        student_service = MagicMock()
        student_service.get_target_difficulty.return_value = TargetDifficultyResponse(
            concept="Tariffs", mastery_level=0.5, target_difficulty="medium"
        )

        with (
            patch("backend.app.api.routes.quiz.get_quiz_generator", return_value=generator),
            patch("backend.app.api.routes.quiz.get_student_service", return_value=student_service),
        ):
            response = client.post(path, params={"topic": "Tariffs"})

        assert response.status_code == status_code
        assert BRACED not in response.text
        assert _logged_with_traceback(error_records)

    def test_student_write_error_is_500(self, client, error_records):
        student_service = MagicMock()
        student_service.update_mastery.side_effect = RuntimeError(BRACED)

        with patch("backend.app.api.routes.quiz.get_student_service", return_value=student_service):
            response = client.post(
                "/api/v1/student/mastery", json={"concept": "Tariffs", "correct": True}
            )

        assert response.status_code == 500
        assert _logged_with_traceback(error_records)

    def test_recommendations_error_is_500(self, client, error_records):
        service = MagicMock()
        service.generate_recommendations = AsyncMock(side_effect=RuntimeError(BRACED))
        payload = {
            "topic": "Tariffs",
            "question_results": [
                {"question_id": "q1", "related_concept": "Tariffs", "correct": False}
            ],
        }

        with patch("backend.app.api.routes.quiz.get_recommendation_service", return_value=service):
            response = client.post("/api/v1/quiz/recommendations", json=payload)

        assert response.status_code == 500
        assert _logged_with_traceback(error_records)


@pytest.mark.unit
class TestGraphErrorLogging:
    """Graph, learning-path and subject routes with brace-containing errors."""

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [
            (RuntimeError(BRACED), 500),
            (ValueError(BRACED), 400),
            (GeneratedCypherError(BRACED), 502),
            (LLMGenerationError(BRACED), 503),
            (LLMConnectionError(BRACED), 503),
            (Neo4jConnectionError(BRACED), 503),
        ],
        ids=[
            "unexpected",
            "blocked-cypher",
            "invalid-generated-cypher",
            "llm-error",
            "llm-unreachable",
            "neo4j-unavailable",
        ],
    )
    def test_graph_query_error(self, client, error_records, error, status_code):
        service = MagicMock()
        service.query.side_effect = error

        with patch("backend.app.kg.cypher_qa.get_cypher_qa_service", return_value=service):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == status_code
        assert BRACED not in response.text
        if status_code != 400:
            assert _logged_with_traceback(error_records)

    @pytest.mark.parametrize(
        ("method", "path", "body", "error", "status_code"),
        [
            ("get", "/api/v1/graph/stats", None, Neo4jConnectionError(BRACED), 503),
            ("get", "/api/v1/graph/stats", None, RuntimeError(BRACED), 500),
            ("get", "/api/v1/graph/data", None, RuntimeError(BRACED), 500),
            ("get", "/api/v1/concepts/top", None, RuntimeError(BRACED), 500),
            ("post", "/api/v1/concepts/search", {"query": "tariffs"}, RuntimeError(BRACED), 500),
            ("get", "/api/v1/learning-path/Tariffs", None, Neo4jConnectionError(BRACED), 503),
            ("get", "/api/v1/learning-path/Tariffs", None, RuntimeError(BRACED), 500),
            ("get", "/api/v1/concepts/Tariffs/prerequisites", None, RuntimeError(BRACED), 500),
            ("get", "/api/v1/concepts/Tariffs/dependents", None, RuntimeError(BRACED), 500),
        ],
    )
    def test_neo4j_route_error_keeps_its_status(
        self, client, error_records, method, path, body, error, status_code
    ):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            _failing_adapter_factory(error),
        ):
            response = client.request(method, path, json=body)

        assert response.status_code == status_code
        assert BRACED not in response.text
        assert _logged_with_traceback(error_records)

    def test_subject_listing_error_is_500(self, client, error_records):
        with patch(
            "backend.app.api.routes.subjects.get_all_subjects",
            side_effect=RuntimeError(BRACED),
        ):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 500
        assert _logged_with_traceback(error_records)

    def test_subject_availability_error_is_logged_not_raised(self, client):
        from backend.app.api.routes.subjects import clear_subject_availability_cache

        clear_subject_availability_cache()
        try:
            with patch(
                "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
                _failing_adapter_factory(RuntimeError(BRACED)),
            ):
                response = client.get("/api/v1/subjects")
        finally:
            clear_subject_availability_cache()

        assert response.status_code == 200
        assert not any(s["available"] for s in response.json()["subjects"])


def _log_calls(tree: ast.AST):
    """Yield ``logger.<level>(...)`` calls."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            yield node


@pytest.mark.unit
def test_route_logging_never_formats_interpolated_text():
    """Route log calls take no keyword arguments and never format an f-string."""
    offenders = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        for call in _log_calls(ast.parse(path.read_text(encoding="utf-8"))):
            formats_message = bool(call.args[1:] or call.keywords)
            if call.keywords or (
                formats_message and call.args and isinstance(call.args[0], ast.JoinedStr)
            ):
                offenders.append(f"{path.name}:{call.lineno}")

    assert offenders == []
