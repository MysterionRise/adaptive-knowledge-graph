"""
Knowledge Graph builder.

Extracts concepts from text and builds the knowledge graph structure.
Uses NLP techniques for concept extraction and relationship mining.
"""

import re
from collections import Counter
from typing import Dict, List, Set, Tuple

import networkx as nx
from loguru import logger
from yake import KeywordExtractor

from backend.app.kg.schema import (
    ConceptNode,
    KnowledgeGraph,
    ModuleNode,
    Relationship,
    RelationshipType,
    SectionNode,
)


class KGBuilder:
    """Builder for constructing knowledge graphs from textbook content."""

    def __init__(self, max_concepts: int = 200):
        """
        Initialize KG builder.

        Args:
            max_concepts: Maximum number of concepts to extract
        """
        self.max_concepts = max_concepts
        self.kg = KnowledgeGraph()

        # YAKE keyword extractor for concept extraction
        self.keyword_extractor = KeywordExtractor(
            lan="en",
            n=3,  # Max n-gram size
            dedupLim=0.7,  # Deduplication threshold
            top=20,  # Top keywords per document
            features=None,
        )

        # Common biology prerequisite patterns
        self.prereq_patterns = [
            (r"before understanding (\w+)", "prereq"),
            (r"requires knowledge of (\w+)", "prereq"),
            (r"builds on (\w+)", "prereq"),
            (r"depends on (\w+)", "prereq"),
            (r"prerequisite.*?(\w+)", "prereq"),
        ]

    def extract_concepts_from_text(self, text: str, key_terms: List[str]) -> List[str]:
        """
        Extract concept names from text.

        Args:
            text: Text to extract from
            key_terms: Known key terms to prioritize

        Returns:
            List of concept names
        """
        concepts = set()

        # Add key terms (highest priority)
        for term in key_terms:
            term_clean = term.strip().title()
            if term_clean:
                concepts.add(term_clean)

        # Extract keywords using YAKE
        try:
            keywords = self.keyword_extractor.extract_keywords(text)
            for keyword, score in keywords:
                # Filter: only accept biological terms (heuristic)
                keyword_clean = keyword.title().strip()
                if (
                    len(keyword_clean.split()) <= 3  # Max 3 words
                    and len(keyword_clean) >= 4  # Min 4 chars
                    and not keyword_clean[0].isdigit()  # Not starting with number
                ):
                    concepts.add(keyword_clean)
        except Exception as e:
            logger.warning(f"YAKE extraction failed: {e}")

        return list(concepts)

    def build_from_records(self, records: List[Dict]) -> KnowledgeGraph:
        """
        Build knowledge graph from normalized data records.

        Args:
            records: List of normalized text records

        Returns:
            Constructed KnowledgeGraph
        """
        logger.info(f"Building KG from {len(records)} records")

        # Group records by module
        modules_data = {}
        for record in records:
            module_id = record["module_id"]
            if module_id not in modules_data:
                modules_data[module_id] = {
                    "title": record["module_title"],
                    "key_terms": record["key_terms"],
                    "texts": [],
                    "sections": set(),
                }

            modules_data[module_id]["texts"].append(record["text"])
            modules_data[module_id]["sections"].add(record["section"])

        # Step 1: Create module nodes
        for module_id, data in modules_data.items():
            module_node = ModuleNode(
                module_id=module_id, title=data["title"], key_terms=data["key_terms"]
            )
            self.kg.modules[module_id] = module_node

        # Step 2: Extract concepts
        all_concepts = Counter()
        concept_to_modules = {}

        for module_id, data in modules_data.items():
            full_text = " ".join(data["texts"])
            concepts = self.extract_concepts_from_text(full_text, data["key_terms"])

            for concept in concepts:
                all_concepts[concept] += 1
                if concept not in concept_to_modules:
                    concept_to_modules[concept] = []
                concept_to_modules[concept].append(module_id)

        # Step 3: Keep top N concepts
        top_concepts = [c for c, _ in all_concepts.most_common(self.max_concepts)]
        logger.info(f"Extracted {len(top_concepts)} top concepts")

        # Step 4: Create concept nodes
        for concept_name in top_concepts:
            concept_node = ConceptNode(
                name=concept_name,
                frequency=all_concepts[concept_name],
                source_modules=concept_to_modules.get(concept_name, []),
                key_term=any(
                    concept_name.lower() in [kt.lower() for kt in modules_data[mid]["key_terms"]]
                    for mid in concept_to_modules.get(concept_name, [])
                ),
            )
            self.kg.add_concept(concept_node)

        # Step 5: Create COVERS relationships (Module -> Concept)
        for concept_name, module_ids in concept_to_modules.items():
            if concept_name in self.kg.concepts:
                for module_id in module_ids:
                    self.kg.add_relationship(
                        Relationship(
                            source=module_id,
                            target=concept_name,
                            type=RelationshipType.COVERS,
                            weight=1.0,
                            confidence=1.0,
                        )
                    )

        # Step 6: Mine concept relationships (co-occurrence based)
        self._mine_concept_relationships(records, top_concepts)

        # Step 7: Compute importance scores
        self._compute_importance_scores()

        logger.success(f"✓ KG built: {self.kg.get_stats()}")
        return self.kg

    def _mine_concept_relationships(self, records: List[Dict], concepts: List[str]):
        """
        Mine relationships between concepts based on co-occurrence.

        Args:
            records: Data records
            concepts: List of concept names
        """
        # Build co-occurrence matrix
        cooccurrence = Counter()

        for record in records:
            text_lower = record["text"].lower()

            # Find which concepts appear in this text
            present_concepts = [c for c in concepts if c.lower() in text_lower]

            # Create pairs
            for i, c1 in enumerate(present_concepts):
                for c2 in present_concepts[i + 1 :]:
                    # Canonical order
                    pair = tuple(sorted([c1, c2]))
                    cooccurrence[pair] += 1

        # Create RELATED relationships for strong co-occurrences
        threshold = 2  # Appear together at least 2 times
        for (c1, c2), count in cooccurrence.items():
            if count >= threshold:
                weight = min(count / 10.0, 1.0)  # Normalize to 0-1
                self.kg.add_relationship(
                    Relationship(
                        source=c1,
                        target=c2,
                        type=RelationshipType.RELATED,
                        weight=weight,
                        confidence=0.7,  # Medium confidence for co-occurrence
                    )
                )

        logger.info(f"Mined {len([r for r in self.kg.relationships if r.type == RelationshipType.RELATED])} RELATED relationships")

    def _compute_importance_scores(self):
        """Compute importance scores for concepts using PageRank-like algorithm."""
        # Build NetworkX graph for analysis
        G = nx.Graph()

        # Add nodes
        for concept_name in self.kg.concepts:
            G.add_node(concept_name)

        # Add edges
        for rel in self.kg.relationships:
            if rel.type == RelationshipType.RELATED:
                G.add_edge(rel.source, rel.target, weight=rel.weight)

        # Compute PageRank
        if len(G.nodes) > 0:
            pagerank = nx.pagerank(G, weight="weight")

            # Normalize to 0-1
            max_pr = max(pagerank.values()) if pagerank else 1.0
            for concept_name, pr_score in pagerank.items():
                self.kg.concepts[concept_name].importance_score = pr_score / max_pr

        logger.info("Computed importance scores using PageRank")

    def get_top_concepts(self, n: int = 20) -> List[Tuple[str, float]]:
        """
        Get top N concepts by importance.

        Args:
            n: Number of concepts to return

        Returns:
            List of (concept_name, importance_score) tuples
        """
        concepts_with_scores = [
            (name, node.importance_score) for name, node in self.kg.concepts.items()
        ]
        concepts_with_scores.sort(key=lambda x: x[1], reverse=True)
        return concepts_with_scores[:n]
