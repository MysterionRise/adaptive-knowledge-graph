"""
Evaluate the live KG-RAG API against a small golden QA set.

This is intentionally lightweight: it runs against the FastAPI service, compares
answers and citations to expected terms/sources, and writes JSON + Markdown
reports under docs/evals/.

Usage:
    poetry run python scripts/evaluate_rag.py
    poetry run python scripts/evaluate_rag.py --api-url http://localhost:8000
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml


def _load_cases(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("cases", []))


def _contains_all_terms(answer: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for term in terms if term.lower() in answer_lower)
    return hits / len(terms)


def _source_match_rank(sources: list[dict[str, Any]], expected_sources: list[str]) -> int | None:
    if not expected_sources:
        return None
    expected_lower = [source.lower() for source in expected_sources]
    for index, source in enumerate(sources, start=1):
        haystack = " ".join(
            str(source.get(field) or "") for field in ("module_title", "section", "text")
        ).lower()
        if any(expected in haystack for expected in expected_lower):
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


def _ask(client: httpx.Client, api_url: str, case: dict[str, Any], use_kg: bool) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.post(
            f"{api_url.rstrip('/')}/api/v1/ask",
            json={
                "question": case["question"],
                "subject": case["subject"],
                "use_kg_expansion": use_kg,
                "top_k": 5,
            },
        )
    except httpx.RequestError as e:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "status_code": None,
            "latency_ms": latency_ms,
            "error_type": type(e).__name__,
            "error": str(e)[:300],
        }

    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    if response.status_code >= 400:
        return {
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": response.text[:300],
        }

    payload = response.json()
    answer = payload.get("answer", "")
    sources = payload.get("sources", [])
    source_rank = _source_match_rank(sources, case.get("expected_sources", []))
    is_unsupported = "unsupported_claim" in case.get("tags", [])

    return {
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "answer_term_recall": round(_contains_all_terms(answer, case.get("expected_terms", [])), 3),
        "citation_hit": bool(source_rank) if case.get("expected_sources") else None,
        "mrr": round(_reciprocal_rank(source_rank), 3),
        "unsupported_refusal": _looks_like_refusal(answer) if is_unsupported else None,
        "retrieved_count": payload.get("retrieved_count"),
        "expanded_concepts": payload.get("expanded_concepts") or [],
        "answer_tokens_approx": len(answer.split()),
        "model": payload.get("model"),
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    kg_successful = [r for r in results if r["kg"].get("status_code") == 200]
    plain_successful = [r for r in results if r["plain"].get("status_code") == 200]
    kg_citation_cases = [r for r in kg_successful if r["kg"].get("citation_hit") is not None]
    plain_citation_cases = [
        r for r in plain_successful if r["plain"].get("citation_hit") is not None
    ]
    kg_unsupported_cases = [
        r for r in kg_successful if r["kg"].get("unsupported_refusal") is not None
    ]
    plain_unsupported_cases = [
        r for r in plain_successful if r["plain"].get("unsupported_refusal") is not None
    ]

    def avg_metric(rows: list[dict[str, Any]], mode: str, metric: str) -> float:
        total = sum(float(r[mode].get(metric, 0.0) or 0.0) for r in rows)
        return round(
            total / max(len(rows), 1),
            3,
        )

    def hit_rate(rows: list[dict[str, Any]], mode: str) -> float:
        return round(
            sum(1 for r in rows if r[mode].get("citation_hit")) / max(len(rows), 1),
            3,
        )

    def failure_count(mode: str) -> int:
        return sum(1 for r in results if r[mode].get("status_code") != 200)

    def refusal_rate(rows: list[dict[str, Any]], mode: str) -> float:
        return round(
            sum(1 for r in rows if r[mode].get("unsupported_refusal")) / max(len(rows), 1),
            3,
        )

    kg_recall = avg_metric(kg_successful, "kg", "answer_term_recall")
    plain_recall = avg_metric(plain_successful, "plain", "answer_term_recall")
    kg_mrr = avg_metric(kg_citation_cases, "kg", "mrr")
    plain_mrr = avg_metric(plain_citation_cases, "plain", "mrr")
    kg_hit_rate = hit_rate(kg_citation_cases, "kg")
    plain_hit_rate = hit_rate(plain_citation_cases, "plain")
    kg_refusal_rate = refusal_rate(kg_unsupported_cases, "kg")
    plain_refusal_rate = refusal_rate(plain_unsupported_cases, "plain")
    kg_latency = round(
        sum(r["kg"].get("latency_ms", 0.0) for r in kg_successful) / max(len(kg_successful), 1),
        2,
    )
    plain_latency = round(
        sum(r["plain"].get("latency_ms", 0.0) for r in plain_successful)
        / max(len(plain_successful), 1),
        2,
    )

    return {
        "cases": len(results),
        "kg_successful_cases": len(kg_successful),
        "plain_successful_cases": len(plain_successful),
        "kg_failure_count": failure_count("kg"),
        "plain_failure_count": failure_count("plain"),
        "kg_answer_term_recall_avg": kg_recall,
        "plain_answer_term_recall_avg": plain_recall,
        "answer_term_recall_delta": round(kg_recall - plain_recall, 3),
        "kg_citation_hit_rate": kg_hit_rate,
        "plain_citation_hit_rate": plain_hit_rate,
        "citation_hit_rate_delta": round(kg_hit_rate - plain_hit_rate, 3),
        "kg_unsupported_refusal_rate": kg_refusal_rate,
        "plain_unsupported_refusal_rate": plain_refusal_rate,
        "unsupported_refusal_rate_delta": round(kg_refusal_rate - plain_refusal_rate, 3),
        "kg_mrr_avg": kg_mrr,
        "plain_mrr_avg": plain_mrr,
        "mrr_delta": round(kg_mrr - plain_mrr, 3),
        "kg_latency_ms_avg": kg_latency,
        "plain_latency_ms_avg": plain_latency,
        "latency_ms_delta": round(kg_latency - plain_latency, 2),
    }


def _write_markdown(report_path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# KG-RAG Evaluation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"API URL: `{report['api_url']}`",
        f"Environment valid: `{report['environment_valid']}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## Client-Readable Signals",
            "",
            "- Citation hit rate checks whether expected source sections appear in returned citations.",
            "- Expected-source MRR rewards the expected source appearing higher in the citation list.",
            "- Unsupported refusal rate checks whether unsupported or unsafe questions are not answered as facts.",
            "- KG-vs-plain deltas show whether graph expansion helped this eval set, not a universal guarantee.",
            "",
            "## Known Limitations",
            "",
            "- Metrics are heuristic and should be paired with human review before production use.",
            "- The report is only valid when `environment_valid` is `True` and successful case counts are non-zero.",
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
                f"- KG term recall: `{kg.get('answer_term_recall')}`",
                f"- KG citation hit / MRR: `{kg.get('citation_hit')}` / `{kg.get('mrr')}`",
                f"- KG unsupported refusal: `{kg.get('unsupported_refusal')}`",
                f"- Plain status/latency: `{plain.get('status_code')}` / `{plain.get('latency_ms')}ms`",
                f"- Plain term recall: `{plain.get('answer_term_recall')}`",
                f"- Plain citation hit / MRR: `{plain.get('citation_hit')}` / `{plain.get('mrr')}`",
                f"- Plain unsupported refusal: `{plain.get('unsupported_refusal')}`",
                f"- Expanded concepts: `{', '.join(kg.get('expanded_concepts', [])[:8])}`",
                "",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate KG-RAG against a golden QA set")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--cases", default="data/evals/golden_qa.yaml")
    parser.add_argument("--out-dir", default="docs/evals")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    cases = _load_cases(Path(args.cases))
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout) as client:
        for case in cases:
            results.append(
                {
                    "id": case["id"],
                    "subject": case["subject"],
                    "question": case["question"],
                    "tags": case.get("tags", []),
                    "kg": _ask(client, args.api_url, case, use_kg=True),
                    "plain": _ask(client, args.api_url, case, use_kg=False),
                }
            )

    generated_at = datetime.now(timezone.utc).isoformat()
    summary = _summarize(results)
    report = {
        "generated_at": generated_at,
        "api_url": args.api_url,
        "environment_valid": (
            summary["kg_successful_cases"] > 0 and summary["plain_successful_cases"] > 0
        ),
        "summary": summary,
        "results": results,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    md_path = out_dir / "latest.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown(md_path, report)

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
