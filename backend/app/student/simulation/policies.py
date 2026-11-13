"""
Policies of the learner simulator (#307): which concept to practise next.

A sequencing policy implements the ``Policy`` interface of ``backend/app/student/policy/``
and returns a ``DecisionRecord``. Its action is ``{"kind": "next_concept", "concept": c}``:
practise one item of c. A policy may also return the kind ``hint`` or ``reading`` with a
concept; the runner charges their time (none of the policies here does).

| Name              | Sequencer                         | State it sees | DAG it sees |
| ----------------- | --------------------------------- | ------------- | ----------- |
| ``random``        | ``RandomOrder``                   | none          | none        |
| ``textbook``      | ``TextbookOrder``                 | none          | none        |
| ``band-v1``       | ``TextbookOrder`` and ``BAND_V1`` | none          | none        |
| ``ready-first``   | ``ReadyFirst``                    | the estimate  | the given   |
| ``oracle``        | ``ReadyFirst``                    | the truth     | the true    |
| ``stuck-on-last`` | ``StuckOnLast`` (tests only)      | none          | none        |

A sequencer that sees no state gets an empty one, and one that sees no DAG gets no edges,
so neither can depend on what it does not declare.

``band-v1`` adds the production difficulty decision to textbook order: ``BAND_V1`` decides
the band of each item from the estimate. It is imported, never copied. Policies without a
difficulty policy ask for ``FIXED_DIFFICULTY``.

``ready-first`` is a selection-only probe, not a candidate for production: it is the policy
that reads the given DAG. It has no correctives and no spaced mastery criterion. A concept
is ready when it is not estimated as mastered and all its prerequisites in the given DAG
are. The probe applies textbook order to the ready concepts: the blocks of ``textbook``,
going round the list of ready concepts in book order. When no concept is ready it falls back
to textbook order over all concepts. ``oracle`` is the same rule on the true DAG and the
true skill: the best-informed run of this rule, not a bound on other rules.

Why the probe goes round the ready concepts and does not take the first of them. Book order
is a topological order of the true DAG, and of every given DAG whose edges all point forward
in book order. In such a DAG the first concept in book order that is not mastered has only
earlier prerequisites, all mastered, so it is always ready. A rule that takes the first
ready concept therefore chooses the same concept whatever forward edges it is given, and
of the variants in ``dags.py`` only the reversed ones have a backward edge. Going round
gives every ready concept its block, so a missing edge lets the probe start a concept too
early and a false edge holds one back. This definition is a draft: the probe is defined in
the protocol, which the maintainer freezes (#307).

A record lists what the policy read. Record mappings hold JSON scalars only, so the
candidates are written as one JSON array in a string, and ``ReadyFirst`` writes one
``mastery:<concept>`` entry per concept it read. A policy's own parameters (the block
length, the mastery threshold) are written into ``context_used`` as well: two decisions with
equal records had equal inputs.

The policies read no clock and no setting. ``RandomOrder`` draws from
``worlds.stream``, seeded by ``context.seed`` and ``context.step``.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import ClassVar, Final, Literal

from backend.app.student.policy.band import BAND_V1, Difficulty
from backend.app.student.policy.base import (
    DecisionContext,
    DecisionRecord,
    EdgeUse,
    LearnerState,
    Policy,
)
from backend.app.student.simulation.worlds import stream

KIND_ITEM: Final = "next_concept"
"""Action kind: practise one item of the concept."""
KIND_HINT: Final = "hint"
"""Action kind: give a hint on the concept. It costs time; the next item on it is assisted."""
KIND_READING: Final = "reading"
"""Action kind: re-read the concept's source. Costs time; the next item on it is assisted."""

FIXED_DIFFICULTY: Final[Difficulty] = "medium"
"""The band a policy without a difficulty policy asks for."""

StateSource = Literal["none", "estimate", "truth"]
DagSource = Literal["none", "given", "true"]


@lru_cache(maxsize=64)
def _encode(candidates: tuple[str, ...]) -> str:
    """The candidates as one JSON array, the form a record's scalar mapping can hold."""
    return json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))


