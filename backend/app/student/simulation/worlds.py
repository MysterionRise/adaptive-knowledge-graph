"""
Synthetic worlds for the learner simulator (#307): a prerequisite graph, learners whose skill
grows under prerequisite gating, and the seeded streams every random draw comes from.

The ground truth is deliberately not Bayesian Knowledge Tracing, the model the production
estimate uses. BKT has one binary "known" state per concept, a fixed chance to learn per
attempt and no prerequisites. Here a learner has a continuous skill in [0, 1] per concept,
the gain of a practised item depends on the learner's own rate and on the skill of the
concept's prerequisites, and a share of learners is not gated at all. A policy that looks
good only because the world shares its estimator's assumptions should not look good here.

Assumptions of the core world (``World.family``). The values are parameters of a
``WorldSpec``; the maintainer fixes them in the protocol.

A1. Response. The probability of answering a fresh item of concept c correctly is
    ``guess + (1 - guess - slip) * skill[c]``. Items have no difficulty: the band a policy
    asks for changes neither this probability nor the learning gain (#311 adds difficulty).
A2. Learning. One practised item, whatever the response, moves the skill towards 1:
    ``skill[c] += learning_rate * base_gain * gate * (1 - skill[c])``.
A3. Gate. ``gate = 1 - strength * (1 - leak) * (1 - weakest)``, where ``weakest`` is the
    lowest skill among the true prerequisites of c (1 when it has none) and ``strength`` is
    0, 0.5 or 1 for prerequisite strength "none", "weak" or "strong". With strong
    prerequisites and an unknown prerequisite, the gate is the leak.
A4. Contradicting learners. A share of learners has knowledge that contradicts the DAG:
    their gate is 1 for every concept, at the start and while learning.
A5. Learning rates. One rate per learner, uniform in a range.
A6. Initial skill. ``draw * initial_skill_max * gate``, concept by concept in book order,
    with the gate of A3 and A4 on the initial skills drawn so far.
A7. No forgetting. The skill never falls, so the retention delay has no effect (#311 adds
    forgetting).
A8. Items are fresh and test the concept they are mapped to.

Everything is arithmetic on floats: no exponential, logarithm or fractional power, so a run
does not depend on the C library. Nothing reads the clock or the environment.

Random numbers. ``stream`` is the only place a generator is built. Its seed is a SHA-256
digest of the master seed, the learner index, a purpose and a key, so every stream is
independent of how much any other stream was used. A learner's traits come from the
learner's "traits" stream. Responses come from the learner's "response" stream, read in
rows of one draw per concept in book order: the k-th answer on a concept uses that
concept's draw of row k. The same learner therefore meets the same draws under every policy
(common random numbers). Only ``Random.random()`` is called on a stream.
"""

import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, Literal, TypeVar

from backend.app.student.policy.band import Difficulty

PrereqStrength = Literal["none", "weak", "strong"]

PREREQ_STRENGTHS: Final[Mapping[str, float]] = MappingProxyType(
    {"none": 0.0, "weak": 0.5, "strong": 1.0}
)
"""A3: how much of the gate a prerequisite strength applies."""

_T = TypeVar("_T")


