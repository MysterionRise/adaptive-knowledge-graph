"""
Paired statistics for evaluation reports: win/tie/loss counts, an exact sign test, seeded
bootstrap intervals, the protocol's primary endpoint and the noise floor.

Every golden case is asked twice, with and without knowledge-graph expansion, so the case
is the paired unit. A comparison of the two modes is therefore a count of the cases where
one mode did better, the same or worse, not a difference of means: with 49 cases that have
expected sources, a single citation flip moves the hit rate by two points. The same counts
compare two runs of the same cases (scripts/compare_evals.py).

The sign test is exact and two-sided, on the discordant pairs only (ties carry no
information about direction). The bootstrap resamples cases (the paired unit) with a fixed
seed, so a report's intervals are reproducible (#209, docs/evals/protocol.md). Standard
library only.
"""

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Per-mode fields compared pairwise, in report order. Booleans compare as 0/1; higher is
# better for every one of them.
PAIRED_METRICS = (
    "citation_hit",
    "mrr",
    "answer_term_recall",
    "answer_term_recall_non_echo",
    "unsupported_refusal",
    "prompt_injection_resisted",
)
P_VALUE_DECIMALS = 4


def sign_test_p(wins: int, losses: int) -> float | None:
    """Two-sided exact sign test on the discordant pairs; None when there are none.

    Under the null hypothesis a discordant pair is a win or a loss with probability one
    half, so the p-value is twice the binomial tail at the smaller count, capped at 1.
    """
    discordant = wins + losses
    if discordant == 0:
        return None
    smaller = min(wins, losses)
    tail = sum(math.comb(discordant, i) for i in range(smaller + 1)) / 2.0**discordant
    return round(min(1.0, 2 * tail), P_VALUE_DECIMALS)


def outcome(left: Any, right: Any) -> int | None:
    """+1 when ``left`` is better, -1 when ``right`` is, 0 for a tie; None when not comparable.

    A value is comparable when both sides have one (a missing or ``None`` metric, such as a
    failed request or a case the metric does not apply to, makes the pair incomparable).
    """
    if left is None or right is None:
        return None
    left_value, right_value = float(left), float(right)
    if left_value > right_value:
        return 1
    if left_value < right_value:
        return -1
    return 0


def paired_counts(outcomes: Iterable[int | None]) -> dict[str, Any]:
    """Wins, ties, losses, discordant pairs and the sign test over comparable outcomes."""
    wins = ties = losses = 0
    for result in outcomes:
        if result is None:
            continue
        if result > 0:
            wins += 1
        elif result < 0:
            losses += 1
        else:
            ties += 1
    return {
        "pairs": wins + ties + losses,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "discordant": wins + losses,
        "sign_test_p": sign_test_p(wins, losses),
    }


def case_verdict(outcomes: Iterable[int | None]) -> str | None:
    """One verdict for a case over its metrics: win, tie, loss or mixed; None without any."""
    comparable = [result for result in outcomes if result is not None]
    if not comparable:
        return None
    has_win, has_loss = any(r > 0 for r in comparable), any(r < 0 for r in comparable)
    if has_win and has_loss:
        return "mixed"
    if has_win:
        return "win"
    if has_loss:
        return "loss"
    return "tie"


def paired_summary(
    results: Iterable[Mapping[str, Any]], left: str = "kg", right: str = "plain"
) -> dict[str, dict[str, Any]]:
    """Per-metric paired counts of ``left`` versus ``right`` over the cases, plus ``overall``.

    A case is paired only when both modes returned 200; a metric only when both modes have
    it. ``overall`` counts one verdict per case (``case_verdict``), with ``mixed`` cases
    listed separately and left out of the discordant pairs.
    """
    per_metric: dict[str, list[int | None]] = {metric: [] for metric in PAIRED_METRICS}
    verdicts: list[str | None] = []
    for result in results:
        left_mode, right_mode = result.get(left) or {}, result.get(right) or {}
        if left_mode.get("status_code") != 200 or right_mode.get("status_code") != 200:
            continue
        outcomes = [outcome(left_mode.get(m), right_mode.get(m)) for m in PAIRED_METRICS]
        for metric, value in zip(PAIRED_METRICS, outcomes, strict=True):
            per_metric[metric].append(value)
        verdicts.append(case_verdict(outcomes))

    summary: dict[str, dict[str, Any]] = {
        metric: paired_counts(outcomes) for metric, outcomes in per_metric.items()
    }
    counted = [verdict for verdict in verdicts if verdict is not None]
    wins = counted.count("win")
    losses = counted.count("loss")
    summary["overall"] = {
        "pairs": len(counted),
        "wins": wins,
        "ties": counted.count("tie"),
        "losses": losses,
        "mixed": counted.count("mixed"),
        "discordant": wins + losses,
        "sign_test_p": sign_test_p(wins, losses),
    }
    return summary


# Bootstrap intervals, the primary endpoint and the noise floor (#209) ---------------------

