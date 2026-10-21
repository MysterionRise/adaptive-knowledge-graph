"""Graph quality report (backend/app/kg/report.py)."""

from datetime import UTC, datetime

import pytest

from backend.app.kg.report import graph_report, prereq_cycles
from backend.app.kg.schema import ConceptNode, KnowledgeGraph, Relationship, RelationshipType

pytestmark = pytest.mark.unit


def _concept(name: str, **fields) -> ConceptNode:
    return ConceptNode(name=name, **fields)


def _rel(source: str, target: str, rel_type: RelationshipType, provenance=None) -> Relationship:
    return Relationship(source=source, target=target, type=rel_type, provenance=provenance)


def _graph() -> KnowledgeGraph:
    """Four concepts, a PREREQ cycle A -> B -> C -> A and one RELATED edge."""
    kg = KnowledgeGraph()
    kg.add_concept(_concept("Stamp Act", key_term=True, definition="a 1765 tax", frequency=5))
    kg.add_concept(_concept("Sons of Liberty", key_term=True, definition="protesters", frequency=3))
    kg.add_concept(_concept("Boycott", aliases=["Boycotts"], frequency=2, importance_score=0.2))
    kg.add_concept(_concept("Parliament", frequency=1, importance_score=0.1))
    for rel in [
        _rel("m1", "Stamp Act", RelationshipType.COVERS),
        _rel("Stamp Act", "Sons of Liberty", RelationshipType.PREREQ, {"source": "glossary"}),
        _rel("Sons of Liberty", "Boycott", RelationshipType.PREREQ, {"source": "pattern"}),
        _rel("Boycott", "Stamp Act", RelationshipType.PREREQ, {"source": "glossary"}),
        _rel("Stamp Act", "Parliament", RelationshipType.RELATED),
    ]:
        kg.add_relationship(rel)
    return kg


class TestPrereqCycles:
    def test_finds_the_cycle_closed_on_its_first_concept(self):
        assert prereq_cycles(_graph()) == [["Boycott", "Stamp Act", "Sons of Liberty", "Boycott"]]

    def test_a_chain_has_no_cycle(self):
        kg = KnowledgeGraph()
        for name in ("A", "B", "C"):
            kg.add_concept(_concept(name))
        kg.add_relationship(_rel("A", "B", RelationshipType.PREREQ))
        kg.add_relationship(_rel("B", "C", RelationshipType.PREREQ))
        kg.add_relationship(_rel("C", "A", RelationshipType.RELATED))  # RELATED does not count
        assert prereq_cycles(kg) == []

    def test_limit_caps_the_cycles_listed(self):
        kg = KnowledgeGraph()
        for name in ("A", "B", "C", "D"):
            kg.add_concept(_concept(name))
        for source, target in (("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")):
            kg.add_relationship(_rel(source, target, RelationshipType.PREREQ))
        assert len(prereq_cycles(kg)) == 2
        assert prereq_cycles(kg, limit=1) == [["A", "B", "A"]]


class TestGraphReport:
    def test_counts_shares_provenance_degree_cycles_and_noise(self):
        report = graph_report(
            _graph(),
            subject_id="us_history",
            source="data/processed/books_us_history.jsonl",
            records=2,
            options={"max_concepts": 200},
            generated_at=datetime(2026, 10, 21, 9, 0, tzinfo=UTC),
        )
        assert report.startswith("# Knowledge graph report: us_history\n")
        assert "Generated: 2026-10-21T09:00:00+00:00" in report
        assert "Source: `data/processed/books_us_history.jsonl` (2 records)" in report
        assert "Builder options: max_concepts=200" in report
        # Concepts
        assert "| Concepts | 4 |" in report
        assert "| Author key terms | 2 (50%) |" in report
        assert "| With a glossary definition | 2 (50%) |" in report
        assert "| With aliases | 1 (25%) |" in report
        assert "| Single-word names | 2 (50%) |" in report
        # Relationships by type and provenance
        assert "| PREREQ | glossary | 2 |" in report
        assert "| PREREQ | pattern | 1 |" in report
        assert "| RELATED | unspecified | 1 |" in report
        assert "| COVERS | - | 1 |" in report
        assert "| Total | | 5 |" in report
        # Degree: Stamp Act has three concept edges, Parliament one
        assert "| 1 | Stamp Act | 3 | 0.000 | 5 | yes | yes |" in report
        assert "| 4 | Parliament | 1 | 0.100 | 1 | no | no |" in report
        # Cycle and noise
        assert "1 cycle(s) found" in report
        assert "- Boycott -> Stamp Act -> Sons of Liberty -> Boycott" in report
        assert report.index("| Parliament | 1 | 0.100 | no | no |") > report.index("## Noise")
        assert report.endswith("\n") and not report.endswith("\n\n")

    def test_empty_graph_reports_without_failing(self):
        report = graph_report(
            KnowledgeGraph(), subject_id="empty", source="x.jsonl", records=0, options={}
        )
        assert "| Concepts | 0 |" in report
        assert "| Author key terms | n/a |" in report
        assert "| PREREQ | - | 0 |" in report
        assert "Builder options: defaults" in report
        assert "No cycles: every PREREQ chain can be ordered." in report
        assert "| - | none | - | - | - | - | - |" in report
        assert "| none | - | - | - | - |" in report
