"""
Unit tests for backend.app.api.validators.
"""

import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError

from backend.app.api import validators
from backend.app.api.validators import (
    ConceptStr,
    NonBlankStr,
    QuestionStr,
    SearchQueryStr,
    StudentId,
    SubjectId,
    TopicStr,
    contains_markup,
    ensure_no_markup,
    error_responses,
    escape_lucene,
    get_subject_or_404,
    resolve_subject,
)
from backend.app.core.subjects import get_default_subject_id


def _accepts(type_: object, value: str) -> bool:
    try:
        TypeAdapter(type_).validate_python(value)
    except ValidationError:
        return False
    return True


@pytest.mark.unit
class TestConstrainedStrings:
    """Trimming and length limits."""

    @pytest.mark.parametrize(
        ("type_", "max_length"),
        [(NonBlankStr, 2000), (TopicStr, 500), (SearchQueryStr, 500), (ConceptStr, 200)],
    )
    def test_trims_and_rejects_blank(self, type_, max_length):
        adapter = TypeAdapter(type_)

        assert adapter.validate_python("  Tariffs \n") == "Tariffs"
        assert not _accepts(type_, "")
        assert not _accepts(type_, " \t\n ")
        assert _accepts(type_, "x" * max_length)
        assert not _accepts(type_, "x" * (max_length + 1))

    def test_length_is_checked_after_trimming(self):
        assert _accepts(ConceptStr, "   " + "x" * 200 + "   ")

    def test_question_needs_three_characters(self):
        assert not _accepts(QuestionStr, "   Hi   ")
        assert TypeAdapter(QuestionStr).validate_python("  Why?  ") == "Why?"
        assert not _accepts(QuestionStr, "x" * 2001)


@pytest.mark.unit
class TestIdentifiers:
    """Subject and student ID patterns."""

    @pytest.mark.parametrize("value", ["us_history", "biology", "world_history", "a", "a" * 32])
    def test_valid_subject_ids(self, value):
        assert _accepts(SubjectId, value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "US_History",
            "1history",
            "_history",
            "us-history",
            "a" * 33,
            "'; DROP --",
            " biology",
        ],
    )
    def test_invalid_subject_ids(self, value):
        assert not _accepts(SubjectId, value)

    @pytest.mark.parametrize("value", ["default", "learner-1", "Jane.Doe_2", "a" * 64])
    def test_valid_student_ids(self, value):
        assert _accepts(StudentId, value)

    @pytest.mark.parametrize("value", ["", "a b", "../x", "a" * 65, "x;y", "émile", "a@b.c"])
    def test_invalid_student_ids(self, value):
        assert not _accepts(StudentId, value)


@pytest.mark.unit
class TestEscapeLucene:
    """Lucene query escaping for fulltext search."""

    @pytest.mark.parametrize(
        ("raw", "escaped"),
        [
            ("photosynthesis", "photosynthesis"),
            ("*:*", r"\*\:\*"),
            ("photo*", r"photo\*"),
            ("photsynthesis~2", r"photsynthesis\~2"),
            ('name:"x" OR y', r"name\:\"x\" or y"),
            ("C++ (economics)", r"C\+\+ \(economics\)"),
            ("a && b || !c", r"a \&\& b \|\| \!c"),
            ("[a TO z] {x} ^2", r"\[a TO z\] \{x\} \^2"),
            ("path/to\\file", r"path\/to\\file"),
            ("NOT tariffs AND trade", "not tariffs and trade"),
            ("Android ORbit NOTE", "Android ORbit NOTE"),
            ("-tariffs", r"\-tariffs"),
        ],
    )
    def test_escapes_query_syntax(self, raw, escaped):
        assert escape_lucene(raw) == escaped


@pytest.mark.unit
class TestMarkupGuard:
    """HTML/script markup detection and rejection."""

    @pytest.mark.parametrize(
        "text",
        [
            "<script>alert(1)</script>",
            "What is <b>biology</b>?",
            "</p>",
            "<!-- comment -->",
            "<?xml version='1.0'?>",
            "<img src=x onerror=alert(1)>",
        ],
    )
    def test_detects_markup(self, text):
        assert contains_markup(text)

    @pytest.mark.parametrize(
        "text",
        ["Is 3 < 5?", "x < y and y > z", "Population <1000", "What is 2<3?", "a -> b", ""],
    )
    def test_plain_text_is_not_markup(self, text):
        assert not contains_markup(text)

    def test_ensure_no_markup_raises_validation_error_without_input(self):
        with pytest.raises(RequestValidationError) as exc_info:
            ensure_no_markup("<script>alert(1)</script>", field="question")

        [error] = exc_info.value.errors()
        assert error["loc"] == ("body", "question")
        assert error["input"] is None
        assert "<script>" not in str(error)

    def test_ensure_no_markup_accepts_plain_text(self):
        ensure_no_markup("Why is x < y?", field="question")


@pytest.mark.unit
class TestSubjectResolution:
    """Unknown subjects become 404; nothing else is swallowed."""

    def test_known_subject(self):
        assert get_subject_or_404("biology").id == "biology"

    def test_none_resolves_to_default_subject(self):
        assert get_subject_or_404(None).id == get_default_subject_id()

    def test_unknown_subject_is_404(self):
        with pytest.raises(HTTPException) as exc_info:
            get_subject_or_404("no_such_subject")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Subject not found"

    def test_broken_default_subject_is_not_reported_as_404(self):
        with (
            patch.object(validators, "get_subject", side_effect=KeyError("default missing")),
            pytest.raises(KeyError),
        ):
            get_subject_or_404(None)

    def test_other_errors_propagate(self):
        with (
            patch.object(validators, "get_subject", side_effect=FileNotFoundError("subjects")),
            pytest.raises(FileNotFoundError),
        ):
            get_subject_or_404("biology")

    def test_resolve_subject_dependency(self):
        assert resolve_subject(None) is None
        assert resolve_subject("biology") == "biology"
        with pytest.raises(HTTPException) as exc_info:
            resolve_subject("no_such_subject")
        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestErrorResponses:
    """OpenAPI error response declarations."""

    def test_error_responses_use_error_models(self):
        responses = error_responses(404, 429, 502)

        assert set(responses) == {404, 429, 502}
        assert responses[404]["model"] is validators.ErrorResponse
        assert responses[429]["model"] is validators.RateLimitResponse
        assert all(entry["description"] for entry in responses.values())

    def test_unknown_status_code_is_a_programming_error(self):
        with pytest.raises(KeyError):
            error_responses(418)


@pytest.mark.unit
def test_payload_constraints_import_without_api_package():
    """Payload models can be imported before the API package (no import cycle)."""
    code = (
        "import backend.app.student.recommendation_service; "
        "import backend.app.ui_payloads.recommendations"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )

    assert result.returncode == 0, result.stderr[-2000:]
