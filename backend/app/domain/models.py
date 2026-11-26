"""
Models for a subject's domain artifacts (#211): the four YAML files in
``data/domains/<subject_id>/``.

- ``domain.yaml`` (``DomainMeta``): who looks after the domain, how often it is
  reviewed, the bar an entry must meet and the domain's status.
- ``dictionary.yaml`` (``DictionaryFile``): the terms. A term's ``name`` is the
  ``Concept.name`` in the subject's graph.
- ``relationships.yaml`` (``RelationshipsFile``): typed edges between terms; the types
  are those of ``backend.app.kg.schema.RelationshipType``.
- ``sources.yaml`` (``SourcesFile``): the source inventory that definitions and
  evidence cite by id.

Every file carries ``schema_version``, so a later change of shape is detectable, and
unknown keys are rejected, so a misspelt field fails instead of being ignored. These
models check one entry at a time; the checks across entries and files (duplicates,
dangling source ids, relationship endpoints) are in ``backend.app.domain.loader``.

Review statuses of terms and relationships (``ReviewStatus``):

- ``extracted``: written by ``scripts/domain_tool.py draft`` from the builder's output;
  nobody has reviewed it. ``draft`` replaces these entries on every run.
- ``proposed``: a person suggests it; it awaits review.
- ``approved``: reviewed; ``apply`` writes it to the graph.
- ``rejected``: reviewed and refused; ``apply`` removes it from the graph.
- ``deprecated``: approved earlier and withdrawn since; ``apply`` removes it too.

Only ``approved``, ``rejected`` and ``deprecated`` entries change the graph.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from backend.app.core.subjects import SLUG_PATTERN
from backend.app.kg.schema import RelationshipType

SCHEMA_VERSION = 1
"""Version of the file shapes below; every file states it."""


class ReviewStatus(StrEnum):
    """Review status of a dictionary term or a relationship."""

    EXTRACTED = "extracted"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


WRITING_STATUSES = frozenset({ReviewStatus.APPROVED})
"""Statuses whose entries ``apply`` writes to the graph."""

REMOVING_STATUSES = frozenset({ReviewStatus.REJECTED, ReviewStatus.DEPRECATED})
"""Statuses whose entries ``apply`` removes from the graph."""

CURATED_STATUSES = WRITING_STATUSES | REMOVING_STATUSES
"""Statuses a reviewer set and ``apply`` acts on; they need ``reviewed_by`` and ``reviewed_on``."""

LIVE_STATUSES = frozenset({ReviewStatus.EXTRACTED, ReviewStatus.PROPOSED, ReviewStatus.APPROVED})
"""Statuses of entries that are, or may become, part of the graph."""


class SourceStatus(StrEnum):
    """Review status of a source in the inventory."""

    APPROVED = "approved"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class DomainStatus(StrEnum):
    """Status of a domain as a whole. It is informative: ``apply`` follows the entries."""

    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class Origin(StrEnum):
    """Who wrote an entry first."""

    BUILDER = "builder"
    REVIEWER = "reviewer"


def _clean(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("must not be empty or start or end with whitespace")
    return value


def _role(value: str) -> str:
    if "@" in value:
        raise ValueError("name a role (for example 'project maintainer'), not an e-mail address")
    return value


Text = Annotated[str, AfterValidator(_clean)]
"""A non-empty string without surrounding whitespace, kept exactly as written."""

Role = Annotated[str, AfterValidator(_clean), AfterValidator(_role)]
"""Who is responsible, as a role. The files are public: no personal names or addresses."""

Identifier = Annotated[str, StringConstraints(pattern=SLUG_PATTERN, max_length=80)]
"""An id: lower-case words joined by hyphens ("stamp-act", "us-history")."""


def _integer(value: object) -> object:
    if type(value) is not int:
        raise ValueError("must be an integer")
    return value


SchemaVersion = Annotated[Literal[1], BeforeValidator(_integer)]
"""The version a file states: the integer 1. ``true``, ``1.0`` and ``"1"`` are refused."""


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(_Entry):
    """
    Where an entry came from and who reviewed it.

    ``draft`` writes ``origin: builder`` with the builder's ``method`` ("key_term" or
    "keyword" for a term, "glossary" or "cue_phrase" for a relationship) and the
    ``module_id`` it was first extracted from. A reviewer adds ``reviewed_by`` (a role) and
    ``reviewed_on``; both are required once the status is approved, rejected or deprecated.
    """

    origin: Origin
    method: Text | None = None
    module_id: Text | None = None
    reviewed_by: Role | None = None
    reviewed_on: date | None = None
    note: Text | None = None


class DictionaryTerm(_Entry):
    """
    One term of ``dictionary.yaml``.

    Two senses of a word are two terms with different names that share an alias; each
    states the words that select it in ``context_terms`` and may label itself in ``scope``.
    """

    id: Identifier
    name: Text
    aliases: list[Text] = Field(default_factory=list)
    definition: Text | None = None
    definition_source: Identifier | None = None
    scope: Text | None = None
    context_terms: list[Text] = Field(default_factory=list)
    review_status: ReviewStatus
    provenance: Provenance


class RelationshipEntry(_Entry):
    """
    One edge of ``relationships.yaml`` between two terms, named by their ``name``.

    For PREREQ the ``source`` is the prerequisite and the ``target`` the concept that
    depends on it, as in the graph. ``rule`` says why the edge holds: the extraction rule
    for an extracted edge ("glossary_definition": the prerequisite is named in the
    target's glossary definition) or the reviewer's reason.
    """

    source: Text
    target: Text
    type: RelationshipType
    rule: Text | None = None
    evidence_source: Identifier | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: ReviewStatus
    provenance: Provenance


class SourceEntry(_Entry):
    """One source of ``sources.yaml``. ``supersedes`` names the source id it replaces."""

    id: Identifier
    title: Text
    connector: Text
    uri: Text | None = None
    path: Text | None = None
    license: Text
    steward: Role
    review_status: SourceStatus
    supersedes: Identifier | None = None


class DomainMeta(_Entry):
    """``domain.yaml``. An approved domain must state its review cadence and accuracy bar."""

    schema_version: SchemaVersion
    subject_id: Text
    status: DomainStatus
    steward: Role
    review_cadence: Text | None = None
    accuracy_bar: Text | None = None


class DictionaryFile(_Entry):
    """``dictionary.yaml``."""

    schema_version: SchemaVersion
    terms: list[DictionaryTerm] = Field(default_factory=list)


class RelationshipsFile(_Entry):
    """``relationships.yaml``."""

    schema_version: SchemaVersion
    relationships: list[RelationshipEntry] = Field(default_factory=list)


class SourcesFile(_Entry):
    """``sources.yaml``."""

    schema_version: SchemaVersion
    sources: list[SourceEntry] = Field(default_factory=list)


@dataclass(frozen=True)
class Domain:
    """A subject's validated domain artifacts, as ``load_domain`` returns them."""

    subject_id: str
    directory: Path
    meta: DomainMeta
    terms: tuple[DictionaryTerm, ...]
    relationships: tuple[RelationshipEntry, ...]
    sources: tuple[SourceEntry, ...]

    @property
    def review_statuses(self) -> list[ReviewStatus]:
        """The review status of every term and relationship."""
        return [
            *(term.review_status for term in self.terms),
            *(relationship.review_status for relationship in self.relationships),
        ]

    @property
    def has_curated_entries(self) -> bool:
        """Whether ``apply`` has anything to do: an approved, rejected or deprecated entry."""
        return any(status in CURATED_STATUSES for status in self.review_statuses)

    def status_counts(self) -> dict[str, int]:
        """Terms and relationships per review status, in the order of ``ReviewStatus``."""
        statuses = self.review_statuses
        return {
            status.value: statuses.count(status) for status in ReviewStatus if status in statuses
        }
