"""
Tests for the OpenSearch retriever module.

Tests cover:
- Reciprocal rank fusion (RRF) merge logic
- Result formatting
- Retrieval mode delegation (knn vs hybrid)
- kNN and hybrid query construction
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestReciprocalRankFusion:
    """Tests for RRF merge logic."""

    def _make_retriever(self):
        """Create a retriever with mocked dependencies."""
        with patch("backend.app.rag.retriever.get_embedding_model"):
            from backend.app.rag.retriever import OpenSearchRetriever

            return OpenSearchRetriever()

    def _make_hit(self, doc_id: str, text: str, score: float = 1.0) -> dict:
        return {
            "_id": doc_id,
            "_score": score,
            "_source": {
                "text": text,
                "id": doc_id,
                "module_id": "mod_1",
                "module_title": "Test Module",
                "section": "Section 1",
                "key_terms": ["term1"],
                "attribution": "Test",
            },
        }

    def test_merges_knn_and_bm25(self):
        retriever = self._make_retriever()
        knn_hits = [self._make_hit("doc1", "Text 1"), self._make_hit("doc2", "Text 2")]
        bm25_hits = [self._make_hit("doc2", "Text 2"), self._make_hit("doc3", "Text 3")]

        result = retriever._reciprocal_rank_fusion(knn_hits, bm25_hits, k=60, top_k=10)

        doc_ids = [r["id"] for r in result]
        # doc2 appears in both, should have highest RRF score
        assert doc_ids[0] == "doc2"
        assert len(result) == 3

    def test_respects_top_k(self):
        retriever = self._make_retriever()
        knn_hits = [self._make_hit(f"doc{i}", f"Text {i}") for i in range(5)]
        bm25_hits = [self._make_hit(f"doc{i+5}", f"Text {i+5}") for i in range(5)]

        result = retriever._reciprocal_rank_fusion(knn_hits, bm25_hits, k=60, top_k=3)
        assert len(result) == 3

    def test_empty_inputs(self):
        retriever = self._make_retriever()
        result = retriever._reciprocal_rank_fusion([], [], k=60, top_k=10)
        assert result == []

    def test_one_side_empty(self):
        retriever = self._make_retriever()
        knn_hits = [self._make_hit("doc1", "Text 1")]
        result = retriever._reciprocal_rank_fusion(knn_hits, [], k=60, top_k=10)
        assert len(result) == 1
        assert result[0]["id"] == "doc1"

    def test_rrf_score_calculation(self):
        retriever = self._make_retriever()
        k = 60
        knn_hits = [self._make_hit("doc1", "Text 1")]
        bm25_hits = [self._make_hit("doc1", "Text 1")]

        result = retriever._reciprocal_rank_fusion(knn_hits, bm25_hits, k=k, top_k=10)
        # doc1 is rank 1 in both: score = 1/(60+1) + 1/(60+1) = 2/61
        expected_score = 2.0 / (k + 1)
        assert abs(result[0]["score"] - expected_score) < 1e-9

    def test_preserves_metadata(self):
        retriever = self._make_retriever()
        hit = self._make_hit("doc1", "Sample text")
        result = retriever._reciprocal_rank_fusion([hit], [], k=60, top_k=10)

        assert result[0]["text"] == "Sample text"
        assert result[0]["module_id"] == "mod_1"
        assert result[0]["module_title"] == "Test Module"
        assert result[0]["section"] == "Section 1"
        assert result[0]["key_terms"] == ["term1"]
        assert result[0]["attribution"] == "Test"


@pytest.mark.unit
class TestFormatResults:
    """Tests for result formatting."""

    def _make_retriever(self):
        with patch("backend.app.rag.retriever.get_embedding_model"):
            from backend.app.rag.retriever import OpenSearchRetriever

            return OpenSearchRetriever()

    def test_formats_hits(self):
        retriever = self._make_retriever()
        results = {
            "hits": {
                "hits": [
                    {
                        "_score": 0.95,
                        "_source": {
                            "text": "Photosynthesis is...",
                            "id": "chunk_1",
                            "module_id": "mod_1",
                            "module_title": "Biology",
                            "section": "Chapter 5",
                            "key_terms": ["photosynthesis"],
                            "attribution": "OpenStax",
                        },
                    }
                ]
            }
        }
        formatted = retriever._format_results(results, "knn")

        assert len(formatted) == 1
        assert formatted[0]["text"] == "Photosynthesis is..."
        assert formatted[0]["score"] == 0.95
        assert formatted[0]["id"] == "chunk_1"

    def test_empty_results(self):
        retriever = self._make_retriever()
        results = {"hits": {"hits": []}}
        formatted = retriever._format_results(results, "knn")
        assert formatted == []


@pytest.mark.unit
class TestRetrieveMode:
    """Tests for retrieve() mode delegation."""

    def _make_retriever(self):
        with patch("backend.app.rag.retriever.get_embedding_model") as mock_embed:
            from backend.app.rag.retriever import OpenSearchRetriever

            mock_embed_instance = MagicMock()
            mock_embed_instance.encode_query.return_value = [0.1] * 1024
            mock_embed.return_value = mock_embed_instance
            retriever = OpenSearchRetriever()
            retriever.client = MagicMock()
            retriever.client.search.return_value = {"hits": {"hits": []}}
            return retriever

    def test_knn_mode(self):
        retriever = self._make_retriever()
        with patch("backend.app.rag.retriever.settings") as mock_settings:
            mock_settings.retrieval_mode = "knn"
            mock_settings.rag_retrieval_top_k = 5
            retriever.retrieve("test query", top_k=5)
            # Should call search once (kNN only)
            assert retriever.client.search.call_count == 1

    def test_hybrid_mode(self):
        retriever = self._make_retriever()
        with patch("backend.app.rag.retriever.settings") as mock_settings:
            mock_settings.retrieval_mode = "hybrid"
            mock_settings.rag_retrieval_top_k = 5
            retriever.retrieve("test query", top_k=5)
            # Should call search twice (kNN + BM25)
            assert retriever.client.search.call_count == 2


@pytest.mark.unit
class TestCollectionInfo:
    """Tests for get_collection_info."""

    def _make_retriever(self):
        with patch("backend.app.rag.retriever.get_embedding_model"):
            from backend.app.rag.retriever import OpenSearchRetriever

            return OpenSearchRetriever()

    def test_index_exists(self):
        retriever = self._make_retriever()
        retriever.client = MagicMock()
        retriever.client.indices.exists.return_value = True
        retriever.client.indices.stats.return_value = {
            "indices": {
                retriever.index_name: {
                    "total": {"docs": {"count": 42}},
                }
            }
        }
        info = retriever.get_collection_info()
        assert info["exists"] is True
        assert info["doc_count"] == 42

    def test_index_not_exists(self):
        retriever = self._make_retriever()
        retriever.client = MagicMock()
        retriever.client.indices.exists.return_value = False
        info = retriever.get_collection_info()
        assert info["exists"] is False
