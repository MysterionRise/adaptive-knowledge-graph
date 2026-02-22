"""
Knowledge Graph builder.

Extracts concepts from text and builds the knowledge graph structure.
Uses NLP techniques for concept extraction and relationship mining.
"""

import re
from collections import Counter

import networkx as nx
from loguru import logger
from yake import KeywordExtractor

from backend.app.kg.schema import (
    ConceptNode,
    KnowledgeGraph,
    ModuleNode,
    Relationship,
    RelationshipType,
)

# Structural/metadata terms from OpenStax HTML that are not educational concepts
STOP_CONCEPTS: set[str] = {
    "data-type",
    "cnx",
    "cnx-pi",
    "review questions",
    "critical thinking",
    "critical thinking questions",
    "self-check questions",
    "thinking questions",
    "key terms",
    "summary",
    "references",
    "title",
    "class",
    "section",
    "chapter",
    "introduction",
    "conclusion",
    "learning objectives",
    "figure",
    "table",
    "link",
    "image",
    "eoc",
    "eob",
    "data type",
    "os-teacher",
    "os-embed",
    "check-understanding",
    "module",
    "content",
    "term",
    "page",
    "note",
    "exercise",
    "problem",
    "solution",
    "abstract",
    "metadata",
    "glossary",
    "index",
    "appendix",
    "preface",
    "answer key",
    "suggested reading",
    "further reading",
    "review",
    "practice",
    "end-of-chapter",
    "end-of-module",
}

