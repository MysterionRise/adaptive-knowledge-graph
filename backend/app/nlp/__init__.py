"""NLP module for embeddings and LLM."""

from backend.app.nlp.concept_extractor import ConceptExtractor, ConceptMatch, get_concept_extractor
from backend.app.nlp.embeddings import EmbeddingModel, get_embedding_model
from backend.app.nlp.llm_client import LLMClient, get_llm_client

__all__ = [
    "EmbeddingModel",
    "get_embedding_model",
    "LLMClient",
    "get_llm_client",
    # Enterprise: Enhanced concept extraction
    "ConceptExtractor",
    "ConceptMatch",
    "get_concept_extractor",
]
