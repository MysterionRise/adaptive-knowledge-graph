"""Cross-encoder reranker for RAG pipeline.

Uses sentence_transformers CrossEncoder to rerank retrieved chunks
by relevance to the query before passing them to the LLM.
"""

from __future__ import annotations

import copy

from loguru import logger

from backend.app.core.settings import settings


class Reranker:
    """Cross-encoder reranker using BGE-reranker-v2-m3."""

    def __init__(self) -> None:
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the cross-encoder model."""
        if self._model is not None:
            return

        from sentence_transformers import CrossEncoder

        device = settings.reranker_device
        try:
            import torch

            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available for reranker, falling back to CPU")
                device = "cpu"
        except ImportError:
            device = "cpu"

        logger.info(f"Loading reranker model {settings.reranker_model} on {device}")
        self._model = CrossEncoder(settings.reranker_model, device=device)
        logger.info("Reranker model loaded")

    def rerank(self, query: str, chunks: list[dict], top_k: int) -> list[dict]:
        """Rerank chunks by relevance to query.

        Args:
            query: The user's question.
            chunks: Retrieved chunks (each must have a "text" key).
            top_k: Number of top chunks to return.

        Returns:
            Top-k chunks sorted by rerank score (descending), each with
            an added ``rerank_score`` field. Input chunks are not mutated.

        Raises:
            RuntimeError: If the model has not been loaded yet.
        """
        if self._model is None:
            raise RuntimeError("Reranker model not loaded. Call load() first.")

        if not chunks:
            return []

        pairs = [[query, chunk["text"]] for chunk in chunks]
        scores = self._model.predict(pairs)

        scored = []
        for chunk, score in zip(chunks, scores, strict=False):
            new_chunk = copy.copy(chunk)
            new_chunk["rerank_score"] = float(score)
            scored.append(new_chunk)

        scored.sort(key=lambda c: c["rerank_score"], reverse=True)
        return scored[:top_k]


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    """Get the global reranker singleton."""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
