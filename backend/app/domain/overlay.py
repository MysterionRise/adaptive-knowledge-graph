"""
Overlay of a curated domain on a subject's graph (#211).

The builder writes what it extracts; a rebuild with ``--clear`` loses anything a person
decided. The overlay puts those decisions back. It works in two steps so that the
decisions can be tested without Neo4j:

- ``plan_overlay(domain, graph_state)`` is pure. It compares the domain with the state of
  the graph and returns the ordered operations that close the gap. Planning against the
  state those operations produce returns no operation, which is what makes ``apply``
  idempotent.
- ``apply_overlay(adapter, domain)`` reads the state through the subject's Neo4j adapter,
  executes the plan and reads the state back to confirm that nothing is left to do.

What each review status does:

- ``approved`` term: the concept is merged on its name. A curated definition replaces the
  builder's; a term without a definition leaves the stored one alone. Aliases are added to
  the stored ones, never removed. The concept gets ``term_id``, ``review_status`` and
  ``definition_source``. A term the build did not extract is created (``create_concept``).
- ``approved`` PREREQ relationship: the edge is merged with ``provenance_source``
  "curated", ``review_status``, ``confidence``, ``rule`` and ``evidence_source``.
- ``rejected`` and ``deprecated`` term: the concept is deleted with all its edges
  (``remove_concept``). This changes retrieval, so the plan lists every removal and
  ``scripts/domain_tool.py apply`` prints them.
- ``rejected`` and ``deprecated`` PREREQ relationship: the edge is deleted.
- ``extracted`` and ``proposed`` entries: nothing. They never reach the graph through the
  overlay, so a dictionary of extracted entries plans no operation.

Entries the overlay cannot apply are returned by ``skipped_entries`` instead of being
written: a relationship of another type (only PREREQ edges are applied), an approved
edge with an endpoint that is not in the graph, and an approved edge that would close a
cycle with the PREREQ edges already there.

The overlay goes on top of a build. ``apply_overlay`` refuses a graph without concepts
(``GraphNotBuiltError``): creating the approved terms there would leave a graph that
looks built to ``scripts/seed_demo.sh``, which would then skip the build.

The overlay only moves the graph towards the domain. Changing an approved entry back to
``proposed`` does not undo what an earlier ``apply`` wrote; rebuild the graph and apply
again for that.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from backend.app.domain.loader import reaches
from backend.app.domain.models import (
    REMOVING_STATUSES,
    WRITING_STATUSES,
    Domain,
    RelationshipEntry,
)
from backend.app.kg.schema import RelationshipType

CURATED_PROVENANCE = "curated"
"""``provenance_source`` of an edge the overlay merged."""

PREREQ_WEIGHT = 0.8
"""Weight of a PREREQ edge the overlay creates: the builder's fixed PREREQ weight."""

CONCEPT_PROPERTIES = ("definition", "aliases", "term_id", "review_status", "definition_source")
"""Concept properties the overlay reads and may set."""


class OperationKind(StrEnum):
    """What an operation does to the graph."""

    CREATE_CONCEPT = "create_concept"
    UPDATE_CONCEPT = "update_concept"
    MERGE_PREREQ = "merge_prereq"
    REMOVE_PREREQ = "remove_prereq"
    REMOVE_CONCEPT = "remove_concept"


REMOVALS = frozenset({OperationKind.REMOVE_PREREQ, OperationKind.REMOVE_CONCEPT})


