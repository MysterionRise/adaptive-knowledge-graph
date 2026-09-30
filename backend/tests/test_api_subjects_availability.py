"""
Tests for the `available` flag on GET /api/v1/subjects.

A subject is available when its knowledge graph has at least one concept. The Neo4j
adapter is mocked; the flag is cached, so each test starts with an empty cache.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.app.api.routes import subjects as subjects_routes
from backend.app.core.subjects import get_default_subject_id, get_subject_ids
from backend.app.main import app

ADAPTER_FACTORY = "backend.app.kg.neo4j_adapter.get_neo4j_adapter"


@pytest.fixture(autouse=True)
def fresh_availability_cache():
    subjects_routes.clear_subject_availability_cache()
    yield
    subjects_routes.clear_subject_availability_cache()


def _adapter(concept_count: int) -> MagicMock:
    adapter = MagicMock()
    adapter.get_graph_stats.return_value = {"Concept_count": concept_count, "Module_count": 2}
    return adapter


def _availability(response) -> dict[str, bool]:
    return {summary["id"]: summary["available"] for summary in response.json()["subjects"]}


@pytest.mark.unit
class TestSubjectAvailability:
    """Tests for the subject `available` flag."""

    def test_available_reflects_concept_counts(self, client):
        subject_ids = get_subject_ids()
        seeded = get_default_subject_id()
        unreachable = next(subject_id for subject_id in subject_ids if subject_id != seeded)

        def adapter_for(subject_id):
            if subject_id == unreachable:
                raise ConnectionError("Neo4j unreachable")
            return _adapter(42 if subject_id == seeded else 0)

        with patch(ADAPTER_FACTORY, side_effect=adapter_for):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        availability = _availability(response)
        assert set(availability) == set(subject_ids)
        assert availability[seeded] is True
        assert not any(availability[s] for s in subject_ids if s != seeded)

    def test_neo4j_outage_marks_every_subject_unavailable(self, client):
        with patch(ADAPTER_FACTORY, side_effect=ConnectionError("Neo4j unreachable")):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        data = response.json()
        assert not any(_availability(response).values())
        assert [s["id"] for s in data["subjects"] if s["is_default"]] == [data["default_subject"]]

    def test_stats_query_failure_marks_subject_unavailable(self, client):
        failing = MagicMock()
        failing.get_graph_stats.side_effect = RuntimeError("Neo.ClientError.Security.Unauthorized")

        with patch(ADAPTER_FACTORY, return_value=failing):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        assert not any(_availability(response).values())

    def test_availability_is_cached(self, client):
        with patch(ADAPTER_FACTORY, return_value=_adapter(5)) as factory:
            first = client.get("/api/v1/subjects")
            second = client.get("/api/v1/subjects")

        assert first.status_code == second.status_code == 200
        assert _availability(first) == _availability(second)
        assert all(_availability(second).values())
        assert factory.call_count == len(get_subject_ids())

    def test_availability_is_rechecked_after_ttl(self, client):
        with patch(ADAPTER_FACTORY, return_value=_adapter(0)):
            first = client.get("/api/v1/subjects")
        assert not any(_availability(first).values())

        # Age every cached entry past the TTL
        cache = subjects_routes._availability_cache
        for subject_id, (checked_at, available) in list(cache.items()):
            cache[subject_id] = (
                checked_at - subjects_routes.AVAILABILITY_CACHE_TTL_SECONDS - 1,
                available,
            )

        with patch(ADAPTER_FACTORY, return_value=_adapter(7)) as factory:
            second = client.get("/api/v1/subjects")

        assert all(_availability(second).values())
        assert factory.call_count == len(get_subject_ids())

    def test_neo4j_checks_run_off_the_event_loop(self, client):
        on_event_loop: list[bool] = []

        def adapter_for(subject_id):
            try:
                asyncio.get_running_loop()
                on_event_loop.append(True)
            except RuntimeError:
                on_event_loop.append(False)
            return _adapter(1)

        with patch(ADAPTER_FACTORY, side_effect=adapter_for):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        assert on_event_loop
        assert not any(on_event_loop)

    def test_openapi_documents_available_flag(self):
        schema = app.openapi()["components"]["schemas"]["SubjectSummary"]

        assert schema["properties"]["available"]["type"] == "boolean"
