"""
Domain artifacts (#211): the loader.

- A valid domain loads with typed entries; a subject without a directory has none.
- Each class of invalid file fails naming the file and the field.

The committed domains are validated in test_domains.py. Domains are written under tmp_path;
nothing connects to Neo4j.
"""

import copy

import pytest

from backend.app.domain.loader import (
    DomainValidationError,
    domain_directories,
    load_domain,
    unresolved_shared_aliases,
)
from backend.app.domain.models import SCHEMA_VERSION, ReviewStatus
from backend.tests.domain_builders import (
    SOURCE_ID,
    SUBJECT,
    documents,
    make_domain,
    relationship,
    source,
    term,
    write_domain,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Loader: valid input
# ---------------------------------------------------------------------------


def test_a_subject_without_a_directory_has_no_domain(tmp_path):
    assert load_domain("biology", tmp_path) is None
    assert load_domain("biology", tmp_path / "missing-root") is None
    assert domain_directories(tmp_path / "missing-root") == []


@pytest.mark.parametrize("subject_id", ["../etc", "a/b", "", ".hidden"])
def test_subject_id_must_be_a_plain_directory_name(tmp_path, subject_id):
    with pytest.raises(ValueError, match="invalid subject id"):
        load_domain(subject_id, tmp_path)


def test_hidden_directories_and_files_are_not_domains(tmp_path):
    write_domain(tmp_path)
    (tmp_path / ".ipynb_checkpoints").mkdir()
    (tmp_path / "notes.txt").write_text("not a directory", encoding="utf-8")

    assert [path.name for path in domain_directories(tmp_path)] == [SUBJECT]


def test_a_valid_domain_loads_with_typed_entries(tmp_path):
    directory = write_domain(tmp_path)

    domain = load_domain(SUBJECT, tmp_path)

    assert domain is not None
    assert domain.directory == directory
    assert [t.name for t in domain.terms] == ["Tariff", "Trade", "Quota"]
    assert domain.terms[0].review_status is ReviewStatus.EXTRACTED
    assert domain.terms[0].definition_source == SOURCE_ID
    assert domain.relationships[0].type.value == "PREREQ"
    assert domain.status_counts() == {"extracted": 4}
    assert SCHEMA_VERSION == 1


def test_reviewed_dates_load_from_yaml_dates_and_strings(tmp_path):
    files = documents([term("Tariff", "approved"), term("Trade", "rejected")], [])
    directory = write_domain(tmp_path, files)
    text = (directory / "dictionary.yaml").read_text(encoding="utf-8")
    (directory / "dictionary.yaml").write_text(
        text.replace("'2026-11-11'", "2026-11-11", 1), encoding="utf-8"
    )

    domain = load_domain(SUBJECT, tmp_path)

    assert domain is not None
    assert {str(t.provenance.reviewed_on) for t in domain.terms} == {"2026-11-11"}


# ---------------------------------------------------------------------------
# Loader: one failing case per error class; each names the file and the field
# ---------------------------------------------------------------------------


def _approved_pair(**second_fields):
    return [
        term("Aggregate Demand", "approved", aliases=["AD"], context_terms=["spending"]),
        term("Aggregate Demand Curve", "approved", aliases=["AD"], **second_fields),
    ]


# (case id, file with the error, field, message fragment, the four files)
INVALID = [
    (
        "dangling definition_source",
        "dictionary.yaml",
        "terms[0].definition_source (term 'tariff')",
        "'no-such-book' is not a source id in sources.yaml",
        documents([term("Tariff", definition="a tax", definition_source="no-such-book")], []),
    ),
    (
        "definition_source without a definition",
        "dictionary.yaml",
        "terms[0].definition_source (term 'tariff')",
        "set without a definition",
        documents([term("Tariff", definition_source=SOURCE_ID)], []),
    ),
    (
        "unknown review_status",
        "dictionary.yaml",
        "terms[1].review_status (term 'trade')",
        "'extracted', 'proposed', 'approved', 'rejected' or 'deprecated' (got 'accepted')",
        documents([term("Tariff"), term("Trade", review_status="accepted")], []),
    ),
    (
        "unknown relationship review_status",
        "relationships.yaml",
        "relationships[0].review_status (relationship 'Trade' -> 'Tariff')",
        "(got 'done')",
        documents(None, [relationship("Trade", "Tariff", review_status="done")]),
    ),
    (
        "unknown source review_status",
        "sources.yaml",
        "sources[0].review_status (source 'demo-book')",
        "'approved', 'superseded' or 'retired' (got 'extracted')",
        documents(sources=[source(review_status="extracted")]),
    ),
    (
        "duplicate alias across terms without context_terms",
        "dictionary.yaml",
        "terms[1].aliases[0] (term 'aggregate-demand-curve')",
        "alias 'AD' is also an alias or the name of ['aggregate-demand']; add context_terms",
        documents(_approved_pair(), []),
    ),
    (
        "duplicate alias with an unreviewed term",
        "dictionary.yaml",
        "terms[0].aliases[0] (term 'aggregate-demand')",
        "alias 'AD' is also an alias or the name of ['aggregate-demand-curve']",
        documents(
            [
                term("Aggregate Demand", "proposed", aliases=["AD"]),
                term("Aggregate Demand Curve", aliases=["ad"]),
            ],
            [],
        ),
    ),
    (
        "alias that is another term's name",
        "dictionary.yaml",
        "terms[0].aliases[1] (term 'tariff')",
        "alias 'Quotas' is also an alias or the name of ['quota']",
        documents([term("Tariff", "approved", aliases=["Duty", "Quotas"]), term("Quota")], []),
    ),
    (
        "duplicate alias within a term",
        "dictionary.yaml",
        "terms[0].aliases[1] (term 'tariff')",
        "duplicate alias 'Duty'",
        documents([term("Tariff", aliases=["Duty", "Duty"])], []),
    ),
    (
        "duplicate term id",
        "dictionary.yaml",
        "terms[1].id (term 'tariff')",
        "duplicate term id",
        documents([term("Tariff"), term("Trade", id="tariff")], []),
    ),
    (
        "duplicate term name",
        "dictionary.yaml",
        "terms[1].name (term 'tariff-2')",
        "duplicate term name 'Tariff'",
        documents([term("Tariff"), term("Tariff", id="tariff-2")], []),
    ),
    (
        "names that differ only by case or plural",
        "dictionary.yaml",
        "terms[1].name (term 'tariffs')",
        "'tariffs' differs from the name of term 'tariff' only by case",
        documents([term("Tariff"), term("tariffs")], []),
    ),
    (
        "id that is not a slug",
        "dictionary.yaml",
        "terms[0].id (term 'Stamp Act')",
        "string should match pattern",
        documents([term("Stamp Act", id="Stamp Act")], []),
    ),
    (
        "name with surrounding whitespace",
        "dictionary.yaml",
        "terms[0].name (term 'tariff')",
        "must not be empty or start or end with whitespace",
        documents([{**term("Tariff"), "name": " Tariff"}], []),
    ),
    (
        "unknown field",
        "dictionary.yaml",
        "terms[0].defintion (term 'tariff')",
        "unknown field",
        documents([term("Tariff", defintion="a tax")], []),
    ),
    (
        "missing required field",
        "dictionary.yaml",
        "terms[0].provenance.origin (term 'tariff')",
        "the field is required",
        documents([term("Tariff", provenance={"method": "key_term"})], []),
    ),
    (
        "approved term without a review record",
        "dictionary.yaml",
        "terms[0].provenance.reviewed_on (term 'tariff')",
        "required when review_status is approved",
        documents(
            [
                term(
                    "Tariff",
                    "approved",
                    provenance={"origin": "reviewer", "reviewed_by": "project maintainer"},
                )
            ],
            [],
        ),
    ),
    (
        "rejected term without a reviewer",
        "dictionary.yaml",
        "terms[0].provenance.reviewed_by (term 'tariff')",
        "required when review_status is rejected",
        documents([term("Tariff", "rejected", provenance={"origin": "builder"})], []),
    ),
    (
        "reviewer given as an e-mail address",
        "dictionary.yaml",
        "terms[0].provenance.reviewed_by (term 'tariff')",
        "name a role",
        documents(
            [
                term(
                    "Tariff",
                    "approved",
                    provenance={
                        "origin": "reviewer",
                        "reviewed_by": "someone@example.org",
                        "reviewed_on": "2026-11-11",
                    },
                )
            ],
            [],
        ),
    ),
    (
        "relationship endpoint that is not a term",
        "relationships.yaml",
        "relationships[0].source (relationship 'Embargo' -> 'Tariff')",
        "'Embargo' is not a term name in dictionary.yaml",
        documents(None, [relationship("Embargo", "Tariff")]),
    ),
    (
        "relationship target that is not a term",
        "relationships.yaml",
        "relationships[0].target (relationship 'Trade' -> 'tariff')",
        "'tariff' is not a term name in dictionary.yaml",
        documents(None, [relationship("Trade", "tariff")]),
    ),
    (
        "relationship type outside RelationshipType",
        "relationships.yaml",
        "relationships[0].type (relationship 'Trade' -> 'Tariff')",
        "(got 'CAUSES')",
        documents(None, [relationship("Trade", "Tariff", kind="CAUSES")]),
    ),
    (
        "relationship type that does not link two terms",
        "relationships.yaml",
        "relationships[0].type (relationship 'Trade' -> 'Tariff')",
        "COVERS does not link two terms; use one of PREREQ, RELATED",
        documents(None, [relationship("Trade", "Tariff", kind="COVERS")]),
    ),
    (
        "relationship from a term to itself",
        "relationships.yaml",
        "relationships[0].target (relationship 'Trade' -> 'Trade')",
        "a term cannot be related to itself",
        documents(None, [relationship("Trade", "Trade")]),
    ),
    (
        "duplicate relationship",
        "relationships.yaml",
        "relationships[1].type (relationship 'Trade' -> 'Tariff')",
        "duplicate relationship",
        documents(None, [relationship("Trade", "Tariff"), relationship("Trade", "Tariff")]),
    ),
    (
        "dangling evidence_source",
        "relationships.yaml",
        "relationships[0].evidence_source (relationship 'Trade' -> 'Tariff')",
        "'old-book' is not a source id in sources.yaml",
        documents(None, [relationship("Trade", "Tariff", evidence_source="old-book")]),
    ),
    (
        "confidence out of range",
        "relationships.yaml",
        "relationships[0].confidence (relationship 'Trade' -> 'Tariff')",
        "input should be less than or equal to 1 (got 1.5)",
        documents(None, [relationship("Trade", "Tariff", confidence=1.5)]),
    ),
    (
        "approved relationship without a review record",
        "relationships.yaml",
        "relationships[0].provenance.reviewed_by (relationship 'Trade' -> 'Tariff')",
        "required when review_status is approved",
        documents(
            None, [relationship("Trade", "Tariff", "approved", provenance={"origin": "builder"})]
        ),
    ),
    (
        "approved relationship that uses a rejected term",
        "relationships.yaml",
        "relationships[0].source (relationship 'Trade' -> 'Tariff')",
        "an approved relationship cannot use the rejected term 'Trade'",
        documents(
            [term("Tariff"), term("Trade", "rejected")],
            [relationship("Trade", "Tariff", "approved")],
        ),
    ),
    (
        "cycle of approved PREREQ relationships",
        "relationships.yaml",
        "relationships[2].target (relationship 'Quota' -> 'Trade')",
        "closes a cycle of approved PREREQ relationships",
        documents(
            None,
            [
                relationship("Trade", "Tariff", "approved"),
                relationship("Tariff", "Quota", "approved"),
                relationship("Quota", "Trade", "approved"),
            ],
        ),
    ),
    (
        "duplicate source id",
        "sources.yaml",
        "sources[1].id (source 'demo-book')",
        "duplicate source id",
        documents(sources=[source(), source()]),
    ),
    (
        "source without a uri or a path",
        "sources.yaml",
        "sources[0].uri (source 'demo-book')",
        "a source needs a uri or a path",
        documents(sources=[source(uri=None)]),
    ),
    (
        "supersedes an unknown source",
        "sources.yaml",
        "sources[0].supersedes (source 'demo-book')",
        "'first-edition' is not a source id in this file",
        documents(sources=[source(supersedes="first-edition")]),
    ),
    (
        "source that supersedes itself",
        "sources.yaml",
        "sources[0].supersedes (source 'demo-book')",
        "a source cannot supersede itself",
        documents(sources=[source(supersedes=SOURCE_ID)]),
    ),
    (
        "source steward given as an e-mail address",
        "sources.yaml",
        "sources[0].steward (source 'demo-book')",
        "name a role",
        documents(sources=[source(steward="owner@example.org")]),
    ),
    (
        "unsupported schema_version",
        "dictionary.yaml",
        "schema_version",
        "input should be 1 (got 2)",
        {**documents(), "dictionary.yaml": {"schema_version": 2, "terms": []}},
    ),
    (
        "missing schema_version",
        "sources.yaml",
        "schema_version",
        "the field is required",
        {**documents(), "sources.yaml": {"sources": [source()]}},
    ),
    (
        "subject_id that is not the directory name",
        "domain.yaml",
        "subject_id",
        "'economics' does not match the directory name 'us_history'",
        {**documents(), "domain.yaml": documents(subject_id="economics")["domain.yaml"]},
    ),
    (
        "unknown domain status",
        "domain.yaml",
        "status",
        "'draft', 'approved' or 'retired' (got 'final')",
        {**documents(), "domain.yaml": {**documents()["domain.yaml"], "status": "final"}},
    ),
    (
        "approved domain without a review cadence",
        "domain.yaml",
        "review_cadence",
        "an approved domain must state it",
        {
            **documents(),
            "domain.yaml": {
                **documents()["domain.yaml"],
                "status": "approved",
                "accuracy_bar": "definitions are quoted from the source glossary",
            },
        },
    ),
]


@pytest.mark.parametrize(
    ("file_name", "field", "fragment", "files"),
    [pytest.param(*case[1:], id=case[0]) for case in INVALID],
)
def test_invalid_domain_names_the_path_and_the_field(tmp_path, file_name, field, fragment, files):
    directory = write_domain(tmp_path, copy.deepcopy(files))

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    messages = [str(error) for error in raised.value.errors]
    prefix = f"{directory / file_name}: {field}: "
    matching = [message for message in messages if message.startswith(prefix)]
    assert matching, messages
    assert fragment in matching[0]
    # Every error of the run names an existing file, whatever the class
    assert all(error.path.parent == directory and error.field for error in raised.value.errors)
    assert str(raised.value) == "\n".join(messages)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_must_be_an_integer(tmp_path, version):
    """YAML `true`, `1.0` and `"1"` are not the version 1, although Python equates the first two."""
    files = documents()
    files["sources.yaml"]["schema_version"] = version
    directory = write_domain(tmp_path, files)

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    assert str(raised.value) == (
        f"{directory / 'sources.yaml'}: schema_version: must be an integer (got {version!r})"
    )


def test_names_without_latin_letters_or_digits_are_only_compared_exactly(tmp_path):
    """Such a name has no comparison key, so two of them are not near-duplicates."""
    terms = [term("生物学", id="biology"), term("化学", id="chemistry"), term("...", id="dots")]

    domain = make_domain(tmp_path, terms, [])

    assert [t.name for t in domain.terms] == ["生物学", "化学", "..."]
    write_domain(tmp_path, documents([terms[0], term("生物学", id="biology-2")], []))
    with pytest.raises(DomainValidationError, match="terms\\[1\\].name .*duplicate term name"):
        load_domain(SUBJECT, tmp_path)


def test_a_schema_error_stops_the_run_before_the_cross_file_checks(tmp_path):
    """Two passes: the cross-file checks need all four files, so they wait for a valid schema."""
    files = documents(
        [term("Tariff", definition="a tax", definition_source="gone"), term("Trade", colour="red")],
        [],
    )
    write_domain(tmp_path, files)

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    assert [error.field for error in raised.value.errors] == ["terms[1].colour"]


def test_missing_file_is_named(tmp_path):
    directory = write_domain(tmp_path)
    (directory / "relationships.yaml").unlink()

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    assert [str(e) for e in raised.value.errors] == [
        f"{directory / 'relationships.yaml'}: <file>: the file is missing"
    ]


def test_invalid_yaml_is_named_with_its_position(tmp_path):
    directory = write_domain(tmp_path)
    (directory / "dictionary.yaml").write_text("terms:\n  - id: [unclosed\n", encoding="utf-8")

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    (error,) = raised.value.errors
    assert str(error).startswith(f"{directory / 'dictionary.yaml'}: <document>: not valid YAML")
    assert "line" in error.message and "\n" not in error.message


@pytest.mark.parametrize("text", ["- just\n- a list\n", "", "plain text\n"])
def test_a_file_must_hold_a_mapping(tmp_path, text):
    directory = write_domain(tmp_path)
    (directory / "sources.yaml").write_text(text, encoding="utf-8")

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    assert str(raised.value) == (
        f"{directory / 'sources.yaml'}: <document>: expected a mapping at the top level"
    )


def test_unreadable_file_is_named(tmp_path):
    directory = write_domain(tmp_path)
    (directory / "domain.yaml").write_bytes(b"\xff\xfe\x00not utf-8")

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    assert str(raised.value).startswith(f"{directory / 'domain.yaml'}: <file>: cannot be read")


def test_every_problem_is_reported_at_once(tmp_path):
    files = documents(
        [
            term("Tariff", definition="a tax", definition_source="gone"),
            term("Trade", id="tariff"),
        ],
        [relationship("Embargo", "Tariff", evidence_source="gone")],
    )
    write_domain(tmp_path, files)

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    fields = sorted(error.field for error in raised.value.errors)
    assert fields == [
        "relationships[0].evidence_source",
        "relationships[0].source",
        "terms[0].definition_source",
        "terms[1].id",
    ]


def test_errors_name_the_entry_only_when_it_can_be_identified(tmp_path):
    files = documents(
        [
            "not a mapping",
            {"review_status": "extracted"},
            term("Tariff", definition="x" * 200 + " "),
        ],
        [{"type": "PREREQ"}],
    )
    directory = write_domain(tmp_path, files)

    with pytest.raises(DomainValidationError) as raised:
        load_domain(SUBJECT, tmp_path)

    by_field = {(error.path.name, error.field): error for error in raised.value.errors}
    assert by_field[("dictionary.yaml", "terms[0]")].entry is None
    assert by_field[("dictionary.yaml", "terms[1].id")].entry is None
    assert by_field[("relationships.yaml", "relationships[0].source")].entry is None
    truncated = by_field[("dictionary.yaml", "terms[2].definition")]
    assert truncated.entry == "term 'tariff'"
    assert truncated.message.endswith("xxx...)") and len(truncated.message) < 160
    assert str(by_field[("dictionary.yaml", "terms[0]")]).startswith(
        f"{directory / 'dictionary.yaml'}: terms[0]: "
    )


def test_a_term_may_be_named_what_an_unreviewed_term_uses_as_an_alias(tmp_path):
    """Only the term that holds the shared word as an alias has to tell the senses apart."""
    terms = [term("Quota", "approved"), term("Tariff", aliases=["Quotas"])]

    domain = make_domain(tmp_path, terms, [])

    assert unresolved_shared_aliases(domain) == {"quota": ["Quota", "Tariff"]}


def test_shared_alias_is_valid_once_the_senses_have_context_terms(tmp_path):
    terms = _approved_pair(context_terms=["curve", "price level"], scope="AD/AS model")

    domain = make_domain(tmp_path, terms, [])

    assert [t.context_terms for t in domain.terms] == [["spending"], ["curve", "price level"]]
    assert unresolved_shared_aliases(domain) == {}


def test_shared_alias_between_extracted_terms_is_reported_not_refused(tmp_path):
    """The builder gives "AD" to two Economics concepts; a draft must still validate."""
    terms = [
        term("Aggregate Demand", aliases=["AD"]),
        term("Aggregate Demand Curve", aliases=["AD", "Aggregate Demand Curves"]),
        term("Trade", "rejected", aliases=["AD"]),  # leaves the graph, so it shares nothing
    ]

    domain = make_domain(tmp_path, terms, [])

    assert unresolved_shared_aliases(domain) == {
        "ad": ["Aggregate Demand", "Aggregate Demand Curve"]
    }
