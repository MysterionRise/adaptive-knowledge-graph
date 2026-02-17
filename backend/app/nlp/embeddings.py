"""
Embeddings module for text vectorization.

Uses BGE-M3 multilingual embeddings for semantic search.
Supports both CPU and GPU inference.
"""

import torch
from loguru import logger
from sentence_transformers import SentenceTransformer

from backend.app.core.settings import settings


class EmbeddingModel:
    """Wrapper for embedding model inference."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
    ):
        """
        Initialize embedding model.

        Args:
            model_name: Model name (defaults to settings)
            device: Device for inference ('cuda' or 'cpu', defaults to settings)
            batch_size: Batch size for embedding (defaults to settings)
        """
        self.model_name = model_name or settings.embedding_model
        self.device = device or settings.embedding_device
        self.batch_size = batch_size or settings.embedding_batch_size

        # Validate device
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            self.device = "cpu"

        self.model: SentenceTransformer | None = None
        self.embedding_dim: int | None = None

    def load(self):
        """Load the embedding model."""
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
    ) -> torch.Tensor | list[list[float]]:
        """
        Encode text(s) into embeddings.

        Args:
            texts: Single text or list of texts
            normalize: Normalize embeddings to unit length
            show_progress: Show progress bar

        Returns:
            Embeddings as tensor or list
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
        embeddings = self.encode(query, normalize=True)
        result = embeddings[0]
        if isinstance(result, list):
            return result
        return list(result)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Encode a batch of texts.

        Args:
            texts: List of texts

        Returns:
            List of embeddings
        """
        result = self.encode(texts, normalize=True, show_progress=True)
        if isinstance(result, list):
            return result
        return list(result)

    def get_embedding_dimension(self) -> int:
        """Get the embedding dimension."""
        if self.embedding_dim is None:
            raise RuntimeError("Model not loaded")
        return self.embedding_dim


# Global singleton instance (lazy loaded)
_embedding_model: EmbeddingModel | None = None


def get_embedding_model() -> EmbeddingModel:
    """
    Get or create the global embedding model instance.

    Returns:
        EmbeddingModel instance
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
        _embedding_model.load()

    return _embedding_model
