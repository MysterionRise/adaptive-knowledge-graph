"""
Tests for the /graph/* and /concepts/* endpoints.

Tests cover:
- Graph statistics
- Top concepts retrieval
- Graph visualization data
- Natural language graph queries (Cypher QA)
- Concept fulltext search
- Graph schema
- Learning path endpoints
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.app.core.exceptions import Neo4jConnectionError, Neo4jQueryError


@pytest.mark.unit
class TestGraphStatsEndpoint:
    """Tests for GET /api/v1/graph/stats endpoint."""

    def test_get_graph_stats_success(self, client, mock_neo4j_adapter):
        """Test successful graph statistics retrieval."""
        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_neo4j_adapter
        ):
            response = client.get("/api/v1/graph/stats")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "concept_count" in data
        assert "module_count" in data
        assert "relationship_count" in data

        # Verify values from mock
        assert data["concept_count"] == 150
        assert data["module_count"] == 25
        assert data["relationship_count"] == 600  # Sum of all relationship types

    def test_get_graph_stats_connection_error(self, client):
        """Test 503 when Neo4j connection fails."""
        failing_adapter = MagicMock()
        failing_adapter.connect.side_effect = Neo4jConnectionError("Connection refused")

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=failing_adapter
        ):
            response = client.get("/api/v1/graph/stats")

        assert response.status_code == 503
        assert "Database connection failed" in response.json()["detail"]

    def test_get_graph_stats_query_error(self, client):
        """Test 500 when Neo4j query fails."""
        failing_adapter = MagicMock()
        failing_adapter.connect.return_value = None
        failing_adapter.get_graph_stats.side_effect = Neo4jQueryError("Query timeout")

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=failing_adapter
        ):
            response = client.get("/api/v1/graph/stats")

        assert response.status_code == 500


@pytest.mark.unit
class TestTopConceptsEndpoint:
    """Tests for GET /api/v1/concepts/top endpoint."""

    def test_get_top_concepts_success(self, client):
        """Test successful top concepts retrieval."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        # Mock the session and query result
        mock_session = MagicMock()
        mock_result = [
            {"name": "Photosynthesis", "score": 0.95, "is_key_term": True, "frequency": 50},
            {"name": "Mitosis", "score": 0.9, "is_key_term": True, "frequency": 45},
            {"name": "DNA", "score": 0.88, "is_key_term": True, "frequency": 60},
        ]
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/concepts/top", params={"limit": 3})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["name"] == "Photosynthesis"

    def test_get_top_concepts_default_limit(self, client):
        """Test top concepts with default limit."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = []

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/concepts/top")

        assert response.status_code == 200
        # Verify default limit=20 was used
        call_args = mock_session.run.call_args
        assert call_args[1]["limit"] == 20


@pytest.mark.unit
class TestGraphDataEndpoint:
    """Tests for GET /api/v1/graph/data endpoint."""

    def test_get_graph_data_success(self, client):
        """Test successful graph data retrieval for visualization."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()

        # First query returns concepts
        concepts = [
            {"id": "node1", "label": "Photosynthesis", "importance": 0.9, "chapter": "Ch5"},
            {"id": "node2", "label": "Chloroplast", "importance": 0.8, "chapter": "Ch5"},
        ]

        # Second query returns relationships
        relationships = [
            {"source": "node1", "target": "node2", "type": "RELATED_TO", "weight": 1.0}
        ]

        mock_session.run.side_effect = [concepts, relationships]

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/graph/data", params={"limit": 100})

        assert response.status_code == 200
        data = response.json()

        # Verify Cytoscape format
        assert "nodes" in data
        assert "edges" in data

        # Check node format
        assert len(data["nodes"]) == 2
        node = data["nodes"][0]
        assert "data" in node
        assert "id" in node["data"]
        assert "label" in node["data"]
        assert "importance" in node["data"]

        # Check edge format
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert "data" in edge
        assert "source" in edge["data"]
        assert "target" in edge["data"]
        assert "type" in edge["data"]

    def test_get_graph_data_empty_graph(self, client):
        """Test graph data with no concepts."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.side_effect = [[], []]  # No concepts, no relationships

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/graph/data")

        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []


@pytest.mark.unit
class TestGraphQueryEndpoint:
    """Tests for POST /api/v1/graph/query endpoint."""

    def test_query_graph_success(self, client, mock_cypher_qa_service):
        """Test successful natural language graph query."""
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query",
                json={
                    "question": "What concepts are prerequisites for Photosynthesis?",
                    "preview_only": False,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "question" in data
        assert "cypher" in data
        assert "result" in data
        assert "answer" in data

        # Verify content
        assert "PREREQUISITE" in data["cypher"]
        assert len(data["result"]) == 2

    def test_query_graph_preview_only(self, client, mock_cypher_qa_service):
        """Test Cypher preview without execution."""
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query",
                json={
                    "question": "Find all concepts related to DNA",
                    "preview_only": True,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Should have Cypher but no result (not executed)
        assert data["cypher"] is not None
        assert data["result"] is None
        assert "Preview only" in data["answer"]

    def test_query_graph_error(self, client):
        """Test 500 when graph query fails."""
        failing_service = MagicMock()
        failing_service.query.side_effect = Exception("LangChain error")

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=failing_service,
        ):
            response = client.post(
                "/api/v1/graph/query",
                json={"question": "Test query"},
            )

        assert response.status_code == 500


@pytest.mark.unit
class TestConceptSearchEndpoint:
    """Tests for POST /api/v1/concepts/search endpoint."""

    def test_search_concepts_success(self, client, mock_neo4j_adapter):
        """Test successful concept search."""
        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_neo4j_adapter
        ):
            response = client.post(
                "/api/v1/concepts/search",
                json={"query": "photo", "limit": 10},
            )

        assert response.status_code == 200
        data = response.json()

        # Verify response is a list of concepts
        assert isinstance(data, list)
        assert len(data) == 2  # Mock returns 2 results

        # Verify concept structure
        concept = data[0]
        assert "name" in concept
        assert "score" in concept
        assert concept["name"] == "Photosynthesis"

    def test_search_concepts_empty_results(self, client):
        """Test search with no matching concepts."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None
        mock_adapter.fulltext_concept_search.return_value = []

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.post(
                "/api/v1/concepts/search",
                json={"query": "xyznonexistent", "limit": 10},
            )

        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.unit
