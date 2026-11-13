"""
Tests for the Neo4j adapter module.

Tests cover:
- Label generation with/without prefix
- Connection lifecycle (connect, close, get_session)
- Database clearing with prefix isolation vs full clear
- Knowledge graph persistence (concepts, modules, relationships)
- Concept neighbor queries
- Graph statistics with and without prefix
- Fulltext concept search
- Vector similarity search
- Chunk node operations (create, NEXT relationships, batching)
- Factory functions (caching, cleanup)
"""

import ast
import inspect
import warnings
from unittest.mock import MagicMock, patch

import neo4j
import pytest
from neo4j.exceptions import ConfigurationError, ServiceUnavailable

from backend.app.kg import neo4j_adapter
from backend.app.kg.neo4j_adapter import (
    QUIET_READ_OPTIONS,
    Neo4jAdapter,
    _neo4j_adapters,
    clear_neo4j_adapters,
    get_neo4j_adapter,
)
from backend.app.kg.schema import (
    ChunkNode,
    ConceptNode,
    KnowledgeGraph,
    ModuleNode,
    Relationship,
    RelationshipType,
)

# ==========================================================================
# Helpers
# ==========================================================================


def _make_adapter(label_prefix=None, database="neo4j"):
    """Create a Neo4jAdapter with a mock driver attached."""
    adapter = Neo4jAdapter(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        database=database,
        label_prefix=label_prefix,
    )
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter.driver = mock_driver
    return adapter, mock_session


def _make_mock_result(records):
    """Create a mock result that is iterable and supports .single()."""
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(records))
    if records:
        mock_result.single.return_value = records[0]
    else:
        mock_result.single.return_value = None
    return mock_result


def _make_sample_kg():
    """Create a sample KnowledgeGraph for testing persist operations."""
    return KnowledgeGraph(
        concepts={
            "Photosynthesis": ConceptNode(
                name="Photosynthesis",
                key_term=True,
                frequency=5,
                importance_score=0.9,
                source_modules=["m1"],
            ),
            "Chloroplast": ConceptNode(
                name="Chloroplast",
                key_term=False,
                frequency=3,
                importance_score=0.7,
                source_modules=["m1"],
            ),
        },
        modules={
            "m1": ModuleNode(
                module_id="m1",
                title="Biology 101",
                key_terms=["photosynthesis", "chloroplast"],
            ),
        },
        relationships=[
            Relationship(
                source="m1",
                target="Photosynthesis",
                type=RelationshipType.COVERS,
                weight=1.0,
                confidence=0.9,
            ),
            Relationship(
                source="Photosynthesis",
                target="Chloroplast",
                type=RelationshipType.RELATED,
                weight=0.8,
                confidence=0.85,
            ),
            Relationship(
                source="Chloroplast",
                target="Photosynthesis",
                type=RelationshipType.PREREQ,
                weight=0.6,
                confidence=0.7,
            ),
        ],
    )


def _make_sample_chunks():
    """Create sample ChunkNode objects for testing chunk operations."""
    chunk1 = ChunkNode(
        chunk_id="c1",
        text="First chunk text.",
        chunk_index=0,
        start_char=0,
        end_char=17,
        module_id="m1",
        section="Intro",
        text_embedding=[0.1, 0.2, 0.3],
        previous_chunk_id=None,
        next_chunk_id="c2",
    )
    chunk2 = ChunkNode(
        chunk_id="c2",
        text="Second chunk text.",
        chunk_index=1,
        start_char=18,
        end_char=36,
        module_id="m1",
        section="Intro",
        text_embedding=[0.4, 0.5, 0.6],
        previous_chunk_id="c1",
        next_chunk_id="c3",
    )
    chunk3 = ChunkNode(
        chunk_id="c3",
        text="Third chunk text.",
        chunk_index=2,
        start_char=37,
        end_char=54,
        module_id="m1",
        section="Body",
        text_embedding=[0.7, 0.8, 0.9],
        previous_chunk_id="c2",
        next_chunk_id=None,
    )
    return [chunk1, chunk2, chunk3]


# ==========================================================================
# Test Classes
# ==========================================================================


@pytest.mark.unit
class TestGetLabel:
    """Tests for _get_label with and without prefix."""

    def test_with_prefix(self):
        adapter = Neo4jAdapter(label_prefix="us_history")
        assert adapter._get_label("Concept") == "us_history_Concept"
        assert adapter._get_label("Module") == "us_history_Module"
        assert adapter._get_label("Chunk") == "us_history_Chunk"

    def test_without_prefix(self):
        adapter = Neo4jAdapter(label_prefix=None)
        assert adapter._get_label("Concept") == "Concept"
        assert adapter._get_label("Module") == "Module"
        assert adapter._get_label("Chunk") == "Chunk"

    def test_empty_prefix_treated_as_no_prefix(self):
        adapter = Neo4jAdapter(label_prefix="")
        # Empty string is falsy, so no prefix applied
        assert adapter._get_label("Concept") == "Concept"

    def test_arbitrary_label(self):
        adapter = Neo4jAdapter(label_prefix="bio")
        assert adapter._get_label("CustomLabel") == "bio_CustomLabel"


@pytest.mark.unit
class TestConnect:
    """Tests for connect() - success and failure paths."""

    @patch("backend.app.kg.neo4j_adapter.GraphDatabase")
    def test_connect_success(self, mock_graph_db):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"test": 1}

        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_graph_db.driver.return_value = mock_driver

        adapter = Neo4jAdapter(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )
        adapter.connect()

        assert adapter.driver is mock_driver
        mock_graph_db.driver.assert_called_once_with(
            "bolt://localhost:7687", auth=("neo4j", "password")
        )
        # Verify the connection test query was executed
        mock_session.run.assert_called_once_with("RETURN 1 as test")
        mock_result.single.assert_called_once()

    @patch("backend.app.kg.neo4j_adapter.GraphDatabase")
    def test_connect_failure_raises(self, mock_graph_db):
        mock_graph_db.driver.side_effect = Exception("Connection refused")

        adapter = Neo4jAdapter(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )

        with pytest.raises(Exception, match="Connection refused"):
            adapter.connect()

    @patch("backend.app.kg.neo4j_adapter.GraphDatabase")
    def test_connect_session_failure_raises(self, mock_graph_db):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Auth failed")
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_graph_db.driver.return_value = mock_driver

        adapter = Neo4jAdapter(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )

        with pytest.raises(Exception, match="Auth failed"):
            adapter.connect()


