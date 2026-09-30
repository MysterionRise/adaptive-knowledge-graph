"""
Multi-strategy concept extraction for enhanced RAG.

Replaces simple substring matching with semantic/NER-based extraction.
Supports multiple strategies:
- ner: spaCy named entities and noun chunks (skipped when no spaCy model is installed)
- embedding: similarity to known concepts
- yake: keyword extraction (original approach)
- fulltext: Neo4j fulltext search
- ensemble: NER + YAKE with score fusion (the embedding and fulltext strategies
  are not part of the ensemble; request them explicitly)

Every strategy drops markup/structural stop concepts ("Data-Type", "Review
Questions", …) using the shared vocabulary in ``backend.app.kg.stopwords``.
"""

import re
from dataclasses import dataclass
from typing import Literal

import yake
from loguru import logger

from backend.app.kg.stopwords import is_stop_concept

# spaCy entity labels that never name a concept (dates, amounts, ordinals, …).
_NON_CONCEPT_ENTITY_LABELS = frozenset(
    {"CARDINAL", "DATE", "MONEY", "ORDINAL", "PERCENT", "QUANTITY", "TIME"}
)


def _contains_phrase(text: str, phrase: str) -> bool:
    """True when ``phrase`` occurs in ``text`` as whole words."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


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
        subject_id: str | None = None,
    ):
        """
        Initialize concept extractor.

        Args:
            known_concepts: Set of known concept names for matching (stop concepts
                such as "Summary" or "Data-Type" are ignored)
            embedding_model: Embedding model for similarity-based extraction
            subject_id: Subject whose Neo4j fulltext index the fulltext strategy
                queries (None = the default subject)
        """
        self.known_concepts = self._filter_known(known_concepts or set())
        self.subject_id = subject_id
        self._embedding_model = embedding_model
        self._spacy_nlp: object | None = None
        self._spacy_unavailable = False
        self._yake_extractor = None
        self._concept_embeddings: dict[str, list[float]] = {}

    @staticmethod
    def _filter_known(concepts: set[str]) -> set[str]:
        """Drop markup/structural stop concepts from a known-concept set."""
        return {concept for concept in concepts if not is_stop_concept(concept)}

    @property
    def spacy_nlp(self):
        """
        Lazy-load a spaCy model, or None when spaCy or its models are unavailable.

        Tries ``en_core_sci_sm`` then ``en_core_web_sm``. A failed load is remembered,
        so the NER strategy degrades to returning no matches without retrying (and
        warning) on every call.
        """
        if self._spacy_nlp is None and not self._spacy_unavailable:
            try:
                import spacy

                # Try to load the science-focused model, fall back to general
                try:
                    self._spacy_nlp = spacy.load("en_core_sci_sm")
                except OSError:
                    self._spacy_nlp = spacy.load("en_core_web_sm")
                    logger.info("Using en_core_web_sm (install en_core_sci_sm for better results)")
            except Exception as e:
                logger.warning(f"spaCy not available, NER concept extraction disabled: {e}")
                self._spacy_nlp = None
                self._spacy_unavailable = True
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
        """Update the set of known concepts (stop concepts are ignored)."""
        self.known_concepts = self._filter_known(concepts)
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

        # Drop stop concepts (e.g. a fulltext hit on "Summary"), then sort and limit
        matches = [match for match in matches if not is_stop_concept(match.name)]
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
            # Dates, amounts and ordinals never name a concept; events ("the Civil
            # War") and laws ("the Stamp Act") often do.
            if ent.label_ in _NON_CONCEPT_ENTITY_LABELS:
                continue

            # Check if entity matches a known concept
            ent_text = ent.text.strip()
            if is_stop_concept(ent_text):
                continue
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
            if len(chunk_text) < 3 or is_stop_concept(chunk_text):
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
                if is_stop_concept(keyword):
                    continue
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
        """Extract concepts using the subject's Neo4j fulltext index."""
        matches = []

        try:
            from backend.app.kg.neo4j_adapter import get_neo4j_adapter

            # Shared, subject-prefixed adapter (labels and fulltext index name);
            # it belongs to the adapter registry, so it is not closed here.
            adapter = get_neo4j_adapter(self.subject_id)

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

        except Exception as e:
            logger.warning(f"Fulltext extraction failed: {e}")

        return self._deduplicate(matches)

    def _extract_ensemble(self, text: str) -> list[ConceptMatch]:
        """
        Fuse the NER and YAKE strategies.

        A concept found by both gets a 20% score boost. The embedding and fulltext
        strategies are not included (they need a model or a database).
        """
        all_matches: dict[str, list[ConceptMatch]] = {}

        # Run the NER and YAKE strategies
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
        """
        Match a text span to a known concept (case-insensitive, whole words).

        An exact match wins; otherwise the longest known concept contained in the
        span ("the Stamp Act of 1765" -> "Stamp Act"), then the shortest known
        concept containing the span. Matching is on word boundaries, so "act" does
        not match inside "fact", and ties are broken alphabetically so the result
        does not depend on set iteration order.
        """
        text_lower = text.lower().strip()
        if not text_lower:
            return None

        contained: list[str] = []
        containing: list[str] = []
        for concept in self.known_concepts:
            concept_lower = concept.lower()
            if concept_lower == text_lower:
                return concept
            if _contains_phrase(text_lower, concept_lower):
                contained.append(concept)
            elif _contains_phrase(concept_lower, text_lower):
                containing.append(concept)

        if contained:
            return min(contained, key=lambda c: (-len(c), c))
        if containing:
            return min(containing, key=lambda c: (len(c), c))
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
