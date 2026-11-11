"""
Tests for the simulator's metrics, statistics and decision rule (#307).

``backend/app/student/simulation/metrics.py`` computes the primary metric (an equally
weighted mean over the slice concepts), paired effects with Monte Carlo standard errors,
the time to criterion with censoring, the AUC with ties counted half, and the decision rule
of the protocol. Every number below is computed by hand in a comment or by a second, slower
implementation in this module.

There are no p-values in the simulator: ``test_results_carry_no_p_value`` holds every result
of this module to that, and ``test_simulation_runner.py`` holds the whole report to it.
"""

import json
import math
import random

import pytest

from backend.app.core import eval_stats
from backend.app.student.simulation import metrics
from backend.app.student.simulation.metrics import (
    RENDER_DECIMALS,
    auc,
    decision,
    mc_standard_error,
    mean,
    paired_effect,
    primary_metric,
    render_json,
    standard_deviation,
    time_to_criterion,
)

pytestmark = pytest.mark.unit

TOLERANCE = 1e-12

# The exact sum is 1.0, and math.fsum gives it. The built-in sum gives 0.0 for this order on
# Python 3.11.18, 3.12.3 and 3.13.18 (measured): the compensated sum of 3.12 and later keeps
# the 1.0 of smaller vectors such as [1e32, 1e16, 1.0, -1e16, -1e32], but not of this one.
CANCELLING = [1e60, 1e30, 1.0, -1e30, -1e60]


# ---------------------------------------------------------------------------
# mean, standard deviation, Monte Carlo standard error
# ---------------------------------------------------------------------------


def test_mean_is_exactly_rounded():
    assert mean(CANCELLING) == 0.2
    assert mean([0.1] * 10) == 0.1  # adding left to right gives 0.9999999999999999 / 10
    assert mean([2.0]) == 2.0


def test_mean_does_not_depend_on_the_order_of_its_values():
    rng = random.Random(307)
    values = [rng.random() * 10 ** int(rng.random() * 30 - 15) for _ in range(200)]
    values += [-value for value in values[:50]]
    orders = [values, values[::-1], sorted(values), sorted(values, key=abs)]

    assert len({mean(order) for order in orders}) == 1
    assert mean(CANCELLING[::-1]) == mean(sorted(CANCELLING)) == 0.2


def test_mean_of_nothing_is_an_error():
    with pytest.raises(ValueError, match="no values"):
        mean([])


def test_standard_deviation_and_standard_error_by_hand():
    """1, 2, 3, 4: mean 2.5, squared deviations 2.25 + 0.25 + 0.25 + 2.25 = 5, over 3."""
    values = [1.0, 2.0, 3.0, 4.0]

    assert standard_deviation(values) == pytest.approx(math.sqrt(5 / 3), abs=TOLERANCE)
    assert mc_standard_error(values) == pytest.approx(math.sqrt(5 / 3) / 2, abs=TOLERANCE)


def test_equal_values_have_exactly_no_spread():
    """The mean of three times 0.4 is 0.4000000000000001; the spread is 0.0 all the same."""
    assert mean([0.4, 0.4, 0.4]) != 0.4
    assert standard_deviation([0.4, 0.4, 0.4]) == 0.0
    assert mc_standard_error([0.7, 0.7, 0.7]) == 0.0
    assert standard_deviation([0.4, 0.4, 0.4000000000000001]) > 0.0


@pytest.mark.parametrize("values", [[], [1.0]])
def test_standard_deviation_needs_two_values(values):
    with pytest.raises(ValueError, match="at least two values"):
        standard_deviation(values)
    with pytest.raises(ValueError, match="at least two values"):
        mc_standard_error(values)


# ---------------------------------------------------------------------------
# Primary metric
# ---------------------------------------------------------------------------


