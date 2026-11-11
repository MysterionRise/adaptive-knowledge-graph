"""
Validate, draft, apply and export a subject's domain artifacts (#211).

The artifacts are the four YAML files in data/domains/<subject_id>/ (docs/DOMAINS.md).

    python scripts/domain_tool.py validate                      # every domain directory
    python scripts/domain_tool.py validate --subject economics
    python scripts/domain_tool.py draft --subject economics
    python scripts/domain_tool.py apply --subject economics [--dry-run]
    python scripts/domain_tool.py export --subject economics --format csv --table terms
    python scripts/domain_tool.py export --subject economics --format json --out domain.json

validate  Checks every file against its schema and the files against each other. Each
          problem names the file and the field. Exit status 1 when a domain is invalid.
          When the last graph build left its JSON copy (data/processed/build/), it also
          lists the dictionary names the build lacks, the build's concepts the dictionary
          lacks and the build's concepts that a rejected term names in another spelling;
          these lines are a report, not an error.
draft     Writes the last graph build as entries with review_status "extracted": the
          concepts to dictionary.yaml and the PREREQ edges to relationships.yaml. It
          replaces the extracted entries and keeps the values of every other entry. Both
          files are rewritten with sorted keys, so comments and formatting are not kept.
          domain.yaml and sources.yaml are written once and never rewritten. Run the
          build first (make build-kg, or build_knowledge_graph.py --no-persist without
          Neo4j).
apply     Applies the approved, rejected and deprecated entries to the subject's graph in
          Neo4j and prints every operation, removals included. It is idempotent, does
          nothing (and does not connect) for a subject without such entries, and refuses
          to run when Neo4j is not reachable or the graph has no concepts (build it
          first). --dry-run prints the plan without writing.
export    Prints the domain as flat rows: CSV for one table (terms, relationships or
          sources) or JSON for all three.

Each subcommand exits 0 on success and 1 on failure.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.settings import settings  # noqa: E402
from backend.app.core.subjects import (  # noqa: E402
    SubjectConfig,
    get_subject,
    get_subject_ids,
    slug,
)
from backend.app.domain.loader import (  # noqa: E402
    DICTIONARY_FILE,
    DOMAIN_FILE,
    RELATIONSHIPS_FILE,
    SOURCES_FILE,
    DomainError,
    DomainValidationError,
    default_domains_root,
    domain_directories,
    load_domain,
    unresolved_shared_aliases,
)
from backend.app.domain.models import (  # noqa: E402
    LIVE_STATUSES,
    REMOVING_STATUSES,
    SCHEMA_VERSION,
    Domain,
    DomainStatus,
    Origin,
    Provenance,
    ReviewStatus,
    SourceStatus,
)
from backend.app.domain.overlay import (  # noqa: E402
    GraphNotBuiltError,
    Operation,
    apply_overlay,
)
from backend.app.kg.neo4j_adapter import get_neo4j_adapter  # noqa: E402
from backend.app.kg.normalize import query_key  # noqa: E402
from backend.app.kg.schema import (  # noqa: E402
    ConceptNode,
    KnowledgeGraph,
    Relationship,
    RelationshipType,
)

DEFAULT_STEWARD = "project maintainer"
"""Steward written by ``draft``: a role, never a person's name or address."""

DRAFT_HEADER = (
    "# Written by scripts/domain_tool.py draft (docs/DOMAINS.md). The command replaces the\n"
    "# entries with review_status: extracted and keeps the values of every other entry. It\n"
    "# rewrites the file with sorted keys: comments and formatting are not kept.\n"
)
ONCE_HEADER = (
    "# Written once by scripts/domain_tool.py draft (docs/DOMAINS.md) and edited by hand\n"
    "# since: the command never rewrites this file.\n"
)

