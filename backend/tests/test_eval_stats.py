"""Paired statistics for evaluation reports (backend/app/core/eval_stats.py)."""

from typing import Any

import pytest

from backend.app.core.eval_stats import (
    PAIRED_METRICS,
    STRATA,
    bootstrap_interval,
    case_verdict,
    interval_summary,
    interval_table,
    noise_floor,
    outcome,
    paired_counts,
    paired_difference,
    paired_summary,
    primary_endpoint,
    sign_test_p,
)
from backend.tests.eval_report_builders import case_result as _case

pytestmark = pytest.mark.unit


class TestSignTest:
    @pytest.mark.parametrize(
        ("wins", "losses", "expected"),
        [
            (0, 0, None),  # no discordant pairs: nothing to test
            (1, 0, 1.0),
            (2, 0, 0.5),
            (3, 0, 0.25),
            (4, 0, 0.125),
            (5, 0, 0.0625),
            (8, 0, 0.0078),
            (5, 1, 0.2188),  # 2 * (1 + 6) / 64
            (2, 2, 1.0),  # 2 * 11 / 16 capped at 1
            (0, 6, 0.0312),
        ],
    )
    def test_known_values(self, wins, losses, expected):
        assert sign_test_p(wins, losses) == expected

    def test_is_symmetric(self):
        assert sign_test_p(2, 7) == sign_test_p(7, 2)


class TestOutcome:
    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            (True, False, 1),
            (False, True, -1),
            (True, True, 0),
            (0.5, 0.25, 1),
            (0.25, 0.5, -1),
            (1.0, 1.0, 0),
            (None, 1.0, None),
            (0.3, None, None),
        ],
    )
    def test_direction(self, left, right, expected):
        assert outcome(left, right) == expected


class TestPairedCounts:
    def test_counts_and_sign_test(self):
        assert paired_counts([1, 1, 0, -1, None]) == {
            "pairs": 4,
            "wins": 2,
            "ties": 1,
            "losses": 1,
            "discordant": 3,
            "sign_test_p": 1.0,  # 2 * (1 + 3) / 8
        }

    def test_empty(self):
        assert paired_counts([]) == {
            "pairs": 0,
            "wins": 0,
            "ties": 0,
            "losses": 0,
            "discordant": 0,
            "sign_test_p": None,
        }


class TestCaseVerdict:
    @pytest.mark.parametrize(
        ("outcomes", "expected"),
        [
            ([1, 0], "win"),
            ([-1, 0], "loss"),
            ([0, 0], "tie"),
            ([1, -1], "mixed"),
            ([None, None], None),
            ([], None),
        ],
    )
    def test_verdict(self, outcomes, expected):
        assert case_verdict(outcomes) == expected


def _paired_case(case_id: str, kg_hit: bool, plain_hit: bool) -> dict[str, Any]:
    result = _case(case_id, hit=kg_hit)
    result["plain"]["citation_hit"] = plain_hit
    result["plain"]["mrr"] = 1.0 if plain_hit else 0.0
    return result


class TestPairedSummary:
    def test_synthetic_report_reproduces_known_counts(self):
        results = [
            _paired_case("c1", True, False),  # KG wins
            _paired_case("c2", True, False),
            _paired_case("c3", True, False),
            _paired_case("c4", False, True),  # plain wins
            _paired_case("c5", True, True),  # ties
            _paired_case("c6", False, False),
        ]
        summary = paired_summary(results)
        citation = {
            "pairs": 6,
            "wins": 3,
            "ties": 2,
            "losses": 1,
            "discordant": 4,
            "sign_test_p": 0.625,  # 2 * (1 + 4) / 16
        }
        assert summary["citation_hit"] == citation
        assert summary["mrr"] == citation
        assert summary["answer_term_recall"] == {
            "pairs": 6,
            "wins": 0,
            "ties": 6,
            "losses": 0,
            "discordant": 0,
            "sign_test_p": None,
        }
        assert summary["overall"] == {
            "pairs": 6,
            "wins": 3,
            "ties": 2,
            "losses": 1,
            "mixed": 0,
            "discordant": 4,
            "sign_test_p": 0.625,
        }

    def test_every_paired_metric_is_reported(self):
        assert set(paired_summary([_case("c1")])) == {*PAIRED_METRICS, "overall"}

    def test_failed_requests_and_missing_metrics_are_not_paired(self):
        failed = _case("c1")
        failed["plain"] = {"status_code": 503, "error": "LLM unavailable"}
        no_sources = _case("c2", hit=None)
        no_sources["plain"]["citation_hit"] = None
        no_sources["plain"]["mrr"] = 0.0
        summary = paired_summary([failed, no_sources])
        assert summary["citation_hit"]["pairs"] == 0
        assert summary["answer_term_recall"]["pairs"] == 1  # c2 only
        assert summary["overall"] == {
            "pairs": 1,
            "wins": 0,
            "ties": 1,
            "losses": 0,
            "mixed": 0,
            "discordant": 0,
            "sign_test_p": None,
        }

    def test_a_case_better_on_one_metric_and_worse_on_another_is_mixed(self):
        mixed = _paired_case("c1", False, True)  # plain wins the citation ...
        mixed["plain"]["answer_term_recall"] = 0.5  # ... KG wins term recall
        summary = paired_summary([mixed])
        assert summary["citation_hit"]["losses"] == 1
        assert summary["answer_term_recall"]["wins"] == 1
        assert summary["overall"]["mixed"] == 1
        assert summary["overall"]["discordant"] == 0
        assert summary["overall"]["sign_test_p"] is None