def test_primary_metric_weights_the_slice_concepts_equally():
    p_fresh = {"a": 0.9, "b": 0.3, "c": 0.6}

    assert primary_metric(p_fresh, ("a", "b", "c")) == pytest.approx(0.6, abs=TOLERANCE)
    assert primary_metric(p_fresh, ("a", "b")) == pytest.approx(0.6, abs=TOLERANCE)
    assert primary_metric(p_fresh, ("b",)) == 0.3
    # A concept outside the slice does not count, however well it is known.
    assert primary_metric({**p_fresh, "d": 1.0}, ("a", "b", "c")) == pytest.approx(
        0.6, abs=TOLERANCE
    )
    assert primary_metric(p_fresh, ("c", "b", "a")) == primary_metric(p_fresh, ("a", "b", "c"))


def test_primary_metric_needs_every_slice_concept_and_a_slice():
    with pytest.raises(KeyError):
        primary_metric({"a": 0.9}, ("a", "b"))
    with pytest.raises(ValueError, match="no values"):
        primary_metric({"a": 0.9}, ())


# ---------------------------------------------------------------------------
# Paired effects
# ---------------------------------------------------------------------------

TREATMENT = [0.5, 0.7, 0.9, 0.6]
BASELINE = [0.4, 0.5, 0.9, 0.7]
# Differences 0.1, 0.2, 0.0, -0.1: mean 0.05; squared deviations 0.0025 + 0.0225 + 0.0025 +
# 0.0225 = 0.05, over 3. Baseline: mean 0.625, squared deviations 0.1475, over 3.
SD_DIFFERENCE = math.sqrt(0.05 / 3)
SD_BASELINE = math.sqrt(0.1475 / 3)


def test_paired_effect_by_hand():
    effect = paired_effect(TREATMENT, BASELINE)

    assert effect["learners"] == 4
    assert effect["mean_difference"] == pytest.approx(0.05, abs=TOLERANCE)
    assert effect["sd_difference"] == pytest.approx(SD_DIFFERENCE, abs=TOLERANCE)
    assert effect["mc_se"] == pytest.approx(SD_DIFFERENCE / 2, abs=TOLERANCE)
    assert effect["standardised"] == pytest.approx(0.05 / SD_BASELINE, abs=TOLERANCE)
    assert effect["ci_low"] is None and effect["ci_high"] is None
    assert set(effect) == {
        "learners",
        "mean_difference",
        "sd_difference",
        "mc_se",
        "standardised",
        "ci_low",
        "ci_high",
    }


def test_paired_effect_uses_the_pairing():
    """The same two samples, paired differently: the same mean, another standard error."""
    paired = paired_effect(TREATMENT, BASELINE)
    mispaired = paired_effect(TREATMENT, BASELINE[::-1])
    unpaired_se = math.sqrt(
        standard_deviation(TREATMENT) ** 2 / 4 + standard_deviation(BASELINE) ** 2 / 4
    )

    assert mispaired["mean_difference"] == pytest.approx(paired["mean_difference"], abs=TOLERANCE)
    assert mispaired["mc_se"] != pytest.approx(paired["mc_se"], abs=1e-6)
    assert paired["mc_se"] < unpaired_se  # pairing learners removes their shared variation


def test_paired_effect_of_a_policy_against_itself_is_exactly_zero():
    effect = paired_effect(TREATMENT, TREATMENT, resamples=20)

    assert effect["mean_difference"] == 0.0
    assert effect["mc_se"] == 0.0
    assert (effect["ci_low"], effect["ci_high"]) == (0.0, 0.0)
    assert effect["standardised"] == 0.0


def test_standardised_effect_is_none_when_the_baseline_does_not_vary():
    effect = paired_effect([0.5, 0.6, 0.7], [0.4, 0.4, 0.4])

    assert effect["standardised"] is None
    assert effect["mean_difference"] == pytest.approx(0.2, abs=TOLERANCE)


def test_paired_effect_needs_the_same_learners_and_at_least_two():
    with pytest.raises(ValueError, match="same learners"):
        paired_effect([0.1, 0.2, 0.3], [0.1, 0.2])
    with pytest.raises(ValueError, match="at least two values"):
        paired_effect([0.1], [0.2])


