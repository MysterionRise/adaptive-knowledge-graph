"""
KG attribution in evaluation reports (#216): backend/app/core/eval_attribution.py, the
harness's --trace option and the first divergent stage in scripts/compare_evals.py.
"""

import json
from typing import Any

import httpx
import pytest

from backend.app.core.eval_attribution import (
    attribution_lines,
    expansion_specificity,
    explain,
    jaccard,
    kg_attribution,
)
from backend.tests.eval_report_builders import build_report, case_result, mode_result
from scripts import compare_evals, evaluate_rag

pytestmark = pytest.mark.unit

EXPECTED = ["The Stamp Act and the Sons and Daughters of Liberty"]


def _candidate(doc_id: str, section: str, rank: int, knn: int | None, bm25: int | None) -> dict:
    return {
        "id": doc_id,
        "rank": rank,
        "knn_rank": knn,
        "bm25_rank": bm25,
        "chapter": "Imperial Reforms",
        "section": section,
    }


def _trace(bm25: list[str], candidates: list[dict], used: list[str] | None = None) -> dict:
    stages: list[dict[str, Any]] = []
    if used is not None:
        stages += [
            {"name": "resolve", "concepts": used},
            {"name": "expand", "used": used},
        ]
    stages += [
        {"name": "knn", "hits": [{"id": "k1", "rank": 1}, {"id": "k2", "rank": 2}]},
        {"name": "bm25", "hits": [{"id": doc_id, "rank": i} for i, doc_id in enumerate(bm25, 1)]},
        {"name": "fuse", "k": 60, "candidates": candidates},
        {"name": "window", "ran": False},
        {"name": "rerank", "ran": False},
        {"name": "select", "sources": [{"id": c["id"]} for c in candidates[:5]]},
    ]
    return {"request_id": "rid", "stages": stages}


KG_TRACE = _trace(
    ["stamp", "b1"],
    [
        _candidate("k1", "Other", 1, 1, None),
        _candidate("stamp", EXPECTED[0], 2, None, 1),
    ],
    used=["Stamp Act", "Sons of Liberty"],
)
PLAIN_TRACE = _trace(
    ["b1", "b2"],
    [_candidate("k1", "Other", 1, 1, None), _candidate("k2", "Other", 2, 2, None)],
)


def _flipped(case_id: str, subject: str = "us_history", kg_hit: bool = True) -> dict:
    case = case_result(case_id, subject, hit=kg_hit, trace=KG_TRACE)
    case["plain"] = mode_result(hit=not kg_hit, kg_expansion_status="disabled", trace=PLAIN_TRACE)
    return case


class TestSpecificity:
    def test_jaccard(self):
        assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
        assert jaccard([], []) == 0.0

    def test_identical_expansions_score_one_and_disjoint_zero(self):
        assert expansion_specificity([["Price", "Firm"]] * 3)["mean_jaccard"] == 1.0
        assert expansion_specificity([["Stamp Act"], ["Cold War"]])["mean_jaccard"] == 0.0

    def test_empty_expansions_are_left_out(self):
        result = expansion_specificity([["Stamp Act"], [], ["Stamp Act", "Tea Act"]])

        assert result == {"cases": 2, "pairs": 1, "mean_jaccard": 0.5}

    def test_fewer_than_two_expansions_have_no_value(self):
        assert expansion_specificity([["Stamp Act"], []])["mean_jaccard"] is None


class TestExplain:
    def test_a_traced_flip_is_explained_from_the_keyword_channel(self):
        explanation = explain(_flipped("c1"), EXPECTED)

        assert explanation is not None
        assert explanation["stage"] == "bm25"  # kNN is the same in both runs
        assert explanation["added_concepts"] == ["Stamp Act", "Sons of Liberty"]
        assert explanation["kg"] == {
            "section": EXPECTED[0],
            "knn_rank": None,
            "bm25_rank": 1,
            "fused_rank": 2,
        }
        assert explanation["plain"] is None
        assert explanation["summary"] == (
            "First divergent stage: bm25. Keyword query adds Stamp Act, Sons of Liberty. "
            f"{EXPECTED[0]}: KG: kNN -, BM25 1, fused 2; plain: not among the fused candidates."
        )

    def test_no_explanation_without_both_traces(self):
        case = _flipped("c1")
        del case["plain"]["trace"]

        assert explain(case, EXPECTED) is None


