"""
Tests for the /ask Q&A endpoint.

Tests cover:
- Successful question answering with mocked services
- KG expansion behavior (enabled/disabled)
- Error handling (no content found, LLM errors, server errors)
- Request validation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import LLMGenerationError


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
        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
        ), patch(
            "backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander
        ), patch(
            "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
            return_value=["photosynthesis", "chloroplast"],
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
        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
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

        with patch("backend.app.api.routes.ask.get_retriever", return_value=empty_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
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

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=failing_llm
        ):
            response = client.post(
                "/api/v1/ask",
                json={
                    "question": "What is photosynthesis?",
                    "use_kg_expansion": False,
                },
            )

        assert response.status_code == 503
        assert "LLM service error" in response.json()["detail"]

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

        with patch(
            "backend.app.api.routes.ask.get_retriever", return_value=long_text_retriever
        ), patch("backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client):
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

        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
        ), patch(
            "backend.app.api.routes.ask.get_kg_expander", return_value=failing_expander
        ), patch(
            "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
            return_value=["photosynthesis"],
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
        assert "Internal server error" in response.json()["detail"]

    def test_ask_default_parameters(
        self,
        client,
        mock_retriever,
        mock_llm_client,
        mock_kg_expander,
    ):
        """Test that default parameters are applied correctly."""
        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
        ), patch(
            "backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander
        ), patch(
            "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
            return_value=["photosynthesis"],
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
        with patch("backend.app.api.routes.ask.get_retriever", return_value=mock_retriever), patch(
            "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
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