@dataclass(frozen=True)
class Operation:
    """
    One write to the graph.

    ``name`` is the concept, or the source of an edge; ``target`` is set for edges only.
    ``properties`` holds the values to set: all of them for a new concept or edge, only
    the ones that differ for an existing one. ``None`` removes a property.
    """

    kind: OperationKind
    name: str
    target: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""

    @property
    def is_removal(self) -> bool:
        return self.kind in REMOVALS

    def describe(self) -> str:
        """One line for the plan that ``apply`` prints."""
        changed = ", ".join(self.properties)
        if self.kind is OperationKind.CREATE_CONCEPT:
            return f"create concept {self.name!r} ({self.reason}; the build did not extract it)"
        if self.kind is OperationKind.UPDATE_CONCEPT:
            return f"update concept {self.name!r}: {changed} ({self.reason})"
        if self.kind is OperationKind.MERGE_PREREQ:
            return f"merge PREREQ {self.name!r} -> {self.target!r}: {changed} ({self.reason})"
        if self.kind is OperationKind.REMOVE_PREREQ:
            return f"REMOVE PREREQ {self.name!r} -> {self.target!r} ({self.reason})"
        return f"REMOVE concept {self.name!r} and its edges ({self.reason})"


@dataclass(frozen=True)
class Skipped:
    """A curated entry the overlay did not apply, and why."""

    entry: str
    reason: str

    def describe(self) -> str:
        return f"{self.entry}: {self.reason}"


@dataclass
class GraphState:
    """
    The part of a subject's graph the overlay compares with the domain.

    ``concepts`` maps a concept name to its ``CONCEPT_PROPERTIES`` (a missing property is
    absent or ``None``); ``prereq_edges`` maps (source name, target name) to the edge's
    properties.
    """

    concepts: dict[str, dict[str, Any]] = field(default_factory=dict)
    prereq_edges: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class OverlayResult:
    """What ``apply_overlay`` did, or would do in a dry run."""

    subject_id: str
    operations: tuple[Operation, ...]
    skipped: tuple[Skipped, ...]
    pending: tuple[Operation, ...] = ()
    """Operations still planned after the writes; empty when the graph matches the domain."""
    dry_run: bool = False

    @property
    def removals(self) -> tuple[Operation, ...]:
        return tuple(operation for operation in self.operations if operation.is_removal)


class GraphNotBuiltError(RuntimeError):
    """The subject's graph has no concepts, so there is no build to put the overlay on."""

    def __init__(self, subject_id: str):
        self.subject_id = subject_id
        super().__init__(
            f"the graph of {subject_id} has no concepts; build it first "
            f"(make build-kg SUBJECT={subject_id})"
        )


class OverlayAdapter(Protocol):
    """The methods of ``Neo4jAdapter`` the overlay uses."""

    def get_concept_overlay_state(self) -> list[dict[str, Any]]: ...

    def get_prereq_edges(self) -> list[dict[str, Any]]: ...

    def merge_curated_concept(self, name: str, properties: dict[str, Any]) -> None: ...

    def delete_concept(self, name: str) -> None: ...

    def merge_curated_prereq(
        self, source: str, target: str, properties: dict[str, Any], weight: float
    ) -> None: ...

    def delete_prereq(self, source: str, target: str) -> None: ...


# --------------------------------------------------------------------------- planning


def plan_overlay(domain: Domain | None, state: GraphState) -> list[Operation]:
    """
    The ordered operations that bring ``state`` in line with ``domain``.

    Concepts are created and updated first, then the rejected and deprecated PREREQ edges
    are removed, then the approved ones are merged, and concepts are removed last; within
    a group the order is alphabetical. An edge is removed before its opposite is merged,
    so the graph holds no two-edge cycle between two writes. The plan is empty for
    ``None``, for a domain without approved, rejected or deprecated entries, and for a
    graph that already matches.
    """
    return _plan(domain, state)[0]


def skipped_entries(domain: Domain | None, state: GraphState) -> list[Skipped]:
    """The curated entries that ``plan_overlay`` leaves out, each with the reason."""
    return _plan(domain, state)[1]


