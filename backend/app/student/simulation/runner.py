"""
The simulation runner (#307): one learner under one policy, and the whole matrix.

One step of ``run_learner``:

1. The sequencing policy decides from the state it is allowed to see (nothing, the
   production estimate, or the true skill for the oracle) and the edges it is allowed to see
   (none, the given DAG of the cell, or the true DAG for the oracle).
2. The action is charged against the time budget. An action that does not fit what is left
   is not started, and the session ends.
3. For an item, the difficulty policy (``band-v1``) decides the band from the estimate, the
   learner answers and learns, and the answer goes through the production update
   (``estimator.apply_answer``, BKT with its fixed parameters). The simulator has no copy of
   that update and no copy of a production policy.

In the core world the band changes nothing: the learner ignores it and an item costs the
same whatever its band. The decision is still taken, reported and written into the item id,
so the robustness worlds of #311 can use it. A hint and a reading cost time and make the
next item on the concept assisted; they change nothing else in the core world.

An attempt record has one ``decision_record_id``. Here it names the sequencing decision,
the one that chose the concept. When a difficulty policy also decided the item's band, that
second record goes to ``on_decision`` and its band into the item id; its id is not on the
attempt. Which decision the field names when an item follows two is for #308 to settle.

Simulated time starts at 0 and only moves by the cost of an action. It is counted in whole
milliseconds (``protocol.minutes_to_ms``), so an action that fits the budget exactly is
started and no float sum decides where a session ends. The session ends at the first chosen
action that does not fit, also when a cheaper action would. No clock is read: timestamps are
``attempts.sim_timestamp`` of the simulated minutes.

The estimate starts from ``INITIAL_MASTERY``, a constant here and not the setting, and no
setting reaches a run, so an ``.env`` cannot change a result. It can stop one: importing
this package imports ``backend.app.student.models`` and with it the settings object, which
reads the environment and refuses values the application refuses.

``run_matrix`` runs every world of a protocol against every given DAG. A policy that does
not see the given DAG gives the same result in every DAG cell of a world, so it is run once
per world and shared.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from backend.app.student.attempts import SIM_EPOCH, Attempt, sim_timestamp
from backend.app.student.estimator import apply_answer
from backend.app.student.models import StudentProfile
from backend.app.student.policy.band import Difficulty, difficulty_of
from backend.app.student.policy.base import (
    DecisionContext,
    DecisionRecord,
    EdgeUse,
    LearnerState,
    policy_key,
)
from backend.app.student.simulation.dags import DagSpec, given_dag, precision_recall, true_dag
from backend.app.student.simulation.metrics import (
    Cell,
    auc,
    decision,
    mc_standard_error,
    mean,
    paired_effect,
    primary_metric,
    standard_deviation,
    time_to_criterion,
)
from backend.app.student.simulation.policies import (
    FIXED_DIFFICULTY,
    KIND_HINT,
    KIND_ITEM,
    KIND_READING,
    PolicySpec,
    build_policy,
)
from backend.app.student.simulation.protocol import (
    MS_PER_MINUTE,
    SimulationProtocol,
    minutes_to_ms,
)
from backend.app.student.simulation.worlds import Learner, World, WorldSpec, stream_seed

SCHEMA_VERSION: Final = 1
"""Version of the report ``run_matrix`` returns."""

INITIAL_MASTERY: Final = 0.3
"""The estimate of a concept without history: the default of STUDENT_INITIAL_MASTERY."""

ESTIMATOR: Final = "bkt-fixed-v1"
"""The estimate a policy sees: the production update with BKT on and its default parameters."""

_COST_OF_KIND: Final[Mapping[str, str]] = {
    KIND_ITEM: "item",
    KIND_HINT: "hint",
    KIND_READING: "reading",
}

_NO_STATE: Final = LearnerState(mastery={}, initial_mastery=INITIAL_MASTERY)
"""What a sequencer that sees no learner state receives."""

_Spec = TypeVar("_Spec", WorldSpec, DagSpec)


@dataclass(frozen=True, slots=True)
class LearnerOutcome:
    """What one learner reached under one policy."""

    learner: int
    primary: float
    """The primary metric at the end of the budget."""
    minutes_used: float
    """Simulated minutes spent; never more than the budget."""
    minutes_to_criterion: float | None
    """Minutes after which the primary value first reached the criterion; None if never."""
    attempts: int
    """Items answered."""
    predictions: tuple[tuple[float, bool], ...]
    """Per slice concept, at the end of the budget: the estimate, and whether the true skill
    is at or above the mastery threshold."""


def _estimate(profile: StudentProfile) -> LearnerState:
    """The production estimate, as the state a policy receives."""
    mastery = {concept: record.mastery_level for concept, record in profile.mastery_map.items()}
    return LearnerState(mastery=mastery, initial_mastery=INITIAL_MASTERY)


def _estimate_of(profile: StudentProfile, concept: str) -> float:
    """The production estimate of one concept; ``INITIAL_MASTERY`` without history."""
    record = profile.mastery_map.get(concept)
    return INITIAL_MASTERY if record is None else record.mastery_level


def _truth(learner: Learner) -> LearnerState:
    """The true skill of every concept, as the state the oracle receives."""
    mastery = {concept: learner.skill(concept) for concept in learner.world.graph.concepts}
    return LearnerState(mastery=mastery, initial_mastery=INITIAL_MASTERY)


def run_learner(
    world: World,
    given: tuple[EdgeUse, ...],
    spec: PolicySpec,
    protocol: SimulationProtocol,
    learner_index: int,
    *,
    on_attempt: Callable[[Attempt], None] | None = None,
    on_decision: Callable[[DecisionRecord], None] | None = None,
) -> LearnerOutcome:
    """
    Simulate one learner under one policy until the time budget ends.

    Args:
        world: The world the learner lives in
        given: The given DAG of the cell; only a policy with ``dag_source`` "given" sees it
        spec: The policy
        protocol: Seed, budget, costs, criterion and thresholds
        learner_index: Which learner; the same index is the same learner under every policy
        on_attempt: Called with the attempt record of every answered item; its
            ``decision_record_id`` is the id of the sequencing decision
        on_decision: Called with the record of every decision whose action was started: the
            sequencing decision, then the difficulty decision of an item if there is one

    Raises:
        ValueError: If a policy returns an action the runner does not know
    """
    graph = world.graph
    learner = Learner(
        world, world.traits(protocol.master_seed, learner_index), protocol.master_seed
    )
    learner_id = f"sim-{learner_index}"
    profile = StudentProfile(
        student_id=learner_id,
        overall_ability=INITIAL_MASTERY,
        created_at=SIM_EPOCH,
        updated_at=SIM_EPOCH,
    )
    edges: tuple[EdgeUse, ...] = ()
    if spec.dag_source == "given":
        edges = given
    elif spec.dag_source == "true":
        edges = true_dag(graph)
    policy_seed = stream_seed(protocol.master_seed, learner_index, "policy")
    band_source = f"fixed-{FIXED_DIFFICULTY}"
    if spec.difficulty is not None:
        band_source = policy_key(spec.difficulty)
    versions = {
        "policy": spec.name,
        "sequencer": policy_key(spec.sequencer),
        "difficulty": band_source,
        "estimator": ESTIMATOR,
        "world": world.family,
    }

    known_concepts = frozenset(graph.concepts)
    delay = protocol.retention_delay_days
    p_fresh = {concept: learner.p_correct_fresh(concept, delay) for concept in graph.slice}
    primary = primary_metric(p_fresh, graph.slice)
    minutes_to_criterion = 0.0 if primary >= protocol.criterion else None

    budget_ms = minutes_to_ms(protocol.time_budget_minutes)
    cost_ms = {
        kind: minutes_to_ms(protocol.time_costs[name]) for kind, name in _COST_OF_KIND.items()
    }
    elapsed_ms = 0
    step = 0
    attempts = 0
    assisted: set[str] = set()

    while True:
        if spec.state_source == "estimate":
            state = _estimate(profile)
        elif spec.state_source == "truth":
            state = _truth(learner)
        else:
            state = _NO_STATE
        context = DecisionContext(
            candidates=graph.concepts, edges=edges, step=step, seed=policy_seed
        )
        record = spec.sequencer.decide(state, context)
        kind, concept = record.action.get("kind"), record.action.get("concept")
        if kind not in _COST_OF_KIND or concept not in known_concepts:
            raise ValueError(f"The runner does not know the action {dict(record.action)!r}")
        concept = str(concept)
        cost = cost_ms[str(kind)]
        if elapsed_ms + cost > budget_ms:
            break  # does not fit what is left: not started
        if on_decision is not None:
            on_decision(record)
        step += 1
        elapsed_ms += cost

        if kind != KIND_ITEM:
            assisted.add(concept)
            continue

        difficulty: Difficulty = FIXED_DIFFICULTY
        if spec.difficulty is not None:
            difficulty_record = spec.difficulty.decide(
                _estimate(profile), DecisionContext(concept=concept)
            )
            difficulty = difficulty_of(difficulty_record)
            if on_decision is not None:
                on_decision(difficulty_record)

        item_number = learner.items_answered(concept)
        correct = learner.answer(concept, difficulty)
        answered_at = sim_timestamp(elapsed_ms / MS_PER_MINUTE)
        apply_answer(
            profile,
            concept,
            correct,
            initial_mastery=INITIAL_MASTERY,
            bkt_enabled=True,
            now=answered_at,
        )
        attempts += 1
        if on_attempt is not None:
            on_attempt(
                Attempt(
                    learner_id=learner_id,
                    item_id=f"sim:{concept}:{difficulty}:{item_number}",
                    concept_ids=(concept,),
                    chosen_option_id=None,
                    correct=correct,
                    latency_ms=cost,
                    assisted=concept in assisted,
                    decision_record_id=record.record_id(),
                    model_versions=versions,
                    source="sim",
                    timestamp=answered_at,
                )
            )
        assisted.discard(concept)

        if concept in p_fresh:
            p_fresh[concept] = learner.p_correct_fresh(concept, delay)
        if minutes_to_criterion is None:
            primary = primary_metric(p_fresh, graph.slice)
            if primary >= protocol.criterion:
                minutes_to_criterion = elapsed_ms / MS_PER_MINUTE

    return LearnerOutcome(
        learner=learner_index,
        primary=primary_metric(p_fresh, graph.slice),
        minutes_used=elapsed_ms / MS_PER_MINUTE,
        minutes_to_criterion=minutes_to_criterion,
        attempts=attempts,
        predictions=tuple(
            (_estimate_of(profile, concept), learner.skill(concept) >= protocol.mastery_threshold)
            for concept in graph.slice
        ),
    )


def run_policy(
    world: World, given: tuple[EdgeUse, ...], spec: PolicySpec, protocol: SimulationProtocol
) -> tuple[LearnerOutcome, ...]:
    """Every learner of the protocol under one policy, in learner order."""
    return tuple(
        run_learner(world, given, spec, protocol, learner_index)
        for learner_index in range(protocol.learners)
    )


def _select(specs: Sequence[_Spec], wanted: Sequence[str] | None, label: str) -> tuple[_Spec, ...]:
    """The protocol's specs, or those with the wanted ids in protocol order."""
    if wanted is None:
        return tuple(specs)
    unknown = sorted(set(wanted) - {spec.id for spec in specs})
    if unknown:
        raise KeyError(f"The protocol has no {label} {unknown}")
    return tuple(spec for spec in specs if spec.id in wanted)


