"""
Validate the latest live KG-RAG eval report for client-demo readiness.

This is intentionally a gate, not a scorer. It rejects missing, malformed, or
non-live reports so a client demo cannot accidentally rely on a 0-case result.

A report passes only if it meets the rules in backend/app/core/eval_report.py, which the
demo status page (/api/v1/demo/status) applies too:
- it carries provenance (schema 2 from scripts/evaluate_rag.py): the server's git SHA, the
  golden-set hash, the LLM and its Ollama digest, the embedding and reranker models with
  their revision fields and devices, the allowlisted retrieval settings and per-subject
  concept and chunk counts;
- it is a full answer run (not --retrieval-only, and not partial unless --allow-partial);
- every request (both modes) returned 200 and no KG expansion failed, recomputed from the
  per-case results rather than trusted from the report's flag.

It must also match the checkout: the server ran the commit the harness ran (an API started
before a commit keeps reporting the old one, even after ``make run-api`` reloads the new
code), and the golden set has not changed since the run.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from backend.app.core.eval_report import as_dict, is_set, report_errors


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON: {e}") from e


def checkout_errors(report: dict[str, Any]) -> list[str]:
    """Whether the server ran the harness's commit, and the golden set is unchanged."""
    errors: list[str] = []
    provenance = as_dict(report.get("provenance"))
    server_sha = as_dict(provenance.get("server")).get("git_sha")
    harness_sha = as_dict(provenance.get("harness")).get("git_sha")
    if not is_set(harness_sha):
        errors.append("harness git_sha missing or unknown (run the harness from a git checkout)")
    elif is_set(server_sha) and server_sha != harness_sha:
        errors.append(
            f"server git_sha {str(server_sha)[:12]} differs from the harness checkout "
            f"{str(harness_sha)[:12]}: restart the API on the evaluated commit and re-run"
        )

    golden_set = as_dict(provenance.get("golden_set"))
    golden_path, golden_sha = golden_set.get("path"), golden_set.get("sha256")
    if is_set(golden_path) and is_set(golden_sha):
        path = Path(str(golden_path))
        if not path.is_file():
            errors.append(f"golden set {golden_path} not found")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != golden_sha:
            errors.append(f"golden set {golden_path} changed since the run (sha256 differs)")
    return errors


def validate_report(
    path: Path, min_successful_cases: int, allow_partial: bool = False
) -> dict[str, Any]:
    """Validate latest eval report and return its summary."""
    report = _load_report(path)
    errors = report_errors(
        report, min_successful_cases=min_successful_cases, allow_partial=allow_partial
    )
    errors.extend(checkout_errors(report))
    if errors:
        raise SystemExit("Eval report is not demo-ready: " + "; ".join(errors))
    return as_dict(report.get("summary"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check latest eval report readiness")
    parser.add_argument("--report", default="docs/evals/latest.json")
    parser.add_argument("--min-successful-cases", type=int, default=1)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Accept a report produced with evaluate_rag.py --subject/--limit",
    )
    args = parser.parse_args()

    summary = validate_report(Path(args.report), args.min_successful_cases, args.allow_partial)
    print("Eval report is demo-ready")
    print(f"  cases: {summary.get('cases')}")
    print(f"  kg_successful_cases: {summary.get('kg_successful_cases')}")
    print(f"  plain_successful_cases: {summary.get('plain_successful_cases')}")
    print(f"  kg_expansion_failures: {summary.get('kg_expansion_failures')}")
    print(f"  citation_hit_rate_delta: {summary.get('citation_hit_rate_delta')}")
    print(f"  mrr_delta: {summary.get('mrr_delta')}")
    print(
        "  kg_prompt_injection_resistance_rate: "
        f"{summary.get('kg_prompt_injection_resistance_rate')}"
    )


if __name__ == "__main__":
    main()
