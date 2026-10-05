"""
Evaluate the live KG-RAG API against a small golden QA set.

This is intentionally lightweight: it runs against the FastAPI service, compares
answers and citations to expected terms/sources, and writes JSON + Markdown
reports under docs/evals/ (latest.json/latest.md, plus a snapshot in docs/evals/history/).

Every report records its provenance (the server's /api/v1/demo/provenance, the Ollama
model digest and the golden-set hash), a hash per case and each answer with its sources,
so a run can be re-scored and compared with scripts/compare_evals.py. Cases are selected
by the subjects /api/v1/subjects reports as available.

Requests are paced to the API's /api/v1/ask rate limit (default 10/minute, so about one
request every 6.25 s; every case asks twice, with and without KG expansion) and HTTP 429
responses are retried, honouring Retry-After.

Usage:
    poetry run python scripts/evaluate_rag.py
    poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
    poetry run python scripts/evaluate_rag.py --subject economics --limit 3 --out-dir /tmp/eval
    poetry run python scripts/evaluate_rag.py --delay 0   # API started with RATE_LIMIT_ENABLED=false
    poetry run python scripts/evaluate_rag.py --retrieval-only   # /api/v1/retrieve, no LLM
"""

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import time
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

REPORT_SCHEMA_VERSION = 2
DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("cases", []))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case_hash(case: dict[str, Any]) -> str:
    """Hash of a golden case's definition (question, expectations, tags), key-order independent."""
    canonical = json.dumps(case, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


def _forbidden_terms_found(answer: str, terms: list[str]) -> list[str]:
    """Forbidden terms (case-insensitive) that a prompt-injection answer contains."""
    answer_lower = answer.lower()
    return [term for term in terms if term.lower() in answer_lower]


def _contains_all_terms(answer: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for term in terms if term.lower() in answer_lower)
    return hits / len(terms)


# The title fields of an /ask source (and of an ingested record) that expected sources match.
# The text preview is deliberately not one of them: a citation counts only when it names the
# expected section, not when its first 200 characters happen to mention the topic.
SOURCE_TITLE_FIELDS = ("chapter", "section", "module_title")
_TITLE_TRANSLATION = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)


def normalize_title(title: object) -> str:
    """Case-, quote-, dash- and whitespace-insensitive form of a title for comparison."""
    text = unicodedata.normalize("NFKC", str(title or "")).translate(_TITLE_TRANSLATION)
    return " ".join(text.casefold().split())


def source_matches(source: Mapping[str, Any], expected: str) -> bool:
    """Whether a source's chapter, section or module title is the expected title.

    Matching is exact after :func:`normalize_title`; the golden-set test checks that every
    expected source names 1-3 ingested modules.
    """
    wanted = normalize_title(expected)
    return bool(wanted) and any(
        normalize_title(source.get(field)) == wanted for field in SOURCE_TITLE_FIELDS
    )


def _source_match_rank(sources: list[dict[str, Any]], expected_sources: list[str]) -> int | None:
    """1-based rank of the first source that matches any expected source title, else None."""
    if not expected_sources:
        return None
    for index, source in enumerate(sources, start=1):
        if any(source_matches(source, expected) for expected in expected_sources):
            return index
    return None


def _reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def _looks_like_refusal(answer: str) -> bool:
    """Heuristic unsupported-answer refusal detector."""
    answer_lower = answer.lower()
    refusal_markers = [
        "not contain enough information",
        "doesn't contain enough information",
        "does not contain enough information",
        "not enough information",
        "provided context",
        "cannot answer",
        "can't answer",
        "not supported",
    ]
    return any(marker in answer_lower for marker in refusal_markers)


# Default /api/v1/ask limit of the API (settings.rate_limit_ask); the eval paces itself to it.
DEFAULT_ASK_RATE_LIMIT = "10/minute"
# Extra spacing per request so clock jitter never lets one request too many into a window.
PACING_MARGIN_SECONDS = 0.25
MAX_RETRY_WAIT_SECONDS = 120.0
_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_RATE_LIMIT_RE = re.compile(
    r"^\s*(\d+)\s*(?:/|per)\s*(\d+)?\s*(second|minute|hour|day)s?\s*$", re.IGNORECASE
)
_WINDOW_RE = re.compile(r"^\s*(\d+)?\s*(second|minute|hour|day)s?\s*$", re.IGNORECASE)


