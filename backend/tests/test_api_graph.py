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
- Input bounds, subject validation, Lucene escaping and the read-only query guard
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core.exceptions import (
    LLMConnectionError,
    LLMGenerationError,
    Neo4jConnectionError,
    Neo4jQueryError,
)
from backend.app.main import app


def create_mock_adapter_with_session(mock_session):
    """Helper to create a mock adapter with properly mocked _get_session."""
    mock_adapter = MagicMock()
    mock_adapter._get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_adapter._get_session.return_value.__exit__ = MagicMock(return_value=False)
    mock_adapter._get_label.side_effect = lambda x: x  # Return label as-is
    return mock_adapter


@pytest.mark.unit
class TestGraphStatsEndpoint:
    """Tests for GET /api/v1/graph/stats endpoint."""

    def test_get_graph_stats_success(self, client, mock_neo4j_adapter):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_neo4j_adapter
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
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            side_effect=Neo4jConnectionError("Connection refused"),
        ):
            response = client.get("/api/v1/graph/stats")

        assert response.status_code == 503
        assert "Database connection failed" in response.json()["detail"]

    def test_get_graph_stats_query_error(self, client):
        """Test 500 when Neo4j query fails."""
        failing_adapter = MagicMock()
        failing_adapter.get_graph_stats.side_effect = Neo4jQueryError("Query timeout")

        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            return_value=failing_adapter,
        ):
            response = client.get("/api/v1/graph/stats")

        assert response.status_code == 500


@pytest.mark.unit
class TestTopConceptsEndpoint:
    """Tests for GET /api/v1/concepts/top endpoint."""

    def test_get_top_concepts_success(self, client):
        """Test successful top concepts retrieval."""
        mock_session = MagicMock()
        mock_result = [
            {"name": "Photosynthesis", "score": 0.95, "is_key_term": True, "frequency": 50},
            {"name": "Mitosis", "score": 0.9, "is_key_term": True, "frequency": 45},
            {"name": "DNA", "score": 0.88, "is_key_term": True, "frequency": 60},
        ]
        mock_session.run.return_value = mock_result

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            response = client.get("/api/v1/concepts/top", params={"limit": 3})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["name"] == "Photosynthesis"

    def test_get_top_concepts_default_limit(self, client):
        """Test top concepts with default limit."""
        mock_session = MagicMock()
        mock_session.run.return_value = []

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
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

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
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
        mock_session = MagicMock()
        mock_session.run.side_effect = [[], []]  # No concepts, no relationships

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
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
        assert "PREREQ" in data["cypher"]
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
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_neo4j_adapter
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
        mock_adapter.fulltext_concept_search.return_value = []

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
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

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            response = client.get("/api/v1/learning-path/Photosynthesis")

        assert response.status_code == 200
        data = response.json()

        assert data["target_concept"] == "Photosynthesis"
        assert len(data["prerequisites"]) == 2
        assert data["total_concepts"] == 3  # 2 prerequisites + 1 target
        assert "PREREQ" in mock_session.run.call_args.args[0]
        assert "PREREQUISITE" not in mock_session.run.call_args.args[0]

    def test_get_learning_path_no_prerequisites(self, client):
        """Test learning path for concept with no prerequisites."""
        mock_session = MagicMock()
        mock_session.run.return_value = []

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            response = client.get("/api/v1/learning-path/BasicConcept")

        assert response.status_code == 200
        data = response.json()
        assert data["prerequisites"] == []
        assert data["total_concepts"] == 1

    def test_get_prerequisites_success(self, client):
        """Test successful prerequisites retrieval."""
        mock_session = MagicMock()
        mock_session.run.return_value = [
            {"name": "Prerequisite A", "importance": 0.7, "chapter": "Ch1", "level": 1},
            {"name": "Prerequisite B", "importance": 0.6, "chapter": "Ch1", "level": 2},
        ]

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            response = client.get("/api/v1/concepts/TestConcept/prerequisites", params={"depth": 2})

        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "TestConcept"
        assert len(data["prerequisites"]) == 2
        assert data["depth"] == 2
        assert "PREREQ" in mock_session.run.call_args.args[0]
        assert "PREREQUISITE" not in mock_session.run.call_args.args[0]

    def test_get_dependents_success(self, client):
        """Test successful dependents retrieval."""
        mock_session = MagicMock()
        mock_session.run.return_value = [
            {"name": "Advanced Topic A", "importance": 0.8, "chapter": "Ch5", "level": 1},
        ]

        mock_adapter = create_mock_adapter_with_session(mock_session)

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_adapter):
            response = client.get("/api/v1/concepts/BasicConcept/dependents")

        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "BasicConcept"
        assert len(data["dependents"]) == 1
        assert "PREREQ" in mock_session.run.call_args.args[0]
        assert "PREREQUISITE" not in mock_session.run.call_args.args[0]

    def test_learning_path_connection_error(self, client):
        """Test 503 when Neo4j connection fails."""
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            side_effect=Neo4jConnectionError("Connection refused"),
        ):
            response = client.get("/api/v1/learning-path/Photosynthesis")

        assert response.status_code == 503
        assert "Database connection failed" in response.json()["detail"]


