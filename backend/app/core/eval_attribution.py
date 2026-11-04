"""
KG attribution in evaluation reports (#216): which citations the graph caused or cost, and
how specific its expansions are.

- **Attributable hits and losses.** A KG-attributable hit is a case where KG retrieval cites
  an expected source and plain retrieval does not; a loss is the reverse. Both modes embed
  the question for the kNN channel, so the difference comes from the keyword (BM25)
  channel, where the graph's concepts are added. With traces (``evaluate_rag.py
  --trace``), each one is explained: the first retrieval stage where the two runs part and
  the expected source's rank in each channel.
- **Expansion specificity.** The mean Jaccard similarity of the expanded-concept sets of
  every pair of cases, per subject, over the cases whose KG run used at least one concept.
  Near 1, every question expands to the same concepts (the hub problem #282 measured);
  near 0, expansions are specific to their question.

Source titles match the way the scorer matches them (``source_matches``). This module only
reads reports; it imports no settings and opens no connections.
"""

import unicodedata
from collections.abc import Iterable, Mapping
from itertools import combinations
from typing import Any

from backend.app.rag.trace import RETRIEVAL_STAGES, first_divergent_stage, stage_of

SOURCE_TITLE_FIELDS = ("chapter", "section", "module_title")
_TITLE_TRANSLATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
DECIMALS = 3


def normalize_title(title: object) -> str:
    """Case-, quote-, dash- and whitespace-insensitive form of a title for comparison."""
    text = unicodedata.normalize("NFKC", str(title or "")).translate(_TITLE_TRANSLATION)
    return " ".join(text.casefold().split())


def source_matches(source: Mapping[str, Any], expected: str) -> bool:
    """Whether a source's chapter, section or module title is the expected title.

    Matching is exact after :func:`normalize_title`; the golden-set test checks that every
    expected source names 1-3 ingested modules.
    """
    wanted = normalize_title(expected)
    return bool(wanted) and any(
        normalize_title(source.get(field)) == wanted for field in SOURCE_TITLE_FIELDS
    )


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """|A ∩ B| / |A ∪ B|; 0 for two empty sets."""
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def expansion_specificity(concept_sets: Iterable[Iterable[str]]) -> dict[str, Any]:
    """Mean pairwise Jaccard similarity of the non-empty concept sets (None below two)."""
    sets = [frozenset(concepts) for concepts in concept_sets]
    sets = [concepts for concepts in sets if concepts]
    pairs = list(combinations(sets, 2))
    mean = sum(jaccard(a, b) for a, b in pairs) / len(pairs) if pairs else None
    return {
        "cases": len(sets),
        "pairs": len(pairs),
        "mean_jaccard": None if mean is None else round(mean, DECIMALS),
    }


def _expected_ranks(trace: Mapping[str, Any] | None, expected: list[str]) -> dict[str, Any] | None:
    """The best-fused candidate matching an expected source: its section and its ranks."""
    fuse = stage_of(trace, "fuse")
    for candidate in (fuse or {}).get("candidates") or []:
        if any(source_matches(candidate, title) for title in expected):
            return {
                "section": candidate.get("section"),
                "knn_rank": candidate.get("knn_rank"),
                "bm25_rank": candidate.get("bm25_rank"),
                "fused_rank": candidate.get("rank"),
            }
    return None


def _ranks_text(label: str, ranks: dict[str, Any] | None) -> str:
    if ranks is None:
        return f"{label}: not among the fused candidates"
    return (
        f"{label}: kNN {ranks['knn_rank'] or '-'}, BM25 {ranks['bm25_rank'] or '-'}, "
        f"fused {ranks['fused_rank']}"
    )


