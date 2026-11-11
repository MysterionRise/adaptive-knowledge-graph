"""
Tests for the simulator's sequencing policies (#307).

``backend/app/student/simulation/policies.py`` holds ``random``, ``textbook``,
``ready-first`` and the deliberately bad ``stuck-on-last`` as implementations of the policy
interface of #306, and the table that says what each named policy may see. The tests follow
the counterfactual pattern of ``test_student_policy.py``: an input a policy declares must
change its record, an input it does not declare must change nothing.

| Policy            | Declared inputs                                                      |
| ----------------- | -------------------------------------------------------------------- |
| ``random``        | candidates, seed, step                                               |
| ``textbook``      | candidates, step (and its block length)                              |
| ``ready-first``   | candidates, step, the state of every candidate and of the            |
|                   | prerequisites of the unmastered ones, the given edges into the       |
|                   | unmastered ones (and its threshold and block length)                 |
| ``stuck-on-last`` | candidates                                                           |

``ready-first`` is the probe that reads the given DAG, so the sweep of #223 needs every
degraded variant to be able to change what it chooses. The last section checks that, and
the property behind the rule's shape: the first ready concept in book order is the same
whatever forward edges are given, which is why the probe goes round the ready concepts.
"""

import json
import random
from dataclasses import FrozenInstanceError, replace

import pytest

from backend.app.student.policy import (
    BAND_V1,
    DecisionContext,
    DecisionRecord,
    EdgeUse,
    LearnerState,
    Policy,
    get_policy,
    policy_key,
)
from backend.app.student.simulation.dags import STANDARD_DAGS, given_dag, true_dag
from backend.app.student.simulation.policies import (
    BAD_POLICY,
    FIXED_DIFFICULTY,
    KIND_HINT,
    KIND_ITEM,
    KIND_READING,
    POLICY_NAMES,
    PolicySpec,
    RandomOrder,
    ReadyFirst,
    StuckOnLast,
    TextbookOrder,
    build_policy,
)
from backend.app.student.simulation.worlds import FIXTURE_GRAPH

pytestmark = pytest.mark.unit

BOOK = ("a", "b", "c", "d")
NO_STATE = LearnerState(mastery={}, initial_mastery=0.3)
OTHER_STATE = LearnerState(mastery={"a": 0.9, "b": 0.1, "zzz": 0.5}, initial_mastery=0.7)


def _edge(source: str, target: str, provenance: str = "sim:test") -> EdgeUse:
    return EdgeUse(source, target, "PREREQ", provenance)


def _state(**mastery: float) -> LearnerState:
    return LearnerState(mastery=mastery, initial_mastery=0.3)


def _context(edges: tuple[EdgeUse, ...] = (), **changes: object) -> DecisionContext:
    values: dict[str, object] = {"candidates": BOOK, "edges": edges, "step": 0, "seed": 11}
    values.update(changes)
    return DecisionContext(**values)


def _chosen(record: DecisionRecord) -> str:
    assert record.action["kind"] == KIND_ITEM
    return str(record.action["concept"])


SEQUENCERS = [RandomOrder(), TextbookOrder(2), ReadyFirst(0.6, 2), StuckOnLast()]


# ---------------------------------------------------------------------------
# All sequencers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy", SEQUENCERS, ids=policy_key)
def test_sequencers_implement_the_policy_interface(policy):
    record = policy.decide(NO_STATE, _context())

    assert isinstance(policy, Policy)
    assert (record.policy_id, record.policy_version) == (policy.id, policy.version)
    assert record.action["kind"] == KIND_ITEM == "next_concept"
    assert record.action["concept"] in BOOK
    assert json.loads(record.canonical_json()) == record.to_dict()
    assert json.loads(str(record.context_used["candidates"])) == list(BOOK)


def test_policy_keys():
    assert [policy_key(policy) for policy in SEQUENCERS] == [
        "random-v1",
        "textbook-v1",
        "ready-first-v1",
        "stuck-on-last-v1",
    ]