PROVENANCE_FIELDS = tuple(Provenance.model_fields)
TERM_COLUMNS = (
    "subject_id",
    "id",
    "name",
    "aliases",
    "definition",
    "definition_source",
    "scope",
    "context_terms",
    "review_status",
    *(f"provenance_{name}" for name in PROVENANCE_FIELDS),
)
RELATIONSHIP_COLUMNS = (
    "subject_id",
    "source",
    "target",
    "type",
    "rule",
    "evidence_source",
    "confidence",
    "review_status",
    *(f"provenance_{name}" for name in PROVENANCE_FIELDS),
)
SOURCE_COLUMNS = (
    "subject_id",
    "id",
    "title",
    "connector",
    "uri",
    "path",
    "license",
    "steward",
    "review_status",
    "supersedes",
)
TABLE_COLUMNS = {
    "terms": TERM_COLUMNS,
    "relationships": RELATIONSHIP_COLUMNS,
    "sources": SOURCE_COLUMNS,
}
LIST_SEPARATOR = "; "
"""Joins the values of a list cell (aliases, context_terms) in CSV."""

DIRECTORY_FIELD = "<directory>"
"""Field of an error about a domain directory as a whole."""

MAX_LISTED = 10
_LICENSE_RE = re.compile(r"\bCC(?: [A-Z]{2,})?(?:-[A-Z]{2,})* \d(?:\.\d)?\b")


def _report(summary: str, details: list[str] | None = None) -> None:
    print(summary)
    for line in details or []:
        print(f"    {line}")


def _listed(names: list[str]) -> str:
    shown = ", ".join(names[:MAX_LISTED])
    return shown if len(names) <= MAX_LISTED else f"{shown} and {len(names) - MAX_LISTED} more"


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root) if args.root else default_domains_root()


def _subject(args: argparse.Namespace) -> SubjectConfig | None:
    """The configured subject of --subject (default subject without it), or None after reporting."""
    try:
        return get_subject(args.subject)
    except KeyError:
        _report(
            f"Unknown subject {args.subject!r}",
            [f"configured in config/subjects.yaml: {', '.join(get_subject_ids())}"],
        )
        return None


def _load(subject_id: str, root: Path) -> tuple[Domain | None, list[DomainError]]:
    try:
        return load_domain(subject_id, root), []
    except DomainValidationError as e:
        return None, e.errors
    except ValueError:
        # Not a name load_domain takes as a directory (".cache", "a/b")
        return None, [
            DomainError(
                root / subject_id,
                DIRECTORY_FIELD,
                "the name is not a subject id (letters, digits, '_' and '-')",
            )
        ]


def _first_line(error: Exception) -> str:
    """The first line of an error's text, or its class name when it has none."""
    return str(error).splitlines()[0] if str(error) else type(error).__name__


def _status_summary(domain: Domain) -> str:
    counts = ", ".join(f"{count} {status}" for status, count in domain.status_counts().items())
    return (
        f"{len(domain.terms)} terms, {len(domain.relationships)} relationships, "
        f"{len(domain.sources)} sources; entries: {counts or 'none'}"
    )


def build_result_path(subject_id: str) -> Path:
    """Where ``build_knowledge_graph.py`` leaves the JSON copy of a subject's graph."""
    return Path(settings.data_processed_dir) / "build" / f"knowledge_graph_{subject_id}.json"