def stream_seed(master_seed: int, learner_index: int, purpose: str, key: str = "") -> int:
    """The seed of one stream: the first 64 bits of a SHA-256 digest of the four values.

    Raises:
        TypeError: If the seed or the index is not an int
        ValueError: If the purpose holds a colon, which separates the four values
    """
    for name, value in (("master_seed", master_seed), ("learner_index", learner_index)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int, got {value!r}")
    if ":" in purpose:
        raise ValueError(f"A purpose must not hold a colon, got {purpose!r}")
    text = f"{master_seed}:{learner_index}:{purpose}:{key}"
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def stream(master_seed: int, learner_index: int, purpose: str, key: str = "") -> random.Random:
    """
    The random stream for one purpose of one learner.

    Args:
        master_seed: The run's seed
        learner_index: The learner; 0 for draws that belong to no learner (graphs, DAGs).
            ``RandomOrder`` passes the learner's policy seed and the step in these two places.
        purpose: What the stream is for, for example "traits" or "response"
        key: A further name inside the purpose, for example the concept

    Returns:
        A generator of which callers use ``random()`` only
    """
    seed = stream_seed(master_seed, learner_index, purpose, key)
    return random.Random(seed)  # nosec B311  # seeded simulation draws, not security


def draw_sample(pool: Sequence[_T], count: int, rng: random.Random) -> list[_T]:
    """``count`` items of ``pool`` without replacement, in drawn order.

    A partial Fisher-Yates shuffle on ``rng.random()``, so the result depends on the order
    of ``pool``: pass it in a fixed order.

    Raises:
        ValueError: If ``count`` is negative or larger than the pool
    """
    if not 0 <= count <= len(pool):
        raise ValueError(f"Cannot draw {count} of {len(pool)} items")
    items = list(pool)
    for index in range(count):
        other = index + int(rng.random() * (len(items) - index))
        items[index], items[other] = items[other], items[index]
    return items[:count]


@dataclass(frozen=True, slots=True)
class ConceptGraph:
    """A book of concepts with its true prerequisite edges.

    Raises:
        ValueError: If a concept repeats, the chapters are not the concepts in book order, an
            edge names an unknown concept or does not point forward in book order, or the
            slice names an unknown concept
    """

    concepts: tuple[str, ...]
    """Every concept in book order, which is a topological order of ``edges``."""
    chapters: tuple[tuple[str, ...], ...]
    """The concepts chapter by chapter, in book order."""
    edges: tuple[tuple[str, str], ...]
    """The true edges as (prerequisite, dependent), stored sorted in book order."""
    slice: tuple[str, ...] = ()
    """The concepts the primary metric averages over, in book order; empty means all."""
    _positions: Mapping[str, int] = field(init=False, repr=False, compare=False)
    _prerequisites: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        concepts = tuple(self.concepts)
        chapters = tuple(tuple(chapter) for chapter in self.chapters)
        positions = {concept: position for position, concept in enumerate(concepts)}
        if not concepts or len(positions) != len(concepts):
            raise ValueError("A graph needs at least one concept and no concept twice")
        if any(not chapter for chapter in chapters) or concepts != tuple(
            concept for chapter in chapters for concept in chapter
        ):
            raise ValueError("The chapters must hold the concepts in book order, none empty")

        edges = set()
        for source, target in self.edges:
            if source not in positions or target not in positions:
                raise ValueError(f"Edge ({source!r}, {target!r}) names an unknown concept")
            if positions[source] >= positions[target]:
                raise ValueError(f"Edge ({source!r}, {target!r}) must point forward in book order")
            edges.add((source, target))
        ordered = tuple(sorted(edges, key=lambda edge: (positions[edge[0]], positions[edge[1]])))

        chosen = set(self.slice)
        if not chosen <= positions.keys():
            raise ValueError(f"The slice names unknown concepts: {sorted(chosen - set(concepts))}")
        in_slice = tuple(c for c in concepts if c in chosen) if chosen else concepts

        prerequisites: dict[str, list[str]] = {concept: [] for concept in concepts}
        for source, target in ordered:
            prerequisites[target].append(source)

        object.__setattr__(self, "concepts", concepts)
        object.__setattr__(self, "chapters", chapters)
        object.__setattr__(self, "edges", ordered)
        object.__setattr__(self, "slice", in_slice)
        # Plain dicts: a read-only proxy cannot be pickled, and the two are private.
        object.__setattr__(self, "_positions", positions)
        object.__setattr__(
            self, "_prerequisites", {c: tuple(sources) for c, sources in prerequisites.items()}
        )

    def position(self, concept: str) -> int:
        """The concept's place in book order, from 0."""
        return self._positions[concept]

    def prerequisites(self, concept: str) -> tuple[str, ...]:
        """The true prerequisites of a concept, in book order."""
        return self._prerequisites[concept]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapters": [list(chapter) for chapter in self.chapters],
            "edges": [list(edge) for edge in self.edges],
            "slice": list(self.slice),
        }


FIXTURE_GRAPH: Final = ConceptGraph(
    concepts=("a1", "a2", "a3", "b1", "b2", "b3", "c1", "c2", "c3"),
    chapters=(("a1", "a2", "a3"), ("b1", "b2", "b3"), ("c1", "c2", "c3")),
    edges=(
        ("a1", "a2"),
        ("a1", "a3"),
        ("a2", "b1"),
        ("a3", "b2"),
        ("b1", "b3"),
        ("b2", "b3"),
        ("b1", "c1"),
        ("b3", "c2"),
        ("c1", "c3"),
        ("c2", "c3"),
    ),
)
"""The hand-written graph of the CI smoke test: three chapters of three concepts, ten edges,
one root (a1) and a longest chain of six concepts (a1, a2, b1, b3, c2, c3)."""


