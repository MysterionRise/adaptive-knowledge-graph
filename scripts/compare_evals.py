"""
Compare two KG-RAG evaluation reports (scripts/evaluate_rag.py) case by case.

Only the case IDs both reports share are compared. The output lists metric flips per case
and mode (citation hit, expected-source rank, KG expansion status, refusal and
prompt-injection results, HTTP status), new and removed cases, and cases whose golden
definition changed (different case hash).

Exit status 1 (regression) when either report is partial (--subject/--limit or an
unavailable subject) or invalid, when KG citation hits on the shared cases drop by 2 or
more, or when the KG expected-source MRR on the shared cases drops by 0.03 or more.

Usage:
    poetry run python scripts/compare_evals.py BASE.json HEAD.json
    poetry run python scripts/compare_evals.py BASE.json HEAD.json --out delta.md
    make eval-compare BASE=docs/evals/history/<base>.json HEAD=docs/evals/latest.json
"""

import argparse
import json
from pathlib import Path
from typing import Any, cast

KG_CITATION_HIT_DROP_LIMIT = 2
KG_MRR_DROP_LIMIT = 0.03

# Per-mode fields compared for flips; the first two are retrieval flips.
RETRIEVAL_FIELDS = ("citation_hit", "mrr")
FLIP_FIELDS = (
    *RETRIEVAL_FIELDS,
    "kg_expansion_status",
    "unsupported_refusal",
    "prompt_injection_resisted",
    "status_code",
)
MODES = ("kg", "plain")


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON in {path}: {e}") from e


def run_problems(report: dict[str, Any]) -> list[str]:
    """Why a report cannot serve as one side of a comparison (partial or invalid run)."""
    run_config = report.get("run_config") or {}
    problems: list[str] = []
    if run_config.get("partial") or run_config.get("subjects") or run_config.get("limit"):
        problems.append("partial run")
    if not report.get("environment_valid"):
        problems.append("invalid run (environment_valid is false)")
    return problems


def _cases(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in report.get("results") or [] if "id" in r}


def _kg_citation_stats(
    cases: dict[str, dict[str, Any]], ids: list[str]
) -> tuple[int, float | None]:
    """KG citation hits and mean KG MRR over the given cases with expected sources."""
    hits = 0
    mrr_values: list[float] = []
    for case_id in ids:
        kg = cases[case_id].get("kg") or {}
        if kg.get("citation_hit") is None:
            continue
        hits += 1 if kg.get("citation_hit") else 0
        mrr_values.append(float(kg.get("mrr") or 0.0))
    mrr = round(sum(mrr_values) / len(mrr_values), 4) if mrr_values else None
    return hits, mrr


