"""Tests for client-demo readiness status endpoints."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.app.api.routes import demo
from backend.app.core.settings import settings


@pytest.mark.unit
class TestDemoStatusEndpoint:
    """Tests for GET /api/v1/demo/status."""

    def test_demo_status_ready(self, client, monkeypatch):
        """Aggregates healthy services, seeded subjects, and a valid eval report."""

        async def ok_neo4j():
            return demo.DemoServiceStatus(status="ok", latency_ms=12.3)

        async def ok_opensearch():
            return demo.DemoServiceStatus(status="ok", latency_ms=8.1)

        async def ok_ollama():
            return demo.DemoServiceStatus(status="ok", latency_ms=15.2)

        monkeypatch.setattr(demo, "_check_neo4j", ok_neo4j)
        monkeypatch.setattr(demo, "_check_opensearch", ok_opensearch)
        monkeypatch.setattr(demo, "_check_ollama", ok_ollama)
        monkeypatch.setattr(
            demo,
            "_subject_statuses",
            lambda: [
                demo.DemoSubjectStatus(
                    id="us_history",
                    name="US History",
                    status="ok",
                    concept_count=100,
                    module_count=10,
                    relationship_count=200,
                )
            ],
        )
        monkeypatch.setattr(
            demo,
            "_latest_eval_status",
            lambda: demo.DemoEvalStatus(
                status="ok",
                environment_valid=True,
                cases=50,
                kg_successful_cases=50,
                plain_successful_cases=50,
            ),
        )

        response = client.get("/api/v1/demo/status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["script_readiness"]["latest_eval_valid"] is True
        assert payload["next_actions"] == []

    def test_demo_status_degraded_when_eval_invalid(self, client, monkeypatch):
        """A seeded local stack with an invalid eval report is not marked ready."""

        async def ok_service():
            return demo.DemoServiceStatus(status="ok")

        monkeypatch.setattr(demo, "_check_neo4j", ok_service)
        monkeypatch.setattr(demo, "_check_opensearch", ok_service)
        monkeypatch.setattr(demo, "_check_ollama", ok_service)
        monkeypatch.setattr(
            demo,
            "_subject_statuses",
            lambda: [
                demo.DemoSubjectStatus(
                    id="us_history",
                    name="US History",
                    status="ok",
                    concept_count=100,
                )
            ],
        )
        monkeypatch.setattr(
            demo,
            "_latest_eval_status",
            lambda: demo.DemoEvalStatus(
                status="error",
                environment_valid=False,
                message="Latest eval is missing successful live KG/plain cases.",
            ),
        )

        response = client.get("/api/v1/demo/status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "degraded"
        assert payload["script_readiness"]["latest_eval_valid"] is False
        assert any("demo-eval" in action for action in payload["next_actions"])

    def test_latest_eval_status_hides_local_paths(self, tmp_path):
        """Malformed eval reports do not expose filesystem paths."""
        report_path = tmp_path / "latest.json"
        report_path.write_text("{not-json", encoding="utf-8")

        status = demo._latest_eval_status(Path(report_path))

        assert status.status == "error"
        assert status.message
        assert str(tmp_path) not in status.message


SECRET_ERROR = "bolt://neo4j:hunter2@internal-db:7687 refused"


def _logged_warning(captured_logs, text: str) -> bool:
    return any(
        text in message
        and message.record["level"].name == "WARNING"
        and message.record["exception"] is not None
        for message in captured_logs
    )


@pytest.mark.unit
class TestDemoStatusFailures:
    """Failed checks report fixed messages; the underlying error is only logged."""

    def test_neo4j_failure(self, captured_logs):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            side_effect=RuntimeError(SECRET_ERROR),
        ):
            status = asyncio.run(demo._check_neo4j())

        assert status == demo.DemoServiceStatus(status="error", message="Neo4j unavailable")
        assert _logged_warning(captured_logs, "Neo4j check failed")

    def test_opensearch_failure(self, captured_logs):
        with patch.object(
            httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError(SECRET_ERROR))
        ):
            status = asyncio.run(demo._check_opensearch())

        assert status == demo.DemoServiceStatus(status="error", message="OpenSearch unavailable")
        assert _logged_warning(captured_logs, "OpenSearch check failed")

    def test_ollama_failure(self, captured_logs, monkeypatch):
        monkeypatch.setattr(settings, "llm_mode", "local")

        with patch.object(
            httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError(SECRET_ERROR))
        ):
            status = asyncio.run(demo._check_ollama())

        assert status == demo.DemoServiceStatus(status="error", message="Ollama unavailable")
        assert _logged_warning(captured_logs, "Ollama check failed")

    def test_subject_graph_failure(self, captured_logs):
        with patch(
            "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
            side_effect=RuntimeError(SECRET_ERROR),
        ):
            statuses = demo._subject_statuses()

        assert statuses
        assert {(s.status, s.message) for s in statuses} == {
            ("error", "Graph statistics unavailable")
        }
        assert _logged_warning(captured_logs, "graph statistics failed for subject")

    def test_subject_configuration_failure(self, captured_logs):
        with patch.object(demo, "get_all_subjects", side_effect=RuntimeError(SECRET_ERROR)):
            statuses = demo._subject_statuses()

        assert statuses == [
            demo.DemoSubjectStatus(
                id="subjects",
                name="Subject configuration",
                status="error",
                message="Subject configuration could not be loaded",
            )
        ]
        assert _logged_warning(captured_logs, "subject configuration failed to load")

    def test_malformed_eval_report(self, captured_logs, tmp_path):
        report_path = tmp_path / "latest.json"
        report_path.write_text("{not-json", encoding="utf-8")

        status = demo._latest_eval_status(report_path)

        assert status == demo.DemoEvalStatus(
            status="error", message="Latest eval report could not be read"
        )
        assert _logged_warning(captured_logs, "latest eval report could not be read")

    def test_endpoint_does_not_leak_errors(self, client, monkeypatch):
        monkeypatch.setattr(
            demo, "_latest_eval_status", lambda: demo.DemoEvalStatus(status="missing")
        )

        with (
            patch(
                "backend.app.kg.neo4j_adapter.get_neo4j_adapter",
                side_effect=RuntimeError(SECRET_ERROR),
            ),
            patch.object(
                httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError(SECRET_ERROR))
            ),
        ):
            response = client.get("/api/v1/demo/status")

        assert response.status_code == 200
        assert response.json()["status"] == "not_ready"
        assert "hunter2" not in response.text
        assert "internal-db" not in response.text
