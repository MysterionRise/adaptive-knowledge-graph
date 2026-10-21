"""
Graph quality report for a built knowledge graph (scripts/build_knowledge_graph.py).

One Markdown document per build, written next to the JSON copy under data/processed/build/,
so a seed leaves a record of what the builder produced before any of it is quoted: how many
concepts carry a glossary definition or aliases, how many relationships of each type and
provenance there are, which concepts dominate by degree, whether the PREREQ graph has cycles
(a learning path cannot order one) and which concepts look like noise. The repository tracks
no graph data, so this report and GET /api/v1/graph/stats are the places to cite.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from backend.app.kg.schema import KnowledgeGraph, RelationshipType

TOP_BY_DEGREE = 20
NOISE_CANDIDATES = 20
MAX_CYCLES_LISTED = 10
# Report order; any other type the graph holds follows these.
RELATIONSHIP_ORDER = (RelationshipType.PREREQ, RelationshipType.RELATED, RelationshipType.COVERS)
# Edges between concepts: counted for the degree and broken down by provenance.
CONCEPT_EDGES = (RelationshipType.PREREQ, RelationshipType.RELATED)


def prereq_cycles(kg: KnowledgeGraph, limit: int = MAX_CYCLES_LISTED) -> list[list[str]]:
    """Cycles in the directed PREREQ graph, one per back edge of a depth-first search.

    Each cycle lists the concept names along it, closed by repeating the first. Concepts
    and their successors are visited in name order, so the result is deterministic. At
    most ``limit`` cycles are collected.
    """
    successors: dict[str, list[str]] = defaultdict(list)
    for rel in kg.relationships:
        if rel.type == RelationshipType.PREREQ:
            successors[rel.source].append(rel.target)
    for targets in successors.values():
        targets.sort()

    white, grey, black = 0, 1, 2
    colour: dict[str, int] = defaultdict(int)
    cycles: list[list[str]] = []
    for start in sorted(successors):
        if colour[start] != white:
            continue
        colour[start] = grey
        path = [start]
        stack = [(start, iter(successors[start]))]
        while stack and len(cycles) < limit:
            node, pending = stack[-1]
            following = next(pending, None)
            if following is None:
                stack.pop()
                path.pop()
                colour[node] = black
            elif colour[following] == grey:
                cycles.append([*path[path.index(following) :], following])
            elif colour[following] == white:
                colour[following] = grey
                path.append(following)
                stack.append((following, iter(successors.get(following, []))))
    return cycles


def _share(count: int, total: int) -> str:
    return "n/a" if total == 0 else f"{count} ({100 * count / total:.0f}%)"


def _yes(flag: object) -> str:
    return "yes" if flag else "no"


def graph_report(
    kg: KnowledgeGraph,
    *,
    subject_id: str,
    source: str,
    records: int,
    options: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> str:
    """The Markdown graph quality report for ``kg``."""
    concepts = list(kg.concepts.values())
    total = len(concepts)
    key_terms = sum(1 for c in concepts if c.key_term)
    defined = sum(1 for c in concepts if c.definition)
    aliased = sum(1 for c in concepts if c.aliases)
    single_word = sum(1 for c in concepts if len(c.name.split()) == 1)

    by_type: Counter[RelationshipType] = Counter(rel.type for rel in kg.relationships)
    by_provenance: Counter[tuple[RelationshipType, str]] = Counter(
        (rel.type, str((rel.provenance or {}).get("source") or "unspecified"))
        for rel in kg.relationships
        if rel.type in CONCEPT_EDGES
    )
    degree: Counter[str] = Counter()
    for rel in kg.relationships:
        if rel.type in CONCEPT_EDGES:
            degree[rel.source] += 1
            degree[rel.target] += 1
    top = sorted(concepts, key=lambda c: (-degree[c.name], -c.importance_score, c.name))
    noise = sorted(concepts, key=lambda c: (c.frequency, c.importance_score, c.name))
    cycles = prereq_cycles(kg)

    when = (generated_at or datetime.now(UTC)).isoformat(timespec="seconds")
    options_text = ", ".join(f"{k}={v}" for k, v in options.items()) or "defaults"
    lines = [
        f"# Knowledge graph report: {subject_id}",
        "",
        f"Generated: {when}",
        f"Source: `{source}` ({records} records)",
        f"Builder options: {options_text}",
        "",
        "## Concepts",
        "",
        "| Measure | Count |",
        "| --- | --- |",
        f"| Concepts | {total} |",
        f"| Author key terms | {_share(key_terms, total)} |",
        f"| With a glossary definition | {_share(defined, total)} |",
        f"| With aliases | {_share(aliased, total)} |",
        f"| Single-word names | {_share(single_word, total)} |",
        "",
        "## Relationships",
        "",
        "| Type | Provenance | Count |",
        "| --- | --- | --- |",
    ]
    ordered = [*RELATIONSHIP_ORDER, *sorted(set(by_type) - set(RELATIONSHIP_ORDER))]
    for rel_type in ordered:
        if rel_type not in by_type:
            lines.append(f"| {rel_type.value} | - | 0 |")
        elif rel_type in CONCEPT_EDGES:
            lines.extend(
                f"| {rel_type.value} | {provenance} | {count} |"
                for (kind, provenance), count in sorted(by_provenance.items())
                if kind == rel_type
            )
        else:
            lines.append(f"| {rel_type.value} | - | {by_type[rel_type]} |")
    lines.append(f"| Total | | {len(kg.relationships)} |")

    lines.extend(
        [
            "",
            f"## Top {TOP_BY_DEGREE} concepts by degree",
            "",
            "Degree counts PREREQ and RELATED edges in both directions.",
            "",
            "| # | Concept | Degree | Importance | Modules | Key term | Definition |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {rank} | {c.name} | {degree[c.name]} | {c.importance_score:.3f} | {c.frequency} | "
        f"{_yes(c.key_term)} | {_yes(c.definition)} |"
        for rank, c in enumerate(top[:TOP_BY_DEGREE], start=1)
    )
    if not top:
        lines.append("| - | none | - | - | - | - | - |")

    lines.extend(["", "## PREREQ cycles", ""])
    if cycles:
        lines.append(
            f"{len(cycles)} cycle(s) found (at most {MAX_CYCLES_LISTED} listed); a learning "
            "path cannot order the concepts on them:"
        )
        lines.append("")
        lines.extend(f"- {' -> '.join(cycle)}" for cycle in cycles)
    else:
        lines.append("No cycles: every PREREQ chain can be ordered.")

    lines.extend(
        [
            "",
            f"## Noise candidates: the {NOISE_CANDIDATES} concepts in the fewest modules",
            "",
            "Check them against the stopword list and the domain dictionary before quoting "
            "the graph.",
            "",
            "| Concept | Modules | Importance | Key term | Definition |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {c.name} | {c.frequency} | {c.importance_score:.3f} | {_yes(c.key_term)} | "
        f"{_yes(c.definition)} |"
        for c in noise[:NOISE_CANDIDATES]
    )
    if not noise:
        lines.append("| none | - | - | - | - |")
    return "\n".join(lines) + "\n"
