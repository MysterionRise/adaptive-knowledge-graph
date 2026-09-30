"""
Tests for the /ask Q&A endpoint.

Tests cover:
- Successful question answering with mocked services
- KG expansion behavior (enabled/disabled)
- Error handling (no content found, LLM errors, empty answers, server errors)
- Request validation (trimming, markup, subjects)
- Reranker and window-retrieval paths
- Blocking retrieval work running in the threadpool
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import LLMConnectionError, LLMGenerationError
from backend.app.core.settings import settings
from backend.app.main import app


@pytest.mark.unit
class TestAskEndpoint:
    """Tests for POST /api/v1/ask endpoint."""

    def test_ask_success_with_kg_expansion(
        self,
        client,
        mock_retriever,
        mock_llm_client,
        mock_kg_expander,
    ):
        """Test successful question answering with KG expansion."""
        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
            patch("backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander),
            patch(
                "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
                return_value=["photosynthesis", "chloroplast"],
            ),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": True,
                    "use_window_retrieval": False,
                    "top_k": 5,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "question" in data
        assert "answer" in data
        assert "sources" in data
        assert "model" in data
        assert "attribution" in data
        assert "retrieved_count" in data

        # Verify content
        assert data["question"] == "What is photosynthesis?"
        assert len(data["answer"]) > 0
        assert len(data["sources"]) > 0
        assert data["retrieved_count"] == 3

        # Verify KG expansion was called
        mock_kg_expander.expand_query.assert_called_once()

    def test_ask_success_without_kg_expansion(
        self,
        client,
        mock_retriever,
        mock_llm_client,
    ):
        """Test question answering without KG expansion."""
        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                    "top_k": 5,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["expanded_concepts"] is None

    def test_ask_no_content_found(self, client, mock_llm_client):
        """Test 404 when no relevant content is found."""
        empty_retriever = MagicMock()
        empty_retriever.retrieve.return_value = []

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=empty_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is an obscure topic that doesn't exist?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 404
        assert "No relevant content found" in response.json()["detail"]

    def test_ask_llm_generation_error(self, client, mock_retriever):
        """Test 503 when LLM fails to generate response."""
        failing_llm = AsyncMock()
        failing_llm.answer_question.side_effect = LLMGenerationError("LLM timeout")

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=failing_llm),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 503
        assert "LLM service temporarily unavailable" in response.json()["detail"]

    def test_ask_validation_question_too_short(self, client):
        """Test validation error for question shorter than 3 characters."""
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "Hi",
                "use_kg_expansion": False,
            },
        )

        assert response.status_code == 422  # Validation error

    def test_ask_validation_top_k_out_of_range(self, client):
        """Test validation error for top_k out of allowed range."""
        # top_k too high
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "What is photosynthesis?",
                "top_k": 100,
            },
        )
        assert response.status_code == 422

        # top_k too low
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "What is photosynthesis?",
                "top_k": 0,
            },
        )
        assert response.status_code == 422

    def test_ask_validation_window_size_out_of_range(self, client):
        """Test validation error for window_size out of allowed range."""
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "What is photosynthesis?",
                "window_size": 10,
            },
        )
        assert response.status_code == 422

    def test_ask_sources_are_truncated(
        self,
        client,
        mock_llm_client,
    ):
        """Test that source texts are truncated to 200 characters."""
        long_text_retriever = MagicMock()
        long_text_retriever.retrieve.return_value = [
            {
                "text": "A" * 500,  # 500 characters
                "module_id": "mod_001",
                "section": "Chapter 1",
                "score": 0.95,
            }
        ]

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=long_text_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        # Source should be truncated to 200 chars + "..."
        assert len(data["sources"][0]["text"]) == 203

    def test_ask_kg_expansion_failure_continues(
        self,
        client,
        mock_retriever,
        mock_llm_client,
    ):
        """Test that KG expansion failure doesn't break the request."""
        failing_expander = MagicMock()
        failing_expander.expand_query.side_effect = Exception("Neo4j connection failed")

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
            patch("backend.app.api.routes.ask.get_kg_expander", return_value=failing_expander),
            patch(
                "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
                return_value=["photosynthesis"],
            ),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": True,
                },
            )

        # Should still succeed, just without expansion
        assert response.status_code == 200
        data = response.json()
        assert data["expanded_concepts"] is None

    def test_ask_internal_server_error(self, client):
        """Test 500 on unexpected errors."""
        broken_retriever = MagicMock()
        broken_retriever.retrieve.side_effect = RuntimeError("Database corruption")

        with patch("backend.app.api.routes.ask.get_retriever", return_value=broken_retriever):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 500
        assert "An internal error occurred" in response.json()["detail"]

    def test_ask_default_parameters(
        self,
        client,
        mock_retriever,
        mock_llm_client,
        mock_kg_expander,
    ):
        """Test that default parameters are applied correctly."""
        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
            patch("backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander),
            patch(
                "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
                return_value=["photosynthesis"],
            ),
        ):
            # Only provide question, rely on defaults
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?"},
            )

        assert response.status_code == 200
        # Verify retriever was called with default top_k=5
        mock_retriever.retrieve.assert_called_once()
        call_args = mock_retriever.retrieve.call_args
        assert call_args[1]["top_k"] == 5

    def test_ask_includes_attribution(
        self,
        client,
        mock_retriever,
        mock_llm_client,
    ):
        """Test that response includes OpenStax attribution."""
        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "attribution" in data
        assert "OpenStax" in data["attribution"]
        assert "CC BY 4.0" in data["attribution"]