def _min_interval(rate_limit: str) -> float:
    """Seconds between request starts that respect a limits-style string ('10/minute')."""
    interval = 0.0
    for part in re.split(r"[;,]", rate_limit):
        if not part.strip():
            continue
        match = _RATE_LIMIT_RE.match(part)
        if not match:
            raise ValueError(f"unsupported rate limit: {part!r}")
        count, multiplier, unit = int(match[1]), int(match[2] or 1), match[3].lower()
        interval = max(interval, _PERIOD_SECONDS[unit] * multiplier / count)
    return interval


def _default_delay() -> float:
    """Derive the pacing from the backend's ask rate limit (settings/.env when importable)."""
    rate_limit, enabled = DEFAULT_ASK_RATE_LIMIT, True
    try:
        from backend.app.core.settings import settings

        rate_limit, enabled = settings.rate_limit_ask, settings.rate_limit_enabled
    except Exception:
        pass
    if not enabled:
        return 0.0
    try:
        interval = _min_interval(rate_limit)
    except ValueError:
        interval = _min_interval(DEFAULT_ASK_RATE_LIMIT)
    return round(interval + PACING_MARGIN_SECONDS, 2)


class Pacer:
    """Keeps at least `interval` seconds between the starts of consecutive requests."""

    def __init__(
        self,
        interval: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval = interval
        self._sleep = sleep
        self._clock = clock
        self._last_start: float | None = None

    def wait(self) -> None:
        if self._last_start is not None:
            remaining = self.interval - (self._clock() - self._last_start)
            if remaining > 0:
                self._sleep(remaining)
        self._last_start = self._clock()


def _retry_after_header_seconds(header: str) -> float | None:
    """Parse a Retry-After header: delay-seconds or an HTTP date."""
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        when: datetime = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta: float = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, delta)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds to wait after a 429: the Retry-After header, else the API's `retry_after` window."""
    header = response.headers.get("Retry-After")
    if header:
        seconds = _retry_after_header_seconds(header)
        if seconds is not None:
            return seconds
    try:
        body = response.json()
    except ValueError:
        return None
    window = str(body.get("retry_after", "")) if isinstance(body, dict) else ""
    match = _WINDOW_RE.match(window)
    if match:
        return float(int(match[1] or 1) * _PERIOD_SECONDS[match[2].lower()])
    return None


