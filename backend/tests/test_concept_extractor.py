"""
Tests for multi-strategy concept extraction (backend/app/nlp/concept_extractor.py).

spaCy models, the embedding model and Neo4j are mocked: no test needs a model
download, a network connection or a running database.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import backend.app.nlp.concept_extractor as concept_extractor_module
from backend.app.nlp.concept_extractor import ConceptExtractor, ConceptMatch, get_concept_extractor

KNOWN = {"Stamp Act", "Sons of Liberty", "Civil War", "World War", "Slavery"}


def fake_nlp(ents=(), noun_chunks=()):
    """A callable standing in for a loaded spaCy pipeline."""
    doc = SimpleNamespace(
        ents=[SimpleNamespace(text=text, label_=label) for text, label in ents],
        noun_chunks=[SimpleNamespace(text=text) for text in noun_chunks],
    )
    return MagicMock(return_value=doc)


def extractor_with_nlp(nlp, known=KNOWN) -> ConceptExtractor:
    extractor = ConceptExtractor(known_concepts=set(known))
    extractor._spacy_nlp = nlp
    return extractor


@pytest.mark.unit
class TestKnownConcepts:
    def test_stop_concepts_are_ignored(self):
        extractor = ConceptExtractor(known_concepts={"Stamp Act", "Data-Type", "Review Questions"})
        assert extractor.known_concepts == {"Stamp Act"}

        extractor._concept_embeddings = {"Stamp Act": [1.0]}
        extractor.set_known_concepts({"Summary", "Civil War", "Cnx-Pi"})

        assert extractor.known_concepts == {"Civil War"}
        assert extractor._concept_embeddings == {}

    def test_defaults(self):
        extractor = ConceptExtractor()

        assert extractor.known_concepts == set()
        assert extractor.subject_id is None
        assert ConceptMatch(name="X", score=0.5, strategy="yake").original_text is None


@pytest.mark.unit
class TestPerCallKnownConcepts:
    """``known_concepts`` passed to one call is used for that call only."""

    def test_given_concepts_are_matched_without_changing_the_extractor(self):
        extractor = extractor_with_nlp(fake_nlp(noun_chunks=["the Stamp Act", "inflation"]))

        matches = extractor.extract_concepts(
            "...", strategy="ner", known_concepts=frozenset({"Inflation", "Summary"})
        )

        assert [m.name for m in matches] == ["Inflation"]
        assert extractor.known_concepts == KNOWN
        assert [m.name for m in extractor.extract_concepts("...", strategy="ner")] == ["Stamp Act"]

    def test_given_concepts_drop_stop_concepts(self):
        extractor = ConceptExtractor()
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [
            ("review questions", 0.01),
            ("inflation", 0.5),
        ]

        matches = extractor.extract_concepts(
            "...", strategy="yake", known_concepts={"Inflation", "Review Questions"}
        )

        assert [m.name for m in matches] == ["Inflation"]
        assert extractor.known_concepts == set()

    def test_a_reused_frozenset_is_filtered_once(self):
        concepts = frozenset({"Inflation", "Summary"})
        concept_extractor_module._filter_known_cached.cache_clear()

        extractor = ConceptExtractor()
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [("inflation", 0.5)]
        for _ in range(3):
            extractor.extract_concepts("...", strategy="yake", known_concepts=concepts)

        info = concept_extractor_module._filter_known_cached.cache_info()
        assert (info.misses, info.hits) == (1, 2)

    def test_embedding_with_given_concepts_does_not_touch_the_cache(self):
        vectors = {"Stamp Act": [1.0, 0.0], "Slavery": [0.0, 1.0]}
        model = MagicMock()
        model.encode_batch.side_effect = lambda names: [vectors[name] for name in names]
        model.encode_query.return_value = [0.9, 0.1]
        extractor = ConceptExtractor(embedding_model=model)

        matches = extractor.extract_concepts(
            "a tax on paper", strategy="embedding", known_concepts={"Stamp Act", "Slavery"}
        )

        assert [m.name for m in matches] == ["Stamp Act"]
        assert extractor._concept_embeddings == {}
        assert extractor.known_concepts == set()


@pytest.mark.unit
class TestMatchToKnown:
    @pytest.mark.parametrize(
        ("span", "expected"),
        [
            ("stamp act", "Stamp Act"),  # exact, case-insensitive
            ("The Stamp Act of 1765", "Stamp Act"),  # known concept inside the span
            ("the Civil War and slavery", "Civil War"),  # longest contained concept wins
            ("War", "Civil War"),  # span inside a known concept: shortest, then alphabetical
            ("liberty", "Sons of Liberty"),
            ("a matter of fact", None),  # no "act" inside "fact"
            ("   ", None),
            ("Photosynthesis", None),
        ],
    )
    def test_matching(self, span, expected):
        assert ConceptExtractor(known_concepts=set(KNOWN))._match_to_known(span) == expected


@pytest.mark.unit
class TestSpacyLoading:
    def test_missing_models_degrade_gracefully_and_are_not_retried(self):
        extractor = ConceptExtractor(known_concepts=set(KNOWN))

        with patch("spacy.load", side_effect=OSError("model not installed")) as load:
            assert extractor.spacy_nlp is None
            assert extractor.spacy_nlp is None
            assert extractor.extract_concepts("The Stamp Act", strategy="ner") == []

        assert load.call_count == 2  # en_core_sci_sm, then en_core_web_sm, only once

    def test_missing_spacy_package_degrades_gracefully(self):
        extractor = ConceptExtractor()

        with patch.dict(sys.modules, {"spacy": None}):
            assert extractor.spacy_nlp is None

    def test_falls_back_to_general_model(self):
        general = object()
        with patch("spacy.load", side_effect=[OSError("no sci model"), general]) as load:
            assert ConceptExtractor().spacy_nlp is general

        assert [call.args[0] for call in load.call_args_list] == [
            "en_core_sci_sm",
            "en_core_web_sm",
        ]

    def test_loaded_model_is_cached(self):
        model = object()
        with patch("spacy.load", return_value=model) as load:
            extractor = ConceptExtractor()
            assert extractor.spacy_nlp is model
            assert extractor.spacy_nlp is model

        assert load.call_count == 1


@pytest.mark.unit
class TestNerStrategy:
    def test_entities_and_noun_chunks_match_known_concepts(self):
        nlp = fake_nlp(
            ents=[("the Stamp Act", "LAW"), ("1765", "DATE"), ("the Civil War", "EVENT")],
            noun_chunks=["the Sons of Liberty", "it", "Review Questions", "the Stamp Act"],
        )
        matches = extractor_with_nlp(nlp).extract_concepts("...", strategy="ner")

        by_name = {m.name: m for m in matches}
        assert set(by_name) == {"Stamp Act", "Civil War", "Sons of Liberty"}
        assert by_name["Stamp Act"].score == 0.8  # entity match beats the noun-chunk match
        assert by_name["Sons of Liberty"].score == 0.6
        assert all(m.strategy == "ner" for m in matches)

    def test_dates_amounts_and_stop_spans_are_skipped(self):
        nlp = fake_nlp(ents=[("1765", "DATE"), ("Summary", "WORK_OF_ART"), ("Slavery", "ORG")])
        matches = extractor_with_nlp(nlp, known=KNOWN | {"1765"}).extract_concepts("...", "ner")

        assert [m.name for m in matches] == ["Slavery"]


@pytest.mark.unit
class TestYakeStrategy:
    def test_real_yake_matches_known_concepts(self):
        text = "The Stamp Act angered colonists. The Sons of Liberty protested the Stamp Act."
        matches = ConceptExtractor(known_concepts=set(KNOWN)).extract_concepts(text, "yake")

        names = {m.name for m in matches}
        assert "Stamp Act" in names
        assert all(0 < m.score <= 1 and m.strategy == "yake" for m in matches)

    def test_stop_keywords_are_skipped(self):
        extractor = ConceptExtractor(known_concepts={"Critical Period", "Stamp Act"})
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [
            ("review questions", 0.01),
            ("critical thinking", 0.02),
            ("stamp act", 0.5),
        ]

        matches = extractor.extract_concepts("...", strategy="yake")

        assert [(m.name, m.score) for m in matches] == [("Stamp Act", pytest.approx(1 / 1.5))]

    def test_keywords_resolving_to_one_concept_are_deduplicated(self):
        extractor = ConceptExtractor(known_concepts={"Stamp Act", "Slavery"})
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [
            ("stamp act", 0.5),
            ("stamp act protests", 0.25),  # contains "Stamp Act": same concept, better score
            ("slavery", 1.0),
        ]

        matches = extractor.extract_concepts("...", strategy="yake")

        assert [(m.name, m.score) for m in matches] == [
            ("Stamp Act", pytest.approx(1 / 1.25)),
            ("Slavery", pytest.approx(1 / 2.0)),
        ]

    def test_yake_failure_returns_no_matches(self):
        extractor = ConceptExtractor(known_concepts=set(KNOWN))
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.side_effect = RuntimeError("boom")

        assert extractor.extract_concepts("The Stamp Act", strategy="yake") == []


@pytest.mark.unit
class TestEmbeddingStrategy:
    def model(self):
        vectors = {"Stamp Act": [1.0, 0.0], "Slavery": [0.0, 1.0]}
        model = MagicMock()
        model.encode_batch.side_effect = lambda names: [vectors[name] for name in names]
        model.encode_query.return_value = [0.9, 0.1]
        return model

    def test_similar_concepts_above_threshold(self):
        model = self.model()
        extractor = ConceptExtractor(known_concepts={"Stamp Act", "Slavery"}, embedding_model=model)

        first = extractor.extract_concepts("a tax on paper", strategy="embedding")
        second = extractor.extract_concepts("a tax on paper", strategy="embedding")

        assert [m.name for m in first] == ["Stamp Act"]
        assert first[0].score == pytest.approx(0.9 / (0.81 + 0.01) ** 0.5, rel=1e-4)
        assert first[0].strategy == "embedding"
        assert [m.name for m in second] == ["Stamp Act"]
        model.encode_batch.assert_called_once()  # concept embeddings are cached

    def test_no_known_concepts(self):
        model = self.model()
        extractor = ConceptExtractor(embedding_model=model)

        assert extractor.extract_concepts("text", strategy="embedding") == []
        model.encode_query.assert_not_called()

    def test_model_failure_returns_no_matches(self):
        model = MagicMock()
        model.encode_batch.side_effect = RuntimeError("model unavailable")
        extractor = ConceptExtractor(known_concepts={"Stamp Act"}, embedding_model=model)

        assert extractor.extract_concepts("text", strategy="embedding") == []

    def test_embedding_model_is_loaded_lazily(self):
        model = object()
        with patch("backend.app.nlp.embeddings.get_embedding_model", return_value=model) as get:
            extractor = ConceptExtractor()
            assert extractor.embedding_model is model
            assert extractor.embedding_model is model

        get.assert_called_once()


@pytest.mark.unit
class TestFulltextStrategy:
    def test_uses_the_subject_adapter_and_normalizes_scores(self):
        adapter = MagicMock()
        adapter.fulltext_concept_search.side_effect = lambda keyword, limit: [
            {"name": "Stamp Act", "score": 4.0},
            {"name": "Stamp Act", "score": 8.0},
            {"name": "Summary", "score": 9.0},
            {"name": "Slavery", "score": 0.2},
        ]
        extractor = ConceptExtractor(subject_id="us_history")
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [("stamp act", 0.1)]

        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter
        ) as get_adapter:
            matches = extractor.extract_concepts("The Stamp Act", strategy="fulltext")

        get_adapter.assert_called_once_with("us_history")
        adapter.fulltext_concept_search.assert_called_once_with("stamp act", limit=5)
        adapter.close.assert_not_called()  # the registry adapter is shared
        assert [(m.name, m.score, m.strategy) for m in matches] == [
            ("Stamp Act", pytest.approx(0.8), "fulltext")
        ]

    def test_database_failure_returns_no_matches(self):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", side_effect=RuntimeError("down")
        ):
            assert ConceptExtractor().extract_concepts("The Stamp Act", "fulltext") == []

    @pytest.mark.parametrize(
        ("subject_id", "index_name"),
        [
            ("economics", "economics_fullTextConceptNames"),
            (None, "us_history_fullTextConceptNames"),  # the default subject
        ],
    )
    def test_queries_the_subject_prefixed_fulltext_index(self, subject_id, index_name):
        """The fulltext strategy must hit the index WS-I's seeding creates per subject."""
        from backend.app.kg import neo4j_adapter

        session = MagicMock()
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        extractor = ConceptExtractor(subject_id=subject_id)
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [("gdp", 0.1)]

        neo4j_adapter.clear_neo4j_adapters()
        try:
            with patch.object(neo4j_adapter.GraphDatabase, "driver", return_value=driver):
                extractor.extract_concepts("What is GDP?", strategy="fulltext")
        finally:
            neo4j_adapter.clear_neo4j_adapters()

        queried = [
            c.kwargs["index_name"] for c in session.run.call_args_list if "index_name" in c.kwargs
        ]
        assert queried == [index_name]
        assert "fullTextConceptNames" not in queried

    def test_search_terms_fall_back_to_words(self):
        extractor = ConceptExtractor()
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.side_effect = RuntimeError("boom")

        assert extractor._get_search_terms("The Stamp Act of 1765") == ["Stamp", "1765"]


