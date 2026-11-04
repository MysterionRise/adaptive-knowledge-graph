"""
Knowledge Graph expansion for RAG.

This is the "secret sauce" - uses KG to expand queries with related concepts
for better retrieval. This is what differentiates us from vanilla RAG.

How it works:
- Concepts are extracted from the query with the ConceptExtractor ensemble
  (spaCy NER + YAKE spans resolved against the subject's concept names and
  aliases, #212), falling back to whole-word matching of the names and aliases
- Each extracted concept is expanded with its neighbours in the subject's
  graph, up to RAG_KG_EXPANSION_HOPS hops

A subject's concept lexicon (names and aliases) is cached per subject
(``get_known_concepts``) and passed to the shared extractor on each call, so
concurrent requests for different subjects never see each other's concepts.
"""

import threading
import time
from collections.abc import Set
from typing import Any, Literal

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter
from backend.app.nlp.lexicon import ConceptLexicon, Resolution, lexicon_for

# Concepts taken from one question at most
MAX_QUERY_CONCEPTS = 5


def resolved_term(
    surface: str,
    canonical: str | None,
    via: str,
    strategy: str,
    candidates: tuple[str, ...] = (),
) -> dict[str, Any]:
    """One entry of ``resolved_terms``: a span of the question and what it resolved to."""
    term: dict[str, Any] = {
        "surface": surface,
        "canonical": canonical,
        "via": via,
        "strategy": strategy,
        "status": "resolved" if canonical is not None else "ambiguous",
    }
    if canonical is None:
        term["candidates"] = list(candidates)
    return term


def _lexicon(concepts: Set[str]) -> ConceptLexicon:
    return concepts if isinstance(concepts, ConceptLexicon) else lexicon_for(frozenset(concepts))


