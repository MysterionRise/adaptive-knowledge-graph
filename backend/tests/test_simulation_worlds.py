"""
Tests for the simulator's worlds: graphs, random streams, learners (#307).

``backend/app/student/simulation/worlds.py`` states the assumptions of the core world as A1
to A8. The tests pin them with hand-computed values:

| Assumption                         | Checked by                                            |
| ---------------------------------- | ----------------------------------------------------- |
| A1 response, no item difficulty    | bounds, monotonicity, the three bands give one value  |
| A2 learning                        | one step by hand; the skill never falls or passes 1   |
| A3 gate: none, weak, strong, leak  | hand-computed gates; the weakest prerequisite decides |
| A4 contradicting learners          | gate 1; the learners of seed 307 by index             |
| A5 heterogeneous rates             | the range and the spread                              |
| A6 initial skill                   | the draw times the ceiling times the gate             |
| A7 no forgetting                   | the delay changes nothing                             |

They also pin the random streams: one place builds a generator, a stream depends on each of
its four inputs, and the k-th answer on a concept uses the same draw whatever was practised
in between (common random numbers).

The source checks at the end hold the whole package to its constraints: no clock, no
environment, no exponential or logarithm, no built-in ``sum``.
"""

import ast
import copy
import pickle
import random
import sys
from dataclasses import FrozenInstanceError, replace
from functools import cache
from pathlib import Path

import pytest

from backend.app.student.simulation import worlds
from backend.app.student.simulation.worlds import (
    FIXTURE_GRAPH,
    PREREQ_STRENGTHS,
    ConceptGraph,
    Learner,
    World,
    WorldSpec,
    draw_sample,
    stream,
    stream_seed,
    synthetic_graph,
)

pytestmark = pytest.mark.unit

SEED = 307
TOLERANCE = 1e-12
PACKAGE_DIR = Path(worlds.__file__).resolve().parent
PACKAGE_MODULES = sorted(path.name for path in PACKAGE_DIR.glob("*.py"))


@cache
def _trees() -> dict[str, ast.Module]:
    return {
        module: ast.parse((PACKAGE_DIR / module).read_text(encoding="utf-8"))
        for module in PACKAGE_MODULES
    }


def _spec(strength: str = "strong", **changes: object) -> WorldSpec:
    values: dict[str, object] = {
        "id": strength,
        "prereq_strength": strength,
        "leak": 0.1,
        "contradicting_share": 0.2,
        "learning_rate_range": (0.5, 1.5),
        "base_gain": 0.3,
        "guess": 0.25,
        "slip": 0.1,
        "initial_skill_max": 0.3,
    }
    values.update(changes)
    return WorldSpec(**values)


def _world(strength: str = "strong", **changes: object) -> World:
    return World(_spec(strength, **changes), FIXTURE_GRAPH)


def _learner(world: World, index: int = 0) -> Learner:
    return Learner(world, world.traits(SEED, index), SEED)


# ---------------------------------------------------------------------------
# Random streams
# ---------------------------------------------------------------------------


def test_stream_is_reproducible_and_pinned():
    """The literal is the same on every Python version: an integer seed and ``random()``."""
    first = stream(SEED, 0, "traits")
    second = stream(SEED, 0, "traits")

    assert stream_seed(SEED, 0, "traits") == 12393262334832495163
    assert [first.random() for _ in range(3)] == [second.random() for _ in range(3)]
    assert stream(SEED, 0, "traits").random() == 0.36992643232042155


@pytest.mark.parametrize(
    "other",
    [
        (308, 0, "traits", ""),
        (SEED, 1, "traits", ""),
        (SEED, 0, "response", ""),
        (SEED, 0, "traits", "a1"),
    ],
    ids=["master-seed", "learner-index", "purpose", "key"],
)
def test_stream_depends_on_each_of_its_four_inputs(other):
    base = (SEED, 0, "traits", "")

    assert stream_seed(*other) != stream_seed(*base)
    assert stream(*other).random() != stream(*base).random()


