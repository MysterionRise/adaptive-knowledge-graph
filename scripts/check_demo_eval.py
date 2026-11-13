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
- it is a full answer run (not --retrieval-only, not the rehearsal split, and not partial
  unless --allow-partial);
- every request (both modes) returned 200 and no KG expansion failed, recomputed from the
  per-case results rather than trusted from the report's flag.

It must also match the checkout: the server ran the commit the harness ran (an API started
before a commit keeps reporting the old one, even after ``make run-api`` reloads the new
code), the server's app version is the version in pyproject.toml (an editable install or an
image built before a version bump keeps reporting the old one), and the golden set has not
changed since the run.
"""

import argparse
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, cast

from backend.app.core.eval_report import as_dict, is_set, report_errors

# Read by checkout_errors(), relative to its ``root``.
PYPROJECT = Path("pyproject.toml")


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON: {e}") from e


def pyproject_version(path: Path) -> str | None:
    """``tool.poetry.version`` of a pyproject.toml, or None when it cannot be read."""
    try:
        with path.open("rb") as file:
            version = tomllib.load(file)["tool"]["poetry"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return None
    return version if isinstance(version, str) and version else None


def checkout_errors(report: dict[str, Any], root: Path = Path(".")) -> list[str]:
    """Whether the report belongs to the checkout at ``root``.

    The server ran the harness's commit, the server's app version is the pyproject version,
    and the golden set is unchanged. The recorded commit is not compared with the checkout's
    HEAD: the report is committed after the run, so it can never name its own commit.
    """
    errors: list[str] = []
    provenance = as_dict(report.get("provenance"))
    server = as_dict(provenance.get("server"))
    server_sha = server.get("git_sha")
    harness_sha = as_dict(provenance.get("harness")).get("git_sha")
    if not is_set(harness_sha):
        errors.append("harness git_sha missing or unknown (run the harness from a git checkout)")
    elif is_set(server_sha) and server_sha != harness_sha:
        errors.append(
            f"server git_sha {str(server_sha)[:12]} differs from the harness checkout "
            f"{str(harness_sha)[:12]}: restart the API on the evaluated commit and re-run"
        )

    if server:  # report_errors() already rejects a report without server provenance
        app_version = server.get("app_version")
        project_version = pyproject_version(root / PYPROJECT)
        if project_version is None:
            errors.append(f"no tool.poetry.version in {PYPROJECT}: cannot check the app version")
        elif not is_set(app_version):
            errors.append("server app_version missing")
        elif app_version != project_version:
            errors.append(
                f"server app_version {app_version} differs from the {PYPROJECT.name} version "
                f"{project_version}: run `poetry install` (or rebuild the image), restart the "
                "API and re-run"
            )

    golden_set = as_dict(provenance.get("golden_set"))
    golden_path, golden_sha = golden_set.get("path"), golden_set.get("sha256")
    if is_set(golden_path) and is_set(golden_sha):
        path = root / str(golden_path)
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
    print(
        f"  citation_hit_rate: kg {summary.get('kg_citation_hit_rate')}, "
        f"plain {summary.get('plain_citation_hit_rate')}"
    )
    print(f"  mrr_avg: kg {summary.get('kg_mrr_avg')}, plain {summary.get('plain_mrr_avg')}")
    citation = as_dict(as_dict(summary.get("paired")).get("citation_hit"))
    print(
        f"  citation_hit per case: KG wins {citation.get('wins')}, ties {citation.get('ties')}, "
        f"plain wins {citation.get('losses')} (sign test p {citation.get('sign_test_p')})"
    )
    print(
        "  kg_prompt_injection_resistance_rate: "
        f"{summary.get('kg_prompt_injection_resistance_rate')}"
    )


if __name__ == "__main__":
    main()
