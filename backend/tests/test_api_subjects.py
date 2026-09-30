"""
Route-level tests for the /api/v1/subjects endpoints.

Tests cover:
- Listing all subjects (GET /api/v1/subjects)
- Listing subject IDs (GET /api/v1/subjects/ids)
- Getting subject details (GET /api/v1/subjects/{subject_id})
- Getting subject theme configuration (GET /api/v1/subjects/{subject_id}/theme)
- Getting subject books (GET /api/v1/subjects/{subject_id}/books)
"""

from unittest.mock import patch

import pytest

from backend.app.core.subjects import (
    BookSource,
    SubjectConfig,
    SubjectDatabase,
    SubjectPrompts,
    SubjectTheme,
)


def _sample_theme() -> SubjectTheme:
    return SubjectTheme(
        primary_color="#004458",
        secondary_color="#105264",
        accent_color="#10b981",
        chapter_colors={"ch1": "#3b82f6", "ch2": "#8b5cf6"},
    )


def _sample_subjects() -> list[SubjectConfig]:
    return [
        SubjectConfig(
            id="us_history",
            name="US History",
            description="Explore American history.",
            database=SubjectDatabase(
                neo4j_database="neo4j",
                label_prefix="USHistory",
                opensearch_index="us_history_chunks",
            ),
            books=[
                BookSource(
                    title="The American Yawp",
                    source_type="github_raw",
                    repo_url_raw="https://raw.githubusercontent.com/Lockelamora/yawp/master",
                    summary_path="SUMMARY.md",
                    content_path="contents",
                    branch="master",
                ),
            ],
            prompts=SubjectPrompts(
                system_prompt="You are a US History tutor.",
                context_label="Historical Context",
            ),
            theme=_sample_theme(),
            attribution="OpenStax / The American Yawp",
        ),
        SubjectConfig(
            id="biology",
            name="Biology 2e",
            description="Study living systems.",
            database=SubjectDatabase(
                neo4j_database="neo4j",
                label_prefix="Biology",
                opensearch_index="biology_chunks",
            ),
            books=[
                BookSource(
                    title="Biology 2e",
                    source_type="openstax_web",
                    openstax_slug="biology-2e",
                ),
            ],
            prompts=SubjectPrompts(
                system_prompt="You are a Biology tutor.",
                context_label="Biological Context",
            ),
            theme=_sample_theme(),
            attribution="OpenStax Biology 2e",
        ),
    ]


@pytest.mark.unit
class TestListSubjectsEndpoint:
    """Tests for GET /api/v1/subjects."""

    def test_list_subjects_returns_200_and_summaries(self, client):
        sample = _sample_subjects()
        with (
            patch("backend.app.api.routes.subjects.get_all_subjects", return_value=sample),
            patch(
                "backend.app.api.routes.subjects.get_default_subject_id",
                return_value="us_history",
            ),
        ):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        data = response.json()
        assert data["default_subject"] == "us_history"
        assert len(data["subjects"]) == 2
        assert data["subjects"][0] == {
            "id": "us_history",
            "name": "US History",
            "description": "Explore American history.",
            "is_default": True,
        }
        assert data["subjects"][1] == {
            "id": "biology",
            "name": "Biology 2e",
            "description": "Study living systems.",
            "is_default": False,
        }

    def test_list_subjects_returns_500_on_unexpected_error(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_all_subjects",
            side_effect=RuntimeError("config read failure"),
        ):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"


@pytest.mark.unit
class TestListSubjectIdsEndpoint:
    """Tests for GET /api/v1/subjects/ids."""

    def test_list_subject_ids_returns_200(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject_ids",
            return_value=["us_history", "biology", "economics"],
        ):
            response = client.get("/api/v1/subjects/ids")

        assert response.status_code == 200
        assert response.json() == ["us_history", "biology", "economics"]

    def test_list_subject_ids_returns_500_on_unexpected_error(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject_ids",
            side_effect=RuntimeError("registry error"),
        ):
            response = client.get("/api/v1/subjects/ids")

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"