def _plan(domain: Domain | None, state: GraphState) -> tuple[list[Operation], list[Skipped]]:
    if domain is None:
        return [], []
    operations: list[Operation] = []
    skipped: list[Skipped] = []

    present = set(state.concepts)
    removed_concepts: list[Operation] = []
    for term in sorted(domain.terms, key=lambda term: term.name):
        reason = f"term {term.id!r} is {term.review_status.value}"
        existing = state.concepts.get(term.name)
        if term.review_status in REMOVING_STATUSES:
            if existing is not None:
                present.discard(term.name)
                removed_concepts.append(
                    Operation(OperationKind.REMOVE_CONCEPT, term.name, reason=reason)
                )
            continue
        if term.review_status not in WRITING_STATUSES:
            continue
        wanted: dict[str, Any] = {
            "term_id": term.id,
            "review_status": term.review_status.value,
            "definition_source": term.definition_source,
        }
        if term.definition is not None:
            wanted["definition"] = term.definition  # the curated definition wins
        if existing is None:
            wanted["aliases"] = list(dict.fromkeys(term.aliases))
            created = {key: value for key, value in wanted.items() if value is not None}
            operations.append(
                Operation(
                    OperationKind.CREATE_CONCEPT, term.name, properties=created, reason=reason
                )
            )
            present.add(term.name)
            continue
        # Union: the stored aliases keep their order, new ones follow in dictionary order
        wanted["aliases"] = list(dict.fromkeys([*(existing.get("aliases") or []), *term.aliases]))
        changes = _changes(existing, wanted)
        if changes:
            operations.append(
                Operation(
                    OperationKind.UPDATE_CONCEPT, term.name, properties=changes, reason=reason
                )
            )

    merged, removed_edges = _plan_edges(domain, state, present, skipped)
    skipped.sort(key=lambda entry: entry.entry)
    return [*operations, *removed_edges, *merged, *removed_concepts], skipped


def _plan_edges(
    domain: Domain, state: GraphState, present: set[str], skipped: list[Skipped]
) -> tuple[list[Operation], list[Operation]]:
    """PREREQ merges and removals, given the concepts ``present`` after the concept steps."""
    curated = sorted(
        (
            relationship
            for relationship in domain.relationships
            if relationship.review_status in WRITING_STATUSES | REMOVING_STATUSES
        ),
        key=lambda relationship: (
            relationship.source,
            relationship.target,
            relationship.type.value,
        ),
    )
    removed: list[Operation] = []
    # Edges that remain: both ends are still there and no reviewer removed the edge
    remaining = {edge for edge in state.prereq_edges if edge[0] in present and edge[1] in present}
    for relationship in curated:
        edge = (relationship.source, relationship.target)
        if relationship.type is not RelationshipType.PREREQ:
            skipped.append(Skipped(_label(relationship), "only PREREQ edges are applied"))
        elif relationship.review_status in REMOVING_STATUSES and edge in remaining:
            remaining.discard(edge)
            removed.append(
                Operation(
                    OperationKind.REMOVE_PREREQ,
                    relationship.source,
                    relationship.target,
                    reason=f"the relationship is {relationship.review_status.value}",
                )
            )

    merged: list[Operation] = []
    for relationship in curated:
        if (
            relationship.type is not RelationshipType.PREREQ
            or relationship.review_status not in WRITING_STATUSES
        ):
            continue
        edge = (relationship.source, relationship.target)
        missing = [name for name in edge if name not in present]
        if missing:
            skipped.append(
                Skipped(_label(relationship), f"{missing[0]!r} is not a concept in the graph")
            )
            continue
        if edge not in remaining and reaches(remaining, relationship.target, relationship.source):
            skipped.append(
                Skipped(
                    _label(relationship),
                    "it would close a cycle with the PREREQ edges in the graph; reject an "
                    "edge on the path that leads back from its target to its source to "
                    "apply this one",
                )
            )
            continue
        wanted = {
            "provenance_source": CURATED_PROVENANCE,
            "review_status": relationship.review_status.value,
            "confidence": relationship.confidence,
            "rule": relationship.rule,
            "evidence_source": relationship.evidence_source,
        }
        existing = state.prereq_edges.get(edge) if edge in remaining else None
        remaining.add(edge)
        changes = (
            _changes(existing, wanted)
            if existing is not None
            else {key: value for key, value in wanted.items() if value is not None}
        )
        if changes:
            merged.append(
                Operation(
                    OperationKind.MERGE_PREREQ,
                    relationship.source,
                    relationship.target,
                    properties=changes,
                    reason="the relationship is approved",
                )
            )
    return merged, removed


