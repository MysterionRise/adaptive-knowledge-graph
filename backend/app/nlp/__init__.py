"""NLP module for embeddings and LLM."""

from backend.app.nlp.embeddings import EmbeddingModel, get_embedding_model
from backend.app.nlp.llm_client import LLMClient, get_llm_client

__all__ = ["EmbeddingModel", "get_embedding_model", "LLMClient", "get_llm_client"]
