"""
The simulation protocol as a typed value, and the protocol of the CI smoke test (#307).

A ``SimulationProtocol`` holds everything a run depends on: the seed, the number of
learners, the graph, the time budget and what each action costs, the worlds, the given-DAG
variants, the policies, the contrasts and the decision rule's delta and primary cell. A run
is a function of its protocol and nothing else.

``SMOKE_PROTOCOL`` is the small protocol of the CI smoke test: the hand-written fixture
graph and a few dozen learners. Its values are its own, so the values the maintainer freezes
for the full matrix cannot break CI. It has the status "draft" and supports no claim.

The frozen protocol, its file and ``docs/evals/simulation-protocol.md`` come with the
second pull request of #307. Nothing here loads a file.

Fields that have no effect in the core world: ``retention_delay_days`` (no forgetting until
#311) and the costs of a hint and of reading for the policies of this package, none of
which takes those actions.

Simulated time is counted in whole milliseconds (``minutes_to_ms``). The budget and every
cost are given in minutes and must be a whole number of milliseconds, so a sum of costs is
exact and an action that fits the budget exactly is started, whatever the values (ten items
of 0.1 minutes fit one minute).
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Final, Literal

from backend.app.student.simulation.dags import STANDARD_DAGS, DagSpec
from backend.app.student.simulation.policies import BAD_POLICY, POLICY_NAMES
from backend.app.student.simulation.worlds import FIXTURE_GRAPH, ConceptGraph, WorldSpec

ACTION_COSTS: Final[tuple[str, ...]] = ("item", "hint", "reading")
"""The actions that cost time. An item costs the same whatever its difficulty band."""

ProtocolStatus = Literal["draft", "frozen"]

MS_PER_MINUTE: Final = 60_000
"""Simulated time is counted in whole milliseconds."""

_WHOLE_MS_TOLERANCE: Final = 1e-6
"""How far, in milliseconds, a value in minutes may be from a whole millisecond: room for
the rounding of a decimal such as 0.1, and nothing more."""


def minutes_to_ms(minutes: float) -> int:
    """Simulated minutes as whole milliseconds.

    Raises:
        ValueError: If the value is not a whole number of milliseconds
    """
    scaled = minutes * MS_PER_MINUTE
    whole = round(scaled)
    if abs(scaled - whole) > _WHOLE_MS_TOLERANCE:
        raise ValueError(f"{minutes!r} minutes is not a whole number of milliseconds")
    return whole


@dataclass(frozen=True, slots=True)
class SimulationProtocol:
    """Everything a simulation run depends on.

    Raises:
        ValueError: If a value is outside its range, the budget or a cost is not a whole
            number of milliseconds, an id repeats, the primary cell, a policy or a contrast
            names something the protocol does not list, or a frozen protocol lists the
            test-only policy
    """

    version: str
    status: ProtocolStatus
    """"draft" until the maintainer freezes the values; a frozen version is never edited."""
    master_seed: int
    learners: int
    """Simulated learners per policy; the same learners under every policy."""
    graph: ConceptGraph
    time_budget_minutes: float
    """Simulated minutes per learner. An action that does not fit what is left is not started."""
    time_costs: Mapping[str, float]
    """Minutes per action, keyed by ``ACTION_COSTS``; each at least one millisecond."""
    retention_delay_days: float
    """The delay D of the primary metric. No effect in the core world (no forgetting)."""
    criterion: float
    """Time to criterion: the level of a learner's primary value that counts as reached."""
    mastery_threshold: float
    """What "mastered" means: the threshold ``ready-first`` and the oracle apply to the state
    they see, and the level of true skill that is the positive label of the AUC."""
    textbook_items_per_concept: int
    """The block length of textbook order, and of the turns ``ready-first`` and the oracle
    give the ready concepts."""
    delta: float
    """Decision rule: the smallest effect that counts, absolute, on the primary metric."""
    primary_cell: tuple[str, str]
    """Decision rule: the (world id, DAG id) in which a gain of delta is required."""
    worlds: tuple[WorldSpec, ...]
    dags: tuple[DagSpec, ...]
    policies: tuple[str, ...]
    contrasts: tuple[tuple[str, str], ...]
    """(policy, baseline) pairs: the effect reported is policy minus baseline."""
    bootstrap_resamples: int
    """Resamples of the percentile interval of each effect; 0 for no interval."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_costs", MappingProxyType(dict(self.time_costs)))
        object.__setattr__(self, "primary_cell", tuple(self.primary_cell))
        object.__setattr__(self, "worlds", tuple(self.worlds))
        object.__setattr__(self, "dags", tuple(self.dags))
        object.__setattr__(self, "policies", tuple(self.policies))
        object.__setattr__(self, "contrasts", tuple(tuple(pair) for pair in self.contrasts))

        if self.status not in ("draft", "frozen"):
            raise ValueError(f"status must be 'draft' or 'frozen', got {self.status!r}")
        if self.learners < 2:
            raise ValueError("A protocol needs at least two learners")
        if self.time_budget_minutes <= 0:
            raise ValueError("The time budget must be positive")
        if set(self.time_costs) != set(ACTION_COSTS) or min(self.time_costs.values()) <= 0:
            raise ValueError(f"time_costs needs a positive cost for each of {ACTION_COSTS}")
        for minutes in (self.time_budget_minutes, *self.time_costs.values()):
            if minutes_to_ms(minutes) < 1:
                raise ValueError("The time budget and every cost need at least one millisecond")
        if self.retention_delay_days < 0:
            raise ValueError("The retention delay must not be negative")
        for name in ("criterion", "mastery_threshold"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must lie in (0, 1], got {getattr(self, name)!r}")
        if self.textbook_items_per_concept < 1:
            raise ValueError("textbook_items_per_concept must be at least 1")
        if self.delta <= 0:
            raise ValueError("delta must be positive")
        if self.bootstrap_resamples < 0:
            raise ValueError("bootstrap_resamples must not be negative")

        world_ids = [world.id for world in self.worlds]
        dag_ids = [dag.id for dag in self.dags]
        for label, ids in (("world", world_ids), ("DAG", dag_ids), ("policy", self.policies)):
            if not ids or len(set(ids)) != len(ids):
                raise ValueError(f"A protocol needs at least one {label} and no id twice")
        if len([dag for dag in self.dags if dag.kind == "true"]) > 1:
            raise ValueError("A protocol lists the true DAG at most once")
        if self.primary_cell[0] not in world_ids or self.primary_cell[1] not in dag_ids:
            raise ValueError(f"The primary cell {self.primary_cell!r} is not in the matrix")
        unknown = sorted(set(self.policies) - {*POLICY_NAMES, BAD_POLICY})
        if unknown:
            raise ValueError(f"Unknown policies: {unknown}")
        if self.status == "frozen" and BAD_POLICY in self.policies:
            raise ValueError(f"A frozen protocol does not list the test-only policy {BAD_POLICY!r}")
        for policy, baseline in self.contrasts:
            if policy not in self.policies or baseline not in self.policies:
                raise ValueError(
                    f"The contrast ({policy!r}, {baseline!r}) names an unlisted policy"
                )

    def __reduce__(self) -> tuple[Any, ...]:
        # Pickling and copying rebuild the protocol: the read-only costs cannot be pickled.
        values = {field.name: getattr(self, field.name) for field in fields(self)}
        values["time_costs"] = dict(self.time_costs)
        return (type(self), tuple(values.values()))

    def __hash__(self) -> int:
        # The generated hash would fail on the read-only costs.
        values = {field.name: getattr(self, field.name) for field in fields(self)}
        values["time_costs"] = tuple(sorted(self.time_costs.items()))
        return hash(tuple(values.values()))

    def to_dict(self) -> dict[str, Any]:
        """The protocol as plain JSON values: the parameters a report echoes."""
        return {
            "version": self.version,
            "status": self.status,
            "master_seed": self.master_seed,
            "learners": self.learners,
            "graph": self.graph.to_dict(),
            "time_budget_minutes": self.time_budget_minutes,
            "time_costs": dict(self.time_costs),
            "retention_delay_days": self.retention_delay_days,
            "criterion": self.criterion,
            "mastery_threshold": self.mastery_threshold,
            "textbook_items_per_concept": self.textbook_items_per_concept,
            "delta": self.delta,
            "primary_cell": list(self.primary_cell),
            "worlds": [world.to_dict() for world in self.worlds],
            "dags": [dag.to_dict() for dag in self.dags],
            "policies": list(self.policies),
            "contrasts": [list(pair) for pair in self.contrasts],
            "bootstrap_resamples": self.bootstrap_resamples,
        }


def _smoke_world(strength: Literal["none", "weak", "strong"]) -> WorldSpec:
    return WorldSpec(
        id=strength,
        prereq_strength=strength,
        leak=0.1,
        contradicting_share=0.2,
        learning_rate_range=(0.5, 1.5),
        base_gain=0.3,
        guess=0.25,
        slip=0.1,
        initial_skill_max=0.3,
    )


SMOKE_DAGS: Final[tuple[DagSpec, ...]] = tuple(
    dag for dag in STANDARD_DAGS if dag.id in ("true", "precision-0.8", "reversed-0.2")
)
"""The given DAGs of the smoke test: the true one, one with false edges and one with reversed
edges. Three keep the test short; every variant has its own tests."""

SMOKE_PROTOCOL: Final = SimulationProtocol(
    version="smoke-1",
    status="draft",
    master_seed=307,
    learners=24,
    graph=FIXTURE_GRAPH,
    # One pass of textbook order (9 concepts, 2 items each) and half a minute that no
    # item fits into.
    time_budget_minutes=18.5,
    time_costs={"item": 1.0, "hint": 0.5, "reading": 2.0},
    retention_delay_days=7.0,
    criterion=0.5,
    mastery_threshold=0.6,
    textbook_items_per_concept=2,
    delta=0.02,
    primary_cell=("weak", "precision-0.8"),
    worlds=(_smoke_world("none"), _smoke_world("weak"), _smoke_world("strong")),
    dags=SMOKE_DAGS,
    policies=POLICY_NAMES,
    contrasts=(("band-v1", "textbook"), ("ready-first", "textbook"), ("oracle", "random")),
    bootstrap_resamples=50,
)
"""The protocol of the CI smoke test."""
