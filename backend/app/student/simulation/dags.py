"""
The prerequisite DAG a policy is given, as variants of the true one (#307).

The world learns by its true DAG. A policy sees a DAG that may be wrong, because a curated
or extracted graph has wrong and missing edges (#223). ``given_dag`` builds one variant from
the true graph, a ``DagSpec`` and a seed; the same three always give the same edges.

| Kind               | What the policy gets                                                |
| ------------------ | ------------------------------------------------------------------- |
| ``true``           | The true edges                                                      |
| ``precision``      | The true edges plus false ones, until precision is about ``level``  |
| ``recall``         | The true edges with some removed, until recall is about ``level``   |
| ``reversed``       | The true edges with a share of ``level`` turned round               |
| ``chapter_chain``  | The last concept of each chapter before every concept of the next   |
| ``none``           | No edge                                                             |
| ``degree_shuffle`` | Rewired edges with every in-degree and out-degree of the true DAG   |

Choices of this draft, for the maintainer to confirm in the protocol:

- Precision is lowered by adding false edges only, so recall stays 1. Recall is lowered by
  removing true edges only, so precision stays 1. The two are not crossed.
- A false edge points forward in book order and joins two concepts that no path of true
  edges joins. A pair with such a path is a redundant edge, not a wrong one, and a forward
  edge keeps the variant acyclic.
- Edges are whole. A precision variant gets the number of false edges whose precision is
  nearest the level; a recall or reversed variant gets the level's share of the true edges,
  rounded half up. A small graph therefore misses a level by up to half an edge, and
  ``precision_recall`` reports what a variant has.
- A reversed edge can close a cycle. The policies take any edge set.
- The shuffle swaps the targets of two edges and keeps a swap only if both new edges point
  forward in book order and are new. Book order therefore stays a topological order.

Every edge is an ``EdgeUse`` with the relation ``PREREQ`` and the provenance
``sim:<DagSpec.id>``, so a decision record shows which variant an edge came from.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from backend.app.student.policy.base import EdgeUse
from backend.app.student.simulation.worlds import ConceptGraph, draw_sample, stream

DagKind = Literal[
    "true", "precision", "recall", "reversed", "chapter_chain", "none", "degree_shuffle"
]

RELATION: Final = "PREREQ"

_KINDS_WITH_LEVEL: Final = frozenset({"precision", "recall", "reversed"})
_KINDS: Final = _KINDS_WITH_LEVEL | {"true", "chapter_chain", "none", "degree_shuffle"}

SHUFFLE_SWAPS_PER_EDGE: Final = 10
"""The shuffle tries this many target swaps per true edge."""

Edge = tuple[str, str]


@dataclass(frozen=True, slots=True)
class DagSpec:
    """One variant of the given DAG.

    Raises:
        ValueError: If the kind is unknown, a level is missing or outside (0, 1], or a kind
            without a level gets one
    """

    id: str
    kind: DagKind
    level: float | None = None
    """Target precision, target recall or the share of reversed edges; None for other kinds."""

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Unknown DAG kind {self.kind!r}")
        if self.kind in _KINDS_WITH_LEVEL:
            if self.level is None or not 0 < self.level <= 1:
                raise ValueError(f"A {self.kind} DAG needs a level in (0, 1], got {self.level!r}")
        elif self.level is not None:
            raise ValueError(f"A {self.kind} DAG takes no level")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "level": self.level}


STANDARD_DAGS: Final[tuple[DagSpec, ...]] = (
    DagSpec("true", "true"),
    DagSpec("precision-0.8", "precision", 0.8),
    DagSpec("precision-0.6", "precision", 0.6),
    DagSpec("recall-0.8", "recall", 0.8),
    DagSpec("recall-0.6", "recall", 0.6),
    DagSpec("reversed-0.1", "reversed", 0.1),
    DagSpec("reversed-0.2", "reversed", 0.2),
    DagSpec("chapter-chain", "chapter_chain"),
    DagSpec("none", "none"),
    DagSpec("degree-shuffle", "degree_shuffle"),
)
"""The levels of the design note's policy-DAG axis."""


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _descendants(graph: ConceptGraph) -> dict[str, set[str]]:
    """For every concept, the concepts a path of true edges leads to."""
    reached: dict[str, set[str]] = {concept: set() for concept in graph.concepts}
    # Reverse book order: a concept's dependents are complete before it is handled.
    for source, target in reversed(graph.edges):
        reached[source].add(target)
        reached[source] |= reached[target]
    return reached


def _false_edge_pool(graph: ConceptGraph) -> list[Edge]:
    """Forward pairs that no path of true edges joins, in book order."""
    reached = _descendants(graph)
    return [
        (source, target)
        for position, source in enumerate(graph.concepts)
        for target in graph.concepts[position + 1 :]
        if target not in reached[source]
    ]