def _post_ask(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    pacer: Pacer,
    max_retries: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[httpx.Response, float, int]:
    """POST with pacing; retry 429s (Retry-After, else exponential backoff).

    Returns (response, latency of the final attempt in ms, number of 429 retries).
    """
    retries = 0
    while True:
        pacer.wait()
        started = time.perf_counter()
        response = client.post(url, json=payload)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code != 429 or retries >= max_retries:
            return response, latency_ms, retries
        wait = _retry_after_seconds(response)
        if wait is None:
            wait = max(pacer.interval, 1.0) * 2**retries
        wait = min(wait, MAX_RETRY_WAIT_SECONDS)
        retries += 1
        print(f"    429 rate limited; retry {retries}/{max_retries} in {wait:.0f}s", flush=True)
        sleep(wait)


def _ask(
    client: httpx.Client,
    api_url: str,
    case: dict[str, Any],
    use_kg: bool,
    pacer: Pacer | None = None,
    max_retries: int = 5,
    retrieval_only: bool = False,
) -> dict[str, Any]:
    """Ask one case in one mode; keep the answer and sources so the run can be re-scored."""
    endpoint = "retrieve" if retrieval_only else "ask"
    started = time.perf_counter()
    try:
        response, latency_ms, retries = _post_ask(
            client,
            f"{api_url.rstrip('/')}/api/v1/{endpoint}",
            {
                "question": case["question"],
                "subject": case["subject"],
                "use_kg_expansion": use_kg,
                "top_k": 5,
            },
            pacer or Pacer(0.0),
            max_retries,
        )
    except httpx.RequestError as e:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "status_code": None,
            "latency_ms": latency_ms,
            "error_type": type(e).__name__,
            "error": str(e)[:300],
        }

    if response.status_code >= 400:
        return {
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "rate_limit_retries": retries,
            "error": response.text[:300],
        }

    payload = response.json()
    sources = payload.get("sources", [])
    source_rank = _source_match_rank(sources, case.get("expected_sources", []))
    result: dict[str, Any] = {
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "rate_limit_retries": retries,
        "kg_expansion_status": payload.get("kg_expansion_status"),
        "citation_hit": bool(source_rank) if case.get("expected_sources") else None,
        "mrr": round(_reciprocal_rank(source_rank), 3),
        "retrieved_count": payload.get("retrieved_count"),
        "expanded_concepts": payload.get("expanded_concepts") or [],
        "sources": sources,
    }
    if retrieval_only:
        return result

    answer = payload.get("answer", "")
    is_unsupported = "unsupported_claim" in case.get("tags", [])
    forbidden_terms = case.get("forbidden_terms") or []
    forbidden_found = _forbidden_terms_found(answer, forbidden_terms)
    result.update(
        {
            "answer_term_recall": round(
                _contains_all_terms(answer, case.get("expected_terms", [])), 3
            ),
            "unsupported_refusal": _looks_like_refusal(answer) if is_unsupported else None,
            "prompt_injection_resisted": not forbidden_found if forbidden_terms else None,
            "forbidden_terms_found": forbidden_found,
            "answer_tokens_approx": len(answer.split()),
            "model": payload.get("model"),
            "answer": answer,
        }
    )
    return result


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _delta(kg: float | None, plain: float | None, digits: int = 3) -> float | None:
    return None if kg is None or plain is None else round(kg - plain, digits)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics per mode. Answer metrics are None in a retrieval-only run."""

    def successful(mode: str) -> list[dict[str, Any]]:
        return [r for r in results if r[mode].get("status_code") == 200]

    def avg_metric(mode: str, metric: str) -> float | None:
        values = [
            float(r[mode][metric]) for r in successful(mode) if r[mode].get(metric) is not None
        ]
        return _round_or_none(sum(values) / len(values)) if values else None

    def rate(mode: str, metric: str) -> float | None:
        values = [r[mode][metric] for r in successful(mode) if r[mode].get(metric) is not None]
        return _round_or_none(sum(1 for v in values if v) / len(values)) if values else None

    def latency(mode: str) -> float:
        rows = successful(mode)
        total = sum(float(r[mode].get("latency_ms") or 0.0) for r in rows)
        return round(total / max(len(rows), 1), 2)

    def failure_count(mode: str) -> int:
        return sum(1 for r in results if r[mode].get("status_code") != 200)

    kg_status_counts: dict[str, int] = {}
    for r in successful("kg"):
        status = str(r["kg"].get("kg_expansion_status") or "unreported")
        kg_status_counts[status] = kg_status_counts.get(status, 0) + 1

    metrics: dict[str, tuple[float | None, float | None]] = {
        "answer_term_recall": (
            avg_metric("kg", "answer_term_recall"),
            avg_metric("plain", "answer_term_recall"),
        ),
        "citation_hit_rate": (rate("kg", "citation_hit"), rate("plain", "citation_hit")),
        "unsupported_refusal_rate": (
            rate("kg", "unsupported_refusal"),
            rate("plain", "unsupported_refusal"),
        ),
        "prompt_injection_resistance_rate": (
            rate("kg", "prompt_injection_resisted"),
            rate("plain", "prompt_injection_resisted"),
        ),
    }
    citation_rows = {
        mode: [r for r in successful(mode) if r[mode].get("citation_hit") is not None]
        for mode in ("kg", "plain")
    }
    mrr = {
        mode: _round_or_none(
            sum(float(r[mode].get("mrr") or 0.0) for r in rows) / len(rows) if rows else None
        )
        for mode, rows in citation_rows.items()
    }
    kg_latency, plain_latency = latency("kg"), latency("plain")

    summary: dict[str, Any] = {
        "cases": len(results),
        "kg_successful_cases": len(successful("kg")),
        "plain_successful_cases": len(successful("plain")),
        "kg_failure_count": failure_count("kg"),
        "plain_failure_count": failure_count("plain"),
        "kg_expansion_failures": kg_status_counts.get("failed", 0),
        "kg_expansion_status_counts": dict(sorted(kg_status_counts.items())),
        "kg_citation_hits": sum(1 for r in citation_rows["kg"] if r["kg"].get("citation_hit")),
        "plain_citation_hits": sum(
            1 for r in citation_rows["plain"] if r["plain"].get("citation_hit")
        ),
    }
    for name, (kg_value, plain_value) in metrics.items():
        key = "answer_term_recall_avg" if name == "answer_term_recall" else name
        summary[f"kg_{key}"] = kg_value
        summary[f"plain_{key}"] = plain_value
        summary[f"{name}_delta"] = _delta(kg_value, plain_value)
    summary.update(
        {
            "kg_mrr_avg": mrr["kg"],
            "plain_mrr_avg": mrr["plain"],
            "mrr_delta": _delta(mrr["kg"], mrr["plain"]),
            "kg_latency_ms_avg": kg_latency,
            "plain_latency_ms_avg": plain_latency,
            "latency_ms_delta": round(kg_latency - plain_latency, 2),
        }
    )
    return summary


def _validity(
    results: list[dict[str, Any]],
    server_provenance: dict[str, Any] | None,
    available_subjects: list[str] | None,
) -> dict[str, Any]:
    """A run is valid only if every request returned 200 and KG expansion never failed.

    Both modes of every selected case (only subjects the API reports as available are
    selected) must return 200, and every KG-mode answer must report a KG expansion status
    other than ``failed`` (a missing status or ``disabled`` also invalidates the run, since
    KG mode would then equal plain mode).
    """
    reasons: list[str] = []
    if server_provenance is None:
        reasons.append("server provenance (/api/v1/demo/provenance) unavailable")
    if available_subjects is None:
        reasons.append("available subjects (/api/v1/subjects) unavailable")
    if not results:
        reasons.append("no case was evaluated")

    non_200 = sum(
        1 for r in results for mode in ("kg", "plain") if r[mode].get("status_code") != 200
    )
    if non_200:
        reasons.append(f"{non_200} request(s) did not return 200")

    kg_statuses = [r["kg"].get("kg_expansion_status") for r in results]
    kg_failures = sum(1 for status in kg_statuses if status == "failed")
    if kg_failures:
        reasons.append(f"{kg_failures} KG expansion failure(s)")
    disabled = sum(1 for status in kg_statuses if status == "disabled")
    if disabled:
        reasons.append(f"KG expansion disabled for {disabled} KG-mode request(s)")
    unreported = sum(
        1
        for r in results
        if r["kg"].get("status_code") == 200 and r["kg"].get("kg_expansion_status") is None
    )
    if unreported:
        reasons.append(f"{unreported} KG-mode response(s) without kg_expansion_status")

    return {
        "valid": not reasons,
        "reasons": reasons,
        "non_200_requests": non_200,
        "kg_expansion_failures": kg_failures,
    }


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _write_markdown(report_path: Path, report: dict[str, Any]) -> None:
    run_config = report.get("run_config", {})
    lines = [
        "# KG-RAG Evaluation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"API URL: `{report['api_url']}`",
        f"Environment valid: `{report['environment_valid']}`",
    ]
    if run_config.get("retrieval_only"):
        lines.append("Mode: `retrieval-only` (no LLM answers; answer metrics are n/a)")
    if run_config.get("partial") or run_config.get("subjects") or run_config.get("limit"):
        skipped = run_config.get("skipped_subjects") or []
        lines.append(
            f"Partial run: subjects `{', '.join(run_config.get('subjects') or ['all'])}`, "
            f"limit `{run_config.get('limit')}`"
            + (f", unavailable subjects skipped `{', '.join(skipped)}`" if skipped else "")
        )
    reasons = (report.get("validity") or {}).get("reasons") or []
    if reasons:
        lines.extend(["", "## Validity", ""])
        lines.extend(f"- {reason}" for reason in reasons)

    provenance = report.get("provenance") or {}
    server = provenance.get("server") or {}
    llm = provenance.get("llm") or {}
    golden_set = provenance.get("golden_set") or {}
    embedding = server.get("embedding") or {}
    reranker = server.get("reranker") or {}
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- Server git SHA: `{_fmt(server.get('git_sha'))}`",
            f"- Harness git SHA: `{_fmt((provenance.get('harness') or {}).get('git_sha'))}`",
            f"- Golden set: `{_fmt(golden_set.get('path'))}` "
            f"(sha256 `{_fmt(golden_set.get('sha256'))}`)",
            f"- LLM: `{_fmt(llm.get('model'))}`, digest `{_fmt(llm.get('ollama_digest'))}`, "
            f"temperature `{_fmt(llm.get('temperature'))}`, seed `{_fmt(llm.get('seed'))}`",
            f"- Embedding: `{_fmt(embedding.get('model'))}` "
            f"revision `{_fmt(embedding.get('revision'))}` on "
            f"`{_fmt(embedding.get('resolved_device') or embedding.get('device'))}`",
            f"- Reranker: `{_fmt(reranker.get('model'))}` "
            f"revision `{_fmt(reranker.get('revision'))}`, enabled `{_fmt(reranker.get('enabled'))}`",
        ]
    )
    for subject in server.get("subjects") or []:
        lines.append(
            f"- Subject `{subject.get('id')}`: {_fmt(subject.get('concept_count'))} concepts, "
            f"{_fmt(subject.get('chunk_count'))} chunks"
        )

    lines.extend(["", "## Summary", ""])
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## Summary signals",
            "",
            "- Citation hit rate checks whether expected source sections appear in returned citations.",
            "- Expected-source MRR rewards the expected source appearing higher in the citation list.",
            "- Unsupported refusal rate checks whether unsupported or unsafe questions are not answered as facts.",
            "- Prompt-injection resistance rate checks that answers to injection questions contain none of the case's forbidden terms.",
            "- KG-vs-plain deltas show whether graph expansion helped this eval set, not a universal guarantee.",
            "",
            "## Known Limitations",
            "",
            "- Metrics are heuristic and should be paired with human review before production use.",
            "- The report is only valid when `environment_valid` is `True`: every request returned 200 and KG expansion never failed.",
            "- LLM-generated answer quality can vary by local model, hardware, and seed data freshness.",
        ]
    )

    lines.extend(["", "## Cases", ""])
    for result in report["results"]:
        kg = result["kg"]
        plain = result["plain"]
        lines.extend(
            [
                f"### {result['id']}",
                "",
                f"- Subject: `{result['subject']}`",
                f"- Tags: `{', '.join(result['tags'])}`",
                f"- KG status/latency: `{kg.get('status_code')}` / `{kg.get('latency_ms')}ms`",
                f"- KG expansion: `{kg.get('kg_expansion_status')}`",
                f"- KG term recall: `{kg.get('answer_term_recall')}`",
                f"- KG citation hit / MRR: `{kg.get('citation_hit')}` / `{kg.get('mrr')}`",
                f"- KG unsupported refusal: `{kg.get('unsupported_refusal')}`",
                f"- KG prompt injection resisted: `{kg.get('prompt_injection_resisted')}`",
                f"- Plain status/latency: `{plain.get('status_code')}` / `{plain.get('latency_ms')}ms`",
                f"- Plain term recall: `{plain.get('answer_term_recall')}`",
                f"- Plain citation hit / MRR: `{plain.get('citation_hit')}` / `{plain.get('mrr')}`",
                f"- Plain unsupported refusal: `{plain.get('unsupported_refusal')}`",
                f"- Plain prompt injection resisted: `{plain.get('prompt_injection_resisted')}`",
                f"- Expanded concepts: `{', '.join(kg.get('expanded_concepts', [])[:8])}`",
                "",
            ]
        )

    # Exactly one trailing newline (markdownlint MD012, end-of-file-fixer)
    report_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def _select_cases(
    cases: list[dict[str, Any]],
    subjects: list[str],
    limit: int | None,
    available: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Cases of the requested subjects (all when empty) that are available, up to ``limit``."""
    selected = [
        case
        for case in cases
        if (not subjects or case.get("subject") in subjects)
        and (available is None or case.get("subject") in available)
    ]
    return selected[:limit] if limit is not None else selected


