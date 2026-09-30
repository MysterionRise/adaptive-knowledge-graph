"""
Tests for error redaction and the 422 handler (backend/app/core/exceptions.py).
"""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from backend.app.core.exceptions import (
    public_validation_errors,
    request_validation_exception_handler,
    safe_error_message,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("message", "leaks"),
    [
        pytest.param(
            "Connection refused: bolt://internal-neo4j:7687 (user: admin, password: s3cret)",
            ["bolt://", "internal-neo4j", "7687", "admin", "s3cret"],
            id="bolt-uri-and-credentials",
        ),
        pytest.param(
            "Failed to connect to neo4j+s://prod-db.example.com:7687 auth=(neo4j, hunter2)",
            ["neo4j+s://", "prod-db", "example.com", "hunter2"],
            id="neo4j-uri-and-auth-tuple",
        ),
        pytest.param(
            "could not connect: postgresql://svc:hunter2@db.internal.example.com:5432/app",
            ["postgresql://", "svc", "hunter2", "db.internal", "5432"],
            id="dsn",
        ),
        pytest.param(
            "login neo4j:neo4jpass@graph-host failed", ["neo4jpass", "graph-host"], id="userinfo"
        ),
        pytest.param(
            "Ollama connection failed: http://internal-ollama:11434 API_KEY=sk-live-abc123",
            ["internal-ollama", "11434", "sk-live-abc123"],
            id="http-url-and-api-key",
        ),
        pytest.param(
            "Couldn't connect to localhost:7687 (resolved to ('127.0.0.1:7687',))",
            ["localhost", "127.0.0.1"],
            id="host-port-and-ipv4",
        ),
        pytest.param(
            "upstream [2001:db8::1]:7687 and fe80::1%lo0 unreachable",
            ["2001:db8", "fe80::1"],
            id="ipv6",
        ),
        pytest.param(
            "Name resolution failed for opensearch.internal.example.org",
            ["opensearch.internal", "example.org"],
            id="fqdn",
        ),
        pytest.param(
            "[Errno 2] No such file or directory: '/home/app/data/processed/latest.json'",
            ["/home/app", "latest.json"],
            id="posix-path",
        ),
        pytest.param(r"C:\Users\bob\secrets.txt is missing", ["bob", "secrets.txt"], id="windows"),
        pytest.param(
            'Authorization: Bearer eyJhbGciOi.payload.sig {"password": "abc123"}',
            ["eyJhbGciOi", "abc123"],
            id="bearer-token-and-json-secret",
        ),
        pytest.param("token=abc&secret=def", ["abc", "def"], id="query-string-secrets"),
    ],
)
def test_safe_error_message_redacts(message, leaks):
    safe = safe_error_message(RuntimeError(message))

    for leak in leaks:
        assert leak not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Prefixed secret names (redacted on main; a word-boundary anchor had broken them)
        ("NEO4J_PASSWORD=hunter2", "NEO4J_PASSWORD=[REDACTED]"),
        ("OPENROUTER_API_KEY=abc", "OPENROUTER_API_KEY=[REDACTED]"),
        ("db_password: x", "db_password: [REDACTED]"),
        ("OPENSEARCH_PASSWORD = s3cret", "OPENSEARCH_PASSWORD = [REDACTED]"),
        ("client_secret=abc123", "client_secret=[REDACTED]"),
        ("csrftoken: t0k", "csrftoken: [REDACTED]"),
        # Concatenated names too, e.g. PostgreSQL's standard variable: an anchor such as
        # (?<![A-Za-z0-9]) would leak these
        ("PGPASSWORD=secret", "PGPASSWORD=[REDACTED]"),
        ("dbpassword: secret", "dbpassword: [REDACTED]"),
        # Secrets containing separator characters are redacted up to the next whitespace
        ("password=p;ss,w)rd", "password=[REDACTED]"),
        ("password: s3cret,more", "password: [REDACTED]"),
        ("key_sk-abc123 rejected", "key_[REDACTED] rejected"),
    ],
)
def test_safe_error_message_redacts_prefixed_and_punctuated_secrets(message, expected):
    assert safe_error_message(message) == expected