def test_streams_of_different_learners_are_all_different():
    seeds = {stream_seed(SEED, index, "traits") for index in range(1000)}
    firsts = {stream(SEED, index, "traits").random() for index in range(200)}

    assert len(seeds) == 1000
    assert len(firsts) == 200


def test_stream_seed_is_64_bits_of_a_digest_and_separates_its_fields():
    assert 0 <= stream_seed(SEED, 0, "traits") < 2**64
    # 1 and 12 against 11 and 2: the separator keeps the two integers apart.
    assert stream_seed(1, 12, "x") != stream_seed(11, 2, "x")
    assert stream_seed(SEED, 0, "a", "b:c") != stream_seed(SEED, 0, "a", "b")


@pytest.mark.parametrize("arguments", [(3.0, 0), (SEED, "0"), (True, 0), (SEED, None)])
def test_stream_seed_needs_integers(arguments):
    with pytest.raises(TypeError, match="must be an int"):
        stream_seed(*arguments, "traits")


def test_stream_purpose_must_not_hold_the_separator():
    with pytest.raises(ValueError, match="colon"):
        stream_seed(SEED, 0, "traits:a1")


def test_the_package_builds_a_generator_in_one_place_only():
    """One call of ``random.Random``, inside ``stream``; no module-level random functions."""
    constructions = []
    other_random_use = []
    for module, tree in _trees().items():
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "random"
                ):
                    if node.func.attr == "Random":
                        constructions.append((module, function.name))
                    else:
                        other_random_use.append((module, function.name, node.func.attr))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "random":
                other_random_use.append((module, "import", "from random import"))
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = {alias.name.split(".")[0] for alias in node.names}
                module_name = (getattr(node, "module", None) or "").split(".")[0]
                assert not {"secrets", "numpy", "uuid"} & (names | {module_name}), module

    assert constructions == [("worlds.py", "stream")]
    assert other_random_use == []


def test_only_random_is_called_on_a_stream():
    """Methods of a generator that the package calls: ``random`` and nothing else."""
    generator_methods = {name for name in dir(random.Random) if not name.startswith("_")}
    called = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    assert called & generator_methods == {"random"}


class _OnlyRandom:
    """A generator that offers ``random()`` and nothing else."""

    def __init__(self) -> None:
        self._rng = random.Random(SEED)

    def random(self) -> float:
        return self._rng.random()


def test_draw_sample_is_a_seeded_draw_without_replacement():
    pool = list(range(20))

    first = draw_sample(pool, 7, _OnlyRandom())
    second = draw_sample(pool, 7, _OnlyRandom())

    assert first == second
    assert len(set(first)) == 7 and set(first) <= set(pool)
    assert pool == list(range(20))  # the pool is not changed
    assert sorted(draw_sample(pool, 20, stream(SEED, 0, "t"))) == pool
    assert draw_sample(pool, 0, stream(SEED, 0, "t")) == []
    assert len({tuple(draw_sample(pool, 3, stream(seed, 0, "t"))) for seed in range(20)}) > 10


@pytest.mark.parametrize("count", [-1, 4])
def test_draw_sample_rejects_impossible_counts(count):
    with pytest.raises(ValueError, match="Cannot draw"):
        draw_sample([1, 2, 3], count, stream(SEED, 0, "t"))


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------


def test_fixture_graph_is_three_chapters_of_three_with_ten_edges():
    graph = FIXTURE_GRAPH

    assert graph.concepts == ("a1", "a2", "a3", "b1", "b2", "b3", "c1", "c2", "c3")
    assert [len(chapter) for chapter in graph.chapters] == [3, 3, 3]
    assert len(graph.edges) == 10
    assert [c for c in graph.concepts if not graph.prerequisites(c)] == ["a1"]
    assert graph.prerequisites("b3") == ("b1", "b2")
    assert graph.prerequisites("c3") == ("c1", "c2")
    assert graph.slice == graph.concepts
    assert graph.position("a1") == 0 and graph.position("c3") == 8