def _on_event_loop() -> bool:
    """True when called from a thread that is running an asyncio event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@pytest.fixture
def ask_services(mock_retriever, mock_llm_client):
    """Patch retrieval and the LLM used by /ask."""
    with (
        patch(
            "backend.app.api.routes.ask.get_retriever", return_value=mock_retriever
        ) as retriever_factory,
        patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
    ):
        yield SimpleNamespace(
            retriever=mock_retriever, retriever_factory=retriever_factory, llm=mock_llm_client
        )


@pytest.mark.unit
class TestAskValidation:
    """Question and subject validation for /ask."""

    def test_whitespace_only_question_is_422(self, client, ask_services):
        response = client.post("/api/v1/ask", json={"question": "     "})

        assert response.status_code == 422
        ask_services.retriever.retrieve.assert_not_called()

    def test_question_is_trimmed(self, client, ask_services):
        response = client.post(
            "/api/v1/ask",
            json={"question": "  What is photosynthesis?  ", "use_kg_expansion": False},
        )

        assert response.status_code == 200
        assert response.json()["question"] == "What is photosynthesis?"
        answer_kwargs = ask_services.llm.answer_question.await_args.kwargs
        assert answer_kwargs["question"] == "What is photosynthesis?"

    @pytest.mark.parametrize(
        "question",
        [
            '<script>alert("XSS")</script>What is biology?',
            "What is <b>biology</b>?",
            "<img src=x onerror=alert(1)> What is DNA?",
        ],
    )
    def test_markup_is_422_without_echo(self, client, ask_services, question):
        response = client.post("/api/v1/ask", json={"question": question})

        assert response.status_code == 422
        for fragment in ("<script", "<b>", "<img", "alert("):
            assert fragment not in response.text
        assert response.json()["detail"][0]["loc"] == ["body", "question"]
        ask_services.retriever.retrieve.assert_not_called()

    def test_comparison_operators_are_not_markup(self, client, ask_services):
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "Why is supply < demand during a shortage?",
                "use_kg_expansion": False,
            },
        )

        assert response.status_code == 200

    def test_unknown_subject_is_404(self, client, ask_services):
        response = client.post(
            "/api/v1/ask", json={"question": "What is biology?", "subject": "no_such_subject"}
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Subject not found"
        ask_services.retriever.retrieve.assert_not_called()

    @pytest.mark.parametrize("subject", ["'; DROP DATABASE neo4j; --", "Biology", "a" * 33])
    def test_malformed_subject_is_422(self, client, ask_services, subject):
        response = client.post(
            "/api/v1/ask", json={"question": "What is biology?", "subject": subject}
        )

        assert response.status_code == 422
        ask_services.retriever.retrieve.assert_not_called()

    def test_subject_selects_retriever(self, client, ask_services):
        response = client.post(
            "/api/v1/ask",
            json={"question": "What is mitosis?", "subject": "biology", "use_kg_expansion": False},
        )

        assert response.status_code == 200
        ask_services.retriever_factory.assert_called_once_with("biology")

    def test_missing_chunk_text_is_500_not_404(self, client, mock_llm_client):
        """A KeyError from chunk data must not be reported as an unknown subject."""
        broken_retriever = MagicMock()
        broken_retriever.retrieve.return_value = [{"id": "c1", "score": 0.9}]

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=broken_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask", json={"question": "What is DNA?", "use_kg_expansion": False}
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"

    def test_error_responses_are_declared_in_openapi(self):
        responses = app.openapi()["paths"]["/api/v1/ask"]["post"]["responses"]

        assert {"404", "422", "429", "502", "503"} <= set(responses)


@pytest.mark.unit
class TestAskEmptyAnswer:
    """An empty LLM answer is an upstream failure, not a successful answer."""

    @pytest.mark.parametrize("answer", ["", "   \n", None])
    def test_empty_llm_answer_is_502(self, client, mock_retriever, answer):
        llm = AsyncMock()
        llm.answer_question.return_value = {"answer": answer, "model": "test-model"}

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=llm),
        ):
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 502
        assert response.json()["detail"] == "The language model returned an empty answer"

    def test_llm_connection_error_is_503(self, client, mock_retriever):
        llm = AsyncMock()
        llm.answer_question.side_effect = LLMConnectionError("Ollama connection failed")

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=llm),
        ):
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 503


@pytest.mark.unit
class TestAskReranking:
    """Reranker path in /ask (settings.reranker_enabled)."""

    @pytest.fixture
    def reranker(self, monkeypatch):
        monkeypatch.setattr(settings, "reranker_enabled", True)
        reranker = MagicMock()
        reranker.is_loaded = True
        reranker.rerank.return_value = [
            {"text": "Chlorophyll absorbs light.", "section": "5.2", "score": 0.99}
        ]
        with patch("backend.app.rag.reranker.get_reranker", return_value=reranker):
            yield reranker

    def test_reranker_selects_final_chunks(self, client, ask_services, reranker):
        response = client.post(
            "/api/v1/ask",
            json={"question": "What is photosynthesis?", "use_kg_expansion": False, "top_k": 3},
        )

        assert response.status_code == 200
        # Retrieval over-fetches for the reranker, which keeps the requested top_k
        retrieve_kwargs = ask_services.retriever.retrieve.call_args.kwargs
        assert retrieve_kwargs["top_k"] == settings.rag_retrieval_top_k
        query, chunks, top_k = reranker.rerank.call_args.args
        assert query == "What is photosynthesis?"
        assert chunks == ask_services.retriever.retrieve.return_value
        assert top_k == 3

        data = response.json()
        assert [source["text"] for source in data["sources"]] == ["Chlorophyll absorbs light."]
        assert data["retrieved_count"] == 3
        answer_kwargs = ask_services.llm.answer_question.await_args.kwargs
        assert answer_kwargs["context"] == ["Chlorophyll absorbs light."]
        reranker.load.assert_not_called()

    def test_reranker_is_loaded_on_first_use(self, client, ask_services, reranker):
        reranker.is_loaded = False

        response = client.post(
            "/api/v1/ask", json={"question": "What is photosynthesis?", "use_kg_expansion": False}
        )

        assert response.status_code == 200
        reranker.load.assert_called_once()

    def test_reranker_failure_keeps_retrieved_chunks(self, client, ask_services, reranker):
        reranker.rerank.side_effect = RuntimeError("CUDA out of memory")

        response = client.post(
            "/api/v1/ask", json={"question": "What is photosynthesis?", "use_kg_expansion": False}
        )

        assert response.status_code == 200
        assert len(response.json()["sources"]) == len(ask_services.retriever.retrieve.return_value)

    def test_reranker_disabled_by_default(self, client, ask_services):
        with patch("backend.app.rag.reranker.get_reranker") as get_reranker:
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 200
        get_reranker.assert_not_called()
        assert ask_services.retriever.retrieve.call_args.kwargs["top_k"] == 5


@pytest.mark.unit
class TestAskWindowRetrieval:
    """NEXT-window expansion path in /ask (vector_backend neo4j/hybrid)."""

    @pytest.fixture
    def window_retriever(self, monkeypatch):
        monkeypatch.setattr(settings, "vector_backend", "neo4j")
        window_retriever = MagicMock()
        window_retriever.retrieve_window_text.return_value = [
            {"module_id": "mod_001", "section": "5.1", "text": "Merged window.", "chunk_count": 3},
            {"module_id": "mod_002", "section": "6.1", "text": "Second window.", "chunk_count": 2},
        ]
        with patch(
            "backend.app.rag.window_retriever.get_window_retriever", return_value=window_retriever
        ):
            yield window_retriever

    def test_window_expansion_replaces_chunks(self, client, ask_services, window_retriever):
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "What is photosynthesis?",
                "use_kg_expansion": False,
                "window_size": 2,
            },
        )

        assert response.status_code == 200
        window_retriever.retrieve_window_text.assert_called_once_with(
            chunk_ids=["chunk_001", "chunk_002", "chunk_003"], window_size=2
        )
        data = response.json()
        assert data["retrieved_count"] == 3
        assert data["window_expanded_count"] == 5
        assert [source["text"] for source in data["sources"]] == [
            "Merged window.",
            "Second window.",
        ]
        answer_kwargs = ask_services.llm.answer_question.await_args.kwargs
        assert answer_kwargs["context"] == ["Merged window.", "Second window."]

    def test_window_failure_keeps_retrieved_chunks(self, client, ask_services, window_retriever):
        window_retriever.retrieve_window_text.side_effect = RuntimeError("Neo4j timeout")

        response = client.post(
            "/api/v1/ask", json={"question": "What is photosynthesis?", "use_kg_expansion": False}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["window_expanded_count"] is None
        assert len(data["sources"]) == 3

    def test_window_skipped_when_request_disables_it(self, client, ask_services, window_retriever):
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "What is photosynthesis?",
                "use_kg_expansion": False,
                "use_window_retrieval": False,
            },
        )

        assert response.status_code == 200
        window_retriever.retrieve_window_text.assert_not_called()

    def test_window_skipped_for_opensearch_backend(self, client, ask_services, monkeypatch):
        monkeypatch.setattr(settings, "vector_backend", "opensearch")

        with patch("backend.app.rag.window_retriever.get_window_retriever") as factory:
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 200
        factory.assert_not_called()

    def test_window_needs_chunk_ids(self, client, mock_llm_client, window_retriever):
        retriever = MagicMock()
        retriever.retrieve.return_value = [{"text": "No id on this chunk.", "score": 0.5}]

        with (
            patch("backend.app.api.routes.ask.get_retriever", return_value=retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client),
        ):
            response = client.post(
                "/api/v1/ask",
                json={"question": "What is photosynthesis?", "use_kg_expansion": False},
            )

        assert response.status_code == 200
        assert response.json()["window_expanded_count"] is None
        window_retriever.retrieve_window_text.assert_not_called()


@pytest.mark.unit
class TestAskKeepsEventLoopFree:
    """Blocking retrieval steps run in the threadpool, the LLM call on the event loop."""

    def test_blocking_steps_run_off_the_event_loop(self, client, monkeypatch):
        monkeypatch.setattr(settings, "vector_backend", "neo4j")
        monkeypatch.setattr(settings, "reranker_enabled", True)
        on_loop: dict[str, bool] = {}

        def recorder(name, result):
            def record(*_args, **_kwargs):
                on_loop[name] = _on_event_loop()
                return result

            return record

        expander = MagicMock()
        expander.expand_query.side_effect = recorder(
            "expand_query",
            {
                "extracted_concepts": ["photosynthesis"],
                "expanded_concepts": ["photosynthesis", "chlorophyll"],
                "expanded_query": "photosynthesis chlorophyll",
            },
        )
        retriever = MagicMock()
        retriever.retrieve.side_effect = recorder(
            "retrieve", [{"text": "Light becomes sugar.", "id": "c1", "score": 0.9}]
        )
        window_retriever = MagicMock()
        window_retriever.retrieve_window_text.side_effect = recorder(
            "window", [{"module_id": "m1", "section": "S1", "text": "Window.", "chunk_count": 2}]
        )
        reranker = MagicMock()
        reranker.is_loaded = True
        reranker.rerank.side_effect = recorder("rerank", [{"text": "Window.", "score": 1.0}])

        async def answer_question(**_kwargs):
            on_loop["llm"] = _on_event_loop()
            return {"answer": "Plants turn light into sugar.", "model": "test-model"}

        llm = AsyncMock()
        llm.answer_question.side_effect = answer_question

        with (
            patch(
                "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
                side_effect=recorder("all_concepts", {"photosynthesis", "chlorophyll"}),
            ),
            patch("backend.app.api.routes.ask.get_kg_expander", return_value=expander),
            patch("backend.app.api.routes.ask.get_retriever", return_value=retriever),
            patch("backend.app.api.routes.ask.get_llm_client", return_value=llm),
            patch(
                "backend.app.rag.window_retriever.get_window_retriever",
                return_value=window_retriever,
            ),
            patch("backend.app.rag.reranker.get_reranker", return_value=reranker),
        ):
            response = client.post("/api/v1/ask", json={"question": "What is photosynthesis?"})

        assert response.status_code == 200
        assert retriever.retrieve.call_args.args == ("photosynthesis chlorophyll",)
        assert on_loop == {
            "all_concepts": False,
            "expand_query": False,
            "retrieve": False,
            "window": False,
            "rerank": False,
            "llm": True,
        }