def _candidates(context: DecisionContext) -> tuple[str, ...]:
    if not context.candidates:
        raise ValueError("A sequencing policy needs the concepts to choose from")
    return context.candidates


def _mastery(state: LearnerState, concept: str) -> float:
    """The state's value for a concept: its mastery, or the initial mastery without history."""
    value = state.mastery.get(concept)
    return float(state.initial_mastery if value is None else value)


@dataclass(frozen=True, slots=True)
class RandomOrder:
    """``random-v1``: a uniformly drawn candidate.

    Declared inputs: ``context.candidates``, ``context.seed`` and ``context.step``. The draw
    is the first number of ``stream(seed, step, "random-order")``, so a learner's k-th
    choice does not depend on anything that happened before.
    """

    id: ClassVar[str] = "random"
    version: ClassVar[str] = "v1"

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """
        Raises:
            ValueError: If the context has no candidates, no seed or no step
        """
        candidates = _candidates(context)
        if context.seed is None or context.step is None:
            raise ValueError("random-v1 needs context.seed and context.step")
        draw = stream(context.seed, context.step, "random-order").random()
        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": KIND_ITEM, "concept": candidates[int(draw * len(candidates))]},
            state_used={},
            context_used={
                "candidates": _encode(candidates),
                "seed": context.seed,
                "step": context.step,
            },
        )


@dataclass(frozen=True, slots=True)
class TextbookOrder:
    """``textbook-v1``: book order in blocks, the same for every learner.

    ``items_per_concept`` items of the first concept, then of the second, and so on; after
    the last concept it starts again. Declared inputs: ``context.candidates`` and
    ``context.step``. It reads no learner state.
    """

    items_per_concept: int
    id: ClassVar[str] = "textbook"
    version: ClassVar[str] = "v1"

    def __post_init__(self) -> None:
        if self.items_per_concept < 1:
            raise ValueError("items_per_concept must be at least 1")

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """
        Raises:
            ValueError: If the context has no candidates or no step
        """
        candidates = _candidates(context)
        if context.step is None:
            raise ValueError("textbook-v1 needs context.step")
        block = context.step // self.items_per_concept
        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": KIND_ITEM, "concept": candidates[block % len(candidates)]},
            state_used={},
            context_used={
                "candidates": _encode(candidates),
                "step": context.step,
                "items_per_concept": self.items_per_concept,
            },
        )


@dataclass(frozen=True, slots=True)
class ReadyFirst:
    """``ready-first-v1``: textbook order over the concepts the learner is ready for.

    A concept counts as mastered when its value in the state is at least
    ``mastery_threshold``. A concept is ready when it is not mastered and every prerequisite
    it has by the edges in ``context.edges`` is. The policy lists the ready candidates in
    book order and applies textbook order to that list: the block
    ``step // items_per_concept`` goes to the entry at the block number modulo the length of
    the list (action reason "ready"). When no candidate is ready (all are mastered, or the
    edges hold a cycle) it takes the candidate ``TextbookOrder`` takes at that step
    ("fallback").

    The list of ready concepts changes with the state, so the block number does not visit
    them strictly in turn: a concept can get two blocks before another ready one gets its
    first.

    The record lists what was read: in ``state_used`` the value of every candidate and of
    every prerequisite of a candidate that is not mastered, and in ``edges_used`` the given
    edges into those candidates, with their provenance. An edge into a mastered candidate is
    not read and cannot change the record.
    """

    mastery_threshold: float
    items_per_concept: int
    id: ClassVar[str] = "ready-first"
    version: ClassVar[str] = "v1"

    def __post_init__(self) -> None:
        if self.items_per_concept < 1:
            raise ValueError("items_per_concept must be at least 1")

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """
        Raises:
            ValueError: If the context has no candidates or no step
        """
        candidates = _candidates(context)
        if context.step is None:
            raise ValueError("ready-first-v1 needs context.step")
        incoming: dict[str, list[EdgeUse]] = {}
        for edge in context.edges:
            incoming.setdefault(edge.target, []).append(edge)

        read: dict[str, float] = {}

        def mastered(concept: str) -> bool:
            if concept not in read:
                read[concept] = _mastery(state, concept)
            return read[concept] >= self.mastery_threshold

        edges_used: list[EdgeUse] = []
        ready: list[str] = []
        for concept in candidates:
            if mastered(concept):
                continue
            prerequisites = incoming.get(concept, [])
            edges_used.extend(prerequisites)
            is_ready = True
            for edge in prerequisites:  # every prerequisite is read, also after a failed one
                is_ready = mastered(edge.source) and is_ready
            if is_ready:
                ready.append(concept)

        block = context.step // self.items_per_concept
        if ready:
            chosen, reason = ready[block % len(ready)], "ready"
        else:
            chosen, reason = candidates[block % len(candidates)], "fallback"

        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": KIND_ITEM, "concept": chosen, "reason": reason},
            state_used={f"mastery:{concept}": value for concept, value in read.items()},
            context_used={
                "candidates": _encode(candidates),
                "step": context.step,
                "items_per_concept": self.items_per_concept,
                "mastery_threshold": float(self.mastery_threshold),
            },
            edges_used=tuple(edges_used),
        )