def _labelled(case_id: str, kg_hit: bool, plain_hit: bool, stratum: str, split: str) -> dict:
    result = _paired_case(case_id, kg_hit, plain_hit)
    result.update(stratum=stratum, split=split)
    return result


class TestBootstrapInterval:
    VALUES = [1.0, 0.0, 0.0, 1.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0]

    def test_pinned_values(self):
        # random.Random.random() keeps its sequence across Python versions for an int seed
        assert bootstrap_interval(self.VALUES) == pytest.approx((-0.2, 0.6))

    def test_deterministic_under_a_fixed_seed(self):
        assert bootstrap_interval(self.VALUES) == bootstrap_interval(list(self.VALUES))
        assert bootstrap_interval(self.VALUES, seed=1) == bootstrap_interval(self.VALUES, seed=1)

    def test_contains_the_mean(self):
        low, high = bootstrap_interval(self.VALUES, seed=7)
        assert low <= sum(self.VALUES) / len(self.VALUES) <= high

    def test_constant_values_give_a_degenerate_interval(self):
        assert bootstrap_interval([0.0] * 22) == (0.0, 0.0)
        assert bootstrap_interval([1.0]) == (1.0, 1.0)

    def test_empty(self):
        assert bootstrap_interval([]) is None


class TestPairedDifference:
    def test_rates_difference_interval_and_counts(self):
        results = [_paired_case(f"c{i}", True, False) for i in range(3)]
        results += [_paired_case("c3", False, True), _paired_case("c4", True, True)]
        estimate = paired_difference(results, "citation_hit")
        low, high = estimate.pop("ci_low"), estimate.pop("ci_high")
        assert estimate == {
            "pairs": 5,
            "kg": 0.8,
            "plain": 0.4,
            "difference": 0.4,
            "wins": 3,
            "losses": 1,
        }
        assert -1.0 <= low <= 0.4 <= high <= 1.0

    def test_mrr_counts_only_cases_with_expected_sources(self):
        no_sources = _case("c2", hit=None)
        no_sources["plain"]["citation_hit"] = None
        estimate = paired_difference([_paired_case("c1", True, False), no_sources], "mrr")
        assert estimate["pairs"] == 1
        assert estimate["difference"] == 1.0

    def test_failed_requests_and_missing_values_are_left_out(self):
        failed = _case("c1")
        failed["plain"] = {"status_code": 503}
        assert paired_difference([failed], "citation_hit") is None
        assert paired_difference([_case("c2")], "answer_term_recall_non_echo")["pairs"] == 1


class TestIntervalSummary:
    def test_overall_and_strata_in_protocol_order(self):
        results = [
            _labelled("c1", True, False, "adversarial", "final"),
            _labelled("c2", True, True, "single_hop", "final"),
            _labelled("c3", False, True, "single_hop", "rehearsal"),
            _paired_case("c4", True, True),  # unlabelled: overall only
        ]
        summary = interval_summary(results)
        assert (summary["resamples"], summary["seed"], summary["confidence"]) == (2000, 209, 0.95)
        assert list(summary["strata"]) == ["single_hop", "adversarial"]
        assert summary["overall"]["citation_hit"]["pairs"] == 4
        assert summary["strata"]["single_hop"]["citation_hit"]["difference"] == -0.5
        assert summary["strata"]["adversarial"]["citation_hit"]["wins"] == 1
        assert set(STRATA) >= set(summary["strata"])

    def test_table_has_a_row_per_group(self):
        table = interval_table(interval_summary([_labelled("c1", True, False, "meaning", "final")]))
        assert table[0].startswith("| Cases | With sources |")
        assert table[2] == (
            "| all | 1 | 1.000 / 0.000 | +1.000 [+1.000, +1.000] | +1.000 [+1.000, +1.000] "
            "| +0.000 [+0.000, +0.000] |"
        )
        assert table[3].startswith("| meaning | 1 |")


