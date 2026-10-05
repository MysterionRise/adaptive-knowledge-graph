"""Cross-encoder reranker for RAG pipeline.

Uses sentence_transformers CrossEncoder to rerank retrieved chunks
by relevance to the query before passing them to the LLM.
"""

from __future__ import annotations

import copy
import threading

from loguru import logger

from backend.app.core.settings import settings
from backend.app.nlp.embeddings import resolve_device


class Reranker:
    """Cross-encoder reranker using BGE-reranker-v2-m3."""

    def __init__(self) -> None:
        self._model = None
        self._device: str | None = None
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str | None:
        """The device the model was loaded on (cuda, mps or cpu), or None before loading."""
        return self._device if self._model is not None else None

    def load(self) -> None:
        """Load the cross-encoder model (thread-safe; concurrent callers load it once)."""
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return

            from sentence_transformers import CrossEncoder

            device = resolve_device(settings.reranker_device)
            logger.info(f"Loading reranker model {settings.reranker_model} on {device}")
            revision = settings.reranker_model_revision
            kwargs = {"revision": revision} if revision else {}
            self._model = CrossEncoder(settings.reranker_model, device=device, **kwargs)
            self._device = device
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
_reranker_lock = threading.Lock()


def get_reranker() -> Reranker:
    """Get the global reranker singleton."""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = Reranker()
    return _reranker


def loaded_reranker_device() -> str | None:
    """The device of the loaded reranker, or None when it has not been loaded (yet)."""
    reranker = _reranker
    return reranker.device if reranker is not None else None
