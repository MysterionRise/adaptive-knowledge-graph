"""
Multi-strategy concept extraction for enhanced RAG.

Replaces simple substring matching with semantic/NER-based extraction.
Supports multiple strategies:
- ner: spaCy named entity recognition
- embedding: similarity to known concepts
- yake: keyword extraction (original approach)
- fulltext: Neo4j fulltext search
- ensemble: combine all strategies
"""

from dataclasses import dataclass
from typing import Literal

import yake
from loguru import logger


@dataclass
class ConceptMatch:
    """A matched concept with metadata."""

    name: str
    score: float  # Confidence/relevance score (0-1)
    strategy: str  # Which strategy found this
    original_text: str | None = None  # Original text span that matched


class ConceptExtractor:
    """
    Multi-strategy concept extraction.

    Extracts educational concepts from text using various NLP strategies
    for better coverage than simple substring matching.
    """

    def __init__(
        self,
        known_concepts: set[str] | None = None,
        embedding_model=None,
    ):
        """
        Initialize concept extractor.

        Args:
            known_concepts: Set of known concept names for matching
            embedding_model: Embedding model for similarity-based extraction
        """
        self.known_concepts = known_concepts or set()
        self._embedding_model = embedding_model
        self._spacy_nlp: object | None = None
        self._yake_extractor = None
        self._concept_embeddings: dict[str, list[float]] = {}

    @property
    def spacy_nlp(self):
        """Lazy-load spaCy model."""
        if self._spacy_nlp is None:
            try:
                import spacy

                # Try to load the science-focused model, fall back to general
                try:
                    self._spacy_nlp = spacy.load("en_core_sci_sm")
                except OSError:
                    self._spacy_nlp = spacy.load("en_core_web_sm")
                    logger.info("Using en_core_web_sm (install en_core_sci_sm for better results)")
            except Exception as e:
                logger.warning(f"spaCy not available: {e}")
                self._spacy_nlp = None
        return self._spacy_nlp

    @property
    def yake_extractor(self):
        """Lazy-load YAKE keyword extractor."""
        if self._yake_extractor is None:
            self._yake_extractor = yake.KeywordExtractor(
                lan="en",
                n=3,  # Max ngram size
                dedupLim=0.9,
                dedupFunc="seqm",
                windowsSize=1,
                top=20,
            )
        return self._yake_extractor

    @property
    def embedding_model(self):
        """Lazy-load embedding model."""
        if self._embedding_model is None:
            from backend.app.nlp.embeddings import get_embedding_model

            self._embedding_model = get_embedding_model()
        return self._embedding_model

    def set_known_concepts(self, concepts: set[str]):
        """Update the set of known concepts."""
        self.known_concepts = concepts
        # Clear cached embeddings
        self._concept_embeddings = {}

    def extract_concepts(
        self,
        text: str,
        strategy: Literal["ner", "embedding", "yake", "fulltext", "ensemble"] = "ensemble",
        top_k: int = 10,
    ) -> list[ConceptMatch]:
        """
        Extract concepts from text using specified strategy.

        Args:
            text: Input text to extract concepts from
            strategy: Extraction strategy to use
            top_k: Maximum number of concepts to return

        Returns:
            List of ConceptMatch objects sorted by score
        """
        if not text:
            return []

        if strategy == "ner":
            matches = self._extract_ner(text)
        elif strategy == "embedding":
            matches = self._extract_embedding(text)
        elif strategy == "yake":
            matches = self._extract_yake(text)
        elif strategy == "fulltext":
            matches = self._extract_fulltext(text)
        elif strategy == "ensemble":
            matches = self._extract_ensemble(text)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Sort by score and limit
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_k]

    def _extract_ner(self, text: str) -> list[ConceptMatch]:
        """Extract concepts using spaCy NER."""
        matches: list[ConceptMatch] = []

        if self.spacy_nlp is None:
            return matches

        doc = self.spacy_nlp(text)

        # Extract named entities
        for ent in doc.ents:
            # Filter to likely educational entities
            if ent.label_ in ("ORG", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"):
                continue

            # Check if entity matches a known concept
            ent_text = ent.text.strip()
            matched_concept = self._match_to_known(ent_text)

            if matched_concept:
                matches.append(
                    ConceptMatch(
                        name=matched_concept,
                        score=0.8,  # NER match confidence
                        strategy="ner",
                        original_text=ent_text,
                    )
                )

        # Also extract noun chunks as potential concepts
        for chunk in doc.noun_chunks:
            chunk_text = chunk.text.strip()
            if len(chunk_text) < 3:
                continue

            matched_concept = self._match_to_known(chunk_text)
            if matched_concept:
                matches.append(
                    ConceptMatch(
                        name=matched_concept,
                        score=0.6,  # Noun chunk confidence
                        strategy="ner",
                        original_text=chunk_text,
                    )
                )

        return self._deduplicate(matches)

    def _extract_yake(self, text: str) -> list[ConceptMatch]:
        """Extract concepts using YAKE keyword extraction."""
        matches = []

        try:
            keywords = self.yake_extractor.extract_keywords(text)

            for keyword, yake_score in keywords:
                # YAKE scores are lower = better, normalize to 0-1
                normalized_score = 1.0 / (1.0 + yake_score)

                # Check if keyword matches a known concept
                matched_concept = self._match_to_known(keyword)
                if matched_concept:
                    matches.append(
                        ConceptMatch(
                            name=matched_concept,
                            score=normalized_score,
                            strategy="yake",
                            original_text=keyword,
                        )
                    )

        except Exception as e:
            logger.warning(f"YAKE extraction failed: {e}")

        return matches

    def _extract_embedding(
        self, text: str, similarity_threshold: float = 0.5
    ) -> list[ConceptMatch]:
        """Extract concepts using embedding similarity."""
        matches: list[ConceptMatch] = []

        if not self.known_concepts:
            return matches

        try:
            # Ensure concept embeddings are cached
            self._ensure_concept_embeddings()

            # Encode query text
            query_embedding = self.embedding_model.encode_query(text)

            # Compute similarity to all known concepts
            import numpy as np

            query_vec = np.array(query_embedding)

            for concept_name, concept_embedding in self._concept_embeddings.items():
                concept_vec = np.array(concept_embedding)

                # Cosine similarity
                similarity = np.dot(query_vec, concept_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(concept_vec) + 1e-8
                )

                if similarity >= similarity_threshold:
                    matches.append(
                        ConceptMatch(
                            name=concept_name,
                            score=float(similarity),
                            strategy="embedding",
                            original_text=None,
                        )
                    )

        except Exception as e:
            logger.warning(f"Embedding extraction failed: {e}")

        return matches

    def _extract_fulltext(self, text: str) -> list[ConceptMatch]:
        """Extract concepts using Neo4j fulltext search."""
        matches = []

        try:
            from backend.app.kg.neo4j_adapter import Neo4jAdapter

            adapter = Neo4jAdapter()
            adapter.connect()

            # Extract potential keywords from text for fulltext search
            keywords = self._get_search_terms(text)

            for keyword in keywords[:10]:  # Limit search terms
                results = adapter.fulltext_concept_search(keyword, limit=5)

                for r in results:
                    if r.get("score", 0) > 0.5:  # Minimum relevance
                        matches.append(
                            ConceptMatch(
                                name=r["name"],
                                score=min(r["score"] / 10.0, 1.0),  # Normalize score
                                strategy="fulltext",
                                original_text=keyword,
                            )
                        )

            adapter.close()

        except Exception as e:
            logger.warning(f"Fulltext extraction failed: {e}")

        return self._deduplicate(matches)

    def _extract_ensemble(self, text: str) -> list[ConceptMatch]:
        """Combine all extraction strategies with score fusion."""
        all_matches: dict[str, list[ConceptMatch]] = {}

        # Run all strategies
        for strategy_fn in [self._extract_ner, self._extract_yake]:
            try:
                for match in strategy_fn(text):
                    if match.name not in all_matches:
                        all_matches[match.name] = []
                    all_matches[match.name].append(match)
            except Exception as e:
                logger.warning(f"Strategy failed: {e}")

        # Fuse scores for concepts found by multiple strategies
        fused_matches = []
        for concept_name, matches_list in all_matches.items():
            # Boost score for concepts found by multiple strategies
            strategy_count = len({m.strategy for m in matches_list})
            max_score = max(m.score for m in matches_list)
            boosted_score = min(1.0, max_score * (1 + 0.2 * (strategy_count - 1)))

            fused_matches.append(
                ConceptMatch(
                    name=concept_name,
                    score=boosted_score,
                    strategy="ensemble",
                    original_text=matches_list[0].original_text,
                )
            )

        return fused_matches

    def _match_to_known(self, text: str) -> str | None:
        """Match text to a known concept (case-insensitive)."""
        text_lower = text.lower()

        for concept in self.known_concepts:
            if concept.lower() == text_lower:
                return concept
            # Also check if text contains the concept
            if concept.lower() in text_lower or text_lower in concept.lower():
                return concept

        return None

    def _ensure_concept_embeddings(self):
        """Ensure concept embeddings are cached."""
        if self._concept_embeddings:
            return

        if not self.known_concepts:
            return

        # Batch encode all concepts
        concept_list = list(self.known_concepts)
        embeddings = self.embedding_model.encode_batch(concept_list)

        self._concept_embeddings = dict(zip(concept_list, embeddings, strict=False))
        logger.info(f"Cached embeddings for {len(self._concept_embeddings)} concepts")

    def _get_search_terms(self, text: str) -> list[str]:
        """Extract search terms from text for fulltext queries."""
        # Use YAKE to get keywords
        try:
            keywords = self.yake_extractor.extract_keywords(text)
            return [kw for kw, _ in keywords]
        except Exception:
            # Fallback to simple tokenization
            words = text.split()
            return [w for w in words if len(w) > 3]

    def _deduplicate(self, matches: list[ConceptMatch]) -> list[ConceptMatch]:
        """Remove duplicate matches, keeping highest score."""
        seen: dict[str, ConceptMatch] = {}
        for match in matches:
            if match.name not in seen or match.score > seen[match.name].score:
                seen[match.name] = match
        return list(seen.values())


# Global singleton
_concept_extractor: ConceptExtractor | None = None


def get_concept_extractor(known_concepts: set[str] | None = None) -> ConceptExtractor:
    """
    Get or create global concept extractor instance.

    Args:
        known_concepts: Set of known concepts (updates extractor if provided)

    Returns:
        ConceptExtractor instance
    """
    global _concept_extractor

    if _concept_extractor is None:
        _concept_extractor = ConceptExtractor(known_concepts=known_concepts)
    elif known_concepts:
        _concept_extractor.set_known_concepts(known_concepts)

    return _concept_extractor
