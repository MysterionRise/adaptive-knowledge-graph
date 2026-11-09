"""
Golden set v3 (#206): every case has a stratum and a split drawn from the recorded seed, and
the final split is the one docs/evals/protocol.md pins by case hash.
"""

import re
from pathlib import Path

import pytest
import yaml

from scripts import evaluate_rag, split_golden

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "data" / "evals" / "golden_qa.yaml"
PROTOCOL = REPO_ROOT / "docs" / "evals" / "protocol.md"


def _golden() -> tuple[str, dict]:
    text = GOLDEN_SET.read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


# ---------------------------------------------------------------------------
# The committed golden set
# ---------------------------------------------------------------------------


def test_every_case_has_a_stratum_and_a_split():
    _, golden = _golden()
    assert golden["version"] == 3
    for case in golden["cases"]:
        assert case.get("stratum") in split_golden.STRATA, case["id"]
        assert case.get("split") in split_golden.SPLITS, case["id"]


def test_labels_are_the_seeded_draw():
    # Equivalent to `scripts/split_golden.py --check`: no split was assigned by hand
    text, golden = _golden()
    seed, version = golden["split_seed"], golden["version"]
    wanted = split_golden.labels(golden["cases"], seed)
    assert split_golden.rewrite(text, wanted, seed, version) == text


def test_final_split_hashes_match_the_protocol():
    _, golden = _golden()
    block = PROTOCOL.read_text(encoding="utf-8").split("## Final-split case hashes", 1)[1]
    pinned = re.findall(r"^([0-9a-f]{64})  (\S+)$", block, re.MULTILINE)
    assert pinned == split_golden.final_hashes(golden["cases"])


# ---------------------------------------------------------------------------
# Strata and the draw
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "sources", "stratum"),
    [
        (["adversarial", "prompt_injection"], ["a"], "adversarial"),
        (["adversarial", "unsupported_claim"], [], "unanswerable"),
        (["source_conflict", "balanced_answer"], ["a", "b"], "distribution"),
        (["ambiguous", "disambiguation"], ["a"], "meaning"),
        (["answerable", "cross_chapter"], ["a"], "multi_hop"),
        (["answerable", "terminology"], ["a", "b"], "single_hop"),
        (["answerable", "contrast"], ["a", "b"], "multi_hop"),
        (["answerable", "contrast"], ["a"], "single_hop"),
    ],
)
def test_stratum_from_tags(tags, sources, stratum):
    case = {"tags": tags, "expected_sources": sources}
    assert split_golden.stratum_from_tags(case) == stratum


def _cases(n: int, **extra) -> list[dict]:
    return [
        {"id": f"c{i:02d}", "subject": "economics", "stratum": "single_hop", **extra}
        for i in range(n)
    ]


def test_draw_is_seeded_stratified_and_rounds_up_for_the_final_split():
    cases = _cases(7) + [{"id": "m1", "subject": "economics", "stratum": "multi_hop"}]
    first = split_golden.draw_splits(cases, seed=1)
    assert first == split_golden.draw_splits(list(reversed(cases)), seed=1)
    assert sum(first[f"c{i:02d}"] == "final" for i in range(7)) == 4
    assert first["m1"] == "final"
    assert first != split_golden.draw_splits(cases, seed=2)


def test_pending_cases_stay_out_of_the_draw():
    cases = _cases(4) + [
        {"id": "new", "subject": "economics", "stratum": "single_hop", "split": "pending"}
    ]
    assert "new" not in split_golden.draw_splits(cases, seed=1)
    assert split_golden.labels(cases, seed=1)["new"] == ("single_hop", "pending")


def test_rewrite_adds_labels_after_tags_and_keeps_the_rest():
    text = (
        "version: 2\n"
        'description: "x"\n'
        "cases:\n"
        "  - id: a\n"
        "    subject: economics\n"
        '    question: "Q?"\n'
        '    tags: ["answerable", "terminology"]\n'
        "\n"
        "  - id: b\n"
        "    subject: economics\n"
        '    tags: ["answerable", "terminology"]\n'
        "    stratum: multi_hop\n"
        "    split: final\n"
    )
    wanted = {"a": ("single_hop", "rehearsal"), "b": ("single_hop", "final")}
    new = split_golden.rewrite(text, wanted, seed=7, version=3)
    assert new.startswith("version: 3\nsplit_seed: 7\n")
    assert (
        '    tags: ["answerable", "terminology"]\n    stratum: single_hop\n    split: rehearsal\n\n'
        in new
    )
    assert new.count("stratum:") == 2 and "multi_hop" not in new


# ---------------------------------------------------------------------------
# Case hashes ignore the labels
# ---------------------------------------------------------------------------


def test_case_hash_ignores_stratum_and_split():
    # So reports from before version 3 stay comparable case by case
    case = {"id": "a", "subject": "economics", "question": "Q?", "tags": ["answerable"]}
    labelled = {**case, "stratum": "single_hop", "split": "final"}
    assert evaluate_rag._case_hash(labelled) == evaluate_rag._case_hash(case)
    assert evaluate_rag._case_hash({**case, "question": "Q2?"}) != evaluate_rag._case_hash(case)
