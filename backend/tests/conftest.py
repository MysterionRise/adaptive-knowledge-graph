"""
Pytest configuration and shared fixtures.

Provides:
- Test settings with mocked services
- Mock factories for Neo4j, OpenSearch, LLM
- TestClient fixture for API testing
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.settings import Settings
from backend.app.main import app


@pytest.fixture(scope="session")
def test_settings():
    """Create test settings."""
    return Settings(
        debug=True,
        log_level="DEBUG",
        neo4j_uri="bolt://localhost:7687",
        opensearch_host="localhost",
        privacy_local_only=True,
    )


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directories."""
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "processed").mkdir(parents=True)
    return data_dir


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PRIVACY_LOCAL_ONLY", "true")


@pytest.fixture
def mock_neo4j_uri():
    """Mock Neo4j connection URI."""
    return "bolt://localhost:7687"


@pytest.fixture
def mock_opensearch_config():
    """Mock OpenSearch configuration."""
    return {
        "host": "localhost",
        "port": 9200,
        "index": "test_index",
    }


# ==========================================================================
# Mock Factories for Services
# ==========================================================================


@pytest.fixture
def mock_neo4j_adapter():
    """
    Mock Neo4j adapter for testing graph operations.

    Returns a MagicMock configured with common responses.
    """
    adapter = MagicMock()
    adapter.connect.return_value = None
    adapter.close.return_value = None

    # Mock driver and session
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter.driver = mock_driver

    # Default stats response
    adapter.get_graph_stats.return_value = {
        "Concept_count": 150,
        "Module_count": 25,
        "CONTAINS_relationships": 300,
        "RELATED_TO_relationships": 200,
        "PREREQUISITE_relationships": 100,
    }

    # Default fulltext search response
    adapter.fulltext_concept_search.return_value = [
        {"name": "Photosynthesis", "importance_score": 0.9, "key_term": True, "score": 5.5},
        {"name": "Chloroplast", "importance_score": 0.8, "key_term": True, "score": 4.2},
    ]

    return adapter


@pytest.fixture
def mock_retriever():
    """
    Mock retriever for RAG testing.

    Returns a MagicMock that simulates chunk retrieval.
    """
    retriever = MagicMock()
    retriever.retrieve.return_value = [
        {
            "text": "Photosynthesis is the process by which plants convert sunlight into energy.",
            "module_id": "mod_001",
            "module_title": "Introduction to Biology",
            "section": "Chapter 5.1",
            "score": 0.95,
            "id": "chunk_001",
        },
        {
            "text": "Chlorophyll is the green pigment responsible for absorbing light energy.",
            "module_id": "mod_001",
            "module_title": "Introduction to Biology",
            "section": "Chapter 5.2",
            "score": 0.88,
            "id": "chunk_002",
        },
        {
            "text": "The light-dependent reactions occur in the thylakoid membrane.",
            "module_id": "mod_002",
            "module_title": "Cell Biology",
            "section": "Chapter 6.1",
            "score": 0.82,
            "id": "chunk_003",
        },
    ]
    return retriever


@pytest.fixture
def mock_llm_client():
    """
    Mock LLM client for testing answer generation.

    Returns an AsyncMock that simulates LLM responses.
    """
    client = AsyncMock()
    client.answer_question.return_value = {
        "answer": (
            "Photosynthesis is the process by which plants and other organisms "
            "convert light energy into chemical energy stored in glucose. "
            "This process occurs primarily in the chloroplasts, where chlorophyll "
            "absorbs sunlight. The light-dependent reactions take place in the "
            "thylakoid membrane, producing ATP and NADPH."
        ),
        "model": "llama3.1:8b-instruct-q4_K_M",
    }
    return client


@pytest.fixture
def mock_kg_expander():
    """
    Mock KG expander for testing query expansion.

    Returns a MagicMock that simulates concept extraction and expansion.
    """
    expander = MagicMock()
    expander.expand_query.return_value = {
        "original_query": "What is photosynthesis?",
        "extracted_concepts": ["photosynthesis"],
        "expanded_concepts": ["photosynthesis", "chloroplast", "chlorophyll", "ATP"],
        "expanded_query": "What is photosynthesis? (Related: chloroplast, chlorophyll, ATP)",
    }
    return expander