# Regex patterns for extracting prerequisite relationships from educational text
PREREQ_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"requires? (?:an? )?understanding of (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"builds? (?:on|upon) (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"prerequisite.{0,20}(.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"before (?:studying|learning|understanding) (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"assumes? (?:knowledge|familiarity) (?:of|with) (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(
        r"(?:following|after) .{0,30}(?:chapter|section|module) on (.+?)(?:\.|,|;)",
        re.IGNORECASE,
    ),
    re.compile(r"led to (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"resulted in (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"paved the way for (.+?)(?:\.|,|;)", re.IGNORECASE),
    re.compile(r"was a precursor to (.+?)(?:\.|,|;)", re.IGNORECASE),
]


def _is_stop_concept(name: str) -> bool:
    """Check if a concept name is a structural/metadata term that should be filtered."""
    return name.lower().strip() in STOP_CONCEPTS


def _deduplicate_concepts(concepts: list[str]) -> list[str]:
    """
    Semantic deduplication via substring containment.

    If concept A is a substring of concept B and both exist, drop A.
    E.g., "United" + "United States" -> keep only "United States".
    """
    # Sort by length descending so longer (more specific) concepts come first
    sorted_concepts = sorted(concepts, key=len, reverse=True)
    kept: list[str] = []

    for concept in sorted_concepts:
        concept_lower = concept.lower()
        # Check if this concept is a substring of any already-kept concept
        is_substring = any(concept_lower in k.lower() and concept_lower != k.lower() for k in kept)
        if not is_substring:
            kept.append(concept)

    return kept


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

    def extract_concepts_from_text(self, text: str, key_terms: list[str]) -> list[str]:
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
            if term_clean and len(term_clean) >= 3 and not _is_stop_concept(term_clean):
                concepts.add(term_clean)

        # Extract keywords using YAKE
        try:
            keywords = self.keyword_extractor.extract_keywords(text)
            for keyword, _ in keywords:
                # Filter: General heuristics for meaningful terms
                keyword_clean = keyword.title().strip()
                if (
                    len(keyword_clean.split()) <= 4  # Max 4 words
                    and len(keyword_clean) >= 3  # Min 3 chars
                    and not _is_stop_concept(keyword_clean)  # Not a stop concept
                ):
                    concepts.add(keyword_clean)
        except Exception as e:
            logger.warning(f"YAKE extraction failed: {e}")

        # Deduplicate: remove substrings of longer concepts
        return _deduplicate_concepts(list(concepts))

    def build_from_records(self, records: list[dict]) -> KnowledgeGraph:
        """
        Build knowledge graph from normalized data records.

        Args:
            records: List of normalized text records

        Returns:
            Constructed KnowledgeGraph
        """
        logger.info(f"Building KG from {len(records)} records")

        # Group records by module
        modules_data: dict[str, dict] = {}
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
        all_concepts: Counter[str] = Counter()
        concept_to_modules: dict[str, list[str]] = {}

        for module_id, data in modules_data.items():
            full_text = " ".join(data["texts"])
            concepts = self.extract_concepts_from_text(full_text, data["key_terms"])

            for concept in concepts:
                all_concepts[concept] += 1
                if concept not in concept_to_modules:
                    concept_to_modules[concept] = []
                concept_to_modules[concept].append(module_id)

        # Step 3: Deduplicate across all modules before selecting top N
        all_concept_names = _deduplicate_concepts(list(all_concepts.keys()))
        # Re-rank after dedup, keeping original counts
        deduped_counts: Counter[str] = Counter()
        for name in all_concept_names:
            deduped_counts[name] = all_concepts[name]

        top_concepts = [c for c, _ in deduped_counts.most_common(self.max_concepts)]
        logger.info(f"Extracted {len(top_concepts)} top concepts (after dedup and filtering)")

        # Step 4: Create concept nodes
        for concept_name in top_concepts:
            concept_node = ConceptNode(
                name=concept_name,
                definition=None,
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
                            evidence=None,
                        )
                    )

        # Step 6: Mine concept relationships (co-occurrence based, threshold=5)
        self._mine_concept_relationships(records, top_concepts)

        # Step 7: Extract prerequisite relationships from text
        self._extract_prereq_relationships(records, top_concepts)

        # Step 8: Compute importance scores
        self._compute_importance_scores()

        logger.success(f"✓ KG built: {self.kg.get_stats()}")
        return self.kg

    def _mine_concept_relationships(self, records: list[dict], concepts: list[str]):
        """
        Mine relationships between concepts based on co-occurrence.

        Args:
            records: Data records
            concepts: List of concept names
        """
        # Build co-occurrence matrix
        cooccurrence: Counter[tuple[str, ...]] = Counter()

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
        threshold = 5  # Appear together at least 5 times (raised from 2)
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
                        evidence=None,
                    )
                )

        related_count = len(
            [r for r in self.kg.relationships if r.type == RelationshipType.RELATED]
        )
        logger.info(f"Mined {related_count} RELATED relationships (threshold={threshold})")

    def _extract_prereq_relationships(self, records: list[dict], concepts: list[str]):
        """
        Extract prerequisite relationships from text using regex patterns.

        Looks for language like "requires understanding of X", "builds on Y",
        "led to Z" and creates PREREQ edges when matched concepts are found.

        Args:
            records: Data records
            concepts: List of concept names
        """
        concept_lookup = {c.lower(): c for c in concepts}
        prereq_count = 0

        for record in records:
            text = record["text"]

            for pattern in PREREQ_PATTERNS:
                for match in pattern.finditer(text):
                    matched_text = match.group(1).strip().lower()

                    # Try to find a matching concept
                    target_concept = self._match_text_to_concept(matched_text, concept_lookup)
                    if not target_concept:
                        continue

                    # Find the source concept: look for concepts mentioned earlier in the text
                    text_before = text[: match.start()].lower()
                    source_concept = None
                    for c_lower, c_name in concept_lookup.items():
                        if c_lower in text_before and c_name != target_concept:
                            source_concept = c_name
                            break

                    if source_concept and source_concept != target_concept:
                        self.kg.add_relationship(
                            Relationship(
                                source=source_concept,
                                target=target_concept,
                                type=RelationshipType.PREREQ,
                                weight=0.8,
                                confidence=0.6,
                                evidence=text[max(0, match.start() - 50) : match.end() + 20],
                            )
                        )
                        prereq_count += 1

        logger.info(f"Extracted {prereq_count} PREREQ relationships from text patterns")

    def _match_text_to_concept(self, text: str, concept_lookup: dict[str, str]) -> str | None:
        """Match extracted text to a known concept."""
        # Exact match
        if text in concept_lookup:
            return concept_lookup[text]

        # Check if any concept is contained in the matched text
        for c_lower, c_name in concept_lookup.items():
            if c_lower in text or text in c_lower:
                return c_name

        return None

    def _compute_importance_scores(self):
        """Compute importance scores for concepts using PageRank-like algorithm."""
        # Build NetworkX graph for analysis
        G = nx.Graph()

        # Add nodes
        for concept_name in self.kg.concepts:
            G.add_node(concept_name)

        # Add edges (include both RELATED and PREREQ)
        for rel in self.kg.relationships:
            if rel.type in (RelationshipType.RELATED, RelationshipType.PREREQ):
                G.add_edge(rel.source, rel.target, weight=rel.weight)

        # Compute PageRank
        if len(G.nodes) > 0:
            pagerank = nx.pagerank(G, weight="weight")

            # Normalize to 0-1
            max_pr = max(pagerank.values()) if pagerank else 1.0
            for concept_name, pr_score in pagerank.items():
                self.kg.concepts[concept_name].importance_score = pr_score / max_pr

        logger.info("Computed importance scores using PageRank")

    def get_top_concepts(self, n: int = 20) -> list[tuple[str, float]]:
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