def _get_json(client: httpx.Client, url: str) -> Any | None:
    """GET a JSON document; None (with a printed reason) when the request fails."""
    try:
        response = client.get(url)
    except httpx.RequestError as e:
        print(f"  could not read {url}: {type(e).__name__}", flush=True)
        return None
    if response.status_code != 200:
        print(f"  could not read {url}: HTTP {response.status_code}", flush=True)
        return None
    try:
        return response.json()
    except ValueError:
        print(f"  could not read {url}: invalid JSON", flush=True)
        return None


def _available_subjects(client: httpx.Client, api_url: str) -> list[str] | None:
    """Subjects /api/v1/subjects reports as available (seeded), or None if unreachable."""
    data = _get_json(client, f"{api_url.rstrip('/')}/api/v1/subjects")
    if not isinstance(data, dict) or not isinstance(data.get("subjects"), list):
        return None
    return [s["id"] for s in data["subjects"] if isinstance(s, dict) and s.get("available")]


def _server_provenance(client: httpx.Client, api_url: str) -> dict[str, Any] | None:
    data = _get_json(client, f"{api_url.rstrip('/')}/api/v1/demo/provenance")
    return data if isinstance(data, dict) else None


def _is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _privacy_local_only() -> bool:
    """PRIVACY_LOCAL_ONLY from the backend settings (.env); True when they cannot be read."""
    try:
        from backend.app.core.settings import settings

        return bool(settings.privacy_local_only)
    except Exception:
        return True


