"""
The CI smoke test of the learner simulator (#307).

``run_matrix(SMOKE_PROTOCOL)`` runs every policy on the hand-written fixture graph: three
worlds (prerequisite strength none, weak, strong) against three given DAGs (the true one, one
with false edges, one with reversed edges), with 24 learners. The tests check what the
simulator must get right before any result is read:

- Determinism: the same seed gives the same bytes, another seed does not, and the SHA-256 of
  the rendered report equals a literal. CI runs Python 3.11, 3.12 and 3.13, so the literal
  also holds the three versions to the same floats.
- Pairing: a learner is the same person, with the same response draws, under every policy.
- Sanity of the world: in the strong-prerequisite cell with the true DAG, the oracle beats
  ``random`` and ``random`` beats a deliberately bad policy, each by more than three Monte
  Carlo standard errors of the paired difference.
- Wiring: ``band-v1`` is the production policy object and equals ``textbook`` learner by
  learner (the core world has no item difficulty); the estimate is the production update;
  ``ready-first`` reads the given DAG and the estimate, the oracle the true DAG and the true
  skill; a policy that does not see the given DAG is run once per world.
- The policy-DAG axis: a given DAG of lower precision or recall moves what ``ready-first``
  reaches, so the sweep of #223 has something to measure. Which way it moves is not
  asserted.
- Time: no run exceeds the budget, an action that does not fit is not started, one that
  fits exactly is, and every timestamp is simulated time.

No test asserts that a candidate policy wins. The smoke protocol is a draft with its own
values; its numbers support no claim.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

from backend.app.core.settings import Settings, settings
from backend.app.student import estimator
from backend.app.student.attempts import ATTEMPT_FIELDS, SIM_EPOCH, Attempt, sim_timestamp
from backend.app.student.models import StudentProfile
from backend.app.student.policy import (
    BAND_V1,
    BandPolicyV1,
    DecisionContext,
    DecisionRecord,
    EdgeUse,
    LearnerState,
    difficulty_of,
)
from backend.app.student.simulation import runner
from backend.app.student.simulation.dags import STANDARD_DAGS, given_dag, true_dag
from backend.app.student.simulation.metrics import (
    decision,
    paired_effect,
    primary_metric,
    render_json,
)
from backend.app.student.simulation.policies import (
    BAD_POLICY,
    POLICY_NAMES,
    PolicySpec,
    ReadyFirst,
    TextbookOrder,
    build_policy,
)
from backend.app.student.simulation.protocol import SMOKE_PROTOCOL, SimulationProtocol
from backend.app.student.simulation.runner import (
    ESTIMATOR,
    INITIAL_MASTERY,
    LearnerOutcome,
    run_learner,
    run_matrix,
    run_policy,
)
from backend.app.student.simulation.worlds import Learner, World, synthetic_graph
from backend.app.student.student_service import StudentService

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
P = SMOKE_PROTOCOL
CONCEPTS = P.graph.concepts

# SHA-256 of render_json(run_matrix(SMOKE_PROTOCOL)). It changes only when the simulator,
# the production mastery update, eval_stats.bootstrap_interval or the smoke protocol changes;
# say which in the commit. A change to band-v1 does not move it, because the core world
# ignores the band: the band-v1 tests below catch that.
SMOKE_SHA256 = "a00422a8e7620319be6ff442eafa729b654cfe0a78af48b27d41ca0683836e55"

# The digest of the given DAGs (_dags_digest), which fresh interpreters recompute under two
# hash seeds.
DAGS_SHA256 = "43f2f76a5c5a2cfccbb7fb21a3fffeb536add608f3844141a72b3e0a213c569b"

ALL_POLICIES = (*POLICY_NAMES, BAD_POLICY)
WORLD_IDS = tuple(world.id for world in P.worlds)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _world(world_id: str, protocol: SimulationProtocol = P) -> World:
    spec = next(world for world in protocol.worlds if world.id == world_id)
    return World(spec, protocol.graph)


def _given(dag_id: str) -> tuple[EdgeUse, ...]:
    """A given DAG as the smoke run builds it; any of the standard variants."""
    spec = next(dag for dag in STANDARD_DAGS if dag.id == dag_id)
    return given_dag(P.graph, spec, P.master_seed)


def _policy(name: str, protocol: SimulationProtocol = P) -> PolicySpec:
    return build_policy(
        name,
        mastery_threshold=protocol.mastery_threshold,
        items_per_concept=protocol.textbook_items_per_concept,
    )


@dataclass
class Trace:
    outcome: LearnerOutcome
    attempts: list[Attempt]
    decisions: list[DecisionRecord]


def _trace(
    world: World,
    given: tuple[EdgeUse, ...],
    spec: PolicySpec,
    learner: int,
    protocol: SimulationProtocol = P,
) -> Trace:
    attempts: list[Attempt] = []
    decisions: list[DecisionRecord] = []
    outcome = run_learner(
        world,
        given,
        spec,
        protocol,
        learner,
        on_attempt=attempts.append,
        on_decision=decisions.append,
    )
    return Trace(outcome, attempts, decisions)


def _fresh_learner(world: World, index: int) -> Learner:
    return Learner(world, world.traits(P.master_seed, index), P.master_seed)


def _service_estimates(attempts: list[Attempt], monkeypatch) -> Iterator[dict[str, float]]:
    """The production path, answer by answer: ``StudentService._apply_answer`` on a profile.

    Yields the mastery levels before each attempt and, at the end, after the last one.
    """
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = StudentService.__new__(StudentService)
    profile = StudentProfile()
    for attempt in attempts:
        yield {concept: record.mastery_level for concept, record in profile.mastery_map.items()}
        service._apply_answer(profile, attempt.concept_ids[0], attempt.correct)
    yield {concept: record.mastery_level for concept, record in profile.mastery_map.items()}


def _unrounded_digest(report: dict[str, Any]) -> str:
    """A digest of the report as computed: JSON writes a float with every digit that
    matters, so two reports have the same digest only if every float is the same."""
    return hashlib.sha256(json.dumps(report, sort_keys=True).encode("utf-8")).hexdigest()


def _keys(value: Any) -> Iterator[str]:
    """Every key of a nested report."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


@dataclass(frozen=True)
class Scripted:
    """A sequencer for tests: plays a list of (kind, concept) actions and starts again."""

    script: tuple[tuple[str, str], ...]
    id: ClassVar[str] = "scripted"
    version: ClassVar[str] = "v0"

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        assert context.step is not None
        kind, concept = self.script[context.step % len(self.script)]
        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": kind, "concept": concept},
            state_used={},
            context_used={"step": context.step},
        )


