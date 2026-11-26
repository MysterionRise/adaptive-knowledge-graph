"""
Loader for a subject's domain artifacts (#211).

``load_domain(subject_id)`` reads the four YAML files of ``data/domains/<subject_id>/``,
validates each against its model (``backend.app.domain.models``) and then checks what a
single entry cannot show: duplicate ids and names, a ``definition_source`` or
``evidence_source`` that is not an id in ``sources.yaml``, a relationship whose endpoint
is not a term, an alias shared by two terms without ``context_terms``.

The checks run in two passes, and one ``DomainValidationError`` lists every problem of
the pass that failed. The first pass validates each file against its model. The second
compares entries and files, so it needs all four files to parse: when a file fails the
first pass, the cross-file problems only show once that file is fixed. Each problem names
the file, the field (with its list index) and, where there is one, the entry's id, for
example::

    data/domains/economics/dictionary.yaml: terms[12].definition_source (term 'gdp'):
    'principles' is not a source id in sources.yaml

A subject without a directory has no curated domain: ``load_domain`` returns ``None``,
which is the state of every subject before its first draft.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from backend.app.domain.models import (
    CURATED_STATUSES,
    LIVE_STATUSES,
    REMOVING_STATUSES,
    DictionaryFile,
    DictionaryTerm,
    Domain,
    DomainMeta,
    DomainStatus,
    Provenance,
    RelationshipEntry,
    RelationshipsFile,
    ReviewStatus,
    SourceEntry,
    SourcesFile,
)
from backend.app.kg.normalize import query_key
from backend.app.kg.schema import RelationshipType

DOMAIN_FILE = "domain.yaml"
DICTIONARY_FILE = "dictionary.yaml"
RELATIONSHIPS_FILE = "relationships.yaml"
SOURCES_FILE = "sources.yaml"
DOMAIN_FILES = (DOMAIN_FILE, DICTIONARY_FILE, RELATIONSHIPS_FILE, SOURCES_FILE)

CONCEPT_RELATIONSHIP_TYPES = frozenset({RelationshipType.PREREQ, RelationshipType.RELATED})
"""Relationship types that link two concepts, and so two terms."""

_SUBJECT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_REVIEWED_STATUSES = (ReviewStatus.PROPOSED, ReviewStatus.APPROVED)

_Model = TypeVar("_Model", bound=BaseModel)


@dataclass(frozen=True)
class DomainError:
    """One validation problem: the file, the field and what is wrong with it."""

    path: Path
    field: str
    message: str
    entry: str | None = None
    """What identifies the entry: "term 'stamp-act'", "source 'us-history'"."""

    def __str__(self) -> str:
        where = f"{self.field} ({self.entry})" if self.entry else self.field
        return f"{self.path}: {where}: {self.message}"


class DomainValidationError(ValueError):
    """A domain's files are invalid; ``errors`` lists every problem found."""

    def __init__(self, errors: list[DomainError]):
        self.errors = errors
        super().__init__("\n".join(str(error) for error in errors))


def default_domains_root() -> Path:
    """``data/domains``: under the working directory when present, else in the repository."""
    local = Path.cwd() / "data" / "domains"
    if local.is_dir():
        return local
    # backend/app/domain/loader.py -> parents[3] is the repository root
    return Path(__file__).resolve().parents[3] / "data" / "domains"


def domain_directories(root: Path | None = None) -> list[Path]:
    """
    The subject directories under ``root``, sorted by name.

    A hidden directory (a name that starts with a dot) is a tool's cache, not a domain,
    and is left out.
    """
    root = root if root is not None else default_domains_root()
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def load_domain(subject_id: str, root: Path | None = None) -> Domain | None:
    """
    Load and validate the domain artifacts of one subject.

    Args:
        subject_id: The subject, which is also the directory name under ``root``.
        root: Directory that holds one directory per subject (default: ``data/domains``).

    Returns:
        The validated ``Domain``, or ``None`` when the subject has no directory.

    Raises:
        DomainValidationError: A file is missing, is not valid YAML or fails a check.
        ValueError: ``subject_id`` is not a plain directory name.
    """
    if not _SUBJECT_ID_RE.fullmatch(subject_id):
        raise ValueError(f"invalid subject id: {subject_id!r}")
    root = root if root is not None else default_domains_root()
    directory = root / subject_id
    if not directory.is_dir():
        return None

    errors: list[DomainError] = []
    meta = _parse(DomainMeta, directory / DOMAIN_FILE, errors)
    dictionary = _parse(DictionaryFile, directory / DICTIONARY_FILE, errors)
    relationships = _parse(RelationshipsFile, directory / RELATIONSHIPS_FILE, errors)
    sources = _parse(SourcesFile, directory / SOURCES_FILE, errors)
    if meta is None or dictionary is None or relationships is None or sources is None:
        raise DomainValidationError(errors)

    errors.extend(_check_meta(directory / DOMAIN_FILE, meta, subject_id))
    errors.extend(_check_sources(directory / SOURCES_FILE, sources.sources))
    source_ids = {source.id for source in sources.sources}
    errors.extend(_check_terms(directory / DICTIONARY_FILE, dictionary.terms, source_ids))
    errors.extend(
        _check_relationships(
            directory / RELATIONSHIPS_FILE,
            relationships.relationships,
            dictionary.terms,
            source_ids,
        )
    )
    if errors:
        raise DomainValidationError(errors)
    return Domain(
        subject_id=subject_id,
        directory=directory,
        meta=meta,
        terms=tuple(dictionary.terms),
        relationships=tuple(relationships.relationships),
        sources=tuple(sources.sources),
    )