@pytest.fixture
def mock_quiz_generator():
    """
    Mock quiz generator for testing quiz endpoints.

    Returns an AsyncMock that simulates quiz generation.
    """
    from backend.app.ui_payloads.quiz import Quiz, QuizOption, QuizQuestion

    generator = AsyncMock()
    generator.generate_from_topic.return_value = Quiz(
        id="quiz_001",
        title="Photosynthesis Quiz",
        questions=[
            QuizQuestion(
                id="q1",
                text="What is the primary function of photosynthesis?",
                options=[
                    QuizOption(id="a", text="Convert light to chemical energy"),
                    QuizOption(id="b", text="Break down glucose"),
                    QuizOption(id="c", text="Transport nutrients"),
                    QuizOption(id="d", text="Produce carbon dioxide"),
                ],
                correct_option_id="a",
                explanation="Photosynthesis converts light energy into chemical energy.",
                related_concept="Photosynthesis",
            ),
            QuizQuestion(
                id="q2",
                text="Where does photosynthesis primarily occur?",
                options=[
                    QuizOption(id="a", text="Mitochondria"),
                    QuizOption(id="b", text="Chloroplasts"),
                    QuizOption(id="c", text="Nucleus"),
                    QuizOption(id="d", text="Cell membrane"),
                ],
                correct_option_id="b",
                explanation="Photosynthesis occurs in chloroplasts.",
                related_concept="Chloroplast",
            ),
        ],
    )
    return generator


@pytest.fixture
def mock_cypher_qa_service():
    """
    Mock Cypher QA service for testing natural language graph queries.

    Returns a MagicMock that simulates Cypher generation and execution.
    """
    service = MagicMock()
    service.query.return_value = {
        "question": "What concepts are prerequisites for Photosynthesis?",
        "cypher": "MATCH (p:Concept)-[:PREREQUISITE]->(c:Concept {name: 'Photosynthesis'}) RETURN p",
        "result": [
            {"name": "Chemistry Basics", "importance_score": 0.7},
            {"name": "Cell Structure", "importance_score": 0.8},
        ],
        "answer": "The prerequisites for Photosynthesis are Chemistry Basics and Cell Structure.",
        "error": None,
    }
    service.generate_cypher_only.return_value = (
        "MATCH (p:Concept)-[:PREREQUISITE]->(c:Concept {name: 'Photosynthesis'}) RETURN p"
    )
    service.get_schema.return_value = (
        "Node types: Concept, Module, Chunk. "
        "Relationships: CONTAINS, RELATED_TO, PREREQUISITE, NEXT."
    )
    return service


# ==========================================================================
# Patch Context Managers
# ==========================================================================


@pytest.fixture
def patch_neo4j(mock_neo4j_adapter):
    """Patch Neo4jAdapter with mock."""
    with patch(
        "backend.app.kg.neo4j_adapter.Neo4jAdapter", return_value=mock_neo4j_adapter
    ) as mock:
        yield mock


@pytest.fixture
def patch_retriever(mock_retriever):
    """Patch get_retriever with mock."""
    with patch(
        "backend.app.api.routes.ask.get_retriever", return_value=mock_retriever
    ) as mock:
        yield mock


@pytest.fixture
def patch_llm_client(mock_llm_client):
    """Patch get_llm_client with mock."""
    with patch(
        "backend.app.api.routes.ask.get_llm_client", return_value=mock_llm_client
    ) as mock:
        yield mock


@pytest.fixture
def patch_kg_expander(mock_kg_expander):
    """Patch KG expander functions."""
    with patch(
        "backend.app.api.routes.ask.get_kg_expander", return_value=mock_kg_expander
    ) as mock_expander, patch(
        "backend.app.api.routes.ask.get_all_concepts_from_neo4j",
        return_value=["photosynthesis", "chloroplast", "chlorophyll", "ATP"],
    ) as mock_concepts:
        yield mock_expander, mock_concepts


@pytest.fixture
def patch_quiz_generator(mock_quiz_generator):
    """Patch get_quiz_generator with mock."""
    with patch(
        "backend.app.api.routes.quiz.get_quiz_generator", return_value=mock_quiz_generator
    ) as mock:
        yield mock


@pytest.fixture
def patch_cypher_qa(mock_cypher_qa_service):
    """Patch get_cypher_qa_service with mock."""
    with patch(
        "backend.app.api.routes.graph.get_cypher_qa_service", return_value=mock_cypher_qa_service
    ) as mock:
        yield mock


# ==========================================================================
# Sample Data Fixtures
# ==========================================================================


@pytest.fixture
def sample_question_request():
    """Sample question request payload."""
    return {
        "question": "What is photosynthesis and how does it work?",
        "use_kg_expansion": True,
        "use_window_retrieval": False,
        "top_k": 5,
    }


@pytest.fixture
def sample_quiz_topic():
    """Sample quiz topic."""
    return "Photosynthesis"


@pytest.fixture
def sample_graph_query_request():
    """Sample graph query request payload."""
    return {
        "question": "What concepts are prerequisites for Photosynthesis?",
        "preview_only": False,
    }


@pytest.fixture
def sample_concept_search_request():
    """Sample concept search request payload."""
    return {
        "query": "photo",
        "limit": 10,
    }