def _summary(outcomes: Sequence[LearnerOutcome], protocol: SimulationProtocol) -> dict[str, Any]:
    primary = [outcome.primary for outcome in outcomes]
    return {
        "primary": {
            "mean": mean(primary),
            "sd": standard_deviation(primary),
            "mc_se": mc_standard_error(primary),
        },
        "time_to_criterion": time_to_criterion(
            [outcome.minutes_to_criterion for outcome in outcomes], protocol.time_budget_minutes
        ),
        "auc": auc([pair for outcome in outcomes for pair in outcome.predictions]),
        "mean_minutes_used": mean([outcome.minutes_used for outcome in outcomes]),
        "mean_attempts": mean([float(outcome.attempts) for outcome in outcomes]),
    }


def _effect(
    treatment: Sequence[LearnerOutcome],
    baseline: Sequence[LearnerOutcome],
    protocol: SimulationProtocol,
) -> dict[str, Any]:
    return paired_effect(
        [outcome.primary for outcome in treatment],
        [outcome.primary for outcome in baseline],
        resamples=protocol.bootstrap_resamples,
        seed=protocol.master_seed,
    )


def run_matrix(
    protocol: SimulationProtocol,
    *,
    worlds: Sequence[str] | None = None,
    dags: Sequence[str] | None = None,
    policies: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Run the protocol's worlds against its given DAGs and report every cell.

    Args:
        protocol: The protocol
        worlds: World ids to run; None for all
        dags: DAG ids to run; None for all
        policies: Policy names to run; None for the protocol's

    Returns:
        A report of plain JSON values (render it with ``metrics.render_json``):
        ``schema_version``; ``simulator``; ``protocol`` (the parameters); ``selection``
        (what was run); ``dags`` (each variant's edge count, precision and recall);
        ``policy_runs`` (how many times a policy was run over the learners); ``cells``,
        one per world and DAG, with a summary per policy, the protocol's ``contrasts`` and,
        for a policy that sees the given DAG, ``dag_effects``: its paired effect against
        itself on the true DAG; and ``decisions``: the decision rule per contrast, when the
        primary cell was run. Floats are not rounded.

    Raises:
        KeyError: If a selected world, DAG or policy is unknown
    """
    world_specs = _select(protocol.worlds, worlds, "world")
    dag_specs = _select(protocol.dags, dags, "DAG")
    names = protocol.policies if policies is None else tuple(policies)
    specs = [
        build_policy(
            name,
            mastery_threshold=protocol.mastery_threshold,
            items_per_concept=protocol.textbook_items_per_concept,
        )
        for name in names
    ]
    given = {dag.id: given_dag(protocol.graph, dag, protocol.master_seed) for dag in dag_specs}
    reference = next((dag.id for dag in dag_specs if dag.kind == "true"), None)
    contrasts = [pair for pair in protocol.contrasts if pair[0] in names and pair[1] in names]

    cells: list[dict[str, Any]] = []
    effects: dict[tuple[str, str], dict[Cell, float]] = {pair: {} for pair in contrasts}
    policy_runs = 0
    for world_spec in world_specs:
        world = World(world_spec, protocol.graph)
        shared: dict[str, tuple[LearnerOutcome, ...]] = {}
        by_dag: dict[str, dict[str, tuple[LearnerOutcome, ...]]] = {dag.id: {} for dag in dag_specs}
        for spec in specs:
            if spec.dag_source != "given":
                shared[spec.name] = run_policy(world, (), spec, protocol)
                policy_runs += 1
                continue
            for dag in dag_specs:
                by_dag[dag.id][spec.name] = run_policy(world, given[dag.id], spec, protocol)
                policy_runs += 1

        for dag in dag_specs:
            outcomes = {name: by_dag[dag.id].get(name) or shared[name] for name in names}
            cell_contrasts = []
            for policy, baseline in contrasts:
                effect = _effect(outcomes[policy], outcomes[baseline], protocol)
                effects[(policy, baseline)][(world_spec.id, dag.id)] = effect["mean_difference"]
                cell_contrasts.append({"policy": policy, "baseline": baseline, **effect})
            cells.append(
                {
                    "world": world_spec.id,
                    "dag": dag.id,
                    "policies": {name: _summary(outcomes[name], protocol) for name in names},
                    "contrasts": cell_contrasts,
                    "dag_effects": [
                        {
                            "policy": name,
                            "reference_dag": reference,
                            **_effect(by_dag[dag.id][name], by_dag[reference][name], protocol),
                        }
                        for name in by_dag[dag.id]
                        if reference is not None and dag.id != reference
                    ],
                }
            )

    dag_report = {}
    for dag in dag_specs:
        precision, recall = precision_recall(given[dag.id], protocol.graph)
        dag_report[dag.id] = {
            "kind": dag.kind,
            "level": dag.level,
            "edges": len(given[dag.id]),
            "precision": precision,
            "recall": recall,
        }

    primary_cell = protocol.primary_cell
    return {
        "schema_version": SCHEMA_VERSION,
        "simulator": {
            "world_family": World.family,
            "estimator": ESTIMATOR,
            "initial_mastery": INITIAL_MASTERY,
        },
        "protocol": protocol.to_dict(),
        "selection": {
            "worlds": [world.id for world in world_specs],
            "dags": [dag.id for dag in dag_specs],
            "policies": list(names),
        },
        "dags": dag_report,
        "policy_runs": policy_runs,
        "cells": cells,
        "decisions": [
            {
                "policy": policy,
                "baseline": baseline,
                "delta": protocol.delta,
                "primary_cell": list(primary_cell),
                **decision(cell_effects, primary_cell, protocol.delta),
            }
            for (policy, baseline), cell_effects in effects.items()
            if primary_cell in cell_effects
        ],
    }