class Recording:
    """Wraps a sequencer and keeps what the runner gave it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.id = inner.id
        self.version = inner.version
        self.seen: list[tuple[LearnerState, DecisionContext]] = []

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        self.seen.append((state, context))
        return self.inner.decide(state, context)


@dataclass
class Smoke:
    """The smoke run and what it ran."""

    report: dict[str, Any]
    text: str
    """The rendered report."""
    seconds: float
    """How long ``run_matrix`` took."""
    runs: dict[tuple[str, str, str | None], tuple[LearnerOutcome, ...]]
    """Every learner's outcome by (world, policy, given DAG); the DAG is None for a policy
    that does not see the given DAG."""
    calls: Counter[tuple[str, str]]
    """How often each (world, policy) was run."""


@pytest.fixture(scope="module")
def smoke() -> Iterator[Smoke]:
    """The smoke run, once per module. ``run_policy`` is watched while it runs, so the tests
    read the very outcomes the report was computed from."""
    runs: dict[tuple[str, str, str | None], tuple[LearnerOutcome, ...]] = {}
    calls: Counter[tuple[str, str]] = Counter()
    real = runner.run_policy
    # By edge set, not by the first edge's provenance: the DAG without edges has no first edge.
    dag_ids = {given_dag(P.graph, dag, P.master_seed): dag.id for dag in P.dags}

    def watched(world, given, spec, protocol):
        outcomes = real(world, given, spec, protocol)
        dag = dag_ids[given] if spec.dag_source == "given" else None
        runs[(world.spec.id, spec.name, dag)] = outcomes
        calls[(world.spec.id, spec.name)] += 1
        return outcomes

    runner.run_policy = watched
    try:
        started = time.perf_counter()
        report = run_matrix(P)
        seconds = time.perf_counter() - started
    finally:
        runner.run_policy = real
    yield Smoke(report, render_json(report), seconds, runs, calls)


@pytest.fixture(scope="module")
def all_runs(smoke) -> dict[tuple[str, str], tuple[LearnerOutcome, ...]]:
    """Every learner's outcome by (world, policy), with the true DAG where a policy sees the
    given one: the smoke run's own outcomes, and the deliberately bad policy run here."""
    runs = {}
    for world_id in WORLD_IDS:
        for name in POLICY_NAMES:
            dag = "true" if _policy(name).dag_source == "given" else None
            runs[(world_id, name)] = smoke.runs[(world_id, name, dag)]
        runs[(world_id, BAD_POLICY)] = run_policy(_world(world_id), (), _policy(BAD_POLICY), P)
    return runs


@pytest.fixture(scope="module")
def strong_true(all_runs) -> dict[str, tuple[LearnerOutcome, ...]]:
    """Every learner's outcome in the strong-prerequisite cell with the true DAG, by policy."""
    return {name: all_runs[("strong", name)] for name in ALL_POLICIES}


def _cell(report: dict[str, Any], world: str, dag: str) -> dict[str, Any]:
    return next(cell for cell in report["cells"] if (cell["world"], cell["dag"]) == (world, dag))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_smoke_run_takes_under_five_seconds(smoke):
    seconds = smoke.seconds

    assert seconds < 5.0


def test_same_seed_gives_identical_json(smoke):
    """A second run of one world gives the bytes the smoke run has for that world's cells,
    so a run also does not depend on which other worlds are run with it."""
    report = smoke.report
    first = [cell for cell in report["cells"] if cell["world"] == "strong"]

    again = run_matrix(P, worlds=["strong"])

    assert render_json({"cells": again["cells"]}) == render_json({"cells": first})
    assert again["cells"] == first  # not only after rounding
    assert again["dags"] == report["dags"]
    assert again["protocol"] == report["protocol"]


def test_different_seed_changes_results():
    small = replace(P, learners=8)
    selection = {"worlds": ["strong"], "dags": ["true"]}

    base = run_matrix(small, **selection)
    other = run_matrix(replace(small, master_seed=308), **selection)

    assert small.master_seed == 307
    assert render_json(other) != render_json(base)
    for name in P.policies:
        assert (
            other["cells"][0]["policies"][name]["primary"]
            != base["cells"][0]["policies"][name]["primary"]
        )


def test_smoke_output_digest_is_pinned(smoke):
    """The literal holds Python 3.11, 3.12 and 3.13 and every later change to the same bytes."""
    text = smoke.text

    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == SMOKE_SHA256


def test_rendered_report_is_json_with_sorted_keys_and_rounded_floats(smoke):
    report, text = smoke.report, smoke.text

    parsed = json.loads(text)

    assert text.endswith("}\n")
    assert list(parsed) == sorted(parsed)
    assert parsed["cells"][0]["policies"]["random"]["primary"]["mean"] == round(
        report["cells"][0]["policies"]["random"]["primary"]["mean"], 6
    )
    assert json.dumps(parsed, sort_keys=True, indent=2, ensure_ascii=False) + "\n" == text


def _dags_digest() -> str:
    """A digest of every standard variant of two graphs for five seeds, edge by edge."""
    graphs = (P.graph, synthetic_graph(4, 4, 1.5, 1))
    edges = [
        given_dag(graph, spec, seed)
        for graph in graphs
        for spec in STANDARD_DAGS
        for seed in range(5)
    ]
    return hashlib.sha256(repr(edges).encode("utf-8")).hexdigest()


