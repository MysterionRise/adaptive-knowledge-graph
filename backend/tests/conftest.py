"""
Pytest configuration and shared fixtures.

Provides:
- Per-test timeout, rate-limiter and graph-cache isolation (autouse)
- TestClient fixtures for the default app and for explicit development/production apps
- Mock factories for Neo4j, retrieval, LLM, quiz generation and Cypher QA
"""

import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.settings import Settings
from backend.app.main import app, create_app

# API key configured on production-mode test apps (production requires 16+ characters).
TEST_API_KEY = "test-api-key-for-production"


@pytest.fixture(autouse=True)
def per_test_timeout():
    """Bound individual backend tests so CI cannot hang indefinitely."""
    timeout_seconds = int(os.getenv("PYTEST_TEST_TIMEOUT_SECONDS", "60"))
    if timeout_seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handle_timeout(signum, frame):
        raise TimeoutError(f"Test exceeded {timeout_seconds}s timeout")

    previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def production_settings():
    """APP_ENV=production settings with an API key configured (no .env file)."""
    return Settings(_env_file=None, app_env="production", api_key=TEST_API_KEY)


@pytest.fixture
def production_client(production_settings):
    """Test client for an app built in production mode (API key required, no docs)."""
    return TestClient(create_app(production_settings))


@pytest.fixture
def development_client():
    """Test client for a keyless development-mode app, whatever the environment says."""
    return TestClient(create_app(Settings(_env_file=None, app_env="development", api_key="")))


@pytest.fixture
def captured_logs():
    """Loguru messages emitted during the test; each item's ``.record`` has the details."""
    from loguru import logger

    messages: list = []
    handler_id = logger.add(messages.append, level="DEBUG", format="{message}")
    yield messages
    try:
        logger.remove(handler_id)
    except ValueError:  # the test reconfigured logging and already removed it
        pass


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment variables and clear caches."""
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PRIVACY_LOCAL_ONLY", "true")

    # Disable rate limiting in tests, and start every test with empty counters
    from backend.app.core.rate_limit import limiter

    limiter.enabled = False
    limiter.reset()

    # Clear graph response cache between tests
    from backend.app.api.routes.graph import clear_graph_cache

    clear_graph_cache()

    yield

    # Re-enable rate limiting after test
    limiter.enabled = True


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
        "PREREQ_relationships": 100,
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
        "cypher": "MATCH (p:Concept)-[:PREREQ]->(c:Concept {name: 'Photosynthesis'}) RETURN p",
        "result": [
            {"name": "Chemistry Basics", "importance_score": 0.7},
            {"name": "Cell Structure", "importance_score": 0.8},
        ],
        "answer": "The prerequisites for Photosynthesis are Chemistry Basics and Cell Structure.",
        "error": None,
    }
    service.generate_cypher_only.return_value = (
        "MATCH (p:Concept)-[:PREREQ]->(c:Concept {name: 'Photosynthesis'}) RETURN p"
    )
    service.get_schema.return_value = (
        "Node types: Concept, Module, Chunk. Relationships: CONTAINS, RELATED_TO, PREREQ, NEXT."
    )
    return service


def mock_neo4j_driver(records: list[dict] | None = None) -> MagicMock:
    """A mocked ``neo4j.Driver`` whose READ transactions return ``records``.

    ``driver.session(...)`` yields ``driver.mock_session``; ``session.execute_read(work)``
    calls ``work`` with ``driver.mock_tx``, whose ``run()`` result fetches ``records``.
    """
    driver = MagicMock(name="neo4j_driver")
    session = MagicMock(name="session")
    tx = MagicMock(name="managed_transaction")
    fetched = [MagicMock(data=MagicMock(return_value=record)) for record in records or []]
    tx.run.return_value.fetch.return_value = fetched
    tx.run.return_value.__iter__.side_effect = lambda: iter(fetched)
    session.execute_read.side_effect = lambda work, *args, **kwargs: work(tx, *args, **kwargs)
    driver.session.return_value.__enter__.return_value = session
    driver.mock_session = session
    driver.mock_tx = tx
    return driver


@pytest.fixture
def make_neo4j_driver():
    """Factory fixture: ``make_neo4j_driver(records)`` returns ``mock_neo4j_driver(records)``."""
    return mock_neo4j_driver


@pytest.fixture
def make_cypher_qa_service():
    """Build a real ``CypherQAService`` (real chain) on a fake LLM and a mocked driver.

    ``make_cypher_qa_service(*llm_responses, records=[...])`` returns ``(service, driver)``;
    the LLM answers the Cypher-generation prompt, then the QA prompt, in order. Nothing
    touches the network.
    """
    from langchain_core.language_models import FakeListLLM

    from backend.app.kg.cypher_qa import CypherQAService, ReadOnlyNeo4jGraph

    def _make(*llm_responses: str, records: list[dict] | None = None):
        driver = mock_neo4j_driver(records)
        with patch("neo4j.GraphDatabase.driver", return_value=driver):
            graph = ReadOnlyNeo4jGraph(
                url="bolt://neo4j.test:7687",
                username="neo4j",
                password="test-password",
                refresh_schema=False,
            )
        graph.structured_schema = {
            "node_props": {"Concept": [{"property": "name", "type": "STRING"}]},
            "rel_props": {},
            "relationships": [{"start": "Concept", "type": "PREREQ", "end": "Concept"}],
            "metadata": {"constraint": [], "index": []},
        }
        service = CypherQAService()
        service._graph = graph
        service._llm = FakeListLLM(responses=list(llm_responses))
        return service, driver

    return _make
