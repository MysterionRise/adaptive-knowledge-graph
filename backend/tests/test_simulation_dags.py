"""
Property tests for the DAG a policy is given (#307).

``backend/app/student/simulation/dags.py`` builds each variant of the design note's
policy-DAG axis from the true graph, a spec and a seed. Every property is checked for the
seeds 0 to 19 on two graphs: the hand-written fixture and a seeded book of four chapters.

| Variant        | Property                                                                |
| -------------- | ----------------------------------------------------------------------- |
| true           | The true edges                                                          |
| precision      | Every true edge is kept (recall 1); the false edges are counted, point  |
|                | forward and join no pair that a true path joins                         |
| recall         | Only true edges (precision 1); the count kept                           |
| reversed       | The count turned round; every other edge untouched                      |
| chapter chain  | Only from the last concept of a chapter to the concepts of the next     |
| none           | No edge                                                                 |
| degree shuffle | Every in-degree and out-degree of the true DAG; no cycle                |
| all            | The same seed gives the same edges; every edge carries its provenance   |

Precision and recall are not crossed here: a precision variant has recall 1 and a recall
variant has precision 1.
"""

import math
from collections import Counter

import pytest

from backend.app.student.policy.base import EdgeUse
from backend.app.student.simulation.dags import (
    RELATION,
    STANDARD_DAGS,
    DagSpec,
    given_dag,
    precision_recall,
    true_dag,
)
from backend.app.student.simulation.worlds import FIXTURE_GRAPH, ConceptGraph, synthetic_graph

pytestmark = pytest.mark.unit

SEEDS = range(20)
BOOK = synthetic_graph(4, 4, 1.5, 1)  # 16 concepts, 22 edges
GRAPHS = {"fixture": FIXTURE_GRAPH, "book": BOOK}

graphs = pytest.mark.parametrize("graph", GRAPHS.values(), ids=GRAPHS.keys())


def _pairs(edges: tuple[EdgeUse, ...]) -> list[tuple[str, str]]:
    return [(edge.source, edge.target) for edge in edges]


def _half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _joined_by_a_true_path(graph: ConceptGraph, source: str, target: str) -> bool:
    """Depth-first search along the true edges, written apart from the module under test."""
    stack, seen = [source], set()
    while stack:
        concept = stack.pop()
        for start, end in graph.edges:
            if start == concept and end not in seen:
                if end == target:
                    return True
                seen.add(end)
                stack.append(end)
    return False


def _has_cycle(concepts: tuple[str, ...], pairs: list[tuple[str, str]]) -> bool:
    """Kahn's algorithm: a cycle is left when no concept without prerequisites remains."""
    remaining = set(pairs)
    waiting = set(concepts)
    while waiting:
        free = {c for c in waiting if not any(target == c for _, target in remaining)}
        if not free:
            return True
        waiting -= free
        remaining = {(source, target) for source, target in remaining if source not in free}
    return False


# ---------------------------------------------------------------------------
# The axis and its specs
# ---------------------------------------------------------------------------


def test_standard_dags_are_the_levels_of_the_design_note():
    by_kind: dict[str, list[float | None]] = {}
    for spec in STANDARD_DAGS:
        by_kind.setdefault(spec.kind, []).append(spec.level)

    assert {kind: sorted(levels, key=str) for kind, levels in by_kind.items()} == {
        "true": [None],
        "precision": [0.6, 0.8],
        "recall": [0.6, 0.8],
        "reversed": [0.1, 0.2],
        "chapter_chain": [None],
        "none": [None],
        "degree_shuffle": [None],
    }
    assert len({spec.id for spec in STANDARD_DAGS}) == len(STANDARD_DAGS) == 10


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("x", "upside_down"), "Unknown DAG kind"),
        (("x", "precision"), "needs a level"),
        (("x", "recall", 0.0), "needs a level"),
        (("x", "reversed", 1.5), "needs a level"),
        (("x", "precision", -0.2), "needs a level"),
        (("x", "true", 0.8), "takes no level"),
        (("x", "none", 0.5), "takes no level"),
        (("x", "chapter_chain", 1.0), "takes no level"),
        (("x", "degree_shuffle", 0.1), "takes no level"),
    ],
)
def test_dag_spec_rejects_a_wrong_kind_or_level(arguments, message):
    with pytest.raises(ValueError, match=message):
        DagSpec(*arguments)


def test_dag_spec_echoes_its_parameters():
    assert DagSpec("precision-0.8", "precision", 0.8).to_dict() == {
        "id": "precision-0.8",
        "kind": "precision",
        "level": 0.8,
    }
    assert DagSpec("none", "none").to_dict() == {"id": "none", "kind": "none", "level": None}


# ---------------------------------------------------------------------------
# Every variant
# ---------------------------------------------------------------------------


