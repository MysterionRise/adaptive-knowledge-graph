"""
Knowledge Graph schema definitions.

Defines node types, relationship types, and their properties for the
Biology Knowledge Graph.
"""

from enum import Enum

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Types of nodes in the knowledge graph."""

    CONCEPT = "Concept"  # Biological concepts (e.g., "Photosynthesis", "Mitosis")
    SECTION = "Section"  # Textbook sections
    MODULE = "Module"  # Textbook modules


class RelationshipType(str, Enum):
    """Types of relationships in the knowledge graph."""

    PREREQ = "PREREQ"  # Prerequisite relationship (A is prerequisite for B)
    RELATED = "RELATED"  # Related concepts
    COVERS = "COVERS"  # Section/Module covers Concept
    PART_OF = "PART_OF"  # Section is part of Module
    MENTIONS = "MENTIONS"  # Content mentions Concept


class ConceptNode(BaseModel):
    """Concept node in the knowledge graph."""

    name: str = Field(..., description="Concept name")
    type: str = Field(default=NodeType.CONCEPT, description="Node type")
    definition: str | None = Field(None, description="Concept definition")
    key_term: bool = Field(default=False, description="Is this a key term from textbook?")
    frequency: int = Field(default=1, description="Number of times mentioned")
    importance_score: float = Field(default=0.0, description="Computed importance (0-1)")

    # Metadata
    source_modules: list[str] = Field(default_factory=list, description="Modules mentioning this")
    aliases: list[str] = Field(default_factory=list, description="Alternative names")


class SectionNode(BaseModel):
    """Section node in the knowledge graph."""

    section_id: str = Field(..., description="Section identifier")
    title: str = Field(..., description="Section title")
    type: str = Field(default=NodeType.SECTION, description="Node type")
    module_id: str = Field(..., description="Parent module ID")
    learning_objectives: list[str] = Field(default_factory=list, description="Learning objectives")


class ModuleNode(BaseModel):
    """Module node in the knowledge graph."""

    module_id: str = Field(..., description="Module identifier")
    title: str = Field(..., description="Module title")
    type: str = Field(default=NodeType.MODULE, description="Node type")
    key_terms: list[str] = Field(default_factory=list, description="Key terms in module")


class Relationship(BaseModel):
    """Relationship between nodes."""

    source: str = Field(..., description="Source node name/ID")
    target: str = Field(..., description="Target node name/ID")
    type: RelationshipType = Field(..., description="Relationship type")
    weight: float = Field(default=1.0, description="Relationship strength (0-1)")
    confidence: float = Field(default=1.0, description="Confidence score (0-1)")
    evidence: str | None = Field(None, description="Text evidence for this relationship")


class KnowledgeGraph(BaseModel):
    """Complete knowledge graph representation."""

    concepts: dict[str, ConceptNode] = Field(default_factory=dict, description="Concept nodes")
    sections: dict[str, SectionNode] = Field(default_factory=dict, description="Section nodes")
    modules: dict[str, ModuleNode] = Field(default_factory=dict, description="Module nodes")
    relationships: list[Relationship] = Field(default_factory=list, description="All relationships")

    def add_concept(self, concept: ConceptNode):
        """Add or update a concept node."""
        if concept.name in self.concepts:
            # Update frequency
            existing = self.concepts[concept.name]
            existing.frequency += concept.frequency
            existing.source_modules.extend(concept.source_modules)
            existing.source_modules = list(set(existing.source_modules))
        else:
            self.concepts[concept.name] = concept

    def add_relationship(self, relationship: Relationship):
        """Add a relationship (avoiding duplicates)."""
        # Check for duplicates
        for rel in self.relationships:
            if (
                rel.source == relationship.source
                and rel.target == relationship.target
                and rel.type == relationship.type
            ):
                # Update weight (take max)
                rel.weight = max(rel.weight, relationship.weight)
                return

        self.relationships.append(relationship)

    def get_concept_neighbors(self, concept_name: str, relationship_types: list[RelationshipType] | None = None) -> list[str]:
        """
        Get neighboring concepts for a given concept.

        Args:
            concept_name: Name of the concept
            relationship_types: Filter by relationship types (None = all types)

        Returns:
            List of neighboring concept names
        """
        neighbors = []
        for rel in self.relationships:
            if relationship_types and rel.type not in relationship_types:
                continue

            if rel.source == concept_name:
                neighbors.append(rel.target)
            elif rel.target == concept_name:
                neighbors.append(rel.source)

        return list(set(neighbors))

    def get_stats(self) -> dict:
        """Get graph statistics."""
        return {
            "concept_count": len(self.concepts),
            "section_count": len(self.sections),
            "module_count": len(self.modules),
            "relationship_count": len(self.relationships),
            "relationship_types": {
                rel_type.value: sum(1 for r in self.relationships if r.type == rel_type)
                for rel_type in RelationshipType
            },
        }
