"""
Tests for the KG expansion module.

Tests cover:
- Simple substring concept extraction
- Enhanced extraction with fallback to simple
- KG-based concept expansion with mock Neo4j
- Full expand_query pipeline
- Edge cases: no concepts, no Neo4j, extraction failure
- Per-subject known-concept cache, and concurrent requests for different subjects
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

import backend.app.nlp.concept_extractor as concept_extractor_module
import backend.app.rag.kg_expansion as kg_expansion_module
from backend.app.nlp.concept_extractor import ConceptExtractor
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
        # The shared extractor gets the concepts per call and is never mutated
        mock_extractor.set_known_concepts.assert_not_called()
        assert mock_extractor.extract_concepts.call_args.kwargs["known_concepts"] is concepts


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


def _adapter_with_concepts(names: set[str]) -> MagicMock:
    adapter = MagicMock()
    adapter.get_all_concept_names.return_value = set(names)
    adapter.query_concept_neighbors.return_value = []
    return adapter


SUBJECT_CONCEPTS = {
    "us_history": {"Stamp Act", "Civil War"},
    "economics": {"Inflation", "Supply and Demand"},
}


@pytest.mark.unit
class TestKnownConceptsCache:
    """get_known_concepts caches each subject's concept names with a TTL."""

    @pytest.fixture
    def adapters(self):
        adapters = {sid: _adapter_with_concepts(names) for sid, names in SUBJECT_CONCEPTS.items()}
        with patch(
            "backend.app.rag.kg_expansion.get_neo4j_adapter",
            side_effect=lambda subject_id: adapters[subject_id],
        ):
            yield adapters

    def test_loads_once_per_subject_within_the_ttl(self, adapters):
        first = kg_expansion_module.get_known_concepts("us_history")
        second = kg_expansion_module.get_known_concepts("us_history")
        economics = kg_expansion_module.get_known_concepts("economics")

        assert first == frozenset(SUBJECT_CONCEPTS["us_history"])
        assert second is first  # the same frozenset, so the extractor filters it once
        assert economics == frozenset(SUBJECT_CONCEPTS["economics"])
        adapters["us_history"].get_all_concept_names.assert_called_once()
        adapters["economics"].get_all_concept_names.assert_called_once()

    def test_none_resolves_the_default_subject(self, adapters):
        from backend.app.core.subjects import get_default_subject_id

        default_id = get_default_subject_id()
        assert kg_expansion_module.get_known_concepts() is (
            kg_expansion_module.get_known_concepts(default_id)
        )
        adapters[default_id].get_all_concept_names.assert_called_once()

    def test_reloads_after_the_ttl(self, adapters):
        kg_expansion_module.get_known_concepts("economics")
        loaded_at, concepts = kg_expansion_module._known_concepts_cache["economics"]
        kg_expansion_module._known_concepts_cache["economics"] = (
            loaded_at - kg_expansion_module.KNOWN_CONCEPTS_CACHE_TTL_SECONDS - 1,
            concepts,
        )
        adapters["economics"].get_all_concept_names.return_value = {"Inflation", "GDP"}

        assert kg_expansion_module.get_known_concepts("economics") == {"Inflation", "GDP"}
        assert adapters["economics"].get_all_concept_names.call_count == 2

    def test_clear_forces_a_reload(self, adapters):
        kg_expansion_module.get_known_concepts("us_history")
        kg_expansion_module.clear_known_concepts_cache()
        kg_expansion_module.get_known_concepts("us_history")

        assert adapters["us_history"].get_all_concept_names.call_count == 2

    def test_empty_result_is_not_cached(self, adapters):
        adapters["us_history"].get_all_concept_names.side_effect = [
            RuntimeError("Neo4j down"),
            {"Stamp Act"},
        ]

        assert kg_expansion_module.get_known_concepts("us_history") == frozenset()
        assert kg_expansion_module.get_known_concepts("us_history") == {"Stamp Act"}

    def test_unknown_subject_raises(self):
        with pytest.raises(KeyError):
            kg_expansion_module.get_known_concepts("no_such_subject")

    def test_concurrent_first_calls_load_once(self, adapters):
        barrier = threading.Barrier(8)
        results: list[frozenset[str]] = []

        def request():
            barrier.wait(timeout=5)
            results.append(kg_expansion_module.get_known_concepts("us_history"))

        threads = [threading.Thread(target=request) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert len(results) == 8
        assert all(result is results[0] for result in results)
        adapters["us_history"].get_all_concept_names.assert_called_once()


@pytest.mark.unit
class TestConcurrentSubjects:
    """Concurrent questions for different subjects match only their own concepts (#157)."""

    def test_requests_held_at_a_barrier_do_not_leak_concepts(self, monkeypatch):
        from backend.app.api.routes.ask import _expand_query
        from backend.app.rag.kg_expansion import clear_kg_expanders

        # One shared extractor, as in production; YAKE is real, spaCy is skipped.
        extractor = ConceptExtractor()
        extractor._spacy_unavailable = True
        monkeypatch.setattr(concept_extractor_module, "_concept_extractor", extractor)

        # Hold both requests at the start of extraction and release them together.
        # Storing the concepts on the shared extractor before this point (the old
        # set_known_concepts call) would let the second request overwrite the first.
        barrier = threading.Barrier(2)
        original_extract = extractor.extract_concepts

        def held_extract(*args, **kwargs):
            barrier.wait(timeout=5)
            return original_extract(*args, **kwargs)

        monkeypatch.setattr(extractor, "extract_concepts", held_extract)

        adapters = {sid: _adapter_with_concepts(names) for sid, names in SUBJECT_CONCEPTS.items()}
        question = "How did the Stamp Act cause inflation?"
        results: dict[str, list[str]] = {}
        errors: list[BaseException] = []

        def ask(subject_id: str):
            try:
                results[subject_id], _ = _expand_query(subject_id, question)
            except BaseException as e:  # surfaced below
                errors.append(e)

        clear_kg_expanders()
        try:
            with patch(
                "backend.app.rag.kg_expansion.get_neo4j_adapter",
                side_effect=lambda subject_id: adapters[subject_id],
            ):
                threads = [threading.Thread(target=ask, args=(sid,)) for sid in SUBJECT_CONCEPTS]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
        finally:
            clear_kg_expanders()

        assert errors == []
        assert results == {"us_history": ["Stamp Act"], "economics": ["Inflation"]}
        assert not barrier.broken  # both requests really were in extraction together
        assert extractor.known_concepts == set()  # the shared extractor was not mutated