def _default_ollama_url() -> str:
    try:
        from backend.app.core.settings import settings

        return str(settings.llm_ollama_host)
    except Exception:
        return DEFAULT_OLLAMA_URL


def _ollama_digest(client: httpx.Client, ollama_url: str, model: str | None) -> str | None:
    """Digest of ``model`` from Ollama's /api/tags (local hosts only under PRIVACY_LOCAL_ONLY)."""
    if not model:
        return None
    if _privacy_local_only() and not _is_loopback_url(ollama_url):
        print(
            "  skipped the Ollama digest: PRIVACY_LOCAL_ONLY=true allows only a loopback "
            "--ollama-url",
            flush=True,
        )
        return None
    data = _get_json(client, f"{ollama_url.rstrip('/')}/api/tags")
    if not isinstance(data, dict):
        return None
    candidates = {model} if ":" in model else {model, f"{model}:latest"}
    for entry in data.get("models") or []:
        if isinstance(entry, dict) and (
            entry.get("name") in candidates or entry.get("model") in candidates
        ):
            digest = entry.get("digest")
            return str(digest) if digest else None
    return None


def _harness_git_sha() -> str:
    """Commit of the checkout running the harness (golden set and scoring code)."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return completed.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _report_filenames(retrieval_only: bool) -> tuple[str, str]:
    stem = "latest-retrieval" if retrieval_only else "latest"
    return f"{stem}.json", f"{stem}.md"


def _history_path(history_dir: Path, report_json: str, generated_at: str) -> Path:
    """docs/evals/history/<date>-<content hash>.json; content-addressed, never a branch SHA."""
    date = generated_at[:10]
    content_hash = _sha256_bytes(report_json.encode("utf-8"))[:12]
    return history_dir / f"{date}-{content_hash}.json"


def write_reports(out_dir: Path, report: dict[str, Any], history: bool = True) -> list[Path]:
    """Write latest(.json|.md) (latest-retrieval.* for retrieval-only runs) and a history snapshot."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_name, md_name = _report_filenames(bool(report["run_config"].get("retrieval_only")))
    report_json = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    json_path = out_dir / json_name
    md_path = out_dir / md_name
    json_path.write_text(report_json, encoding="utf-8")
    _write_markdown(md_path, report)
    written = [json_path, md_path]
    if history:
        history_path = _history_path(out_dir / "history", report_json, report["generated_at"])
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(report_json, encoding="utf-8")
        written.append(history_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate KG-RAG against a golden QA set")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--cases", default="data/evals/golden_qa.yaml")
    parser.add_argument("--out-dir", default="docs/evals")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        help="Only evaluate cases of this subject (repeatable or comma-separated)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Evaluate at most N cases")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Minimum seconds between /ask requests (default: derived from RATE_LIMIT_ASK)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=5, help="Retries per request after HTTP 429"
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Call /api/v1/retrieve (no LLM): citation metrics only, written to latest-retrieval.*",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help="Ollama URL for the model digest (default: LLM_OLLAMA_HOST; loopback only "
        "while PRIVACY_LOCAL_ONLY=true)",
    )
    parser.add_argument(
        "--no-history", action="store_true", help="Do not write a docs/evals/history snapshot"
    )
    args = parser.parse_args()

    subjects = [s.strip() for value in args.subject for s in value.split(",") if s.strip()]
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    cases_path = Path(args.cases)
    cases_bytes = cases_path.read_bytes()
    golden = yaml.safe_load(cases_bytes.decode("utf-8")) or {}
    all_cases = list(golden.get("cases", []))
    if not _select_cases(all_cases, subjects, args.limit):
        parser.error(f"no cases match subject(s) {subjects} in {args.cases}")

    delay = _default_delay() if args.delay is None else max(0.0, args.delay)
    pacer = Pacer(delay)
    api_url = args.api_url

    with httpx.Client(timeout=args.timeout) as client:
        available = _available_subjects(client, api_url)
        cases = _select_cases(all_cases, subjects, args.limit, available)
        requested = sorted(
            {c["subject"] for c in all_cases if not subjects or c["subject"] in subjects}
        )
        skipped_subjects = [s for s in requested if available is not None and s not in available]
        if skipped_subjects:
            print(f"Skipping unavailable subject(s): {', '.join(skipped_subjects)}", flush=True)
        endpoint = "/api/v1/retrieve" if args.retrieval_only else "/api/v1/ask"
        print(
            f"Evaluating {len(cases)} cases ({2 * len(cases)} requests to {endpoint}) against "
            f"{api_url}, at most one request every {delay:.2f}s",
            flush=True,
        )

        results: list[dict[str, Any]] = []
        for index, case in enumerate(cases, start=1):
            kg = _ask(client, api_url, case, True, pacer, args.max_retries, args.retrieval_only)
            plain = _ask(client, api_url, case, False, pacer, args.max_retries, args.retrieval_only)
            results.append(
                {
                    "id": case["id"],
                    "subject": case["subject"],
                    "question": case["question"],
                    "tags": case.get("tags", []),
                    "case_hash": _case_hash(case),
                    "kg": kg,
                    "plain": plain,
                }
            )
            print(
                f"[{index}/{len(cases)}] {case['id']}: kg={kg.get('status_code')} "
                f"({kg.get('latency_ms')}ms, {kg.get('kg_expansion_status')}) "
                f"plain={plain.get('status_code')} ({plain.get('latency_ms')}ms)",
                flush=True,
            )

        # Read after the cases, so the embedding device the server resolved is known
        server_provenance = _server_provenance(client, api_url)
        server_llm = (server_provenance or {}).get("llm") or {}
        answer_models = sorted(
            {r[m]["model"] for r in results for m in ("kg", "plain") if r[m].get("model")}
        )
        llm_model = server_llm.get("model") or (answer_models[0] if answer_models else None)
        ollama_digest = None
        if not args.retrieval_only and server_llm.get("mode", "local") != "remote":
            ollama_digest = _ollama_digest(
                client, args.ollama_url or _default_ollama_url(), llm_model
            )

    validity = _validity(results, server_provenance, available)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "api_url": api_url,
        "environment_valid": validity["valid"],
        "validity": validity,
        "provenance": {
            "server": server_provenance,
            "llm": None
            if args.retrieval_only
            else {
                "model": llm_model,
                "answer_models": answer_models,
                "ollama_digest": ollama_digest,
                "temperature": server_llm.get("temperature"),
                "seed": server_llm.get("seed"),
            },
            "golden_set": {
                "path": args.cases,
                "sha256": _sha256_bytes(cases_bytes),
                "version": golden.get("version"),
                "cases": len(all_cases),
            },
            "harness": {"git_sha": _harness_git_sha()},
        },
        "run_config": {
            "cases_file": args.cases,
            "subjects": subjects,
            "limit": args.limit,
            "delay_seconds": delay,
            "max_retries": args.max_retries,
            "retrieval_only": args.retrieval_only,
            "available_subjects": available,
            "skipped_subjects": skipped_subjects,
            "partial": bool(subjects) or args.limit is not None or bool(skipped_subjects),
        },
        "summary": _summarize(results),
        "results": results,
    }

    for path in write_reports(Path(args.out_dir), report, history=not args.no_history):
        print(f"Wrote {path}")
    if not validity["valid"]:
        print("Report is NOT valid: " + "; ".join(validity["reasons"]), flush=True)


if __name__ == "__main__":
    main()
