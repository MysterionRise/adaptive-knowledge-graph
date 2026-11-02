"""
Label every golden case with a stratum and a rehearsal/final split (#206).

A case without a stratum gets one from its tags, by the mapping in docs/evals/protocol.md
(``stratum_from_tags``); a case that has one keeps it. The split is stratified by subject
and stratum and drawn from the seed, never by hand: in each (subject, stratum) cell the case
IDs are sorted, shuffled with ``random.Random("<seed>:<subject>:<stratum>")``, and the first
half, rounded up, goes to the final split. Cases labelled ``split: pending`` (added since the
last version bump) stay out of the draw and keep their label.

The labels are written into the YAML in place, as ``stratum:`` and ``split:`` lines after
each case's ``tags:`` line, so the rest of the file keeps its formatting. The header records
``version`` and ``split_seed``, and ``--check`` recomputes the labels from that seed.

Usage:
    poetry run python scripts/split_golden.py --seed 206 --version 3   # write the labels
    poetry run python scripts/split_golden.py --check                  # exit 1 if they differ
    poetry run python scripts/split_golden.py --final-hashes           # list for protocol.md
"""

import argparse
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_rag import _case_hash  # noqa: E402

DEFAULT_CASES = "data/evals/golden_qa.yaml"
STRATA = ("single_hop", "multi_hop", "meaning", "distribution", "unanswerable", "adversarial")
SPLITS = ("rehearsal", "final", "pending")

# Checked in order: the first group that shares a tag with the case decides its stratum.
TAG_STRATA: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"prompt_injection"}), "adversarial"),
    (frozenset({"unsupported_claim"}), "unanswerable"),
    (frozenset({"source_conflict", "balanced_answer"}), "distribution"),
    (frozenset({"ambiguous", "disambiguation"}), "meaning"),
    (frozenset({"cross_chapter", "synthesis"}), "multi_hop"),
    (frozenset({"source_grounding", "terminology"}), "single_hop"),
)

_ID_RE = re.compile(r"^  - id: (\S+)\s*$")
_TAGS_RE = re.compile(r"^    tags: ")
_LABEL_RE = re.compile(r"^    (stratum|split): ")


def stratum_from_tags(case: dict[str, Any]) -> str:
    """The stratum today's tags imply; other answerable cases (contrast, kg_expansion) are
    multi-hop when they name more than one expected source."""
    tags = set(case.get("tags") or [])
    for group, stratum in TAG_STRATA:
        if tags & group:
            return stratum
    return "multi_hop" if len(case.get("expected_sources") or []) > 1 else "single_hop"


def draw_splits(cases: list[dict[str, Any]], seed: int) -> dict[str, str]:
    """Case ID -> "final" or "rehearsal", stratified by subject and stratum; pending cases
    are left out."""
    cells: dict[tuple[str, str], list[str]] = defaultdict(list)
    for case in cases:
        if case.get("split") != "pending":
            cells[(case["subject"], case["stratum"])].append(case["id"])
    splits: dict[str, str] = {}
    for (subject, stratum), ids in sorted(cells.items()):
        order = sorted(ids)
        random.Random(f"{seed}:{subject}:{stratum}").shuffle(order)
        n_final = (len(order) + 1) // 2
        for index, case_id in enumerate(order):
            splits[case_id] = "final" if index < n_final else "rehearsal"
    return splits


def labels(cases: list[dict[str, Any]], seed: int) -> dict[str, tuple[str, str]]:
    """Case ID -> (stratum, split) as the file should carry them."""
    with_strata = [
        {**case, "stratum": case.get("stratum") or stratum_from_tags(case)} for case in cases
    ]
    splits = draw_splits(with_strata, seed)
    return {
        case["id"]: (
            case["stratum"],
            "pending" if case.get("split") == "pending" else splits[case["id"]],
        )
        for case in with_strata
    }


def rewrite(text: str, wanted: dict[str, tuple[str, str]], seed: int, version: int) -> str:
    """The YAML text with the header and every case's labels set, the rest unchanged."""
    out: list[str] = []
    header = True
    current: str | None = None
    for line in text.splitlines():
        if header and re.match(r"^(version|split_seed): ", line):
            if line.startswith("version: "):
                out.extend([f"version: {version}", f"split_seed: {seed}"])
            continue
        match = _ID_RE.match(line)
        if match:
            header = False
            current = match.group(1)
        if _LABEL_RE.match(line):
            continue
        out.append(line)
        if current is not None and _TAGS_RE.match(line):
            stratum, split = wanted[current]
            out.extend([f"    stratum: {stratum}", f"    split: {split}"])
    new_text = "\n".join(out) + "\n"
    # The rewrite may only add or change the labels and the header
    old = yaml.safe_load(text)
    new = yaml.safe_load(new_text)
    strip = ("stratum", "split")
    assert [{k: v for k, v in c.items() if k not in strip} for c in old["cases"]] == [
        {k: v for k, v in c.items() if k not in strip} for c in new["cases"]
    ], "rewrite changed a case definition"
    missing = [
        c["id"] for c in new["cases"] if (c.get("stratum"), c.get("split")) != wanted[c["id"]]
    ]
    assert not missing, f"cases without a single-line tags: entry: {missing}"
    return new_text


def final_hashes(cases: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(case hash, ID) of the final split, sorted by ID: the list docs/evals/protocol.md pins."""
    return sorted(
        ((_case_hash(c), c["id"]) for c in cases if c.get("split") == "final"), key=lambda p: p[1]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--seed", type=int, default=None, help="Default: split_seed in the file")
    parser.add_argument("--version", type=int, default=None, help="Default: version in the file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Exit 1 if the labels differ")
    mode.add_argument("--final-hashes", action="store_true", help="Print the final-split hashes")
    args = parser.parse_args()

    path = Path(args.cases)
    text = path.read_text(encoding="utf-8")
    golden = yaml.safe_load(text)
    cases = golden["cases"]
    if args.final_hashes:
        for case_hash, case_id in final_hashes(cases):
            print(f"{case_hash}  {case_id}")
        return 0
    seed = args.seed if args.seed is not None else golden.get("split_seed")
    if seed is None:
        parser.error("no --seed and no split_seed in the file")
    version = args.version if args.version is not None else int(golden["version"])
    new_text = rewrite(text, labels(cases, seed), seed, version)
    if args.check:
        if new_text != text:
            print(
                f"{path}: stratum/split labels differ from seed {seed}; run scripts/split_golden.py"
            )
            return 1
        print(f"{path}: labels match seed {seed}")
        return 0
    path.write_text(new_text, encoding="utf-8")
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for stratum, split in labels(yaml.safe_load(new_text)["cases"], seed).values():
        counts[(stratum, split)] += 1
    for stratum in STRATA:
        print(f"{stratum:13} " + "  ".join(f"{s} {counts[(stratum, s)]}" for s in SPLITS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
