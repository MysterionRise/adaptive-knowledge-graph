"""
Validate the latest live KG-RAG eval report for client-demo readiness.

This is intentionally a gate, not a scorer. It rejects missing, malformed, or
non-live reports so a client demo cannot accidentally rely on a 0-case result.
"""

import argparse
import json
from pathlib import Path
from typing import Any, cast


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON: {e}") from e


def validate_report(path: Path, min_successful_cases: int) -> dict[str, Any]:
    """Validate latest eval report and return its summary."""
    report = _load_report(path)
    summary = report.get("summary", {})

    environment_valid = bool(report.get("environment_valid"))
    kg_successful = int(summary.get("kg_successful_cases", 0) or 0)
    plain_successful = int(summary.get("plain_successful_cases", 0) or 0)

    errors = []
    if not environment_valid:
        errors.append("environment_valid is false")
    if kg_successful < min_successful_cases:
        errors.append(f"kg_successful_cases {kg_successful} < {min_successful_cases}")
    if plain_successful < min_successful_cases:
        errors.append(f"plain_successful_cases {plain_successful} < {min_successful_cases}")

    if errors:
        raise SystemExit("Eval report is not demo-ready: " + "; ".join(errors))

    return cast(dict[str, Any], summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check latest eval report readiness")
    parser.add_argument("--report", default="docs/evals/latest.json")
    parser.add_argument("--min-successful-cases", type=int, default=1)
    args = parser.parse_args()

    summary = validate_report(Path(args.report), args.min_successful_cases)
    print("Eval report is demo-ready")
    print(f"  cases: {summary.get('cases')}")
    print(f"  kg_successful_cases: {summary.get('kg_successful_cases')}")
    print(f"  plain_successful_cases: {summary.get('plain_successful_cases')}")
    print(f"  citation_hit_rate_delta: {summary.get('citation_hit_rate_delta')}")
    print(f"  mrr_delta: {summary.get('mrr_delta')}")


if __name__ == "__main__":
    main()