@pytest.mark.unit
class TestClose:
    """Tests for close() - with and without driver."""

    def test_close_with_driver(self):
        adapter = Neo4jAdapter()
        mock_driver = MagicMock()
        adapter.driver = mock_driver

        adapter.close()
        mock_driver.close.assert_called_once()

    def test_close_without_driver_is_noop(self):
        adapter = Neo4jAdapter()
        adapter.driver = None
        # Should not raise
        adapter.close()


@pytest.mark.unit
class TestGetSession:
    """Tests for _get_session() assertion behavior."""

    def test_raises_when_driver_is_none(self):
        adapter = Neo4jAdapter()
        adapter.driver = None

        with pytest.raises(RuntimeError, match="Not connected. Call connect\\(\\) first."):
            adapter._get_session()

    def test_returns_session_when_driver_exists(self):
        adapter = Neo4jAdapter(database="testdb")
        mock_driver = MagicMock()
        adapter.driver = mock_driver

        session = adapter._get_session()

        mock_driver.session.assert_called_once_with(database="testdb")
        assert session == mock_driver.session(database="testdb")

    def test_passes_session_options_to_the_driver(self):
        adapter = Neo4jAdapter(database="testdb")
        adapter.driver = MagicMock()

        adapter._get_session(fetch_size=10)

        adapter.driver.session.assert_called_once_with(database="testdb", fetch_size=10)


@pytest.mark.unit
class TestQueryConceptNeighbors:
    """Tests for query_concept_neighbors()."""

    def test_returns_neighbors(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        mock_session.run.return_value = _make_mock_result(
            [
                {"name": "Chloroplast", "importance_score": 0.8, "key_term": True},
                {"name": "ATP", "importance_score": 0.7, "key_term": False},
            ]
        )

        result = adapter.query_concept_neighbors("Photosynthesis", max_hops=2)

        assert len(result) == 2
        assert result[0]["name"] == "Chloroplast"
        assert result[1]["name"] == "ATP"

        # Verify the Cypher query uses the prefixed label
        cypher_call = mock_session.run.call_args
        assert "bio_Concept" in cypher_call[0][0]
        assert cypher_call[1]["name"] == "Photosynthesis"
        # The strongest links first; ties go to importance, then the name, so the LIMIT
        # keeps the same neighbours
        assert "ORDER BY weight DESC, importance_score DESC, name" in cypher_call[0][0]
        assert "[:RELATED|PREREQ*1..2]" in cypher_call[0][0]  # not through Module nodes
        # only association scores rank; a PREREQ edge's fixed weight does not
        assert "CASE type(r) WHEN 'RELATED' THEN" in cypher_call[0][0]

    def test_empty_results(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        mock_session.run.return_value = _make_mock_result([])

        result = adapter.query_concept_neighbors("NonExistent")

        assert result == []

    def test_uses_correct_label_without_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        mock_session.run.return_value = _make_mock_result([])

        adapter.query_concept_neighbors("Photosynthesis")

        cypher_call = mock_session.run.call_args
        query = cypher_call[0][0]
        assert "Concept" in query
        # Should NOT have a prefix
        assert "None_Concept" not in query

    def test_default_max_hops_is_one(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result([])

        adapter.query_concept_neighbors("Photosynthesis")

        cypher_call = mock_session.run.call_args
        query = cypher_call[0][0]
        assert "*1..1" in query


@pytest.mark.unit
class TestGetGraphStats:
    """Tests for get_graph_stats() with and without prefix."""

    def test_with_prefix_counts_per_label(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")

        # Set up return values for each session.run call in order:
        # 1. Concept count
        # 2. Module count
        # 3. Chunk count
        # 4. Concept relationships
        # 5. Module relationships
        concept_count = MagicMock()
        concept_count.single.return_value = {"count": 50}

        module_count = MagicMock()
        module_count.single.return_value = {"count": 10}

        chunk_count = MagicMock()
        chunk_count.single.return_value = {"count": 200}

        concept_rels = MagicMock()
        concept_rels.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "RELATED", "count": 30},
                    {"type": "PREREQ", "count": 15},
                ]
            )
        )

        module_rels = MagicMock()
        module_rels.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "COVERS", "count": 40},
                ]
            )
        )

        mock_session.run.side_effect = [
            concept_count,
            module_count,
            chunk_count,
            concept_rels,
            module_rels,
        ]

        stats = adapter.get_graph_stats()

        assert stats["Concept_count"] == 50
        assert stats["Module_count"] == 10
        assert stats["Chunk_count"] == 200
        assert stats["RELATED_relationships"] == 30
        assert stats["PREREQ_relationships"] == 15
        assert stats["COVERS_relationships"] == 40

        # Verify queries use prefixed labels
        calls = mock_session.run.call_args_list
        assert "bio_Concept" in calls[0][0][0]
        assert "bio_Module" in calls[1][0][0]
        assert "bio_Chunk" in calls[2][0][0]

    def test_without_prefix_counts_all(self):
        adapter, mock_session = _make_adapter(label_prefix=None)

        # labels query
        labels_result = MagicMock()
        labels_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"labels": ["Concept"], "count": 100},
                    {"labels": ["Module"], "count": 20},
                    {"labels": ["Chunk"], "count": 500},
                ]
            )
        )

        # relationships query
        rels_result = MagicMock()
        rels_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "COVERS", "count": 80},
                    {"type": "RELATED", "count": 60},
                ]
            )
        )

        mock_session.run.side_effect = [labels_result, rels_result]

        stats = adapter.get_graph_stats()

        assert stats["Concept_count"] == 100
        assert stats["Module_count"] == 20
        assert stats["Chunk_count"] == 500
        assert stats["COVERS_relationships"] == 80
        assert stats["RELATED_relationships"] == 60

    def test_without_prefix_handles_empty_labels(self):
        adapter, mock_session = _make_adapter(label_prefix=None)

        labels_result = MagicMock()
        labels_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"labels": [], "count": 5},
                ]
            )
        )

        rels_result = MagicMock()
        rels_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session.run.side_effect = [labels_result, rels_result]

        stats = adapter.get_graph_stats()
        assert stats["Unknown_count"] == 5

    def test_with_prefix_relationship_accumulation(self):
        """Test that relationship counts from concepts and modules are accumulated."""
        adapter, mock_session = _make_adapter(label_prefix="test")

        concept_count = MagicMock()
        concept_count.single.return_value = {"count": 10}

        module_count = MagicMock()
        module_count.single.return_value = {"count": 5}

        chunk_count = MagicMock()
        chunk_count.single.return_value = {"count": 50}

        # Concept nodes have COVERS relationships too (same key)
        concept_rels = MagicMock()
        concept_rels.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "COVERS", "count": 10},
                ]
            )
        )

        module_rels = MagicMock()
        module_rels.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "COVERS", "count": 20},
                ]
            )
        )

        mock_session.run.side_effect = [
            concept_count,
            module_count,
            chunk_count,
            concept_rels,
            module_rels,
        ]

        stats = adapter.get_graph_stats()
        # 10 from concept rels + 20 from module rels = 30
        assert stats["COVERS_relationships"] == 30