def test_a_fresh_interpreter_gets_the_same_floats_under_any_hash_seed_and_imports_little(smoke):
    """Two fresh interpreters with different string hash seeds run the strong-prerequisite
    world of the smoke protocol. An order that leaned on a set would differ between them, so
    each prints the digest of the rendered cells, the digest of the cells before rounding (a
    sum taken in set order moves the last bit of a float and nothing a rounded report
    shows) and the digest of the given DAGs themselves, since which false edge is drawn
    need not show in a result. The cells must be the ones of the smoke run in this process,
    which has a third hash seed.

    The same run shows what importing the package loads: no model library, no database
    client, no web framework, and of this application only the core, learner and payload
    packages. The settings object is among them (the learner models import it)."""
    code = (
        "import hashlib, json, sys\n"
        "import backend.app.student.simulation as simulation\n"
        "heavy = ('torch', 'neo4j', 'opensearchpy', 'fastapi', 'starlette', 'spacy',\n"
        "         'sentence_transformers', 'httpx', 'backend.app.main',\n"
        "         'backend.app.student.student_service', 'backend.app.nlp.llm_client',\n"
        "         'backend.app.kg.neo4j_adapter', 'backend.app.rag.retriever')\n"
        "print(json.dumps([name for name in heavy if name in sys.modules]))\n"
        "parts = {name.split('.')[2] for name in sys.modules\n"
        "         if name.startswith('backend.app.') and name.count('.') >= 2}\n"
        "print(json.dumps(sorted(parts)))\n"
        "report = simulation.run_matrix(simulation.SMOKE_PROTOCOL, worlds=['strong'])\n"
        "cells = {'cells': report['cells']}\n"
        "text = simulation.render_json(cells)\n"
        "print(json.dumps(hashlib.sha256(text.encode('utf-8')).hexdigest()))\n"
        "unrounded = json.dumps(cells, sort_keys=True)\n"
        "print(json.dumps(hashlib.sha256(unrounded.encode('utf-8')).hexdigest()))\n"
        "graphs = (simulation.FIXTURE_GRAPH, simulation.synthetic_graph(4, 4, 1.5, 1))\n"
        "edges = [simulation.given_dag(graph, spec, seed) for graph in graphs\n"
        "         for spec in simulation.STANDARD_DAGS for seed in range(5)]\n"
        "print(json.dumps(hashlib.sha256(repr(edges).encode('utf-8')).hexdigest()))\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for hash_seed in ("0", "307")
    ]
    outputs = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=50)
            assert process.returncode == 0, stderr[-2000:]
            outputs.append([json.loads(line) for line in stdout.splitlines()])
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()

    cells = {"cells": [cell for cell in smoke.report["cells"] if cell["world"] == "strong"]}
    expected = [
        [],
        ["core", "student", "ui_payloads"],
        hashlib.sha256(render_json(cells).encode("utf-8")).hexdigest(),
        _unrounded_digest(cells),
        DAGS_SHA256,
    ]
    assert len(cells["cells"]) == 3
    assert outputs == [expected, expected]
    assert _dags_digest() == DAGS_SHA256


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_report_has_a_cell_for_every_world_and_dag_with_every_policy(smoke):
    report = smoke.report

    assert report["schema_version"] == 1
    assert [(cell["world"], cell["dag"]) for cell in report["cells"]] == [
        (world.id, dag.id) for world in P.worlds for dag in P.dags
    ]
    assert len(report["cells"]) == 9
    for cell in report["cells"]:
        assert list(cell["policies"]) == list(P.policies)
        assert [(c["policy"], c["baseline"]) for c in cell["contrasts"]] == list(P.contrasts)
        for summary in cell["policies"].values():
            assert set(summary) == {
                "primary",
                "time_to_criterion",
                "auc",
                "mean_minutes_used",
                "mean_attempts",
            }
            assert set(summary["primary"]) == {"mean", "sd", "mc_se"}
            assert 0.25 <= summary["primary"]["mean"] <= 0.9  # between guess and 1 - slip
            assert summary["auc"] is None or 0.0 <= summary["auc"] <= 1.0
    assert report["selection"] == {
        "worlds": ["none", "weak", "strong"],
        "dags": [dag.id for dag in P.dags],
        "policies": list(P.policies),
    }
    assert report["protocol"] == P.to_dict()
    assert report["simulator"] == {
        "world_family": "gated-continuous-growth-v1",
        "estimator": "bkt-fixed-v1",
        "initial_mastery": 0.3,
    }


def test_report_has_no_p_value(smoke):
    report, text = smoke.report, smoke.text
    keys = set(_keys(report))

    assert not [key for key in keys if "p_value" in key or "sign_test" in key or key == "p"]
    assert "p_value" not in text and "sign_test" not in text
    assert {"mean_difference", "mc_se", "sd_difference", "ci_low", "ci_high"} <= keys


def test_effects_are_paired_differences_with_monte_carlo_standard_errors(smoke, strong_true):
    report = smoke.report
    contrast = next(
        c for c in _cell(report, "strong", "true")["contrasts"] if c["policy"] == "oracle"
    )
    expected = paired_effect(
        [outcome.primary for outcome in strong_true["oracle"]],
        [outcome.primary for outcome in strong_true["random"]],
        resamples=P.bootstrap_resamples,
        seed=P.master_seed,
    )

    assert contrast == {"policy": "oracle", "baseline": "random", **expected}
    assert contrast["learners"] == 24
    assert contrast["ci_low"] < contrast["mean_difference"] < contrast["ci_high"]


def test_report_names_what_each_given_dag_is(smoke):
    report = smoke.report

    assert report["dags"] == {
        "true": {"kind": "true", "level": None, "edges": 10, "precision": 1.0, "recall": 1.0},
        "precision-0.8": {
            "kind": "precision",
            "level": 0.8,
            "edges": 13,
            "precision": 10 / 13,
            "recall": 1.0,
        },
        "reversed-0.2": {
            "kind": "reversed",
            "level": 0.2,
            "edges": 10,
            "precision": 0.8,
            "recall": 0.8,
        },
    }


def test_report_applies_the_decision_rule_to_every_contrast(smoke):
    """Each entry is the rule applied to that contrast's effect in every cell of the report,
    the other cells included: their losses are listed whatever the verdict."""
    report = smoke.report
    primary_cell = ("weak", "precision-0.8")

    assert [(d["policy"], d["baseline"]) for d in report["decisions"]] == list(P.contrasts)
    for entry in report["decisions"]:
        effects = {
            (cell["world"], cell["dag"]): contrast["mean_difference"]
            for cell in report["cells"]
            for contrast in cell["contrasts"]
            if (contrast["policy"], contrast["baseline"]) == (entry["policy"], entry["baseline"])
        }
        assert len(effects) == 9
        assert entry == {
            "policy": entry["policy"],
            "baseline": entry["baseline"],
            "delta": P.delta,
            "primary_cell": list(primary_cell),
            **decision(effects, primary_cell, P.delta),
        }
        assert entry["verdict"] in ("forward", "no_gain", "loss_elsewhere")


def test_the_decision_rule_gets_the_effect_of_every_cell(monkeypatch):
    """Watched at the call: a rule that only saw the primary cell could never report a loss
    elsewhere."""
    seen = []

    def spy(effects, primary_cell, delta):
        seen.append((dict(effects), primary_cell, delta))
        return decision(effects, primary_cell, delta)

    monkeypatch.setattr(runner, "decision", spy)
    report = run_matrix(
        replace(P, learners=2, bootstrap_resamples=0), policies=["textbook", "ready-first"]
    )

    ((effects, primary_cell, delta),) = seen
    assert (primary_cell, delta) == (("weak", "precision-0.8"), P.delta)
    assert set(effects) == {(world.id, dag.id) for world in P.worlds for dag in P.dags}
    for cell in report["cells"]:
        (contrast,) = cell["contrasts"]
        assert effects[(cell["world"], cell["dag"])] == contrast["mean_difference"]


def test_policies_that_ignore_the_given_dag_are_run_once_per_world(smoke):
    """Counted in the smoke run itself: 3 worlds, 4 policies once each and ready-first once
    per given DAG."""
    dag_count = len(P.dags)

    for world in P.worlds:
        for name in ("random", "textbook", "band-v1", "oracle"):
            assert smoke.calls[(world.id, name)] == 1
            assert (world.id, name, None) in smoke.runs
        assert smoke.calls[(world.id, "ready-first")] == dag_count == 3
        assert {dag for w, name, dag in smoke.runs if (w, name) == (world.id, "ready-first")} == {
            "true",
            "precision-0.8",
            "reversed-0.2",
        }
    assert sum(smoke.calls.values()) == smoke.report["policy_runs"] == 3 * (4 + 3)
    assert len(smoke.runs) == 21
    assert all(len(outcomes) == P.learners for outcomes in smoke.runs.values())


def test_the_bad_policy_is_not_in_the_smoke_run(smoke):
    assert not [key for key in smoke.runs if key[1] == BAD_POLICY]