class TestPrimaryEndpoint:
    def test_uses_the_final_split_when_the_run_has_it(self):
        results = [
            _labelled("f1", True, True, "single_hop", "final"),
            _labelled("r1", False, True, "single_hop", "rehearsal"),
        ]
        endpoint = primary_endpoint(results)
        assert endpoint["cases"] == "final"
        assert endpoint["pairs"] == 1
        assert "over 1 final-split cases" in endpoint["claim"]

    def test_a_rehearsal_run_is_labelled_as_not_evidence(self):
        endpoint = primary_endpoint([_labelled("r1", True, True, "single_hop", "rehearsal")])
        assert endpoint["cases"] == "rehearsal"
        assert "rehearsal cases (not release evidence)" in endpoint["claim"]
        assert primary_endpoint([_paired_case("c1", True, True)])["cases"] == "unlabelled"

    def test_kg_better_only_when_the_interval_excludes_zero(self):
        endpoint = primary_endpoint([_paired_case(f"c{i}", True, False) for i in range(10)])
        assert endpoint["verdict"] == "kg_better"
        assert endpoint["claim"].startswith("KG retrieval cites better in citation hit rate:")
        assert "KG cited better on 10 and plain on 0" in endpoint["claim"]
        assert endpoint["non_inferior"] is True

    def test_plain_better_and_not_non_inferior(self):
        results = [_paired_case(f"c{i}", False, True) for i in range(10)]
        endpoint = primary_endpoint(results)
        assert endpoint["verdict"] == "plain_better"
        assert endpoint["non_inferior"] is False
        assert endpoint["claim"].endswith("Non-inferiority at the -0.10 margin is not shown.")

    def test_an_interval_across_zero_is_no_evidence(self):
        results = [_paired_case("c1", True, False), _paired_case("c2", False, True)]
        results += [_paired_case(f"t{i}", True, True) for i in range(8)]
        endpoint = primary_endpoint(results)
        assert endpoint["verdict"] == "no_difference"
        assert endpoint["claim"].startswith("No evidence of a difference")

    def test_a_difference_below_the_noise_floor_is_no_difference(self):
        results = [_paired_case(f"c{i}", True, False) for i in range(10)]
        results += [_paired_case(f"t{i}", True, True) for i in range(90)]
        assert primary_endpoint(results)["verdict"] == "kg_better"  # +0.10, interval above 0
        endpoint = primary_endpoint(results, noise_floor=0.15)
        assert endpoint["verdict"] == "no_difference"
        assert endpoint["noise_floor"] == 0.15
        assert "below the noise floor (0.150)" in endpoint["claim"]

    def test_none_without_cases_with_expected_sources(self):
        no_sources = _case("c1", hit=None)
        no_sources["plain"]["citation_hit"] = None
        assert primary_endpoint([no_sources]) is None


class TestNoiseFloor:
    def test_change_rates_per_mode_and_the_floor_per_metric(self):
        base = [_paired_case(f"c{i}", True, True) for i in range(4)]
        head = [_paired_case(f"c{i}", True, True) for i in range(4)]
        head[0]["kg"]["answer_term_recall"] = 0.5  # one KG answer changed
        head[1]["plain"]["answer_term_recall"] = 0.0  # and one plain answer
        head[2]["plain"]["answer_term_recall"] = 0.0  # and another
        result = noise_floor(base, head)
        assert result["modes"]["kg"]["answer_term_recall"] == {
            "pairs": 4,
            "changed": 1,
            "rate": 0.25,
            "changed_cases": ["c0"],
        }
        assert result["modes"]["plain"]["answer_term_recall"]["changed_cases"] == ["c1", "c2"]
        assert result["floor"]["answer_term_recall"] == 0.5  # the larger mode
        assert result["floor"]["citation_hit"] == 0.0
        assert set(result["floor"]) == set(PAIRED_METRICS)

    def test_only_cases_both_runs_scored_count(self):
        base = [_paired_case("c1", True, True), _paired_case("c2", True, True)]
        failed = _paired_case("c1", True, True)
        failed["kg"] = {"status_code": 503}
        result = noise_floor(base, [failed])  # c2 is missing from the second run
        assert result["modes"]["kg"]["citation_hit"]["pairs"] == 0
        assert result["modes"]["plain"]["citation_hit"]["pairs"] == 1
        assert result["floor"]["citation_hit"] == 0.0
        assert result["floor"]["unsupported_refusal"] is None
