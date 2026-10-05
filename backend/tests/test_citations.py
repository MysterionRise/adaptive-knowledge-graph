"""
Citation matching in the evaluation harness, and the golden set's expected sources.

The golden set names the sections a good answer should cite. Every name must match
1-3 ingested modules by title, so a citation hit means the right section was retrieved.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import build_chunk_windows, evaluate_rag

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "data" / "evals" / "golden_qa.yaml"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

STAMP_ACT = {
    "text": "The Stamp Act of 1765 taxed printed paper in the colonies...",
    "module_title": (
        "Imperial Reforms and Colonial Protests, 1763-1774 - "
        "The Stamp Act and the Sons and Daughters of Liberty"
    ),
    "chapter": "Imperial Reforms and Colonial Protests, 1763-1774",
    "section": "The Stamp Act and the Sons and Daughters of Liberty",
}
TEA = {
    "text": "Colonists dumped the tea into Boston Harbor; the Stamp Act was long repealed...",
    "module_title": (
        "Imperial Reforms and Colonial Protests, 1763-1774 - "
        "The Destruction of the Tea and the Coercive Acts"
    ),
    "chapter": "Imperial Reforms and Colonial Protests, 1763-1774",
    "section": "The Destruction of the Tea and the Coercive Acts",
}


def _records(subject: str) -> list[dict[str, Any]]:
    path = PROCESSED_DIR / f"books_{subject}.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _expected_sources() -> Iterator[tuple[str, str, str]]:
    cases = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        for expected in case.get("expected_sources") or []:
            yield case["id"], case["subject"], expected


# ---------------------------------------------------------------------------
# evaluate_rag: matching on titles only
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSourceMatching:
    def test_matches_section_chapter_or_module_title(self):
        assert evaluate_rag.source_matches(STAMP_ACT, STAMP_ACT["section"])
        assert evaluate_rag.source_matches(STAMP_ACT, STAMP_ACT["chapter"])
        assert evaluate_rag.source_matches(STAMP_ACT, STAMP_ACT["module_title"])

    def test_never_matches_the_text_preview(self):
        # "Stamp Act" is in TEA's preview but not in its titles
        assert not evaluate_rag.source_matches(TEA, "Stamp Act")
        assert evaluate_rag._source_match_rank([TEA, STAMP_ACT], ["Stamp Act"]) is None

    def test_partial_titles_do_not_match(self):
        assert not evaluate_rag.source_matches(STAMP_ACT, "The Stamp Act")
        assert not evaluate_rag.source_matches(STAMP_ACT, "Imperial Reforms")

    def test_case_quotes_dashes_and_whitespace_are_normalised(self):
        source = {"section": "Challenges to Spain’s Supremacy", "chapter": "Early, 1492–1650"}
        assert evaluate_rag.source_matches(source, "challenges to  spain's supremacy")
        assert evaluate_rag.source_matches(source, "EARLY, 1492-1650")

    def test_empty_expected_or_missing_titles_never_match(self):
        assert not evaluate_rag.source_matches(STAMP_ACT, "  ")
        assert not evaluate_rag.source_matches({"text": "The Stamp Act"}, "The Stamp Act")

    def test_rank_is_the_first_matching_source(self):
        sources = [{"section": "Other"}, TEA, STAMP_ACT]
        expected = [STAMP_ACT["section"], TEA["section"]]
        assert evaluate_rag._source_match_rank(sources, expected) == 2
        assert evaluate_rag._source_match_rank(sources, []) is None
        assert evaluate_rag._reciprocal_rank(2) == 0.5


# ---------------------------------------------------------------------------
# The golden set against the ingested titles
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("subject", ["us_history", "economics"])
def test_ingested_records_carry_real_titles(subject):
    records = _records(subject)
    assert records
    for record in records:
        assert record["section"] and record["section"] != record["module_id"]
        assert record["module_id"] not in record["module_title"]
        if record["chapter"]:
            assert record["module_title"] == f"{record['chapter']} - {record['section']}"
        else:
            assert record["module_title"] == record["section"]
    # The chapter makes every title unique ("Introduction" opens most chapters)
    assert len({r["module_title"] for r in records}) == len(records)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case_id", "subject", "expected"),
    [pytest.param(*entry, id=f"{entry[0]}:{entry[2]}") for entry in _expected_sources()],
)
def test_expected_source_matches_one_to_three_ingested_titles(case_id, subject, expected):
    matches = [
        record["module_title"]
        for record in _records(subject)
        if evaluate_rag.source_matches(record, expected)
    ]
    assert 1 <= len(matches) <= 3, f"{case_id}: {expected!r} matches {len(matches)}: {matches}"


@pytest.mark.unit
def test_golden_set_has_expected_sources():
    entries = list(_expected_sources())
    assert len({case_id for case_id, _, _ in entries}) >= 40


# ---------------------------------------------------------------------------
# Chunk nodes for window retrieval keep the chapter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chunk_nodes_keep_chapter_and_section():
    chunks = [{"id": "m1_0", "text": "Text.", "module_id": "m1", "chapter": "Ch", "section": "S"}]
    [node] = build_chunk_windows.to_chunk_nodes(chunks, {})
    assert (node.chapter, node.section) == ("Ch", "S")