def synthetic_graph(chapters: int, per_chapter: int, parents: float, seed: int) -> ConceptGraph:
    """
    A seeded book: ``chapters`` chapters of ``per_chapter`` concepts with local prerequisites.

    Every concept but the first gets ``parents`` prerequisites on average: the whole part of
    ``parents``, and one more with the probability of its fractional part. They are drawn
    without replacement from the ``2 * per_chapter`` concepts before it, so prerequisites stay
    in the same or the previous chapters. Every concept is in the slice.

    Raises:
        ValueError: If a count is below 1 or ``parents`` is negative
    """
    if chapters < 1 or per_chapter < 1 or parents < 0:
        raise ValueError("chapters and per_chapter must be at least 1 and parents at least 0")
    book = tuple(
        tuple(f"c{chapter + 1}.{place + 1}" for place in range(per_chapter))
        for chapter in range(chapters)
    )
    concepts = tuple(concept for chapter in book for concept in chapter)
    whole = int(parents)
    rng = stream(seed, 0, "graph")
    edges: list[tuple[str, str]] = []
    for position in range(1, len(concepts)):
        pool = concepts[max(0, position - 2 * per_chapter) : position]
        count = min(len(pool), whole + (rng.random() < parents - whole))
        edges.extend((source, concepts[position]) for source in draw_sample(pool, count, rng))
    return ConceptGraph(concepts=concepts, chapters=book, edges=tuple(edges))


