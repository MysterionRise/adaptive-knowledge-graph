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
        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter", return_value=mock_adapter
        ) as factory:
            expander = KGExpander(subject_id="us_history")
            expander.connect()
            assert expander.neo4j_adapter is mock_adapter
        factory.assert_called_once_with("us_history")

    def test_connect_without_subject_uses_default_subject_adapter(self):
        """No subject -> the registry adapter for default_subject (prefixed labels)."""
        mock_adapter = MagicMock()
        with (
            patch(
                "backend.app.rag.kg_expansion.get_neo4j_adapter", return_value=mock_adapter
            ) as factory,
            patch("backend.app.kg.neo4j_adapter.Neo4jAdapter") as raw_adapter,
        ):
            expander = KGExpander()
            expander.connect()
            assert expander.neo4j_adapter is mock_adapter
        factory.assert_called_once_with(None)
        raw_adapter.assert_not_called()

    def test_close_releases_shared_adapter_without_closing_it(self):
        expander = KGExpander()
        mock_adapter = MagicMock()
        expander.neo4j_adapter = mock_adapter
        expander.close()
        mock_adapter.close.assert_not_called()
        assert expander.neo4j_adapter is None


@pytest.mark.unit
class TestFactories:
    """get_kg_expander / get_all_concepts_from_neo4j resolve the default subject."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from backend.app.rag.kg_expansion import clear_kg_expanders

        clear_kg_expanders()
        yield
        clear_kg_expanders()

    def test_get_kg_expander_none_resolves_default_subject(self):
        from backend.app.core.subjects import get_default_subject_id
        from backend.app.rag.kg_expansion import get_kg_expander

        default_id = get_default_subject_id()
        with patch("backend.app.rag.kg_expansion.get_neo4j_adapter") as factory:
            expander = get_kg_expander()
            assert expander.subject_id == default_id
            assert get_kg_expander(default_id) is expander
        factory.assert_called_once_with(default_id)

    def test_get_kg_expander_caches_per_subject(self):
        from backend.app.rag.kg_expansion import get_kg_expander

        with patch("backend.app.rag.kg_expansion.get_neo4j_adapter"):
            economics = get_kg_expander("economics")
            history = get_kg_expander("us_history")
        assert economics is not history
        assert economics.subject_id == "economics"

    def test_concurrent_first_calls_create_one_expander(self):
        import threading
        import time

        from backend.app.rag.kg_expansion import get_kg_expander

        def slow_adapter(subject_id):
            time.sleep(0.05)  # widen the race window
            return MagicMock()

        results: list[KGExpander] = []
        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter", side_effect=slow_adapter
        ) as factory:
            threads = [
                threading.Thread(target=lambda: results.append(get_kg_expander("us_history")))
                for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        factory.assert_called_once_with("us_history")
        assert len(results) == 8
        assert all(result is results[0] for result in results)

    def test_get_kg_expander_unknown_subject_raises(self):
        from backend.app.rag.kg_expansion import get_kg_expander

        with pytest.raises(KeyError):
            get_kg_expander("no_such_subject")

    def test_get_kg_expander_survives_connection_failure(self):
        from backend.app.rag.kg_expansion import get_kg_expander

        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter",
            side_effect=RuntimeError("Neo4j down"),
        ):
            expander = get_kg_expander("us_history")
        assert expander.neo4j_adapter is None

    def test_get_all_concepts_uses_subject_adapter(self):
        from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j

        adapter = MagicMock()
        adapter.get_all_concept_names.return_value = {"Civil War", "Reconstruction"}
        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter", return_value=adapter
        ) as factory:
            assert get_all_concepts_from_neo4j() == {"Civil War", "Reconstruction"}
            assert get_all_concepts_from_neo4j("economics") == {"Civil War", "Reconstruction"}
        assert [c.args for c in factory.call_args_list] == [(None,), ("economics",)]

    def test_get_all_concepts_returns_empty_set_on_error(self):
        from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j

        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter",
            side_effect=RuntimeError("Neo4j down"),
        ):
            assert get_all_concepts_from_neo4j("us_history") == set()