@pytest.mark.parametrize("policy", SEQUENCERS, ids=policy_key)
def test_sequencers_need_candidates(policy):
    with pytest.raises(ValueError, match="needs the concepts to choose from"):
        policy.decide(NO_STATE, DecisionContext(step=0, seed=1))


@pytest.mark.parametrize("policy", SEQUENCERS, ids=policy_key)
def test_sequencers_are_frozen_values(policy):
    assert policy == replace(policy)
    assert hash(policy) == hash(replace(policy))
    # A frozen dataclass with slots refuses every assignment; the error type for a name
    # that is no field differs between Python versions.
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        policy.version = "v2"


def test_sequencer_parameters_cannot_be_reassigned():
    with pytest.raises(FrozenInstanceError):
        TextbookOrder(2).items_per_concept = 3
    with pytest.raises(FrozenInstanceError):
        ReadyFirst(0.6, 2).mastery_threshold = 0.1
    with pytest.raises(FrozenInstanceError):
        ReadyFirst(0.6, 2).items_per_concept = 3


@pytest.mark.parametrize("policy", [RandomOrder(), TextbookOrder(2), StuckOnLast()], ids=policy_key)
def test_state_blind_sequencers_ignore_state_and_edges(policy):
    """Their record lists no state and no edge, and neither can change it."""
    edges = (_edge("a", "b"), _edge("d", "a"))
    plain = policy.decide(NO_STATE, _context(step=3))
    changed = policy.decide(OTHER_STATE, _context(edges, step=3))

    assert changed == plain
    assert dict(plain.state_used) == {}
    assert plain.edges_used == ()


def test_action_kinds_and_the_fixed_band():
    assert (KIND_ITEM, KIND_HINT, KIND_READING) == ("next_concept", "hint", "reading")
    assert FIXED_DIFFICULTY == "medium"


# ---------------------------------------------------------------------------
# random
# ---------------------------------------------------------------------------


def test_random_order_is_a_function_of_candidates_seed_and_step():
    policy = RandomOrder()
    base = policy.decide(NO_STATE, _context(step=5, seed=11))

    assert policy.decide(NO_STATE, _context(step=5, seed=11)) == base
    assert dict(base.context_used) == {"candidates": '["a","b","c","d"]', "seed": 11, "step": 5}
    assert policy.decide(NO_STATE, _context(step=6, seed=11)) != base
    assert policy.decide(NO_STATE, _context(step=5, seed=12)) != base
    assert policy.decide(NO_STATE, _context(step=5, seed=11, candidates=("a", "b"))) != base


def test_random_order_spreads_over_the_candidates():
    policy = RandomOrder()
    counts = dict.fromkeys(BOOK, 0)
    for step in range(400):
        counts[_chosen(policy.decide(NO_STATE, _context(step=step, seed=307)))] += 1

    assert all(70 <= count <= 130 for count in counts.values())  # 100 each expected
    other = [_chosen(policy.decide(NO_STATE, _context(step=step, seed=308))) for step in range(40)]
    same = [_chosen(policy.decide(NO_STATE, _context(step=step, seed=307))) for step in range(40)]
    assert other != same


@pytest.mark.parametrize("missing", ["seed", "step"])
def test_random_order_needs_seed_and_step(missing):
    with pytest.raises(ValueError, match=r"needs context.seed and context.step"):
        RandomOrder().decide(NO_STATE, _context(**{missing: None}))


# ---------------------------------------------------------------------------
# textbook
# ---------------------------------------------------------------------------


def test_textbook_order_is_blocks_in_book_order_and_starts_again():
    policy = TextbookOrder(2)
    order = [_chosen(policy.decide(NO_STATE, _context(step=step))) for step in range(10)]

    assert order == ["a", "a", "b", "b", "c", "c", "d", "d", "a", "a"]
    assert [_chosen(TextbookOrder(1).decide(NO_STATE, _context(step=s))) for s in range(5)] == [
        "a",
        "b",
        "c",
        "d",
        "a",
    ]