class TestKgAttribution:
    def test_hits_and_losses_per_subject_with_specificity(self):
        results = [
            _flipped("hit", kg_hit=True),
            _flipped("loss", "economics", kg_hit=False),
            case_result("tie", expanded_concepts=["Stamp Act"]),
            case_result("other", expanded_concepts=["Stamp Act", "Tea Act"]),
        ]
        results[0]["kg"]["expanded_concepts"] = ["Cold War"]

        attribution = kg_attribution(results, {"hit": EXPECTED, "loss": EXPECTED})

        history, economics = attribution["us_history"], attribution["economics"]
        assert history["compared"] == 3
        assert [record["id"] for record in history["hits"]] == ["hit"]
        assert history["hits"][0]["explanation"]["stage"] == "bm25"
        assert history["losses"] == []
        assert history["specificity"] == {"cases": 3, "pairs": 3, "mean_jaccard": 0.167}
        assert [record["id"] for record in economics["losses"]] == ["loss"]
        assert list(attribution) == ["economics", "us_history"]

    def test_failed_requests_and_cases_without_sources_are_not_compared(self):
        failed = case_result("failed")
        failed["plain"] = {"status_code": 500}
        no_sources = case_result("refusal", hit=None)

        attribution = kg_attribution([failed, no_sources])

        assert attribution["us_history"]["compared"] == 0
        assert attribution["us_history"]["specificity"]["cases"] == 0  # no concepts used

    def test_markdown_lists_each_flip(self):
        lines = attribution_lines(kg_attribution([_flipped("c1")], {"c1": EXPECTED}))
        text = "\n".join(lines)

        assert "## KG attribution" in text
        assert "| us_history | 1 | 1 | 0 | n/a (0 cases) |" in text
        assert "- `c1` (us_history, KG hit): First divergent stage: bm25." in text
        assert attribution_lines({}) == []


def _api_recording(seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        payload: dict[str, Any] = {
            "question": body["question"],
            "sources": [{"section": EXPECTED[0], "chapter": "Imperial Reforms"}],
            "expanded_concepts": ["Stamp Act"],
            "kg_expansion_status": "ok",
            "retrieved_count": 1,
        }
        if body.get("include_trace"):
            payload["trace"] = {**KG_TRACE, "stages": [*KG_TRACE["stages"], {"name": "llm"}]}
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


CASE = {
    "id": "stamp",
    "subject": "us_history",
    "question": "Why did colonists oppose the Stamp Act?",
    "expected_sources": EXPECTED,
    "tags": ["answerable"],
}


class TestHarness:
    def test_trace_is_requested_and_kept_allowlisted(self):
        seen: list[dict] = []
        with httpx.Client(transport=_api_recording(seen)) as client:
            traced = evaluate_rag._ask(
                client, "http://api", CASE, True, retrieval_only=True, trace=True
            )
            plain = evaluate_rag._ask(client, "http://api", CASE, True, retrieval_only=True)

        assert [body["include_trace"] for body in seen] == [True, False]
        assert [stage["name"] for stage in traced["trace"]["stages"]][-1] == "select"  # no "llm"
        assert "trace" not in plain

    def test_summary_and_markdown_carry_the_attribution(self, tmp_path):
        report = build_report([_flipped("c1"), case_result("c2", "economics")])
        report["summary"] = evaluate_rag._summarize(report["results"], None, {"c1": EXPECTED})

        attribution = report["summary"]["kg_attribution"]
        assert attribution["us_history"]["hits"][0]["explanation"]["stage"] == "bm25"
        path = tmp_path / "report.md"
        evaluate_rag._write_markdown(path, report)
        markdown = path.read_text(encoding="utf-8")
        assert "## KG attribution" in markdown
        assert "- `kg_attribution`" not in markdown  # a section, not a summary bullet


class TestCompareStages:
    def test_a_flip_names_the_first_divergent_stage_when_both_runs_are_traced(self):
        base_case = case_result("c1", hit=True, trace=KG_TRACE)
        head_case = case_result("c1", hit=False, trace=PLAIN_TRACE)
        untraced = case_result("c2", hit=False)

        result = compare_evals.compare(
            build_report([base_case, case_result("c2")]), build_report([head_case, untraced])
        )

        stages = {(flip["id"], flip["field"]): flip["stage"] for flip in result["flips"]}
        assert stages[("c1", "citation_hit")] == "resolve"  # the head run recognised nothing
        assert stages[("c2", "citation_hit")] is None
        markdown = compare_evals.format_markdown(build_report(), build_report(), result)
        assert "| First divergent stage |" in markdown
        assert "| c1 | kg | citation_hit | True | False | resolve |" in markdown
