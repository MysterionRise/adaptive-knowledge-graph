"""
Per-route rate limits.

Route limits come from the `rate_limit_*` settings. The suite-wide fixture disables the
limiter, so these tests enable it locally and reset its counters before and after
each test.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from limits import parse

from backend.app.core.rate_limit import limiter
from backend.app.core.settings import settings
from backend.app.main import app
from backend.app.student.models import MasteryUpdateResponse, StudentProfileResponse
from backend.app.ui_payloads.recommendations import RecommendationResponse

ROUTES = "backend.app.api.routes"


@pytest.fixture
def limited_client():
    """Test client with rate limiting enabled and fresh counters."""
    limiter.reset()
    limiter.enabled = True
    try:
        yield TestClient(app)
    finally:
        limiter.enabled = False
        limiter.reset()


def _allowed(setting: str) -> int:
    """Number of requests the configured limit allows per window."""
    return parse(getattr(settings, setting)).amount


def _send_until_limited(send, allowed: int) -> list[int]:
    """Send one more request than the limit allows and return the status codes."""
    return [send().status_code for _ in range(allowed + 1)]


@pytest.mark.unit
class TestRouteLimitsComeFromSettings:
    """Every decorated route uses its `rate_limit_*` setting."""

    @pytest.mark.parametrize(
        ("endpoint", "setting"),
        [
            ("ask.ask_question", "rate_limit_ask"),
            ("ask.ask_question_stream", "rate_limit_ask"),
            ("quiz.generate_quiz", "rate_limit_quiz"),
            ("quiz.generate_adaptive_quiz", "rate_limit_quiz"),
            ("graph.get_graph_stats", "rate_limit_graph"),
            ("graph.get_graph_data", "rate_limit_graph"),
            ("graph.query_graph_natural_language", "rate_limit_graph_query"),
            ("quiz.update_student_mastery", "rate_limit_student_write"),
            ("quiz.reset_student_profile", "rate_limit_student_write"),
            ("quiz.get_quiz_recommendations", "rate_limit_recommendations"),
        ],
    )
    def test_route_limit_matches_setting(self, endpoint, setting):
        route_limits = limiter._route_limits[f"{ROUTES}.{endpoint}"]

        assert [limit.limit for limit in route_limits] == [parse(getattr(settings, setting))]


@pytest.mark.unit
class TestLimitedRoutes:
    """Requests beyond the configured limit get 429."""

    def test_student_mastery_is_rate_limited(self, limited_client):
        service = MagicMock()
        service.update_mastery.return_value = MasteryUpdateResponse(
            concept="Tariffs",
            previous_mastery=0.3,
            new_mastery=0.48,
            target_difficulty="medium",
            total_attempts=1,
            bkt_p_known=0.48,
        )
        allowed = _allowed("rate_limit_student_write")

        with patch(f"{ROUTES}.quiz.get_student_service", return_value=service):
            statuses = _send_until_limited(
                lambda: limited_client.post(
                    "/api/v1/student/mastery", json={"concept": "Tariffs", "correct": True}
                ),
                allowed,
            )

        assert statuses == [200] * allowed + [429]
        assert service.update_mastery.call_count == allowed

    def test_student_reset_is_rate_limited(self, limited_client):
        service = MagicMock()
        service.reset_profile.return_value = StudentProfileResponse(
            student_id="default",
            overall_ability=0.3,
            mastery_levels={},
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        allowed = _allowed("rate_limit_student_write")

        with patch(f"{ROUTES}.quiz.get_student_service", return_value=service):
            statuses = _send_until_limited(
                lambda: limited_client.post("/api/v1/student/reset"), allowed
            )

        assert statuses == [200] * allowed + [429]
        assert service.reset_profile.call_count == allowed

    def test_graph_query_is_rate_limited(self, limited_client, mock_cypher_qa_service):
        allowed = _allowed("rate_limit_graph_query")

        with patch(
            "backend.app.kg.cypher_qa.get_cypher_qa_service",
            return_value=mock_cypher_qa_service,
        ):
            statuses = _send_until_limited(
                lambda: limited_client.post(
                    "/api/v1/graph/query", json={"question": "Which concepts cover tariffs?"}
                ),
                allowed,
            )

        assert statuses == [200] * allowed + [429]
        assert mock_cypher_qa_service.query.call_count == allowed

    def test_quiz_recommendations_are_rate_limited(self, limited_client):
        service = MagicMock()
        service.generate_recommendations = AsyncMock(
            return_value=RecommendationResponse(
                path_type="advancement", score_pct=100.0, summary="Great work."
            )
        )
        payload = {
            "topic": "Tariffs",
            "question_results": [
                {"question_id": "q1", "related_concept": "Tariffs", "correct": True}
            ],
        }
        allowed = _allowed("rate_limit_recommendations")

        with patch(f"{ROUTES}.quiz.get_recommendation_service", return_value=service):
            statuses = _send_until_limited(
                lambda: limited_client.post("/api/v1/quiz/recommendations", json=payload),
                allowed,
            )

        assert statuses == [200] * allowed + [429]
        assert service.generate_recommendations.await_count == allowed

    def test_rate_limited_routes_declare_429(self):
        schema = app.openapi()["paths"]

        for path in (
            "/api/v1/student/mastery",
            "/api/v1/student/reset",
            "/api/v1/graph/query",
            "/api/v1/quiz/recommendations",
        ):
            assert "429" in schema[path]["post"]["responses"]