@pytest.mark.unit
class TestGetSubjectDetailEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id}."""

    def test_get_subject_detail_returns_200(self, client):
        subj = _sample_subjects()[0]
        with (
            patch("backend.app.api.routes.subjects.get_subject", return_value=subj),
            patch(
                "backend.app.api.routes.subjects.get_default_subject_id",
                return_value="us_history",
            ),
        ):
            response = client.get("/api/v1/subjects/us_history")

        assert response.status_code == 200
        assert response.json() == {
            "id": "us_history",
            "name": "US History",
            "description": "Explore American history.",
            "attribution": "OpenStax / The American Yawp",
            "opensearch_index": "us_history_chunks",
            "book_count": 1,
            "is_default": True,
        }

    def test_get_subject_detail_returns_404_when_not_found(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=KeyError("Subject 'unknown' not found"),
        ):
            response = client.get("/api/v1/subjects/unknown")

        assert response.status_code == 404
        assert response.json()["detail"] == "Subject not found"

    def test_get_subject_detail_returns_500_on_unexpected_error(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=RuntimeError("unexpected failure"),
        ):
            response = client.get("/api/v1/subjects/us_history")

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"


@pytest.mark.unit
class TestGetSubjectThemeEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id}/theme."""

    def test_get_subject_theme_returns_200(self, client):
        subj = _sample_subjects()[0]
        with patch("backend.app.api.routes.subjects.get_subject", return_value=subj):
            response = client.get("/api/v1/subjects/us_history/theme")

        assert response.status_code == 200
        assert response.json() == {
            "subject_id": "us_history",
            "primary_color": "#004458",
            "secondary_color": "#105264",
            "accent_color": "#10b981",
            "chapter_colors": {"ch1": "#3b82f6", "ch2": "#8b5cf6"},
        }

    def test_get_subject_theme_returns_404_when_not_found(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=KeyError("Subject 'nonexistent' not found"),
        ):
            response = client.get("/api/v1/subjects/nonexistent/theme")

        assert response.status_code == 404
        assert response.json()["detail"] == "Theme not found"

    def test_get_subject_theme_returns_500_on_unexpected_error(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=RuntimeError("theme error"),
        ):
            response = client.get("/api/v1/subjects/us_history/theme")

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"


@pytest.mark.unit
class TestGetSubjectBooksEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id}/books."""

    def test_get_subject_books_github_raw_returns_200(self, client):
        subj = _sample_subjects()[0]
        with patch("backend.app.api.routes.subjects.get_subject", return_value=subj):
            response = client.get("/api/v1/subjects/us_history/books")

        assert response.status_code == 200
        assert response.json() == [
            {
                "title": "The American Yawp",
                "source_type": "github_raw",
                "repo_url_raw": "https://raw.githubusercontent.com/Lockelamora/yawp/master",
                "summary_path": "SUMMARY.md",
                "content_path": "contents",
                "branch": "master",
            }
        ]

    def test_get_subject_books_openstax_web_returns_200(self, client):
        subj = _sample_subjects()[1]
        with patch("backend.app.api.routes.subjects.get_subject", return_value=subj):
            response = client.get("/api/v1/subjects/biology/books")

        assert response.status_code == 200
        assert response.json() == [
            {
                "title": "Biology 2e",
                "source_type": "openstax_web",
                "openstax_slug": "biology-2e",
            }
        ]

    def test_get_subject_books_returns_404_when_not_found(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=KeyError("Subject 'missing' not found"),
        ):
            response = client.get("/api/v1/subjects/missing/books")

        assert response.status_code == 404
        assert response.json()["detail"] == "Books not found for this subject"

    def test_get_subject_books_returns_500_on_unexpected_error(self, client):
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=RuntimeError("books error"),
        ):
            response = client.get("/api/v1/subjects/us_history/books")

        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"