def test_bootstrap_interval_comes_from_eval_stats(monkeypatch):
    """The interval is the reused function's, called on the paired differences."""
    calls = []

    def spy(values, *, resamples, seed):
        calls.append((list(values), resamples, seed))
        return (-0.25, 0.75)

    monkeypatch.setattr(metrics, "bootstrap_interval", spy)

    effect = paired_effect(TREATMENT, BASELINE, resamples=300, seed=9)

    ((values, resamples, seed),) = calls
    assert values == pytest.approx([0.1, 0.2, 0.0, -0.1], abs=TOLERANCE)
    assert (resamples, seed) == (300, 9)
    assert (effect["ci_low"], effect["ci_high"]) == (-0.25, 0.75)
    assert metrics.bootstrap_interval is spy
    monkeypatch.undo()
    assert metrics.bootstrap_interval is eval_stats.bootstrap_interval


def test_bootstrap_interval_is_seeded_and_brackets_the_effect():
    rng = random.Random(307)
    baseline = [rng.random() for _ in range(60)]
    treatment = [value + 0.05 + 0.1 * (rng.random() - 0.5) for value in baseline]

    first = paired_effect(treatment, baseline, resamples=200, seed=1)
    again = paired_effect(treatment, baseline, resamples=200, seed=1)
    other = paired_effect(treatment, baseline, resamples=200, seed=2)

    assert first == again
    assert (first["ci_low"], first["ci_high"]) != (other["ci_low"], other["ci_high"])
    assert first["ci_low"] < first["mean_difference"] < first["ci_high"]
    assert first["ci_high"] - first["ci_low"] < 6 * first["mc_se"]


# ---------------------------------------------------------------------------
# Time to criterion
# ---------------------------------------------------------------------------


def test_time_to_criterion_counts_a_censored_learner_at_the_budget():
    """5, censored, 10, censored with a budget of 20: (5 + 20 + 10 + 20) / 4."""
    summary = time_to_criterion([5.0, None, 10.0, None], 20.0)

    assert summary == {"reached": 2, "censored": 2, "restricted_mean_minutes": 13.75}


def test_time_to_criterion_without_and_with_only_censored_learners():
    assert time_to_criterion([4.0, 6.0], 20.0) == {
        "reached": 2,
        "censored": 0,
        "restricted_mean_minutes": 5.0,
    }
    assert time_to_criterion([None, None, None], 20.0) == {
        "reached": 0,
        "censored": 3,
        "restricted_mean_minutes": 20.0,
    }


def test_time_zero_is_reached_not_censored():
    """A learner who starts at the criterion has the time 0.0, which is not None."""
    assert time_to_criterion([0.0, None], 10.0) == {
        "reached": 1,
        "censored": 1,
        "restricted_mean_minutes": 5.0,
    }


def test_time_to_criterion_needs_learners():
    with pytest.raises(ValueError, match="no values"):
        time_to_criterion([], 20.0)


# ---------------------------------------------------------------------------
# AUC
# ---------------------------------------------------------------------------


def _auc_by_pairs(predictions: list[tuple[float, bool]]) -> float | None:
    """Every positive against every negative: 1 for a win, a half for a tie."""
    positives = [score for score, label in predictions if label]
    negatives = [score for score, label in predictions if not label]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            wins += 1.0 if positive > negative else 0.5 if positive == negative else 0.0
    return wins / (len(positives) * len(negatives))


def test_auc_of_a_perfect_an_inverted_and_a_constant_score():
    perfect = [(0.1, False), (0.2, False), (0.8, True), (0.9, True)]
    inverted = [(0.9, False), (0.8, False), (0.2, True), (0.1, True)]
    constant = [(0.3, False), (0.3, True), (0.3, False), (0.3, True), (0.3, True)]

    assert auc(perfect) == 1.0
    assert auc(inverted) == 0.0
    assert auc(constant) == 0.5  # every pair is a tie, and a tie counts half