class KGExpander:
    """Expands queries using knowledge graph relationships."""

    def __init__(
        self,
        max_hops: int | None = None,
        extraction_strategy: Literal["simple", "ensemble", "ner", "yake"] = "ensemble",
        subject_id: str | None = None,
        max_neighbours: int | None = None,
    ):
        """
        Initialize KG expander.

        Args:
            max_hops: Maximum hops in graph for expansion
            max_neighbours: Graph neighbours added to the keyword query
                (default RAG_KG_EXPANSION_MAX_NEIGHBOURS)
            extraction_strategy: Concept extraction strategy
                - "simple": Original substring matching
                - "ensemble": Multi-strategy extraction (NER + YAKE)
                - "ner": spaCy NER only
                - "yake": YAKE keyword extraction only
            subject_id: Subject identifier for multi-subject support
                (None = default_subject from config/subjects.yaml)
        """
        self.max_hops = max_hops or settings.rag_kg_expansion_hops
        self.max_neighbours = (
            settings.rag_kg_expansion_max_neighbours if max_neighbours is None else max_neighbours
        )
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

    def extract_concepts_from_query(self, query: str, all_concepts: Set[str]) -> list[str]:
        """
        Extract concept names from query.

        Uses multi-strategy extraction when available, falls back to whole-word matching.

        Args:
            query: User query text
            all_concepts: The subject's concepts: a ``ConceptLexicon`` (names and aliases,
                as ``get_known_concepts`` returns) or a set of names

        Returns:
            List of concept names found in query
        """
        return self.resolve_query(query, all_concepts)[0]

    def resolve_query(
        self, query: str, all_concepts: Set[str]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """The concepts a question names, and how each span resolved (``resolved_terms``).

        An ambiguous span (an alias of several concepts) is reported in the terms but is
        not a concept of the question.
        """
        if self.extraction_strategy == "simple":
            return self._resolve_simple(query, all_concepts)

        terms: list[dict[str, Any]] = []

        # Use enhanced concept extraction
        try:
            extractor = self.concept_extractor
            if extractor:
                # The extractor is shared by every subject: pass this subject's
                # concepts to the call instead of storing them on the extractor.
                matches = extractor.extract_concepts(
                    query,
                    strategy=self.extraction_strategy
                    if self.extraction_strategy in ("ner", "yake")
                    else "ensemble",
                    top_k=MAX_QUERY_CONCEPTS,
                    known_concepts=all_concepts,
                )
                terms = [
                    resolved_term(
                        m.original_text or m.name,
                        m.name if m.status == "resolved" else None,
                        m.via,
                        m.strategy,
                        m.candidates,
                    )
                    for m in matches
                ]
                found_concepts = [m.name for m in matches if m.status == "resolved"]

                if found_concepts:
                    logger.info(
                        f"Enhanced extraction ({self.extraction_strategy}): "
                        f"found {len(found_concepts)} concepts"
                    )
                    return found_concepts, terms

        except Exception as e:
            logger.warning(f"Enhanced extraction failed, using simple: {e}")

        # Fallback to simple extraction
        found, simple_terms = self._resolve_simple(query, all_concepts)
        return found, terms + simple_terms

    def _resolve_simple(
        self, query: str, all_concepts: Set[str]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Every concept name or alias in the question as whole words, longest first."""
        resolutions: list[Resolution] = _lexicon(all_concepts).find_in(query)
        found = [r.canonical for r in resolutions if r.canonical is not None]
        found = found[:MAX_QUERY_CONCEPTS]
        terms = [
            resolved_term(r.surface, r.canonical, r.via, "simple", r.candidates)
            for r in resolutions
            if r.canonical is None or r.canonical in found
        ]
        return found, terms

    def _extract_simple(self, query: str, all_concepts: Set[str]) -> list[str]:
        """Whole-word matching of the concept names and aliases (the fallback strategy).

        Longer (more specific) matches come first, and ties are broken by name, so the
        result does not depend on the set's iteration order, which differs per process.
        """
        return self._resolve_simple(query, all_concepts)[0]

    def expand_with_kg(self, concepts: list[str]) -> list[str]:
        """
        Expand concepts using KG relationships.

        Args:
            concepts: Initial concepts from query

        Returns:
            Expanded list of concepts
        """
        return self._expand_with_kg(concepts)[0]

    def _expand_with_kg(self, concepts: list[str]) -> tuple[list[str], int]:
        """Expand concepts; also return how many graph lookups failed (Neo4j errors).

        The order is reproducible: the query's concepts first, then each one's neighbours
        in the order Neo4j returns them (strongest link first, then importance and name). The
        joined terms are embedded for retrieval, so a set's per-process order here would
        make the same question retrieve differently after a restart.
        """
        if not self.neo4j_adapter:
            logger.warning("Neo4j not connected, cannot expand with KG")
            return concepts, len(concepts)

        expanded = dict.fromkeys(concepts)  # an ordered set
        failures = 0

        for concept in concepts:
            try:
                # Get neighboring concepts
                neighbors = self.neo4j_adapter.query_concept_neighbors(
                    concept, max_hops=self.max_hops
                )

                for neighbor in neighbors:
                    expanded.setdefault(neighbor["name"])

            except Exception as e:
                failures += 1
                logger.warning(f"Failed to expand concept '{concept}': {e}")
                continue

        logger.info(f"Expanded {len(concepts)} concepts to {len(expanded)} using KG")
        return list(expanded), failures

    def expand_query(self, query: str, all_concepts: Set[str]) -> dict:
        """
        Full query expansion pipeline.

        The expansion feeds the keyword (BM25) channel only; the kNN channel embeds the
        question itself (#282). Adding every neighbour to the embedded text pulled retrieval
        toward the same high-degree hub concepts on most questions, so by default only the
        concepts recognised in the question are used, and their graph neighbours are
        returned as ``related_concepts`` for display.

        Args:
            query: Original query
            all_concepts: Set of all known concepts

        Returns:
            Dict with original_query, extracted_concepts, expanded_concepts (the concepts
            the retrieval uses: the recognised ones plus at most ``max_neighbours``
            neighbours), related_concepts (their graph neighbours, in Neo4j's order),
            expanded_query (the keyword-channel text: the question plus expanded_concepts),
            resolved_terms (each span of the question and what it resolved to, #212),
            expansion_count and failed_lookups (graph lookups that raised)
        """
        # Extract concepts from query
        extracted, terms = self.resolve_query(query, all_concepts)

        # Look up their neighbours in the graph
        expanded, failed_lookups = self._expand_with_kg(extracted)
        recognised = set(extracted)
        neighbours = [concept for concept in expanded if concept not in recognised]
        used = list(extracted) + neighbours[: max(0, self.max_neighbours)]

        expanded_query = f"{query} {' '.join(used)}" if used else query

        return {
            "original_query": query,
            "extracted_concepts": extracted,
            "expanded_concepts": used,
            "related_concepts": neighbours,
            "resolved_terms": terms,
            "expanded_query": expanded_query,
            "expansion_count": len(used) - len(extracted),
            "failed_lookups": failed_lookups,
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


def get_concept_lexicon_from_neo4j(subject_id: str | None = None) -> ConceptLexicon:
    """A subject's concept names and stored aliases (empty if Neo4j is unavailable)."""
    try:
        return ConceptLexicon(get_neo4j_adapter(subject_id).get_concept_aliases())
    except Exception as e:
        logger.error(f"Failed to load concepts from Neo4j: {e}")
        return ConceptLexicon({})


# Concept names change only when a subject is re-seeded, so they are cached per
# subject instead of being loaded from Neo4j on every question.
KNOWN_CONCEPTS_CACHE_TTL_SECONDS = 300.0
_known_concepts_cache: dict[str, tuple[float, ConceptLexicon]] = {}
_known_concepts_locks: dict[str, threading.Lock] = {}
_known_concepts_registry_lock = threading.Lock()


def get_known_concepts(subject_id: str | None = None) -> ConceptLexicon:
    """
    Get a subject's concept lexicon, cached for KNOWN_CONCEPTS_CACHE_TTL_SECONDS.

    The lexicon is the set of concept names and also resolves their aliases (#212).

    Each subject has its own entry and its own load lock, so concurrent requests
    for one subject load it once and other subjects are not blocked. An empty
    result (Neo4j unavailable or the subject not seeded yet) is not cached, so
    the next request tries again.

    Args:
        subject_id: Subject identifier (None = default_subject from config/subjects.yaml)

    Returns:
        The concept lexicon (the same object until the entry expires)
    """
    resolved_id = get_subject(subject_id).id

    cached = _known_concepts_cache.get(resolved_id)
    if cached is not None and time.monotonic() - cached[0] < KNOWN_CONCEPTS_CACHE_TTL_SECONDS:
        return cached[1]

    with _known_concepts_registry_lock:
        lock = _known_concepts_locks.setdefault(resolved_id, threading.Lock())

    with lock:
        # Another request may have loaded the subject while this one waited.
        cached = _known_concepts_cache.get(resolved_id)
        if cached is not None and time.monotonic() - cached[0] < KNOWN_CONCEPTS_CACHE_TTL_SECONDS:
            return cached[1]

        concepts = get_concept_lexicon_from_neo4j(resolved_id)
        if concepts:
            _known_concepts_cache[resolved_id] = (time.monotonic(), concepts)
            logger.info(
                f"Cached {len(concepts)} concept names and {concepts.alias_count} aliases "
                f"for subject {resolved_id}"
            )
        return concepts


def clear_known_concepts_cache() -> None:
    """Clear cached concept names (used in tests and after reseeding)."""
    _known_concepts_cache.clear()


def clear_kg_expanders() -> None:
    """Clear all cached KG expanders."""
    with _kg_expanders_lock:
        for expander in _kg_expanders.values():
            expander.close()
        _kg_expanders.clear()
    logger.info("Cleared all cached KG expanders")