def test_a_run_on_its_own_equals_the_run_inside_the_matrix(smoke):
    """``run_policy`` for one cell gives what the matrix computed for it."""
    world, given = _world("strong"), _given("reversed-0.2")
    small = replace(P, learners=6)

    assert (
        run_policy(world, given, _policy("ready-first"), small)
        == (smoke.runs[("strong", "ready-first", "reversed-0.2")][:6])
    )
    assert (
        run_policy(world, (), _policy("oracle"), small)
        == smoke.runs[("strong", "oracle", None)][:6]
    )


def test_shared_results_are_the_same_in_every_dag_cell_of_a_world(smoke):
    report = smoke.report

    for world in P.worlds:
        cells = [cell for cell in report["cells"] if cell["world"] == world.id]
        for name in ("random", "textbook", "band-v1", "oracle"):
            assert all(cell["policies"][name] == cells[0]["policies"][name] for cell in cells)
    # Worlds differ, so the sharing is per world and not global.
    assert (
        _cell(report, "none", "true")["policies"]["random"]
        != _cell(report, "strong", "true")["policies"]["random"]
    )


def test_dag_effects_compare_ready_first_with_itself_on_the_true_dag(smoke):
    """The effect of a given DAG is the variant minus the true DAG, on the same learners."""
    report = smoke.report
    checked = 0
    for cell in report["cells"]:
        if cell["dag"] == "true":
            assert cell["dag_effects"] == []
            continue
        (effect,) = cell["dag_effects"]
        on_variant = smoke.runs[(cell["world"], "ready-first", cell["dag"])]
        on_true = smoke.runs[(cell["world"], "ready-first", "true")]

        assert effect == {
            "policy": "ready-first",
            "reference_dag": "true",
            **paired_effect(
                [outcome.primary for outcome in on_variant],
                [outcome.primary for outcome in on_true],
                resamples=P.bootstrap_resamples,
                seed=P.master_seed,
            ),
        }
        assert effect["learners"] == 24
        checked += 1

    assert checked == 6


def test_every_degraded_dag_of_the_smoke_run_moves_ready_first(smoke):
    """In every world, false edges and reversed edges each leave at least one learner
    somewhere else than the true DAG does. No direction is asserted."""
    for cell in smoke.report["cells"]:
        for effect in cell["dag_effects"]:
            assert effect["sd_difference"] > 0, (cell["world"], cell["dag"])


@pytest.mark.parametrize("dag_id", ["precision-0.8", "precision-0.6", "recall-0.8", "recall-0.6"])
def test_the_precision_and_recall_sweep_has_something_to_measure(dag_id, smoke):
    """The issue's reason for the probe. With strong prerequisites, each standard level of
    precision and of recall leaves learners of ``ready-first`` somewhere else than the true
    DAG does (``test_simulation_policies.py`` shows the choices change, for twenty draws of
    every variant)."""
    reference = smoke.runs[("strong", "ready-first", "true")][:8]

    outcomes = run_policy(
        _world("strong"), _given(dag_id), _policy("ready-first"), replace(P, learners=8)
    )

    moved = sum(a.primary != b.primary for a, b in zip(outcomes, reference, strict=True))
    assert moved > 0


def test_selection_runs_a_part_of_the_matrix():
    part = run_matrix(
        replace(P, learners=4),
        worlds=["strong"],
        dags=["reversed-0.2", "true"],
        policies=["textbook", "ready-first"],
    )

    assert [(cell["world"], cell["dag"]) for cell in part["cells"]] == [
        ("strong", "true"),
        ("strong", "reversed-0.2"),
    ]
    assert list(part["cells"][0]["policies"]) == ["textbook", "ready-first"]
    assert [(c["policy"], c["baseline"]) for c in part["cells"][0]["contrasts"]] == [
        ("ready-first", "textbook")
    ]
    assert part["policy_runs"] == 1 + 2
    assert part["decisions"] == []  # the primary cell was not run
    assert part["selection"] == {
        "worlds": ["strong"],
        "dags": ["true", "reversed-0.2"],
        "policies": ["textbook", "ready-first"],
    }
    assert part["protocol"]["learners"] == 4


def test_selection_without_the_true_dag_has_no_dag_effects():
    part = run_matrix(
        replace(P, learners=2), worlds=["weak"], dags=["reversed-0.2", "precision-0.8"]
    )

    assert [cell["dag_effects"] for cell in part["cells"]] == [[], []]
    assert [d["verdict"] for d in part["decisions"]] and len(part["decisions"]) == 3


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ({"worlds": ["medium"]}, "no world"),
        ({"dags": ["precision-0.6"]}, "no DAG"),
        ({"policies": ["frontier-v1"]}, "Unknown policy"),
    ],
)
def test_selection_of_something_unknown_is_an_error(selection, message):
    with pytest.raises(KeyError, match=message):
        run_matrix(replace(P, learners=2), **selection)


def test_the_bad_policy_can_be_run_by_name_and_the_smoke_protocol_does_not_list_it():
    part = run_matrix(
        replace(P, learners=2), worlds=["strong"], dags=["true"], policies=[BAD_POLICY]
    )

    assert list(part["cells"][0]["policies"]) == ["stuck-on-last"]
    assert BAD_POLICY not in P.policies


# ---------------------------------------------------------------------------
# Sanity of the world: the oracle beats random, random beats the bad policy
# ---------------------------------------------------------------------------


def _effect(outcomes: dict[str, tuple[LearnerOutcome, ...]], policy: str, baseline: str) -> dict:
    return paired_effect(
        [outcome.primary for outcome in outcomes[policy]],
        [outcome.primary for outcome in outcomes[baseline]],
    )


def test_oracle_beats_random_with_strong_prerequisites(strong_true):
    effect = _effect(strong_true, "oracle", "random")

    assert effect["mc_se"] > 0
    assert effect["mean_difference"] > 3 * effect["mc_se"]


def test_random_beats_the_deliberately_bad_policy(strong_true):
    effect = _effect(strong_true, "random", BAD_POLICY)

    assert effect["mc_se"] > 0
    assert effect["mean_difference"] > 3 * effect["mc_se"]


def test_the_bad_policy_practises_one_gated_concept_only(strong_true):
    world = _world("strong")
    trace = _trace(world, (), _policy(BAD_POLICY), 0)

    assert {attempt.concept_ids for attempt in trace.attempts} == {("c3",)}
    assert trace.outcome == strong_true[BAD_POLICY][0]


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def test_run_policy_returns_every_learner_in_order(strong_true):
    for outcomes in strong_true.values():
        assert [outcome.learner for outcome in outcomes] == list(range(P.learners))


def test_learners_are_paired_across_policies():
    """Without prerequisites, the skill on a concept depends on its own items only. The k-th
    answer of a learner on a concept is then the same under every policy, as far as both
    policies got on that concept."""
    world = _world("none")
    compared = 0
    for learner in range(12):
        answers: dict[str, dict[str, list[bool]]] = {}
        for name in ("random", "textbook", "ready-first"):
            trace = _trace(world, _given("true"), _policy(name), learner)
            answers[name] = {}
            for attempt in trace.attempts:
                answers[name].setdefault(attempt.concept_ids[0], []).append(attempt.correct)
        for name in ("random", "ready-first"):
            for concept, sequence in answers[name].items():
                reference = answers["textbook"][concept]
                shared = min(len(sequence), len(reference))
                assert sequence[:shared] == reference[:shared]
                compared += shared

    assert compared > 150