@dataclass(frozen=True, slots=True)
class StuckOnLast:
    """``stuck-on-last-v1``: always the last concept of the book. Deliberately bad.

    Tests use it as the policy every sensible one must beat. ``SimulationProtocol`` refuses
    it in a frozen protocol. Declared input: ``context.candidates``.
    """

    id: ClassVar[str] = "stuck-on-last"
    version: ClassVar[str] = "v1"

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """
        Raises:
            ValueError: If the context has no candidates
        """
        candidates = _candidates(context)
        return DecisionRecord(
            policy_id=self.id,
            policy_version=self.version,
            action={"kind": KIND_ITEM, "concept": candidates[-1]},
            state_used={},
            context_used={"candidates": _encode(candidates)},
        )


@dataclass(frozen=True, slots=True)
class PolicySpec:
    """A policy as the runner uses it: a sequencer and what it is allowed to see."""

    name: str
    """The name protocols and reports use, for example ``ready-first``."""
    sequencer: Policy
    """Chooses the next action."""
    difficulty: Policy | None = None
    """Chooses the difficulty band of an item from the estimate; None asks for the fixed band."""
    state_source: StateSource = "none"
    """What the sequencer gets as learner state: nothing, the production estimate or the
    true skill."""
    dag_source: DagSource = "none"
    """Which edges the sequencer gets: none, the given DAG of the cell, or the true DAG."""


POLICY_NAMES: Final[tuple[str, ...]] = ("random", "textbook", "band-v1", "ready-first", "oracle")
"""The policies of the issue: what a frozen protocol may list."""

BAD_POLICY: Final = "stuck-on-last"
"""The deliberately bad policy, for tests: a draft protocol may list it, a frozen one not."""


def build_policy(name: str, *, mastery_threshold: float, items_per_concept: int) -> PolicySpec:
    """
    Build a policy by name.

    Args:
        name: One of ``POLICY_NAMES``, or ``BAD_POLICY``
        mastery_threshold: The threshold of ``ReadyFirst``
        items_per_concept: The block length of ``TextbookOrder`` and of ``ReadyFirst``

    Raises:
        KeyError: If the name is unknown
    """
    if name == "random":
        return PolicySpec(name, RandomOrder())
    if name == "textbook":
        return PolicySpec(name, TextbookOrder(items_per_concept))
    if name == "band-v1":
        return PolicySpec(name, TextbookOrder(items_per_concept), difficulty=BAND_V1)
    if name == "ready-first":
        return PolicySpec(
            name,
            ReadyFirst(mastery_threshold, items_per_concept),
            state_source="estimate",
            dag_source="given",
        )
    if name == "oracle":
        return PolicySpec(
            name,
            ReadyFirst(mastery_threshold, items_per_concept),
            state_source="truth",
            dag_source="true",
        )
    if name == BAD_POLICY:
        return PolicySpec(name, StuckOnLast())
    known = ", ".join((*POLICY_NAMES, BAD_POLICY))
    raise KeyError(f"Unknown policy {name!r}. Known policies: {known}")
