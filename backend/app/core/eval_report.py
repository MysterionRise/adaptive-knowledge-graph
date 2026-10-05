"""
Validity rules for live evaluation reports (scripts/evaluate_rag.py, schema 2).

One rule set serves the demo gate (scripts/check_demo_eval.py) and the demo status page
(/api/v1/demo/status), so the page never calls a report ready that the gate rejects.

A report is demo-ready only if it:
- carries provenance: the server's git SHA, the golden-set hash, the LLM and its Ollama
  digest, the embedding and reranker models with their revision fields and devices (an
  enabled reranker must have loaded), the allowlisted retrieval settings and per-subject
  concept and chunk counts;
- is a full answer run (not --retrieval-only, and not partial unless allowed);
- shows every request (both modes) returning 200 and zero KG-expansion failures,
  recomputed from the per-case results rather than trusted from the report's flag;
- has at least ``min_successful_cases`` successful KG and plain cases.

This module only reads the report; it imports no settings and opens no connections.
"""

from typing import Any, cast

MIN_SCHEMA_VERSION = 2


def as_dict(value: object) -> dict[str, Any]:
    """``value`` if it is a dict, else an empty dict (reports are untyped JSON)."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def is_set(value: object) -> bool:
    """Whether a provenance value was recorded (not None, empty or "unknown")."""
    return value is not None and str(value).strip() not in ("", "unknown")


def is_partial(report: dict[str, Any]) -> bool:
    """A run limited by --subject/--limit, or one that skipped an unavailable subject."""
    run_config = as_dict(report.get("run_config"))
    return bool(run_config.get("partial") or run_config.get("subjects") or run_config.get("limit"))


def provenance_errors(report: dict[str, Any]) -> list[str]:
    """What the report's provenance block is missing (empty when complete)."""
    errors: list[str] = []
    schema_version = report.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < MIN_SCHEMA_VERSION:
        errors.append(f"schema_version {schema_version!r} < {MIN_SCHEMA_VERSION}")

    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        return [*errors, "no provenance"]

    server = as_dict(provenance.get("server"))
    if not server:
        return [*errors, "no server provenance (/api/v1/demo/provenance)"]
    if not is_set(server.get("git_sha")):
        errors.append("server git_sha missing or unknown (start the API with GIT_SHA set)")

    golden_set = as_dict(provenance.get("golden_set"))
    if not is_set(golden_set.get("sha256")):
        errors.append("golden-set sha256 missing")

    llm = as_dict(provenance.get("llm"))
    if not is_set(llm.get("model")):
        errors.append("LLM model missing")
    if not is_set(llm.get("ollama_digest")):
        errors.append("Ollama model digest missing")

    for name in ("embedding", "reranker"):
        model = as_dict(server.get(name))
        if not is_set(model.get("model")):
            errors.append(f"{name} model missing")
        if "revision" not in model:
            errors.append(f"{name} revision field missing")
        if not is_set(model.get("device")):
            errors.append(f"{name} device missing")
    reranker = as_dict(server.get("reranker"))
    if reranker.get("enabled") and not is_set(reranker.get("resolved_device")):
        # Provenance is read after the cases: an enabled reranker that never loaded means
        # every request fell back to unreranked results.
        errors.append("reranker enabled but not loaded (reranking failed or never ran)")

    if not as_dict(server.get("retrieval")):
        errors.append("retrieval settings missing")

    subjects = server.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        errors.append("per-subject counts missing")
    else:
        evaluated = {r.get("subject") for r in report.get("results") or [] if isinstance(r, dict)}
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
    results = [r for r in report.get("results") or [] if isinstance(r, dict)]
    errors: list[str] = []
    non_200 = sum(
        1
        for r in results
        for mode in ("kg", "plain")
        if as_dict(r.get(mode)).get("status_code") != 200
    )
    if non_200:
        errors.append(f"{non_200} request(s) did not return 200")
    kg_statuses = [as_dict(r.get("kg")).get("kg_expansion_status") for r in results]
    failures = sum(1 for status in kg_statuses if status == "failed")
    if failures:
        errors.append(f"{failures} KG expansion failure(s)")
    if any(status in (None, "disabled") for status in kg_statuses):
        errors.append("KG-mode results without a working KG expansion status")
    return errors


def report_errors(
    report: dict[str, Any], *, min_successful_cases: int = 1, allow_partial: bool = False
) -> list[str]:
    """Why ``report`` is not demo-ready (empty when it is)."""
    errors = provenance_errors(report)
    if as_dict(report.get("run_config")).get("retrieval_only"):
        errors.append("report comes from a retrieval-only run (--retrieval-only)")
    if not allow_partial and is_partial(report):
        errors.append("report comes from a partial run (--subject/--limit/unavailable subject)")
    if not report.get("environment_valid"):
        errors.append("environment_valid is false")
    errors.extend(validity_errors(report))
    summary = as_dict(report.get("summary"))
    for mode in ("kg", "plain"):
        successful = int(summary.get(f"{mode}_successful_cases", 0) or 0)
        if successful < min_successful_cases:
            errors.append(f"{mode}_successful_cases {successful} < {min_successful_cases}")
    return errors
