"""Knowledge Graph module."""

from backend.app.kg.builder import KGBuilder
from backend.app.kg.neo4j_adapter import Neo4jAdapter
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

__all__ = [
    "KGBuilder",
    "Neo4jAdapter",
    "KnowledgeGraph",
    "ConceptNode",
    "ModuleNode",
    "SectionNode",
    "ChunkNode",
    "NodeType",
    "Relationship",
    "RelationshipType",
]


# Lazy imports for optional LangChain functionality
def __getattr__(name: str):
    """Lazy import for optional dependencies."""
    if name in ("CypherQAService", "get_cypher_qa_service", "is_langchain_available"):
        from backend.app.kg import cypher_qa

        return getattr(cypher_qa, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