def _false_edge_count(true_count: int, level: float) -> int:
    """How many false edges bring the precision nearest to ``level``; the fewer on a tie."""
    if true_count == 0:
        return 0
    fewer = math.floor(true_count * (1 - level) / level)

    def miss(false_count: int) -> float:
        return abs(true_count / (true_count + false_count) - level)

    return fewer + 1 if miss(fewer + 1) < miss(fewer) else fewer


def _with_false_edges(graph: ConceptGraph, level: float, seed: int, key: str) -> list[Edge]:
    wanted = _false_edge_count(len(graph.edges), level)
    pool = _false_edge_pool(graph)
    if wanted > len(pool):
        raise ValueError(
            f"Precision {level} needs {wanted} false edges, the graph has room for {len(pool)}"
        )
    return [*graph.edges, *draw_sample(pool, wanted, stream(seed, 0, "dag", key))]


def _with_removed_edges(graph: ConceptGraph, level: float, seed: int, key: str) -> list[Edge]:
    kept = _round_half_up(len(graph.edges) * level)
    return draw_sample(graph.edges, kept, stream(seed, 0, "dag", key))


def _with_reversed_edges(graph: ConceptGraph, level: float, seed: int, key: str) -> list[Edge]:
    count = _round_half_up(len(graph.edges) * level)
    turned = set(draw_sample(graph.edges, count, stream(seed, 0, "dag", key)))
    return [
        (target, source) if (source, target) in turned else (source, target)
        for source, target in graph.edges
    ]


def _chapter_chain(graph: ConceptGraph) -> list[Edge]:
    return [
        (previous[-1], concept)
        for previous, chapter in zip(graph.chapters, graph.chapters[1:], strict=False)
        for concept in chapter
    ]


def _degree_shuffle(graph: ConceptGraph, seed: int, key: str) -> list[Edge]:
    edges = list(graph.edges)
    present = set(edges)
    rng = stream(seed, 0, "dag", key)
    for _ in range(SHUFFLE_SWAPS_PER_EDGE * len(edges)):
        first = int(rng.random() * len(edges))
        second = int(rng.random() * len(edges))
        (a, b), (c, d) = edges[first], edges[second]
        swapped = ((a, d), (c, b))
        if any(
            edge in present or graph.position(edge[0]) >= graph.position(edge[1])
            for edge in swapped
        ):
            continue
        present -= {(a, b), (c, d)}
        present |= set(swapped)
        edges[first], edges[second] = swapped
    return edges


_LEVEL_BUILDERS: Final[Mapping[str, Callable[[ConceptGraph, float, int, str], list[Edge]]]] = {
    "precision": _with_false_edges,
    "recall": _with_removed_edges,
    "reversed": _with_reversed_edges,
}


def given_dag(graph: ConceptGraph, spec: DagSpec, seed: int) -> tuple[EdgeUse, ...]:
    """
    The edges a policy is given for one variant.

    Args:
        graph: The true graph
        spec: The variant
        seed: Seed of the variant's draws; kinds without a draw ignore it

    Returns:
        The edges sorted by the book positions of prerequisite and dependent, each with the
        provenance ``sim:<spec.id>``

    Raises:
        ValueError: If a precision level needs more false edges than the graph has room for
    """
    edges: Iterable[Edge] = ()  # kind "none"
    if spec.kind == "true":
        edges = graph.edges
    elif spec.kind == "chapter_chain":
        edges = _chapter_chain(graph)
    elif spec.kind == "degree_shuffle":
        edges = _degree_shuffle(graph, seed, spec.id)
    elif spec.level is not None:  # precision, recall, reversed: DagSpec requires their level
        edges = _LEVEL_BUILDERS[spec.kind](graph, spec.level, seed, spec.id)

    provenance = f"sim:{spec.id}"
    ordered = sorted(edges, key=lambda edge: (graph.position(edge[0]), graph.position(edge[1])))
    return tuple(EdgeUse(source, target, RELATION, provenance) for source, target in ordered)


def true_dag(graph: ConceptGraph) -> tuple[EdgeUse, ...]:
    """The true edges with the provenance ``sim:true``: what the oracle is given."""
    return given_dag(graph, DagSpec("true", "true"), 0)


def precision_recall(
    given: Iterable[EdgeUse], graph: ConceptGraph
) -> tuple[float | None, float | None]:
    """Precision and recall of a given edge set against the true edges.

    Precision is None for an empty edge set and recall is None for a graph without edges.
    """
    pairs = {(edge.source, edge.target) for edge in given}
    true_edges = set(graph.edges)
    hits = len(pairs & true_edges)
    precision = hits / len(pairs) if pairs else None
    recall = hits / len(true_edges) if true_edges else None
    return precision, recall