@graphs
@pytest.mark.parametrize("spec", STANDARD_DAGS, ids=lambda spec: spec.id)
def test_variant_is_deterministic_sorted_and_carries_its_provenance(graph, spec):
    for seed in SEEDS:
        edges = given_dag(graph, spec, seed)

        assert edges == given_dag(graph, spec, seed)
        assert all(isinstance(edge, EdgeUse) for edge in edges)
        assert {edge.provenance for edge in edges} <= {f"sim:{spec.id}"}
        assert {edge.relation for edge in edges} <= {RELATION} == {"PREREQ"}
        assert len(set(_pairs(edges))) == len(edges)  # no edge twice
        assert all(edge.source != edge.target for edge in edges)
        assert {c for pair in _pairs(edges) for c in pair} <= set(graph.concepts)
        keys = [
            (graph.position(source), graph.position(target)) for source, target in _pairs(edges)
        ]
        assert keys == sorted(keys)


@graphs
@pytest.mark.parametrize(
    "spec",
    [
        spec
        for spec in STANDARD_DAGS
        if spec.kind in ("precision", "recall", "reversed", "degree_shuffle")
    ],
    ids=lambda spec: spec.id,
)
def test_drawn_variants_depend_on_the_seed(graph, spec):
    variants = {given_dag(graph, spec, seed) for seed in SEEDS}

    assert len(variants) > 5


@graphs
@pytest.mark.parametrize(
    "spec",
    [spec for spec in STANDARD_DAGS if spec.kind in ("true", "chapter_chain", "none")],
    ids=lambda spec: spec.id,
)
def test_variants_without_a_draw_ignore_the_seed(graph, spec):
    assert len({given_dag(graph, spec, seed) for seed in SEEDS}) == 1


def test_a_variant_s_draw_is_keyed_by_its_id():
    """The same kind and level under another id is another draw of the same size."""
    first = set(_pairs(given_dag(BOOK, DagSpec("recall-0.6", "recall", 0.6), 0)))
    renamed = set(_pairs(given_dag(BOOK, DagSpec("other-name", "recall", 0.6), 0)))

    assert renamed != first
    assert len(renamed) == len(first)


# ---------------------------------------------------------------------------
# true, none
# ---------------------------------------------------------------------------


@graphs
def test_true_dag_is_the_true_edges(graph):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec("true", "true"), seed)

        assert tuple(_pairs(edges)) == graph.edges
        assert precision_recall(edges, graph) == (1.0, 1.0)
        assert true_dag(graph) == edges
        assert {edge.provenance for edge in true_dag(graph)} == {"sim:true"}


@graphs
def test_no_dag_is_empty(graph):
    for seed in SEEDS:
        assert given_dag(graph, DagSpec("none", "none"), seed) == ()
        assert precision_recall((), graph) == (None, 0.0)


# ---------------------------------------------------------------------------
# precision: false edges are added, true edges stay
# ---------------------------------------------------------------------------


@graphs
@pytest.mark.parametrize("level", [0.6, 0.8])
def test_precision_is_lowered_by_adding_false_edges_at_recall_one(graph, level):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec(f"precision-{level}", "precision", level), seed)
        pairs = set(_pairs(edges))
        true_count = len(graph.edges)
        # The number of false edges whose precision is nearest the level, found by trying all.
        false_count = min(range(200), key=lambda f: (abs(true_count / (true_count + f) - level), f))

        assert set(graph.edges) <= pairs  # no true edge was removed
        assert len(pairs) == true_count + false_count
        precision, recall = precision_recall(edges, graph)
        assert recall == 1.0
        assert precision == true_count / (true_count + false_count)
        # Whole edges: the target is missed by less than one false edge more or less would.
        assert abs(precision - level) < 0.04


@graphs
@pytest.mark.parametrize("level", [0.6, 0.8])
def test_false_edges_point_forward_and_join_unrelated_concepts(graph, level):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec(f"precision-{level}", "precision", level), seed)
        false_pairs = set(_pairs(edges)) - set(graph.edges)

        assert false_pairs
        for source, target in false_pairs:
            assert graph.position(source) < graph.position(target)
            assert not _joined_by_a_true_path(graph, source, target)
        assert not _has_cycle(graph.concepts, _pairs(edges))


def test_precision_one_adds_nothing():
    edges = given_dag(BOOK, DagSpec("precision-1", "precision", 1.0), 0)

    assert tuple(_pairs(edges)) == BOOK.edges


def test_precision_of_a_graph_without_edges_adds_nothing():
    """No true edge, so no number of false edges gives a precision above zero."""
    no_edges = ConceptGraph(concepts=("x", "y", "z"), chapters=(("x", "y", "z"),), edges=())

    assert given_dag(no_edges, DagSpec("precision-0.8", "precision", 0.8), 0) == ()


