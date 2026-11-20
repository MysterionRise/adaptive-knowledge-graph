"""
Domain artifacts (#211): the committed domains.

- Every directory under data/domains validates. This is the check CI runs on them.
- The committed files plan no write beyond their reviewed entries (none before the first
  review), cite the configured books and name roles, not people.

The loader is tested in test_domain_loader.py, the overlay and the lexicon view in
test_domain_overlay.py, the command line in test_domain_tool.py, test_domain_export.py and
test_domain_apply.py. Nothing here writes under data/ or connects to Neo4j.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from backend.app.core.subjects import get_subject, get_subject_ids
from backend.app.domain.lexicon import DomainLexicon, domain_lexicon
from backend.app.domain.loader import (
    default_domains_root,
    domain_directories,
    load_domain,
    unresolved_shared_aliases,
)
from backend.app.domain.models import CURATED_STATUSES
from backend.app.domain.overlay import GraphState, apply_overlay, plan_overlay
from backend.tests.domain_builders import REVIEWED, fake_adapter

pytestmark = pytest.mark.unit

COMMITTED_ROOT = Path("data/domains")
COMMITTED = [path.name for path in domain_directories(COMMITTED_ROOT)]


# ---------------------------------------------------------------------------
# The committed domains
# ---------------------------------------------------------------------------


def test_the_demo_subjects_have_a_committed_domain():
    assert {"us_history", "economics"} <= set(COMMITTED)
    assert COMMITTED == sorted(COMMITTED)
    assert default_domains_root().resolve() == COMMITTED_ROOT.resolve()


@pytest.mark.parametrize("subject_id", COMMITTED)
def test_committed_domains_validate(subject_id):
    assert subject_id in get_subject_ids(), "a domain directory needs a configured subject"

    domain = load_domain(subject_id, COMMITTED_ROOT)

    assert domain is not None
    assert domain.subject_id == domain.meta.subject_id == subject_id
    assert domain.terms and domain.sources


@pytest.mark.parametrize("subject_id", COMMITTED)
def test_committed_domains_change_only_what_was_reviewed(subject_id):
    """
    The seed applies these files. Until someone reviews an entry the plan is empty and the
    lexicon adds nothing; from then on every operation names a reviewed term or edge.
    """
    domain = load_domain(subject_id, COMMITTED_ROOT)
    assert domain is not None
    builder_state = GraphState(
        concepts={t.name: {"aliases": list(t.aliases)} for t in domain.terms},
        prereq_edges={(r.source, r.target): {} for r in domain.relationships},
    )
    reviewed_terms = {t.name for t in domain.terms if t.review_status in CURATED_STATUSES}
    reviewed_edges = {
        (r.source, r.target) for r in domain.relationships if r.review_status in CURATED_STATUSES
    }

    plan = plan_overlay(domain, builder_state)

    for operation in plan:
        if operation.target is None:
            assert operation.name in reviewed_terms
        else:
            assert (operation.name, operation.target) in reviewed_edges
    if not domain.has_curated_entries:
        assert plan == [] and plan_overlay(domain, GraphState()) == []
        assert domain_lexicon(domain) == DomainLexicon()


def test_a_proposed_alias_on_a_committed_term_plans_no_write(tmp_path):
    """
    The design review's probe, on a copy of the Economics files: a proposed alias reaches
    no plan; once approved it is exactly one update, and applying it is idempotent.
    """
    shutil.copytree(COMMITTED_ROOT / "economics", tmp_path / "economics")
    path = tmp_path / "economics" / "dictionary.yaml"
    committed = load_domain("economics", tmp_path)
    assert committed is not None
    sharing = {name for names in unresolved_shared_aliases(committed).values() for name in names}
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = next(
        (
            e
            for e in document["terms"]
            if e["review_status"] == "extracted" and e["name"] not in sharing
        ),
        None,
    )
    if entry is None:
        pytest.skip("every committed Economics term is reviewed or shares an alias")
    adapter, session = fake_adapter("economics")
    for built in committed.terms:
        session.add_concept(built.name, definition=built.definition, aliases=list(built.aliases))
    baseline = apply_overlay(adapter, committed, dry_run=True).operations
    entry["aliases"].append("a suggested alias")

    def applied_as(status: str, **provenance: str) -> list:
        """Apply the copy with the entry in ``status``; the operations the alias adds."""
        entry["review_status"] = status
        entry["provenance"].update(provenance)
        path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
        domain = load_domain("economics", tmp_path)
        assert domain is not None
        return [op for op in apply_overlay(adapter, domain).operations if op not in baseline]

    assert applied_as("proposed") == []
    assert "a suggested alias" not in session.concepts[entry["name"]]["aliases"]

    (operation,) = applied_as("approved", **REVIEWED)
    assert (operation.kind.value, operation.name) == ("update_concept", entry["name"])
    assert session.concepts[entry["name"]]["aliases"][-1] == "a suggested alias"
    assert applied_as("approved") == []


@pytest.mark.parametrize("subject_id", COMMITTED)
def test_committed_inventory_matches_the_configured_books(subject_id):
    domain = load_domain(subject_id, COMMITTED_ROOT)
    subject = get_subject(subject_id)
    assert domain is not None

    assert [s.id for s in domain.sources] == [book.id for book in subject.books]
    for entry, book in zip(domain.sources, subject.books, strict=True):
        assert entry.title == book.title
        assert entry.connector == book.connector
        assert entry.uri in (book.repo_url_raw, f"https://openstax.org/books/{book.openstax_slug}")
        assert entry.license in subject.attribution  # "CC BY 4.0", as the attribution states it


@pytest.mark.parametrize("subject_id", COMMITTED)
def test_committed_files_name_roles_not_people(subject_id):
    """The files are public: a steward or a reviewer is a role, never an address."""
    domain = load_domain(subject_id, COMMITTED_ROOT)
    assert domain is not None

    roles = [
        domain.meta.steward,
        *(entry.steward for entry in domain.sources),
        *(entry.provenance.reviewed_by or "" for entry in (*domain.terms, *domain.relationships)),
    ]
    assert domain.meta.steward and not [role for role in roles if "@" in role]


def test_domains_are_found_from_another_working_directory(tmp_path, monkeypatch):
    repository_root = COMMITTED_ROOT.resolve()
    monkeypatch.chdir(tmp_path)

    assert default_domains_root() == repository_root
    assert load_domain("us_history") is not None


def test_committed_dictionaries_are_sorted_and_use_slug_ids():
    """What draft writes: terms by id, relationships by type, source and target."""
    for subject_id in COMMITTED:
        directory = COMMITTED_ROOT / subject_id
        terms = yaml.safe_load((directory / "dictionary.yaml").read_text(encoding="utf-8"))["terms"]
        edges = yaml.safe_load((directory / "relationships.yaml").read_text(encoding="utf-8"))[
            "relationships"
        ]
        ids = [entry["id"] for entry in terms]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        keys = [(entry["type"], entry["source"], entry["target"]) for entry in edges]
        assert keys == sorted(keys)
