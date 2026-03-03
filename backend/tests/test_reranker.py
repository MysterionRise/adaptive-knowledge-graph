"""
Tests for the Reranker module.

All tests mock CrossEncoder.predict — no model download required.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.rag.reranker import Reranker, get_reranker


def _make_chunks(n: int) -> list[dict]:
    """Create n test chunks with text and metadata."""
    return [
        {"text": f"chunk {i} content", "section": f"section_{i}", "score": 0.5 + i * 0.01}
        for i in range(n)
    ]


@pytest.mark.unit
class TestReranker:
    """Tests for Reranker.rerank()."""

    def _loaded_reranker(self) -> Reranker:
        """Create a Reranker with a mocked model."""
        reranker = Reranker()
        reranker._model = MagicMock()
        return reranker

    def test_reorders_by_score(self):
        reranker = self._loaded_reranker()
        chunks = _make_chunks(3)
        # Reverse the natural order: chunk 2 best, chunk 0 worst
        reranker._model.predict.return_value = [0.1, 0.5, 0.9]

        result = reranker.rerank("query", chunks, top_k=3)

        assert len(result) == 3
        assert result[0]["text"] == "chunk 2 content"
        assert result[1]["text"] == "chunk 1 content"
        assert result[2]["text"] == "chunk 0 content"

    def test_truncates_to_top_k(self):
        reranker = self._loaded_reranker()
        chunks = _make_chunks(5)
        reranker._model.predict.return_value = [0.5, 0.1, 0.9, 0.3, 0.7]

        result = reranker.rerank("query", chunks, top_k=2)

        assert len(result) == 2
        assert result[0]["text"] == "chunk 2 content"  # score 0.9
        assert result[1]["text"] == "chunk 4 content"  # score 0.7

    def test_adds_rerank_score(self):
        reranker = self._loaded_reranker()
        chunks = _make_chunks(2)
        reranker._model.predict.return_value = [0.8, 0.3]

        result = reranker.rerank("query", chunks, top_k=2)

        assert result[0]["rerank_score"] == pytest.approx(0.8)
        assert result[1]["rerank_score"] == pytest.approx(0.3)

    def test_empty_input_returns_empty(self):
        reranker = self._loaded_reranker()

        result = reranker.rerank("query", [], top_k=5)

        assert result == []
        reranker._model.predict.assert_not_called()

    def test_does_not_mutate_input(self):
        reranker = self._loaded_reranker()
        chunks = _make_chunks(3)
        original_chunks = [dict(c) for c in chunks]
        reranker._model.predict.return_value = [0.1, 0.5, 0.9]

        reranker.rerank("query", chunks, top_k=2)

        # Original chunks should be unchanged
        for orig, chunk in zip(original_chunks, chunks, strict=False):
            assert chunk == orig
            assert "rerank_score" not in chunk

    def test_raises_if_not_loaded(self):
        reranker = Reranker()

        with pytest.raises(RuntimeError, match="not loaded"):
            reranker.rerank("query", _make_chunks(1), top_k=1)

    def test_preserves_chunk_metadata(self):
        reranker = self._loaded_reranker()
        chunks = [
            {"text": "content", "section": "intro", "module_id": "mod1", "score": 0.9},
        ]
        reranker._model.predict.return_value = [0.75]

        result = reranker.rerank("query", chunks, top_k=1)

        assert result[0]["section"] == "intro"
        assert result[0]["module_id"] == "mod1"
        assert result[0]["score"] == 0.9
        assert result[0]["rerank_score"] == pytest.approx(0.75)

    def test_top_k_larger_than_input(self):
        reranker = self._loaded_reranker()
        chunks = _make_chunks(2)
        reranker._model.predict.return_value = [0.8, 0.3]

        result = reranker.rerank("query", chunks, top_k=10)

        assert len(result) == 2

    def test_is_loaded_property(self):
        reranker = Reranker()
        assert not reranker.is_loaded

        reranker._model = MagicMock()
        assert reranker.is_loaded


@pytest.mark.unit
class TestGetReranker:
    """Tests for the singleton factory."""

    def test_returns_reranker_instance(self):
        import backend.app.rag.reranker as mod

        old = mod._reranker
        try:
            mod._reranker = None
            r = get_reranker()
            assert isinstance(r, Reranker)
        finally:
            mod._reranker = old

    def test_returns_same_instance(self):
        import backend.app.rag.reranker as mod

        old = mod._reranker
        try:
            mod._reranker = None
            r1 = get_reranker()
            r2 = get_reranker()
            assert r1 is r2
        finally:
            mod._reranker = old


@pytest.mark.unit
class TestRerankerLoad:
    """Tests for Reranker.load() with mocked CrossEncoder."""

    def test_load_creates_model(self):
        """load() should instantiate CrossEncoder."""
        reranker = Reranker()
        mock_ce_cls = MagicMock(return_value=MagicMock())

        with patch("sentence_transformers.CrossEncoder", mock_ce_cls):
            reranker.load()

        assert reranker.is_loaded
        mock_ce_cls.assert_called_once()

    def test_load_is_idempotent(self):
        """Calling load() twice should not re-create the model."""
        reranker = Reranker()
        mock_ce_cls = MagicMock(return_value=MagicMock())

        with patch("sentence_transformers.CrossEncoder", mock_ce_cls):
            reranker.load()
            reranker.load()

        mock_ce_cls.assert_called_once()