def test_graph_stores_edges_once_and_in_book_order():
    graph = ConceptGraph(
        concepts=("x", "y", "z"),
        chapters=(("x", "y"), ("z",)),
        edges=[("y", "z"), ("x", "z"), ("x", "y"), ("x", "z")],
    )

    assert graph.edges == (("x", "y"), ("x", "z"), ("y", "z"))
    assert graph.prerequisites("z") == ("x", "y")
    assert graph.to_dict() == {
        "chapters": [["x", "y"], ["z"]],
        "edges": [["x", "y"], ["x", "z"], ["y", "z"]],
        "slice": ["x", "y", "z"],
    }


def test_graph_slice_is_kept_in_book_order():
    graph = replace(FIXTURE_GRAPH, slice=("c1", "a2"))

    assert graph.slice == ("a2", "c1")
    assert graph.to_dict()["slice"] == ["a2", "c1"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"concepts": ()}, "at least one concept"),
        ({"concepts": ("x", "x", "z"), "chapters": (("x", "x"), ("z",))}, "no concept twice"),
        ({"chapters": (("x",), ("z", "y"))}, "in book order"),
        ({"chapters": (("x", "y", "z"), ())}, "none empty"),
        ({"chapters": (("x", "y"),)}, "in book order"),
        ({"edges": (("x", "w"),)}, "unknown concept"),
        ({"edges": (("w", "x"),)}, "unknown concept"),
        ({"edges": (("z", "x"),)}, "forward in book order"),
        ({"edges": (("y", "y"),)}, "forward in book order"),
        ({"slice": ("x", "w")}, "slice names unknown"),
    ],
)
def test_graph_rejects_what_is_not_a_book_with_forward_edges(changes, message):
    values: dict[str, object] = {
        "concepts": ("x", "y", "z"),
        "chapters": (("x", "y"), ("z",)),
        "edges": (("x", "y"),),
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        ConceptGraph(**values)


def test_graph_survives_pickling_and_copying():
    for clone in (pickle.loads(pickle.dumps(FIXTURE_GRAPH)), copy.deepcopy(FIXTURE_GRAPH)):
        assert clone == FIXTURE_GRAPH
        assert clone.position("c3") == 8
        assert clone.prerequisites("c3") == ("c1", "c2")


def test_graph_is_frozen_and_hashable():
    with pytest.raises(FrozenInstanceError):
        FIXTURE_GRAPH.edges = ()
    assert hash(FIXTURE_GRAPH) == hash(replace(FIXTURE_GRAPH))
    assert FIXTURE_GRAPH == replace(FIXTURE_GRAPH)


def test_synthetic_graph_is_seeded_and_local():
    graph = synthetic_graph(8, 5, 1.5, SEED)
    again = synthetic_graph(8, 5, 1.5, SEED)

    assert graph == again
    assert graph != synthetic_graph(8, 5, 1.5, SEED + 1)
    assert len(graph.concepts) == 40
    assert graph.concepts[:6] == ("c1.1", "c1.2", "c1.3", "c1.4", "c1.5", "c2.1")
    assert [len(chapter) for chapter in graph.chapters] == [5] * 8
    assert len(graph.edges) == 55  # about 1.5 for each of the 39 concepts after the first
    assert graph.slice == graph.concepts
    for source, target in graph.edges:
        distance = graph.position(target) - graph.position(source)
        assert 1 <= distance <= 10  # the same or the previous two chapters' worth of concepts


def test_synthetic_graph_parent_counts():
    """``parents`` 2 gives every concept two prerequisites, or all the earlier ones."""
    for seed in range(20):
        graph = synthetic_graph(3, 4, 2, seed)
        mixed = synthetic_graph(3, 4, 1.5, seed)

        assert [len(graph.prerequisites(c)) for c in graph.concepts] == [0, 1] + [2] * 10
        assert {len(mixed.prerequisites(c)) for c in mixed.concepts[2:]} <= {1, 2}
        assert synthetic_graph(3, 4, 0, seed).edges == ()


@pytest.mark.parametrize("arguments", [(0, 5, 1.5), (8, 0, 1.5), (8, 5, -0.5)])
def test_synthetic_graph_rejects_impossible_sizes(arguments):
    with pytest.raises(ValueError, match="at least"):
        synthetic_graph(*arguments, SEED)


# ---------------------------------------------------------------------------
# World parameters
# ---------------------------------------------------------------------------


def test_prerequisite_strengths_are_none_weak_strong():
    assert dict(PREREQ_STRENGTHS) == {"none": 0.0, "weak": 0.5, "strong": 1.0}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"prereq_strength": "medium"}, "Unknown prerequisite strength"),
        ({"learning_rate_range": (0.0, 1.0)}, "must be positive"),
        ({"learning_rate_range": (1.5, 0.5)}, "lowest first"),
        ({"base_gain": 0.0}, "base_gain"),
        ({"base_gain": 0.7}, "at most 1 at the highest rate"),
        ({"leak": -0.1}, "leak must lie in"),
        ({"leak": 1.1}, "leak must lie in"),
        ({"contradicting_share": 1.5}, "contradicting_share must lie in"),
        ({"initial_skill_max": -0.2}, "initial_skill_max must lie in"),
        ({"guess": -0.1}, "guess and slip"),
        ({"slip": -0.1}, "guess and slip"),
        ({"guess": 0.6, "slip": 0.4}, "less than 1"),
    ],
)
def test_world_spec_rejects_values_outside_their_range(changes, message):
    with pytest.raises(ValueError, match=message):
        _spec(**changes)


