"""Paired statistics for evaluation reports (backend/app/core/eval_stats.py)."""

from typing import Any

import pytest

from backend.app.core.eval_stats import (
    PAIRED_METRICS,
    case_verdict,
    outcome,
    paired_counts,
    paired_summary,
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