def test_a_learner_has_the_same_id_and_start_under_every_policy():
    world = _world("strong")
    traces = {
        name: _trace(world, _given("true"), _policy(name), 3)
        for name in ("random", "textbook", "oracle")
    }

    assert {trace.attempts[0].learner_id for trace in traces.values()} == {"sim-3"}
    # The oracle's first decision reads the true initial skill: the traits of learner 3.
    record = traces["oracle"].decisions[0]
    assert record.state_used["mastery:a1"] == world.traits(P.master_seed, 3).initial_skill[0]


# ---------------------------------------------------------------------------
# band-v1: the production policy, and no effect in the core world
# ---------------------------------------------------------------------------


def test_band_v1_is_the_production_policy():
    spec = _policy("band-v1")

    assert spec.difficulty is BAND_V1
    assert isinstance(spec.difficulty, BandPolicyV1)


def test_band_v1_decides_every_item_and_the_band_reaches_the_attempt(monkeypatch):
    calls = []
    real = BandPolicyV1.decide

    def spy(self, state, context):
        calls.append((self, state, context))
        return real(self, state, context)

    monkeypatch.setattr(BandPolicyV1, "decide", spy)
    trace = _trace(_world("strong"), (), _policy("band-v1"), 5)

    assert len(calls) == len(trace.attempts) == 18
    assert all(policy is BAND_V1 for policy, _, _ in calls)
    sequencing, difficulty = trace.decisions[0::2], trace.decisions[1::2]
    assert {record.policy_id for record in sequencing} == {"textbook"}
    assert {(record.policy_id, record.policy_version) for record in difficulty} == {("band", "v1")}
    for attempt, chosen, band, (_, _, context) in zip(
        trace.attempts, sequencing, difficulty, calls, strict=True
    ):
        concept = str(chosen.action["concept"])
        assert context == DecisionContext(concept=concept)
        assert attempt.concept_ids == (concept,)
        assert attempt.item_id.split(":")[:3] == ["sim", concept, difficulty_of(band)]
        assert attempt.decision_record_id == chosen.record_id()
    # The decision is live: the estimate moves, and with it the band.
    assert len({difficulty_of(record) for record in difficulty}) >= 2


def test_band_v1_decides_from_the_production_estimate(monkeypatch):
    trace = _trace(_world("weak"), (), _policy("band-v1"), 2)
    estimates = _service_estimates(trace.attempts, monkeypatch)

    for attempt, record, before in zip(
        trace.attempts, trace.decisions[1::2], estimates, strict=False
    ):
        concept = attempt.concept_ids[0]
        assert record == BAND_V1.decide(
            LearnerState(mastery=before, initial_mastery=0.3), DecisionContext(concept=concept)
        )
        assert record.state_used["mastery"] == before.get(concept, 0.3)


def test_band_v1_equals_textbook_learner_by_learner(strong_true):
    """The wiring check of the issue: no item difficulty in the core world, so the band
    changes neither the answers, nor the learning, nor the time an item costs."""
    assert strong_true["band-v1"] == strong_true["textbook"]
    for world_id in ("none", "weak"):
        world = _world(world_id)
        for learner in range(6):
            band = run_learner(world, (), _policy("band-v1"), P, learner)
            textbook = run_learner(world, (), _policy("textbook"), P, learner)
            assert band == textbook
            assert band.minutes_used == textbook.minutes_used == 18.0


@pytest.mark.parametrize("world_id", WORLD_IDS)
def test_band_v1_equals_textbook_also_where_it_asks_for_every_band(world_id):
    """The smoke budget is one pass of the book, in which ``band-v1`` never gets to "hard".
    Three passes of six items per concept reach all three bands, so a cost or a gain tied
    to one band would show here."""
    long = replace(P, textbook_items_per_concept=6, time_budget_minutes=54.5)
    world = _world(world_id, long)
    bands: Counter[str] = Counter()
    for learner in range(3):
        band = _trace(world, (), _policy("band-v1", long), learner, long)
        textbook = _trace(world, (), _policy("textbook", long), learner, long)
        bands.update(attempt.item_id.split(":")[2] for attempt in band.attempts)

        assert band.outcome == textbook.outcome
        assert (band.outcome.attempts, band.outcome.minutes_used) == (54, 54.0)
        assert [a.correct for a in band.attempts] == [a.correct for a in textbook.attempts]
        assert [a.timestamp for a in band.attempts] == [a.timestamp for a in textbook.attempts]
        assert [a.latency_ms for a in band.attempts] == [a.latency_ms for a in textbook.attempts]

    assert set(bands) == {"easy", "medium", "hard"}
    assert min(bands.values()) >= 10


def test_policies_without_a_difficulty_policy_ask_for_the_fixed_band():
    for name in ("random", "textbook", "ready-first", "oracle"):
        trace = _trace(_world("strong"), _given("true"), _policy(name), 1)

        assert {attempt.item_id.split(":")[2] for attempt in trace.attempts} == {"medium"}
        assert {record.policy_id for record in trace.decisions} == {_policy(name).sequencer.id}
        assert len(trace.decisions) == len(trace.attempts)


# ---------------------------------------------------------------------------
# The estimate is the production update
# ---------------------------------------------------------------------------


def test_estimator_is_the_production_bkt(monkeypatch):
    """Every answer goes through ``estimator.apply_answer``, the function the service runs."""
    assert runner.apply_answer is estimator.apply_answer
    calls = []

    def spy(profile, concept, correct, **keywords):
        calls.append((concept, correct, keywords))
        return estimator.apply_answer(profile, concept, correct, **keywords)

    monkeypatch.setattr(runner, "apply_answer", spy)
    trace = _trace(_world("strong"), _given("true"), _policy("ready-first"), 4)

    assert [(concept, correct) for concept, correct, _ in calls] == [
        (attempt.concept_ids[0], attempt.correct) for attempt in trace.attempts
    ]
    assert len(calls) == 18
    for (_, _, keywords), attempt in zip(calls, trace.attempts, strict=True):
        assert keywords == {"initial_mastery": 0.3, "bkt_enabled": True, "now": attempt.timestamp}


def test_the_estimate_a_policy_sees_is_what_the_service_would_store(monkeypatch):
    """Replay the simulated answers through ``StudentService._apply_answer`` and compare
    every mastery value ``ready-first`` read, step by step."""
    checked = 0
    for learner in range(8):
        trace = _trace(_world("strong"), _given("true"), _policy("ready-first"), learner)
        estimates = _service_estimates(trace.attempts, monkeypatch)
        for record, before in zip(trace.decisions, estimates, strict=False):
            for key, value in record.state_used.items():
                assert value == before.get(key.removeprefix("mastery:"), 0.3)
                checked += 1

    assert checked > 300


