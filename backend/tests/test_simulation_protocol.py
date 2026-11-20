"""
Tests for the simulation protocol as a typed value and for the smoke protocol (#307).

``backend/app/student/simulation/protocol.py`` holds ``SimulationProtocol`` and
``SMOKE_PROTOCOL``, the small protocol of the CI smoke test. The smoke protocol has its own
values and the status "draft", so the values the maintainer freezes for the full matrix
cannot break CI. The frozen protocol and its file come with the second pull request of
#307; nothing here reads a file.
"""

import copy
import json
import pickle
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from backend.app.student.simulation.dags import STANDARD_DAGS, DagSpec
from backend.app.student.simulation.policies import BAD_POLICY, POLICY_NAMES
from backend.app.student.simulation.protocol import (
    ACTION_COSTS,
    MS_PER_MINUTE,
    SMOKE_DAGS,
    SMOKE_PROTOCOL,
    SimulationProtocol,
    minutes_to_ms,
)
from backend.app.student.simulation.worlds import FIXTURE_GRAPH

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The smoke protocol
# ---------------------------------------------------------------------------


def test_smoke_protocol_is_a_small_draft_on_the_fixture_graph():
    protocol = SMOKE_PROTOCOL

    assert protocol.status == "draft"
    assert protocol.version == "smoke-1"
    assert protocol.graph is FIXTURE_GRAPH
    assert 24 <= protocol.learners <= 48  # a few dozen
    assert protocol.master_seed == 307


def test_smoke_protocol_covers_every_strength_three_dags_and_every_policy():
    protocol = SMOKE_PROTOCOL

    assert [world.prereq_strength for world in protocol.worlds] == ["none", "weak", "strong"]
    assert [world.id for world in protocol.worlds] == ["none", "weak", "strong"]
    assert protocol.dags == SMOKE_DAGS
    assert [dag.id for dag in SMOKE_DAGS] == ["true", "precision-0.8", "reversed-0.2"]
    assert set(SMOKE_DAGS) <= set(STANDARD_DAGS)
    assert protocol.policies == POLICY_NAMES
    assert BAD_POLICY not in protocol.policies
    assert protocol.primary_cell == ("weak", "precision-0.8")
    assert protocol.contrasts == (
        ("band-v1", "textbook"),
        ("ready-first", "textbook"),
        ("oracle", "random"),
    )


def test_smoke_worlds_differ_in_prerequisite_strength_only():
    none, weak, strong = SMOKE_PROTOCOL.worlds

    assert replace(none, id="x", prereq_strength="strong") == replace(strong, id="x")
    assert replace(weak, id="x", prereq_strength="strong") == replace(strong, id="x")
    assert 0 < strong.contradicting_share < 1  # some learners contradict the DAG
    assert strong.learning_rate_range[0] < strong.learning_rate_range[1]  # heterogeneous


def test_smoke_budget_is_one_pass_of_the_book_and_a_rest_no_item_fits():
    protocol = SMOKE_PROTOCOL
    items = len(protocol.graph.concepts) * protocol.textbook_items_per_concept
    rest = protocol.time_budget_minutes - items * protocol.time_costs["item"]

    assert items == 18
    assert 0 < rest < protocol.time_costs["item"]


def test_action_costs_have_one_item_cost_whatever_the_band():
    assert ACTION_COSTS == ("item", "hint", "reading")
    assert set(SMOKE_PROTOCOL.time_costs) == set(ACTION_COSTS)


@pytest.mark.parametrize(
    ("minutes", "milliseconds"),
    [
        (1.0, 60_000),
        (0.1, 6_000),  # 0.1 * 60000 is 6000.000000000001 in floats
        (1.1, 66_000),
        (18.5, 1_110_000),
        (1 / 3, 20_000),
        (0.001, 60),
        (0.0, 0),
    ],
)
def test_simulated_time_is_counted_in_whole_milliseconds(minutes, milliseconds):
    assert MS_PER_MINUTE == 60_000
    assert minutes_to_ms(minutes) == milliseconds
    assert type(minutes_to_ms(minutes)) is int


