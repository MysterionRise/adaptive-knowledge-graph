"""
Pytest configuration and shared fixtures.
"""

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
