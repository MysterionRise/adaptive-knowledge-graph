"""
scripts/domain_tool.py (#211): validate and draft.

Every domain is written under tmp_path and every graph build is a small JSON file there;
nothing connects to Neo4j. `export` is tested in test_domain_export.py, `apply` and the
scripts that call the tool in test_domain_apply.py.
"""

from pathlib import Path

import pytest
import yaml

from backend.app.core.subjects import get_subject
from backend.app.kg.schema import ConceptNode, KnowledgeGraph, Relationship, RelationshipType
from backend.tests.domain_builders import (
    REVIEWED,
    SOURCE_ID,
    SUBJECT,
    documents,
    term,
    write_domain,
)
from scripts import domain_tool

pytestmark = pytest.mark.unit

BOOK_ID = "us-history"  # the configured book of the subject the tests draft for


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No Neo4j adapter, and no graph build of the checkout: tests pass their own with --build."""
    monkeypatch.setattr(
        domain_tool, "get_neo4j_adapter", lambda subject_id: pytest.fail("connected to Neo4j")
    )
    monkeypatch.setattr(domain_tool.settings, "data_processed_dir", str(tmp_path / "processed"))


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = domain_tool.main(list(argv))
    return code, capsys.readouterr().out


def _concept(name: str, definition: str | None = None, **fields) -> ConceptNode:
    return ConceptNode(name=name, definition=definition, key_term=definition is not None, **fields)


def _prereq(prerequisite: str, dependent: str, **provenance: str) -> Relationship:
    return Relationship(
        source=prerequisite,
        target=dependent,
        type=RelationshipType.PREREQ,
        weight=0.8,
        confidence=0.8,
        evidence=f"{dependent}: its glossary definition",
        provenance=provenance or {"source": "glossary", "module_id": "m2"},
    )


def _build(path: Path, concepts: list[ConceptNode], relationships: list[Relationship]) -> Path:
    """A graph build as build_knowledge_graph.py leaves it, in the order given."""
    kg = KnowledgeGraph()
    for concept in concepts:
        kg.concepts[concept.name] = concept
    kg.relationships = list(relationships)
    path.write_text(kg.model_dump_json(indent=2), encoding="utf-8")
    return path


CONCEPTS = [
    _concept("Trade", source_modules=["m3", "m1"]),
    _concept(
        "Tariff",
        "a tax on imported goods",
        aliases=["Tariffs", "TARIFF"],
        source_modules=["m2"],
    ),
    _concept("Quota", " a limit on imports ", source_modules=["m4"]),
    _concept("Aggregate Demand", aliases=["AD"]),
]
RELATIONSHIPS = [
    _prereq("Trade", "Tariff"),
    _prereq("Tariff", "Quota", source="cue_phrase", pattern="led_to", module_id="m4"),
    Relationship(source="Quota", target="Trade", type=RelationshipType.RELATED, weight=0.4),
    Relationship(source="m2", target="Tariff", type=RelationshipType.COVERS),
]


@pytest.fixture
def build(tmp_path):
    return _build(tmp_path / "build.json", CONCEPTS, RELATIONSHIPS)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "domains"
    path.mkdir()
    return path


def _draft(capsys, root: Path, build: Path, subject: str = SUBJECT) -> tuple[int, str]:
    return _run(capsys, "draft", "--subject", subject, "--root", str(root), "--build", str(build))


def _read(root: Path, name: str, subject: str = SUBJECT) -> dict:
    return yaml.safe_load((root / subject / name).read_text(encoding="utf-8"))


def _texts(root: Path, subject: str = SUBJECT) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in (root / subject).iterdir()}


def _edit(root: Path, name: str, change, subject: str = SUBJECT) -> None:
    path = root / subject / name
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_passes_on_every_committed_domain(capsys):
    code, out = _run(capsys, "validate")

    assert code == 0, out
    for subject_id in ("economics", "us_history"):
        assert f"{subject_id}: valid (" in out
    assert "INVALID" not in out
    assert out.count("report: no graph build at ") == out.count(": valid (")


def test_validate_exits_1_naming_the_path_and_the_field(capsys, root):
    files = documents([term("Tariff", definition="a tax", definition_source="gone")], [])
    directory = write_domain(root, files)

    code, out = _run(capsys, "validate", "--root", str(root))

    assert code == 1
    assert "us_history: INVALID (1 error(s))" in out
    assert (
        f"    {directory / 'dictionary.yaml'}: terms[0].definition_source (term 'tariff'): "
        "'gone' is not a source id in sources.yaml"
    ) in out


def test_validate_checks_every_directory_and_fails_if_one_is_invalid(capsys, root):
    write_domain(root, documents(subject_id="economics"), subject_id="economics")
    write_domain(root, documents([term("Tariff"), term("Tariff", id="tariff-2")], []))

    code, out = _run(capsys, "validate", "--root", str(root))

    assert code == 1
    assert "economics: valid (3 terms, 1 relationships, 1 sources; entries: 4 extracted)" in out
    assert "us_history: INVALID" in out and "duplicate term name 'Tariff'" in out


def test_validate_refuses_a_directory_without_a_configured_subject(capsys, root):
    write_domain(root, documents(subject_id="astronomy"), subject_id="astronomy")

    code, out = _run(capsys, "validate", "--root", str(root))

    assert code == 1
    assert (
        f"{root / 'astronomy'}: <directory>: no subject with this id in config/subjects.yaml" in out
    )


def test_validate_names_a_directory_that_is_not_a_subject_id(capsys, root):
    """A stray directory is an error with a path and a field, never a traceback."""
    write_domain(root)
    (root / "__pycache__").mkdir()
    (root / ".ipynb_checkpoints").mkdir()  # hidden: a tool's cache, not a domain

    code, out = _run(capsys, "validate", "--root", str(root))

    assert code == 1
    assert "us_history: valid (" in out and ".ipynb_checkpoints" not in out
    assert "__pycache__: INVALID (1 error(s))" in out
    assert f"    {root / '__pycache__'}: <directory>: the name is not a subject id" in out

    code, out = _run(capsys, "validate", "--root", str(root), "--subject", ".cache")

    assert code == 1
    assert out.splitlines() == [
        ".cache: INVALID (1 error(s))",
        f"    {root / '.cache'}: <directory>: the name is not a subject id "
        "(letters, digits, '_' and '-')",
    ]


def test_validate_without_domains_or_for_a_subject_without_one(capsys, root):
    assert _run(capsys, "validate", "--root", str(root)) == (
        0,
        f"No domain directories under {root}\n",
    )
    code, out = _run(capsys, "validate", "--root", str(root), "--subject", "biology")
    assert code == 0
    assert out == f"biology: no domain directory under {root} (no curated domain)\n"


def test_validate_reports_how_dictionary_and_build_differ(capsys, root, tmp_path):
    terms = [
        term("Tariff"),
        term("Quota", "proposed"),
        term("Embargo", "approved"),
        term("Summary", "rejected"),
        term("Mercantilism", "deprecated"),
    ]
    write_domain(root, documents(terms, []))
    build = _build(
        tmp_path / "build.json",
        [_concept("Tariff"), _concept("Summary"), _concept("Subsidy"), _concept("Trade")],
        [],
    )

    code, out = _run(capsys, "validate", "--root", str(root), "--build", str(build))

    assert code == 0  # a report, not an error
    assert f"report: 2 dictionary name(s) missing from the build ({build}): Embargo, Quota" in out
    assert (
        "report: 2 build concept(s) missing from the dictionary (run draft): Subsidy, Trade" in out
    )


def test_validate_reports_a_removed_concept_the_build_spells_differently(capsys, root, tmp_path):
    """apply removes by exact name, so a respelt noise concept would come back unnoticed."""
    terms = [term("Summary", "rejected"), term("Key Terms", "deprecated"), term("Tariff")]
    write_domain(root, documents(terms, []))
    build = _build(
        tmp_path / "build.json",
        [_concept("summary"), _concept("Key Term"), _concept("Tariff"), _concept("Summary")],
        [],
    )

    code, out = _run(capsys, "validate", "--root", str(root), "--build", str(build))

    assert code == 0
    assert (
        "report: 2 build concept(s) differ from a rejected or deprecated term only by case, an "
        "article or a plural, so apply does not remove them: "
        "'Key Term' (term 'Key Terms'), 'summary' (term 'Summary')"
    ) in out


def test_validate_says_when_dictionary_and_build_agree_or_no_build_exists(
    capsys, root, build, tmp_path
):
    assert _draft(capsys, root, build)[0] == 0

    _, compared = _run(capsys, "validate", "--root", str(root), "--build", str(build))
    _, missing = _run(
        capsys, "validate", "--root", str(root), "--build", str(tmp_path / "none.json")
    )
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    code, broken = _run(
        capsys, "validate", "--root", str(root), "--build", str(tmp_path / "broken.json")
    )

    assert f"report: the dictionary names every concept of the build ({build})" in compared
    assert f"report: no graph build at {tmp_path / 'none.json'}" in missing
    assert code == 0 and "report: cannot read the graph build" in broken


def test_validate_reports_inventory_and_alias_notices(capsys, root):
    terms = [
        term("Aggregate Demand", aliases=["AD"]),
        term("Aggregate Demand Curve", aliases=["AD"]),
    ]
    write_domain(root, documents(terms, []))  # its source id is not the configured book's

    code, out = _run(capsys, "validate", "--root", str(root))

    assert code == 0
    assert (
        "report: 1 alias(es) shared by several terms without context_terms: "
        "'ad' (Aggregate Demand, Aggregate Demand Curve)"
    ) in out
    assert f"report: configured books without an approved source: ['{BOOK_ID}']" in out
    assert f"report: approved sources that are not configured books: ['{SOURCE_ID}']" in out


def test_build_drift_lists_names_in_both_directions(root):
    from backend.app.domain.loader import load_domain

    write_domain(root, documents([term("Tariff"), term("Quota", "rejected")], []))
    domain = load_domain(SUBJECT, root)
    assert domain is not None

    assert domain_tool.build_drift(domain, {"Tariff", "Quota"}) == ([], [])
    assert domain_tool.build_drift(domain, {"Trade"}) == (["Tariff"], ["Trade"])


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


def test_draft_writes_the_build_as_extracted_entries(capsys, root, build):
    code, out = _draft(capsys, root, build)

    assert code == 0, out
    assert "written: domain.yaml, sources.yaml, dictionary.yaml, relationships.yaml" in out
    dictionary = _read(root, "dictionary.yaml")
    assert dictionary["schema_version"] == 1
    by_id = {entry["id"]: entry for entry in dictionary["terms"]}
    assert list(by_id) == ["aggregate-demand", "quota", "tariff", "trade"]
    assert by_id["tariff"] == {
        "id": "tariff",
        "name": "Tariff",
        "aliases": ["TARIFF", "Tariffs"],
        "definition": "a tax on imported goods",
        "definition_source": BOOK_ID,
        "review_status": "extracted",
        "provenance": {"origin": "builder", "method": "key_term", "module_id": "m2"},
    }
    assert by_id["trade"]["definition"] is None and by_id["trade"]["definition_source"] is None
    assert by_id["trade"]["provenance"] == {
        "origin": "builder",
        "method": "keyword",
        "module_id": "m3",
    }
    assert by_id["quota"]["definition"] == "a limit on imports"
    assert by_id["aggregate-demand"]["provenance"] == {"origin": "builder", "method": "keyword"}
    assert {entry["review_status"] for entry in dictionary["terms"]} == {"extracted"}


def test_draft_writes_only_the_prereq_edges(capsys, root, build):
    _draft(capsys, root, build)

    edges = _read(root, "relationships.yaml")["relationships"]

    assert edges == [
        {
            "source": "Tariff",
            "target": "Quota",
            "type": "PREREQ",
            "rule": "cue_phrase:led_to",
            "evidence_source": BOOK_ID,
            "confidence": 0.8,
            "review_status": "extracted",
            "provenance": {"origin": "builder", "method": "cue_phrase", "module_id": "m4"},
        },
        {
            "source": "Trade",
            "target": "Tariff",
            "type": "PREREQ",
            "rule": "glossary_definition",
            "evidence_source": BOOK_ID,
            "confidence": 0.8,
            "review_status": "extracted",
            "provenance": {"origin": "builder", "method": "glossary", "module_id": "m2"},
        },
    ]


def test_draft_writes_the_domain_and_the_inventory_once(capsys, root, build):
    _draft(capsys, root, build)
    subject = get_subject(SUBJECT)

    assert _read(root, "domain.yaml") == {
        "schema_version": 1,
        "subject_id": SUBJECT,
        "status": "draft",
        "steward": "project maintainer",
        "review_cadence": None,
        "accuracy_bar": None,
    }
    assert _read(root, "sources.yaml") == {
        "schema_version": 1,
        "sources": [
            {
                "id": BOOK_ID,
                "title": "US History",
                "connector": "github_raw",
                "uri": subject.books[0].repo_url_raw,
                "license": "CC BY 4.0",
                "steward": "project maintainer",
                "review_status": "approved",
                "supersedes": None,
            }
        ],
    }

    _edit(root, "domain.yaml", lambda document: document.update(review_cadence="every release"))
    _edit(
        root, "sources.yaml", lambda document: document["sources"][0].update(title="US History 2e")
    )
    edited = _texts(root)
    code, out = _draft(capsys, root, build)

    assert code == 0 and "no file changed" in out
    assert _texts(root) == edited


def test_draft_is_byte_identical_on_a_second_run_and_in_any_build_order(
    capsys, root, build, tmp_path
):
    assert _draft(capsys, root, build)[0] == 0
    first = _texts(root)

    code, out = _draft(capsys, root, build)
    assert code == 0 and "no file changed" in out
    assert _texts(root) == first

    shuffled = _build(tmp_path / "shuffled.json", CONCEPTS[::-1], RELATIONSHIPS[::-1])
    other = tmp_path / "other"
    other.mkdir()
    assert _draft(capsys, other, shuffled)[0] == 0
    assert _texts(other) == first
    assert first["dictionary.yaml"].startswith("# Written by scripts/domain_tool.py draft")
    assert not [
        line for text in first.values() for line in text.splitlines() if line != line.rstrip()
    ]


def test_draft_sorts_the_aliases_of_a_term():
    """The aliases pass through a set, which has no order of its own between two runs."""
    aliases = [f"alias {letter}" for letter in "hgfedcba"]
    concept = ConceptNode(name="Tariff", aliases=[*aliases, " alias a ", "Tariff", " "])

    entry = domain_tool._term_entry(concept, "tariff", None)

    assert entry["aliases"] == sorted(aliases)


def test_draft_writes_every_entry_with_sorted_keys(capsys, root, build):
    """Sorted keys keep a diff to the values that changed, however the code builds an entry."""
    _draft(capsys, root, build)

    terms = _read(root, "dictionary.yaml")["terms"]  # a mapping loads in file order
    edges = _read(root, "relationships.yaml")["relationships"]

    assert terms and edges
    for entry in (*terms, *edges):
        assert list(entry) == sorted(entry)
        assert list(entry["provenance"]) == sorted(entry["provenance"])
    text = _texts(root)["dictionary.yaml"]
    assert text.index("schema_version: 1\n") < text.index("terms:\n")


def test_draft_does_not_touch_reviewed_entries(capsys, root, build, tmp_path):
    """Approved, rejected and proposed entries survive a draft with every value unchanged."""
    _draft(capsys, root, build)

    def review_terms(document):
        by_id = {entry["id"]: entry for entry in document["terms"]}
        by_id["tariff"].update(
            review_status="approved",
            definition="a tax a government puts on imported goods",
            aliases=["Duty"],
            provenance={"origin": "builder", "method": "key_term", **REVIEWED},
        )
        by_id["quota"].update(review_status="proposed", provenance={"origin": "reviewer"})
        by_id["trade"].update(id="commerce")  # still extracted: the id is kept by name

    def review_edges(document):
        for entry in document["relationships"]:
            if entry["source"] == "Trade":
                entry.update(review_status="rejected", provenance={"origin": "builder", **REVIEWED})

    _edit(root, "dictionary.yaml", review_terms)
    _edit(root, "relationships.yaml", review_edges)
    reviewed_terms = {entry["id"]: entry for entry in _read(root, "dictionary.yaml")["terms"]}
    reviewed_edges = _read(root, "relationships.yaml")["relationships"]

    # The next build changes Tariff, drops Quota and Aggregate Demand, and adds Subsidy
    rebuilt = _build(
        tmp_path / "rebuilt.json",
        [
            _concept("Trade", "the exchange of goods", source_modules=["m9"]),
            _concept("Tariff", "a builder definition that must not win", aliases=["Tariffs"]),
            _concept("Subsidy"),
        ],
        [_prereq("Trade", "Tariff"), _prereq("Trade", "Subsidy")],
    )
    code, out = _draft(capsys, root, rebuilt)

    assert code == 0, out
    terms = {entry["id"]: entry for entry in _read(root, "dictionary.yaml")["terms"]}
    assert list(terms) == ["commerce", "quota", "subsidy", "tariff"]  # sorted by id
    assert terms["tariff"] == reviewed_terms["tariff"]  # approved: untouched
    assert terms["quota"] == reviewed_terms["quota"]  # proposed: kept without the build
    assert terms["commerce"]["name"] == "Trade"  # extracted: replaced, id kept
    assert terms["commerce"]["definition"] == "the exchange of goods"
    assert terms["commerce"]["provenance"]["module_id"] == "m9"
    assert terms["subsidy"]["review_status"] == "extracted"
    assert "aggregate-demand" not in terms  # extracted and no longer built

    edges = _read(root, "relationships.yaml")["relationships"]
    rejected = [entry for entry in reviewed_edges if entry["review_status"] == "rejected"]
    assert [(e["source"], e["target"], e["review_status"]) for e in edges] == [
        ("Trade", "Subsidy", "extracted"),
        ("Trade", "Tariff", "rejected"),  # not drafted again next to the reviewed entry
    ]
    assert edges[1] == rejected[0]

    again = _texts(root)
    assert _draft(capsys, root, rebuilt)[0] == 0
    assert _texts(root) == again


def test_draft_keeps_the_values_of_a_reviewed_entry_not_its_formatting(capsys, root, build):
    """Both files are re-serialised: a comment, the key order and the quoting are not kept."""
    _draft(capsys, root, build)
    (root / SUBJECT / "relationships.yaml").write_text(
        "schema_version: 1\nrelationships: []\n", encoding="utf-8"
    )
    path = root / SUBJECT / "dictionary.yaml"
    path.write_text(
        "schema_version: 1\n"
        "terms:\n"
        "  # checked against the glossary of chapter 3\n"
        '  - name: "Tariff"\n'
        "    id: tariff\n"
        "    review_status: approved\n"
        "    definition: >-\n"
        "      a tax a government puts\n"
        "      on imported goods\n"
        f"    definition_source: {BOOK_ID}\n"
        "    aliases: [Duty]\n"
        "    provenance: {origin: builder, reviewed_by: project maintainer,\n"
        "                 reviewed_on: 2026-11-11, note: checked}\n",
        encoding="utf-8",
    )
    (reviewed,) = _read(root, "dictionary.yaml")["terms"]
    assert reviewed["definition"] == "a tax a government puts on imported goods"

    code, out = _draft(capsys, root, build)

    assert code == 0, out
    by_id = {entry["id"]: entry for entry in _read(root, "dictionary.yaml")["terms"]}
    assert by_id["tariff"] == reviewed  # every value, the date included
    assert list(by_id["tariff"]) == sorted(reviewed)
    text = path.read_text(encoding="utf-8")
    assert "# checked against the glossary" not in text and '"Tariff"' not in text
    assert text.startswith(domain_tool.DRAFT_HEADER)
    assert "comments and formatting are not kept" in domain_tool.DRAFT_HEADER


def test_a_new_name_does_not_take_over_the_id_of_an_extracted_term(capsys, root, tmp_path):
    """A later build adds names with the same slug, one sorting first: no id moves."""
    first = _build(tmp_path / "first.json", [_concept("AD/AS Model"), _concept("Supply Side")], [])
    assert _draft(capsys, root, first)[0] == 0
    assert {entry["name"]: entry["id"] for entry in _read(root, "dictionary.yaml")["terms"]} == {
        "AD/AS Model": "ad-as-model",
        "Supply Side": "supply-side",
    }

    names = ["Supply-Side", "AD-AS Model", "AD/AS Model", "Supply Side"]
    second = _build(tmp_path / "second.json", [_concept(name) for name in names], [])
    code, out = _draft(capsys, root, second)

    assert code == 0, out
    assert "AD-AS Model" < "AD/AS Model"  # the new name is visited first
    assert {entry["name"]: entry["id"] for entry in _read(root, "dictionary.yaml")["terms"]} == {
        "AD-AS Model": "ad-as-model-2",
        "AD/AS Model": "ad-as-model",
        "Supply Side": "supply-side",
        "Supply-Side": "supply-side-2",
    }
    again = _texts(root)
    assert _draft(capsys, root, second)[0] == 0 and _texts(root) == again


def test_draft_ids_do_not_collide(tmp_path):
    kg = KnowledgeGraph()
    for name in ("A&B", "A B", "M1"):
        kg.concepts[name] = _concept(name)
    reviewed = term("Embargo", "approved", id="m1")

    terms = domain_tool.draft_terms(kg, [reviewed], None)

    assert [(entry["id"], entry["name"]) for entry in terms] == [
        ("a-b", "A B"),
        ("a-b-2", "A&B"),
        ("m1", "Embargo"),
        ("m1-2", "M1"),
    ]
    assert domain_tool.unique_id("???", set()) == "term"
    long_id = domain_tool.unique_id("Very Long Name " * 20, set())
    assert len(long_id) <= 72 and not long_id.endswith("-")


def test_draft_needs_a_graph_build(capsys, root, tmp_path):
    code, out = _draft(capsys, root, tmp_path / "missing.json")

    assert code == 1
    assert f"us_history: no graph build at {tmp_path / 'missing.json'}" in out
    assert "build_knowledge_graph.py --subject us_history --no-persist" in out
    assert not (root / SUBJECT).exists()


def test_draft_reports_a_graph_build_it_cannot_read(capsys, root, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    code, out = _draft(capsys, root, broken)

    assert code == 1
    lines = out.splitlines()
    assert lines[0] == f"us_history: cannot read the graph build {broken}; nothing was written"
    assert lines[1].startswith("    error: ") and len(lines) == 2
    assert not (root / SUBJECT).exists()


def test_draft_refuses_to_run_over_an_invalid_domain(capsys, root, build):
    write_domain(root, documents([term("Tariff"), term("Trade", id="tariff")], []))
    before = _texts(root)

    code, out = _draft(capsys, root, build)

    assert code == 1
    assert "the existing domain is invalid; fix it before drafting (1 error(s))" in out
    assert "terms[1].id (term 'tariff'): duplicate term id" in out
    assert _texts(root) == before


def test_draft_never_writes_an_invalid_domain(capsys, root, build, tmp_path):
    """A reviewed edge keeps its endpoints: a build without one must not empty the term."""
    _draft(capsys, root, build)

    def approve(document):
        document["relationships"][1].update(
            review_status="approved", provenance={"origin": "builder", **REVIEWED}
        )

    _edit(root, "relationships.yaml", approve)  # Trade -> Tariff
    before = _texts(root)
    without_trade = _build(tmp_path / "smaller.json", [CONCEPTS[1]], [])

    code, out = _draft(capsys, root, without_trade)

    assert code == 1
    assert "the draft would be invalid; nothing was written (1 error(s))" in out
    assert (
        f"{root / SUBJECT / 'relationships.yaml'}: relationships[0].source "
        "(relationship 'Trade' -> 'Tariff'): 'Trade' is not a term name in dictionary.yaml"
    ) in out
    assert _texts(root) == before


def test_draft_leaves_the_source_open_when_the_subject_has_several_books(capsys, root, build):
    code, out = _draft(capsys, root, build, subject="biology")

    assert code == 0, out
    assert [s["id"] for s in _read(root, "sources.yaml", "biology")["sources"]] == [
        "biology-2e",
        "concepts-of-biology",
    ]
    terms = {entry["id"]: entry for entry in _read(root, "dictionary.yaml", "biology")["terms"]}
    assert terms["tariff"]["definition"] and terms["tariff"]["definition_source"] is None
    edges = _read(root, "relationships.yaml", "biology")["relationships"]
    assert {entry["evidence_source"] for entry in edges} == {None}


def test_sources_come_from_the_configured_books():
    world = yaml.safe_load(domain_tool.render_sources(get_subject("world_history")))["sources"]

    assert [(entry["id"], entry["connector"], entry["uri"]) for entry in world] == [
        (
            "world-history-volume-1",
            "openstax_web",
            "https://openstax.org/books/world-history-volume-1",
        ),
        (
            "world-history-volume-2",
            "openstax_web",
            "https://openstax.org/books/world-history-volume-2",
        ),
    ]
    assert {entry["license"] for entry in world} == {"CC BY 4.0"}
    assert domain_tool.source_license("Content from A Book (CC BY-NC-SA 4.0).") == "CC BY-NC-SA 4.0"
    assert domain_tool.source_license(" All rights reserved. ") == "All rights reserved."