def test_safe_error_message_keeps_harmless_text():
    assert safe_error_message("All connection attempts failed") == "All connection attempts failed"
    assert safe_error_message(ValueError("Expecting value: line 1 column 1 (char 0)")) == (
        "Expecting value: line 1 column 1 (char 0)"
    )


def test_safe_error_message_is_bounded_and_single_line():
    safe = safe_error_message("line one\nline two\r\n\t" + "x " * 500)

    assert "\n" not in safe and "\r" not in safe and "\t" not in safe
    assert len(safe) <= 160
    assert safe.startswith("line one line two")


def test_safe_error_message_falls_back_when_empty():
    assert safe_error_message(RuntimeError()) == "Service unavailable"
    assert safe_error_message("", fallback="Unavailable") == "Unavailable"


def test_safe_error_message_does_not_split_a_secret_at_the_scan_bound():
    """Only the first 2000 characters are scanned; a token cut by that bound is dropped.

    The long URI collapses to a short placeholder, so without that rule the start of the
    cut IP address ("10.20.3", no longer a full IPv4) would show up in the output.
    """
    message = "http://" + "a" * 1985 + " 10.20.30.40 tail"  # the IP straddles char 2000

    assert safe_error_message(message) == "[REDACTED]"


def test_safe_error_message_handles_pathological_input_quickly():
    for message in ("a." * 500_000, "a" * 1_000_000, "a:" * 500_000):
        assert len(safe_error_message(message)) <= 160


def test_public_validation_errors_keeps_only_loc_msg_type():
    errors = [
        {
            "type": "string_too_long",
            "loc": ("body", "question"),
            "msg": "String should have at most 2000 characters",
            "input": "x" * 1_000_000,
            "ctx": {"max_length": 2000},
            "url": "https://errors.pydantic.dev/2/v/string_too_long",
        },
        {"type": "value_error", "loc": ("body", 0, object()), "msg": "m" * 1000},
    ]

    public = public_validation_errors(errors)

    assert public[0] == {
        "loc": ["body", "question"],
        "msg": "String should have at most 2000 characters",
        "type": "string_too_long",
    }
    assert set(public[1]) == {"loc", "msg", "type"}
    assert public[1]["loc"][:2] == ["body", 0] and isinstance(public[1]["loc"][2], str)
    assert len(public[1]["msg"]) == 200


class _Question(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


def _validation_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

    @app.post("/ask")
    def ask(body: _Question):
        return {"ok": True}

    return app


def test_validation_handler_never_echoes_input():
    """A 1 MB field used to come back in full in the 422 body."""
    payload = "What is " + "x" * 1_000_000 + "?"

    response = TestClient(_validation_app()).post("/ask", json={"question": payload})

    assert response.status_code == 422
    assert len(response.content) < 1000
    assert "xxxxxxxxxx" not in response.text
    detail = response.json()["detail"]
    assert detail == [
        {
            "loc": ["body", "question"],
            "msg": "String should have at most 2000 characters",
            "type": "string_too_long",
        }
    ]


def test_validation_handler_hides_ctx_and_input_for_every_error():
    response = TestClient(_validation_app()).post("/ask", json={"question": "Hi", "extra": 1})

    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


def test_validation_handler_accepts_errors_raised_by_route_code():
    """Routes may raise RequestValidationError themselves (e.g. a markup check)."""
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

    @app.post("/check")
    def check():
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "question"),
                    "msg": "Value error, markup is not allowed",
                    "input": "<script>secret</script>",
                    "ctx": {"error": "markup"},
                },
                "a bare string entry",
            ]
        )

    response = TestClient(app).post("/check")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "loc": ["body", "question"],
            "msg": "Value error, markup is not allowed",
            "type": "value_error",
        },
        {"loc": [], "msg": "a bare string entry", "type": "value_error"},
    ]
    assert "secret" not in response.text