def test_the_final_estimate_is_what_the_service_stores_through_sqlite(tmp_path, monkeypatch):
    """The whole production path, storage included: the simulated answers go through
    ``StudentService.update_mastery`` on a store in ``tmp_path``, and the stored mastery is
    the estimate the simulator ends with."""
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = StudentService(tmp_path / "profiles.db")
    world = _world("strong")
    for index in (0, 9):
        trace = _trace(world, (), _policy("random"), index)
        for attempt in trace.attempts:
            service.update_mastery(attempt.concept_ids[0], attempt.correct, student_id=f"s{index}")
        stored = service.get_profile(f"s{index}").mastery_map

        assert len(stored) >= 5  # random order reaches most of the nine concepts
        assert [estimate for estimate, _ in trace.outcome.predictions] == [
            stored[concept].mastery_level if concept in stored else 0.3 for concept in P.graph.slice
        ]


def test_the_run_does_not_read_the_settings(monkeypatch, strong_true):
    assert INITIAL_MASTERY == Settings.model_fields["student_initial_mastery"].default == 0.3
    assert Settings.model_fields["student_bkt_enabled"].default is True
    assert ESTIMATOR == "bkt-fixed-v1"
    monkeypatch.setattr(settings, "student_initial_mastery", 0.9)
    monkeypatch.setattr(settings, "student_bkt_enabled", False)

    for name in ("ready-first", "band-v1"):
        outcomes = run_policy(
            _world("strong"), _given("true"), _policy(name), replace(P, learners=6)
        )
        assert outcomes == strong_true[name][:6]


def test_auc_pairs_are_the_final_estimate_against_the_true_mastery(monkeypatch):
    world = _world("strong")
    trace = _trace(world, _given("true"), _policy("ready-first"), 7)
    *_, final = _service_estimates(trace.attempts, monkeypatch)
    learner = _fresh_learner(world, 7)
    for attempt in trace.attempts:
        learner.answer(attempt.concept_ids[0])

    assert trace.outcome.predictions == tuple(
        (final.get(concept, 0.3), learner.skill(concept) >= P.mastery_threshold)
        for concept in P.graph.slice
    )
    assert len(trace.outcome.predictions) == 9


# ---------------------------------------------------------------------------
# What each policy is allowed to see
# ---------------------------------------------------------------------------


def test_oracle_reads_the_true_skill_and_the_true_dag(monkeypatch):
    """Replayed on a fresh learner: every value the oracle read is the true skill then.
    The given DAG of the cell is "none"; the oracle still gets the true edges."""
    world = _world("strong")
    read_edges = set()
    for index in range(6):
        trace = _trace(world, _given("none"), _policy("oracle"), index)
        learner = _fresh_learner(world, index)
        for record, attempt in zip(trace.decisions, trace.attempts, strict=True):
            for key, value in record.state_used.items():
                assert value == learner.skill(key.removeprefix("mastery:"))
            read_edges.update(record.edges_used)
            learner.answer(attempt.concept_ids[0])

    assert read_edges <= set(true_dag(P.graph))
    assert {edge.provenance for edge in read_edges} == {"sim:true"}
    assert len(read_edges) >= 3


def test_oracle_does_not_read_the_estimate(monkeypatch):
    """Its records hold true skills, which are not the estimate's values."""
    trace = _trace(_world("strong"), (), _policy("oracle"), 0)
    estimates = _service_estimates(trace.attempts, monkeypatch)

    differing = 0
    for record, before in zip(trace.decisions, estimates, strict=False):
        for key, value in record.state_used.items():
            differing += value != before.get(key.removeprefix("mastery:"), 0.3)

    assert differing > 18


@pytest.mark.parametrize("dag_id", [dag.id for dag in STANDARD_DAGS])
def test_ready_first_reads_the_given_dag_of_its_cell(dag_id):
    given = _given(dag_id)
    read_edges = set()
    for index in range(2):
        trace = _trace(_world("strong"), given, _policy("ready-first"), index)
        for record in trace.decisions:
            read_edges.update(record.edges_used)

    assert read_edges <= set(given)
    assert {edge.provenance for edge in read_edges} <= {f"sim:{dag_id}"}
    if dag_id == "none":
        assert read_edges == set()
    else:
        assert read_edges


