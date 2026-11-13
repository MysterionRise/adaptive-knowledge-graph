"""
The overlay of a curated domain on a subject's graph, and the lexicon view (#211).

- domain_lexicon / merged_aliases: approved aliases and rejected names only.
- plan_overlay: what each review status does, the order of the operations, what is
  skipped, and that planning against the applied state is empty.
- apply_overlay through a real Neo4jAdapter on an in-memory session: applying twice
  leaves identical node and edge property sets and the second run writes nothing.

Domains are written under tmp_path; nothing connects to Neo4j.
"""

import ast
import copy
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.domain.lexicon import DomainLexicon, domain_lexicon, merged_aliases
from backend.app.domain.overlay import (
    CURATED_PROVENANCE,
    GraphNotBuiltError,
    GraphState,
    Operation,
    OperationKind,
    apply_overlay,
    execute,
    plan_overlay,
    read_graph_state,
    skipped_entries,
)
from backend.app.kg.neo4j_adapter import QUIET_READ_OPTIONS
from backend.tests.domain_builders import (
    SOURCE_ID,
    SUBJECT,
    fake_adapter,
    make_domain,
    relationship,
    term,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Lexicon view
# ---------------------------------------------------------------------------


def _mixed_terms():
    return [
        term("Tariff", "approved", aliases=["Duty", "Customs Duty"], context_terms=["import"]),
        term("Trade", "proposed", aliases=["Commerce"]),
        term("Quota", aliases=["Quotas"]),
        term("Summary", "rejected"),
        term("Mercantilism", "deprecated", aliases=["Mercantile System"]),
    ]


def test_lexicon_takes_approved_aliases_and_rejected_names(tmp_path):
    lexicon = domain_lexicon(make_domain(tmp_path, _mixed_terms(), []))

    assert lexicon.aliases == {"Tariff": ("Duty", "Customs Duty")}
    assert lexicon.rejected_names == frozenset({"Summary", "Mercantilism"})
    assert lexicon.context_terms == {"Tariff": ("import",)}
    assert domain_lexicon(None) == DomainLexicon()


def test_merged_aliases_unions_and_drops_rejected_names(tmp_path):
    lexicon = domain_lexicon(make_domain(tmp_path, _mixed_terms(), []))
    graph = {"Tariff": ["Tariffs", "Duty"], "Trade": [], "Summary": ["Summaries"]}

    merged = merged_aliases(graph, lexicon)

    assert merged == {"Tariff": ["Tariffs", "Duty", "Customs Duty"], "Trade": []}
    assert graph["Tariff"] == ["Tariffs", "Duty"]  # the input is not changed


def _imported_modules(path: Path) -> set[str]:
    """Every module a file imports, at module level or inside a function or class."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def test_the_request_path_does_not_import_the_domain_package():
    """
    Wiring the domain into retrieval is a later change (after the v0.4.0 run).

    No module of backend/app outside the package imports it, the Neo4j adapter and the
    subject configuration included: the scripts are its only users.
    """
    app = Path("backend/app")
    importing = [
        str(path)
        for path in sorted(app.rglob("*.py"))
        if app / "domain" not in path.parents
        and any("domain" in module.split(".") for module in _imported_modules(path))
    ]
    assert importing == []


def test_importing_the_api_does_not_load_the_domain_package():
    code = (
        "import sys\n"
        "import backend.app.main\n"
        "print(sorted(m for m in sys.modules if m.startswith('backend.app.domain')))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=50, check=False
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


# ---------------------------------------------------------------------------
# plan_overlay
# ---------------------------------------------------------------------------

BUILDER_DEFINITION = "a tax on imports (builder)"


def _state() -> GraphState:
    """A graph as the builder left it: three concepts and one glossary PREREQ edge."""
    return GraphState(
        concepts={
            "Tariff": {"definition": BUILDER_DEFINITION, "aliases": ["Tariffs", "TARIFF"]},
            "Trade": {"definition": None, "aliases": []},
            "Quota": {"definition": "a limit on imports", "aliases": ["Quotas"]},
        },
        prereq_edges={
            ("Trade", "Tariff"): {"weight": 0.8, "confidence": 0.8, "provenance_source": "glossary"}
        },
    )


CYCLE_HINT = (
    "it would close a cycle with the PREREQ edges in the graph; reject an edge on the path "
    "that leads back from its target to its source to apply this one"
)
"""Why an approved PREREQ edge is skipped when the graph already leads back from its target."""


def _run(state: GraphState, operations: list[Operation]) -> GraphState:
    """Execute operations on a copy of ``state`` through the adapter, as apply does."""
    adapter, session = fake_adapter()
    for name, properties in state.concepts.items():
        session.add_concept(name, **properties)
    session.edges = {edge: dict(properties) for edge, properties in state.prereq_edges.items()}
    for operation in operations:
        execute(adapter, operation)
    return read_graph_state(adapter)


def test_extracted_only_dictionary_writes_nothing(tmp_path):
    domain = make_domain(tmp_path)  # every entry is extracted

    assert plan_overlay(domain, _state()) == []
    assert plan_overlay(domain, GraphState()) == []
    assert skipped_entries(domain, _state()) == []
    assert plan_overlay(None, _state()) == []


def test_proposed_never_reaches_graph(tmp_path):
    """A proposed term, alias, definition or edge plans no write, present in the graph or not."""
    terms = [
        term("Tariff", "proposed", aliases=["Duty"], definition="a proposed definition"),
        term("Trade", "proposed"),
        term("Embargo", "proposed", aliases=["Blockade"]),
    ]
    edges = [
        relationship("Tariff", "Trade", "proposed"),
        relationship("Embargo", "Trade", "proposed"),
    ]
    domain = make_domain(tmp_path, terms, edges)

    assert plan_overlay(domain, _state()) == []
    assert skipped_entries(domain, _state()) == []
    assert not domain.has_curated_entries


def test_approved_term_curated_definition_wins_and_aliases_are_unioned(tmp_path):
    curated = term(
        "Tariff",
        "approved",
        definition="a tax a government puts on imported goods",
        definition_source=SOURCE_ID,
        aliases=["Duty", "Tariffs", "Customs Duty"],
    )
    domain = make_domain(tmp_path, [curated, term("Trade"), term("Quota")], [])

    (operation,) = plan_overlay(domain, _state())

    assert operation.kind is OperationKind.UPDATE_CONCEPT
    assert operation.name == "Tariff" and not operation.is_removal
    assert operation.properties == {
        "definition": "a tax a government puts on imported goods",
        # stored aliases first and all kept, new ones after them, none repeated
        "aliases": ["Tariffs", "TARIFF", "Duty", "Customs Duty"],
        "term_id": "tariff",
        "review_status": "approved",
        "definition_source": SOURCE_ID,
    }
    assert "update concept 'Tariff': " in operation.describe()


def test_approved_term_without_a_definition_keeps_the_stored_one(tmp_path):
    domain = make_domain(tmp_path, [term("Tariff", "approved", aliases=["Tariffs"])], [])

    (operation,) = plan_overlay(domain, _state())

    assert operation.properties == {"term_id": "tariff", "review_status": "approved"}
    after = _run(_state(), [operation])
    assert after.concepts["Tariff"]["definition"] == BUILDER_DEFINITION
    assert after.concepts["Tariff"]["aliases"] == ["Tariffs", "TARIFF"]


def test_approved_term_the_build_did_not_extract_is_created(tmp_path):
    curated = term("Embargo", "approved", definition="a ban on trade", definition_source=SOURCE_ID)
    domain = make_domain(tmp_path, [curated], [])

    (operation,) = plan_overlay(domain, _state())

    assert operation.kind is OperationKind.CREATE_CONCEPT
    assert operation.properties == {
        "term_id": "embargo",
        "review_status": "approved",
        "definition_source": SOURCE_ID,
        "definition": "a ban on trade",
        "aliases": [],
    }
    assert "the build did not extract it" in operation.describe()
    created = _run(_state(), [operation]).concepts["Embargo"]
    assert created["definition"] == "a ban on trade" and created["review_status"] == "approved"


@pytest.mark.parametrize("status", ["rejected", "deprecated"])
def test_rejected_and_deprecated_names_are_removed(tmp_path, status):
    domain = make_domain(tmp_path, [term("Tariff", status), term("Embargo", status)], [])

    (operation,) = plan_overlay(domain, _state())  # "Embargo" is not in the graph

    assert operation.kind is OperationKind.REMOVE_CONCEPT
    assert operation.name == "Tariff" and operation.is_removal
    assert operation.describe() == (
        f"REMOVE concept 'Tariff' and its edges (term 'tariff' is {status})"
    )
    after = _run(_state(), [operation])
    assert "Tariff" not in after.concepts
    assert after.prereq_edges == {}  # its edges go with it


def test_approved_prereq_is_merged_with_curated_provenance(tmp_path):
    edges = [
        relationship("Trade", "Tariff", "approved", confidence=1.0, rule="taught first"),
        relationship("Quota", "Tariff", "approved", evidence_source=None, rule=None),
    ]
    domain = make_domain(tmp_path, None, edges)

    new, existing = plan_overlay(domain, _state())

    assert {new.kind, existing.kind} == {OperationKind.MERGE_PREREQ}
    assert (new.name, new.target) == ("Quota", "Tariff")
    assert new.properties == {
        "provenance_source": CURATED_PROVENANCE,
        "review_status": "approved",
        "confidence": 0.8,
    }
    # The builder's edge exists: only what differs is set
    assert (existing.name, existing.target) == ("Trade", "Tariff")
    assert existing.properties == {
        "provenance_source": "curated",
        "review_status": "approved",
        "confidence": 1.0,
        "rule": "taught first",
        "evidence_source": SOURCE_ID,
    }
    after = _run(_state(), [new, existing])
    assert after.prereq_edges[("Quota", "Tariff")]["provenance_source"] == "curated"
    assert after.prereq_edges[("Quota", "Tariff")]["weight"] == 0.8
    assert after.prereq_edges[("Trade", "Tariff")]["provenance_source"] == "curated"


@pytest.mark.parametrize("status", ["rejected", "deprecated"])
def test_rejected_prereq_is_removed(tmp_path, status):
    edges = [relationship("Trade", "Tariff", status), relationship("Quota", "Tariff", status)]
    domain = make_domain(tmp_path, None, edges)

    (operation,) = plan_overlay(domain, _state())  # Quota -> Tariff is not in the graph

    assert operation.kind is OperationKind.REMOVE_PREREQ and operation.is_removal
    assert operation.describe() == (
        f"REMOVE PREREQ 'Trade' -> 'Tariff' (the relationship is {status})"
    )
    after = _run(_state(), [operation])
    assert after.prereq_edges == {} and set(after.concepts) == {"Tariff", "Trade", "Quota"}


def test_operations_are_ordered_with_edge_removals_before_merges(tmp_path):
    terms = [
        term("Trade", "approved", aliases=["Commerce"]),
        term("Embargo", "approved"),
        term("Quota", "rejected"),
        term("Tariff"),
    ]
    edges = [
        relationship("Embargo", "Trade", "approved"),
        relationship("Trade", "Tariff", "rejected"),
    ]
    domain = make_domain(tmp_path, terms, edges)

    plan = plan_overlay(domain, _state())

    assert [(op.kind.value, op.name, op.target) for op in plan] == [
        ("create_concept", "Embargo", None),
        ("update_concept", "Trade", None),
        ("remove_prereq", "Trade", "Tariff"),
        ("merge_prereq", "Embargo", "Trade"),
        ("remove_concept", "Quota", None),
    ]
    assert [op.is_removal for op in plan] == [False, False, True, False, True]


def test_edges_the_overlay_cannot_apply_are_skipped_with_a_reason(tmp_path):
    terms = [term("Tariff"), term("Trade"), term("Quota"), term("Embargo")]
    edges = [
        relationship("Embargo", "Tariff", "approved"),  # Embargo is not in the graph
        relationship("Tariff", "Trade", "approved"),  # the graph has Trade -> Tariff
        relationship("Quota", "Trade", "approved", kind="RELATED"),
        relationship("Quota", "Tariff", "rejected", kind="RELATED"),
    ]
    domain = make_domain(tmp_path, terms, edges)

    assert plan_overlay(domain, _state()) == []
    skipped = {entry.entry: entry.reason for entry in skipped_entries(domain, _state())}
    assert skipped == {
        "PREREQ 'Embargo' -> 'Tariff' (approved)": "'Embargo' is not a concept in the graph",
        "PREREQ 'Tariff' -> 'Trade' (approved)": CYCLE_HINT,
        "RELATED 'Quota' -> 'Trade' (approved)": "only PREREQ edges are applied",
        "RELATED 'Quota' -> 'Tariff' (rejected)": "only PREREQ edges are applied",
    }
    assert skipped_entries(domain, _state())[0].describe().startswith("PREREQ 'Embargo'")


def test_rejecting_the_reverse_edge_lets_the_curated_direction_in(tmp_path):
    edges = [
        relationship("Tariff", "Trade", "approved"),
        relationship("Trade", "Tariff", "rejected"),
    ]
    domain = make_domain(tmp_path, None, edges)

    plan = plan_overlay(domain, _state())

    # The builder's edge goes first: between two writes the graph never holds both directions
    assert [(op.kind.value, op.name, op.target) for op in plan] == [
        ("remove_prereq", "Trade", "Tariff"),
        ("merge_prereq", "Tariff", "Trade"),
    ]
    assert skipped_entries(domain, _state()) == []
    assert set(_run(_state(), plan[:1]).prereq_edges) == set()
    after = _run(_state(), plan)
    assert set(after.prereq_edges) == {("Tariff", "Trade")}
    assert after.prereq_edges[("Tariff", "Trade")]["provenance_source"] == "curated"
    assert plan_overlay(domain, after) == []


def test_the_cycle_hint_fits_a_cycle_of_three_edges(tmp_path):
    """No edge runs the other way here: the way back from the target has two edges."""
    state = _state()  # Trade -> Tariff
    state.prereq_edges[("Tariff", "Quota")] = {"weight": 0.8, "provenance_source": "glossary"}
    closing = relationship("Quota", "Trade", "approved")  # Quota -> Trade -> Tariff -> Quota

    domain = make_domain(tmp_path / "skipped", None, [closing])

    assert ("Trade", "Quota") not in state.prereq_edges
    assert plan_overlay(domain, state) == []
    assert [entry.describe() for entry in skipped_entries(domain, state)] == [
        f"PREREQ 'Quota' -> 'Trade' (approved): {CYCLE_HINT}"
    ]

    # Rejecting either edge of the path Trade -> Tariff -> Quota lets the approved one in
    for on_path in (("Trade", "Tariff"), ("Tariff", "Quota")):
        edges = [closing, relationship(*on_path, "rejected")]
        domain = make_domain(tmp_path / "-".join(on_path), None, edges)

        plan = plan_overlay(domain, state)

        assert [(op.kind.value, op.name, op.target) for op in plan] == [
            ("remove_prereq", *on_path),
            ("merge_prereq", "Quota", "Trade"),
        ]
        assert skipped_entries(domain, state) == []
        assert plan_overlay(domain, _run(state, plan)) == []


def test_the_documentation_gives_the_same_cycle_advice():
    text = " ".join(Path("docs/DOMAINS.md").read_text(encoding="utf-8").split())

    assert (
        "Reject an edge on the path that leads back from the target to the source to apply it."
    ) in text
    assert "runs the other way" not in text


def test_an_edge_of_a_removed_concept_is_not_removed_twice(tmp_path):
    terms = [term("Tariff", "rejected"), term("Trade"), term("Quota")]
    domain = make_domain(tmp_path, terms, [relationship("Trade", "Tariff", "rejected")])

    plan = plan_overlay(domain, _state())

    assert [op.kind for op in plan] == [OperationKind.REMOVE_CONCEPT]


def test_planning_does_not_change_its_inputs(tmp_path):
    terms = [
        term("Tariff", "approved", aliases=["Duty"], definition="a curated definition"),
        term("Trade"),
        term("Quota", "rejected"),
    ]
    domain = make_domain(tmp_path, terms, [relationship("Trade", "Tariff", "approved")])
    state = _state()
    state_before, domain_before = copy.deepcopy(state), copy.deepcopy(domain)

    first = plan_overlay(domain, state)

    assert len(first) == 3
    assert state == state_before and domain == domain_before
    assert plan_overlay(domain, state) == first


def test_the_plan_does_not_depend_on_the_order_of_the_file_entries(tmp_path):
    terms = [
        term("Trade", "approved", aliases=["Commerce"]),
        term("Tariff", "approved", definition="a curated definition"),
        term("Embargo", "approved"),
        term("Quota", "rejected"),
    ]
    edges = [
        relationship("Trade", "Tariff", "rejected"),
        relationship("Tariff", "Trade", "approved"),
        relationship("Embargo", "Trade", "approved"),
    ]

    forward = plan_overlay(make_domain(tmp_path / "a", terms, edges), _state())
    backward = plan_overlay(make_domain(tmp_path / "b", terms[::-1], edges[::-1]), _state())

    assert len(forward) == 7
    assert forward == backward


def _curated_domain(tmp_path):
    """Every kind of curated entry at once, against ``_state()``."""
    terms = [
        term(
            "Tariff",
            "approved",
            definition="a tax a government puts on imported goods",
            definition_source=SOURCE_ID,
            aliases=["Duty", "Tariffs", "Customs Duty"],
        ),
        term("Trade", "approved"),
        term("Embargo", "approved", aliases=["Blockade"]),
        term("Quota", "rejected"),
        term("Mercantilism", "proposed", aliases=["Mercantile System"]),
        term("Subsidy"),
    ]
    edges = [
        relationship("Trade", "Tariff", "approved", confidence=0.9),
        relationship("Embargo", "Trade", "approved", rule="taught first", evidence_source=None),
        relationship("Mercantilism", "Trade", "proposed"),
    ]
    return make_domain(tmp_path, terms, edges)


def test_planning_against_the_applied_state_is_empty(tmp_path):
    """Idempotence without Neo4j: the state a plan produces needs no further operation."""
    domain = _curated_domain(tmp_path)

    plan = plan_overlay(domain, _state())
    assert len(plan) == 6
    once = _run(_state(), plan)

    assert plan_overlay(domain, once) == []
    twice = _run(once, plan)  # replaying the same operations changes nothing either
    assert twice == once
    assert once.concepts["Tariff"]["aliases"] == ["Tariffs", "TARIFF", "Duty", "Customs Duty"]
    assert "Quota" not in once.concepts and "Mercantilism" not in once.concepts
    assert "Subsidy" not in once.concepts  # extracted, and the build did not have it


# ---------------------------------------------------------------------------
# apply_overlay through the Neo4j adapter
# ---------------------------------------------------------------------------


def _seeded_adapter():
    adapter, session = fake_adapter()
    for name, properties in _state().concepts.items():
        session.add_concept(name, key_term=True, importance_score=0.5, **properties)
    session.add_prereq("Trade", "Tariff", evidence="Tariff: a tax on trade")
    return adapter, session


def test_apply_twice_is_identical(tmp_path):
    """Acceptance: two runs of apply leave identical node and edge property sets."""
    domain = _curated_domain(tmp_path)
    adapter, session = _seeded_adapter()

    first = apply_overlay(adapter, domain)
    after_first = session.snapshot()
    writes_after_first = len(session.writes)
    second = apply_overlay(adapter, domain)

    assert session.snapshot() == after_first
    assert len(session.writes) == writes_after_first == 6  # the second run writes nothing
    assert len(first.operations) == 6 and first.pending == () and not first.dry_run
    assert second.operations == () and second.pending == ()
    assert [op.kind.value for op in first.removals] == ["remove_concept"]

    nodes, edges = after_first
    assert nodes["Tariff"] == {
        "key_term": True,
        "importance_score": 0.5,
        "definition": "a tax a government puts on imported goods",
        "aliases": ["Tariffs", "TARIFF", "Duty", "Customs Duty"],
        "term_id": "tariff",
        "review_status": "approved",
        "definition_source": SOURCE_ID,
    }
    assert nodes["Embargo"]["aliases"] == ["Blockade"] and nodes["Embargo"]["frequency"] == 0
    assert set(nodes) == {"Tariff", "Trade", "Embargo"}
    assert edges[("Trade", "Tariff")] == {
        "weight": 0.8,
        "evidence": "Tariff: a tax on trade",
        "provenance_source": "curated",
        "review_status": "approved",
        "confidence": 0.9,
        "rule": "glossary_definition",
        "evidence_source": SOURCE_ID,
    }
    assert edges[("Embargo", "Trade")] == {
        "weight": 0.8,
        "provenance_source": "curated",
        "review_status": "approved",
        "confidence": 0.8,
        "rule": "taught first",
    }


def test_apply_reads_on_quiet_sessions_and_writes_on_plain_ones(tmp_path):
    """
    Only the two state reads hide the server's "unrecognized" notifications.

    On a store without the curated property keys the first reads would log a warning per
    key. A write keeps its notifications.
    """
    domain = _curated_domain(tmp_path)
    adapter, session = _seeded_adapter()

    apply_overlay(adapter, domain)

    quiet = {"database": "neo4j", **QUIET_READ_OPTIONS}
    plain = {"database": "neo4j"}
    opened = [call.kwargs for call in adapter.driver.session.call_args_list]
    # The state is read (two statements), six operations are written, the state is read again
    assert opened == [quiet, quiet, *[plain] * 6, quiet, quiet]
    assert QUIET_READ_OPTIONS == {"notifications_disabled_classifications": ["UNRECOGNIZED"]}
    reads = [query for query, _ in session.calls if "MERGE" not in query and "DELETE" not in query]
    assert len(reads) == 4 and len(session.writes) == 6


def test_apply_acts_on_a_domain_whose_only_curated_entry_is_a_relationship(tmp_path):
    domain = make_domain(tmp_path, None, [relationship("Quota", "Tariff", "approved")])
    adapter, session = _seeded_adapter()

    assert domain.has_curated_entries
    result = apply_overlay(adapter, domain)

    assert [(op.kind.value, op.name, op.target) for op in result.operations] == [
        ("merge_prereq", "Quota", "Tariff")
    ]
    assert session.edges[("Quota", "Tariff")]["provenance_source"] == "curated"
    assert result.pending == ()


def test_a_rebuild_is_overlaid_again(tmp_path):
    """`make build-kg` writes the builder's values again; the next apply restores the domain."""
    domain = _curated_domain(tmp_path)
    adapter, session = _seeded_adapter()
    apply_overlay(adapter, domain)
    applied = session.snapshot()

    # The builder's MERGE ... SET on a concept, and a rejected concept that it extracts again
    session.concepts["Tariff"].update(definition=BUILDER_DEFINITION, aliases=["Tariffs"])
    session.add_concept("Quota", definition="a limit on imports")
    again = apply_overlay(adapter, domain)

    assert [(op.kind.value, op.name) for op in again.operations] == [
        ("update_concept", "Tariff"),
        ("remove_concept", "Quota"),
    ]
    nodes, edges = session.snapshot()
    assert nodes["Tariff"]["definition"] == "a tax a government puts on imported goods"
    assert nodes["Tariff"]["aliases"] == ["Tariffs", "Duty", "Customs Duty"]
    assert "Quota" not in nodes
    assert edges == applied[1] and again.pending == ()


def test_apply_refuses_a_graph_without_concepts(tmp_path):
    """Nothing is built: creating the approved terms would make the graph look seeded."""
    domain = _curated_domain(tmp_path)
    adapter, session = fake_adapter()

    for dry_run in (False, True):
        with pytest.raises(GraphNotBuiltError, match="the graph of us_history has no concepts"):
            apply_overlay(adapter, domain, dry_run=dry_run)

    assert session.writes == [] and session.concepts == {}
    # An extracted domain still applies as nothing, without reading the graph
    assert apply_overlay(adapter, make_domain(tmp_path / "extracted")).operations == ()


def test_apply_keeps_file_values_out_of_the_query_text(tmp_path):
    domain = _curated_domain(tmp_path)
    adapter, session = _seeded_adapter()

    apply_overlay(adapter, domain)

    file_values = ["Tariff", "Embargo", "Blockade", "imported goods", SOURCE_ID, "curated"]
    for query, _ in session.calls:
        assert "us_history_Concept" in query
        assert not [value for value in file_values if value in query], query
    assert any("properties" in parameters for _, parameters in session.writes)


def test_apply_of_an_extracted_domain_does_not_read_the_graph(tmp_path):
    adapter, session = _seeded_adapter()
    before = session.snapshot()

    result = apply_overlay(adapter, make_domain(tmp_path))
    nothing = apply_overlay(adapter, None)

    assert session.calls == [] and session.snapshot() == before
    assert result.operations == () and result.skipped == () and result.subject_id == SUBJECT
    assert nothing.operations == () and nothing.subject_id == ""


def test_dry_run_plans_without_writing_and_announces_each_operation(tmp_path):
    domain = _curated_domain(tmp_path)
    adapter, session = _seeded_adapter()
    before = session.snapshot()
    announced: list[str] = []

    result = apply_overlay(
        adapter, domain, dry_run=True, announce=lambda op: announced.append(op.describe())
    )

    assert session.writes == [] and session.snapshot() == before
    assert result.dry_run and len(result.operations) == 6 and result.pending == ()
    assert announced == [op.describe() for op in result.operations]
    assert announced[-1] == "REMOVE concept 'Quota' and its edges (term 'quota' is rejected)"


def test_each_operation_is_announced_before_it_runs(tmp_path):
    domain = make_domain(tmp_path, [term("Quota", "rejected")], [])
    adapter, session = _seeded_adapter()
    seen: list[bool] = []

    apply_overlay(adapter, domain, announce=lambda op: seen.append("Quota" in session.concepts))

    assert seen == [True] and "Quota" not in session.concepts


def test_apply_reports_what_is_still_pending(tmp_path):
    """A graph that does not take the writes is reported, not assumed to be applied."""
    domain = make_domain(tmp_path, [term("Quota", "rejected")], [])
    adapter, session = _seeded_adapter()
    adapter.delete_concept = lambda name: None

    result = apply_overlay(adapter, domain)

    assert [op.name for op in result.pending] == ["Quota"]
    assert "Quota" in session.concepts


def test_execute_refuses_an_edge_operation_without_a_target():
    adapter, _ = fake_adapter()

    with pytest.raises(ValueError, match="merge_prereq needs a target"):
        execute(adapter, Operation(OperationKind.MERGE_PREREQ, "Trade"))