def load_build(path: Path) -> KnowledgeGraph:
    return KnowledgeGraph.model_validate_json(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- validate


def build_drift(domain: Domain, concept_names: set[str]) -> tuple[list[str], list[str]]:
    """
    How a dictionary and a graph build differ, as two sorted lists of names.

    The first lists the extracted, proposed and approved terms the build does not have
    (``apply`` would create the approved ones); the second lists the build's concepts
    that no term names, whatever its status (``draft`` would add them).
    """
    live = {term.name for term in domain.terms if term.review_status in LIVE_STATUSES}
    known = {term.name for term in domain.terms}
    return sorted(live - concept_names), sorted(concept_names - known)


def respelt_removed_concepts(domain: Domain, concept_names: set[str]) -> list[str]:
    """
    Build concepts that a rejected or deprecated term names in another spelling.

    ``apply`` removes a concept by its exact name. When the builder changes the case or the
    number of a name ("Summary" becomes "summary"), the concept a reviewer removed comes
    back under the new spelling. Each is returned as "'<concept>' (term '<name>')".
    """
    removed = {
        query_key(term.name): term.name
        for term in domain.terms
        if term.review_status in REMOVING_STATUSES and query_key(term.name)
    }
    return sorted(
        f"{name!r} (term {removed[query_key(name)]!r})"
        for name in concept_names
        if removed.get(query_key(name), name) != name
    )


def inventory_drift(domain: Domain, subject: SubjectConfig) -> tuple[list[str], list[str]]:
    """Configured book ids missing from sources.yaml, and current source ids not configured."""
    configured = {book.id for book in subject.books}
    current = {
        source.id for source in domain.sources if source.review_status is SourceStatus.APPROVED
    }
    return sorted(configured - current), sorted(current - configured)


def _notices(domain: Domain, build_path: Path) -> list[str]:
    """Report-only lines of ``validate``."""
    notices: list[str] = []
    shared = unresolved_shared_aliases(domain)
    if shared:
        examples = [f"{key!r} ({', '.join(names)})" for key, names in shared.items()]
        notices.append(
            f"report: {len(shared)} alias(es) shared by several terms without context_terms: "
            f"{_listed(examples)}"
        )
    missing_books, unknown_sources = inventory_drift(domain, get_subject(domain.subject_id))
    if missing_books:
        notices.append(f"report: configured books without an approved source: {missing_books}")
    if unknown_sources:
        notices.append(f"report: approved sources that are not configured books: {unknown_sources}")
    if not build_path.is_file():
        notices.append(f"report: no graph build at {build_path}, so the build was not compared")
        return notices
    try:
        concept_names = set(load_build(build_path).concepts)
    except (OSError, ValueError) as e:
        notices.append(f"report: cannot read the graph build {build_path}: {_first_line(e)}")
        return notices
    not_in_build, not_in_dictionary = build_drift(domain, concept_names)
    if not_in_build:
        notices.append(
            f"report: {len(not_in_build)} dictionary name(s) missing from the build "
            f"({build_path}): {_listed(not_in_build)}"
        )
    if not_in_dictionary:
        notices.append(
            f"report: {len(not_in_dictionary)} build concept(s) missing from the dictionary "
            f"(run draft): {_listed(not_in_dictionary)}"
        )
    if not not_in_build and not not_in_dictionary:
        notices.append(f"report: the dictionary names every concept of the build ({build_path})")
    respelt = respelt_removed_concepts(domain, concept_names)
    if respelt:
        notices.append(
            f"report: {len(respelt)} build concept(s) differ from a rejected or deprecated term "
            f"only by case, an article or a plural, so apply does not remove them: "
            f"{_listed(respelt)}"
        )
    return notices


def cmd_validate(args: argparse.Namespace) -> int:
    root = _root(args)
    subject_ids = args.subject or [path.name for path in domain_directories(root)]
    if not subject_ids:
        _report(f"No domain directories under {root}")
        return 0
    configured = set(get_subject_ids())
    invalid = 0
    for subject_id in subject_ids:
        domain, errors = _load(subject_id, root)
        named = bool(errors) and errors[0].field == DIRECTORY_FIELD
        if subject_id not in configured and not named:
            errors.insert(
                0,
                DomainError(
                    root / subject_id,
                    DIRECTORY_FIELD,
                    "no subject with this id in config/subjects.yaml",
                ),
            )
        if errors:
            invalid += 1
            _report(
                f"{subject_id}: INVALID ({len(errors)} error(s))", [str(error) for error in errors]
            )
        elif domain is None:
            _report(f"{subject_id}: no domain directory under {root} (no curated domain)")
        else:
            build_path = Path(args.build) if args.build else build_result_path(subject_id)
            _report(
                f"{subject_id}: valid ({_status_summary(domain)})", _notices(domain, build_path)
            )
    return 1 if invalid else 0


# --------------------------------------------------------------------------- draft


MAX_ID_BASE = 72
"""Longest slug taken from a name: ids hold at most 80 characters, a suffix needs room."""


def unique_id(name: str, used: set[str]) -> str:
    """``slug(name)``, with a numeric suffix when that id is taken; the id is added to ``used``."""
    base = slug(name)[:MAX_ID_BASE].strip("-") or "term"
    candidate, suffix = base, 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _cleaned(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


def _term_entry(concept: ConceptNode, term_id: str, source_id: str | None) -> dict[str, Any]:
    definition = _cleaned(concept.definition)
    provenance: dict[str, Any] = {
        "origin": Origin.BUILDER.value,
        "method": "key_term" if concept.key_term else "keyword",
    }
    if concept.source_modules:
        provenance["module_id"] = concept.source_modules[0]
    aliases = {alias.strip() for alias in concept.aliases} - {"", concept.name}
    return {
        "id": term_id,
        "name": concept.name,
        "aliases": sorted(aliases),
        "definition": definition,
        "definition_source": source_id if definition else None,
        "review_status": ReviewStatus.EXTRACTED.value,
        "provenance": provenance,
    }


def draft_terms(
    kg: KnowledgeGraph, existing: list[dict[str, Any]], source_id: str | None
) -> list[dict[str, Any]]:
    """
    The terms of a new dictionary.yaml, sorted by id.

    Entries of ``existing`` whose status is not "extracted" are returned with their values
    unchanged. The extracted ones are replaced by the build's concepts, and a concept a
    reviewed entry already names is not added again. A concept that is still built keeps
    the id it had: those ids are reserved before a new name gets one, so a new name with
    the same slug ("AD-AS Model" next to "AD/AS Model") takes a suffix and never an id
    that already names another concept.
    """
    kept = [term for term in existing if term.get("review_status") != ReviewStatus.EXTRACTED]
    kept_names = {term.get("name") for term in kept}
    used = {str(term.get("id")) for term in kept}
    previous = {
        term.get("name"): str(term.get("id"))
        for term in existing
        if term.get("review_status") == ReviewStatus.EXTRACTED
    }
    names = [name for name in sorted(kg.concepts) if name not in kept_names]
    ids: dict[str, str] = {}
    for name in names:
        earlier = previous.get(name)
        if earlier and earlier not in used:
            used.add(earlier)
            ids[name] = earlier
    drafted = [
        _term_entry(kg.concepts[name], ids.get(name) or unique_id(name, used), source_id)
        for name in names
    ]
    return sorted([*kept, *drafted], key=lambda term: str(term.get("id")))


def _relationship_entry(relationship: Relationship, source_id: str | None) -> dict[str, Any]:
    builder = relationship.provenance or {}
    method = builder.get("source")
    provenance: dict[str, Any] = {"origin": Origin.BUILDER.value}
    if method:
        provenance["method"] = method
    if builder.get("module_id"):
        provenance["module_id"] = builder["module_id"]
    if method == "glossary":
        rule: str | None = "glossary_definition"
    elif method == "cue_phrase" and builder.get("pattern"):
        rule = f"cue_phrase:{builder['pattern']}"
    else:
        rule = method
    return {
        "source": relationship.source,
        "target": relationship.target,
        "type": relationship.type.value,
        "rule": rule,
        "evidence_source": source_id,
        "confidence": relationship.confidence,
        "review_status": ReviewStatus.EXTRACTED.value,
        "provenance": provenance,
    }


def draft_relationships(
    kg: KnowledgeGraph, existing: list[dict[str, Any]], source_id: str | None
) -> list[dict[str, Any]]:
    """
    The entries of a new relationships.yaml, sorted by type, source and target.

    Only the build's PREREQ edges are drafted: they carry evidence a reviewer can check,
    while the RELATED edges are association scores. Entries whose status is not
    "extracted" are returned with their values unchanged and are not drafted again.
    """
    kept = [entry for entry in existing if entry.get("review_status") != ReviewStatus.EXTRACTED]
    kept_keys = {(entry.get("source"), entry.get("target"), entry.get("type")) for entry in kept}
    drafted = [
        _relationship_entry(relationship, source_id)
        for relationship in kg.relationships
        if relationship.type is RelationshipType.PREREQ
        and (relationship.source, relationship.target, relationship.type.value) not in kept_keys
    ]
    return sorted(
        [*kept, *drafted],
        key=lambda entry: (
            str(entry.get("type")),
            str(entry.get("source")),
            str(entry.get("target")),
        ),
    )


def render_entries(key: str, entries: list[dict[str, Any]]) -> str:
    """dictionary.yaml or relationships.yaml as text: the version first, entry keys sorted."""
    body = yaml.safe_dump(
        {key: entries}, sort_keys=True, allow_unicode=True, default_flow_style=False, width=100
    )
    return f"{DRAFT_HEADER}schema_version: {SCHEMA_VERSION}\n{body}"


def _render_once(document: dict[str, Any]) -> str:
    body = yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    )
    return f"{ONCE_HEADER}{body}"


def source_license(attribution: str) -> str:
    """The licence a subject's attribution states ("CC BY 4.0"), else the attribution itself."""
    match = _LICENSE_RE.search(attribution)
    return match.group(0) if match else attribution.strip()


def render_sources(subject: SubjectConfig) -> str:
    """A first sources.yaml: one approved entry per configured book of the subject."""
    sources = []
    for book in subject.books:
        if book.source_type == "openstax_web" and book.openstax_slug:
            uri: str | None = f"https://openstax.org/books/{book.openstax_slug}"
        else:
            uri = book.repo_url_raw
        sources.append(
            {
                "id": book.id,
                "title": book.title,
                "connector": book.connector,
                "uri": uri,
                "license": source_license(subject.attribution),
                "steward": DEFAULT_STEWARD,
                "review_status": SourceStatus.APPROVED.value,
                "supersedes": None,
            }
        )
    return _render_once({"schema_version": SCHEMA_VERSION, "sources": sources})


def render_domain(subject_id: str) -> str:
    """A first domain.yaml: a draft, with the cadence and the accuracy bar left to the steward."""
    return _render_once(
        {
            "schema_version": SCHEMA_VERSION,
            "subject_id": subject_id,
            "status": DomainStatus.DRAFT.value,
            "steward": DEFAULT_STEWARD,
            "review_cadence": None,
            "accuracy_bar": None,
        }
    )


def _existing_entries(path: Path, key: str) -> list[dict[str, Any]]:
    """The raw entries of an existing, already validated file."""
    if not path.is_file():
        return []
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(key) or []
    return [entry for entry in entries if isinstance(entry, dict)]


def draft_files(subject: SubjectConfig, kg: KnowledgeGraph, directory: Path) -> dict[str, str]:
    """
    The text of the four files after a draft, by file name.

    domain.yaml and sources.yaml keep their text when they exist. A definition and its
    PREREQ evidence cite the subject's source when the inventory has exactly one current
    source; with several, the build does not say which book a term came from, so
    ``definition_source`` and ``evidence_source`` stay empty for the reviewer.
    """
    files: dict[str, str] = {}
    for name, rendered in (
        (DOMAIN_FILE, render_domain(subject.id)),
        (SOURCES_FILE, render_sources(subject)),
    ):
        path = directory / name
        files[name] = path.read_text(encoding="utf-8") if path.is_file() else rendered
    sources = (yaml.safe_load(files[SOURCES_FILE]) or {}).get("sources") or []
    current = [
        source.get("id")
        for source in sources
        if isinstance(source, dict) and source.get("review_status") == SourceStatus.APPROVED
    ]
    source_id = current[0] if len(current) == 1 else None
    files[DICTIONARY_FILE] = render_entries(
        "terms", draft_terms(kg, _existing_entries(directory / DICTIONARY_FILE, "terms"), source_id)
    )
    files[RELATIONSHIPS_FILE] = render_entries(
        "relationships",
        draft_relationships(
            kg, _existing_entries(directory / RELATIONSHIPS_FILE, "relationships"), source_id
        ),
    )
    return files


def cmd_draft(args: argparse.Namespace) -> int:
    subject = _subject(args)
    if subject is None:
        return 1
    root = _root(args)
    directory = root / subject.id
    build_path = Path(args.build) if args.build else build_result_path(subject.id)
    if not build_path.is_file():
        _report(
            f"{subject.id}: no graph build at {build_path}",
            [
                "hint: poetry run python scripts/build_knowledge_graph.py "
                f"--subject {subject.id} --no-persist"
            ],
        )
        return 1
    _, errors = _load(subject.id, root)
    if errors:
        _report(
            f"{subject.id}: the existing domain is invalid; fix it before drafting "
            f"({len(errors)} error(s))",
            [str(error) for error in errors],
        )
        return 1
    try:
        kg = load_build(build_path)
    except (OSError, ValueError) as e:
        _report(
            f"{subject.id}: cannot read the graph build {build_path}; nothing was written",
            [f"error: {_first_line(e)}"],
        )
        return 1
    files = draft_files(subject, kg, directory)

    # A draft never leaves an invalid domain behind: check the result before writing it
    with tempfile.TemporaryDirectory() as scratch:
        candidate = Path(scratch) / subject.id
        candidate.mkdir()
        for name, text in files.items():
            (candidate / name).write_text(text, encoding="utf-8")
        domain, errors = _load(subject.id, Path(scratch))
    if errors or domain is None:
        _report(
            f"{subject.id}: the draft would be invalid; nothing was written "
            f"({len(errors)} error(s))",
            [
                str(DomainError(directory / e.path.name, e.field, e.message, e.entry))
                for e in errors
            ],
        )
        return 1

    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = directory / name
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        path.write_text(text, encoding="utf-8")
        written.append(name)
    _report(
        f"{subject.id}: drafted {directory} ({_status_summary(domain)})",
        [f"written: {', '.join(written)}" if written else "no file changed"],
    )
    return 0


# --------------------------------------------------------------------------- apply


def cmd_apply(args: argparse.Namespace) -> int:
    subject = _subject(args)
    if subject is None:
        return 1
    root = _root(args)
    domain, errors = _load(subject.id, root)
    if errors:
        _report(
            f"{subject.id}: the domain is invalid; nothing was applied ({len(errors)} error(s))",
            [str(error) for error in errors],
        )
        return 1
    if domain is None:
        _report(f"{subject.id}: no domain directory under {root}; nothing to apply")
        return 0
    if not domain.has_curated_entries:
        _report(
            f"{subject.id}: no approved, rejected or deprecated entries "
            f"({_status_summary(domain)}); nothing to apply"
        )
        return 0

    try:
        adapter = get_neo4j_adapter(subject.id)
    except Exception as e:
        _report(
            f"{subject.id}: Neo4j is not reachable at {settings.neo4j_uri}; nothing was applied",
            [f"error: {type(e).__name__}: {e}", "hint: `make up` starts the databases"],
        )
        return 1

    def announce(operation: Operation) -> None:
        print(f"    {operation.describe()}")

    dry_run = bool(args.dry_run)
    print(f"{subject.id}: {'plan (dry run, nothing is written)' if dry_run else 'applying'}")
    try:
        result = apply_overlay(adapter, domain, dry_run=dry_run, announce=announce)
    except GraphNotBuiltError:
        _report(
            f"{subject.id}: the graph has no concepts; nothing was applied",
            [f"hint: build it first: make build-kg SUBJECT={subject.id} (or `make seed`)"],
        )
        return 1
    except Exception as e:
        _report(
            f"{subject.id}: apply failed; the graph may be partly updated",
            [f"error: {type(e).__name__}: {e}", "hint: run it again, apply is idempotent"],
        )
        return 1
    finally:
        adapter.close()

    for skipped in result.skipped:
        print(f"    skipped {skipped.describe()}")
    removals = len(result.removals)
    verb = "planned" if dry_run else "applied"
    _report(
        f"{subject.id}: {len(result.operations)} operation(s) {verb} "
        f"({removals} removal(s), {len(result.skipped)} skipped)"
    )
    if result.pending:
        _report(
            f"{subject.id}: {len(result.pending)} operation(s) are still pending after apply",
            [operation.describe() for operation in result.pending],
        )
        return 1
    return 0


# --------------------------------------------------------------------------- export


def _provenance_cells(provenance: Provenance) -> dict[str, Any]:
    return {
        f"provenance_{name}": value for name, value in provenance.model_dump(mode="json").items()
    }


def export_rows(domain: Domain) -> dict[str, list[dict[str, Any]]]:
    """The domain as flat rows per table; each row has exactly the table's columns."""
    terms = [
        {
            "subject_id": domain.subject_id,
            **term.model_dump(mode="json", exclude={"provenance"}),
            **_provenance_cells(term.provenance),
        }
        for term in domain.terms
    ]
    relationships = [
        {
            "subject_id": domain.subject_id,
            **relationship.model_dump(mode="json", exclude={"provenance"}),
            **_provenance_cells(relationship.provenance),
        }
        for relationship in domain.relationships
    ]
    sources = [
        {"subject_id": domain.subject_id, **source.model_dump(mode="json")}
        for source in domain.sources
    ]
    tables = {"terms": terms, "relationships": relationships, "sources": sources}
    return {
        table: [{column: row[column] for column in TABLE_COLUMNS[table]} for row in rows]
        for table, rows in tables.items()
    }


def export_csv(domain: Domain, table: str) -> str:
    """One table as CSV; a list cell joins its values with ``LIST_SEPARATOR``."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TABLE_COLUMNS[table], lineterminator="\n")
    writer.writeheader()
    for row in export_rows(domain)[table]:
        writer.writerow(
            {
                column: LIST_SEPARATOR.join(value) if isinstance(value, list) else value
                for column, value in row.items()
            }
        )
    return buffer.getvalue()


def export_json(domain: Domain, table: str | None = None) -> str:
    """All tables (or one) as JSON, with the subject and the schema version."""
    rows = export_rows(domain)
    document: dict[str, Any] = {
        "subject_id": domain.subject_id,
        "schema_version": SCHEMA_VERSION,
        **({table: rows[table]} if table else rows),
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def cmd_export(args: argparse.Namespace) -> int:
    subject = _subject(args)
    if subject is None:
        return 1
    root = _root(args)
    domain, errors = _load(subject.id, root)
    if errors:
        _report(
            f"{subject.id}: the domain is invalid; nothing was exported ({len(errors)} error(s))",
            [str(error) for error in errors],
        )
        return 1
    if domain is None:
        _report(f"{subject.id}: no domain directory under {root}; nothing to export")
        return 1
    if args.format == "csv":
        text = export_csv(domain, args.table or "terms")
    else:
        text = export_json(domain, args.table)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        _report(f"{subject.id}: wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate, draft, apply and export domain artifacts (data/domains/)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, summary: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=summary)
        command.add_argument("--root", help="directory of the domains (default: data/domains)")
        return command

    validate = add("validate", "check every domain; exit 1 naming the file and the field")
    validate.add_argument(
        "--subject", action="append", help="subject to check (repeatable; default: every domain)"
    )
    validate.add_argument("--build", help="graph build JSON to compare with (one subject)")
    validate.set_defaults(func=cmd_validate)

    draft = add("draft", "write the last graph build as extracted entries")
    draft.add_argument("--subject", help="subject id (default: the default subject)")
    draft.add_argument("--build", help="graph build JSON (default: data/processed/build/)")
    draft.set_defaults(func=cmd_draft)

    apply = add("apply", "apply the curated entries to the subject's graph in Neo4j")
    apply.add_argument("--subject", help="subject id (default: the default subject)")
    apply.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    apply.set_defaults(func=cmd_apply)

    export = add("export", "print the domain as flat CSV or JSON")
    export.add_argument("--subject", help="subject id (default: the default subject)")
    export.add_argument("--format", choices=("csv", "json"), default="csv")
    export.add_argument(
        "--table",
        choices=tuple(TABLE_COLUMNS),
        help="table to export (CSV default: terms; JSON default: all)",
    )
    export.add_argument("--out", help="file to write (default: standard output)")
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