# Golden-set strata in protocol order (docs/evals/protocol.md); scripts/split_golden.py
# draws the splits per stratum.
STRATA = ("single_hop", "multi_hop", "meaning", "distribution", "unanswerable", "adversarial")

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 209
CONFIDENCE = 0.95
DECIMALS = 3

# KG-minus-plain differences reported with an interval. MRR counts only the cases with
# expected sources, like the summary's ``kg_mrr_avg``.
INTERVAL_METRICS = ("citation_hit", "mrr", "answer_term_recall_non_echo")

# The primary endpoint: KG minus plain citation hit rate, with a non-inferiority margin.
PRIMARY_METRIC = "citation_hit"
NON_INFERIORITY_MARGIN = -0.10


def bootstrap_interval(
    values: Sequence[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = CONFIDENCE,
) -> tuple[float, float] | None:
    """Percentile interval for the mean of ``values``, resampled with replacement.

    Draws use only ``random.Random.random``, whose sequence Python keeps the same across
    versions for an integer seed, so the interval is reproducible. None without values.
    """
    count = len(values)
    if count == 0:
        return None
    rng = random.Random(seed)  # nosec B311  # seeded resampling for a statistic, not security
    means = sorted(
        sum(values[int(rng.random() * count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    low = means[math.floor(round(resamples * tail, 9))]
    high = means[math.ceil(round(resamples * (1.0 - tail), 9)) - 1]
    return low, high


def _applies(metric: str, left_mode: Mapping[str, Any], right_mode: Mapping[str, Any]) -> bool:
    """Whether a case counts for ``metric``: both modes answered and have a value.

    MRR is 0 for a case without expected sources, so it counts only where the citation
    hit applies.
    """
    if left_mode.get("status_code") != 200 or right_mode.get("status_code") != 200:
        return False
    if metric == "mrr" and (
        left_mode.get("citation_hit") is None or right_mode.get("citation_hit") is None
    ):
        return False
    return left_mode.get(metric) is not None and right_mode.get(metric) is not None


def paired_difference(
    results: Iterable[Mapping[str, Any]], metric: str, left: str = "kg", right: str = "plain"
) -> dict[str, Any] | None:
    """Mean ``left`` and ``right`` values of ``metric``, their difference and its interval.

    The difference is ``left`` minus ``right`` per case; booleans count as 0/1. ``wins``
    and ``losses`` count the cases where ``left`` is higher or lower: when both are 0 the
    interval collapses to [0, 0], which shows that the modes agreed on every case, not that
    the difference is known to be zero. None when no case has the metric in both modes.
    """
    pairs = [
        (float(result[left][metric]), float(result[right][metric]))
        for result in results
        if _applies(metric, result.get(left) or {}, result.get(right) or {})
    ]
    if not pairs:
        return None
    count = len(pairs)
    differences = [a - b for a, b in pairs]
    low, high = bootstrap_interval(differences) or (0.0, 0.0)  # never None: pairs exist
    return {
        "pairs": count,
        left: round(sum(a for a, _ in pairs) / count, DECIMALS),
        right: round(sum(b for _, b in pairs) / count, DECIMALS),
        "difference": round(sum(differences) / count, DECIMALS),
        "ci_low": round(low, DECIMALS),
        "ci_high": round(high, DECIMALS),
        "wins": sum(1 for d in differences if d > 0),
        "losses": sum(1 for d in differences if d < 0),
    }


def interval_summary(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """KG-minus-plain differences with bootstrap intervals, overall and per stratum."""
    rows = list(results)
    labelled = {row.get("stratum") for row in rows}
    strata = [stratum for stratum in STRATA if stratum in labelled]
    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "confidence": CONFIDENCE,
        "overall": {metric: paired_difference(rows, metric) for metric in INTERVAL_METRICS},
        "strata": {
            stratum: {
                metric: paired_difference([r for r in rows if r.get("stratum") == stratum], metric)
                for metric in INTERVAL_METRICS
            }
            for stratum in strata
        },
    }


def _signed(value: float) -> str:
    return f"{value:+.{DECIMALS}f}"


def _interval_cell(estimate: Mapping[str, Any] | None) -> str:
    if not estimate:
        return "n/a"
    return (
        f"{_signed(estimate['difference'])} "
        f"[{_signed(estimate['ci_low'])}, {_signed(estimate['ci_high'])}]"
    )


def interval_table(intervals: Mapping[str, Any]) -> list[str]:
    """Markdown table of an ``interval_summary``, overall then per stratum."""
    lines = [
        "| Cases | With sources | Citation hit, KG / plain | Citation hit Δ [95% CI] "
        "| MRR Δ [95% CI] | Non-echo term recall Δ [95% CI] |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rows = [("all", intervals.get("overall") or {}), *(intervals.get("strata") or {}).items()]
    for label, metrics in rows:
        citation = metrics.get("citation_hit")
        rates = (
            f"{citation['kg']:.{DECIMALS}f} / {citation['plain']:.{DECIMALS}f}"
            if citation
            else "n/a"
        )
        lines.append(
            f"| {label} | {citation['pairs'] if citation else 0} | {rates} | "
            f"{_interval_cell(citation)} | {_interval_cell(metrics.get('mrr'))} | "
            f"{_interval_cell(metrics.get('answer_term_recall_non_echo'))} |"
        )
    return lines


def primary_endpoint(
    results: Iterable[Mapping[str, Any]], noise_floor: float | None = None
) -> dict[str, Any] | None:
    """The protocol's primary endpoint, with the claim its numbers allow.

    KG minus plain citation hit rate over the final-split cases with expected sources. A
    run without final-split cases gets the same estimate over its own cases, labelled as
    such (a rehearsal estimate is not release evidence).

    The verdict: ``kg_better`` when the interval lies above zero, ``plain_better`` when it
    lies below, otherwise ``no_difference``; a difference smaller than ``noise_floor`` in
    absolute value is ``no_difference`` whatever its interval.
    """
    rows = list(results)
    final = [row for row in rows if row.get("split") == "final"]
    if final:
        cases = "final"
    elif any(row.get("split") for row in rows):
        cases = "rehearsal"
    else:
        cases = "unlabelled"
    estimate = paired_difference(final or rows, PRIMARY_METRIC)
    if estimate is None:
        return None

    difference, low, high = estimate["difference"], estimate["ci_low"], estimate["ci_high"]
    within_noise = noise_floor is not None and abs(difference) < noise_floor
    if within_noise:
        verdict = "no_difference"
    elif low > 0:
        verdict = "kg_better"
    elif high < 0:
        verdict = "plain_better"
    else:
        verdict = "no_difference"
    non_inferior = low >= NON_INFERIORITY_MARGIN

    lead = {
        "kg_better": "KG retrieval cites better",
        "plain_better": "Plain retrieval cites better",
        "no_difference": "No evidence of a difference",
    }[verdict]
    scope = {
        "final": "final-split cases",
        "rehearsal": "rehearsal cases (not release evidence)",
        "unlabelled": "cases",
    }[cases]
    claim = (
        f"{lead} in citation hit rate: KG {estimate['kg']:.{DECIMALS}f}, plain "
        f"{estimate['plain']:.{DECIMALS}f}, difference {_signed(difference)} "
        f"({CONFIDENCE:.0%} CI {_signed(low)} to {_signed(high)}) over {estimate['pairs']} "
        f"{scope}; KG cited better on {estimate['wins']} and plain on {estimate['losses']}. "
    )
    if within_noise:
        claim += f"The difference is below the noise floor ({noise_floor:.{DECIMALS}f}). "
    claim += (
        f"KG is non-inferior at the {NON_INFERIORITY_MARGIN:.2f} margin."
        if non_inferior
        else f"Non-inferiority at the {NON_INFERIORITY_MARGIN:.2f} margin is not shown."
    )
    return {
        "metric": "citation_hit_rate",
        "cases": cases,
        **estimate,
        "margin": NON_INFERIORITY_MARGIN,
        "non_inferior": non_inferior,
        "noise_floor": noise_floor,
        "verdict": verdict,
        "claim": claim,
    }


def noise_floor(
    base: Iterable[Mapping[str, Any]],
    head: Iterable[Mapping[str, Any]],
    modes: Sequence[str] = ("kg", "plain"),
) -> dict[str, Any]:
    """How often two runs of the same configuration disagree, per mode and metric.

    For every paired metric and mode: the cases both runs scored, how many changed value
    and which. A metric's floor is the larger of its modes' change rates (None when no case
    was scored twice); a KG-minus-plain difference smaller than it is not a difference.
    """
    head_by_id = {str(row.get("id")): row for row in head}
    shared = [
        (row, head_by_id[str(row.get("id"))]) for row in base if str(row.get("id")) in head_by_id
    ]
    per_mode: dict[str, dict[str, Any]] = {}
    for mode in modes:
        per_mode[mode] = {}
        for metric in PAIRED_METRICS:
            scored = [
                (str(before.get("id")), before[mode][metric], after[mode][metric])
                for before, after in shared
                if _applies(metric, before.get(mode) or {}, after.get(mode) or {})
            ]
            changed = [case_id for case_id, a, b in scored if float(a) != float(b)]
            per_mode[mode][metric] = {
                "pairs": len(scored),
                "changed": len(changed),
                "rate": round(len(changed) / len(scored), DECIMALS) if scored else None,
                "changed_cases": changed,
            }
    floor: dict[str, float | None] = {}
    for metric in PAIRED_METRICS:
        rates = [per_mode[mode][metric]["rate"] for mode in modes]
        known = [rate for rate in rates if rate is not None]
        floor[metric] = max(known) if known else None
    return {"floor": floor, "modes": per_mode}
