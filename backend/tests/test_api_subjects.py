"""
Tests for the /subjects/* endpoints.

Tests cover:
- Subject listing with default marking
- Subject ID listing
- Subject detail retrieval (success + not found)
- Subject theme retrieval (success + not found)
- Subject book listing (success + not found, both source flavors)
"""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestListSubjectsEndpoint:
    """Tests for GET /api/v1/subjects endpoint."""

    def test_list_subjects_success(self, client):
        """Test successful subject listing."""
        response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        data = response.json()

        assert "subjects" in data
        assert "default_subject" in data
        assert len(data["subjects"]) > 0

        for summary in data["subjects"]:
            assert "id" in summary
            assert "name" in summary
            assert "description" in summary
            assert "is_default" in summary

    def test_list_subjects_marks_single_default(self, client):
        """Test that exactly the default subject is flagged."""
        response = client.get("/api/v1/subjects")

        assert response.status_code == 200
        data = response.json()

        flagged = [s for s in data["subjects"] if s["is_default"]]
        assert len(flagged) == 1
        assert flagged[0]["id"] == data["default_subject"]

    def test_list_subjects_error(self, client):
        """Test 500 when listing fails."""
        with patch(
            "backend.app.api.routes.subjects.get_all_subjects",
            side_effect=Exception("DB exploded"),
        ):
            response = client.get("/api/v1/subjects")

        assert response.status_code == 500


@pytest.mark.unit
class TestListSubjectIdsEndpoint:
    """Tests for GET /api/v1/subjects/ids endpoint."""

    def test_list_subject_ids_success(self, client):
        """Test successful subject ID listing."""
        response = client.get("/api/v1/subjects/ids")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) > 0
        assert all(isinstance(item, str) for item in data)

    def test_list_subject_ids_contains_default(self, client):
        """Test the default subject is among the IDs."""
        ids = client.get("/api/v1/subjects/ids").json()
        listing = client.get("/api/v1/subjects").json()

        assert listing["default_subject"] in ids
        assert {s["id"] for s in listing["subjects"]} == set(ids)

    def test_list_subject_ids_error(self, client):
        """Test 500 when ID listing fails."""
        with patch(
            "backend.app.api.routes.subjects.get_subject_ids",
            side_effect=Exception("DB exploded"),
        ):
            response = client.get("/api/v1/subjects/ids")

        assert response.status_code == 500


@pytest.mark.unit
class TestSubjectDetailEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id} endpoint."""

    def test_get_subject_detail_success(self, client):
        """Test successful subject detail retrieval."""
        response = client.get("/api/v1/subjects/us_history")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "us_history"
        assert data["name"]
        assert data["description"]
        assert data["attribution"]
        assert data["opensearch_index"]
        assert isinstance(data["book_count"], int)
        assert data["book_count"] > 0
        assert data["is_default"] is True

    def test_get_subject_detail_non_default(self, client):
        """Test detail for a non-default subject."""
        response = client.get("/api/v1/subjects/biology")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "biology"
        assert data["is_default"] is False

    def test_get_subject_detail_not_found(self, client):
        """Test 404 for an unknown subject."""
        response = client.get("/api/v1/subjects/no_such_subject")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_subject_detail_error(self, client):
        """Test 500 when detail lookup fails."""
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=Exception("DB exploded"),
        ):
            response = client.get("/api/v1/subjects/us_history")

        assert response.status_code == 500


@pytest.mark.unit
class TestSubjectThemeEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id}/theme endpoint."""

    def test_get_subject_theme_success(self, client):
        """Test successful theme retrieval."""
        response = client.get("/api/v1/subjects/us_history/theme")

        assert response.status_code == 200
        data = response.json()

        assert data["subject_id"] == "us_history"
        assert data["primary_color"]
        assert data["secondary_color"]
        assert data["accent_color"]
        assert isinstance(data["chapter_colors"], dict)
        assert len(data["chapter_colors"]) > 0

    def test_get_subject_theme_not_found(self, client):
        """Test 404 for an unknown subject."""
        response = client.get("/api/v1/subjects/no_such_subject/theme")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_subject_theme_error(self, client):
        """Test 500 when theme lookup fails."""
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=Exception("DB exploded"),
        ):
            response = client.get("/api/v1/subjects/us_history/theme")

        assert response.status_code == 500


@pytest.mark.unit
class TestSubjectBooksEndpoint:
    """Tests for GET /api/v1/subjects/{subject_id}/books endpoint."""

    def test_get_subject_books_github_raw(self, client):
        """Test book listing for a github_raw subject."""
        response = client.get("/api/v1/subjects/us_history/books")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) > 0
        for book in data:
            assert book["title"]
            assert book["source_type"] == "github_raw"
            assert book["repo_url_raw"]
            assert book["summary_path"]
            assert book["content_path"]
            assert book["branch"]

    def test_get_subject_books_openstax_web(self, client):
        """Test book listing for an openstax_web subject."""
        response = client.get("/api/v1/subjects/world_history/books")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) > 0
        assert all(book["source_type"] == "openstax_web" for book in data)
        assert all(book["openstax_slug"] for book in data)

    def test_get_subject_books_not_found(self, client):
        """Test 404 for an unknown subject."""
        response = client.get("/api/v1/subjects/no_such_subject/books")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_subject_books_error(self, client):
        """Test 500 when book listing fails."""
        with patch(
            "backend.app.api.routes.subjects.get_subject",
            side_effect=Exception("DB exploded"),
        ):
            response = client.get("/api/v1/subjects/us_history/books")

        assert response.status_code == 500