@pytest.mark.parametrize("minutes", [0.00001, 1.00001, 0.1 + 1e-9, 1 / 7])
def test_a_time_that_is_no_whole_number_of_milliseconds_is_refused(minutes):
    with pytest.raises(ValueError, match="not a whole number of milliseconds"):
        minutes_to_ms(minutes)


def test_protocol_is_frozen():
    with pytest.raises(FrozenInstanceError):
        SMOKE_PROTOCOL.learners = 1000
    with pytest.raises(TypeError):
        SMOKE_PROTOCOL.time_costs["item"] = 0.1


def test_protocol_survives_pickling_and_copying():
    """A protocol can go to another process: every part of it can be pickled."""
    for clone in (pickle.loads(pickle.dumps(SMOKE_PROTOCOL)), copy.deepcopy(SMOKE_PROTOCOL)):
        assert clone == SMOKE_PROTOCOL
        assert clone.to_dict() == SMOKE_PROTOCOL.to_dict()
        assert clone.graph.prerequisites("b3") == ("b1", "b2")
        with pytest.raises(TypeError):
            clone.time_costs["item"] = 0.1


def test_protocol_can_be_hashed_and_equal_protocols_hash_alike():
    """The costs are a read-only mapping, which the generated hash could not take."""
    same = replace(SMOKE_PROTOCOL, time_costs={"reading": 2.0, "hint": 0.5, "item": 1.0})
    other = replace(SMOKE_PROTOCOL, time_costs={"item": 1.5, "hint": 0.5, "reading": 2.0})

    assert same == SMOKE_PROTOCOL
    assert hash(same) == hash(SMOKE_PROTOCOL)
    assert other != SMOKE_PROTOCOL
    assert len({SMOKE_PROTOCOL, same, other, replace(SMOKE_PROTOCOL, master_seed=308)}) == 3


def test_protocol_copies_what_it_is_given():
    costs = {"item": 1.0, "hint": 0.5, "reading": 2.0}
    protocol = replace(
        SMOKE_PROTOCOL,
        time_costs=costs,
        policies=["random", "textbook"],
        contrasts=[["textbook", "random"]],
        primary_cell=["weak", "reversed-0.2"],
        worlds=list(SMOKE_PROTOCOL.worlds),
        dags=list(SMOKE_PROTOCOL.dags),
    )
    costs["item"] = 99.0

    assert protocol.time_costs["item"] == 1.0
    assert protocol.policies == ("random", "textbook")
    assert protocol.contrasts == (("textbook", "random"),)
    assert protocol.primary_cell == ("weak", "reversed-0.2")
    assert isinstance(protocol.worlds, tuple) and isinstance(protocol.dags, tuple)