def test_textbook_order_declares_step_candidates_and_block_length():
    record = TextbookOrder(3).decide(NO_STATE, _context(step=7))

    assert dict(record.action) == {"kind": "next_concept", "concept": "c"}
    assert dict(record.context_used) == {
        "candidates": '["a","b","c","d"]',
        "step": 7,
        "items_per_concept": 3,
    }
    # The seed is not declared and changes nothing.
    assert TextbookOrder(3).decide(NO_STATE, _context(step=7, seed=999)) == record
    assert TextbookOrder(2).decide(NO_STATE, _context(step=7)) != record


def test_textbook_order_needs_a_step_and_a_block_of_at_least_one():
    with pytest.raises(ValueError, match="needs context.step"):
        TextbookOrder(2).decide(NO_STATE, _context(step=None))
    with pytest.raises(ValueError, match="at least 1"):
        TextbookOrder(0)


# ---------------------------------------------------------------------------
# stuck-on-last
# ---------------------------------------------------------------------------


def test_stuck_on_last_always_takes_the_last_concept():
    policy = StuckOnLast()

    for step in range(5):
        record = policy.decide(OTHER_STATE, _context(step=step, seed=step))
        assert _chosen(record) == "d"
        assert dict(record.context_used) == {"candidates": '["a","b","c","d"]'}


# ---------------------------------------------------------------------------
# ready-first: the rule
# ---------------------------------------------------------------------------

READY_FIRST = ReadyFirst(0.6, 2)


def _order(policy: ReadyFirst, state: LearnerState, edges: tuple[EdgeUse, ...], steps: int):
    return [_chosen(policy.decide(state, _context(edges, step=step))) for step in range(steps)]


def test_ready_first_goes_round_the_ready_concepts_in_blocks():
    """a is mastered. b waits for d. c waits for a only, so c is ready, and so is d, which
    waits for nothing. Blocks of two items go to c, to d and to c again."""
    edges = (_edge("d", "b"), _edge("a", "c"))
    state = _state(a=0.9, b=0.2)

    record = READY_FIRST.decide(state, _context(edges))

    assert dict(record.action) == {"kind": "next_concept", "concept": "c", "reason": "ready"}
    assert record.edges_used == (_edge("d", "b"), _edge("a", "c"))
    assert dict(record.state_used) == {
        "mastery:a": 0.9,
        "mastery:b": 0.2,
        "mastery:c": 0.3,  # no history: the initial mastery
        "mastery:d": 0.3,
    }
    assert dict(record.context_used) == {
        "candidates": '["a","b","c","d"]',
        "step": 0,
        "items_per_concept": 2,
        "mastery_threshold": 0.6,
    }
    assert _order(READY_FIRST, state, edges, 6) == ["c", "c", "d", "d", "c", "c"]
    assert _order(ReadyFirst(0.6, 1), state, edges, 4) == ["c", "d", "c", "d"]
    assert _order(ReadyFirst(0.6, 3), state, edges, 6) == ["c", "c", "c", "d", "d", "d"]


def test_ready_first_does_not_return_to_a_mastered_concept():
    """Without edges every concept that is not mastered is ready."""
    assert _order(READY_FIRST, _state(a=0.7), (), 8) == ["b", "b", "c", "c", "d", "d", "b", "b"]
    assert _order(READY_FIRST, _state(a=0.7, b=0.8, c=0.1), (), 6) == ["c", "c", "d", "d", "c", "c"]


def test_ready_first_is_textbook_order_while_nothing_is_mastered_and_no_edge_is_given():
    textbook = TextbookOrder(2)
    for step in range(12):
        context = _context(step=step)
        record = READY_FIRST.decide(_state(a=0.1, c=0.59), context)

        assert _chosen(record) == _chosen(textbook.decide(NO_STATE, context))
        assert record.action["reason"] == "ready"