def test_world_spec_echoes_its_parameters():
    assert _spec("weak").to_dict() == {
        "id": "weak",
        "prereq_strength": "weak",
        "leak": 0.1,
        "contradicting_share": 0.2,
        "learning_rate_range": [0.5, 1.5],
        "base_gain": 0.3,
        "guess": 0.25,
        "slip": 0.1,
        "initial_skill_max": 0.3,
    }


def test_world_family_is_not_bkt():
    assert World.family == "gated-continuous-growth-v1"
    assert "bkt" not in World.family


# ---------------------------------------------------------------------------
# A3, A4: the gate
# ---------------------------------------------------------------------------

# Skill per concept in book order: a1 0.5, a2 0.2, a3 0.0, b1 1.0, b2 0.6, the rest 0.
SKILL = (0.5, 0.2, 0.0, 1.0, 0.6, 0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("strength", "concept", "expected"),
    [
        # strong: 1 - 0.9 * (1 - weakest)
        ("strong", "a1", 1.0),  # no prerequisite
        ("strong", "a2", 0.55),  # a1 at 0.5
        ("strong", "b1", 0.28),  # a2 at 0.2
        ("strong", "b2", 0.1),  # a3 at 0: only the leak gets through
        ("strong", "b3", 0.64),  # b1 at 1.0 and b2 at 0.6: the weakest decides
        ("strong", "c1", 1.0),  # b1 at 1.0: the gate is open
        # weak: 1 - 0.5 * 0.9 * (1 - weakest)
        ("weak", "a2", 0.775),
        ("weak", "b2", 0.55),
        ("weak", "b3", 0.82),
        # none: prerequisites do not matter
        ("none", "a2", 1.0),
        ("none", "b2", 1.0),
    ],
)
def test_gate_by_prerequisite_strength(strength, concept, expected):
    assert _world(strength).gate(SKILL, concept, False) == pytest.approx(expected, abs=TOLERANCE)


def test_gate_with_another_leak():
    assert _world("strong", leak=0.0).gate(SKILL, "b2", False) == 0.0
    assert _world("strong", leak=0.4).gate(SKILL, "b2", False) == pytest.approx(0.4, abs=TOLERANCE)
    assert _world("strong", leak=1.0).gate(SKILL, "b2", False) == 1.0
    assert _world("weak", leak=0.4).gate(SKILL, "b2", False) == pytest.approx(0.7, abs=TOLERANCE)


