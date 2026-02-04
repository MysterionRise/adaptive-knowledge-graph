"""
Window retriever for context-aware RAG.

Retrieves chunks with surrounding context using NEXT relationships in Neo4j.
This is the enterprise RAG pattern from deeplearning.ai Knowledge Graphs course.
"""

from loguru import logger

from backend.app.core.settings import settings
from backend.app.kg.neo4j_adapter import Neo4jAdapter


class WindowRetriever:
    """
    Retrieve chunks with context window via NEXT traversal.

    This retriever enhances standard chunk retrieval by including
    neighboring chunks for better context. Uses the NEXT relationship
    graph pattern for efficient window queries.
    """

    def __init__(
        self,
        window_size: int = 1,
        neo4j_adapter: Neo4jAdapter | None = None,
    ):
        """
        Initialize window retriever.

        Args:
            window_size: Number of chunks before/after to include (default 1)
            neo4j_adapter: Neo4j adapter instance (creates new if not provided)
        """
        self.window_size = window_size
        self._adapter = neo4j_adapter
        self._owns_adapter = neo4j_adapter is None

    @property
    def adapter(self) -> Neo4jAdapter:
        """Lazy-load Neo4j adapter."""
        if self._adapter is None:
            self._adapter = Neo4jAdapter()
            self._adapter.connect()
        return self._adapter

    def close(self):
        """Close Neo4j connection if we own it."""
        if self._owns_adapter and self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    def retrieve_with_window(
        self,
        chunk_ids: list[str],
        window_size: int | None = None,
        deduplicate: bool = True,
    ) -> list[dict]:
        """
        Get chunks plus their neighbors via NEXT relationships.

        Args:
            chunk_ids: List of chunk IDs to expand
            window_size: Override default window size
            deduplicate: Remove duplicate chunks from overlapping windows

        Returns:
            List of chunk dicts with context, ordered by module then chunk_index
        """
        window_size = window_size or self.window_size

        all_chunks = []
        seen_ids = set()

        for chunk_id in chunk_ids:
            window_chunks = self.adapter.get_chunk_window(
                chunk_id=chunk_id,
                window_before=window_size,
                window_after=window_size,
            )

            for chunk in window_chunks:
                if deduplicate:
                    if chunk["chunk_id"] in seen_ids:
                        continue
                    seen_ids.add(chunk["chunk_id"])

                # Mark which chunk was the original retrieval hit
                chunk["is_original_hit"] = chunk["chunk_id"] == chunk_id
                all_chunks.append(chunk)

        # Sort by module_id, then chunk_index for coherent reading order
        all_chunks.sort(key=lambda c: (c.get("module_id", ""), c.get("chunk_index", 0)))

        logger.info(
            f"Window retrieval: {len(chunk_ids)} chunks -> "
            f"{len(all_chunks)} chunks (window_size={window_size})"
        )

        return all_chunks

    def retrieve_window_text(
        self,
        chunk_ids: list[str],
        window_size: int | None = None,
        separator: str = "\n\n",
    ) -> list[dict]:
        """
        Get chunks with window context merged into single text blocks.

        Groups consecutive chunks by module and merges their text.
        Useful for providing cleaner context to LLMs.

        Args:
            chunk_ids: List of chunk IDs to expand
            window_size: Override default window size
            separator: Text separator between merged chunks

        Returns:
            List of dicts with merged text and metadata per module group
        """
        chunks = self.retrieve_with_window(chunk_ids, window_size)

        # Group by module
        module_groups: dict[str, list[dict]] = {}
        for chunk in chunks:
            module_id = chunk.get("module_id", "unknown")
            if module_id not in module_groups:
                module_groups[module_id] = []
            module_groups[module_id].append(chunk)

        # Merge text per module
        merged_results = []
        for module_id, module_chunks in module_groups.items():
            # Sort by chunk_index within module
            module_chunks.sort(key=lambda c: c.get("chunk_index", 0))

            # Count original hits in this group
            original_hits = [c for c in module_chunks if c.get("is_original_hit")]

            merged = {
                "module_id": module_id,
                "section": module_chunks[0].get("section") if module_chunks else None,
                "text": separator.join(c["text"] for c in module_chunks),
                "chunk_count": len(module_chunks),
                "original_hit_count": len(original_hits),
                "chunk_ids": [c["chunk_id"] for c in module_chunks],
            }
            merged_results.append(merged)

        logger.info(
            f"Merged window retrieval: {len(chunk_ids)} hits -> "
            f"{len(merged_results)} module groups"
        )

        return merged_results


# Global singleton
_window_retriever: WindowRetriever | None = None


def get_window_retriever(window_size: int | None = None) -> WindowRetriever:
    """
    Get or create global window retriever instance.

    Args:
        window_size: Override default window size (only used on creation)

    Returns:
        WindowRetriever instance
    """
    global _window_retriever

    if _window_retriever is None:
        _window_retriever = WindowRetriever(
            window_size=window_size or settings.rag_kg_expansion_hops
        )

    return _window_retriever
