"""
Re-score a KG-RAG evaluation report from the answers and sources it stores.

scripts/evaluate_rag.py keeps every case's answer and returned sources, so the scorer can run
again without asking the API: after a scorer change, re-score the snapshots in
docs/evals/history/ to see what the change does to them, and before quoting an old report,
check that the current scorer reproduces its metrics. The re-scored report keeps the run's
provenance and records the re-scoring: when, which checkout, which golden set.

Scoring needs each case's golden definition (expected terms and sources, forbidden terms and
claims, tags), which a report does not store. By default the golden set the report names in
its provenance is read from the checkout. A case whose definition changed since the run (its
case_hash differs) is re-scored against the current definition and listed, because its new
metrics measure something else. A case missing from the golden set cannot be re-scored and
is an error: check out the run's harness commit, or pass --cases.

Usage:
    poetry run python scripts/rescore_eval.py docs/evals/history/<file>.json
    poetry run python scripts/rescore_eval.py REPORT.json --out rescored.json
    poetry run python scripts/rescore_eval.py REPORT.json --check   # exit 1 when a metric changes
    make eval-rescore REPORT=docs/evals/history/<file>.json
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.eval_report import as_dict  # noqa: E402
from scripts.evaluate_rag import (  # noqa: E402
    SCORED_FIELDS,
    _case_hash,
    _harness_git_sha,
    _sha256_bytes,
    _summarize,
    rescore_result,
)

DEFAULT_CASES = "data/evals/golden_qa.yaml"
MODES = ("kg", "plain")
MAX_LISTED_CHANGES = 60


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing eval report: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid eval JSON in {path}: {e}") from e


def load_cases(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """The golden cases by id, and the SHA-256 of the file (as a report's provenance records it)."""
    if not path.is_file():
        raise SystemExit(f"Missing golden set: {path}")
    data = path.read_bytes()
    golden = yaml.safe_load(data.decode("utf-8")) or {}
    cases = {
        str(case["id"]): case
        for case in golden.get("cases") or []
        if isinstance(case, dict) and "id" in case
    }
    return cases, _sha256_bytes(data)


def rescore_report(
    report: dict[str, Any],
    cases: dict[str, dict[str, Any]],
    *,
    cases_path: str,
    cases_sha256: str,
) -> dict[str, Any]:
    """The report with every scored field and the summary recomputed by the current scorer.

    Raises ``SystemExit`` when a case of the report is not in ``cases``.
    """
    retrieval_only = bool(as_dict(report.get("run_config")).get("retrieval_only"))
    provenance = as_dict(report.get("provenance"))
    recorded_sha = as_dict(provenance.get("golden_set")).get("sha256")

    results: list[dict[str, Any]] = []
    changed: list[str] = []
    missing: list[str] = []
    for result in report.get("results") or []:
        case_id = str(result.get("id"))
        case = cases.get(case_id)
        if case is None:
            missing.append(case_id)
            continue
        if result.get("case_hash") and result["case_hash"] != _case_hash(case):
            changed.append(case_id)
        rescored = dict(result)
        for mode in MODES:
            if isinstance(result.get(mode), dict):
                rescored[mode] = rescore_result(case, result[mode], retrieval_only)
        results.append(rescored)
    if missing:
        harness_sha = as_dict(provenance.get("harness")).get("git_sha") or "unknown"
        raise SystemExit(
            f"{len(missing)} case(s) of the report are not in {cases_path}: "
            f"{', '.join(missing)}. Re-score with the golden set of the run (harness commit "
            f"{harness_sha}; `git show {harness_sha}:{DEFAULT_CASES} > /tmp/golden.yaml` and "
            "`--cases /tmp/golden.yaml`)."
        )

    rescored_report = dict(report)
    rescored_report["summary"] = _summarize(results)
    rescored_report["results"] = results
    rescored_report["rescoring"] = {
        "rescored_at": datetime.now(UTC).isoformat(),
        "harness": {"git_sha": _harness_git_sha()},
        "golden_set": {
            "path": cases_path,
            "sha256": cases_sha256,
            "same_as_run": cases_sha256 == recorded_sha,
        },
        "changed_definitions": changed,
        "scored_fields": list(SCORED_FIELDS),
    }
    return rescored_report


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Summary keys and per-case scored fields whose value the re-scoring changed."""
    before_summary, after_summary = as_dict(before.get("summary")), as_dict(after.get("summary"))
    summary = [
        {"key": key, "before": before_summary.get(key), "after": after_summary.get(key)}
        for key in sorted(before_summary.keys() | after_summary.keys())
        if before_summary.get(key) != after_summary.get(key)
    ]
    after_cases = {str(r.get("id")): r for r in after.get("results") or []}
    results: list[dict[str, Any]] = []
    for result in before.get("results") or []:
        rescored = after_cases.get(str(result.get("id")))
        if rescored is None:
            continue
        for mode in MODES:
            old, new = as_dict(result.get(mode)), as_dict(rescored.get(mode))
            for field in SCORED_FIELDS:
                if old.get(field) != new.get(field):
                    results.append(
                        {
                            "id": result.get("id"),
                            "mode": mode,
                            "field": field,
                            "before": old.get(field),
                            "after": new.get(field),
                        }
                    )
    return {"summary": summary, "results": results}


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def format_text(
    report_path: Path, rescored: dict[str, Any], diff: dict[str, list[dict[str, Any]]]
) -> str:
    rescoring = rescored["rescoring"]
    golden_set = rescoring["golden_set"]
    same = "the golden set of the run" if golden_set["same_as_run"] else "a different golden set"
    changed = rescoring["changed_definitions"]
    lines = [
        f"Re-scored {len(rescored.get('results') or [])} case(s) of {report_path} against "
        f"{golden_set['path']} ({same}).",
        "Changed case definitions, re-scored against the current definition: "
        f"{', '.join(changed) or 'none'}",
    ]
    if diff["summary"]:
        lines.append("Summary metrics that changed:")
        lines.extend(
            f"  {row['key']}: {_fmt(row['before'])} -> {_fmt(row['after'])}"
            for row in diff["summary"]
        )
    else:
        lines.append("Summary: every metric reproduced.")
    if diff["results"]:
        lines.append(f"Per-case scored fields that changed: {len(diff['results'])}")
        lines.extend(
            f"  {row['id']} [{row['mode']}] {row['field']}: "
            f"{_fmt(row['before'])} -> {_fmt(row['after'])}"
            for row in diff["results"][:MAX_LISTED_CHANGES]
        )
        if len(diff["results"]) > MAX_LISTED_CHANGES:
            lines.append(f"  ... and {len(diff['results']) - MAX_LISTED_CHANGES} more")
    else:
        lines.append("Per-case scored fields: every value reproduced.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-score an evaluation report from its stored answers and sources"
    )
    parser.add_argument("report", help="Report to re-score (e.g. a docs/evals/history snapshot)")
    parser.add_argument(
        "--cases",
        default=None,
        help="Golden set with the cases' definitions (default: the path the report's "
        f"provenance records, else {DEFAULT_CASES})",
    )
    parser.add_argument("--out", default=None, help="Write the re-scored report here")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when the current scorer does not reproduce every metric of the report",
    )
    parser.add_argument("--json", action="store_true", help="Print the changes as JSON")
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    report = load_report(report_path)
    recorded_path = as_dict(as_dict(report.get("provenance")).get("golden_set")).get("path")
    cases_path = Path(args.cases or str(recorded_path or DEFAULT_CASES))
    cases, cases_sha256 = load_cases(cases_path)
    rescored = rescore_report(report, cases, cases_path=str(cases_path), cases_sha256=cases_sha256)
    diff = changes(report, rescored)

    if args.json:
        print(json.dumps({"rescoring": rescored["rescoring"], **diff}, indent=2))
    else:
        print(format_text(report_path, rescored, diff), end="")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(rescored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Wrote {out_path}")
    if args.check and (diff["summary"] or diff["results"]):
        print("Re-scoring changed the report's metrics (--check).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
