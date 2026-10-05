"""
Validate the latest live KG-RAG eval report for client-demo readiness.

This is intentionally a gate, not a scorer. It rejects missing, malformed, or
non-live reports so a client demo cannot accidentally rely on a 0-case result.

A report passes only if it:
- carries provenance (schema 2 from scripts/evaluate_rag.py): the server's git SHA, the
  golden-set hash, the LLM and its Ollama digest, the embedding and reranker models with
  their revision fields and devices, the allowlisted retrieval settings and per-subject
  concept and chunk counts;
- is a full answer run (not --retrieval-only, and not partial unless --allow-partial);
- shows every request (both modes) returning 200 and zero KG-expansion failures,
  recomputed from the per-case results rather than trusted from the report's flag.
"""

import argparse
import json
from pathlib import Path
from typing import Any, cast

MIN_SCHEMA_VERSION = 2


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON: {e}") from e


def _as_dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _is_set(value: object) -> bool:
    return value is not None and str(value).strip() not in ("", "unknown")


def provenance_errors(report: dict[str, Any]) -> list[str]:
    """What the report's provenance block is missing (empty when complete)."""
    errors: list[str] = []
    schema_version = report.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < MIN_SCHEMA_VERSION:
        errors.append(f"schema_version {schema_version!r} < {MIN_SCHEMA_VERSION}")

    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        return [*errors, "no provenance"]

    server = _as_dict(provenance.get("server"))
    if not server:
        return [*errors, "no server provenance (/api/v1/demo/provenance)"]
    if not _is_set(server.get("git_sha")):
        errors.append("server git_sha missing or unknown (start the API with GIT_SHA set)")

    golden_set = _as_dict(provenance.get("golden_set"))
    if not _is_set(golden_set.get("sha256")):
        errors.append("golden-set sha256 missing")

    llm = _as_dict(provenance.get("llm"))
    if not _is_set(llm.get("model")):
        errors.append("LLM model missing")
    if not _is_set(llm.get("ollama_digest")):
        errors.append("Ollama model digest missing")

    for name in ("embedding", "reranker"):
        model = _as_dict(server.get(name))
        if not _is_set(model.get("model")):
            errors.append(f"{name} model missing")
        if "revision" not in model:
            errors.append(f"{name} revision field missing")
        if not _is_set(model.get("device")):
            errors.append(f"{name} device missing")

    if not _as_dict(server.get("retrieval")):
        errors.append("retrieval settings missing")

    subjects = server.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        errors.append("per-subject counts missing")
    else:
        evaluated = {r.get("subject") for r in report.get("results") or []}
        counted = {
            s.get("id")
            for s in subjects
            if isinstance(s, dict)
            and s.get("concept_count") is not None
            and s.get("chunk_count") is not None
        }
        missing = sorted(str(s) for s in evaluated - counted)
        if missing:
            errors.append(f"concept/chunk counts missing for subject(s) {', '.join(missing)}")
    return errors


def validity_errors(report: dict[str, Any]) -> list[str]:
    """Every request for an evaluated (available) subject returned 200; no KG failures."""
    results = report.get("results") or []
    errors: list[str] = []
    non_200 = sum(
        1
        for r in results
        for mode in ("kg", "plain")
        if _as_dict(r.get(mode)).get("status_code") != 200
    )
    if non_200:
        errors.append(f"{non_200} request(s) did not return 200")
    kg_statuses = [_as_dict(r.get("kg")).get("kg_expansion_status") for r in results]
    failures = sum(1 for status in kg_statuses if status == "failed")
    if failures:
        errors.append(f"{failures} KG expansion failure(s)")
    if any(status in (None, "disabled") for status in kg_statuses):
        errors.append("KG-mode results without a working KG expansion status")
    return errors


def validate_report(
    path: Path, min_successful_cases: int, allow_partial: bool = False
) -> dict[str, Any]:
    """Validate latest eval report and return its summary."""
    report = _load_report(path)
    summary = report.get("summary", {})
    run_config = report.get("run_config") or {}

    environment_valid = bool(report.get("environment_valid"))
    kg_successful = int(summary.get("kg_successful_cases", 0) or 0)
    plain_successful = int(summary.get("plain_successful_cases", 0) or 0)

    errors = provenance_errors(report)
    if run_config.get("retrieval_only"):
        errors.append("report comes from a retrieval-only run (--retrieval-only)")
    if not allow_partial and (
        run_config.get("partial") or run_config.get("subjects") or run_config.get("limit")
    ):
        errors.append("report comes from a partial run (--subject/--limit/unavailable subject)")
    if not environment_valid:
        errors.append("environment_valid is false")
    errors.extend(validity_errors(report))
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
