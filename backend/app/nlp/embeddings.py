"""
Embeddings module for text vectorization.

Uses BGE-M3 multilingual embeddings for semantic search. The inference device
comes from EMBEDDING_DEVICE: ``auto`` (the default) picks CUDA, then Apple MPS,
then CPU. torch and sentence-transformers are imported only when a model is
loaded, so importing this module stays cheap.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from loguru import logger

from backend.app.core.settings import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def resolve_device(requested: str | None = None) -> str:
    """
    Resolve a requested inference device to one that is available.

    Args:
        requested: "auto", "cuda" (or "cuda:N"), "mps" or "cpu". None means "auto".

    Returns:
        The device string to pass to torch; "cpu" whenever the requested
        accelerator is unavailable.
    """
    choice = (requested or "auto").strip().lower()
    if choice == "cpu":
        return "cpu"

    try:
        import torch
    except ImportError:
        logger.warning("torch is not installed, using CPU")
        return "cpu"

    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(torch.backends, "mps", None)
    mps_available = bool(mps_backend is not None and mps_backend.is_available())

    if choice == "auto":
        if cuda_available:
            return "cuda"
        if mps_available:
            return "mps"
        return "cpu"

    if choice.startswith("cuda"):
        if cuda_available:
            return choice
        logger.warning(f"Device {choice!r} requested but CUDA is not available, using CPU")
        return "cpu"

    if choice == "mps":
        if mps_available:
            return "mps"
        logger.warning("Device 'mps' requested but Apple MPS is not available, using CPU")
        return "cpu"

    logger.warning(f"Unknown device {requested!r}, using CPU")
    return "cpu"


class EmbeddingModel:
    """Wrapper for embedding model inference."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
    ):
        """
        Initialize embedding model (nothing is loaded until load()).

        Args:
            model_name: Model name (defaults to settings)
            device: Requested device ('auto', 'cuda', 'mps' or 'cpu'; defaults to settings)
            batch_size: Batch size for embedding (defaults to settings)
        """
        self.model_name = model_name or settings.embedding_model
        self.requested_device = device or settings.embedding_device
        self.device: str | None = None  # resolved in load()
        self.batch_size = batch_size or settings.embedding_batch_size

        self.model: SentenceTransformer | None = None
        self.embedding_dim: int | None = None

    def load(self) -> None:
        """Resolve the device and load the embedding model."""
        from sentence_transformers import SentenceTransformer

        self.device = resolve_device(self.requested_device)
        logger.info(f"Loading embedding model: {self.model_name} on {self.device}")

        try:
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self.embedding_dim = self.model.get_sentence_embedding_dimension()

            logger.success(
                f"✓ Loaded {self.model_name} (dim={self.embedding_dim}) on {self.device}"
            )

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def encode(
        self,
        texts: str | list[str],
        normalize: bool = True,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """
        Encode text(s) into embeddings.

        Args:
            texts: Single text or list of texts
            normalize: Normalize embeddings to unit length
            show_progress: Show progress bar

        Returns:
            One embedding (list of floats) per input text
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Convert single text to list
        if isinstance(texts, str):
            texts = [texts]

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=show_progress,
                normalize_embeddings=normalize,
                convert_to_tensor=False,  # Return as numpy array
            )

            return list(embeddings.tolist())  # Convert to list for JSON serialization

        except Exception as e:
            logger.error(f"Encoding failed: {e}")
            raise

    def encode_query(self, query: str) -> list[float]:
        """
        Encode a single query text.

        Args:
            query: Query text

        Returns:
            Query embedding
        """
        return self.encode(query, normalize=True)[0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Encode a batch of texts.

        Args:
            texts: List of texts

        Returns:
            List of embeddings
        """
        return self.encode(texts, normalize=True, show_progress=True)

    def get_embedding_dimension(self) -> int:
        """Get the embedding dimension."""
        if self.embedding_dim is None:
            raise RuntimeError("Model not loaded")
        return self.embedding_dim


# Global singleton instance (lazy loaded)
_embedding_model: EmbeddingModel | None = None
_embedding_model_lock = threading.Lock()


def get_embedding_model() -> EmbeddingModel:
    """
    Get or create the global embedding model instance.

    Thread-safe: concurrent first calls load the model only once, and a model
    that failed to load is not cached.

    Returns:
        EmbeddingModel instance
    """
    global _embedding_model

    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:
                model = EmbeddingModel()
                model.load()
                _embedding_model = model

    return _embedding_model