def test_precision_too_low_for_the_graph_is_an_error():
    """The fixture has room for 8 false edges; precision 0.3 would need 23."""
    with pytest.raises(ValueError, match="needs 23 false edges, the graph has room for 8"):
        given_dag(FIXTURE_GRAPH, DagSpec("precision-0.3", "precision", 0.3), 0)


# ---------------------------------------------------------------------------
# recall: true edges are removed, none is added
# ---------------------------------------------------------------------------


@graphs
@pytest.mark.parametrize("level", [0.6, 0.8])
def test_recall_is_lowered_by_removing_true_edges_at_precision_one(graph, level):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec(f"recall-{level}", "recall", level), seed)
        pairs = set(_pairs(edges))
        kept = _half_up(len(graph.edges) * level)

        assert pairs <= set(graph.edges)  # no false edge was added
        assert len(pairs) == kept
        precision, recall = precision_recall(edges, graph)
        assert precision == 1.0
        assert recall == kept / len(graph.edges)
        assert abs(recall - level) < 0.03


def test_recall_one_removes_nothing():
    edges = given_dag(BOOK, DagSpec("recall-1", "recall", 1.0), 0)

    assert tuple(_pairs(edges)) == BOOK.edges


def test_every_true_edge_is_removed_for_some_seed_and_kept_for_another():
    """Over the seeds, removal is not stuck on the same edges."""
    kept = Counter(
        pair
        for other in SEEDS
        for pair in _pairs(given_dag(FIXTURE_GRAPH, DagSpec("recall-0.6", "recall", 0.6), other))
    )

    assert set(kept) == set(FIXTURE_GRAPH.edges)
    assert max(kept.values()) < len(SEEDS)


# ---------------------------------------------------------------------------
# reversed
# ---------------------------------------------------------------------------


@graphs
@pytest.mark.parametrize("level", [0.1, 0.2])
def test_reversed_share_of_the_true_edges(graph, level):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec(f"reversed-{level}", "reversed", level), seed)
        pairs = set(_pairs(edges))
        true_edges = set(graph.edges)
        turned = pairs - true_edges
        count = _half_up(len(true_edges) * level)

        assert len(pairs) == len(true_edges)
        assert len(turned) == count >= 1
        assert all((target, source) in true_edges for source, target in turned)
        assert pairs - turned == true_edges - {(target, source) for source, target in turned}
        assert precision_recall(edges, graph) == (
            (len(true_edges) - count) / len(true_edges),
            (len(true_edges) - count) / len(true_edges),
        )


def test_reversed_edges_can_close_a_cycle():
    """The module says so; the policies must cope. Some seed turns a1 -> a2 or the like."""
    spec = DagSpec("reversed-0.2", "reversed", 0.2)

    cyclic = [
        seed
        for seed in range(200)
        if _has_cycle(BOOK.concepts, _pairs(given_dag(BOOK, spec, seed)))
    ]

    assert cyclic


# ---------------------------------------------------------------------------
# whole edges: a share that ends in a half is rounded up
# ---------------------------------------------------------------------------

FIVE_EDGE_CHAIN = ConceptGraph(
    concepts=("p1", "p2", "p3", "p4", "p5", "p6"),
    chapters=(("p1", "p2", "p3", "p4", "p5", "p6"),),
    edges=(("p1", "p2"), ("p2", "p3"), ("p3", "p4"), ("p4", "p5"), ("p5", "p6")),
)


@pytest.mark.parametrize(
    ("kind", "level", "changed"),
    [
        ("reversed", 0.1, 1),  # 0.5 of an edge: one is turned (rounding half to even: none)
        ("reversed", 0.5, 3),  # 2.5 (half to even: 2)
        ("reversed", 0.3, 2),  # 1.5
        ("recall", 0.5, 3),  # 2.5 edges are kept as 3 (half to even: 2)
        ("recall", 0.9, 5),  # 4.5 (half to even: 4)
        ("recall", 0.7, 4),  # 3.5
    ],
)
def test_half_an_edge_is_rounded_up(kind, level, changed):
    """The module's draft choice, at the shares of five edges that end in a half. The other
    DAG tests use 10 and 22 edges, where no standard level does."""
    for seed in SEEDS:
        pairs = set(_pairs(given_dag(FIVE_EDGE_CHAIN, DagSpec("half", kind, level), seed)))
        true_edges = set(FIVE_EDGE_CHAIN.edges)

        if kind == "reversed":
            assert len(pairs - true_edges) == changed
        else:
            assert len(pairs) == changed and pairs <= true_edges


# ---------------------------------------------------------------------------
# chapter chain
# ---------------------------------------------------------------------------


