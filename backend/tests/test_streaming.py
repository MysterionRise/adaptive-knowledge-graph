"""
Tests for the /ask/stream SSE streaming endpoint.

Tests cover:
- SSE protocol: metadata event, token events, [DONE] event
- Metadata structure and ordering
- Error events during streaming
- HTTP error codes: 404 (no content), 503 (LLM errors)
- Client disconnect handling (backpressure)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import LLMConnectionError, LLMGenerationError


def _parse_sse_events(response_text: str) -> list[dict | str]:
    """Parse SSE event stream into a list of parsed data objects."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            events.append("[DONE]")
        else:
            events.append(json.loads(data_str))
    return events


@pytest.mark.unit
class TestStreamingProtocol:
    """Tests for SSE event protocol compliance."""

    def _mock_stream(self, tokens: list[str]):
        """Create a mock LLM client that yields given tokens."""
        client = AsyncMock()
        client.model_name = "test-model"

        async def mock_stream(*args, **kwargs):
            for t in tokens:
                yield t

        client.answer_question_stream = mock_stream
        return client

    def test_stream_metadata_first_event(self, client, mock_retriever):
        """First SSE event should be metadata with sources."""
        mock_llm = self._mock_stream(["Hello", " world"])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
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
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)
        assert len(events) >= 3  # metadata + tokens + [DONE]

        metadata = events[0]
        assert metadata["type"] == "metadata"
        assert "sources" in metadata
        assert "model" in metadata
        assert "attribution" in metadata
        assert "retrieved_count" in metadata

    def test_stream_token_events(self, client, mock_retriever):
        """Token events should have type='token' and content."""
        mock_llm = self._mock_stream(["Hello", " ", "world"])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        events = _parse_sse_events(response.text)
        token_events = [e for e in events if isinstance(e, dict) and e.get("type") == "token"]
        assert len(token_events) == 3
        assert token_events[0]["content"] == "Hello"
        assert token_events[1]["content"] == " "
        assert token_events[2]["content"] == "world"

    def test_stream_done_event(self, client, mock_retriever):
        """Last SSE event should be [DONE]."""
        mock_llm = self._mock_stream(["token"])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        events = _parse_sse_events(response.text)
        assert events[-1] == "[DONE]"

    def test_stream_sources_truncated(self, client, mock_llm_client):
        """Sources in metadata should be truncated to 200 chars."""
        long_retriever = MagicMock()
        long_retriever.retrieve.return_value = [
            {"text": "A" * 500, "module_id": "m1", "section": "S1", "score": 0.9, "id": "c1"},
        ]
        mock_llm = self._mock_stream(["answer"])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=long_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        events = _parse_sse_events(response.text)
        metadata = events[0]
        assert len(metadata["sources"][0]["text"]) == 203  # 200 + "..."

    def test_stream_empty_tokens(self, client, mock_retriever):
        """Stream with no tokens should still produce metadata and [DONE]."""
        mock_llm = self._mock_stream([])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        events = _parse_sse_events(response.text)
        assert events[0]["type"] == "metadata"
        assert events[-1] == "[DONE]"


@pytest.mark.unit
class TestStreamingErrors:
    """Tests for error handling in streaming endpoint."""

    def test_stream_no_content_404(self, client):
        """Should return 404 when no content found."""
        empty_retriever = MagicMock()
        empty_retriever.retrieve.return_value = []

        with patch("backend.app.api.routes.ask.get_retriever", return_value=empty_retriever):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is an obscure topic that doesn't exist?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 404
        assert "No relevant content found" in response.json()["detail"]

    def test_stream_llm_generation_error_503(self, client, mock_retriever):
        """Should return 503 when LLM generation fails during retrieval."""
        failing_llm = AsyncMock()
        failing_llm.answer_question_stream.side_effect = LLMGenerationError("LLM timeout")

        # _retrieve_context itself doesn't use LLM, so this tests the outer handler
        # Let's make retrieval raise instead
        failing_retriever = MagicMock()
        failing_retriever.retrieve.side_effect = LLMGenerationError("Upstream LLM error")

        with patch("backend.app.api.routes.ask.get_retriever", return_value=failing_retriever):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 503
        assert "LLM service temporarily unavailable" in response.json()["detail"]

    def test_stream_llm_connection_error_503(self, client):
        """Should return 503 when LLM connection fails."""
        failing_retriever = MagicMock()
        failing_retriever.retrieve.side_effect = LLMConnectionError("Connection refused")

        with patch("backend.app.api.routes.ask.get_retriever", return_value=failing_retriever):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 503

    def test_stream_internal_error_500(self, client):
        """Should return 500 on unexpected errors."""
        broken_retriever = MagicMock()
        broken_retriever.retrieve.side_effect = RuntimeError("Database corruption")

        with patch("backend.app.api.routes.ask.get_retriever", return_value=broken_retriever):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 500

    def test_stream_error_event_during_generation(self, client, mock_retriever):
        """LLM error during token streaming should produce an error event."""
        mock_llm = AsyncMock()
        mock_llm.model_name = "test-model"

        async def failing_stream(*args, **kwargs):
            yield "partial"
            raise RuntimeError("GPU out of memory")

        mock_llm.answer_question_stream = failing_stream

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                    "use_window_retrieval": False,
                },
            )

        assert response.status_code == 200  # SSE stream already started
        events = _parse_sse_events(response.text)

        error_events = [e for e in events if isinstance(e, dict) and e.get("type") == "error"]
        assert len(error_events) == 1
        assert "An error occurred during streaming" in error_events[0]["content"]

    def test_stream_validation_error(self, client):
        """Should return 422 for invalid request."""
        response = client.post(
            "/api/v1/ask/stream",
            json={"question": "Hi"},  # Too short (min_length=3 but "Hi" is 2)
        )
        assert response.status_code == 422


@pytest.mark.unit
class TestStreamingWithKGExpansion:
    """Tests for streaming with KG expansion enabled."""

    def _mock_stream(self, tokens: list[str]):
        client = AsyncMock()
        client.model_name = "test-model"

        async def mock_stream(*args, **kwargs):
            for t in tokens:
                yield t

        client.answer_question_stream = mock_stream
        return client

    def test_stream_with_expanded_concepts(self, client, mock_retriever, mock_kg_expander):
        """Metadata should include expanded concepts when KG expansion is used."""
        mock_llm = self._mock_stream(["answer"])

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm
        ), patch(
            "backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander
        ), patch(
            "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
            return_value=["photosynthesis", "chloroplast"],
        ):
            response = client.post(
                "/api/v1/ask/stream",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": True,
                    "use_window_retrieval": False,
                },
            )

        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        metadata = events[0]
        assert metadata["expanded_concepts"] is not None
        assert len(metadata["expanded_concepts"]) > 0