@pytest.mark.parametrize("strength", ["none", "weak", "strong"])
def test_contradicting_learners_are_never_gated(strength):
    world = _world(strength)

    for concept in FIXTURE_GRAPH.concepts:
        assert world.gate(SKILL, concept, True) == 1.0
        assert world.gate((0.0,) * 9, concept, True) == 1.0


def test_stronger_prerequisites_close_the_gate_further():
    gates = [_world(strength).gate(SKILL, "b1", False) for strength in ("none", "weak", "strong")]

    assert gates[0] > gates[1] > gates[2] > 0


# ---------------------------------------------------------------------------
# A4, A5, A6: traits
# ---------------------------------------------------------------------------


def test_traits_are_the_same_on_every_call():
    world = _world()

    assert world.traits(SEED, 3) == world.traits(SEED, 3)
    assert world.traits(SEED, 3) != world.traits(SEED, 4)
    assert world.traits(SEED, 3) != world.traits(SEED + 1, 3)
    assert world.traits(SEED, 3).index == 3


def test_contradicting_learners_of_seed_307():
    """With a share of 0.2: four of the first 24 learners and 197 of the first 1000."""
    world = _world()
    first = [world.traits(SEED, index) for index in range(24)]

    assert [traits.index for traits in first if traits.contradicts_dag] == [10, 15, 18, 21]
    assert len([i for i in range(1000) if world.traits(SEED, i).contradicts_dag]) == 197


def test_contradicting_share_of_zero_and_one():
    nobody = _world(contradicting_share=0.0)
    everybody = _world(contradicting_share=1.0)

    assert not any(nobody.traits(SEED, index).contradicts_dag for index in range(200))
    assert all(everybody.traits(SEED, index).contradicts_dag for index in range(200))


def test_learning_rates_are_heterogeneous_and_inside_the_range():
    world = _world(learning_rate_range=(0.5, 1.5))
    rates = [world.traits(SEED, index).learning_rate for index in range(1000)]

    assert world.traits(SEED, 0).learning_rate == pytest.approx(0.5 + 0.36992643232042155)
    assert 0.5 <= min(rates) < 0.51
    assert 1.49 < max(rates) <= 1.5
    assert len(set(rates)) == 1000
    assert all(
        _world(learning_rate_range=(0.8, 0.8)).traits(SEED, i).learning_rate == 0.8
        for i in range(20)
    )


def test_a_learner_is_the_same_person_in_every_world():
    """The stream is read in a fixed order, so strength changes the gated skills only."""
    none, strong = _world("none").traits(SEED, 0), _world("strong").traits(SEED, 0)

    assert none.learning_rate == strong.learning_rate
    assert none.contradicts_dag == strong.contradicts_dag
    assert none.initial_skill[0] == strong.initial_skill[0]  # a1 has no prerequisite
    assert all(a >= b for a, b in zip(none.initial_skill, strong.initial_skill, strict=True))
    assert none.initial_skill != strong.initial_skill


def test_initial_skill_is_the_draw_times_the_ceiling_times_the_gate():
    """Learner 0, by hand from the learner's stream: rate, contradiction, then the concepts."""
    world = _world("strong")
    draws = stream(SEED, 0, "traits")
    draws.random(), draws.random()
    traits = world.traits(SEED, 0)

    a1 = draws.random() * 0.3  # no prerequisite: gate 1
    a2 = draws.random() * 0.3 * (1 - 0.9 * (1 - a1))  # a1 is the prerequisite
    a3 = draws.random() * 0.3 * (1 - 0.9 * (1 - a1))

    assert not traits.contradicts_dag
    assert traits.initial_skill[:3] == pytest.approx((a1, a2, a3), abs=TOLERANCE)
    assert traits.initial_skill[0] == pytest.approx(0.013135280516773495, abs=TOLERANCE)


def test_initial_skill_of_a_contradicting_learner_ignores_the_dag():
    gated = _world("strong", contradicting_share=0.0).traits(SEED, 0)
    free = _world("strong", contradicting_share=1.0).traits(SEED, 0)
    draws = stream(SEED, 0, "traits")
    draws.random(), draws.random()

    assert free.contradicts_dag and not gated.contradicts_dag
    assert free.initial_skill == pytest.approx([draws.random() * 0.3 for _ in range(9)])
    assert all(a > b for a, b in zip(free.initial_skill[1:], gated.initial_skill[1:], strict=True))


