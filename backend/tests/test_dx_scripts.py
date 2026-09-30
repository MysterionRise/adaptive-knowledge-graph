"""
Unit tests for the developer-experience scripts (no services needed).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from scripts import build_chunk_windows, check_demo_eval, evaluate_rag, stack_check

# ---------------------------------------------------------------------------
# stack_check: npm engines ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "version_range", "expected"),
    [
        ("v20.18.0", ">=20 <21", True),
        ("v26.3.0", ">=20 <21", False),
        ("v22.12.0", "^22.13.0 || >=24", False),
        ("v22.13.0", "^22.13.0 || >=24", True),
        ("v23.1.0", "^22.13.0 || >=24", False),
        ("v24.0.0", "^22.13.0 || >=24", True),
        ("v26.3.0", "^22.13.0 || >=24", True),
        ("v22.0.0", ">=22", True),
        ("v21.9.9", ">=22", False),
        ("v20.1.0", "20.x", True),
        ("v20.2.0", "~20.1", False),
        ("v18.0.0", "*", True),
        ("v18.9.0", ">18", False),
        ("v18.9.0", "<=18", True),
    ],
)
def test_satisfies_npm_ranges(version, version_range, expected):
    assert stack_check.satisfies(version, version_range) is expected


def test_ollama_check_can_be_skipped(monkeypatch, capsys):
    monkeypatch.setenv("SKIP_OLLAMA_CHECK", "1")
    assert stack_check.main(["ollama"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_ollama_check_reports_unreachable_server(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_OLLAMA_CHECK", raising=False)
    monkeypatch.setattr(
        stack_check,
        "_llm_config",
        lambda: stack_check.LLMConfig("local", "http://127.0.0.1:9", "model:tag"),
    )
    assert stack_check.main(["ollama"]) == 1
    output = capsys.readouterr().out
    assert "not reachable" in output
    assert "SKIP_OLLAMA_CHECK=1" in output


def test_ollama_check_reports_generation_failure(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_OLLAMA_CHECK", raising=False)
    monkeypatch.setattr(
        stack_check,
        "_llm_config",
        lambda: stack_check.LLMConfig("local", "http://ollama:11434", "llama3.1:8b"),
    )

    def fake_http_json(url, payload=None, **kwargs):
        if url.endswith("/api/tags"):
            return 200, {"models": [{"name": "llama3.1:8b"}]}
        assert payload["options"] == {"num_predict": 1}
        return 500, {"error": "llama-server binary not found"}

    monkeypatch.setattr(stack_check, "_http_json", fake_http_json)
    assert stack_check.main(["ollama"]) == 1
    output = capsys.readouterr().out
    assert "cannot generate" in output
    assert "llama-server binary not found" in output
    assert "Reinstall" in output


def test_ollama_check_passes_when_a_token_is_generated(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_OLLAMA_CHECK", raising=False)
    monkeypatch.setattr(
        stack_check,
        "_llm_config",
        lambda: stack_check.LLMConfig("local", "http://ollama:11434", "llama3.1:8b"),
    )
    monkeypatch.setattr(
        stack_check,
        "_http_json",
        lambda url, payload=None, **kwargs: (
            (200, {"models": [{"name": "llama3.1:8b"}]})
            if payload is None
            else (200, {"response": "OK", "done": True})
        ),
    )
    assert stack_check.main(["ollama"]) == 0
    assert "Ollama OK" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# evaluate_rag: pacing, 429 handling, case selection, report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate_limit", "interval"),
    [
        ("10/minute", 6.0),
        ("10 per minute", 6.0),
        ("100/hour", 36.0),
        ("5/second", 0.2),
        ("10/2 minutes", 12.0),
        ("10/minute;100/hour", 36.0),
    ],
)
def test_min_interval(rate_limit, interval):
    assert evaluate_rag._min_interval(rate_limit) == pytest.approx(interval)


def test_default_delay_follows_the_ask_rate_limit(monkeypatch):
    from backend.app.core.settings import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_ask", "10/minute")
    # 10/minute -> one request every 6 s plus a small margin: 106 requests never hit a 429
    assert 6.0 < evaluate_rag._default_delay() <= 7.0
    monkeypatch.setattr(settings, "rate_limit_ask", "not a limit")
    assert 6.0 < evaluate_rag._default_delay() <= 7.0
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    assert evaluate_rag._default_delay() == 0.0


def test_pacer_spaces_request_starts():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    pacer = evaluate_rag.Pacer(6.0, sleep=sleep, clock=lambda: now[0])
    pacer.wait()  # first request: no wait
    now[0] += 2.0  # request took 2 s
    pacer.wait()
    now[0] += 9.0  # slow request: already past the interval
    pacer.wait()
    assert sleeps == [pytest.approx(4.0)]


def test_retry_after_header_and_body():
    assert evaluate_rag._retry_after_seconds(httpx.Response(429, headers={"Retry-After": "7"})) == 7
    body = httpx.Response(429, json={"detail": "Rate limit exceeded", "retry_after": "1 minute"})
    assert evaluate_rag._retry_after_seconds(body) == 60
    assert evaluate_rag._retry_after_seconds(httpx.Response(429, text="busy")) is None


def test_post_ask_retries_429_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json={"answer": "ok"})

    waits: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response, _, retries = evaluate_rag._post_ask(
            client,
            "http://api/api/v1/ask",
            {"question": "q"},
            evaluate_rag.Pacer(0.0),
            max_retries=5,
            sleep=waits.append,
        )
    assert response.status_code == 200
    assert retries == 2
    assert waits == [2.0, 2.0]


def test_post_ask_gives_up_after_max_retries():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        response, _, retries = evaluate_rag._post_ask(
            client,
            "http://api/api/v1/ask",
            {},
            evaluate_rag.Pacer(1.0),
            max_retries=2,
            sleep=lambda s: None,
        )
    assert response.status_code == 429
    assert retries == 2


def test_select_cases_by_subject_and_limit():
    cases = [{"id": str(i), "subject": "economics" if i % 2 else "us_history"} for i in range(6)]
    assert [c["id"] for c in evaluate_rag._select_cases(cases, ["economics"], 2)] == ["1", "3"]
    assert len(evaluate_rag._select_cases(cases, [], None)) == 6


def test_markdown_report_uses_neutral_headings_and_one_trailing_newline(tmp_path):
    report = {
        "generated_at": "2026-09-30T00:00:00+00:00",
        "api_url": "http://localhost:8000",
        "environment_valid": True,
        "run_config": {"subjects": ["economics"], "limit": 1},
        "summary": {"cases": 1},
        "results": [{"id": "c1", "subject": "economics", "tags": ["core"], "kg": {}, "plain": {}}],
    }
    path = tmp_path / "latest.md"
    evaluate_rag._write_markdown(path, report)
    text = path.read_text()
    assert "Client-Readable" not in text
    assert "## Summary signals" in text
    assert "Partial run" in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_check_demo_eval_rejects_partial_runs(tmp_path):
    report = {
        "environment_valid": True,
        "run_config": {"subjects": [], "limit": 3},
        "summary": {"kg_successful_cases": 3, "plain_successful_cases": 3},
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report))
    with pytest.raises(SystemExit, match="partial run"):
        check_demo_eval.validate_report(path, 1)
    assert check_demo_eval.validate_report(path, 1, allow_partial=True)["kg_successful_cases"] == 3


# ---------------------------------------------------------------------------
# build_chunk_windows / build_knowledge_graph / seed_student_profile
# ---------------------------------------------------------------------------


def test_find_mentions_uses_word_boundaries():
    chunks = [
        {"id": "m1_0", "text": "Warren Harding won in 1920."},
        {"id": "m1_1", "text": "The war ended; the WAR economy shrank."},
    ]
    mentions = build_chunk_windows.find_mentions(chunks, {"War", "Harding"})
    assert sorted(mentions) == [("m1_0", "Harding"), ("m1_1", "War")]


def test_chunk_nodes_keep_sequential_links_and_embeddings():
    chunks = [
        {"id": "m1_0", "text": "a", "module_id": "m1", "next_chunk_id": "m1_1"},
        {"id": "m1_1", "text": "b", "module_id": "m1", "previous_chunk_id": "m1_0"},
    ]
    nodes = build_chunk_windows.to_chunk_nodes(chunks, {"m1_1": [0.1, 0.2]})
    assert nodes[0].text_embedding is None
    assert nodes[1].text_embedding == [0.1, 0.2]
    assert nodes[1].previous_chunk_id == "m1_0"


def test_load_chunks_matches_the_indexer(tmp_path):
    jsonl = tmp_path / "books_demo.jsonl"
    records = [
        {"module_id": "m1", "section": "s", "text": "First sentence. " * 80},
        {"module_id": "m2", "section": "s", "text": "Second module. " * 10},
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    chunks, first_chunks = build_chunk_windows.load_chunks(jsonl)
    ids = [c["id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert first_chunks == {"m1": "m1_0", "m2": "m2_0"}
    assert chunks[1]["previous_chunk_id"] == chunks[0]["id"]


def test_build_knowledge_graph_does_not_prompt_without_a_terminal(monkeypatch):
    from scripts import build_knowledge_graph

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("prompted"))
    assert build_knowledge_graph._should_clear("us_history", clear_flag=False) is False
    assert build_knowledge_graph._should_clear("us_history", clear_flag=True) is True


class _TunableBuilder:
    def __init__(self, max_concepts=200, *, cooccurrence_threshold=5, prereq_patterns=False):
        pass


class _PlainBuilder:
    def __init__(self, max_concepts=200):
        pass


def test_builder_options_follow_flags_then_env(monkeypatch):
    from scripts import build_knowledge_graph as bkg

    monkeypatch.setattr(bkg, "KGBuilder", _TunableBuilder)
    monkeypatch.delenv("KG_COOCCURRENCE_THRESHOLD", raising=False)
    monkeypatch.delenv("KG_COOCCURRENCE_THRESHOLD_US_HISTORY", raising=False)
    monkeypatch.delenv("KG_PREREQ_PATTERNS", raising=False)
    assert bkg.builder_options("us_history", None, False) == {}

    monkeypatch.setenv("KG_COOCCURRENCE_THRESHOLD", "4")
    assert bkg.builder_options("economics", None, False) == {"cooccurrence_threshold": 4}
    monkeypatch.setenv("KG_COOCCURRENCE_THRESHOLD_US_HISTORY", "3")
    assert bkg.builder_options("us_history", None, False) == {"cooccurrence_threshold": 3}
    # the flag wins over the environment
    assert bkg.builder_options("us_history", 7, True) == {
        "cooccurrence_threshold": 7,
        "prereq_patterns": True,
    }
    monkeypatch.setenv("KG_COOCCURRENCE_THRESHOLD", "many")
    with pytest.raises(SystemExit, match="must be an integer"):
        bkg.builder_options("economics", None, False)


def test_builder_options_skip_what_the_builder_does_not_support(monkeypatch):
    from scripts import build_knowledge_graph as bkg

    monkeypatch.setattr(bkg, "KGBuilder", _PlainBuilder)
    assert bkg.builder_options("us_history", 3, True) == {}


def test_seed_student_profile_writes_sqlite_only(tmp_path, monkeypatch):
    from scripts import seed_student_profile

    json_out = tmp_path / "profiles.json"
    monkeypatch.setattr(sys, "argv", ["seed", "--output", str(json_out)])
    with pytest.raises(SystemExit):
        seed_student_profile.main()
    assert not json_out.exists()

    db = tmp_path / "profiles.sqlite3"
    monkeypatch.setattr(sys, "argv", ["seed", "--output", str(db)])
    seed_student_profile.main()
    assert db.exists()


# ---------------------------------------------------------------------------
# scripts/lib.sh and the Makefile read host ports from the repository .env
# ---------------------------------------------------------------------------

DOTENV_FIXTURE = (
    "# host ports only in .env\n"
    "NEO4J_BOLT_PORT=17687\n"
    'API_PORT="18000"\n'
    "export OPENSEARCH_PORT=19200   # inline comment\n"
    "FRONTEND_PORT='13000'\r\n"
    "NEO4J_PASSWORD=not-exported-by-lib\n"
    "API_PORT=18001\n"  # the last assignment wins
)
PROBE = (
    '. scripts/lib.sh && printf "%s|%s|%s|%s|%s|%s" "${NEO4J_URI:-}" "${NEO4J_BOLT_PORT:-}" '
    '"${OPENSEARCH_PORT:-}" "${API_PORT:-}" "${FRONTEND_PORT:-}" "${NEO4J_PASSWORD:-unset}"'
)
PORT_KEYS = ["NEO4J_URI", "NEO4J_BOLT_PORT", "NEO4J_HTTP_PORT", "OPENSEARCH_PORT", "API_PORT"]


def _repo_copy(tmp_path: Path, dotenv: str | None) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "lib.sh").write_text(Path("scripts/lib.sh").read_text())
    (tmp_path / "Makefile").write_text(Path("Makefile").read_text())
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    return tmp_path


def _clean_env(**extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in PORT_KEYS + ["FRONTEND_PORT", "OLLAMA_PORT", "NEO4J_PASSWORD"]
    }
    env.update(extra)
    return env


def test_lib_reads_host_ports_from_dotenv(tmp_path):
    root = _repo_copy(tmp_path, DOTENV_FIXTURE)
    out = subprocess.run(
        ["bash", "-c", PROBE], cwd=root, env=_clean_env(), capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    # NEO4J_URI is derived from the .env bolt port; secrets are never read into the shell
    assert out.stdout == "bolt://localhost:17687|17687|19200|18001|13000|unset"


def test_environment_wins_over_dotenv(tmp_path):
    root = _repo_copy(tmp_path, DOTENV_FIXTURE + "NEO4J_URI=bolt://db.example:7687\n")
    env = _clean_env(API_PORT="28000", OPENSEARCH_PORT="29200")
    out = subprocess.run(["bash", "-c", PROBE], cwd=root, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "bolt://db.example:7687|17687|29200|28000|13000|unset"


def test_lib_without_dotenv_keeps_defaults(tmp_path):
    root = _repo_copy(tmp_path, None)
    out = subprocess.run(
        ["bash", "-c", PROBE], cwd=root, env=_clean_env(), capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout == "|||||unset"


def test_makefile_api_port_follows_dotenv(tmp_path):
    root = _repo_copy(tmp_path, DOTENV_FIXTURE)
    env = _clean_env()
    out = subprocess.run(
        ["make", "-n", "run-api"], cwd=root, env=env, capture_output=True, text=True
    )
    assert "--port 18001" in out.stdout, out.stdout + out.stderr
    env["API_PORT"] = "8123"
    out = subprocess.run(
        ["make", "-n", "run-api"], cwd=root, env=env, capture_output=True, text=True
    )
    assert "--port 8123" in out.stdout


def test_legacy_scripts_and_data_are_gone():
    for path in [
        "scripts/ingest_us_history.py",
        "scripts/migrate_to_multisubject.py",
        "scripts/migrate_to_enterprise.py",
        "scripts/fetch_openstax.py",
        "scripts/parse_sections.py",
        "scripts/normalize_book.py",
        "scripts/run_pipeline.sh",
        "scripts/validate_setup.sh",
        "data/processed/knowledge_graph.json",
        "data/processed/books.jsonl",
        "data/processed/student_profiles.json",
    ]:
        assert not Path(path).exists(), path