def test_auc_with_some_ties_by_hand():
    """Positives 0.5 and 0.9, negatives 0.2 and 0.5: three wins and one tie of four pairs."""
    predictions = [(0.2, False), (0.5, True), (0.5, False), (0.9, True)]

    assert auc(predictions) == 3.5 / 4
    assert auc(predictions[::-1]) == 3.5 / 4


def test_auc_of_an_uninformative_score_is_a_half():
    """Two positives and two negatives at each of two scores."""
    predictions = [(0.3, True), (0.3, False), (0.8, True), (0.8, False)] * 2

    assert auc(predictions) == 0.5


@pytest.mark.parametrize(
    "predictions",
    [[], [(0.4, True)], [(0.4, True), (0.9, True)], [(0.1, False), (0.2, False)]],
    ids=["empty", "one", "all-positive", "all-negative"],
)
def test_auc_needs_both_labels(predictions):
    assert auc(predictions) is None


@pytest.mark.parametrize("seed", range(20))
def test_auc_equals_the_count_over_all_pairs(seed):
    """Seeded cases with many ties (scores on a grid of ten values)."""
    rng = random.Random(seed)
    predictions = [(int(rng.random() * 10) / 10, rng.random() < 0.4) for _ in range(120)]

    expected = _auc_by_pairs(predictions)

    assert expected is not None
    assert auc(predictions) == pytest.approx(expected, abs=TOLERANCE)
    assert auc(sorted(predictions, reverse=True)) == auc(predictions)
    assert 0.0 <= expected <= 1.0


# ---------------------------------------------------------------------------
# The decision rule
# ---------------------------------------------------------------------------

PRIMARY = ("weak", "precision-0.8")
DELTA = 0.02


def _effects(primary: float, **others: float) -> dict[tuple[str, str], float]:
    effects = {PRIMARY: primary}
    for name, effect in others.items():
        world, dag = name.split("__")
        effects[(world, dag)] = effect
    return effects


def test_forward_with_a_gain_in_the_primary_cell_and_no_loss_elsewhere():
    result = decision(_effects(0.03, strong__true=0.01, none__true=-0.01), PRIMARY, DELTA)

    assert result == {
        "verdict": "forward",
        "primary_effect": 0.03,
        "primary_gain": True,
        "losing_cells": [],
    }


def test_no_gain_when_the_primary_cell_gains_less_than_delta():
    result = decision(_effects(0.019, strong__true=0.2, none__true=0.2), PRIMARY, DELTA)

    assert result["verdict"] == "no_gain"
    assert result["primary_gain"] is False
    assert result["losing_cells"] == []


def test_loss_elsewhere_stops_a_policy_that_gains_in_the_primary_cell():
    """A policy that loses more than delta in one other cell does not go forward."""
    result = decision(
        _effects(0.2, strong__true=0.3, none__true=-0.021, weak__none=0.1), PRIMARY, DELTA
    )

    assert result["verdict"] == "loss_elsewhere"
    assert result["primary_gain"] is True
    assert result["losing_cells"] == [["none", "true"]]


def test_no_gain_and_losses_lists_the_losing_cells_sorted():
    result = decision(
        _effects(-0.5, weak__none=-0.03, strong__true=-0.2, none__true=0.0), PRIMARY, DELTA
    )

    assert result["verdict"] == "no_gain"
    assert result["losing_cells"] == [["strong", "true"], ["weak", "none"]]
    # The primary cell is judged by its gain; it is not listed among the others.
    assert list(PRIMARY) not in result["losing_cells"]


def test_decision_boundaries_are_at_least_delta_and_no_worse_than_minus_delta():
    exactly = decision(_effects(DELTA, strong__true=-DELTA), PRIMARY, DELTA)
    just_under = decision(_effects(0.019999999, strong__true=0.0), PRIMARY, DELTA)
    just_over_loss = decision(_effects(DELTA, strong__true=-0.020000001), PRIMARY, DELTA)

    assert exactly["verdict"] == "forward"
    assert just_under["verdict"] == "no_gain"
    assert just_over_loss["verdict"] == "loss_elsewhere"