@pytest.mark.parametrize("strength", ["none", "weak", "strong"])
def test_initial_skill_stays_under_its_ceiling(strength):
    world = _world(strength, initial_skill_max=0.3)

    for index in range(200):
        assert all(0.0 <= skill < 0.3 for skill in world.traits(SEED, index).initial_skill)
    assert set(_world(strength, initial_skill_max=0.0).traits(SEED, 0).initial_skill) == {0.0}


# ---------------------------------------------------------------------------
# A1, A7: responses
# ---------------------------------------------------------------------------


def test_p_correct_runs_from_guess_to_one_minus_slip():
    world = _world(guess=0.25, slip=0.1)

    assert world.p_correct(0.0) == 0.25
    assert world.p_correct(1.0) == pytest.approx(0.9, abs=TOLERANCE)
    assert world.p_correct(0.5) == pytest.approx(0.575, abs=TOLERANCE)
    grid = [world.p_correct(k / 100) for k in range(101)]
    assert all(low < high for low, high in zip(grid, grid[1:], strict=False))
    assert all(0.25 <= p <= 0.9 + TOLERANCE for p in grid)


def test_item_difficulty_changes_nothing_in_the_core_world():
    learner = _learner(_world())

    for concept in FIXTURE_GRAPH.concepts:
        values = {learner.p_correct(concept, band) for band in ("easy", "medium", "hard")}
        assert values == {learner.p_correct(concept)}


def test_two_learners_differ_only_by_what_they_practised_not_by_the_band_asked():
    world = _world()
    easy, hard = _learner(world, 5), _learner(world, 5)

    for step in range(30):
        concept = FIXTURE_GRAPH.concepts[step % 4]
        assert easy.answer(concept, "easy") == hard.answer(concept, "hard")
    assert [easy.skill(c) for c in FIXTURE_GRAPH.concepts] == [
        hard.skill(c) for c in FIXTURE_GRAPH.concepts
    ]


def test_fresh_item_probability_ignores_the_delay():
    learner = _learner(_world())
    for _ in range(5):
        learner.answer("a1")

    for concept in FIXTURE_GRAPH.concepts:
        expected = 0.25 + 0.65 * learner.skill(concept)
        for delay in (0.0, 7.0, 365.0):
            assert learner.p_correct_fresh(concept, delay) == pytest.approx(expected, abs=TOLERANCE)
        assert learner.p_correct_fresh(concept) == learner.p_correct_fresh(concept, 365.0)


def test_p_correct_fresh_draws_nothing():
    """Reading the metric must not move a response stream."""
    world = _world()
    watched, plain = _learner(world, 2), _learner(world, 2)

    for _ in range(20):
        for concept in FIXTURE_GRAPH.concepts:
            watched.p_correct_fresh(concept, 7.0)
        assert watched.answer("a1") == plain.answer("a1")


def test_answers_are_right_about_as_often_as_p_correct_says():
    """First answers on a1 at skill 0: right with the guess probability of 0.25."""
    world = _world(initial_skill_max=0.0)

    correct = len([i for i in range(1200) if _learner(world, i).answer("a1")])

    assert 255 <= correct <= 345  # 300 expected; three standard deviations are 45


def test_answer_is_the_draw_compared_with_p_correct():
    always = _world(guess=0.999999, slip=0.0, initial_skill_max=0.0)
    never = _world(guess=0.0, slip=0.0, initial_skill_max=0.0, contradicting_share=0.0)

    assert all(_learner(always, i).answer("a1") for i in range(200))
    assert not any(_learner(never, i).answer("a1") for i in range(200))


# ---------------------------------------------------------------------------
# A2: learning
# ---------------------------------------------------------------------------