def compare(base: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    """Compare two reports; ``failures`` lists the reasons for a non-zero exit."""
    base_cases, head_cases = _cases(base), _cases(head)
    shared = sorted(base_cases.keys() & head_cases.keys())
    new = sorted(head_cases.keys() - base_cases.keys())
    removed = sorted(base_cases.keys() - head_cases.keys())

    flips: list[dict[str, Any]] = []
    changed_definitions: list[str] = []
    for case_id in shared:
        base_case, head_case = base_cases[case_id], head_cases[case_id]
        if (
            base_case.get("case_hash")
            and head_case.get("case_hash")
            and base_case["case_hash"] != head_case["case_hash"]
        ):
            changed_definitions.append(case_id)
        for mode in MODES:
            base_mode, head_mode = base_case.get(mode) or {}, head_case.get(mode) or {}
            for field in FLIP_FIELDS:
                if field not in base_mode and field not in head_mode:
                    continue
                before, after = base_mode.get(field), head_mode.get(field)
                if before != after:
                    flips.append(
                        {
                            "id": case_id,
                            "mode": mode,
                            "field": field,
                            "base": before,
                            "head": after,
                            "retrieval": field in RETRIEVAL_FIELDS,
                        }
                    )

    base_hits, base_mrr = _kg_citation_stats(base_cases, shared)
    head_hits, head_mrr = _kg_citation_stats(head_cases, shared)
    hit_drop = base_hits - head_hits
    mrr_drop = (
        round(base_mrr - head_mrr, 4) if base_mrr is not None and head_mrr is not None else None
    )

    failures: list[str] = []
    for side, report in (("base", base), ("head", head)):
        failures.extend(f"{side}: {problem}" for problem in run_problems(report))
    if hit_drop >= KG_CITATION_HIT_DROP_LIMIT:
        failures.append(
            f"KG citation hits dropped by {hit_drop} ({base_hits} -> {head_hits}), "
            f"limit {KG_CITATION_HIT_DROP_LIMIT}"
        )
    if mrr_drop is not None and mrr_drop >= KG_MRR_DROP_LIMIT:
        failures.append(
            f"KG MRR dropped by {mrr_drop} ({base_mrr} -> {head_mrr}), limit {KG_MRR_DROP_LIMIT}"
        )

    return {
        "shared_cases": len(shared),
        "new_cases": new,
        "removed_cases": removed,
        "changed_definitions": changed_definitions,
        "flips": flips,
        "retrieval_flips": sum(1 for flip in flips if flip["retrieval"]),
        "kg_citation_hits": {"base": base_hits, "head": head_hits, "drop": hit_drop},
        "kg_mrr": {"base": base_mrr, "head": head_mrr, "drop": mrr_drop},
        "failures": failures,
    }


def _provenance_line(label: str, report: dict[str, Any]) -> str:
    provenance = report.get("provenance") or {}
    server = provenance.get("server") or {}
    golden_set = provenance.get("golden_set") or {}
    llm = provenance.get("llm") or {}
    golden_sha = str(golden_set.get("sha256") or "n/a")[:12]
    mode = "retrieval-only" if (report.get("run_config") or {}).get("retrieval_only") else "full"
    return (
        f"- {label}: generated `{report.get('generated_at', 'n/a')}`, {mode}, server "
        f"`{server.get('git_sha', 'n/a')}`, golden set `{golden_sha}`, LLM "
        f"`{llm.get('model', 'n/a')}`"
    )


def format_markdown(base: dict[str, Any], head: dict[str, Any], result: dict[str, Any]) -> str:
    hits, mrr = result["kg_citation_hits"], result["kg_mrr"]
    lines = [
        "# Evaluation comparison",
        "",
        _provenance_line("Base", base),
        _provenance_line("Head", head),
        "",
        f"- Shared cases: {result['shared_cases']}",
        f"- KG citation hits: {hits['base']} -> {hits['head']} (drop {hits['drop']})",
        f"- KG MRR: {mrr['base']} -> {mrr['head']} (drop {mrr['drop']})",
        f"- Retrieval flips: {result['retrieval_flips']}; all flips: {len(result['flips'])}",
        f"- New cases: {', '.join(result['new_cases']) or 'none'}",
        f"- Removed cases: {', '.join(result['removed_cases']) or 'none'}",
        f"- Changed case definitions: {', '.join(result['changed_definitions']) or 'none'}",
        "",
        "## Result",
        "",
    ]
    if result["failures"]:
        lines.extend(f"- FAIL: {failure}" for failure in result["failures"])
    else:
        lines.append("- PASS")
    if result["flips"]:
        lines.extend(["", "## Flips", "", "| Case | Mode | Field | Base | Head |"])
        lines.append("| --- | --- | --- | --- | --- |")
        for flip in result["flips"]:
            lines.append(
                f"| {flip['id']} | {flip['mode']} | {flip['field']} | "
                f"{flip['base']} | {flip['head']} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two KG-RAG evaluation reports")
    parser.add_argument("base", help="Base report (e.g. a docs/evals/history snapshot)")
    parser.add_argument("head", help="Head report (e.g. docs/evals/latest.json)")
    parser.add_argument("--out", default=None, help="Also write the Markdown comparison here")
    parser.add_argument("--json", action="store_true", help="Print the comparison as JSON")
    args = parser.parse_args(argv)

    base, head = load_report(Path(args.base)), load_report(Path(args.head))
    result = compare(base, head)
    markdown = format_markdown(base, head, result)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(markdown, end="")
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