def unresolved_shared_aliases(domain: Domain) -> dict[str, list[str]]:
    """
    Aliases that several terms share and that ``context_terms`` do not tell apart yet.

    The builder can give one alias to two concepts ("AD" for "Aggregate Demand" and
    "Aggregate Demand Curve"). That is not an error while the terms are ``extracted``;
    it becomes one for a term that is proposed or approved without ``context_terms``.
    Returns each such alias key with the names of the terms that share it.
    """
    unresolved: dict[str, list[str]] = {}
    for key, sharing in sorted(_alias_groups(domain.terms).items()):
        if len(sharing) < 2:
            continue
        holders = [term for term in sharing if any(query_key(a) == key for a in term.aliases)]
        if any(not term.context_terms for term in holders):
            unresolved[key] = sorted(term.name for term in sharing)
    return unresolved


# --------------------------------------------------------------------------- reading


def read_yaml_mapping(path: Path, errors: list[DomainError]) -> dict[str, Any] | None:
    """The mapping in a YAML file, or ``None`` after recording why it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(DomainError(path, "<file>", "the file is missing"))
        return None
    except (OSError, UnicodeDecodeError) as e:
        errors.append(DomainError(path, "<file>", f"cannot be read: {e}"))
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        errors.append(
            DomainError(path, "<document>", f"not valid YAML: {' '.join(str(e).split())}")
        )
        return None
    if not isinstance(data, dict):
        errors.append(DomainError(path, "<document>", "expected a mapping at the top level"))
        return None
    return data


def _parse(model: type[_Model], path: Path, errors: list[DomainError]) -> _Model | None:
    data = read_yaml_mapping(path, errors)
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        for problem in e.errors():
            location = problem["loc"]
            errors.append(
                DomainError(
                    path,
                    _field_path(location),
                    _problem_message(problem),
                    _entry_label(data, location),
                )
            )
        return None


def _field_path(location: tuple[int | str, ...]) -> str:
    """("terms", 3, "review_status") -> "terms[3].review_status"."""
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "<document>"


def _problem_message(problem: Any) -> str:
    kind = problem["type"]
    if kind == "missing":
        return "the field is required"
    if kind == "extra_forbidden":
        return "unknown field"
    value = repr(problem.get("input"))
    if len(value) > 80:
        value = value[:77] + "..."
    message = str(problem["msg"]).removeprefix("Value error, ")
    return f"{message[:1].lower()}{message[1:]} (got {value})"


def _entry_label(data: dict[str, Any], location: tuple[int | str, ...]) -> str | None:
    """Identify the list entry a field path points into, from the raw data."""
    if len(location) < 2 or not isinstance(location[1], int):
        return None
    entries = data.get(str(location[0]))
    if not isinstance(entries, list) or location[1] >= len(entries):
        return None
    entry = entries[location[1]]
    if not isinstance(entry, dict):
        return None
    if location[0] == "relationships":
        if "source" in entry and "target" in entry:
            return f"relationship {entry['source']!r} -> {entry['target']!r}"
        return None
    label = entry.get("id") or entry.get("name")
    return f"{str(location[0]).rstrip('s')} {label!r}" if label else None


# --------------------------------------------------------------------------- checks


def _check_meta(path: Path, meta: DomainMeta, subject_id: str) -> list[DomainError]:
    errors: list[DomainError] = []
    if meta.subject_id != subject_id:
        errors.append(
            DomainError(
                path,
                "subject_id",
                f"{meta.subject_id!r} does not match the directory name {subject_id!r}",
            )
        )
    if meta.status is DomainStatus.APPROVED:
        for field in ("review_cadence", "accuracy_bar"):
            if getattr(meta, field) is None:
                errors.append(DomainError(path, field, "an approved domain must state it"))
    return errors


def _check_sources(path: Path, sources: list[SourceEntry]) -> list[DomainError]:
    errors: list[DomainError] = []
    ids = {source.id for source in sources}
    seen: set[str] = set()
    for index, source in enumerate(sources):
        entry = f"source {source.id!r}"
        if source.id in seen:
            errors.append(DomainError(path, f"sources[{index}].id", "duplicate source id", entry))
        seen.add(source.id)
        if source.uri is None and source.path is None:
            errors.append(
                DomainError(path, f"sources[{index}].uri", "a source needs a uri or a path", entry)
            )
        if source.supersedes is not None:
            field = f"sources[{index}].supersedes"
            if source.supersedes == source.id:
                errors.append(DomainError(path, field, "a source cannot supersede itself", entry))
            elif source.supersedes not in ids:
                errors.append(
                    DomainError(
                        path, field, f"{source.supersedes!r} is not a source id in this file", entry
                    )
                )
    return errors


def _check_review(
    path: Path, field: str, entry: str, status: ReviewStatus, provenance: Provenance
) -> list[DomainError]:
    """An approved, rejected or deprecated entry records who reviewed it and when."""
    if status not in CURATED_STATUSES:
        return []
    return [
        DomainError(
            path,
            f"{field}.provenance.{name}",
            f"required when review_status is {status.value}",
            entry,
        )
        for name in ("reviewed_by", "reviewed_on")
        if getattr(provenance, name) is None
    ]


def _alias_groups(terms: Iterable[DictionaryTerm]) -> dict[str, list[DictionaryTerm]]:
    """
    Live terms per alias key, for the keys at least one of them uses as an alias.

    A term counts for a key when the key is one of its aliases or its name, so an alias
    that is another term's name is found as well. Keys are ``query_key`` forms: case, a
    leading article and a plural last word are ignored, as in the query-time lexicon.
    """
    holders: dict[str, dict[str, DictionaryTerm]] = defaultdict(dict)
    alias_keys: set[str] = set()
    for term in terms:
        if term.review_status not in LIVE_STATUSES:
            continue
        name_key = query_key(term.name)
        if name_key:
            holders[name_key][term.id] = term
        for alias in term.aliases:
            key = query_key(alias)
            if key and key != name_key:
                holders[key][term.id] = term
                alias_keys.add(key)
    return {key: list(holders[key].values()) for key in alias_keys}


def _check_terms(
    path: Path, terms: list[DictionaryTerm], source_ids: set[str]
) -> list[DomainError]:
    errors: list[DomainError] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    live_name_keys: dict[str, str] = {}
    for index, term in enumerate(terms):
        field = f"terms[{index}]"
        entry = f"term {term.id!r}"
        if term.id in seen_ids:
            errors.append(DomainError(path, f"{field}.id", "duplicate term id", entry))
        seen_ids.add(term.id)
        if term.name in seen_names:
            errors.append(
                DomainError(path, f"{field}.name", f"duplicate term name {term.name!r}", entry)
            )
        elif term.review_status in LIVE_STATUSES and query_key(term.name):
            # A name without a letter or digit in a-z and 0-9 has no key to compare
            other = live_name_keys.setdefault(query_key(term.name), term.id)
            if other != term.id:
                errors.append(
                    DomainError(
                        path,
                        f"{field}.name",
                        f"{term.name!r} differs from the name of term {other!r} only by case, "
                        "an article or a plural",
                        entry,
                    )
                )
        seen_names.add(term.name)
        for position, alias in enumerate(term.aliases):
            if alias in term.aliases[:position]:
                errors.append(
                    DomainError(
                        path, f"{field}.aliases[{position}]", f"duplicate alias {alias!r}", entry
                    )
                )
        if term.definition_source is not None:
            if term.definition is None:
                errors.append(
                    DomainError(
                        path,
                        f"{field}.definition_source",
                        "set without a definition",
                        entry,
                    )
                )
            if term.definition_source not in source_ids:
                errors.append(
                    DomainError(
                        path,
                        f"{field}.definition_source",
                        f"{term.definition_source!r} is not a source id in {SOURCES_FILE}",
                        entry,
                    )
                )
        errors.extend(_check_review(path, field, entry, term.review_status, term.provenance))

    positions = {term.id: index for index, term in enumerate(terms)}
    for key, sharing in sorted(_alias_groups(terms).items()):
        if len(sharing) < 2:
            continue
        for term in sharing:
            if term.review_status not in _REVIEWED_STATUSES or term.context_terms:
                continue
            aliases = [alias for alias in term.aliases if query_key(alias) == key]
            if not aliases:
                continue  # the key is this term's name; the terms that alias it are checked
            others = sorted(other.id for other in sharing if other.id != term.id)
            position = term.aliases.index(aliases[0])
            errors.append(
                DomainError(
                    path,
                    f"terms[{positions[term.id]}].aliases[{position}]",
                    f"alias {aliases[0]!r} is also an alias or the name of {others}; "
                    "add context_terms to tell the senses apart",
                    f"term {term.id!r}",
                )
            )
    return errors


def _check_relationships(
    path: Path,
    relationships: list[RelationshipEntry],
    terms: list[DictionaryTerm],
    source_ids: set[str],
) -> list[DomainError]:
    errors: list[DomainError] = []
    status_by_name = {term.name: term.review_status for term in terms}
    seen: set[tuple[str, str, RelationshipType]] = set()
    for index, relationship in enumerate(relationships):
        field = f"relationships[{index}]"
        entry = f"relationship {relationship.source!r} -> {relationship.target!r}"
        if relationship.type not in CONCEPT_RELATIONSHIP_TYPES:
            allowed = ", ".join(sorted(kind.value for kind in CONCEPT_RELATIONSHIP_TYPES))
            errors.append(
                DomainError(
                    path,
                    f"{field}.type",
                    f"{relationship.type.value} does not link two terms; use one of {allowed}",
                    entry,
                )
            )
        for end in ("source", "target"):
            name = getattr(relationship, end)
            if name not in status_by_name:
                errors.append(
                    DomainError(
                        path,
                        f"{field}.{end}",
                        f"{name!r} is not a term name in {DICTIONARY_FILE}",
                        entry,
                    )
                )
            elif (
                relationship.review_status is ReviewStatus.APPROVED
                and status_by_name[name] in REMOVING_STATUSES
            ):
                errors.append(
                    DomainError(
                        path,
                        f"{field}.{end}",
                        f"an approved relationship cannot use the {status_by_name[name].value} "
                        f"term {name!r}",
                        entry,
                    )
                )
        if relationship.source == relationship.target:
            errors.append(
                DomainError(path, f"{field}.target", "a term cannot be related to itself", entry)
            )
        key = (relationship.source, relationship.target, relationship.type)
        if key in seen:
            errors.append(DomainError(path, f"{field}.type", "duplicate relationship", entry))
        seen.add(key)
        if (
            relationship.evidence_source is not None
            and relationship.evidence_source not in source_ids
        ):
            errors.append(
                DomainError(
                    path,
                    f"{field}.evidence_source",
                    f"{relationship.evidence_source!r} is not a source id in {SOURCES_FILE}",
                    entry,
                )
            )
        errors.extend(
            _check_review(path, field, entry, relationship.review_status, relationship.provenance)
        )
    errors.extend(_check_prereq_cycles(path, relationships))
    return errors


def _check_prereq_cycles(path: Path, relationships: list[RelationshipEntry]) -> list[DomainError]:
    """The approved PREREQ edges must have an order: a learning path cannot follow a cycle."""
    approved = [
        (index, relationship)
        for index, relationship in enumerate(relationships)
        if relationship.type is RelationshipType.PREREQ
        and relationship.review_status is ReviewStatus.APPROVED
        and relationship.source != relationship.target
    ]
    errors: list[DomainError] = []
    accepted: set[tuple[str, str]] = set()
    for index, relationship in approved:
        if reaches(accepted, relationship.target, relationship.source):
            errors.append(
                DomainError(
                    path,
                    f"relationships[{index}].target",
                    "closes a cycle of approved PREREQ relationships",
                    f"relationship {relationship.source!r} -> {relationship.target!r}",
                )
            )
        else:
            accepted.add((relationship.source, relationship.target))
    return errors


def reaches(edges: Iterable[tuple[str, str]], start: str, goal: str) -> bool:
    """Whether ``goal`` can be reached from ``start`` along the directed ``edges``."""
    following: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        following[source].append(target)
    pending = [start]
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node == goal:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(following[node])
    return False