def test_ready_first_counts_a_value_at_the_threshold_as_mastered():
    """a before b. Below the threshold a is still to be learnt and b waits for it."""
    chain = (_edge("a", "b"),)

    below = _order(READY_FIRST, _state(a=0.5999999999999999), chain, 6)
    at = _order(READY_FIRST, _state(a=0.6), chain, 6)

    assert below == ["a", "a", "c", "c", "d", "d"]
    assert at == ["b", "b", "c", "c", "d", "d"]
    assert _order(ReadyFirst(0.61, 2), _state(a=0.6), chain, 6) == below


def test_ready_first_uses_the_initial_mastery_for_a_concept_without_history():
    high_start = LearnerState(mastery={}, initial_mastery=0.9)

    record = READY_FIRST.decide(high_start, _context((_edge("a", "b"),)))

    assert record.action["reason"] == "fallback"  # everything counts as mastered
    assert record.state_used["mastery:a"] == 0.9
    assert record.edges_used == ()


def test_ready_first_needs_every_prerequisite_mastered():
    """c has two prerequisites: a is mastered, d is not. So c waits and only d is ready."""
    two = (_edge("a", "c"), _edge("d", "c"))
    state = _state(a=0.9, b=0.9)

    record = READY_FIRST.decide(state, _context(two))

    assert _chosen(record) == "d"
    assert record.edges_used == two
    assert _order(READY_FIRST, state, two, 4) == ["d", "d", "d", "d"]
    assert _order(READY_FIRST, state, (_edge("a", "c"),), 4) == ["c", "c", "d", "d"]
    assert _order(READY_FIRST, _state(a=0.9, b=0.9, d=0.9), two, 4) == ["c", "c", "c", "c"]


def test_ready_first_reads_every_prerequisite_of_a_concept_that_is_not_mastered():
    """Also after one of them has failed, so the record does not depend on the edge order."""
    first = READY_FIRST.decide(_state(), _context((_edge("x", "a"), _edge("y", "a"))))
    second = READY_FIRST.decide(_state(), _context((_edge("y", "a"), _edge("x", "a"))))

    assert _chosen(first) == _chosen(second) == "b"
    assert dict(first.state_used) == dict(second.state_used)
    assert set(first.state_used) >= {"mastery:x", "mastery:y"}


def test_ready_first_leaves_out_a_concept_that_waits_for_a_later_one():
    """An edge that points backward in book order: a waits for c."""
    edges = (_edge("c", "a"),)
    record = READY_FIRST.decide(_state(), _context(edges))

    assert _chosen(record) == "b"
    assert record.action["reason"] == "ready"
    assert record.edges_used == edges
    assert "a" not in _order(READY_FIRST, _state(), edges, 12)
    assert _order(READY_FIRST, _state(c=0.9), edges, 6) == ["a", "a", "b", "b", "d", "d"]


def test_ready_first_falls_back_to_textbook_order_when_nothing_is_ready():
    """A cycle: a waits for b and b for a; c and d wait for a. Nothing is ready, so every
    step is the step of ``textbook``."""
    edges = (_edge("b", "a"), _edge("a", "b"), _edge("a", "c"), _edge("a", "d"))
    record = READY_FIRST.decide(_state(), _context(edges))

    assert dict(record.action) == {"kind": "next_concept", "concept": "a", "reason": "fallback"}
    assert set(record.edges_used) == set(edges)
    assert set(record.state_used) == {"mastery:a", "mastery:b", "mastery:c", "mastery:d"}
    textbook = TextbookOrder(2)
    for step in range(10):
        context = _context(edges, step=step)
        fallback = READY_FIRST.decide(_state(), context)
        assert _chosen(fallback) == _chosen(textbook.decide(NO_STATE, context))
        assert fallback.action["reason"] == "fallback"

    # With a mastered, the cycle no longer blocks b, c and d.
    assert _order(READY_FIRST, _state(a=0.9), edges, 6) == ["b", "b", "c", "c", "d", "d"]