def _changes(existing: Mapping[str, Any], wanted: Mapping[str, Any]) -> dict[str, Any]:
    """The wanted properties whose stored value differs (``None`` equals a missing one)."""
    return {key: value for key, value in wanted.items() if existing.get(key) != value}


def _label(relationship: RelationshipEntry) -> str:
    return (
        f"{relationship.type.value} {relationship.source!r} -> {relationship.target!r} "
        f"({relationship.review_status.value})"
    )


# --------------------------------------------------------------------------- applying


def read_graph_state(adapter: OverlayAdapter) -> GraphState:
    """Read the concepts and PREREQ edges of the adapter's subject."""
    concepts = {
        row["name"]: {
            "definition": row.get("definition"),
            "aliases": list(row.get("aliases") or []),
            "term_id": row.get("term_id"),
            "review_status": row.get("review_status"),
            "definition_source": row.get("definition_source"),
        }
        for row in adapter.get_concept_overlay_state()
    }
    edges = {
        (row["source"], row["target"]): dict(row.get("properties") or {})
        for row in adapter.get_prereq_edges()
    }
    return GraphState(concepts=concepts, prereq_edges=edges)


def execute(adapter: OverlayAdapter, operation: Operation) -> None:
    """Run one operation through the adapter."""
    properties = dict(operation.properties)
    if operation.kind in (OperationKind.CREATE_CONCEPT, OperationKind.UPDATE_CONCEPT):
        adapter.merge_curated_concept(operation.name, properties)
    elif operation.kind is OperationKind.REMOVE_CONCEPT:
        adapter.delete_concept(operation.name)
    elif operation.target is None:
        raise ValueError(f"{operation.kind.value} needs a target")
    elif operation.kind is OperationKind.MERGE_PREREQ:
        adapter.merge_curated_prereq(operation.name, operation.target, properties, PREREQ_WEIGHT)
    else:
        adapter.delete_prereq(operation.name, operation.target)


def apply_overlay(
    adapter: OverlayAdapter,
    domain: Domain | None,
    *,
    dry_run: bool = False,
    announce: Callable[[Operation], None] | None = None,
) -> OverlayResult:
    """
    Apply a domain to its subject's graph.

    Args:
        adapter: The subject's Neo4j adapter; its label prefix keeps the writes inside
            the subject.
        domain: The loaded domain; ``None`` (no domain directory) applies nothing.
        dry_run: Plan only, without writing.
        announce: Called with each operation before it runs (in a dry run: with each
            planned operation), so a removal is shown before it happens.

    Returns:
        The operations executed (or planned), the entries skipped and, after a real run,
        the operations a second plan still finds. ``pending`` is empty when the graph
        matches the domain.

    Raises:
        GraphNotBuiltError: The domain has curated entries and the graph has no concepts.
            Nothing is written.
    """
    subject_id = domain.subject_id if domain is not None else ""
    if domain is None or not domain.has_curated_entries:
        # Nothing can be planned, so the graph is not read at all
        return OverlayResult(subject_id, (), (), dry_run=dry_run)
    state = read_graph_state(adapter)
    if not state.concepts:
        raise GraphNotBuiltError(subject_id)
    operations, skipped = _plan(domain, state)
    for operation in operations:
        if announce is not None:
            announce(operation)
        if not dry_run:
            execute(adapter, operation)
    if dry_run or not operations:
        return OverlayResult(subject_id, tuple(operations), tuple(skipped), dry_run=dry_run)
    pending = plan_overlay(domain, read_graph_state(adapter))
    return OverlayResult(subject_id, tuple(operations), tuple(skipped), tuple(pending))
