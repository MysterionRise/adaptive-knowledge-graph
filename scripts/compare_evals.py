"""
Compare two KG-RAG evaluation reports (scripts/evaluate_rag.py) case by case.

Only the case IDs both reports share are compared, and of those only the ones whose golden
definition is unchanged (same case hash): the output lists the others as changed
definitions, outside the gate. It lists metric flips per compared case and mode (citation
hit, expected-source rank, KG expansion status, refusal and prompt-injection results, HTTP
status), new and removed cases, and the paired head-versus-base counts per mode and metric
(wins, ties, losses, discordant pairs and an exact sign test), next to each run's own
KG-versus-plain counts and bootstrap intervals.

When both runs of a flipped case kept retrieval traces (``evaluate_rag.py --trace``), the
flip names the first retrieval stage where the two runs part (``first_divergent_stage``).

When the two reports are repeats (same commit, settings, golden set, split, LLM and seed;
see ``repeat_configuration``), the cases on which they disagree are the noise floor.
--noise-floor FILE records it for the run mode (full or retrieval-only) in FILE, which
scripts/evaluate_rag.py reads (docs/evals/protocol.md).

Exit status 1 (regression) when either report is partial (--subject/--limit or an
unavailable subject) or invalid, when one is a retrieval-only run and the other a full run,
when KG citation hits on the compared cases drop by 2 or more, or when the KG
expected-source MRR on the compared cases drops by 0.03 or more.

Usage:
    poetry run python scripts/compare_evals.py BASE.json HEAD.json
    poetry run python scripts/compare_evals.py BASE.json HEAD.json --out delta.md
    make eval-compare BASE=docs/evals/history/<base>.json HEAD=docs/evals/latest.json
    make eval-noise-floor BASE=<run 1>.json HEAD=<run 2>.json
"""

import argparse
import json
from pathlib import Path
from typing import Any, cast

from backend.app.core.eval_report import (
    as_dict,
    configuration_differences,
    is_partial,
    noise_configuration,
    repeat_configuration,
    run_mode,
)
from backend.app.core.eval_stats import (
    PAIRED_METRICS,
    interval_summary,
    interval_table,
    noise_floor,
    outcome,
    paired_counts,
)
from backend.app.rag.trace import first_divergent_stage

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
    problems: list[str] = []
    if is_partial(report):
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

    # A case whose question or expectations changed is a different case: its flips are not
    # regressions, so it is listed but left out of the flips and the gate.
    changed_definitions = [
        case_id
        for case_id in shared
        if base_cases[case_id].get("case_hash")
        and head_cases[case_id].get("case_hash")
        and base_cases[case_id]["case_hash"] != head_cases[case_id]["case_hash"]
    ]
    compared = [case_id for case_id in shared if case_id not in changed_definitions]

    flips: list[dict[str, Any]] = []
    for case_id in compared:
        base_case, head_case = base_cases[case_id], head_cases[case_id]
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
                            # None unless both runs kept traces (evaluate_rag.py --trace)
                            "stage": first_divergent_stage(
                                base_mode.get("trace"), head_mode.get("trace")
                            ),
                        }
                    )

    # Head versus base, per mode and metric, over the compared cases: wins are head better.
    paired = {
        mode: {
            metric: paired_counts(
                outcome(
                    as_dict(head_cases[case_id].get(mode)).get(metric),
                    as_dict(base_cases[case_id].get(mode)).get(metric),
                )
                for case_id in compared
            )
            for metric in PAIRED_METRICS
        }
        for mode in MODES
    }

    base_hits, base_mrr = _kg_citation_stats(base_cases, compared)
    head_hits, head_mrr = _kg_citation_stats(head_cases, compared)
    hit_drop = base_hits - head_hits
    mrr_drop = (
        round(base_mrr - head_mrr, 4) if base_mrr is not None and head_mrr is not None else None
    )

    failures: list[str] = []
    for side, report in (("base", base), ("head", head)):
        failures.extend(f"{side}: {problem}" for problem in run_problems(report))
    if run_mode(base) != run_mode(head):
        failures.append(
            f"run modes differ (base {run_mode(base)}, head {run_mode(head)}); "
            "compare two runs of the same mode"
        )
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
        "compared_cases": len(compared),
        "new_cases": new,
        "removed_cases": removed,
        "changed_definitions": changed_definitions,
        "flips": flips,
        "retrieval_flips": sum(1 for flip in flips if flip["retrieval"]),
        "kg_citation_hits": {"base": base_hits, "head": head_hits, "drop": hit_drop},
        "kg_mrr": {"base": base_mrr, "head": head_mrr, "drop": mrr_drop},
        "paired": paired,
        "within_run": {
            "base": as_dict(base.get("summary")).get("paired"),
            "head": as_dict(head.get("summary")).get("paired"),
        },
        # Recomputed, so reports written before the intervals existed get them too
        "intervals": {
            "base": interval_summary(base.get("results") or []),
            "head": interval_summary(head.get("results") or []),
        },
        "repeat": {
            "differences": configuration_differences(
                repeat_configuration(base), repeat_configuration(head)
            ),
            "noise_floor": noise_floor(
                [base_cases[case_id] for case_id in compared],
                [head_cases[case_id] for case_id in compared],
            ),
        },
        "failures": failures,
    }