def test_decision_with_the_primary_cell_only():
    assert decision({PRIMARY: 0.05}, PRIMARY, DELTA)["verdict"] == "forward"
    assert decision({PRIMARY: 0.0}, PRIMARY, DELTA)["verdict"] == "no_gain"


def test_decision_depends_on_delta():
    effects = _effects(0.05, strong__true=-0.04)

    assert decision(effects, PRIMARY, 0.02)["verdict"] == "loss_elsewhere"
    assert decision(effects, PRIMARY, 0.05)["verdict"] == "forward"
    assert decision(effects, PRIMARY, 0.06)["verdict"] == "no_gain"


def test_decision_needs_a_positive_delta_and_the_primary_cell():
    with pytest.raises(ValueError, match="delta must be positive"):
        decision(_effects(0.1), PRIMARY, 0.0)
    with pytest.raises(ValueError, match="No effect for the primary cell"):
        decision({("strong", "true"): 0.1}, PRIMARY, DELTA)


# ---------------------------------------------------------------------------
# No p-values
# ---------------------------------------------------------------------------


def test_results_carry_no_p_value():
    results = [
        paired_effect(TREATMENT, BASELINE, resamples=20),
        decision(_effects(0.03, strong__true=0.01), PRIMARY, DELTA),
        time_to_criterion([5.0, None], 20.0),
    ]

    for result in results:
        assert not [key for key in result if "p_value" in key or "sign_test" in key or key == "p"]
    assert not {"sign_test_p", "paired_counts", "paired_summary"} & set(vars(metrics))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_json_sorts_keys_so_insertion_order_does_not_matter():
    first = {"b": 1, "a": {"y": 2.5, "x": [1, 2]}}
    second = {"a": {"x": [1, 2], "y": 2.5}, "b": 1}

    text = render_json(first)

    assert text == render_json(second)
    assert (
        text
        == '{\n  "a": {\n    "x": [\n      1,\n      2\n    ],\n    "y": 2.5\n  },\n  "b": 1\n}\n'
    )
    assert json.loads(text) == first


def test_render_json_rounds_floats_to_six_decimals_and_only_when_rendering():
    report = {"third": 1 / 3, "small": 1.4e-7, "list": [2 / 3, (0.1 + 0.2,)]}

    rendered = json.loads(render_json(report))

    assert RENDER_DECIMALS == 6
    assert rendered == {"third": 0.333333, "small": 0.0, "list": [0.666667, [0.3]]}
    assert report["third"] == 1 / 3  # the report itself keeps every digit
    assert report["list"] == [2 / 3, (0.1 + 0.2,)]


def test_render_json_never_writes_a_negative_zero():
    text = render_json({"a": -0.0, "b": -1e-9, "c": [-0.0000004]})

    assert "-0.0" not in text
    assert json.loads(text) == {"a": 0.0, "b": 0.0, "c": [0.0]}


def test_render_json_keeps_other_values_as_they_are():
    report = {"flag": True, "count": 3, "none": None, "name": "weak", "big": 12393262334832495163}

    rendered = json.loads(render_json(report))

    assert rendered == report
    assert type(rendered["flag"]) is bool and type(rendered["count"]) is int


def test_render_json_ends_with_a_newline_and_keeps_non_ascii():
    text = render_json({"δ": 0.02})

    assert text == '{\n  "δ": 0.02\n}\n'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_render_json_refuses_floats_that_are_not_finite(bad):
    with pytest.raises(ValueError, match="cannot hold"):
        render_json({"value": bad})


def test_render_json_refuses_keys_and_values_json_has_no_form_for():
    with pytest.raises(TypeError, match="keys must be strings"):
        render_json({"cells": {("weak", "true"): 1.0}})
    with pytest.raises(TypeError, match="cannot hold set"):
        render_json({"values": {1, 2}})