def test_ready_first_falls_back_to_textbook_order_when_everything_is_mastered():
    """No review rule of its own: the book again, from its place in textbook order."""
    state = _state(a=0.9, b=0.7, c=0.99, d=0.7)
    record = READY_FIRST.decide(state, _context((_edge("a", "b"),), step=2))

    assert dict(record.action) == {"kind": "next_concept", "concept": "b", "reason": "fallback"}
    assert record.edges_used == ()  # an edge into a mastered concept is not read
    assert len(record.state_used) == 4
    assert _order(READY_FIRST, state, (), 10) == ["a", "a", "b", "b", "c", "c", "d", "d", "a", "a"]


def test_ready_first_reads_a_prerequisite_that_is_no_candidate():
    edges = (_edge("outside", "a"),)

    waiting = READY_FIRST.decide(_state(), _context(edges))
    open_ = READY_FIRST.decide(_state(outside=0.8), _context(edges))

    assert _chosen(waiting) == "b"
    assert _chosen(open_) == "a"
    assert open_.state_used["mastery:outside"] == 0.8


def test_ready_first_takes_items_only():
    """A selection-only probe: no hint, no reading, whatever the state."""
    rng = random.Random(1)
    chain = (_edge("a", "b"), _edge("b", "c"), _edge("c", "d"))
    kinds = set()
    for step in range(200):
        mastery = {concept: rng.random() for concept in BOOK if rng.random() < 0.7}
        record = READY_FIRST.decide(_state(**mastery), _context(chain, step=step))
        kinds.add(record.action["kind"])

    assert kinds == {KIND_ITEM}


def test_ready_first_needs_a_step_and_a_block_of_at_least_one():
    with pytest.raises(ValueError, match="needs context.step"):
        READY_FIRST.decide(NO_STATE, _context(step=None))
    with pytest.raises(ValueError, match="at least 1"):
        ReadyFirst(0.6, 0)


# ---------------------------------------------------------------------------
# ready-first: the record lists what was read, and only that
# ---------------------------------------------------------------------------


def test_ready_first_record_keeps_the_provenance_of_the_given_edges():
    edges = (_edge("a", "b", "sim:precision-0.8"), _edge("a", "c", "sim:precision-0.8"))
    record = READY_FIRST.decide(_state(a=0.9), _context(edges))

    assert _chosen(record) == "b"
    assert record.edges_used == edges
    assert record.to_dict()["edges_used"][0] == {
        "source": "a",
        "target": "b",
        "relation": "PREREQ",
        "provenance": "sim:precision-0.8",
    }


def test_ready_first_does_not_read_the_edges_into_a_mastered_concept():
    """a and b are mastered. The edges into b cannot change the record; what the policy did
    read can."""
    state = _state(a=0.9, b=0.9)
    edges = (_edge("a", "c"),)
    record = READY_FIRST.decide(state, _context(edges))

    into_mastered = (_edge("a", "b"), _edge("d", "b"), *edges, _edge("c", "a"))
    assert READY_FIRST.decide(state, _context(into_mastered)) == record
    assert record.edges_used == edges
    assert set(record.state_used) == {"mastery:a", "mastery:b", "mastery:c", "mastery:d"}

    assert READY_FIRST.decide(_state(a=0.91, b=0.9), _context(edges)) != record
    assert READY_FIRST.decide(_state(a=0.9, b=0.9, d=0.2), _context(edges)) != record
    assert READY_FIRST.decide(state, _context((_edge("a", "c", "sim:other"),))) != record
    assert READY_FIRST.decide(state, _context((*edges, _edge("d", "c")))) != record
    assert ReadyFirst(0.7, 2).decide(state, _context(edges)) != record
    assert ReadyFirst(0.6, 3).decide(state, _context(edges)) != record