def noise_floor_record(
    base: dict[str, Any], head: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """The noise floor of two repeat runs, as evaluate_rag.py reads it."""
    repeat = result["repeat"]["noise_floor"]
    return {
        "measured_on": str(head.get("generated_at") or "")[:10],
        "runs": [base.get("generated_at"), head.get("generated_at")],
        "server_git_sha": as_dict(as_dict(head.get("provenance")).get("server")).get("git_sha"),
        "split": as_dict(head.get("run_config")).get("split") or "all",
        "cases": result["compared_cases"],
        "configuration": noise_configuration(head),
        "floor": repeat["floor"],
        "modes": repeat["modes"],
    }


def record_noise_floor(path: Path, mode: str, record: dict[str, Any]) -> None:
    """Store ``record`` as the ``mode`` (full or retrieval-only) noise floor in ``path``."""
    records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    records[mode] = record
    path.write_text(json.dumps(dict(sorted(records.items())), indent=2) + "\n", encoding="utf-8")


def _provenance_line(label: str, report: dict[str, Any]) -> str:
    provenance = report.get("provenance") or {}
    server = provenance.get("server") or {}
    golden_set = provenance.get("golden_set") or {}
    llm = provenance.get("llm") or {}
    golden_sha = str(golden_set.get("sha256") or "n/a")[:12]
    return (
        f"- {label}: generated `{report.get('generated_at', 'n/a')}`, {run_mode(report)}, server "
        f"`{server.get('git_sha', 'n/a')}`, golden set `{golden_sha}`, LLM "
        f"`{llm.get('model', 'n/a')}`"
    )


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _paired_sections(result: dict[str, Any]) -> list[str]:
    """Head-versus-base counts per mode and metric, then each run's KG-versus-plain counts."""
    lines = [
        "",
        "## Paired comparison (head versus base, per case)",
        "",
        "| Mode | Metric | Pairs | Head wins | Ties | Base wins | Discordant | Sign test p |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode, metrics in (result.get("paired") or {}).items():
        for metric, counts in metrics.items():
            if not counts.get("pairs"):
                continue
            lines.append(
                f"| {mode} | {metric} | {counts['pairs']} | {counts['wins']} | {counts['ties']} "
                f"| {counts['losses']} | {counts['discordant']} | {_fmt(counts['sign_test_p'])} |"
            )
    within = result.get("within_run") or {}
    if any(within.get(side) for side in ("base", "head")):
        lines.extend(
            [
                "",
                "## KG versus plain within each run (per case)",
                "",
                "| Run | Metric | Pairs | KG wins | Ties | Plain wins | Discordant | Sign test p |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for side in ("base", "head"):
            for metric, counts in as_dict(within.get(side)).items():
                if not counts.get("pairs"):
                    continue
                lines.append(
                    f"| {side} | {metric} | {counts['pairs']} | {counts['wins']} | "
                    f"{counts['ties']} | {counts['losses']} | {counts['discordant']} | "
                    f"{_fmt(counts['sign_test_p'])} |"
                )
    for side in ("base", "head"):
        intervals = as_dict(as_dict(result.get("intervals")).get(side))
        if intervals:
            lines.extend(
                [
                    "",
                    f"## KG minus plain in the {side} run (95% bootstrap intervals)",
                    "",
                    *interval_table(intervals),
                ]
            )
    return lines


def _noise_section(result: dict[str, Any]) -> list[str]:
    """Whether the runs are repeats, and if so how often they disagree."""
    repeat = as_dict(result.get("repeat"))
    differences = repeat.get("differences") or []
    lines = ["", "## Repeat runs", ""]
    if differences:
        lines.append("Not repeats of each other, so no noise floor; they differ in:")
        lines.append("")
        lines.extend(f"- {difference}" for difference in differences)
        return lines
    lines.extend(
        [
            "Repeats of the same configuration: the share of cases whose value changed is the "
            "noise floor (the larger of the two modes).",
            "",
            "| Metric | KG changed | Plain changed | Floor |",
            "| --- | --- | --- | --- |",
        ]
    )
    floor_values = as_dict(as_dict(repeat.get("noise_floor")).get("floor"))
    modes = as_dict(as_dict(repeat.get("noise_floor")).get("modes"))
    for metric, floor in floor_values.items():
        if floor is None:  # neither run scored it (answer metrics in a retrieval-only run)
            continue
        cells = []
        for mode in MODES:
            counts = as_dict(as_dict(modes.get(mode)).get(metric))
            cells.append(f"{counts.get('changed')} of {counts.get('pairs')}")
        lines.append(f"| {metric} | {cells[0]} | {cells[1]} | {_fmt(floor)} |")
    return lines


def format_markdown(base: dict[str, Any], head: dict[str, Any], result: dict[str, Any]) -> str:
    hits, mrr = result["kg_citation_hits"], result["kg_mrr"]
    lines = [
        "# Evaluation comparison",
        "",
        _provenance_line("Base", base),
        _provenance_line("Head", head),
        "",
        f"- Shared cases: {result['shared_cases']} ({result['compared_cases']} compared)",
        f"- KG citation hits: {hits['base']} -> {hits['head']} (drop {hits['drop']})",
        f"- KG MRR: {mrr['base']} -> {mrr['head']} (drop {mrr['drop']})",
        f"- Retrieval flips: {result['retrieval_flips']}; all flips: {len(result['flips'])}",
        f"- New cases: {', '.join(result['new_cases']) or 'none'}",
        f"- Removed cases: {', '.join(result['removed_cases']) or 'none'}",
        "- Changed case definitions (not compared): "
        f"{', '.join(result['changed_definitions']) or 'none'}",
        "",
        "## Result",
        "",
    ]
    if result["failures"]:
        lines.extend(f"- FAIL: {failure}" for failure in result["failures"])
    else:
        lines.append("- PASS")
    lines.extend(_paired_sections(result))
    lines.extend(_noise_section(result))
    if result["flips"]:
        lines.extend(
            [
                "",
                "## Flips",
                "",
                "The first divergent stage needs traces in both runs (`evaluate_rag.py --trace`).",
                "",
                "| Case | Mode | Field | Base | Head | First divergent stage |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for flip in result["flips"]:
            lines.append(
                f"| {flip['id']} | {flip['mode']} | {flip['field']} | "
                f"{flip['base']} | {flip['head']} | {flip.get('stage') or 'n/a'} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two KG-RAG evaluation reports")
    parser.add_argument("base", help="Base report (e.g. a docs/evals/history snapshot)")
    parser.add_argument("head", help="Head report (e.g. docs/evals/latest.json)")
    parser.add_argument("--out", default=None, help="Also write the Markdown comparison here")
    parser.add_argument("--json", action="store_true", help="Print the comparison as JSON")
    parser.add_argument(
        "--noise-floor",
        default=None,
        metavar="FILE",
        help="The reports are repeat runs: record their noise floor for the run mode in FILE "
        "(e.g. docs/evals/noise-floor.json); exit 1 if they are not repeats",
    )
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
    if args.noise_floor:
        problems = [*result["failures"], *result["repeat"]["differences"]]
        if problems:
            print(
                f"No noise floor recorded: the runs are not valid repeats ({len(problems)} problems)"
            )
            return 1
        record_noise_floor(
            Path(args.noise_floor), run_mode(head), noise_floor_record(base, head, result)
        )
        print(f"Recorded the {run_mode(head)} noise floor in {args.noise_floor}")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
