"""
Application settings and configuration.
"""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRIVACY_LLM_MODE_ERROR = (
    "PRIVACY_LOCAL_ONLY=true requires LLM_MODE=local "
    "(set LLM_MODE=local or PRIVACY_LOCAL_ONLY=false)"
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Adaptive Professional Certifications"
    app_version: str = "0.2.0"
    debug: bool = False
    log_level: str = "INFO"

    # API
    api_prefix: str = "/api/v1"
    api_key: str = ""  # Set via API_KEY env var for authentication

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_ask: str = "10/minute"  # 10 requests per minute for /ask
    rate_limit_quiz: str = "5/minute"  # 5 requests per minute for /quiz
    rate_limit_graph: str = "30/minute"  # 30 requests per minute for /graph/*

    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # OpenSearch
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_index: str = Field(
        default="textbook_chunks",
        description=(
            "Legacy single-subject index name, read only by scripts/migrate_to_multisubject.py. "
            "The API uses the per-subject indices from config/subjects.yaml."
        ),
    )
    opensearch_use_ssl: bool = False
    opensearch_verify_certs: bool = True
    opensearch_user: str = "admin"
    opensearch_password: str = ""  # Set via OPENSEARCH_PASSWORD env var

    # LLM Configuration
    llm_mode: Literal["local", "remote", "hybrid"] = Field(
        default="local",
        description=(
            "local = Ollama only; remote = OpenRouter only; hybrid = Ollama with OpenRouter "
            "fallback. remote and hybrid require PRIVACY_LOCAL_ONLY=false."
        ),
    )
    llm_ollama_host: str = "http://localhost:11434"
    llm_local_model: str = "llama3.1:8b-instruct-q4_K_M"
    llm_temperature: float = 0.1
    llm_timeout: int = 60  # Non-streaming timeout (seconds)
    llm_stream_timeout: int = 120  # Streaming timeout (seconds)
    llm_retry_attempts: int = 3  # Max retries for non-streaming calls
    llm_retry_min_wait: float = 1.0  # Min backoff (seconds)
    llm_retry_max_wait: float = 10.0  # Max backoff (seconds)

    # OpenRouter (remote provider; never called while PRIVACY_LOCAL_ONLY=true)
    openrouter_api_key: str = ""
    openrouter_model: str = "mistralai/mixtral-8x7b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_verify_ssl: bool = True

    # Embeddings
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = Field(
        default="auto",
        description="auto (CUDA, then Apple MPS, then CPU), cuda, mps or cpu.",
    )
    embedding_batch_size: int = 32

    # Reranker
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = Field(
        default="cuda",
        description="auto, cuda, mps or cpu; an unavailable accelerator falls back to CPU.",
    )

    # RAG
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 128
    rag_retrieval_top_k: int = 20
    rag_kg_expansion: bool = True
    rag_kg_expansion_hops: int = 1

    # Retrieval mode for OpenSearch: "knn" (vector only) or "hybrid" (BM25 + kNN with RRF)
    retrieval_mode: Literal["knn", "hybrid"] = "hybrid"

    vector_backend: Literal["opensearch", "neo4j", "hybrid"] = Field(
        default="opensearch",
        description=(
            "Chunks are always retrieved from OpenSearch. 'neo4j' or 'hybrid' additionally "
            "turns on window retrieval over Neo4j Chunk nodes linked by NEXT relationships "
            "(created by scripts/migrate_to_enterprise.py). 'opensearch' (default) keeps "
            "window retrieval off."
        ),
    )

    # Neo4j vector index (created by scripts/create_neo4j_indexes.py)
    neo4j_vector_index_name: str = "chunk_embeddings"
    neo4j_vector_dimension: int = 1024  # BGE-M3 dimension

    # Window retrieval (opt-in, see vector_backend)
    rag_window_retrieval: bool = Field(
        default=True,
        description=(
            "Allow /ask to add the neighbouring chunks of each hit (NEXT relationships). "
            "Opt-in: it only runs when VECTOR_BACKEND is neo4j or hybrid and the request "
            "keeps use_window_retrieval=true."
        ),
    )
    rag_window_size: int = Field(
        default=1,
        ge=0,
        description=(
            "Default number of chunks to add before and after each hit when window "
            "retrieval runs; 0 returns only the hits."
        ),
    )

    # Student Model
    student_bkt_enabled: bool = True
    student_initial_mastery: float = 0.3
    student_profiles_db: str = Field(
        default="data/processed/student_profiles.sqlite3",
        description="SQLite database file that stores learner profiles.",
    )
    student_validate_concepts: bool = Field(
        default=False,
        description=(
            "Reject mastery updates for concepts that are not in the subject's knowledge "
            "graph. Opt-in until the quiz topics offered by the frontend are aligned with "
            "knowledge-graph concept names."
        ),
    )

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    trust_proxy_headers: bool = False

    # Privacy & Compliance
    privacy_local_only: bool = Field(
        default=True,
        description=(
            "Never send prompts to a remote LLM provider. Requires LLM_MODE=local; any other "
            "combination fails at startup."
        ),
    )
    attribution_openstax: str = (
        "Content adapted from OpenStax (various), "
        "licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
    )

    # Data paths
    data_raw_dir: str = "data/raw"
    data_processed_dir: str = "data/processed"
    data_books_jsonl: str = "data/processed/books.jsonl"  # read by scripts/normalize_book.py

    @property
    def remote_llm_allowed(self) -> bool:
        """Whether this configuration may send prompts to a remote LLM provider."""
        return not self.privacy_local_only and self.llm_mode != "local"

    @model_validator(mode="after")
    def _require_local_llm_when_private(self) -> "Settings":
        """Fail fast when PRIVACY_LOCAL_ONLY is combined with a remote-capable LLM mode."""
        if self.privacy_local_only and self.llm_mode != "local":
            raise ValueError(PRIVACY_LLM_MODE_ERROR)
        return self


# Global settings instance
settings = Settings()