class TestGraphSchemaEndpoint:
    """Tests for GET /api/v1/graph/schema endpoint."""

    def test_get_graph_schema_success(self, client, mock_cypher_qa_service):
        """Test successful schema retrieval."""
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.get("/api/v1/graph/schema")

        assert response.status_code == 200
        data = response.json()

        assert "schema" in data
        assert "Node types" in data["schema"]
        assert "Relationships" in data["schema"]

    def test_get_graph_schema_error(self, client):
        """Test 500 when schema retrieval fails."""
        failing_service = MagicMock()
        failing_service.get_schema.side_effect = Exception("Connection failed")

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=failing_service,
        ):
            response = client.get("/api/v1/graph/schema")

        assert response.status_code == 500


@pytest.mark.unit
class TestLearningPathEndpoint:
    """Tests for /api/v1/learning-path/* endpoints."""

    def test_get_learning_path_success(self, client):
        """Test successful learning path retrieval."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = [
            {
                "id": "node1",
                "name": "Chemistry Basics",
                "importance": 0.7,
                "chapter": "Ch1",
                "depth": 2,
            },
            {
                "id": "node2",
                "name": "Cell Structure",
                "importance": 0.8,
                "chapter": "Ch2",
                "depth": 1,
            },
        ]

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/learning-path/Photosynthesis")

        assert response.status_code == 200
        data = response.json()

        assert data["target_concept"] == "Photosynthesis"
        assert len(data["prerequisites"]) == 2
        assert data["total_concepts"] == 3  # 2 prerequisites + 1 target

    def test_get_learning_path_no_prerequisites(self, client):
        """Test learning path for concept with no prerequisites."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = []

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/learning-path/BasicConcept")

        assert response.status_code == 200
        data = response.json()
        assert data["prerequisites"] == []
        assert data["total_concepts"] == 1

    def test_get_prerequisites_success(self, client):
        """Test successful prerequisites retrieval."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = [
            {"name": "Prerequisite A", "importance": 0.7, "chapter": "Ch1", "level": 1},
            {"name": "Prerequisite B", "importance": 0.6, "chapter": "Ch1", "level": 2},
        ]

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get(
                "/api/v1/concepts/TestConcept/prerequisites", params={"depth": 2}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "TestConcept"
        assert len(data["prerequisites"]) == 2
        assert data["depth"] == 2

    def test_get_dependents_success(self, client):
        """Test successful dependents retrieval."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None
        mock_adapter.close.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = [
            {"name": "Advanced Topic A", "importance": 0.8, "chapter": "Ch5", "level": 1},
        ]

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_adapter.driver = mock_driver

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/concepts/BasicConcept/dependents")

        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "BasicConcept"
        assert len(data["dependents"]) == 1

    def test_learning_path_connection_error(self, client):
        """Test 503 when Neo4j connection fails."""
        mock_adapter = MagicMock()
        mock_adapter.connect.side_effect = Neo4jConnectionError("Connection refused")

        with patch(
            "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_adapter
        ):
            response = client.get("/api/v1/learning-path/Photosynthesis")

        assert response.status_code == 503
        assert "Database connection failed" in response.json()["detail"]