def _session_adapter(*run_results):
    """Mock adapter whose session returns the given results for successive queries."""
    session = MagicMock()
    if len(run_results) == 1:
        session.run.return_value = run_results[0]
    else:
        session.run.side_effect = list(run_results)
    return create_mock_adapter_with_session(session), session


@pytest.mark.unit
class TestGraphBounds:
    """Bounds on limit and depth parameters."""

    @pytest.mark.parametrize("limit", [0, -10, 501, 1_000_000])
    def test_graph_data_limit_out_of_range(self, client, limit):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.get("/api/v1/graph/data", params={"limit": limit})

        assert response.status_code == 422
        factory.assert_not_called()

    def test_graph_data_accepts_max_limit(self, client):
        adapter, session = _session_adapter([], [])

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter):
            response = client.get("/api/v1/graph/data", params={"limit": 500})

        assert response.status_code == 200
        assert session.run.call_args_list[0].kwargs["limit"] == 500

    def test_graph_data_cache_key_uses_validated_limit(self, client):
        adapter, _session = _session_adapter([], [])

        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter
        ) as factory:
            first = client.get("/api/v1/graph/data")
            second = client.get("/api/v1/graph/data", params={"limit": "100"})

        assert first.status_code == second.status_code == 200
        factory.assert_called_once()  # the second request is served from the cache

    @pytest.mark.parametrize("limit", [0, -5, 101])
    def test_top_concepts_limit_out_of_range(self, client, limit):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.get("/api/v1/concepts/top", params={"limit": limit})

        assert response.status_code == 422
        factory.assert_not_called()

    def test_top_concepts_accepts_max_limit(self, client):
        adapter, session = _session_adapter([])

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter):
            response = client.get("/api/v1/concepts/top", params={"limit": 100})

        assert response.status_code == 200
        assert session.run.call_args.kwargs["limit"] == 100

    @pytest.mark.parametrize(
        ("path", "param"),
        [
            ("/api/v1/learning-path/Photosynthesis", "max_depth"),
            ("/api/v1/concepts/Photosynthesis/prerequisites", "depth"),
            ("/api/v1/concepts/Photosynthesis/dependents", "depth"),
        ],
    )
    @pytest.mark.parametrize("depth", [0, -1, 11, 99999])
    def test_depth_out_of_range(self, client, path, param, depth):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.get(path, params={param: depth})

        assert response.status_code == 422
        factory.assert_not_called()

    @pytest.mark.parametrize(
        ("path", "params", "expected_hops"),
        [
            ("/api/v1/learning-path/Photosynthesis", {}, "*1..3]"),
            ("/api/v1/learning-path/Photosynthesis", {"max_depth": 10}, "*1..10]"),
            ("/api/v1/concepts/Photosynthesis/prerequisites", {}, "*1..2]"),
            ("/api/v1/concepts/Photosynthesis/prerequisites", {"depth": 4}, "*1..4]"),
            ("/api/v1/concepts/Photosynthesis/dependents", {}, "*1..2]"),
            ("/api/v1/concepts/Photosynthesis/dependents", {"depth": 1}, "*1..1]"),
        ],
    )
    def test_depth_bounds_the_traversal(self, client, path, params, expected_hops):
        adapter, session = _session_adapter([])

        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter):
            response = client.get(path, params=params)

        assert response.status_code == 200
        query = session.run.call_args.args[0]
        assert f"[:PREREQ{expected_hops}" in query
        assert "[:PREREQ*1..]" not in query
        assert "length(path) <=" not in query
        assert session.run.call_args.kwargs == {"name": "Photosynthesis"}

    def test_blank_concept_name_is_rejected(self, client):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.get("/api/v1/learning-path/%20%20")

        assert response.status_code == 422
        factory.assert_not_called()