@pytest.mark.unit
class TestClearDatabase:
    """Tests for clear_database() with prefix isolation."""

    def test_with_prefix_deletes_only_prefixed_nodes(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")

        adapter.clear_database()

        calls = mock_session.run.call_args_list
        assert len(calls) == 3
        assert "bio_Concept" in calls[0][0][0]
        assert "bio_Module" in calls[1][0][0]
        assert "bio_Chunk" in calls[2][0][0]
        for c in calls:
            assert "DETACH DELETE" in c[0][0]

    def test_without_prefix_deletes_all_nodes(self):
        adapter, mock_session = _make_adapter(label_prefix=None)

        adapter.clear_database()

        calls = mock_session.run.call_args_list
        assert len(calls) == 1
        assert "MATCH (n) DETACH DELETE n" in calls[0][0][0]


@pytest.mark.unit
class TestPersistKnowledgeGraph:
    """Tests for persist_knowledge_graph() with a mock KnowledgeGraph."""

    def test_creates_concepts_modules_and_relationships(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        kg = _make_sample_kg()

        adapter.persist_knowledge_graph(kg)

        calls = mock_session.run.call_args_list

        # Should have calls for:
        # 2 concepts + 1 module + 3 relationships = 6 calls total
        assert len(calls) == 6

        # First two calls are concept MERGE
        concept_queries = [c[0][0] for c in calls[:2]]
        for q in concept_queries:
            assert "MERGE" in q
            assert "test_Concept" in q

        # Third call is module MERGE
        module_query = calls[2][0][0]
        assert "MERGE" in module_query
        assert "test_Module" in module_query

        # Relationships
        covers_query = calls[3][0][0]
        assert "COVERS" in covers_query
        assert "test_Module" in covers_query
        assert "test_Concept" in covers_query

        related_query = calls[4][0][0]
        assert "RELATED" in related_query

        prereq_query = calls[5][0][0]
        assert "PREREQ" in prereq_query

    def test_concept_node_properties_are_passed(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        kg = KnowledgeGraph(
            concepts={
                "DNA": ConceptNode(
                    name="DNA",
                    key_term=True,
                    frequency=10,
                    importance_score=0.95,
                    source_modules=["m2"],
                ),
            },
            modules={},
            relationships=[],
        )

        adapter.persist_knowledge_graph(kg)

        concept_call = mock_session.run.call_args_list[0]
        assert concept_call[1]["name"] == "DNA"
        assert concept_call[1]["key_term"] is True
        assert concept_call[1]["frequency"] == 10
        assert concept_call[1]["importance_score"] == 0.95
        assert concept_call[1]["source_modules"] == ["m2"]
        # Optional fields default to None / []
        assert concept_call[1]["definition"] is None
        assert concept_call[1]["aliases"] == []

    def test_concept_definition_and_aliases_are_persisted(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        kg = KnowledgeGraph(
            concepts={
                "GDP": ConceptNode(
                    name="GDP",
                    definition="The value of all final goods and services produced.",
                    aliases=["Gross Domestic Product"],
                ),
            },
            modules={},
            relationships=[],
        )

        adapter.persist_knowledge_graph(kg)

        query, kwargs = mock_session.run.call_args_list[0][0][0], mock_session.run.call_args[1]
        assert "c.definition = $definition" in query
        assert "c.aliases = $aliases" in query
        assert kwargs["definition"] == "The value of all final goods and services produced."
        assert kwargs["aliases"] == ["Gross Domestic Product"]

    def test_module_node_properties_are_passed(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        kg = KnowledgeGraph(
            concepts={},
            modules={
                "m1": ModuleNode(
                    module_id="m1",
                    title="Genetics",
                    key_terms=["DNA", "RNA"],
                ),
            },
            relationships=[],
        )

        adapter.persist_knowledge_graph(kg)

        module_call = mock_session.run.call_args_list[0]
        assert module_call[1]["module_id"] == "m1"
        assert module_call[1]["title"] == "Genetics"
        assert module_call[1]["key_terms"] == ["DNA", "RNA"]

    def test_relationship_properties_are_passed(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        kg = KnowledgeGraph(
            concepts={
                "A": ConceptNode(name="A"),
                "B": ConceptNode(name="B"),
            },
            modules={},
            relationships=[
                Relationship(
                    source="A",
                    target="B",
                    type=RelationshipType.RELATED,
                    weight=0.75,
                    confidence=0.8,
                ),
            ],
        )

        adapter.persist_knowledge_graph(kg)

        # 2 concept calls + 1 relationship call = 3 total
        rel_call = mock_session.run.call_args_list[2]
        assert rel_call[1]["source"] == "A"
        assert rel_call[1]["target"] == "B"
        assert rel_call[1]["weight"] == 0.75
        assert rel_call[1]["confidence"] == 0.8
        assert rel_call[1]["properties"] == {}
        assert "r += $properties" in rel_call[0][0]

    def test_relationship_evidence_is_persisted(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        kg = KnowledgeGraph(
            concepts={"A": ConceptNode(name="A"), "B": ConceptNode(name="B")},
            modules={},
            relationships=[
                Relationship(
                    source="A",
                    target="B",
                    type=RelationshipType.PREREQ,
                    evidence="B is defined in terms of A.",
                ),
            ],
        )

        adapter.persist_knowledge_graph(kg)

        rel_call = mock_session.run.call_args_list[2]
        assert rel_call[1]["properties"] == {"evidence": "B is defined in terms of A."}

    def test_relationship_provenance_is_flattened(self):
        """Neo4j cannot store maps, so provenance keys become provenance_* properties."""
        from types import SimpleNamespace

        from backend.app.kg.neo4j_adapter import _relationship_properties

        rel = SimpleNamespace(
            evidence=None,
            provenance={"source": "glossary", "module_id": "m48590", "page": 3, "note": None},
        )

        assert _relationship_properties(rel) == {
            "provenance_source": "glossary",
            "provenance_module_id": "m48590",
            "provenance_page": 3,
        }
        nested = SimpleNamespace(evidence="e", provenance={"spans": [1, 2]})
        assert _relationship_properties(nested) == {"evidence": "e", "provenance_spans": "[1, 2]"}

    def test_unknown_relationship_type_is_skipped(self):
        """Relationships with an unrecognized type should be silently skipped."""
        adapter, mock_session = _make_adapter(label_prefix=None)

        # Create a relationship with a type that's not COVERS, RELATED, or PREREQ
        rel = Relationship(
            source="m1",
            target="c1",
            type=RelationshipType.MENTIONS,
            weight=1.0,
            confidence=1.0,
        )
        kg = KnowledgeGraph(
            concepts={"c1": ConceptNode(name="c1")},
            modules={"m1": ModuleNode(module_id="m1", title="M1")},
            relationships=[rel],
        )

        adapter.persist_knowledge_graph(kg)

        # 1 concept + 1 module = 2 calls; the MENTIONS relationship is skipped
        assert len(mock_session.run.call_args_list) == 2


@pytest.mark.unit
class TestFulltextSearch:
    """Tests for fulltext_concept_search()."""

    def test_returns_results_with_scores(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        mock_session.run.return_value = _make_mock_result(
            [
                {"name": "Photosynthesis", "importance_score": 0.9, "key_term": True, "score": 5.5},
                {
                    "name": "Photorespiration",
                    "importance_score": 0.6,
                    "key_term": False,
                    "score": 3.2,
                },
            ]
        )

        results = adapter.fulltext_concept_search("photo", limit=5)

        assert len(results) == 2
        assert results[0]["name"] == "Photosynthesis"
        assert results[0]["score"] == 5.5
        assert results[1]["name"] == "Photorespiration"

    def test_auto_generates_index_name_with_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([])

        adapter.fulltext_concept_search("test query")

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "us_history_fullTextConceptNames"

    def test_auto_generates_index_name_without_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        mock_session.run.return_value = _make_mock_result([])

        adapter.fulltext_concept_search("test query")

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "fullTextConceptNames"

    def test_uses_explicit_index_name(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        mock_session.run.return_value = _make_mock_result([])

        adapter.fulltext_concept_search("test", index_name="my_custom_index")

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "my_custom_index"

    def test_empty_results(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result([])

        results = adapter.fulltext_concept_search("nonexistent")
        assert results == []

    def test_passes_limit_parameter(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result([])

        adapter.fulltext_concept_search("test", limit=25)

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["limit"] == 25


@pytest.mark.unit
class TestVectorSearch:
    """Tests for vector_search()."""

    def test_returns_chunks_with_scores(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result(
            [
                {
                    "chunk_id": "c1",
                    "text": "Some text",
                    "module_id": "m1",
                    "section": "Intro",
                    "chunk_index": 0,
                    "score": 0.95,
                },
                {
                    "chunk_id": "c2",
                    "text": "More text",
                    "module_id": "m1",
                    "section": "Body",
                    "chunk_index": 1,
                    "score": 0.88,
                },
            ]
        )

        results = adapter.vector_search([0.1, 0.2, 0.3], top_k=5)

        assert len(results) == 2
        assert results[0]["chunk_id"] == "c1"
        assert results[0]["score"] == 0.95
        assert results[1]["chunk_id"] == "c2"

    def test_auto_generates_index_name_with_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix="history")
        mock_session.run.return_value = _make_mock_result([])

        adapter.vector_search([0.1], top_k=3)

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "history_chunk_embeddings"

    def test_auto_generates_index_name_without_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        mock_session.run.return_value = _make_mock_result([])

        adapter.vector_search([0.1], top_k=3)

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "chunk_embeddings"

    def test_uses_explicit_index_name(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        mock_session.run.return_value = _make_mock_result([])

        adapter.vector_search([0.1], index_name="custom_vec_index")

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["index_name"] == "custom_vec_index"

    def test_passes_top_k_and_embedding(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result([])
        embedding = [0.1, 0.2, 0.3, 0.4]

        adapter.vector_search(embedding, top_k=15)

        cypher_call = mock_session.run.call_args
        assert cypher_call[1]["top_k"] == 15
        assert cypher_call[1]["query_embedding"] == embedding


@pytest.mark.unit
class TestChunkOperations:
    """Tests for chunk node creation and relationship operations."""

    def test_create_chunk_nodes(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        chunks = _make_sample_chunks()

        adapter.create_chunk_nodes(chunks, batch_size=100)

        # All 3 chunks in a single batch
        assert mock_session.run.call_count == 1
        cypher_call = mock_session.run.call_args
        assert "test_Chunk" in cypher_call[0][0]
        chunk_data = cypher_call[1]["chunks"]
        assert len(chunk_data) == 3
        assert chunk_data[0]["chunk_id"] == "c1"
        assert chunk_data[1]["chunk_id"] == "c2"
        assert chunk_data[2]["chunk_id"] == "c3"

    def test_create_chunk_nodes_batching(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        chunks = _make_sample_chunks()

        adapter.create_chunk_nodes(chunks, batch_size=2)

        # 3 chunks with batch_size=2 -> 2 batches
        assert mock_session.run.call_count == 2

        first_batch = mock_session.run.call_args_list[0][1]["chunks"]
        second_batch = mock_session.run.call_args_list[1][1]["chunks"]
        assert len(first_batch) == 2
        assert len(second_batch) == 1

    def test_create_chunk_nodes_empty_list(self):
        adapter, mock_session = _make_adapter()

        adapter.create_chunk_nodes([])

        mock_session.run.assert_not_called()

    def test_create_next_relationships(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        chunks = _make_sample_chunks()

        adapter.create_next_relationships(chunks)

        # Chunks c2 and c3 have previous_chunk_id set; c1 does not
        assert mock_session.run.call_count == 1
        cypher_call = mock_session.run.call_args
        assert "NEXT" in cypher_call[0][0]
        assert "test_Chunk" in cypher_call[0][0]
        pairs = cypher_call[1]["pairs"]
        assert len(pairs) == 2
        assert pairs[0] == {"from_id": "c1", "to_id": "c2"}
        assert pairs[1] == {"from_id": "c2", "to_id": "c3"}

    def test_create_next_relationships_no_links(self):
        adapter, mock_session = _make_adapter()
        # Single chunk with no previous_chunk_id
        chunks = [
            ChunkNode(chunk_id="c1", text="Only chunk", previous_chunk_id=None),
        ]

        adapter.create_next_relationships(chunks)

        # No pairs, so session.run should not be called for the UNWIND query
        # (the pairs list is empty, so the if guard prevents the run call)
        assert mock_session.run.call_count == 0

    def test_create_first_chunk_relationships(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        module_first_chunks = {"m1": "c1", "m2": "c5"}

        adapter.create_first_chunk_relationships(module_first_chunks)

        assert mock_session.run.call_count == 1
        cypher_call = mock_session.run.call_args
        assert "FIRST_CHUNK" in cypher_call[0][0]
        assert "test_Module" in cypher_call[0][0]
        assert "test_Chunk" in cypher_call[0][0]
        links = cypher_call[1]["links"]
        assert len(links) == 2

    def test_create_first_chunk_relationships_empty(self):
        adapter, mock_session = _make_adapter()

        adapter.create_first_chunk_relationships({})

        # Empty dict -> no links -> session.run not called
        assert mock_session.run.call_count == 0

    def test_create_chunk_mentions_relationships(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        pairs = [("c1", "Photosynthesis"), ("c2", "Chloroplast"), ("c1", "ATP")]

        adapter.create_chunk_mentions_relationships(pairs, batch_size=500)

        assert mock_session.run.call_count == 1
        cypher_call = mock_session.run.call_args
        assert "MENTIONS" in cypher_call[0][0]
        assert "bio_Chunk" in cypher_call[0][0]
        assert "bio_Concept" in cypher_call[0][0]
        sent_pairs = cypher_call[1]["pairs"]
        assert len(sent_pairs) == 3

    def test_create_chunk_mentions_relationships_batching(self):
        adapter, mock_session = _make_adapter()
        pairs = [("c1", "A"), ("c2", "B"), ("c3", "C")]

        adapter.create_chunk_mentions_relationships(pairs, batch_size=2)

        # 3 pairs with batch_size=2 -> 2 batches
        assert mock_session.run.call_count == 2

    def test_create_chunk_mentions_relationships_empty(self):
        adapter, mock_session = _make_adapter()

        adapter.create_chunk_mentions_relationships([])

        mock_session.run.assert_not_called()

    def test_chunk_node_data_fields(self):
        """Verify that all ChunkNode fields are correctly mapped to query parameters."""
        adapter, mock_session = _make_adapter()
        chunk = ChunkNode(
            chunk_id="test_id",
            text="test text",
            chunk_index=5,
            start_char=100,
            end_char=200,
            module_id="mod1",
            chapter="Chapter A",
            section="Section A",
            text_embedding=[1.0, 2.0],
        )

        adapter.create_chunk_nodes([chunk])

        chunk_data = mock_session.run.call_args[1]["chunks"][0]
        assert chunk_data["chunk_id"] == "test_id"
        assert chunk_data["text"] == "test text"
        assert chunk_data["chunk_index"] == 5
        assert chunk_data["start_char"] == 100
        assert chunk_data["end_char"] == 200
        assert chunk_data["module_id"] == "mod1"
        assert chunk_data["chapter"] == "Chapter A"
        assert chunk_data["section"] == "Section A"
        assert chunk_data["text_embedding"] == [1.0, 2.0]
        assert "c.chapter = chunk.chapter" in mock_session.run.call_args[0][0]


@pytest.mark.unit
class TestGetChunkWindow:
    """Tests for get_chunk_window()."""

    def test_returns_window_of_chunks(self):
        adapter, mock_session = _make_adapter(label_prefix="test")
        mock_session.run.return_value = _make_mock_result(
            [
                {
                    "chunk_id": "c1",
                    "text": "Before",
                    "module_id": "m1",
                    "section": "A",
                    "chunk_index": 0,
                },
                {
                    "chunk_id": "c2",
                    "text": "Center",
                    "module_id": "m1",
                    "section": "A",
                    "chunk_index": 1,
                },
                {
                    "chunk_id": "c3",
                    "text": "After",
                    "module_id": "m1",
                    "section": "A",
                    "chunk_index": 2,
                },
            ]
        )

        results = adapter.get_chunk_window("c2", window_before=1, window_after=1)

        assert len(results) == 3
        assert results[0]["chunk_id"] == "c1"
        assert results[1]["chunk_id"] == "c2"
        assert results[2]["chunk_id"] == "c3"

    def test_uses_prefixed_chunk_label(self):
        adapter, mock_session = _make_adapter(label_prefix="hist")
        mock_session.run.return_value = _make_mock_result([])

        adapter.get_chunk_window("c1")

        query = mock_session.run.call_args[0][0]
        assert "hist_Chunk" in query

    def test_passes_chunk_id(self):
        adapter, mock_session = _make_adapter()
        mock_session.run.return_value = _make_mock_result([])

        adapter.get_chunk_window("my_chunk_42")

        assert mock_session.run.call_args[1]["chunk_id"] == "my_chunk_42"


@pytest.mark.unit
class TestCreateIndexes:
    """Tests for index creation methods."""

    def test_create_vector_index_auto_name_with_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix="bio")
        # First call: SHOW INDEXES (index doesn't exist)
        show_result = MagicMock()
        show_result.single.return_value = None
        mock_session.run.side_effect = [show_result, None]

        adapter.create_vector_index()

        calls = mock_session.run.call_args_list
        # Check index name in SHOW query
        assert calls[0][1]["name"] == "bio_chunk_embeddings"
        # Check CREATE query uses prefixed label
        assert "bio_Chunk" in calls[1][0][0]
        assert "bio_chunk_embeddings" in calls[1][0][0]

    def test_create_vector_index_auto_name_without_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix=None)
        show_result = MagicMock()
        show_result.single.return_value = None
        mock_session.run.side_effect = [show_result, None]

        adapter.create_vector_index()

        calls = mock_session.run.call_args_list
        assert calls[0][1]["name"] == "chunk_embeddings"
        assert "chunk_embeddings" in calls[1][0][0]

    def test_create_vector_index_already_exists(self):
        adapter, mock_session = _make_adapter()
        show_result = MagicMock()
        show_result.single.return_value = {"name": "chunk_embeddings"}
        mock_session.run.return_value = show_result

        adapter.create_vector_index()

        # Only the SHOW INDEXES call, no CREATE
        assert mock_session.run.call_count == 1

    def test_create_fulltext_index_auto_name_with_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix="hist")
        show_result = MagicMock()
        show_result.single.return_value = None
        mock_session.run.side_effect = [show_result, None]

        adapter.create_fulltext_index()

        calls = mock_session.run.call_args_list
        assert calls[0][1]["name"] == "hist_fullTextConceptNames"
        assert "hist_Concept" in calls[1][0][0]

    def test_create_fulltext_index_already_exists(self):
        adapter, mock_session = _make_adapter()
        show_result = MagicMock()
        show_result.single.return_value = {"name": "fullTextConceptNames"}
        mock_session.run.return_value = show_result

        adapter.create_fulltext_index()

        assert mock_session.run.call_count == 1

    def test_create_chunk_id_index_with_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix="test")

        adapter.create_chunk_id_index()

        query = mock_session.run.call_args[0][0]
        assert "test_chunk_id_index" in query
        assert "test_Chunk" in query

    def test_create_chunk_id_index_without_prefix(self):
        adapter, mock_session = _make_adapter(label_prefix=None)

        adapter.create_chunk_id_index()

        query = mock_session.run.call_args[0][0]
        assert "chunk_id_index" in query
        assert "Chunk" in query


@pytest.mark.unit
class TestFactoryFunction:
    """Tests for get_neo4j_adapter() caching and clear_neo4j_adapters()."""

    def setup_method(self):
        """Clear the adapter registry before each test."""
        _neo4j_adapters.clear()

    def teardown_method(self):
        """Clean up the adapter registry after each test."""
        _neo4j_adapters.clear()

    @patch("backend.app.core.subjects.get_subject")
    @patch("backend.app.core.subjects.get_default_subject_id")
    def test_get_adapter_creates_and_caches(self, mock_default_id, mock_get_subject):
        mock_default_id.return_value = "biology"
        mock_subject = MagicMock()
        mock_subject.database.neo4j_database = "neo4j"
        mock_subject.database.label_prefix = "biology"
        mock_get_subject.return_value = mock_subject

        with patch.object(Neo4jAdapter, "connect"):
            adapter1 = get_neo4j_adapter("biology")
            adapter2 = get_neo4j_adapter("biology")

        # Should be the same cached instance
        assert adapter1 is adapter2
        assert "biology" in _neo4j_adapters

    @patch("backend.app.core.subjects.get_subject")
    @patch("backend.app.core.subjects.get_default_subject_id")
    def test_get_adapter_uses_default_subject(self, mock_default_id, mock_get_subject):
        mock_default_id.return_value = "us_history"
        mock_subject = MagicMock()
        mock_subject.database.neo4j_database = "neo4j"
        mock_subject.database.label_prefix = "us_history"
        mock_get_subject.return_value = mock_subject

        with patch.object(Neo4jAdapter, "connect"):
            get_neo4j_adapter(None)

        mock_default_id.assert_called_once()
        mock_get_subject.assert_called_once_with("us_history")
        assert "us_history" in _neo4j_adapters

    @patch("backend.app.core.subjects.get_subject")
    @patch("backend.app.core.subjects.get_default_subject_id")
    def test_get_adapter_reconnects_if_driver_none(self, mock_default_id, mock_get_subject):
        """If a cached adapter has driver=None, it should reconnect."""
        mock_default_id.return_value = "bio"
        mock_subject = MagicMock()
        mock_subject.database.neo4j_database = "neo4j"
        mock_subject.database.label_prefix = "bio"
        mock_get_subject.return_value = mock_subject

        with patch.object(Neo4jAdapter, "connect"):
            adapter = get_neo4j_adapter("bio")

        # Simulate driver being closed
        adapter.driver = None

        with patch.object(adapter, "connect") as mock_connect:
            returned = get_neo4j_adapter("bio")
            mock_connect.assert_called_once()
            assert returned is adapter

    @patch("backend.app.core.subjects.get_subject")
    @patch("backend.app.core.subjects.get_default_subject_id")
    def test_different_subjects_get_different_adapters(self, mock_default_id, mock_get_subject):
        mock_subject_a = MagicMock()
        mock_subject_a.database.neo4j_database = "neo4j"
        mock_subject_a.database.label_prefix = "biology"

        mock_subject_b = MagicMock()
        mock_subject_b.database.neo4j_database = "neo4j"
        mock_subject_b.database.label_prefix = "history"

        mock_get_subject.side_effect = lambda sid: (
            mock_subject_a if sid == "biology" else mock_subject_b
        )

        with patch.object(Neo4jAdapter, "connect"):
            adapter_a = get_neo4j_adapter("biology")
            adapter_b = get_neo4j_adapter("history")

        assert adapter_a is not adapter_b
        assert len(_neo4j_adapters) == 2

    def test_clear_adapters_closes_all(self):
        mock_adapter_1 = MagicMock()
        mock_adapter_2 = MagicMock()
        _neo4j_adapters["sub1"] = mock_adapter_1
        _neo4j_adapters["sub2"] = mock_adapter_2

        clear_neo4j_adapters()

        mock_adapter_1.close.assert_called_once()
        mock_adapter_2.close.assert_called_once()
        assert len(_neo4j_adapters) == 0

    def test_clear_adapters_on_empty_registry(self):
        # Should not raise when registry is empty
        clear_neo4j_adapters()
        assert len(_neo4j_adapters) == 0


@pytest.mark.unit
def test_concurrent_first_calls_create_one_adapter():
    import threading
    import time

    created: list[Neo4jAdapter] = []

    def slow_connect(self):
        time.sleep(0.05)  # widen the race window
        created.append(self)
        self.driver = MagicMock()

    results: list[Neo4jAdapter] = []
    _neo4j_adapters.clear()
    try:
        with patch.object(Neo4jAdapter, "connect", slow_connect):
            threads = [
                threading.Thread(target=lambda: results.append(get_neo4j_adapter("us_history")))
                for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
    finally:
        _neo4j_adapters.clear()

    assert len(created) == 1
    assert len(results) == 8
    assert all(result is created[0] for result in results)
    assert created[0].label_prefix == "us_history"


@pytest.mark.unit
class TestCloseAndReconnect:
    """A closed adapter is reconnected by the registry instead of reused half-closed."""

    def test_close_resets_driver(self):
        adapter = Neo4jAdapter()
        mock_driver = MagicMock()
        adapter.driver = mock_driver

        adapter.close()

        mock_driver.close.assert_called_once()
        assert adapter.driver is None

    @patch("backend.app.core.subjects.get_subject")
    @patch("backend.app.core.subjects.get_default_subject_id")
    def test_registry_reconnects_closed_adapter(self, mock_default_id, mock_get_subject):
        mock_subject = MagicMock()
        mock_subject.database.neo4j_database = "neo4j"
        mock_subject.database.label_prefix = "bio"
        mock_get_subject.return_value = mock_subject
        _neo4j_adapters.clear()
        try:
            with patch.object(Neo4jAdapter, "connect"):
                adapter = get_neo4j_adapter("bio")
            adapter.driver = MagicMock()
            adapter.close()

            with patch.object(adapter, "connect") as mock_connect:
                assert get_neo4j_adapter("bio") is adapter
                mock_connect.assert_called_once()
        finally:
            _neo4j_adapters.clear()


@pytest.mark.unit
class TestConceptLookup:
    """get_all_concept_names / concept_exists use the subject's prefixed label."""

    def test_get_all_concept_names(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result(
            [{"name": "Civil War"}, {"name": "Reconstruction"}, {"name": None}]
        )

        names = adapter.get_all_concept_names()

        assert names == {"Civil War", "Reconstruction"}
        assert "us_history_Concept" in mock_session.run.call_args[0][0]

    def test_get_concept_aliases(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.return_value = _make_mock_result(
            [
                {"name": "Gross Domestic Product", "aliases": ["GDP", ""]},
                {"name": "Recession", "aliases": []},
                {"name": None, "aliases": ["orphan"]},
            ]
        )

        assert adapter.get_concept_aliases() == {
            "Gross Domestic Product": ["GDP"],
            "Recession": [],
        }
        query = mock_session.run.call_args[0][0]
        assert "economics_Concept" in query
        assert "coalesce(c.aliases, [])" in query

    def test_concept_exists_matches_case_insensitively_and_ignores_leading_the(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([{"found": True}])

        assert adapter.concept_exists("  The   Civil War ") is True

        query = mock_session.run.call_args[0][0]
        assert "us_history_Concept" in query
        assert "toLower(c.name) IN $names" in query
        assert "coalesce(c.aliases, [])" in query  # aliases match too
        assert mock_session.run.call_args[1]["names"] == ["the civil war", "civil war"]

    def test_concept_exists_false_when_not_found(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([{"found": False}])

        assert adapter.concept_exists("TOTALLY_FAKE_CONCEPT_12345") is False
        assert mock_session.run.call_args[1]["names"] == ["totally_fake_concept_12345"]

    @pytest.mark.parametrize("name", ["", "   ", "\n"])
    def test_blank_concept_never_exists(self, name):
        adapter, mock_session = _make_adapter(label_prefix="us_history")

        assert adapter.concept_exists(name) is False
        mock_session.run.assert_not_called()

    def test_bare_the_is_not_stripped(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([{"found": False}])

        adapter.concept_exists("The")

        assert mock_session.run.call_args[1]["names"] == ["the"]


@pytest.mark.unit
class TestDomainOverlayQueries:
    """The overlay methods (#211): prefixed labels, and every value passed as a parameter."""

    def test_get_concept_overlay_state(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        row = {
            "name": "Tariff",
            "definition": "a tax on imports",
            "aliases": ["Tariffs"],
            "term_id": "tariff",
            "review_status": "approved",
            "definition_source": "economics",
        }
        mock_session.run.return_value = _make_mock_result([row, {"name": None, "aliases": []}])

        assert adapter.get_concept_overlay_state() == [row]
        query = mock_session.run.call_args[0][0]
        assert "MATCH (c:economics_Concept)" in query
        assert "coalesce(c.aliases, []) AS aliases" in query
        for name in ("definition", "term_id", "review_status", "definition_source"):
            assert f"c.{name} AS {name}" in query
        assert mock_session.run.call_args[1] == {}

    def test_get_prereq_edges(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.return_value = _make_mock_result(
            [
                {
                    "source": "Trade",
                    "target": "Tariff",
                    "properties": {"weight": 0.8, "provenance_source": "glossary"},
                },
                {"source": "Good", "target": "Trade", "properties": None},
            ]
        )

        assert adapter.get_prereq_edges() == [
            {
                "source": "Trade",
                "target": "Tariff",
                "properties": {"weight": 0.8, "provenance_source": "glossary"},
            },
            {"source": "Good", "target": "Trade", "properties": {}},
        ]
        query = mock_session.run.call_args[0][0]
        assert "(a:economics_Concept)-[r:PREREQ]->(b:economics_Concept)" in query
        assert "properties(r) AS properties" in query

    def test_merge_curated_concept(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        properties = {
            "definition": "a curated definition",
            "aliases": ["Duty"],
            "term_id": "tariff",
        }

        adapter.merge_curated_concept("Tariff", properties)

        query = mock_session.run.call_args[0][0]
        assert query.startswith("MERGE (c:us_history_Concept {name: $name}) ON CREATE SET ")
        assert "c.importance_score = 0.0" in query and "c.source_modules = []" in query
        assert query.endswith("SET c += $properties")
        assert mock_session.run.call_args[1] == {"name": "Tariff", "properties": properties}
        assert "Tariff" not in query and "curated" not in query

    def test_delete_concept(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")

        adapter.delete_concept("Summary")

        mock_session.run.assert_called_once_with(
            "MATCH (c:us_history_Concept {name: $name}) DETACH DELETE c", name="Summary"
        )

    def test_merge_curated_prereq(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        properties = {"provenance_source": "curated", "review_status": "approved"}

        adapter.merge_curated_prereq("Trade", "Tariff", properties, 0.8)

        query = mock_session.run.call_args[0][0]
        assert "MATCH (a:us_history_Concept {name: $source})" in query
        assert "MATCH (b:us_history_Concept {name: $target})" in query
        assert "MERGE (a)-[r:PREREQ]->(b) ON CREATE SET r.weight = $weight" in query
        assert query.endswith("SET r += $properties")
        assert mock_session.run.call_args[1] == {
            "source": "Trade",
            "target": "Tariff",
            "weight": 0.8,
            "properties": properties,
        }
        assert "curated" not in query

    def test_delete_prereq(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")

        adapter.delete_prereq("Trade", "Tariff")

        mock_session.run.assert_called_once_with(
            "MATCH (:us_history_Concept {name: $source})"
            "-[r:PREREQ]->(:us_history_Concept {name: $target}) DELETE r",
            source="Trade",
            target="Tariff",
        )

    def test_unprefixed_adapter_uses_the_plain_label(self):
        adapter, mock_session = _make_adapter()

        adapter.delete_concept("Summary")

        assert "MATCH (c:Concept {name: $name})" in mock_session.run.call_args[0][0]


def _method_calls(tree: ast.AST, name: str) -> list[ast.Call]:
    """The ``<object>.<name>(...)`` calls under ``tree``."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    ]


@pytest.mark.unit
class TestQuietOverlayReads:
    """
    The overlay's two reads hide the server's "unrecognized" notifications.

    Before the first apply the store has no ``term_id``, ``review_status`` or
    ``definition_source`` property key, and the driver logs one warning per key. Every
    other session stays plain: there the same notification points at a misspelt name.
    """

    QUIET = {"database": "neo4j", "notifications_disabled_classifications": ["UNRECOGNIZED"]}
    READS = ("get_concept_overlay_state", "get_prereq_edges")

    def test_the_options_hide_unrecognized_notifications_only(self):
        assert {"database": "neo4j", **QUIET_READ_OPTIONS} == self.QUIET
        # The server refuses a classification it does not know, so the spelling matters
        assert "UNRECOGNIZED" in {c.value for c in neo4j.NotificationDisabledClassification}

    def test_the_installed_driver_accepts_the_options(self):
        """
        The real driver builds the session without connecting.

        It raises ConfigurationError for a session option it does not know. The adapter
        would then fall back to a plain session, so only this test would notice.
        """
        driver = neo4j.GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("neo4j", "password"))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")  # neither deprecated nor a preview option
                driver.session(database="neo4j", **QUIET_READ_OPTIONS).close()
            with pytest.raises(ConfigurationError, match="Unexpected config keys"):
                driver.session(database="neo4j", notifications_disabled_classes=["UNRECOGNIZED"])
        finally:
            driver.close()

    @pytest.mark.parametrize("read", READS)
    def test_overlay_reads_open_a_quiet_session(self, read):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.return_value = _make_mock_result([])

        assert getattr(adapter, read)() == []

        adapter.driver.session.assert_called_once_with(**self.QUIET)
        mock_session.run.assert_called_once()

    @pytest.mark.parametrize(
        ("method", "arguments"),
        [
            ("merge_curated_concept", ("Tariff", {"term_id": "tariff"})),
            ("delete_concept", ("Summary",)),
            ("merge_curated_prereq", ("Trade", "Tariff", {"review_status": "approved"}, 0.8)),
            ("delete_prereq", ("Trade", "Tariff")),
            ("get_all_concept_names", ()),
            ("get_concept_aliases", ()),
            ("count_concepts", ()),
            ("concept_exists", ("Tariff",)),
            ("query_concept_neighbors", ("Tariff",)),
        ],
    )
    def test_other_methods_open_a_plain_session(self, method, arguments):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.return_value = _make_mock_result([])

        getattr(adapter, method)(*arguments)

        adapter.driver.session.assert_called_once_with(database="neo4j")

    def test_only_the_overlay_reads_ask_for_a_quiet_session(self):
        """Structural, for the methods the test above does not call."""
        adapter_class = next(
            node
            for node in ast.parse(inspect.getsource(neo4j_adapter)).body
            if isinstance(node, ast.ClassDef) and node.name == "Neo4jAdapter"
        )
        methods = [node for node in adapter_class.body if isinstance(node, ast.FunctionDef)]
        with_options = {
            method.name
            for method in methods
            for call in _method_calls(method, "_get_session")
            if call.args or call.keywords
        }
        quiet_readers = {
            method.name for method in methods if _method_calls(method, "_run_quiet_read")
        }
        opens_driver_sessions = {
            method.name for method in methods if _method_calls(method, "session")
        }

        assert with_options == {"_run_quiet_read"}
        assert quiet_readers == set(self.READS)
        assert opens_driver_sessions == {"_get_session"}

    @pytest.mark.parametrize(
        ("read", "row"),
        [
            ("get_concept_overlay_state", {"name": "Tariff", "term_id": None}),
            ("get_prereq_edges", {"source": "Trade", "target": "Tariff", "properties": {}}),
        ],
    )
    def test_a_server_that_cannot_filter_notifications_gets_a_plain_session(self, read, row):
        """Before Neo4j 5.7 the driver refuses the option when the statement runs."""
        adapter, mock_session = _make_adapter(label_prefix="economics")
        refused = ConfigurationError(
            "Notification filtering is not supported for the Bolt Protocol 4.4."
        )
        mock_session.run.side_effect = [refused, _make_mock_result([row])]

        assert getattr(adapter, read)() == [row]
        assert [call.kwargs for call in adapter.driver.session.call_args_list] == [
            self.QUIET,
            {"database": "neo4j"},
        ]
        queries = [call.args[0] for call in mock_session.run.call_args_list]
        assert len(queries) == 2 and queries[0] == queries[1]

    def test_a_driver_that_does_not_know_the_option_gets_a_plain_session(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        plain_session = adapter.driver.session.return_value
        adapter.driver.session.side_effect = [
            ConfigurationError("Unexpected config keys: notifications_disabled_classifications"),
            plain_session,
        ]
        mock_session.run.return_value = _make_mock_result([{"name": "Tariff"}])

        assert adapter.get_concept_overlay_state() == [{"name": "Tariff"}]
        assert adapter.driver.session.call_args_list[-1].kwargs == {"database": "neo4j"}

    def test_other_errors_are_not_retried(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.side_effect = ServiceUnavailable("connection refused")

        with pytest.raises(ServiceUnavailable, match="connection refused"):
            adapter.get_concept_overlay_state()

        adapter.driver.session.assert_called_once_with(**self.QUIET)

    def test_a_refusal_of_the_plain_session_is_raised(self):
        adapter, mock_session = _make_adapter(label_prefix="economics")
        mock_session.run.side_effect = ConfigurationError("database selection is not supported")

        with pytest.raises(ConfigurationError, match="database selection"):
            adapter.get_prereq_edges()

        assert adapter.driver.session.call_count == 2


@pytest.mark.unit
class TestChunkWindowSizes:
    """get_chunk_window honours zero-sized windows and joins module titles."""

    def test_zero_window_skips_next_traversal(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([])

        adapter.get_chunk_window("c1", window_before=0, window_after=0)

        query = mock_session.run.call_args[0][0]
        assert "NEXT" not in query
        assert "*1..0" not in query
        assert "us_history_Chunk" in query

    def test_one_sided_window(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([])

        adapter.get_chunk_window("c1", window_before=0, window_after=2)

        query = mock_session.run.call_args[0][0]
        assert "(center)-[:NEXT*1..2]->(next:us_history_Chunk)" in query
        assert "->(center)" not in query

    def test_window_sizes_are_interpolated_as_integers(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result([])

        adapter.get_chunk_window("c1", window_before=3, window_after=1)

        query = mock_session.run.call_args[0][0]
        assert "[:NEXT*1..3]->(center)" in query
        assert "(center)-[:NEXT*1..1]->" in query

    def test_returns_module_title_from_prefixed_module(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")
        mock_session.run.return_value = _make_mock_result(
            [
                {
                    "chunk_id": "c1",
                    "text": "Text",
                    "module_id": "m1",
                    "module_title": "The Civil War",
                    "section": "A",
                    "chunk_index": 0,
                }
            ]
        )

        [chunk] = adapter.get_chunk_window("c1")

        query = mock_session.run.call_args[0][0]
        assert "us_history_Module" in query
        assert "module.title AS module_title" in query
        assert "chunk.chapter AS chapter" in query
        assert chunk["module_title"] == "The Civil War"

    def test_negative_window_rejected(self):
        adapter, mock_session = _make_adapter(label_prefix="us_history")

        with pytest.raises(ValueError):
            adapter.get_chunk_window("c1", window_before=-1)
        mock_session.run.assert_not_called()


@pytest.mark.unit
def test_query_concept_neighbors_uses_integer_hops():
    adapter, mock_session = _make_adapter(label_prefix="bio")
    mock_session.run.return_value = _make_mock_result([])

    adapter.query_concept_neighbors("Photosynthesis", max_hops=2)

    assert "*1..2" in mock_session.run.call_args[0][0]
