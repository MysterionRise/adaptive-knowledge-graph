"""
Metrics and statistics of the learner simulator (#307).

Primary metric. For one learner: the mean, over the graph's slice concepts with equal
weights, of the true probability of answering a fresh item correctly, taken from the latent
state when the time budget ends. For a policy: the mean over learners.

Secondary metrics.

- Time to criterion: the simulated minutes after which a learner's primary value first
  reaches the protocol's criterion. A learner who does not get there within the budget is
  censored. The restricted mean counts a censored learner with the whole budget.
- AUC of the estimate: how well the production estimate ranks the truly mastered concepts
  above the others when the budget ends, over every learner and slice concept. The label
  is the truth (the true skill at or above the mastery threshold), not the next response:
  the issue asks for the estimate "against the truth" and the design note's validity test
  reads "in simulation: against the latent true state". A response would add guess and
  slip noise that caps the AUC of any estimate, and attempts alone would leave out the
  concepts a policy never practised. Ties count half.

Effects are paired differences. Learners are paired across policies by seed (common random
numbers), so an effect is the mean of the per-learner differences and its Monte Carlo
standard error is the standard deviation of those differences over the square root of the
number of learners. There are no p-values: the number of simulated learners is arbitrary,
so any difference becomes "significant" with enough of them. A percentile interval from
``eval_stats.bootstrap_interval`` can be added.

Sums use ``math.fsum``, which is exactly rounded and so independent of the order of its
terms and of the Python version. Numbers are rounded only when a report is rendered
(``render_json``). Nothing in this package calls the built-in ``sum``, whose float
algorithm changed in Python 3.12. ``bootstrap_interval`` does, so the last bit of an interval
bound can differ between Python versions. That is very unlikely to change a value at the six
decimals a report keeps, and it is not excluded: the pinned digest of the smoke test, which
CI computes on each version, is the check.

The decision rule is ``decision``: a policy goes forward when it gains at least delta in
the primary cell and loses no more than delta in every other cell.
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

from backend.app.core.eval_stats import bootstrap_interval

RENDER_DECIMALS: Final = 6
"""Decimals a rendered report keeps."""

Cell = tuple[str, str]
"""A cell of the matrix: (world id, DAG id)."""


def mean(values: Sequence[float]) -> float:
    """The mean, summed with ``math.fsum``.

    Raises:
        ValueError: If there are no values
    """
    if not values:
        raise ValueError("The mean of no values is undefined")
    return math.fsum(values) / len(values)


def standard_deviation(values: Sequence[float]) -> float:
    """The sample standard deviation (divisor n - 1); exactly 0.0 for equal values.

    Raises:
        ValueError: If there are fewer than two values
    """
    if len(values) < 2:
        raise ValueError("A standard deviation needs at least two values")
    if min(values) == max(values):
        # The mean of equal floats can differ from them in the last bit; their spread is 0.
        return 0.0
    centre = mean(values)
    squares = [(value - centre) * (value - centre) for value in values]
    return math.sqrt(math.fsum(squares) / (len(values) - 1))


def mc_standard_error(values: Sequence[float]) -> float:
    """The Monte Carlo standard error of the mean of ``values``."""
    return standard_deviation(values) / math.sqrt(len(values))


def primary_metric(p_fresh: Mapping[str, float], slice_concepts: Sequence[str]) -> float:
    """One learner's primary value: the equally weighted mean over the slice concepts.

    Args:
        p_fresh: The true probability of answering a fresh item correctly, by concept
        slice_concepts: The concepts that count; each has the weight 1 / len(slice_concepts)

    Raises:
        KeyError: If a slice concept has no probability
        ValueError: If the slice is empty
    """
    return mean([p_fresh[concept] for concept in slice_concepts])


def paired_effect(
    treatment: Sequence[float],
    baseline: Sequence[float],
    *,
    resamples: int = 0,
    seed: int = 0,
) -> dict[str, Any]:
    """
    The effect of ``treatment`` against ``baseline`` on paired learners.

    Args:
        treatment: One value per learner
        baseline: The same learners' values under the baseline, in the same order
        resamples: Bootstrap resamples for a 95% percentile interval; 0 for none
        seed: Seed of the bootstrap

    Returns:
        ``learners``, ``mean_difference``, ``sd_difference`` (of the paired differences),
        ``mc_se``, ``standardised`` (the mean difference in baseline standard deviations;
        None when the baseline does not vary), and ``ci_low`` and ``ci_high`` (None without
        resamples)

    Raises:
        ValueError: If the two sequences differ in length or hold fewer than two learners
    """
    if len(treatment) != len(baseline):
        raise ValueError("Paired values need the same learners on both sides")
    differences = [after - before for after, before in zip(treatment, baseline, strict=True)]
    spread = standard_deviation(baseline)
    effect = mean(differences)
    interval = (
        bootstrap_interval(differences, resamples=resamples, seed=seed) if resamples else None
    )
    return {
        "learners": len(differences),
        "mean_difference": effect,
        "sd_difference": standard_deviation(differences),
        "mc_se": mc_standard_error(differences),
        "standardised": effect / spread if spread > 0 else None,
        "ci_low": interval[0] if interval else None,
        "ci_high": interval[1] if interval else None,
    }


def time_to_criterion(minutes: Sequence[float | None], budget: float) -> dict[str, Any]:
    """
    Summary of the time to criterion over learners.

    Args:
        minutes: Per learner, the minutes after which the criterion was reached; None for a
            learner who did not reach it within the budget (censored)
        budget: The time budget in minutes

    Returns:
        ``reached`` and ``censored`` (counts) and ``restricted_mean_minutes``: the mean
        with every censored learner counted at the budget, a lower bound of the mean time

    Raises:
        ValueError: If there are no learners
    """
    reached = [value for value in minutes if value is not None]
    return {
        "reached": len(reached),
        "censored": len(minutes) - len(reached),
        "restricted_mean_minutes": mean([budget if value is None else value for value in minutes]),
    }


def auc(predictions: Sequence[tuple[float, bool]]) -> float | None:
    """
    Area under the ROC curve of scored labels.

    The probability that a positive case has a higher score than a negative one, with a tie
    counted as half (the Mann-Whitney statistic over the number of pairs).

    Args:
        predictions: (score, label) pairs

    Returns:
        The AUC, or None when the labels are all True or all False
    """
    ordered = sorted(predictions, key=lambda pair: pair[0])
    positives = len([score for score, label in ordered if label])
    negatives = len(ordered) - positives
    if positives == 0 or negatives == 0:
        return None

    # Counted in half pairs, in integers: 2 for a win, 1 for a tie.
    half_pairs = 0
    negatives_below = 0
    start = 0
    while start < len(ordered):
        end = start
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        tied_positives = len([score for score, label in ordered[start:end] if label])
        tied_negatives = (end - start) - tied_positives
        half_pairs += tied_positives * (2 * negatives_below + tied_negatives)
        negatives_below += tied_negatives
        start = end
    return half_pairs / (2 * positives * negatives)


def decision(effects: Mapping[Cell, float], primary_cell: Cell, delta: float) -> dict[str, Any]:
    """
    The protocol's decision rule for one policy against its baseline.

    A policy goes forward when its effect is at least ``+delta`` in the primary cell and no
    worse than ``-delta`` in every other cell.

    Args:
        effects: The effect (policy minus baseline, on the primary metric) per cell
        primary_cell: The cell in which the gain is required
        delta: The smallest effect that counts, in units of the primary metric

    Returns:
        ``verdict``: "forward", "no_gain" (the primary cell gains less than delta) or
        "loss_elsewhere" (the gain is there, another cell loses more than delta);
        ``primary_effect``; ``primary_gain`` (bool); ``losing_cells``: the other cells that
        lose more than delta, sorted, whatever the verdict

    Raises:
        ValueError: If delta is not positive or the primary cell has no effect
    """
    if delta <= 0:
        raise ValueError("delta must be positive")
    if primary_cell not in effects:
        raise ValueError(f"No effect for the primary cell {primary_cell!r}")
    primary_effect = effects[primary_cell]
    primary_gain = primary_effect >= delta
    losing = sorted(
        cell for cell, effect in effects.items() if cell != primary_cell and effect < -delta
    )
    if not primary_gain:
        verdict = "no_gain"
    elif losing:
        verdict = "loss_elsewhere"
    else:
        verdict = "forward"
    return {
        "verdict": verdict,
        "primary_effect": primary_effect,
        "primary_gain": primary_gain,
        "losing_cells": [list(cell) for cell in losing],
    }


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"A report cannot hold {value!r}")
        rounded = round(value, RENDER_DECIMALS)
        return 0.0 if rounded == 0 else rounded  # no "-0.0"
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Report keys must be strings")
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(item) for item in value]
    raise TypeError(f"A report cannot hold {type(value).__name__}")


def render_json(report: Mapping[str, Any]) -> str:
    """
    A report as JSON text: the same report always gives the same bytes.

    Keys are sorted, the indent is two spaces, floats are rounded to ``RENDER_DECIMALS``
    decimals here and nowhere earlier, and the text ends with a newline.

    Raises:
        TypeError: If the report holds a key that is not a string or a value JSON has no
            form for
        ValueError: If the report holds a float that is not finite
    """
    return json.dumps(_rounded(report), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