@graphs
def test_chapter_chain_links_consecutive_chapters_only(graph):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec("chapter-chain", "chapter_chain"), seed)
        chapter_of = {
            concept: number for number, chapter in enumerate(graph.chapters) for concept in chapter
        }

        assert len(edges) == len(graph.concepts) - len(graph.chapters[0])
        for source, target in _pairs(edges):
            assert chapter_of[target] == chapter_of[source] + 1
            assert source == graph.chapters[chapter_of[source]][-1]
        # Every concept after the first chapter has exactly one prerequisite.
        assert Counter(target for _, target in _pairs(edges)) == {
            concept: 1 for chapter in graph.chapters[1:] for concept in chapter
        }


def test_chapter_chain_of_the_fixture():
    edges = given_dag(FIXTURE_GRAPH, DagSpec("chapter-chain", "chapter_chain"), 0)

    assert _pairs(edges) == [
        ("a3", "b1"),
        ("a3", "b2"),
        ("a3", "b3"),
        ("b3", "c1"),
        ("b3", "c2"),
        ("b3", "c3"),
    ]
    assert precision_recall(edges, FIXTURE_GRAPH) == (2 / 6, 2 / 10)


def test_chapter_chain_of_one_chapter_is_empty():
    one = ConceptGraph(concepts=("x", "y"), chapters=(("x", "y"),), edges=(("x", "y"),))

    assert given_dag(one, DagSpec("chapter-chain", "chapter_chain"), 0) == ()


# ---------------------------------------------------------------------------
# degree-preserving shuffle
# ---------------------------------------------------------------------------


@graphs
def test_shuffle_keeps_every_in_and_out_degree_and_stays_acyclic(graph):
    for seed in SEEDS:
        edges = given_dag(graph, DagSpec("degree-shuffle", "degree_shuffle"), seed)
        pairs = _pairs(edges)

        assert len(pairs) == len(set(pairs)) == len(graph.edges)
        assert Counter(source for source, _ in pairs) == Counter(
            source for source, _ in graph.edges
        )
        assert Counter(target for _, target in pairs) == Counter(
            target for _, target in graph.edges
        )
        assert not _has_cycle(graph.concepts, pairs)
        assert all(graph.position(source) < graph.position(target) for source, target in pairs)


@graphs
def test_shuffle_rewires_the_graph_for_most_seeds(graph):
    rewired = [
        seed
        for seed in SEEDS
        if set(_pairs(given_dag(graph, DagSpec("degree-shuffle", "degree_shuffle"), seed)))
        != set(graph.edges)
    ]

    assert len(rewired) >= 15


def test_shuffle_of_a_graph_without_a_legal_swap_is_the_graph():
    chain = ConceptGraph(
        concepts=("x", "y", "z"), chapters=(("x", "y", "z"),), edges=(("x", "y"), ("y", "z"))
    )
    empty = ConceptGraph(concepts=("x", "y"), chapters=(("x", "y"),), edges=())

    for seed in SEEDS:
        shuffled = given_dag(chain, DagSpec("degree-shuffle", "degree_shuffle"), seed)
        assert tuple(_pairs(shuffled)) == chain.edges
        assert given_dag(empty, DagSpec("degree-shuffle", "degree_shuffle"), seed) == ()


# ---------------------------------------------------------------------------
# precision_recall
# ---------------------------------------------------------------------------


def test_precision_and_recall_against_the_true_edges():
    given = (
        EdgeUse("a1", "a2", RELATION, "test"),  # true
        EdgeUse("a2", "b1", RELATION, "test"),  # true
        EdgeUse("b1", "a1", RELATION, "test"),  # false
        EdgeUse("a2", "a3", RELATION, "test"),  # false
    )

    assert precision_recall(given, FIXTURE_GRAPH) == (0.5, 0.2)


def test_precision_and_recall_without_edges():
    no_edges = ConceptGraph(concepts=("x", "y"), chapters=(("x", "y"),), edges=())

    assert precision_recall((), FIXTURE_GRAPH) == (None, 0.0)
    assert precision_recall((), no_edges) == (None, None)
    assert precision_recall((EdgeUse("x", "y", RELATION, "test"),), no_edges) == (0.0, None)


def test_helpers_of_this_module_find_a_cycle_and_a_path():
    """The checks above rest on these two helpers, so they are checked on known cases."""
    assert _has_cycle(("x", "y"), [("x", "y"), ("y", "x")])
    assert not _has_cycle(("x", "y", "z"), [("x", "y"), ("y", "z"), ("x", "z")])
    assert _joined_by_a_true_path(FIXTURE_GRAPH, "a1", "c3")
    assert not _joined_by_a_true_path(FIXTURE_GRAPH, "a2", "b2")
    assert not _joined_by_a_true_path(FIXTURE_GRAPH, "c3", "a1")
