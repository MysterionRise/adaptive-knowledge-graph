"""
Knowledge Graph expansion for RAG.

This is the "secret sauce" - uses KG to expand queries with related concepts
for better retrieval. This is what differentiates us from vanilla RAG.

How it works:
- Concepts are extracted from the query with the ConceptExtractor ensemble
  (spaCy NER + YAKE keywords matched against the subject's concept names),
  falling back to plain substring matching
- Each extracted concept is expanded with its neighbours in the subject's
  graph, up to RAG_KG_EXPANSION_HOPS hops
"""

import threading
from typing import Literal

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter


class KGExpander:
    """Expands queries using knowledge graph relationships."""

    def __init__(
        self,
        max_hops: int | None = None,
        extraction_strategy: Literal["simple", "ensemble", "ner", "yake"] = "ensemble",
        subject_id: str | None = None,
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
            subject_id: Subject identifier for multi-subject support
                (None = default_subject from config/subjects.yaml)
        """
        self.max_hops = max_hops or settings.rag_kg_expansion_hops
        self.extraction_strategy = extraction_strategy
        self.subject_id = subject_id
        self.neo4j_adapter: Neo4jAdapter | None = None
        self._concept_extractor: object | None = None

    @property
    def concept_extractor(self):
        """Lazy-load concept extractor."""
        if self._concept_extractor is None and self.extraction_strategy != "simple":
            from backend.app.nlp.concept_extractor import get_concept_extractor

            self._concept_extractor = get_concept_extractor()
        return self._concept_extractor

    def connect(self):
        """Use the subject's shared Neo4j adapter (subject-prefixed labels)."""
        self.neo4j_adapter = get_neo4j_adapter(self.subject_id)
        logger.info(f"KG Expander connected to Neo4j (subject: {self.subject_id or 'default'})")

    def close(self):
        """Release the adapter; shared adapters are closed by clear_neo4j_adapters()."""
        self.neo4j_adapter = None

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


# Registry of KG expanders per subject
_kg_expanders: dict[str, KGExpander] = {}
_kg_expanders_lock = threading.Lock()


def get_kg_expander(subject_id: str | None = None) -> KGExpander:
    """
    Get or create a KG expander instance for a specific subject.

    Uses a registry pattern to reuse expanders per subject.

    Args:
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, uses default_subject from config/subjects.yaml.

    Returns:
        KGExpander instance configured for the subject
    """
    resolved_id = get_subject(subject_id).id

    # Return cached expander if available
    expander = _kg_expanders.get(resolved_id)
    if expander is not None:
        return expander

    with _kg_expanders_lock:
        expander = _kg_expanders.get(resolved_id)
        if expander is None:
            # Create new expander with subject-specific configuration
            expander = KGExpander(subject_id=resolved_id)
            try:
                expander.connect()
            except Exception as e:
                logger.warning(
                    f"KG expansion disabled for {resolved_id} (Neo4j connection failed): {e}"
                )
            _kg_expanders[resolved_id] = expander
        return expander


def get_all_concepts_from_neo4j(subject_id: str | None = None) -> set[str]:
    """
    Get all concept names of a subject's knowledge graph.

    Args:
        subject_id: Subject identifier (None = default_subject from config/subjects.yaml)

    Returns:
        Set of concept names (empty if Neo4j is unavailable)
    """
    try:
        return get_neo4j_adapter(subject_id).get_all_concept_names()
    except Exception as e:
        logger.error(f"Failed to load concepts from Neo4j: {e}")
        return set()


def clear_kg_expanders() -> None:
    """Clear all cached KG expanders."""
    with _kg_expanders_lock:
        for expander in _kg_expanders.values():
            expander.close()
        _kg_expanders.clear()
    logger.info("Cleared all cached KG expanders")