@pytest.mark.unit
class TestEnsembleAndDispatch:
    def test_concepts_found_by_both_strategies_are_boosted(self):
        nlp = fake_nlp(ents=[("the Stamp Act", "LAW")], noun_chunks=["the Civil War"])
        extractor = extractor_with_nlp(nlp)
        extractor._yake_extractor = MagicMock()
        extractor._yake_extractor.extract_keywords.return_value = [("stamp act", 0.25)]

        matches = extractor.extract_concepts("...", strategy="ensemble")

        by_name = {m.name: m for m in matches}
        assert by_name["Stamp Act"].score == pytest.approx(0.96)  # max(0.8, 0.8) * 1.2
        assert by_name["Civil War"].score == pytest.approx(0.6)
        assert all(m.strategy == "ensemble" for m in matches)
        assert [m.name for m in matches] == ["Stamp Act", "Civil War"]  # sorted by score

    def test_a_failing_strategy_does_not_break_the_ensemble(self):
        extractor = ConceptExtractor(known_concepts=set(KNOWN))
        extractor._spacy_unavailable = True
        with patch.object(extractor, "_extract_ner", side_effect=RuntimeError("boom")):
            matches = extractor.extract_concepts(
                "The Stamp Act angered colonists. The Stamp Act raised taxes.", "ensemble"
            )

        assert "Stamp Act" in {m.name for m in matches}

    def test_top_k_and_empty_text(self):
        nlp = fake_nlp(noun_chunks=["Stamp Act", "Civil War", "Slavery"])
        extractor = extractor_with_nlp(nlp)

        assert len(extractor.extract_concepts("...", strategy="ner", top_k=2)) == 2
        assert extractor.extract_concepts("", strategy="ner") == []

    def test_unknown_strategy(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            ConceptExtractor().extract_concepts("text", strategy="magic")  # type: ignore[arg-type]


@pytest.mark.unit
class TestSingleton:
    def test_get_concept_extractor(self, monkeypatch):
        monkeypatch.setattr(concept_extractor_module, "_concept_extractor", None)

        first = get_concept_extractor({"Stamp Act"})
        same = get_concept_extractor()
        updated = get_concept_extractor({"Civil War", "Summary"})

        assert first is same is updated
        assert updated.known_concepts == {"Civil War"}