def explain(result: Mapping[str, Any], expected: list[str]) -> dict[str, Any] | None:
    """
    Why the KG and plain runs of one case cite differently, from their traces.

    Returns the first retrieval stage where they part, the concepts the KG run added to the
    keyword query, the expected source's ranks in each run and a one-line summary; None
    when either run has no trace.
    """
    kg_trace = (result.get("kg") or {}).get("trace")
    plain_trace = (result.get("plain") or {}).get("trace")
    if not kg_trace or not plain_trace:
        return None
    stage = first_divergent_stage(plain_trace, kg_trace, RETRIEVAL_STAGES)
    added = list((stage_of(kg_trace, "expand") or {}).get("used") or [])
    kg_ranks = _expected_ranks(kg_trace, expected)
    plain_ranks = _expected_ranks(plain_trace, expected)
    section = (kg_ranks or plain_ranks or {}).get("section") or (expected[0] if expected else "")
    summary = (
        f"First divergent stage: {stage or 'none'}. Keyword query adds "
        f"{', '.join(added) or 'nothing'}. {section}: {_ranks_text('KG', kg_ranks)}; "
        f"{_ranks_text('plain', plain_ranks)}."
    )
    return {
        "stage": stage,
        "added_concepts": added,
        "kg": kg_ranks,
        "plain": plain_ranks,
        "summary": summary,
    }


def kg_attribution(
    results: Iterable[Mapping[str, Any]], expected_by_id: Mapping[str, list[str]] | None = None
) -> dict[str, Any]:
    """
    Per subject: KG-attributable hits and losses (with explanations when traced) and
    expansion specificity.

    ``expected_by_id`` gives each case's expected sources; a case without them, or whose
    KG or plain request failed, counts for specificity only if its KG request succeeded.
    """
    expected_by_id = expected_by_id or {}
    by_subject: dict[str, dict[str, Any]] = {}
    concepts_by_subject: dict[str, list[list[str]]] = {}
    for result in results:
        subject = str(result.get("subject") or "unknown")
        entry = by_subject.setdefault(subject, {"compared": 0, "hits": [], "losses": []})
        kg, plain = result.get("kg") or {}, result.get("plain") or {}
        if kg.get("status_code") == 200:
            concepts_by_subject.setdefault(subject, []).append(
                list(kg.get("expanded_concepts") or [])
            )
        if kg.get("status_code") != 200 or plain.get("status_code") != 200:
            continue
        kg_hit, plain_hit = kg.get("citation_hit"), plain.get("citation_hit")
        if kg_hit is None or plain_hit is None:
            continue
        entry["compared"] += 1
        if kg_hit == plain_hit:
            continue
        case_id = str(result.get("id"))
        record: dict[str, Any] = {"id": case_id}
        explanation = explain(result, list(expected_by_id.get(case_id) or []))
        if explanation is not None:
            record["explanation"] = explanation
        entry["hits" if kg_hit else "losses"].append(record)
    for subject, entry in by_subject.items():
        entry["specificity"] = expansion_specificity(concepts_by_subject.get(subject, []))
    return dict(sorted(by_subject.items()))


def attribution_lines(attribution: Mapping[str, Any]) -> list[str]:
    """The Markdown section for ``kg_attribution``; empty without any subject."""
    if not attribution:
        return []
    lines = [
        "",
        "## KG attribution",
        "",
        "Cases where the KG run cites an expected source and the plain run does not (hits), "
        "or the reverse (losses). Expansion specificity is the mean Jaccard similarity of "
        "the expanded-concept sets of every pair of cases: near 1, every question expands "
        "to the same concepts. Explanations need traces (`evaluate_rag.py --trace`).",
        "",
        "| Subject | Compared | KG-attributable hits | Losses | Specificity (mean Jaccard) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for subject, entry in attribution.items():
        specificity = entry.get("specificity") or {}
        mean = specificity.get("mean_jaccard")
        lines.append(
            f"| {subject} | {entry.get('compared')} | {len(entry.get('hits') or [])} | "
            f"{len(entry.get('losses') or [])} | "
            f"{'n/a' if mean is None else mean} ({specificity.get('cases')} cases) |"
        )
    for subject, entry in attribution.items():
        for kind in ("hits", "losses"):
            for record in entry.get(kind) or []:
                explanation = record.get("explanation") or {}
                summary = explanation.get("summary") or "no trace"
                label = "hit" if kind == "hits" else "loss"
                lines.append(f"- `{record['id']}` ({subject}, KG {label}): {summary}")
    return lines
