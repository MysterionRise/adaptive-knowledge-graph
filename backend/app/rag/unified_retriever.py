"""
Unified retriever combining Neo4j vector search with graph expansion.

This is the enterprise RAG pattern: single Cypher query that performs
vector similarity search AND graph traversal for context enrichment.
"""

from loguru import logger

from backend.app.core.settings import settings
from backend.app.kg.neo4j_adapter import Neo4jAdapter
from backend.app.nlp.embeddings import get_embedding_model
from backend.app.rag.retriever import OpenSearchRetriever


class UnifiedRetriever:
    """
    Single query combining vector search + graph expansion.

    Supports three modes:
    - neo4j: Pure Neo4j vector index search
    - opensearch: Original OpenSearch kNN (fallback)
    - hybrid: Query both, merge and deduplicate results
    """

    def __init__(
        self,
        backend: str | None = None,
        neo4j_adapter: Neo4jAdapter | None = None,
    ):
        """
        Initialize unified retriever.

        Args:
            backend: "neo4j", "opensearch", or "hybrid" (defaults to settings)
            neo4j_adapter: Neo4j adapter instance (creates new if not provided)
        """
        self.backend = backend or settings.vector_backend
        self._neo4j_adapter = neo4j_adapter
        self._owns_neo4j = neo4j_adapter is None
        self._opensearch_retriever: OpenSearchRetriever | None = None
        self._embedding_model: object | None = None

    @property
    def neo4j_adapter(self) -> Neo4jAdapter:
        """Lazy-load Neo4j adapter."""
        if self._neo4j_adapter is None:
            self._neo4j_adapter = Neo4jAdapter()
            self._neo4j_adapter.connect()
        return self._neo4j_adapter

    @property
    def opensearch_retriever(self) -> OpenSearchRetriever:
        """Lazy-load OpenSearch retriever."""
        if self._opensearch_retriever is None:
            self._opensearch_retriever = OpenSearchRetriever(
                username=settings.opensearch_user,
                password=settings.opensearch_password,
            )
            self._opensearch_retriever.connect()
        return self._opensearch_retriever

    @property
    def embedding_model(self):
        """Lazy-load embedding model."""
        if self._embedding_model is None:
            self._embedding_model = get_embedding_model()
        return self._embedding_model

    def close(self):
        """Close connections."""
        if self._owns_neo4j and self._neo4j_adapter is not None:
            self._neo4j_adapter.close()
            self._neo4j_adapter = None

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        include_graph_context: bool = True,
        window_size: int = 1,
    ) -> list[dict]:
        """
        Retrieve relevant chunks with optional graph context.

        Args:
            query: Query text
            top_k: Number of results to return
            include_graph_context: Expand results with NEXT and concept relations
            window_size: Chunks before/after for window expansion

        Returns:
            List of retrieved chunks with scores and context
        """
        top_k = top_k or settings.rag_retrieval_top_k

        if self.backend == "neo4j":
            return self._retrieve_neo4j(query, top_k, include_graph_context, window_size)
        elif self.backend == "hybrid":
            return self._retrieve_hybrid(query, top_k, include_graph_context, window_size)
        else:
            # Default to OpenSearch
            return self._retrieve_opensearch(query, top_k)

    def _retrieve_opensearch(self, query: str, top_k: int) -> list[dict]:
        """Retrieve using OpenSearch (original behavior)."""
        return self.opensearch_retriever.retrieve(query, top_k=top_k)

    def _retrieve_neo4j(
        self,
        query: str,
        top_k: int,
        include_graph_context: bool,
        window_size: int,
    ) -> list[dict]:
        """
        Retrieve using Neo4j native vector search.

        Optionally includes graph context via NEXT traversal and concept expansion.
        """
        # Encode query to embedding
        query_embedding = self.embedding_model.encode_query(query)

        # Vector search on Neo4j
        results = self.neo4j_adapter.vector_search(
            query_embedding=query_embedding,
            top_k=top_k,
            index_name=settings.neo4j_vector_index_name,
        )

        if not results:
            logger.warning(f"No results from Neo4j vector search for: {query[:50]}...")
            return []

        if include_graph_context and window_size > 0:
            # Expand with window context
            results = self._expand_with_window(results, window_size)

        logger.info(f"Neo4j vector search returned {len(results)} chunks")
        return results

    def _retrieve_hybrid(
        self,
        query: str,
        top_k: int,
        include_graph_context: bool,
        window_size: int,
    ) -> list[dict]:
        """
        Retrieve from both Neo4j and OpenSearch, merge results.

        Uses reciprocal rank fusion for score combination.
        """
        # Get results from both backends
        neo4j_results = self._retrieve_neo4j(
            query, top_k, include_graph_context=False, window_size=0
        )
        opensearch_results = self._retrieve_opensearch(query, top_k)

        # Merge using reciprocal rank fusion
        merged = self._reciprocal_rank_fusion(
            [neo4j_results, opensearch_results],
            k=60,  # RRF constant
        )

        # Take top_k after fusion
        merged = merged[:top_k]

        # Optionally expand with graph context
        if include_graph_context and window_size > 0:
            merged = self._expand_with_window(merged, window_size)

        logger.info(
            f"Hybrid retrieval: Neo4j={len(neo4j_results)}, "
            f"OpenSearch={len(opensearch_results)}, merged={len(merged)}"
        )

        return merged

    def _expand_with_window(self, chunks: list[dict], window_size: int) -> list[dict]:
        """Expand chunks with NEXT relationship context."""
        seen_ids = set()
        expanded = []

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id") or chunk.get("id")
            if not chunk_id or chunk_id in seen_ids:
                continue

            seen_ids.add(chunk_id)

            # Get window context
            window_chunks = self.neo4j_adapter.get_chunk_window(
                chunk_id=chunk_id,
                window_before=window_size,
                window_after=window_size,
            )

            for wc in window_chunks:
                wc_id = wc.get("chunk_id")
                if wc_id not in seen_ids:
                    seen_ids.add(wc_id)
                    wc["is_window_context"] = wc_id != chunk_id
                    wc["original_score"] = chunk.get("score", 0.0)
                    expanded.append(wc)

        # Sort by module then chunk_index
        expanded.sort(key=lambda c: (c.get("module_id", ""), c.get("chunk_index", 0)))

        return expanded

    def _reciprocal_rank_fusion(
        self,
        result_lists: list[list[dict]],
        k: int = 60,
    ) -> list[dict]:
        """
        Combine multiple ranked result lists using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank)) across all lists

        Args:
            result_lists: List of ranked result lists
            k: RRF constant (default 60)

        Returns:
            Merged and re-ranked results
        """
        scores: dict[str, float] = {}
        chunk_data: dict[str, dict] = {}

        for results in result_lists:
            for rank, chunk in enumerate(results, start=1):
                chunk_id = chunk.get("chunk_id") or chunk.get("id") or str(hash(chunk["text"][:50]))

                # Accumulate RRF score
                rrf_score = 1.0 / (k + rank)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + rrf_score

                # Store chunk data (prefer first occurrence)
                if chunk_id not in chunk_data:
                    chunk_data[chunk_id] = chunk

        # Sort by RRF score and return
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        merged = []
        for chunk_id in sorted_ids:
            chunk = chunk_data[chunk_id].copy()
            chunk["rrf_score"] = scores[chunk_id]
            merged.append(chunk)

        return merged

    def retrieve_with_graph_context(
        self,
        query: str,
        top_k: int = 10,
        expand_concepts: bool = True,
        concept_hops: int = 1,
    ) -> list[dict]:
        """
        Full enterprise RAG pattern: vector search + graph expansion.

        Performs a single Cypher query that:
        1. Vector search on chunk embeddings
        2. Get window context via NEXT
        3. Get related concepts via RELATED/PREREQ

        Args:
            query: Query text
            top_k: Number of initial vector results
            expand_concepts: Include related concepts from graph
            concept_hops: Hops for concept expansion

        Returns:
            List of enriched chunk results with concept context
        """
        # Encode query
        query_embedding = self.embedding_model.encode_query(query)

        # Combined Cypher query for vector + graph
        with self.neo4j_adapter._get_session() as session:
            cypher_query = f"""
            // Step 1: Vector similarity search
            CALL db.index.vector.queryNodes($index_name, $top_k, $query_embedding)
            YIELD node AS chunk, score

            // Step 2: Get window context via NEXT
            OPTIONAL MATCH (prev:Chunk)-[:NEXT]->(chunk)
            OPTIONAL MATCH (chunk)-[:NEXT]->(next:Chunk)

            // Step 3: Get related concepts via MENTIONS
            OPTIONAL MATCH (chunk)-[:MENTIONS]->(concept:Concept)
            OPTIONAL MATCH (concept)-[:RELATED|PREREQ*1..{concept_hops}]-(related:Concept)

            // Return enriched results
            RETURN chunk.chunkId AS chunk_id,
                   chunk.text AS text,
                   chunk.moduleId AS module_id,
                   chunk.section AS section,
                   chunk.chunkIndex AS chunk_index,
                   score,
                   prev.chunkId AS prev_chunk_id,
                   next.chunkId AS next_chunk_id,
                   collect(DISTINCT concept.name) AS mentioned_concepts,
                   collect(DISTINCT related.name) AS related_concepts
            ORDER BY score DESC
            """

            result = session.run(
                cypher_query,
                index_name=settings.neo4j_vector_index_name,
                top_k=top_k,
                query_embedding=query_embedding,
            )

            enriched = []
            for record in result:
                chunk = {
                    "chunk_id": record["chunk_id"],
                    "text": record["text"],
                    "module_id": record["module_id"],
                    "section": record["section"],
                    "chunk_index": record["chunk_index"],
                    "score": record["score"],
                    "prev_chunk_id": record["prev_chunk_id"],
                    "next_chunk_id": record["next_chunk_id"],
                }

                if expand_concepts:
                    chunk["mentioned_concepts"] = record["mentioned_concepts"] or []
                    chunk["related_concepts"] = record["related_concepts"] or []

                enriched.append(chunk)

            logger.info(f"Graph-enriched retrieval returned {len(enriched)} chunks")
            return enriched


# Global singleton
_unified_retriever: UnifiedRetriever | None = None


def get_unified_retriever() -> UnifiedRetriever:
    """
    Get or create global unified retriever instance.

    Returns:
        UnifiedRetriever instance
    """
    global _unified_retriever

    if _unified_retriever is None:
        _unified_retriever = UnifiedRetriever()

    return _unified_retriever
