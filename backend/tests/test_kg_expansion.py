"""
Tests for the KG expansion module.

Tests cover:
- Simple substring concept extraction
- Enhanced extraction with fallback to simple
- KG-based concept expansion with mock Neo4j
- Full expand_query pipeline
- Edge cases: no concepts, no Neo4j, extraction failure
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.rag.kg_expansion import KGExpander


@pytest.mark.unit
class TestExtractSimple:
    """Tests for simple substring concept extraction."""

    def test_finds_exact_match(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"photosynthesis", "mitosis", "cell division"}
        result = expander.extract_concepts_from_query("Explain photosynthesis", concepts)
        assert "photosynthesis" in result

    def test_case_insensitive(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"Photosynthesis"}
        result = expander.extract_concepts_from_query("tell me about photosynthesis", concepts)
        assert "Photosynthesis" in result

    def test_multiple_concepts(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"photosynthesis", "chloroplast", "mitosis"}
        result = expander.extract_concepts_from_query(
            "How do chloroplast and photosynthesis relate?", concepts
        )
        assert "photosynthesis" in result
        assert "chloroplast" in result

    def test_no_match(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"photosynthesis", "chloroplast"}
        result = expander.extract_concepts_from_query("What is quantum physics?", concepts)
        assert result == []

    def test_prefers_longer_matches(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"cell", "cell division"}
        result = expander.extract_concepts_from_query("Explain cell division", concepts)
        # Longer match should come first
        assert result[0] == "cell division"

    def test_max_five_concepts(self):
        expander = KGExpander(extraction_strategy="simple")
        # All of these are substrings of the query
        concepts = {f"concept{i}" for i in range(10)}
        query = " ".join(f"concept{i}" for i in range(10))
        result = expander.extract_concepts_from_query(query, concepts)
        assert len(result) <= 5

    def test_empty_query(self):
        expander = KGExpander(extraction_strategy="simple")
        concepts = {"photosynthesis"}
        result = expander.extract_concepts_from_query("", concepts)
        assert result == []

    def test_empty_concepts(self):
        expander = KGExpander(extraction_strategy="simple")
        result = expander.extract_concepts_from_query("What is photosynthesis?", set())
        assert result == []


@pytest.mark.unit
class TestExtractEnhanced:
    """Tests for enhanced concept extraction with fallback."""

    def test_falls_back_to_simple_on_extractor_failure(self):
        expander = KGExpander(extraction_strategy="ensemble")
        # Force extractor to raise
        mock_extractor = MagicMock()
        mock_extractor.extract_concepts.side_effect = RuntimeError("NLP model not loaded")
        expander._concept_extractor = mock_extractor

        concepts = {"photosynthesis"}
        result = expander.extract_concepts_from_query("Explain photosynthesis", concepts)
        # Should fall back to simple extraction
        assert "photosynthesis" in result

    def test_falls_back_when_extractor_returns_empty(self):
        expander = KGExpander(extraction_strategy="ensemble")
        mock_extractor = MagicMock()
        mock_extractor.extract_concepts.return_value = []
        expander._concept_extractor = mock_extractor

        concepts = {"photosynthesis"}
        result = expander.extract_concepts_from_query("Explain photosynthesis", concepts)
        assert "photosynthesis" in result

    def test_uses_enhanced_when_available(self):
        expander = KGExpander(extraction_strategy="ensemble")
        mock_match = MagicMock()
        mock_match.name = "photosynthesis"
        mock_extractor = MagicMock()
        mock_extractor.extract_concepts.return_value = [mock_match]
        expander._concept_extractor = mock_extractor

        concepts = {"photosynthesis", "chloroplast"}
        result = expander.extract_concepts_from_query("Explain photosynthesis", concepts)
        assert result == ["photosynthesis"]
        mock_extractor.set_known_concepts.assert_called_once_with(concepts)


@pytest.mark.unit
class TestExpandWithKG:
    """Tests for KG-based concept expansion."""

    def test_expands_with_neighbors(self):
        expander = KGExpander(extraction_strategy="simple")
        mock_adapter = MagicMock()
        mock_adapter.query_concept_neighbors.return_value = [
            {"name": "chloroplast"},
            {"name": "ATP"},
        ]
        expander.neo4j_adapter = mock_adapter

        result = expander.expand_with_kg(["photosynthesis"])
        assert "photosynthesis" in result
        assert "chloroplast" in result
        assert "ATP" in result

    def test_returns_original_without_neo4j(self):
        expander = KGExpander(extraction_strategy="simple")
        expander.neo4j_adapter = None

        result = expander.expand_with_kg(["photosynthesis"])
        assert result == ["photosynthesis"]

    def test_handles_neo4j_error_gracefully(self):
        expander = KGExpander(extraction_strategy="simple")
        mock_adapter = MagicMock()
        mock_adapter.query_concept_neighbors.side_effect = RuntimeError("Connection lost")
        expander.neo4j_adapter = mock_adapter

        result = expander.expand_with_kg(["photosynthesis"])
        # Should still return original concepts even on error
        assert "photosynthesis" in result

    def test_deduplicates_expanded_concepts(self):
        expander = KGExpander(extraction_strategy="simple")
        mock_adapter = MagicMock()
        # Both concepts return "ATP" as neighbor
        mock_adapter.query_concept_neighbors.side_effect = [
            [{"name": "ATP"}],
            [{"name": "ATP"}],
        ]
        expander.neo4j_adapter = mock_adapter

        result = expander.expand_with_kg(["photosynthesis", "chloroplast"])
        assert result.count("ATP") == 1  # No duplicates


@pytest.mark.unit
class TestExpandQuery:
    """Tests for full expand_query pipeline."""

    def test_full_pipeline(self):
        expander = KGExpander(extraction_strategy="simple")
        mock_adapter = MagicMock()
        mock_adapter.query_concept_neighbors.return_value = [
            {"name": "chloroplast"},
        ]
        expander.neo4j_adapter = mock_adapter

        concepts = {"photosynthesis", "mitosis"}
        result = expander.expand_query("Explain photosynthesis", concepts)

        assert result["original_query"] == "Explain photosynthesis"
        assert "photosynthesis" in result["extracted_concepts"]
        assert "chloroplast" in result["expanded_concepts"]
        assert "photosynthesis" in result["expanded_query"]
        assert "chloroplast" in result["expanded_query"]

    def test_no_expansion_when_no_concepts(self):
        expander = KGExpander(extraction_strategy="simple")
        expander.neo4j_adapter = MagicMock()

        result = expander.expand_query("What is quantum physics?", {"photosynthesis"})
        assert result["extracted_concepts"] == []
        assert result["expanded_query"] == "What is quantum physics?"
        assert result["expansion_count"] == 0

    def test_expansion_count(self):
        expander = KGExpander(extraction_strategy="simple")
        mock_adapter = MagicMock()
        mock_adapter.query_concept_neighbors.return_value = [
            {"name": "chloroplast"},
            {"name": "ATP"},
        ]
        expander.neo4j_adapter = mock_adapter

        concepts = {"photosynthesis"}
        result = expander.expand_query("Explain photosynthesis", concepts)

        # 1 extracted, expanded to 3 total -> 2 new concepts
        assert result["expansion_count"] == 2


@pytest.mark.unit
class TestKGExpanderInit:
    """Tests for KGExpander initialization."""

    def test_defaults(self):
        expander = KGExpander()
        assert expander.extraction_strategy == "ensemble"
        assert expander.neo4j_adapter is None
        assert expander.subject_id is None

    def test_custom_params(self):
        expander = KGExpander(max_hops=3, extraction_strategy="ner", subject_id="biology")
        assert expander.max_hops == 3
        assert expander.extraction_strategy == "ner"
        assert expander.subject_id == "biology"

    def test_connect_with_subject(self):
        mock_adapter = MagicMock()
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            expander = KGExpander(subject_id="us_history")
            expander.connect()
            assert expander.neo4j_adapter is mock_adapter

    def test_connect_without_subject(self):
        mock_adapter = MagicMock()
        with patch("backend.app.rag.kg_expansion.Neo4jAdapter", return_value=mock_adapter):
            expander = KGExpander()
            expander.connect()
            assert expander.neo4j_adapter is mock_adapter
            mock_adapter.connect.assert_called_once()

    def test_close(self):
        expander = KGExpander()
        mock_adapter = MagicMock()
        expander.neo4j_adapter = mock_adapter
        expander.close()
        mock_adapter.close.assert_called_once()