def test_one_item_moves_the_skill_by_rate_gain_gate_of_what_is_left():
    world = _world("strong", contradicting_share=0.0)
    learner = _learner(world)
    rate = learner.traits.learning_rate
    a1, a2 = learner.skill("a1"), learner.skill("a2")

    learner.answer("a2")  # gated by a1
    expected_a2 = a2 + rate * 0.3 * (1 - 0.9 * (1 - a1)) * (1 - a2)
    assert learner.skill("a2") == pytest.approx(expected_a2, abs=TOLERANCE)
    assert learner.skill("a1") == a1  # only the practised concept moves

    learner.answer("a1")  # no prerequisite: the full gain
    assert learner.skill("a1") == pytest.approx(a1 + rate * 0.3 * (1 - a1), abs=TOLERANCE)
    assert learner.items_answered("a1") == 1 and learner.items_answered("a2") == 1
    assert learner.items_answered("c3") == 0


def test_learning_does_not_depend_on_the_response():
    """Two learners with the same rate: one always right, one always wrong, the same skill."""
    right = _world("none", guess=0.999999, slip=0.0, learning_rate_range=(1.0, 1.0))
    wrong = _world("none", guess=0.0, slip=0.999999, learning_rate_range=(1.0, 1.0))
    a, b = _learner(right, 1), _learner(wrong, 1)

    responses = [(a.answer("a1"), b.answer("a1")) for _ in range(5)]

    assert responses == [(True, False)] * 5
    assert a.skill("a1") == b.skill("a1")


@pytest.mark.parametrize("strength", ["none", "weak", "strong"])
def test_skill_never_falls_and_never_passes_one(strength):
    world = _world(strength, learning_rate_range=(1.5, 1.5), base_gain=2 / 3)  # gain 1.0
    learner = _learner(world, 7)
    rng = random.Random(SEED)

    for _ in range(400):
        concept = FIXTURE_GRAPH.concepts[int(rng.random() * 9)]
        before = learner.skill(concept)
        learner.answer(concept)
        assert before <= learner.skill(concept) <= 1.0
    assert learner.skill("a1") == 1.0  # a gain of 1 closes the gap in one item


def test_strong_prerequisites_slow_a_concept_whose_prerequisite_is_unknown():
    """Ten items on b2 while a3 is unknown: far less is learnt than without the gate."""
    skills = {}
    for strength in ("none", "weak", "strong"):
        learner = _learner(_world(strength, contradicting_share=0.0, initial_skill_max=0.0))
        for _ in range(10):
            learner.answer("b2")
        skills[strength] = learner.skill("b2")

    assert skills["none"] > skills["weak"] > skills["strong"] > 0
    assert skills["strong"] < 0.25 < 0.9 < skills["none"]


def test_a_contradicting_learner_learns_an_ungated_concept_at_full_speed():
    gated = _learner(_world("strong", contradicting_share=0.0, initial_skill_max=0.0))
    free = _learner(_world("strong", contradicting_share=1.0, initial_skill_max=0.0))
    for _ in range(10):
        gated.answer("c3")
        free.answer("c3")

    reference = _learner(_world("none", contradicting_share=0.0, initial_skill_max=0.0))
    for _ in range(10):
        reference.answer("c3")

    assert free.skill("c3") == reference.skill("c3")
    assert gated.skill("c3") < free.skill("c3") / 3


# ---------------------------------------------------------------------------
# Common random numbers
# ---------------------------------------------------------------------------


def test_kth_answer_on_a_concept_uses_the_same_draw_whatever_came_between():
    """Without prerequisites the skill on a concept depends on its own items only, so the
    answers on a concept must be the same in every order of practice."""
    world = _world("none")
    blocked, interleaved, reversed_order = (_learner(world, 4) for _ in range(3))
    concepts = ("a1", "b2", "c3")

    in_blocks = {c: [blocked.answer(c) for _ in range(8)] for c in concepts}
    mixed: dict[str, list[bool]] = {c: [] for c in concepts}
    for _ in range(8):
        for concept in concepts:
            mixed[concept].append(interleaved.answer(concept))
    backwards = {c: [reversed_order.answer(c) for _ in range(8)] for c in reversed(concepts)}

    assert mixed == in_blocks == backwards
    assert len({tuple(answers) for answers in in_blocks.values()}) > 1  # not one shared sequence