def test_protocol_echo_names_every_field_and_is_json():
    echo = SMOKE_PROTOCOL.to_dict()

    assert set(echo) == {field.name for field in fields(SimulationProtocol)}
    assert json.loads(json.dumps(echo)) == echo
    assert echo["status"] == "draft"
    assert echo["primary_cell"] == ["weak", "precision-0.8"]
    assert echo["time_costs"] == {"item": 1.0, "hint": 0.5, "reading": 2.0}
    assert echo["graph"]["edges"][0] == ["a1", "a2"]
    assert echo["dags"][1] == {"id": "precision-0.8", "kind": "precision", "level": 0.8}
    assert echo["worlds"][2]["prereq_strength"] == "strong"
    assert echo["retention_delay_days"] == 7.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "final"}, "status must be"),
        ({"learners": 1}, "at least two learners"),
        ({"time_budget_minutes": 0.0}, "budget must be positive"),
        ({"time_costs": {"item": 1.0, "hint": 0.5}}, "positive cost for each"),
        ({"time_costs": {"item": 1.0, "hint": 0.5, "reading": 0.0}}, "positive cost for each"),
        (
            {"time_costs": {"item": 1.0, "hint": 0.5, "reading": 2.0, "item_hard": 2.0}},
            "positive cost for each",
        ),
        ({"time_budget_minutes": 18.50001}, "not a whole number of milliseconds"),
        (
            {"time_costs": {"item": 1 / 7, "hint": 0.5, "reading": 2.0}},
            "not a whole number of milliseconds",
        ),
        (
            {"time_costs": {"item": 1.0, "hint": 1e-12, "reading": 2.0}},
            "at least one millisecond",
        ),
        ({"time_budget_minutes": 1e-12}, "at least one millisecond"),
        ({"retention_delay_days": -1.0}, "delay must not be negative"),
        ({"criterion": 0.0}, "criterion must lie in"),
        ({"criterion": 1.2}, "criterion must lie in"),
        ({"mastery_threshold": 0.0}, "mastery_threshold must lie in"),
        ({"textbook_items_per_concept": 0}, "at least 1"),
        ({"delta": 0.0}, "delta must be positive"),
        ({"delta": -0.02}, "delta must be positive"),
        ({"bootstrap_resamples": -1}, "must not be negative"),
        ({"worlds": ()}, "at least one world"),
        ({"dags": ()}, "at least one DAG"),
        ({"policies": ()}, "at least one policy"),
        ({"policies": ("random", "random")}, "no id twice"),
        ({"dags": (DagSpec("true", "true"), DagSpec("true", "none"))}, "no id twice"),
        (
            {"dags": (*SMOKE_PROTOCOL.dags, DagSpec("truth", "true"))},
            "true DAG at most once",
        ),
        ({"primary_cell": ("medium", "true")}, "primary cell"),
        ({"primary_cell": ("weak", "recall-0.8")}, "primary cell"),
        ({"policies": ("random", "frontier-v1"), "contrasts": ()}, "Unknown policies"),
        ({"contrasts": (("oracle", "stuck-on-last"),)}, "names an unlisted policy"),
        ({"contrasts": (("mastery-textbook", "textbook"),)}, "names an unlisted policy"),
        (
            {"status": "frozen", "policies": (*POLICY_NAMES, BAD_POLICY)},
            "frozen protocol does not list the test-only policy 'stuck-on-last'",
        ),
    ],
)
def test_protocol_rejects_values_outside_their_range(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(SMOKE_PROTOCOL, **changes)


def test_protocol_duplicate_world_ids_are_rejected():
    worlds = (SMOKE_PROTOCOL.worlds[0], SMOKE_PROTOCOL.worlds[0])

    with pytest.raises(ValueError, match="no id twice"):
        replace(SMOKE_PROTOCOL, worlds=worlds, primary_cell=("none", "true"))


def test_a_draft_protocol_may_list_the_bad_policy_and_a_frozen_one_may_not():
    """Tests run the deliberately bad policy from a draft; no frozen protocol can carry it."""
    draft = replace(
        SMOKE_PROTOCOL,
        policies=(*POLICY_NAMES, BAD_POLICY),
        contrasts=(("random", BAD_POLICY),),
    )

    assert draft.status == "draft"
    assert draft.policies[-1] == "stuck-on-last"
    with pytest.raises(ValueError, match="test-only policy"):
        replace(draft, status="frozen")


def test_protocol_accepts_the_frozen_status_and_values_at_the_edge_of_their_range():
    protocol = replace(
        SMOKE_PROTOCOL,
        status="frozen",
        bootstrap_resamples=0,
        retention_delay_days=0.0,
        criterion=1.0,
        mastery_threshold=1.0,
        time_costs={"item": 0.1, "hint": 0.001, "reading": 2.0},
    )

    assert protocol.status == "frozen"
    assert protocol.policies == POLICY_NAMES
    assert protocol.time_costs["hint"] == 0.001  # 60 milliseconds