@pytest.mark.unit
class TestGraphSubjectValidation:
    """Every graph endpoint validates the subject before touching Neo4j."""

    ENDPOINTS = [
        ("get", "/api/v1/graph/stats", None),
        ("get", "/api/v1/graph/data", None),
        ("get", "/api/v1/concepts/top", None),
        ("post", "/api/v1/concepts/search", {"query": "tariffs"}),
        ("get", "/api/v1/learning-path/Tariffs", None),
        ("get", "/api/v1/concepts/Tariffs/prerequisites", None),
        ("get", "/api/v1/concepts/Tariffs/dependents", None),
    ]

    @pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
    def test_unknown_subject_is_404(self, client, method, path, body):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.request(
                method, path, params={"subject": "no_such_subject"}, json=body
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Subject not found"
        factory.assert_not_called()

    @pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
    def test_malformed_subject_is_422(self, client, method, path, body):
        with patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter") as factory:
            response = client.request(
                method, path, params={"subject": "'; DROP DATABASE neo4j; --"}, json=body
            )

        assert response.status_code == 422
        factory.assert_not_called()

    def test_known_subject_reaches_adapter(self, client, mock_neo4j_adapter):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_neo4j_adapter
        ) as factory:
            response = client.get("/api/v1/graph/stats", params={"subject": "biology"})

        assert response.status_code == 200
        factory.assert_called_once_with("biology")


@pytest.mark.unit
class TestConceptSearchEscaping:
    """Lucene syntax in concept search is matched literally."""

    @pytest.mark.parametrize(
        ("query", "sent"),
        [
            ("*:*", r"\*\:\*"),
            ("  photo*  ", r"photo\*"),
            ("C++ (economics)", r"C\+\+ \(economics\)"),
            ("tariffs OR name:x", r"tariffs or name\:x"),
            ("photosynthesis", "photosynthesis"),
        ],
    )
    def test_query_is_escaped_before_search(self, client, mock_neo4j_adapter, query, sent):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_neo4j_adapter
        ):
            response = client.post("/api/v1/concepts/search", json={"query": query})

        assert response.status_code == 200
        mock_neo4j_adapter.fulltext_concept_search.assert_called_once_with(
            query_text=sent, limit=10
        )

    @pytest.mark.parametrize("query", ["   ", "x" * 501])
    def test_invalid_query_is_422(self, client, mock_neo4j_adapter, query):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=mock_neo4j_adapter
        ):
            response = client.post("/api/v1/concepts/search", json={"query": query})

        assert response.status_code == 422
        mock_neo4j_adapter.fulltext_concept_search.assert_not_called()