@dataclass(frozen=True, slots=True)
class WorldSpec:
    """The parameters of one world (assumptions A1 to A6 in the module docstring).

    Raises:
        ValueError: If a value is outside its range
    """

    id: str
    prereq_strength: PrereqStrength
    """A3: "none", "weak" or "strong"."""
    leak: float
    """A3: the share of the gain that gets through a fully closed gate, in [0, 1]."""
    contradicting_share: float
    """A4: the probability that a learner is not gated, in [0, 1]."""
    learning_rate_range: tuple[float, float]
    """A5: the lowest and the highest learning rate."""
    base_gain: float
    """A2: the share of the remaining skill a learner of rate 1 gains from one item."""
    guess: float
    """A1: the probability of a correct answer at skill 0."""
    slip: float
    """A1: the probability of a wrong answer at skill 1."""
    initial_skill_max: float
    """A6: the highest initial skill, in [0, 1]."""

    def __post_init__(self) -> None:
        if self.prereq_strength not in PREREQ_STRENGTHS:
            raise ValueError(f"Unknown prerequisite strength {self.prereq_strength!r}")
        low, high = self.learning_rate_range
        object.__setattr__(self, "learning_rate_range", (low, high))
        if not 0 < low <= high:
            raise ValueError("The learning rates must be positive, lowest first")
        if not 0 < self.base_gain or high * self.base_gain > 1:
            raise ValueError("base_gain must be positive and at most 1 at the highest rate")
        for name in ("leak", "contradicting_share", "initial_skill_max"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must lie in [0, 1], got {getattr(self, name)!r}")
        if self.guess < 0 or self.slip < 0 or self.guess + self.slip >= 1:
            raise ValueError("guess and slip must not be negative and must sum to less than 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prereq_strength": self.prereq_strength,
            "leak": self.leak,
            "contradicting_share": self.contradicting_share,
            "learning_rate_range": list(self.learning_rate_range),
            "base_gain": self.base_gain,
            "guess": self.guess,
            "slip": self.slip,
            "initial_skill_max": self.initial_skill_max,
        }


@dataclass(frozen=True, slots=True)
class LearnerTraits:
    """What a learner brings: drawn once from the learner's "traits" stream."""

    index: int
    learning_rate: float
    contradicts_dag: bool
    initial_skill: tuple[float, ...]
    """Initial skill per concept, in book order."""


class World:
    """One world: a ``WorldSpec`` on a ``ConceptGraph``."""

    family: ClassVar[str] = "gated-continuous-growth-v1"
    """The model family. It is not BKT: skill is continuous and there is no "known" state."""

    def __init__(self, spec: WorldSpec, graph: ConceptGraph) -> None:
        self.spec = spec
        self.graph = graph
        self._strength = PREREQ_STRENGTHS[spec.prereq_strength]
        self._prerequisite_positions = tuple(
            tuple(graph.position(source) for source in graph.prerequisites(concept))
            for concept in graph.concepts
        )

    def gate(self, skill: Sequence[float], concept: str, contradicts: bool) -> float:
        """A3 and A4: the share of the full gain a learner gets on ``concept``.

        Args:
            skill: Skill per concept in book order; only the prerequisites are read
            concept: The concept being practised
            contradicts: Whether the learner's knowledge contradicts the DAG
        """
        if contradicts:
            return 1.0
        sources = self._prerequisite_positions[self.graph.position(concept)]
        weakest = min((skill[source] for source in sources), default=1.0)
        return 1.0 - self._strength * (1.0 - self.spec.leak) * (1.0 - weakest)

    def p_correct(self, skill: float) -> float:
        """A1: the probability of a correct answer on a fresh item at this skill."""
        return self.spec.guess + (1.0 - self.spec.guess - self.spec.slip) * skill

    def traits(self, master_seed: int, learner_index: int) -> LearnerTraits:
        """The learner's traits. The same seed and index give the same draws in every world.

        The stream is read in a fixed order: the rate, the contradiction, then one draw per
        concept in book order.
        """
        rng = stream(master_seed, learner_index, "traits")
        low, high = self.spec.learning_rate_range
        learning_rate = low + (high - low) * rng.random()
        contradicts = rng.random() < self.spec.contradicting_share
        skill: list[float] = []
        for concept in self.graph.concepts:
            ceiling = self.spec.initial_skill_max * self.gate(skill, concept, contradicts)
            skill.append(rng.random() * ceiling)
        return LearnerTraits(
            index=learner_index,
            learning_rate=learning_rate,
            contradicts_dag=contradicts,
            initial_skill=tuple(skill),
        )


class Learner:
    """One simulated learner in one world: the latent state and its responses."""

    def __init__(self, world: World, traits: LearnerTraits, master_seed: int) -> None:
        self.world = world
        self.traits = traits
        self._master_seed = master_seed
        self._skill = list(traits.initial_skill)
        self._positions = {concept: place for place, concept in enumerate(world.graph.concepts)}
        self._gain = traits.learning_rate * world.spec.base_gain
        self._responses: random.Random | None = None
        self._response_rows: list[list[float]] = []
        self._answered: dict[str, int] = {}

    def skill(self, concept: str) -> float:
        """The true skill on a concept, in [0, 1]."""
        return self._skill[self._positions[concept]]

    def items_answered(self, concept: str) -> int:
        """How many items of the concept the learner has answered."""
        return self._answered.get(concept, 0)

    def p_correct(self, concept: str, difficulty: Difficulty = "medium") -> float:
        """A1: the true probability of a correct answer on an item of the concept.

        The core world has no item difficulty, so ``difficulty`` changes nothing.
        """
        return self.world.p_correct(self.skill(concept))

    def p_correct_fresh(self, concept: str, delay_days: float = 0.0) -> float:
        """The true probability of a correct answer on a fresh item after a delay.

        Computed from the latent state, without a draw. A7: the core world does not forget,
        so ``delay_days`` changes nothing.
        """
        return self.world.p_correct(self.skill(concept))

    def _response_draw(self, position: int, number: int) -> float:
        """The draw behind the ``number``-th answer on the concept at ``position``.

        Row k of the response stream holds the k-th draw of every concept, in book order.
        Rows are read when first needed, so a draw depends on the learner, the concept and
        the number of the answer only.
        """
        if self._responses is None:
            self._responses = stream(self._master_seed, self.traits.index, "response")
        while len(self._response_rows) <= number:
            self._response_rows.append([self._responses.random() for _ in self._skill])
        return self._response_rows[number][position]

    def answer(self, concept: str, difficulty: Difficulty = "medium") -> bool:
        """Answer one fresh item of the concept, then learn from it (A1, A2).

        The k-th answer on a concept uses the same draw whatever was practised in between
        (``_response_draw``).
        """
        position = self._positions[concept]
        number = self._answered.get(concept, 0)
        correct = self._response_draw(position, number) < self.p_correct(concept, difficulty)

        gate = self.world.gate(self._skill, concept, self.traits.contradicts_dag)
        self._skill[position] += self._gain * gate * (1.0 - self._skill[position])
        self._answered[concept] = number + 1
        return correct