@pytest.mark.parametrize(
    ("state_source", "dag_source"),
    [("none", "none"), ("estimate", "given"), ("truth", "true"), ("estimate", "none")],
)
def test_runner_gives_a_sequencer_only_what_its_spec_allows(state_source, dag_source):
    world, given = _world("strong"), _given("recall-0.8")
    recording = Recording(TextbookOrder(2))
    spec = PolicySpec("recorded", recording, state_source=state_source, dag_source=dag_source)

    outcome = run_learner(world, given, spec, P, 0)

    assert outcome == run_learner(world, (), _policy("textbook"), P, 0)
    assert len(recording.seen) == 19  # 18 started actions and the one that did not fit
    expected_edges = {"none": (), "given": given, "true": true_dag(P.graph)}[dag_source]
    for step, (state, context) in enumerate(recording.seen):
        assert context.edges == expected_edges
        assert context.candidates == CONCEPTS
        assert context.step == step
        assert context.concept is None and context.now is None
        assert state.initial_mastery == 0.3
    states = [dict(state.mastery) for state, _ in recording.seen]
    if state_source == "none":
        assert states == [{}] * 19
    elif state_source == "truth":
        assert all(set(state) == set(CONCEPTS) for state in states)
        assert states[0] == dict(
            zip(CONCEPTS, world.traits(P.master_seed, 0).initial_skill, strict=True)
        )
    else:
        # The estimate has a value for the concepts answered so far: two items per concept.
        assert [len(state) for state in states] == [(step + 1) // 2 for step in range(19)]


def test_the_policy_seed_is_the_learner_s_own():
    world = _world("strong")
    seeds = set()
    for learner in range(5):
        recording = Recording(TextbookOrder(2))
        run_learner(world, (), PolicySpec("recorded", recording), P, learner)
        seeds.add(recording.seen[0][1].seed)
        assert len({context.seed for _, context in recording.seen}) == 1

    assert len(seeds) == 5


# ---------------------------------------------------------------------------
# The primary metric and the secondary ones
# ---------------------------------------------------------------------------


def test_primary_is_the_equal_weight_mean_of_the_true_probabilities_at_the_end():
    """``random`` gives the concepts unequal numbers of items; each still weighs 1/9."""
    world = _world("strong")
    for index in range(6):
        trace = _trace(world, (), _policy("random"), index)
        learner = _fresh_learner(world, index)
        for attempt in trace.attempts:
            learner.answer(attempt.concept_ids[0])
        p_fresh = {concept: learner.p_correct_fresh(concept) for concept in CONCEPTS}
        counts = Counter(attempt.concept_ids[0] for attempt in trace.attempts)
        weighted_by_attempts = sum(p_fresh[c] * n for c, n in counts.items()) / len(trace.attempts)

        assert trace.outcome.primary == primary_metric(p_fresh, CONCEPTS)
        assert trace.outcome.primary == pytest.approx(sum(p_fresh.values()) / 9, abs=1e-12)
        assert len(set(counts.values())) > 1
        assert abs(trace.outcome.primary - weighted_by_attempts) > 1e-3


@pytest.mark.parametrize("world_id", WORLD_IDS)
@pytest.mark.parametrize("name", ALL_POLICIES)
def test_primary_is_computed_from_the_latent_state_under_every_policy(world_id, name, all_runs):
    """The attempts replayed on a fresh learner give the same answers and the same skills;
    the primary value is the mean of guess + (1 - guess - slip) * skill over the nine
    concepts, and the time to criterion says whether it reached the criterion."""
    world = _world(world_id)
    guess, slip = world.spec.guess, world.spec.slip
    index = 11
    trace = _trace(world, _given("true"), _policy(name), index)
    twin = _fresh_learner(world, index)
    for attempt in trace.attempts:
        assert twin.answer(attempt.concept_ids[0]) == attempt.correct
    expected = sum(guess + (1 - guess - slip) * twin.skill(c) for c in CONCEPTS) / 9

    assert trace.outcome == all_runs[(world_id, name)][index]
    assert trace.outcome.primary == pytest.approx(expected, abs=1e-12)
    reached = trace.outcome.minutes_to_criterion is not None
    assert reached == (trace.outcome.primary >= P.criterion)  # the skill never falls
    if reached:
        assert 0.0 <= trace.outcome.minutes_to_criterion <= trace.outcome.minutes_used


def test_primary_counts_the_slice_concepts_only():
    sliced = replace(P, graph=replace(P.graph, slice=("a1", "c3")))
    world = _world("none", sliced)
    trace = _trace(world, (), _policy("textbook"), 0, sliced)
    learner = _fresh_learner(_world("none"), 0)
    for attempt in trace.attempts:
        learner.answer(attempt.concept_ids[0])

    expected = (learner.p_correct_fresh("a1") + learner.p_correct_fresh("c3")) / 2
    assert trace.outcome.primary == pytest.approx(expected, abs=1e-12)
    assert len(trace.outcome.predictions) == 2
    assert len(trace.attempts) == 18  # the policy still practises the whole book


@pytest.mark.parametrize("world_id", WORLD_IDS)
def test_primary_metric_ignores_the_retention_delay(world_id, all_runs):
    """D is a protocol field with no effect in the core world, which does not forget: every
    outcome of every policy is the same at a delay of 0, of 7 (the smoke run) and of 365 days."""
    world, given = _world(world_id), _given("true")
    assert P.retention_delay_days == 7.0
    for delay in (0.0, 365.0):
        protocol = replace(P, retention_delay_days=delay, learners=3)
        for name in POLICY_NAMES:
            outcomes = run_policy(world, given, _policy(name), protocol)
            assert outcomes == all_runs[(world_id, name)][:3]


def test_time_to_criterion_is_the_first_minute_at_the_criterion_or_censored(strong_true):
    world = _world("strong")
    reached = censored = 0
    for index in range(P.learners):
        trace = _trace(world, _given("true"), _policy("oracle"), index)
        assert trace.outcome == strong_true["oracle"][index]
        learner = _fresh_learner(world, index)
        first = None
        for number, attempt in enumerate(trace.attempts, start=1):
            learner.answer(attempt.concept_ids[0])
            value = primary_metric({c: learner.p_correct_fresh(c) for c in CONCEPTS}, CONCEPTS)
            if first is None and value >= P.criterion:
                first = float(number)  # an item costs one minute

        assert trace.outcome.minutes_to_criterion == first
        reached += first is not None
        censored += first is None

    assert reached > 0 and censored > 0  # both cases occur in the smoke run


def test_a_learner_who_starts_at_the_criterion_has_the_time_zero():
    easy = replace(P, criterion=0.26)  # just above the guess probability of 0.25

    outcome = run_learner(_world("none"), (), _policy("textbook"), easy, 0)

    assert outcome.minutes_to_criterion == 0.0


# ---------------------------------------------------------------------------
# Time: the budget, the cost of actions, simulated timestamps
# ---------------------------------------------------------------------------


def test_no_run_exceeds_the_time_budget(smoke, all_runs):
    """Every run of the smoke matrix, on every given DAG, and the bad policy in every world."""
    every_run = [*smoke.runs.values(), *all_runs.values()]

    assert len(every_run) == 21 + 3 * 6
    for outcomes in every_run:
        for outcome in outcomes:
            assert outcome.minutes_used <= P.time_budget_minutes
            # 18.5 minutes and items of one minute: the 19th item does not fit.
            assert (outcome.minutes_used, outcome.attempts) == (18.0, 18)


@pytest.mark.parametrize(
    ("budget", "item_cost", "items", "minutes"),
    [
        (18.0, 1.0, 18, 18.0),  # an action that fits exactly is started
        (17.99, 1.0, 17, 17.0),
        (10.0, 1.5, 6, 9.0),  # a seventh item would end at 10.5
        (10.0, 3.0, 3, 9.0),
        (0.9, 1.0, 0, 0.0),  # nothing fits: nothing is started
        # Costs that are no binary fractions: 0.1 + 0.1 + 0.1 > 0.3 in floats, and the third
        # item still fits, because simulated time is counted in whole milliseconds.
        (0.3, 0.1, 3, 0.3),
        (0.7, 0.1, 7, 0.7),
        (1.0, 0.1, 10, 1.0),
        (1.2, 0.4, 3, 1.2),
        (3.3, 1.1, 3, 3.3),
        (3.299, 1.1, 2, 2.2),
    ],
)
def test_an_action_that_does_not_fit_the_budget_is_not_started(budget, item_cost, items, minutes):
    protocol = replace(
        P,
        time_budget_minutes=budget,
        time_costs={"item": item_cost, "hint": 0.5, "reading": 2.0},
    )
    for name in ("textbook", "random", "oracle"):
        trace = _trace(_world("strong"), (), _policy(name), 0, protocol)

        assert (trace.outcome.attempts, trace.outcome.minutes_used) == (items, minutes)
        assert len(trace.attempts) == len(trace.decisions) == items
        assert trace.outcome.minutes_used <= budget
        assert [attempt.timestamp for attempt in trace.attempts] == [
            SIM_EPOCH + timedelta(milliseconds=round(item_cost * 60_000) * number)
            for number in range(1, items + 1)
        ]


def test_hints_and_reading_cost_time_and_the_session_ends_at_the_first_action_that_does_not_fit():
    """Reading 2.0, hint 0.5, item 1.0 on a1, again and again: five rounds are 17.5 minutes.
    The sixth reading would end at 19.5, past the budget of 18.5, so the session ends, though
    a hint or an item would still fit."""
    spec = PolicySpec(
        "scripted", Scripted((("reading", "a1"), ("hint", "a1"), ("next_concept", "a1")))
    )
    trace = _trace(_world("strong"), (), spec, 0)

    assert trace.outcome.minutes_used == 17.5
    assert trace.outcome.attempts == 5
    assert len(trace.decisions) == 15  # the sixteenth decision was not started
    assert [attempt.timestamp for attempt in trace.attempts] == [
        sim_timestamp(3.5 * round_) for round_ in range(1, 6)
    ]
    assert all(attempt.assisted for attempt in trace.attempts)
    assert all(attempt.latency_ms == 60_000 for attempt in trace.attempts)


def test_time_spent_on_help_is_not_spent_on_items():
    world = _world("none")
    helped = PolicySpec("scripted", Scripted((("reading", "a1"), ("next_concept", "a1"))))
    plain = PolicySpec("scripted", Scripted((("next_concept", "a1"),)))

    with_help = run_learner(world, (), helped, P, 0)
    without = run_learner(world, (), plain, P, 0)

    assert (with_help.attempts, with_help.minutes_used) == (6, 18.0)
    assert (without.attempts, without.minutes_used) == (18, 18.0)
    assert with_help.primary < without.primary  # help changes nothing else in the core world


def test_assisted_marks_the_next_item_on_the_helped_concept_only():
    script = (
        ("next_concept", "a1"),
        ("hint", "a2"),
        ("next_concept", "a1"),  # the hint was on a2
        ("next_concept", "a2"),  # assisted
        ("next_concept", "a2"),  # the flag is used up
        ("reading", "a1"),
        ("next_concept", "a1"),  # assisted
    )
    short = replace(P, time_budget_minutes=7.5)
    trace = _trace(_world("strong"), (), PolicySpec("scripted", Scripted(script)), 0, short)

    assert [(attempt.concept_ids[0], attempt.assisted) for attempt in trace.attempts] == [
        ("a1", False),
        ("a1", False),
        ("a2", True),
        ("a2", False),
        ("a1", True),
    ]
    assert trace.outcome.minutes_used == 5 * 1.0 + 0.5 + 2.0


@pytest.mark.parametrize(
    "action",
    [("teleport", "a1"), ("next_concept", "zz"), ("hint", "zz")],
    ids=["unknown-kind", "unknown-concept", "hint-on-unknown-concept"],
)
def test_an_action_the_runner_does_not_know_is_an_error(action):
    spec = PolicySpec("scripted", Scripted((action,)))

    with pytest.raises(ValueError, match="does not know the action"):
        run_learner(_world("strong"), (), spec, P, 0)


def test_simulated_attempts_are_marked_sim_and_carry_record_ids():
    world = _world("strong")
    trace = _trace(world, _given("precision-0.8"), _policy("ready-first"), 9)

    assert len(trace.attempts) == len(trace.decisions) == 18
    numbers: Counter[str] = Counter()
    for attempt, record in zip(trace.attempts, trace.decisions, strict=True):
        concept = str(record.action["concept"])
        assert attempt.source == "sim"
        assert attempt.decision_record_id == record.record_id()
        assert len(attempt.decision_record_id) == 16
        assert attempt.learner_id == "sim-9"
        assert attempt.concept_ids == (concept,)
        assert attempt.item_id == f"sim:{concept}:medium:{numbers[concept]}"
        assert attempt.chosen_option_id is None
        assert attempt.latency_ms == 60_000
        assert attempt.assisted is False
        assert dict(attempt.model_versions) == {
            "policy": "ready-first",
            "sequencer": "ready-first-v1",
            "difficulty": "fixed-medium",
            "estimator": "bkt-fixed-v1",
            "world": "gated-continuous-growth-v1",
        }
        assert tuple(json.loads(json.dumps(attempt.to_row()))) == ATTEMPT_FIELDS
        numbers[concept] += 1
    assert len({attempt.item_id for attempt in trace.attempts}) == 18  # every item is fresh
    assert len({attempt.decision_record_id for attempt in trace.attempts}) > 1


def test_band_v1_attempts_name_the_production_policy():
    trace = _trace(_world("strong"), (), _policy("band-v1"), 0)

    assert {attempt.model_versions["difficulty"] for attempt in trace.attempts} == {"band-v1"}
    assert {attempt.model_versions["policy"] for attempt in trace.attempts} == {"band-v1"}
    assert {attempt.model_versions["sequencer"] for attempt in trace.attempts} == {"textbook-v1"}


def test_timestamps_are_simulated_time_never_the_clock():
    """An item costs one minute: the k-th answer is stamped k minutes after the epoch of
    simulated time, in the year 2000, and a second run gives the same records."""
    world = _world("strong")
    before = datetime.now().astimezone()
    first = _trace(world, _given("true"), _policy("ready-first"), 2)
    second = _trace(world, _given("true"), _policy("ready-first"), 2)

    assert [attempt.timestamp for attempt in first.attempts] == [
        sim_timestamp(float(number)) for number in range(1, 19)
    ]
    assert first.attempts[0].timestamp == SIM_EPOCH.replace(minute=1)
    assert {attempt.timestamp.year for attempt in first.attempts} == {2000}
    assert all(attempt.timestamp < before for attempt in first.attempts)
    assert all(attempt.timestamp.utcoffset() is not None for attempt in first.attempts)
    assert first.attempts == second.attempts
    assert first.decisions == second.decisions
    assert first.outcome == second.outcome


def test_timestamps_follow_the_cost_of_an_item():
    protocol = replace(P, time_costs={"item": 2.5, "hint": 0.5, "reading": 2.0})
    trace = _trace(_world("strong"), (), _policy("textbook"), 0, protocol)

    assert [attempt.timestamp for attempt in trace.attempts] == [
        sim_timestamp(2.5 * number) for number in range(1, 8)
    ]
    assert {attempt.latency_ms for attempt in trace.attempts} == {150_000}
    assert trace.outcome.minutes_used == 17.5


def test_observers_do_not_change_a_run(strong_true):
    world, given = _world("strong"), _given("true")
    for name in ("random", "band-v1", "ready-first", "oracle"):
        assert _trace(world, given, _policy(name), 11).outcome == strong_true[name][11]


def test_the_block_length_of_the_protocol_reaches_ready_first_and_the_oracle():
    longer = replace(P, textbook_items_per_concept=3)

    for name in ("ready-first", "oracle"):
        assert _policy(name, longer).sequencer == ReadyFirst(0.6, 3)
        assert run_policy(
            _world("strong"), _given("true"), _policy(name, longer), replace(longer, learners=3)
        ) != run_policy(_world("strong"), _given("true"), _policy(name), replace(P, learners=3))


def test_ready_first_with_another_threshold_is_another_policy():
    """The protocol's threshold reaches the sequencer."""
    strict = replace(P, mastery_threshold=0.95)

    assert _policy("ready-first", strict).sequencer == ReadyFirst(0.95, 2)
    assert run_policy(
        _world("strong"),
        _given("true"),
        _policy("ready-first", strict),
        replace(strict, learners=6),
    ) != (
        run_policy(_world("strong"), _given("true"), _policy("ready-first"), replace(P, learners=6))
    )
