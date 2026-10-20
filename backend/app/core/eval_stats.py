"""
Paired statistics for evaluation reports: win/tie/loss counts and an exact sign test.

Every golden case is asked twice, with and without knowledge-graph expansion, so the case
is the paired unit. A comparison of the two modes is therefore a count of the cases where
one mode did better, the same or worse, not a difference of means: with 49 cases that have
expected sources, a single citation flip moves the hit rate by two points. The same counts
compare two runs of the same cases (scripts/compare_evals.py).

The sign test is exact and two-sided, on the discordant pairs only (ties carry no
information about direction). Standard library only; bootstrap intervals come separately.
"""

import math
from collections.abc import Iterable, Mapping
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
