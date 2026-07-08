"""Tests for client-demo readiness status endpoints."""

from pathlib import Path

import pytest

from backend.app.api.routes import demo


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
