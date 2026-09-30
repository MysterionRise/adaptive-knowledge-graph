"""Tests for the knowledge-graph schema models (backend/app/kg/schema.py)."""

import pytest

from backend.app.kg.schema import (
    ChunkNode,
    ConceptNode,
    KnowledgeGraph,
    ModuleNode,
    NodeType,
    Relationship,
    RelationshipType,
    SectionNode,
)


def related(source: str, target: str, weight: float = 0.5) -> Relationship:
    return Relationship(source=source, target=target, type=RelationshipType.RELATED, weight=weight)


@pytest.mark.unit
class TestModels:
    def test_enum_values_match_neo4j_labels_and_types(self):
        assert [t.value for t in NodeType] == ["Concept", "Section", "Module", "Chunk"]
        assert {t.value for t in RelationshipType} == {
            "PREREQ",
            "RELATED",
            "COVERS",
            "PART_OF",
            "MENTIONS",
            "NEXT",
            "FIRST_CHUNK",
        }

    def test_concept_defaults(self):
        concept = ConceptNode(name="Stamp Act")

        assert concept.type == NodeType.CONCEPT
        assert concept.definition is None
        assert concept.key_term is False
        assert concept.frequency == 1
        assert concept.importance_score == 0.0
        assert concept.source_modules == [] and concept.aliases == []

    def test_other_node_defaults(self):
        section = SectionNode(section_id="s1", title="Intro", module_id="m1")
        module = ModuleNode(module_id="m1", title="The Americas")
        chunk = ChunkNode(chunk_id="m1_0", text="Some text")

        assert section.type == NodeType.SECTION and section.learning_objectives == []
        assert module.type == NodeType.MODULE and module.key_terms == []
        assert chunk.type == NodeType.CHUNK
        assert (chunk.chunk_index, chunk.start_char, chunk.end_char) == (0, 0, 0)
        assert chunk.text_embedding is None and chunk.previous_chunk_id is None

    def test_relationship_defaults_and_provenance(self):
        plain = Relationship(source="a", target="b", type=RelationshipType.COVERS)
        prereq = Relationship(
            source="Stamp Act",
            target="Townshend Acts",
            type=RelationshipType.PREREQ,
            evidence="Townshend Acts: taxes passed after the repeal of the Stamp Act",
            provenance={"source": "glossary", "module_id": "m50024"},
        )

        assert (plain.weight, plain.confidence, plain.evidence, plain.provenance) == (
            1.0,
            1.0,
            None,
            None,
        )
        restored = Relationship.model_validate_json(prereq.model_dump_json())
        assert restored == prereq
        assert restored.provenance == {"source": "glossary", "module_id": "m50024"}


@pytest.mark.unit
class TestKnowledgeGraph:
    def test_add_concept_merges_duplicates_in_first_seen_order(self):
        kg = KnowledgeGraph()
        kg.add_concept(ConceptNode(name="Slavery", frequency=2, source_modules=["m2", "m1"]))
        kg.add_concept(ConceptNode(name="Slavery", frequency=3, source_modules=["m1", "m3"]))
        kg.add_concept(ConceptNode(name="Reconstruction"))

        assert list(kg.concepts) == ["Slavery", "Reconstruction"]
        assert kg.concepts["Slavery"].frequency == 5
        assert kg.concepts["Slavery"].source_modules == ["m2", "m1", "m3"]

    def test_add_relationship_deduplicates_keeping_max_weight(self):
        kg = KnowledgeGraph()
        kg.add_relationship(related("a", "b", 0.5))
        kg.add_relationship(related("a", "b", 0.9))
        kg.add_relationship(related("a", "b", 0.2))
        kg.add_relationship(Relationship(source="a", target="b", type=RelationshipType.PREREQ))
        kg.add_relationship(related("b", "a", 0.1))  # direction matters

        assert len(kg.relationships) == 3
        assert kg.relationships[0].weight == 0.9

    def test_add_chunk(self):
        kg = KnowledgeGraph()
        kg.add_chunk(ChunkNode(chunk_id="m1_0", text="first"))
        kg.add_chunk(ChunkNode(chunk_id="m1_0", text="replaced"))

        assert list(kg.chunks) == ["m1_0"]
        assert kg.chunks["m1_0"].text == "replaced"

    def test_get_concept_neighbors(self):
        kg = KnowledgeGraph()
        kg.add_relationship(related("Stamp Act", "Sons of Liberty"))
        kg.add_relationship(
            Relationship(source="Stamp Act", target="Townshend Acts", type=RelationshipType.PREREQ)
        )
        kg.add_relationship(
            Relationship(source="Sugar Act", target="Stamp Act", type=RelationshipType.PREREQ)
        )
        kg.add_relationship(related("Sons of Liberty", "Stamp Act"))

        assert sorted(kg.get_concept_neighbors("Stamp Act")) == [
            "Sons of Liberty",
            "Sugar Act",
            "Townshend Acts",
        ]
        assert sorted(kg.get_concept_neighbors("Stamp Act", [RelationshipType.PREREQ])) == [
            "Sugar Act",
            "Townshend Acts",
        ]
        assert kg.get_concept_neighbors("Unknown") == []

    def test_get_stats(self):
        kg = KnowledgeGraph()
        kg.add_concept(ConceptNode(name="Stamp Act"))
        kg.modules["m1"] = ModuleNode(module_id="m1", title="Protests")
        kg.sections["s1"] = SectionNode(section_id="s1", title="Intro", module_id="m1")
        kg.add_chunk(ChunkNode(chunk_id="m1_0", text="text"))
        kg.add_relationship(related("Stamp Act", "Sons of Liberty"))
        kg.add_relationship(
            Relationship(source="m1", target="Stamp Act", type=RelationshipType.COVERS)
        )

        stats = kg.get_stats()

        assert stats["concept_count"] == 1
        assert stats["module_count"] == 1
        assert stats["section_count"] == 1
        assert stats["chunk_count"] == 1
        assert stats["relationship_count"] == 2
        assert stats["relationship_types"]["RELATED"] == 1
        assert stats["relationship_types"]["COVERS"] == 1
        assert stats["relationship_types"]["PREREQ"] == 0
        assert set(stats["relationship_types"]) == {t.value for t in RelationshipType}

    def test_json_round_trip(self):
        kg = KnowledgeGraph()
        kg.add_concept(ConceptNode(name="Stamp Act", key_term=True, aliases=["Duties Act"]))
        kg.add_relationship(
            Relationship(
                source="Stamp Act",
                target="Sons of Liberty",
                type=RelationshipType.PREREQ,
                provenance={"source": "cue_phrase", "pattern": "led_to", "module_id": "m1"},
            )
        )

        assert KnowledgeGraph.model_validate_json(kg.model_dump_json()) == kg