def test_ready_first_declares_the_step_and_ignores_the_seed():
    state, edges = _state(a=0.9), (_edge("a", "b"),)
    record = READY_FIRST.decide(state, _context(edges, step=4))

    assert READY_FIRST.decide(state, _context(edges, step=4, seed=5)) == record
    # Step 5 is in the same block and gives the same concept; the record still names the step.
    same_block = READY_FIRST.decide(state, _context(edges, step=5))
    assert _chosen(same_block) == _chosen(record)
    assert same_block != record
    assert _chosen(READY_FIRST.decide(state, _context(edges, step=6))) != _chosen(record)


def test_ready_first_record_holds_json_scalars_and_one_number_type():
    record = ReadyFirst(1, 2).decide(  # an integer threshold
        LearnerState(mastery={"a": 1, "b": 0}, initial_mastery=0), _context()
    )

    assert _chosen(record) == "b"
    assert all(type(value) is float for value in record.state_used.values())
    assert type(record.context_used["mastery_threshold"]) is float
    assert type(record.context_used["items_per_concept"]) is int
    assert record == ReadyFirst(1.0, 2).decide(
        LearnerState(mastery={"a": 1.0, "b": 0.0}, initial_mastery=0.0), _context()
    )


# ---------------------------------------------------------------------------
# ready-first and the given DAG: every degraded variant can change the choice
# ---------------------------------------------------------------------------

DEGRADED_DAGS = [spec for spec in STANDARD_DAGS if spec.kind != "true"]
FORWARD_DAGS = [spec for spec in STANDARD_DAGS if spec.kind != "reversed"]
TRUE_EDGES = true_dag(FIXTURE_GRAPH)


def _random_state(rng: random.Random) -> LearnerState:
    """Some concepts with history, about half of them above the threshold."""
    mastery = {c: rng.random() for c in FIXTURE_GRAPH.concepts if rng.random() < 0.7}
    return LearnerState(mastery=mastery, initial_mastery=0.3)


def _fixture_context(edges: tuple[EdgeUse, ...], step: int) -> DecisionContext:
    return DecisionContext(candidates=FIXTURE_GRAPH.concepts, edges=edges, step=step)


@pytest.mark.parametrize("spec", DEGRADED_DAGS, ids=lambda spec: spec.id)
def test_every_degraded_dag_can_change_what_ready_first_chooses(spec):
    """Against the true DAG, on the same state and step. This is what the precision and
    recall sweep of #223 measures: a variant that could not change a choice would have an
    effect of exactly zero."""
    rng = random.Random(307)
    changed = compared = 0
    for seed in range(20):
        edges = given_dag(FIXTURE_GRAPH, spec, seed)
        for step in range(0, 10, 2):
            state = _random_state(rng)
            on_given = READY_FIRST.decide(state, _fixture_context(edges, step))
            on_true = READY_FIRST.decide(state, _fixture_context(TRUE_EDGES, step))
            changed += on_given.action["concept"] != on_true.action["concept"]
            compared += 1
            assert set(on_given.edges_used) <= set(edges)

    assert compared == 100
    assert changed >= 10  # 21 to 69 of the 100, depending on the variant


@pytest.mark.parametrize("spec", FORWARD_DAGS, ids=lambda spec: spec.id)
def test_the_first_ready_concept_is_the_same_whatever_forward_edges_are_given(spec):
    """Why the probe goes round the ready concepts. Every variant but the reversed ones keeps
    book order topological, and then the first concept that is not mastered has only
    earlier, mastered prerequisites. In block 0 the probe takes that concept: a rule that
    always took it could not tell these variants apart."""
    rng = random.Random(307)
    for seed in range(20):
        edges = given_dag(FIXTURE_GRAPH, spec, seed)
        for _ in range(4):
            state = _random_state(rng)
            record = READY_FIRST.decide(state, _fixture_context(edges, 0))
            without = READY_FIRST.decide(state, _fixture_context((), 0))
            unmastered = [
                concept
                for concept in FIXTURE_GRAPH.concepts
                if state.mastery.get(concept, 0.3) < 0.6
            ]

            assert dict(record.action) == dict(without.action)
            if unmastered:
                assert dict(record.action) == {
                    "kind": "next_concept",
                    "concept": unmastered[0],
                    "reason": "ready",
                }


