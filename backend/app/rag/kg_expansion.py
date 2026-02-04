"""
Knowledge Graph expansion for RAG.

This is the "secret sauce" - uses KG to expand queries with related concepts
for better retrieval. This is what differentiates us from vanilla RAG.

Enterprise patterns:
- Multi-strategy concept extraction (NER, embedding, YAKE)
- Fulltext concept search for fuzzy matching
"""

from typing import Literal

from loguru import logger

from backend.app.core.settings import settings
from backend.app.kg.neo4j_adapter import Neo4jAdapter


class KGExpander:
    """Expands queries using knowledge graph relationships."""

    def __init__(
        self,
        max_hops: int = None,
        extraction_strategy: Literal["simple", "ensemble", "ner", "yake"] = "ensemble",
    ):
        """
        Initialize KG expander.

        Args:
            max_hops: Maximum hops in graph for expansion
            extraction_strategy: Concept extraction strategy
                - "simple": Original substring matching
                - "ensemble": Multi-strategy extraction (NER + YAKE)
                - "ner": spaCy NER only
                - "yake": YAKE keyword extraction only
        """
        self.max_hops = max_hops or settings.rag_kg_expansion_hops
        self.extraction_strategy = extraction_strategy
        self.neo4j_adapter = None
        self._concept_extractor = None

    @property
    def concept_extractor(self):
        """Lazy-load concept extractor."""
        if self._concept_extractor is None and self.extraction_strategy != "simple":
            from backend.app.nlp.concept_extractor import get_concept_extractor

            self._concept_extractor = get_concept_extractor()
        return self._concept_extractor

    def connect(self):
        """Connect to Neo4j."""
        self.neo4j_adapter = Neo4jAdapter()
        self.neo4j_adapter.connect()
        logger.info("KG Expander connected to Neo4j")

    def close(self):
        """Close Neo4j connection."""
        if self.neo4j_adapter:
            self.neo4j_adapter.close()

    def extract_concepts_from_query(self, query: str, all_concepts: set[str]) -> list[str]:
        """
        Extract concept names from query.

        Uses multi-strategy extraction when available, falls back to substring matching.

        Args:
            query: User query text
            all_concepts: Set of all known concept names

        Returns:
            List of concept names found in query
        """
        if self.extraction_strategy == "simple":
            return self._extract_simple(query, all_concepts)

        # Use enhanced concept extraction
        try:
            extractor = self.concept_extractor
            if extractor:
                extractor.set_known_concepts(all_concepts)
                matches = extractor.extract_concepts(
                    query,
                    strategy=self.extraction_strategy
                    if self.extraction_strategy in ("ner", "yake")
                    else "ensemble",
                    top_k=5,
                )
                found_concepts = [m.name for m in matches]

                if found_concepts:
                    logger.info(
                        f"Enhanced extraction ({self.extraction_strategy}): "
                        f"found {len(found_concepts)} concepts"
                    )
                    return found_concepts

        except Exception as e:
            logger.warning(f"Enhanced extraction failed, using simple: {e}")

        # Fallback to simple extraction
        return self._extract_simple(query, all_concepts)

    def _extract_simple(self, query: str, all_concepts: set[str]) -> list[str]:
        """Original simple substring matching."""
        query_lower = query.lower()
        found_concepts = []

        for concept in all_concepts:
            # Simple substring matching
            if concept.lower() in query_lower:
                found_concepts.append(concept)

        # Sort by length (prefer longer, more specific matches)
        found_concepts.sort(key=len, reverse=True)

        return found_concepts[:5]  # Max 5 concepts from query

    def expand_with_kg(self, concepts: list[str]) -> list[str]:
        """
        Expand concepts using KG relationships.

        Args:
            concepts: Initial concepts from query

        Returns:
            Expanded list of concepts
        """
        if not self.neo4j_adapter:
            logger.warning("Neo4j not connected, cannot expand with KG")
            return concepts

        expanded = set(concepts)

        for concept in concepts:
            try:
                # Get neighboring concepts
                neighbors = self.neo4j_adapter.query_concept_neighbors(
                    concept, max_hops=self.max_hops
                )

                for neighbor in neighbors:
                    expanded.add(neighbor["name"])

            except Exception as e:
                logger.warning(f"Failed to expand concept '{concept}': {e}")
                continue

        logger.info(f"Expanded {len(concepts)} concepts to {len(expanded)} using KG")
        return list(expanded)

    def expand_query(self, query: str, all_concepts: set[str]) -> dict:
        """
        Full query expansion pipeline.

        Args:
            query: Original query
            all_concepts: Set of all known concepts

        Returns:
            Dict with original_query, extracted_concepts, expanded_concepts
        """
        # Extract concepts from query
        extracted = self.extract_concepts_from_query(query, all_concepts)

        # Expand using KG
        expanded = self.expand_with_kg(extracted)

        # Build expanded query
        if expanded:
            expanded_terms = " ".join(expanded)
            expanded_query = f"{query} {expanded_terms}"
        else:
            expanded_query = query

        return {
            "original_query": query,
            "extracted_concepts": extracted,
            "expanded_concepts": expanded,
            "expanded_query": expanded_query,
            "expansion_count": len(expanded) - len(extracted),
        }


# Global singleton
_kg_expander: KGExpander = None


def get_kg_expander() -> KGExpander:
    """
    Get or create global KG expander instance.

    Returns:
        KGExpander instance
    """
    global _kg_expander

    if _kg_expander is None:
        _kg_expander = KGExpander()
        try:
            _kg_expander.connect()
        except Exception as e:
            logger.warning(f"KG expansion disabled (Neo4j connection failed): {e}")

    return _kg_expander


def get_all_concepts_from_neo4j() -> set[str]:
    """
    Get all concept names from Neo4j.

    Returns:
        Set of concept names
    """
    try:
        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            result = session.run("MATCH (c:Concept) RETURN c.name as name")
            concepts = {record["name"] for record in result}

        adapter.close()
        return concepts

    except Exception as e:
        logger.error(f"Failed to load concepts from Neo4j: {e}")
        return set()
