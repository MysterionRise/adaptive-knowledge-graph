"""
Policy interface and decision records for learner-state decisions (#306).

A policy takes one decision from a learner's state. It receives a ``LearnerState`` and a
``DecisionContext`` and returns a ``DecisionRecord``: the policy's id and version, the action
it chose, the learner state and the context it used, and the graph edges it used with their
provenance. The record lists only what the policy read, so a test can change any other input
and require the same record.

A record holds no clock time and no random id. Two records are equal exactly when policy,
action, state used, context used and edges used are equal, and ``record_id()`` is a digest of
the record's canonical JSON. Equality compares that same JSON, so equal records have equal
ids. The time of a decision belongs to whatever envelope carries the record
(``DecisionRecordPayload.decided_at`` in the API). A policy never reads the clock: a policy
that needs time takes it from ``DecisionContext.now`` or ``DecisionContext.step``.

Everything here is immutable. The dataclasses are frozen, and their mappings are read-only
copies of what the caller passed in.

This module imports the standard library only (no settings, no learner models), so a script
or a simulator can import the policies without the rest of the application.
"""

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

Json = str | int | float | bool | None
"""A JSON scalar: the only kind of value a record's mappings hold."""

RECORD_ID_HEX_CHARS = 16
"""Length of ``DecisionRecord.record_id()``: the first 64 bits of the SHA-256 digest."""


class _FrozenMap(Mapping[str, Json]):
    """A read-only copy of a mapping with string keys and JSON scalar values.

    It compares equal to any mapping with the same items and is hashable, so the frozen
    dataclasses that hold it keep value equality and hashing.

    Negative zero is stored as 0.0. The two compare equal and JSON writes them differently,
    so keeping one of them lets equal numbers give the same canonical JSON.

    Raises:
        TypeError: If a key is not a string or a value is not a JSON scalar
    """

    __slots__ = ("_items",)

    def __init__(self, items: Mapping[str, Json]) -> None:
        copied: dict[str, Json] = {}
        for key, value in items.items():
            if not isinstance(key, str):
                raise TypeError(f"Keys must be strings, got {key!r}")
            if value is not None and not isinstance(value, str | int | float | bool):
                raise TypeError(f"The value of {key!r} must be a JSON scalar, got {value!r}")
            copied[key] = 0.0 if isinstance(value, float) and value == 0.0 else value
        self._items = copied

    def __getitem__(self, key: str) -> Json:
        return self._items[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(frozenset(self._items.items()))

    def __repr__(self) -> str:
        return repr(self._items)


@dataclass(frozen=True, slots=True)
class EdgeUse:
    """A graph edge a decision used, with where the edge came from."""

    source: str
    """The prerequisite concept."""
    target: str
    """The concept that depends on ``source``."""
    relation: str
    """The edge type, for example ``PREREQ``."""
    provenance: str
    """Where the edge came from: a curated file and its version, or an extraction method."""

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class LearnerState:
    """The only view of a learner a policy receives.

    ``StudentProfile.learner_state`` builds it for one concept, so a policy cannot read a
    profile field that is not in this class.
    """

    mastery: Mapping[str, float]
    """Mastery level by concept, for the concepts this state was built for and that have
    history. A concept without history is absent."""
    initial_mastery: float
    """The mastery level of a concept without history (``STUDENT_INITIAL_MASTERY``)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "mastery", _FrozenMap(self.mastery))


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """What a policy may read besides the learner state: content, time and a seed.

    Every field is optional. A policy says in its record which ones it used
    (``DecisionRecord.context_used`` and ``edges_used``).
    """

    concept: str | None = None
    """Content: the concept the decision is about."""
    candidates: tuple[str, ...] = ()
    """Content: the concepts a policy may choose from, in book order."""
    edges: tuple[EdgeUse, ...] = ()
    """Content: the graph edges the policy is given."""
    step: int | None = None
    """Time, counted in steps (a simulator's clock)."""
    now: datetime | None = None
    """Time, supplied by the caller. A policy never reads the clock itself."""
    seed: int | None = None
    """Seed for a policy that draws random numbers."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "edges", tuple(self.edges))


@dataclass(frozen=True, slots=True, eq=False)
class DecisionRecord:
    """One decision: who decided, what was decided, and every input the policy read.

    Two records are equal exactly when their ``canonical_json()`` is equal: the same policy,
    action, state used, context used and edges used, value for value and type for type.
    ``record_id()`` is a digest of the same text, so equal records have equal ids.
    """

    policy_id: str
    policy_version: str
    action: Mapping[str, Json]
    """What the policy chose, for example ``{"kind": "difficulty", "difficulty": "easy"}``."""
    state_used: Mapping[str, Json]
    """The learner state the policy read, with the exact values (nothing rounded)."""
    context_used: Mapping[str, Json]
    """The context fields the policy read."""
    edges_used: tuple[EdgeUse, ...] = ()
    """The graph edges the policy read."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _FrozenMap(self.action))
        object.__setattr__(self, "state_used", _FrozenMap(self.state_used))
        object.__setattr__(self, "context_used", _FrozenMap(self.context_used))
        object.__setattr__(self, "edges_used", tuple(self.edges_used))

    def to_dict(self) -> dict[str, Any]:
        """The record as plain dicts and lists, ready for ``json.dumps``."""
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "action": dict(self.action),
            "state_used": dict(self.state_used),
            "context_used": dict(self.context_used),
            "edges_used": [edge.to_dict() for edge in self.edges_used],
        }

    def canonical_json(self) -> str:
        """``to_dict()`` as JSON with sorted keys and no whitespace.

        This text is the record's identity: ``==`` compares it and ``record_id()`` is a
        digest of it. Numbers are written as Python writes them, so the integer 1, the float
        1.0 and True give three different texts and three different records. A policy
        therefore stores one number type per field. A float that is not finite is written as
        ``NaN`` or ``Infinity``, which JSON does not have.
        """
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def record_id(self) -> str:
        """The first 16 hexadecimal characters of the SHA-256 of ``canonical_json()``.

        Equal records have the same id: no time and no random value goes into it.
        """
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return digest[:RECORD_ID_HEX_CHARS]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DecisionRecord):
            return NotImplemented
        return self.canonical_json() == other.canonical_json()

    def __hash__(self) -> int:
        return hash(self.canonical_json())


@runtime_checkable
class Policy(Protocol):
    """A versioned rule that takes one decision from learner state and context.

    ``decide`` is a function of its two arguments only: it reads no clock, no settings and no
    storage, and it lists what it read in the record. A change in behaviour is a new version.
    """

    @property
    def id(self) -> str:
        """The policy's name, for example ``band``."""

    @property
    def version(self) -> str:
        """The version of the rule, for example ``v1``."""

    def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
        """Take the decision and return its record."""


def policy_key(policy: Policy) -> str:
    """The registry key of a policy: its id and version, for example ``band-v1``."""
    return f"{policy.id}-{policy.version}"