def test_reversed_edges_can_leave_nothing_ready():
    """a1 and a2 wait for each other and every other concept waits for one of them."""
    turned = tuple(
        _edge(target, source) if (source, target) == ("a1", "a2") else _edge(source, target)
        for source, target in FIXTURE_GRAPH.edges
    )
    edges = (*turned, _edge("a1", "a2"))

    record = READY_FIRST.decide(_state(), _fixture_context(edges, 4))

    assert dict(record.action) == {"kind": "next_concept", "concept": "a3", "reason": "fallback"}


def test_ready_first_reads_the_edges_it_is_given_not_the_true_ones():
    """With the fixture's concepts and one made-up edge, a1 waits for a2."""
    turned = (_edge("a2", "a1", "sim:made-up"),)

    on_true = READY_FIRST.decide(_state(), _fixture_context(TRUE_EDGES, 0))
    on_turned = READY_FIRST.decide(_state(), _fixture_context(turned, 0))

    assert _chosen(on_true) == "a1"
    assert _chosen(on_turned) == "a2"
    assert {edge.provenance for edge in on_true.edges_used} == {"sim:true"}
    assert {edge.provenance for edge in on_turned.edges_used} == {"sim:made-up"}


# ---------------------------------------------------------------------------
# The named policies
# ---------------------------------------------------------------------------


def _build(name: str) -> PolicySpec:
    return build_policy(name, mastery_threshold=0.6, items_per_concept=2)


def test_policy_names_of_a_protocol_leave_out_the_bad_policy():
    assert POLICY_NAMES == ("random", "textbook", "band-v1", "ready-first", "oracle")
    assert BAD_POLICY == "stuck-on-last"
    assert BAD_POLICY not in POLICY_NAMES


def test_what_each_named_policy_is_and_may_see():
    table = {
        name: (
            type(spec.sequencer).__name__,
            spec.difficulty,
            spec.state_source,
            spec.dag_source,
        )
        for name in (*POLICY_NAMES, BAD_POLICY)
        for spec in [_build(name)]
    }

    assert table == {
        "random": ("RandomOrder", None, "none", "none"),
        "textbook": ("TextbookOrder", None, "none", "none"),
        "band-v1": ("TextbookOrder", BAND_V1, "none", "none"),
        "ready-first": ("ReadyFirst", None, "estimate", "given"),
        "oracle": ("ReadyFirst", None, "truth", "true"),
        "stuck-on-last": ("StuckOnLast", None, "none", "none"),
    }
    assert all(_build(name).name == name for name in table)


def test_band_v1_is_the_production_policy_object():
    """Imported, not copied: the object the registry and the API use."""
    spec = _build("band-v1")

    assert spec.difficulty is BAND_V1
    assert spec.difficulty is get_policy("band-v1")
    assert policy_key(spec.difficulty) == spec.name == "band-v1"
    assert spec.sequencer == _build("textbook").sequencer


def test_oracle_is_ready_first_with_other_inputs():
    oracle, ready_first = _build("oracle"), _build("ready-first")

    assert oracle.sequencer == ready_first.sequencer == ReadyFirst(0.6, 2)
    assert (oracle.state_source, oracle.dag_source) == ("truth", "true")
    assert (ready_first.state_source, ready_first.dag_source) == ("estimate", "given")


def test_parameters_reach_the_sequencers():
    for name in ("ready-first", "oracle"):
        spec = build_policy(name, mastery_threshold=0.75, items_per_concept=5)
        assert spec.sequencer == ReadyFirst(0.75, 5)
    for name in ("textbook", "band-v1"):
        spec = build_policy(name, mastery_threshold=0.75, items_per_concept=5)
        assert spec.sequencer == TextbookOrder(5)


def test_unknown_policy_is_an_error_that_lists_the_known_ones():
    with pytest.raises(KeyError, match="Unknown policy 'frontier-v1'.*random, textbook, band-v1"):
        _build("frontier-v1")
