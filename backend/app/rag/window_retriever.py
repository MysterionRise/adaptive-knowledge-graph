"""
Window retriever for context-aware RAG.

Retrieves chunks with surrounding context using NEXT relationships in Neo4j.
This is the enterprise RAG pattern from deeplearning.ai Knowledge Graphs course.

Window retrieval is opt-in: /ask only uses it when VECTOR_BACKEND is neo4j or
hybrid (see the Settings field descriptions). The subject's Chunk nodes and
their NEXT relationships are created by scripts/migrate_to_enterprise.py.
"""

import threading
from collections.abc import Mapping, Sequence
from typing import Any

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter


def _check_window_size(window_size: int) -> int:
    if window_size < 0:
        raise ValueError(f"window_size must be >= 0, got {window_size}")
    return window_size


class WindowRetriever:
    """
    Retrieve chunks with context window via NEXT traversal.

    This retriever enhances standard chunk retrieval by including
    neighboring chunks for better context. Uses the NEXT relationship
    graph pattern for efficient window queries.
    """

    def __init__(
        self,
        window_size: int | None = None,
        neo4j_adapter: Neo4jAdapter | None = None,
        subject_id: str | None = None,
    ):
        """
        Initialize window retriever.

        Args:
            window_size: Chunks before/after each hit (defaults to RAG_WINDOW_SIZE; 0 = hits only)
            neo4j_adapter: Neo4j adapter to use (defaults to the subject's shared adapter)
            subject_id: Subject whose prefixed Chunk labels are queried (None = default subject)
        """
        self.window_size = _check_window_size(
            settings.rag_window_size if window_size is None else window_size
        )
        self.subject_id = subject_id
        self._adapter = neo4j_adapter

    @property
    def adapter(self) -> Neo4jAdapter:
        """The subject's Neo4j adapter (shared through get_neo4j_adapter)."""
        if self._adapter is None:
            self._adapter = get_neo4j_adapter(self.subject_id)
        return self._adapter

    def close(self) -> None:
        """Drop the adapter reference; shared adapters are closed by clear_neo4j_adapters()."""
        self._adapter = None

    def retrieve_with_window(
        self,
        chunk_ids: Sequence[str],
        window_size: int | None = None,
        deduplicate: bool = True,
    ) -> list[dict]:
        """
        Get chunks plus their neighbors via NEXT relationships.

        Args:
            chunk_ids: List of chunk IDs to expand
            window_size: Override the default window size (0 returns only the hits)
            deduplicate: Remove duplicate chunks from overlapping windows

        Returns:
            List of chunk dicts with context, ordered by module then chunk_index
        """
        size = _check_window_size(self.window_size if window_size is None else window_size)
        hit_ids = set(chunk_ids)

        all_chunks: list[dict] = []
        seen_ids: set[str] = set()

        for chunk_id in chunk_ids:
            window_chunks = self.adapter.get_chunk_window(
                chunk_id=chunk_id,
                window_before=size,
                window_after=size,
            )

            for chunk in window_chunks:
                if deduplicate:
                    if chunk["chunk_id"] in seen_ids:
                        continue
                    seen_ids.add(chunk["chunk_id"])

                # A hit can also fall inside another hit's window
                chunk["is_original_hit"] = chunk["chunk_id"] in hit_ids
                all_chunks.append(chunk)

        # Sort by module_id, then chunk_index for coherent reading order
        all_chunks.sort(key=lambda c: (c.get("module_id") or "", c.get("chunk_index") or 0))

        logger.info(
            f"Window retrieval: {len(chunk_ids)} chunks -> "
            f"{len(all_chunks)} chunks (window_size={size})"
        )

        return all_chunks

    def retrieve_window_text(
        self,
        chunk_ids: Sequence[str],
        window_size: int | None = None,
        separator: str = "\n\n",
        scores: Mapping[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get chunks with window context merged into one text block per module.

        Each result is a complete chunk dict in the retriever's format, so callers
        can use it as a retrieval result as-is: ``id`` (the group's first original
        hit), ``text``, ``module_id``, ``module_title``, ``section`` and ``score``
        (best score of the group's original hits taken from ``scores``; None if no
        score is known), plus ``chunk_count``, ``original_hit_count`` and ``chunk_ids``.

        Args:
            chunk_ids: List of chunk IDs to expand
            window_size: Override the default window size (0 returns only the hits)
            separator: Text separator between merged chunks
            scores: Retrieval scores of the hits, keyed by chunk ID

        Returns:
            One dict per module group; ordered by score when scores are given,
            otherwise by module
        """
        chunks = self.retrieve_with_window(chunk_ids, window_size)

        # Group by module
        module_groups: dict[str, list[dict]] = {}
        for chunk in chunks:
            module_groups.setdefault(chunk.get("module_id") or "unknown", []).append(chunk)

        merged_results: list[dict[str, Any]] = []
        for module_id, module_chunks in module_groups.items():
            module_chunks.sort(key=lambda c: c.get("chunk_index") or 0)
            hits = [c for c in module_chunks if c.get("is_original_hit")]
            anchor = hits[0] if hits else module_chunks[0]
            hit_scores = [
                float(scores[c["chunk_id"]]) for c in hits if scores and c["chunk_id"] in scores
            ]

            merged_results.append(
                {
                    "id": anchor["chunk_id"],
                    "text": separator.join(c["text"] for c in module_chunks),
                    "module_id": module_id,
                    "module_title": next(
                        (c["module_title"] for c in module_chunks if c.get("module_title")), None
                    ),
                    "section": module_chunks[0].get("section"),
                    "score": max(hit_scores) if hit_scores else None,
                    "chunk_count": len(module_chunks),
                    "original_hit_count": len(hits),
                    "chunk_ids": [c["chunk_id"] for c in module_chunks],
                }
            )

        if scores:
            # Best-scoring groups first; groups without a known score keep module order at the end
            merged_results.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))

        logger.info(
            f"Merged window retrieval: {len(chunk_ids)} hits -> {len(merged_results)} module groups"
        )

        return merged_results


# Registry of window retrievers per subject
_window_retrievers: dict[str, WindowRetriever] = {}
_window_retrievers_lock = threading.Lock()


def get_window_retriever(
    subject_id: str | None = None,
    window_size: int | None = None,
) -> WindowRetriever:
    """
    Get or create the window retriever for a subject.

    Args:
        subject_id: Subject identifier; None uses default_subject from config/subjects.yaml
        window_size: Default window size, only used when the retriever is created

    Returns:
        WindowRetriever using the subject's prefixed Chunk labels
    """
    resolved_id = get_subject(subject_id).id
    with _window_retrievers_lock:
        retriever = _window_retrievers.get(resolved_id)
        if retriever is None:
            retriever = WindowRetriever(window_size=window_size, subject_id=resolved_id)
            _window_retrievers[resolved_id] = retriever
        return retriever


def clear_window_retrievers() -> None:
    """Clear all cached window retrievers."""
    with _window_retrievers_lock:
        _window_retrievers.clear()