def test_response_draws_differ_between_learners_and_between_concepts():
    world = _world("none", initial_skill_max=0.0, learning_rate_range=(0.5, 0.5), base_gain=0.01)

    by_learner = set()
    for index in range(20):
        learner = _learner(world, index)
        by_learner.add(tuple(learner.answer("a1") for _ in range(30)))
    one = _learner(world, 0)
    by_concept = {c: tuple(one.answer(c) for _ in range(30)) for c in FIXTURE_GRAPH.concepts}

    assert len(by_learner) == 20
    assert len(set(by_concept.values())) == 9


def test_response_stream_is_the_learner_s_own():
    """Row k of the "response" stream holds the k-th draw of each concept, in book order."""
    world = _world("none", contradicting_share=0.0)
    learner = _learner(world, 6)
    draws = stream(SEED, 6, "response")
    rows = [[draws.random() for _ in FIXTURE_GRAPH.concepts] for _ in range(3)]

    for number in range(3):
        for concept in ("c3", "a1"):  # any order of concepts
            p = learner.p_correct(concept)
            position = FIXTURE_GRAPH.position(concept)
            assert learner.answer(concept) == (rows[number][position] < p)


# ---------------------------------------------------------------------------
# Constraints on the whole package, read from its source
# ---------------------------------------------------------------------------


def test_package_has_the_six_modules_of_the_issue():
    """At least these: a later module is held to the source checks below like the others."""
    assert set(PACKAGE_MODULES) >= {
        "__init__.py",
        "dags.py",
        "metrics.py",
        "policies.py",
        "protocol.py",
        "runner.py",
        "worlds.py",
    }


def test_package_source_reads_no_clock_and_no_environment():
    """A check of the package's own source. The settings object is not in it: the learner
    models import it, so importing the package reads the environment once and no module here
    uses a setting (``test_simulation_runner.py`` lists what the import loads)."""
    forbidden_imports = {"time", "os", "socket", "subprocess", "datetime"}
    forbidden_attributes = {"now", "utcnow", "today", "environ", "getenv", "perf_counter"}
    for module, tree in _trees().items():
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module is not None
                imported.add(node.module.split(".")[0])
                assert node.module != "backend.app.core.settings", module
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

        assert not imported & forbidden_imports, module
        assert not attributes & forbidden_attributes, module


def test_package_imports_only_what_it_declares():
    """The standard library, the policy interface, the attempt schema, the production
    update with its models, and ``eval_stats``."""
    allowed = (
        "backend.app.student.simulation.",
        "backend.app.student.policy.",
        "backend.app.student.attempts",
        "backend.app.student.estimator",
        "backend.app.student.models",
        "backend.app.core.eval_stats",
    )
    for module, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith("backend."):
                    assert name.startswith(allowed), (module, name)
                else:
                    top_level = name.split(".")[0]
                    assert top_level in sys.stdlib_module_names, (module, name)


def test_package_uses_arithmetic_only():
    """No power operator, no built-in ``sum`` and, from ``math``, only exactly rounded
    functions: results cannot depend on the C library or on the Python version. No ``hash``
    or ``id`` either, which differ between processes; a ``__hash__`` method may call
    ``hash`` to say what a value's own hash is."""
    exact_math = {"fsum", "sqrt", "floor", "isfinite"}
    for module, tree in _trees().items():
        math_used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "math"
        }
        in_hash_methods = {
            id(node)
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef) and function.name == "__hash__"
            for node in ast.walk(function)
        }
        called = {
            (node.func.id, id(node) in in_hash_methods)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        forbidden = {"sum", "pow", "hash", "id", "exp", "log"}

        assert math_used <= exact_math, module
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.Pow)], module
        assert [call for call in called if call[0] in forbidden and call != ("hash", True)] == [], (
            module
        )