@pytest.mark.unit
class TestGraphQueryGuard:
    """The natural-language guard blocks write requests, not ordinary questions."""

    @pytest.mark.parametrize(
        "question",
        [
            "What caused the drop in GDP?",
            "Why did the stock market drop in 1929?",
            "Who created the Federal Reserve?",
            "What set of reforms followed the Civil War?",
            "How did the colonists remove British officials?",
            "Is there clear data on inflation?",
            "Find all concepts related to DNA",
        ],
    )
    def test_ordinary_questions_are_allowed(self, client, mock_cypher_qa_service, question):
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post("/api/v1/graph/query", json={"question": question})

        assert response.status_code == 200
        mock_cypher_qa_service.query.assert_called_once_with(question)

    @pytest.mark.parametrize(
        "question",
        [
            "Delete all nodes in the database",
            "MATCH (n) DETACH DELETE n",
            "MATCH (n) DELETE n",
            "drop index concept_names",
            "DROP CONSTRAINT unique_concept_name",
            "CREATE (n:Concept {name: 'Fake'})",
            "MATCH (c:Concept) SET c.name = 'x'",
            "Remove the Photosynthesis concept",
            "Please clear the graph",
            "Can you delete every relationship?",
            "wipe all data",
        ],
    )
    def test_write_requests_are_blocked(self, client, mock_cypher_qa_service, question):
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post("/api/v1/graph/query", json={"question": question})

        assert response.status_code == 400
        assert "read queries" in response.json()["detail"]
        mock_cypher_qa_service.query.assert_not_called()

    def test_blocked_cypher_from_service_is_400(self, client, mock_cypher_qa_service):
        class BlockedCypherError(ValueError):
            pass

        mock_cypher_qa_service.query.side_effect = BlockedCypherError("write query blocked")

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            (LLMGenerationError("Cypher QA chain failed"), "LLM service temporarily unavailable"),
            (LLMConnectionError("Ollama connection failed"), "LLM service temporarily unavailable"),
            (Neo4jConnectionError("Neo4j is not available"), "Database connection failed"),
        ],
        ids=["llm-error", "llm-unreachable", "neo4j-unavailable"],
    )
    def test_upstream_failures_are_503(self, client, mock_cypher_qa_service, error, detail):
        mock_cypher_qa_service.query.side_effect = error

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == 503
        assert response.json()["detail"] == detail

    def test_generated_cypher_error_is_502(self, client, mock_cypher_qa_service):
        """An invalid generated query is 502, although it subclasses LLMGenerationError."""
        from backend.app.kg.cypher_qa import GeneratedCypherError

        mock_cypher_qa_service.query.side_effect = GeneratedCypherError(
            "The model generated an invalid query"
        )

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == 502
        assert response.json()["detail"] == "The model generated an invalid query"

    def test_response_has_no_error_field(self, client, mock_cypher_qa_service):
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == 200
        assert set(response.json()) == {"question", "cypher", "result", "answer"}

    def test_error_responses_are_declared_in_openapi(self):
        responses = app.openapi()["paths"]["/api/v1/graph/query"]["post"]["responses"]

        assert {"400", "401", "422", "429", "502", "503"} <= set(responses)

    def test_malformed_service_result_is_500(self, client, mock_cypher_qa_service):
        mock_cypher_qa_service.query.return_value = {"question": "q", "result": {"not": "a list"}}

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"

    def test_blank_question_is_422(self, client, mock_cypher_qa_service):
        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post("/api/v1/graph/query", json={"question": "   "})

        assert response.status_code == 422
        mock_cypher_qa_service.query.assert_not_called()

    @pytest.mark.parametrize("preview_only", [False, True])
    def test_service_calls_run_off_the_event_loop(
        self, client, mock_cypher_qa_service, preview_only
    ):
        on_event_loop: list[bool] = []

        def record_loop(*_args, **_kwargs):
            try:
                asyncio.get_running_loop()
                on_event_loop.append(True)
            except RuntimeError:
                on_event_loop.append(False)

        mock_cypher_qa_service.query.side_effect = lambda question: (
            record_loop() or {"question": question, "cypher": "RETURN 1", "result": [1]}
        )
        mock_cypher_qa_service.generate_cypher_only.side_effect = lambda question: (
            record_loop() or "RETURN 1"
        )

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            response = client.post(
                "/api/v1/graph/query",
                json={"question": "Which concepts cover tariffs?", "preview_only": preview_only},
            )

        assert response.status_code == 200
        assert on_event_loop == [False]
