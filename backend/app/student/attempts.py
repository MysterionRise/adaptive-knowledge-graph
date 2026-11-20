"""
The attempt record: one answered item, with who answered, what was asked and what decided it.

This is the schema of the attempt log in ``docs/adaptivity/README.md`` (#307, #308). The
learner simulator builds these records in memory (``source`` "sim"); #308 persists them and
writes the ones that come from graded answers (``source`` "real"). Nothing here stores
anything.

The fields are an allowlist (``ATTEMPT_FIELDS``) with no free-text field: every string is
an identifier, one printable line of at most ``MAX_ID_CHARS`` characters, and the other
fields are booleans, an integer, a time and a mapping of identifiers. The check is on the
form of a string, not on its content: a line of prose of that length passes where an id is
expected, so a writer passes ids only. A learner id is opaque: nothing here reads meaning
into it.

A record holds no clock time of its own making. The caller passes the timestamp; a simulated
attempt gets ``sim_timestamp`` (``SIM_EPOCH`` plus simulated minutes), never the clock. An
error names the field and the rule, never the rejected value.

This module imports the standard library only.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Final, Literal

AttemptSource = Literal["real", "sim"]

ATTEMPT_SOURCES: Final[tuple[str, ...]] = ("real", "sim")
"""Where an attempt comes from: a graded answer of a learner, or the simulator."""

ATTEMPT_FIELDS: Final[tuple[str, ...]] = (
    "learner_id",
    "item_id",
    "concept_ids",
    "chosen_option_id",
    "correct",
    "latency_ms",
    "assisted",
    "decision_record_id",
    "model_versions",
    "source",
    "timestamp",
)
"""The allowlist: the fields of an attempt, in the order ``Attempt.to_row`` writes them."""

MAX_ID_CHARS: Final = 200
"""Longest identifier an attempt accepts (the limit concept names already have)."""

SIM_EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)
"""Time zero of every simulated learner. A simulated timestamp is this plus simulated time."""


def sim_timestamp(minutes: float) -> datetime:
    """The timestamp of a simulated event: ``SIM_EPOCH`` plus ``minutes`` of simulated time."""
    return SIM_EPOCH + timedelta(minutes=minutes)


def _check_id(name: str, value: object) -> str:
    """An identifier: a non-empty printable line of at most ``MAX_ID_CHARS`` characters."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    if not value or len(value) > MAX_ID_CHARS or not value.isprintable():
        raise ValueError(
            f"{name} must be one printable line of 1 to {MAX_ID_CHARS} characters, "
            f"got {len(value)} characters"
        )
    return value


@dataclass(frozen=True, slots=True)
class Attempt:
    """One answered item.

    Raises:
        TypeError: If a field has the wrong type
        ValueError: If an identifier is empty, too long or not one printable line, if there
            is no concept, if the latency is negative, if ``source`` is not "real" or "sim",
            or if the timestamp has no UTC offset
    """

    learner_id: str
    """Opaque learner id."""
    item_id: str
    """The item that was answered."""
    concept_ids: tuple[str, ...]
    """The concepts the item tests; at least one."""
    chosen_option_id: str | None
    """The option the learner chose; None when the item has no options (simulated items)."""
    correct: bool
    """Whether the answer was correct."""
    latency_ms: int | None
    """Time from showing the item to the answer, in milliseconds; None when unknown."""
    assisted: bool
    """Whether help was given before the answer (a hint, source text or a second try)."""
    decision_record_id: str | None
    """``DecisionRecord.record_id()`` of the decision that led to this item, if there is one.
    One id only: when two decisions precede an item (which concept, then which difficulty),
    the writer chooses which one it names. The simulator names the sequencing decision; the
    rule for real attempts comes with #308."""
    model_versions: Mapping[str, str]
    """Which versions produced the attempt, for example ``{"policy": "band-v1"}``."""
    source: AttemptSource
    """"real" for a learner's graded answer, "sim" for a simulated one."""
    timestamp: datetime
    """When the answer was given, with a UTC offset. Simulated: ``sim_timestamp``."""

    def __post_init__(self) -> None:
        _check_id("learner_id", self.learner_id)
        _check_id("item_id", self.item_id)
        if isinstance(self.concept_ids, str):
            raise TypeError("concept_ids must be a sequence of ids, not one string")
        if not isinstance(self.concept_ids, Iterable):
            raise TypeError("concept_ids must be a sequence of ids")
        concept_ids = tuple(_check_id("concept_ids", concept) for concept in self.concept_ids)
        if not concept_ids:
            raise ValueError("concept_ids must name at least one concept")
        object.__setattr__(self, "concept_ids", concept_ids)
        if self.chosen_option_id is not None:
            _check_id("chosen_option_id", self.chosen_option_id)
        for name in ("correct", "assisted"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if self.latency_ms is not None:
            if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int):
                raise TypeError("latency_ms must be an int or None")
            if self.latency_ms < 0:
                raise ValueError(f"latency_ms must not be negative, got {self.latency_ms}")
        if self.decision_record_id is not None:
            _check_id("decision_record_id", self.decision_record_id)
        if not isinstance(self.model_versions, Mapping):
            raise TypeError("model_versions must be a mapping of ids")
        for key in self.model_versions:  # before sorting: keys of mixed types do not sort
            _check_id("model_versions key", key)
        versions = {
            key: _check_id(f"model_versions[{key!r}]", self.model_versions[key])
            for key in sorted(self.model_versions)
        }
        object.__setattr__(self, "model_versions", MappingProxyType(versions))
        if self.source not in ATTEMPT_SOURCES:
            raise ValueError(f"source must be one of {ATTEMPT_SOURCES}")
        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must have a UTC offset")

    def __reduce__(self) -> tuple[Any, ...]:
        # Pickling and copying rebuild the record: the read-only mapping cannot be pickled.
        values = [getattr(self, name) for name in ATTEMPT_FIELDS]
        values[ATTEMPT_FIELDS.index("model_versions")] = dict(self.model_versions)
        return (type(self), tuple(values))

    def __hash__(self) -> int:
        # The generated hash would fail on the read-only mapping.
        return hash(
            (
                self.learner_id,
                self.item_id,
                self.concept_ids,
                self.chosen_option_id,
                self.correct,
                self.latency_ms,
                self.assisted,
                self.decision_record_id,
                tuple(self.model_versions.items()),
                self.source,
                self.timestamp,
            )
        )

    def to_row(self) -> dict[str, Any]:
        """The attempt as plain JSON values, keyed by ``ATTEMPT_FIELDS`` in that order.

        The timestamp is written in ISO 8601 with its UTC offset.
        """
        return {
            "learner_id": self.learner_id,
            "item_id": self.item_id,
            "concept_ids": list(self.concept_ids),
            "chosen_option_id": self.chosen_option_id,
            "correct": self.correct,
            "latency_ms": self.latency_ms,
            "assisted": self.assisted,
            "decision_record_id": self.decision_record_id,
            "model_versions": dict(self.model_versions),
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
        }
