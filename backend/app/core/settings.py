"""
Application settings and configuration.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _package_version() -> str:
    """Installed package version: the single source of truth for ``app_version``."""
    try:
        return version("adaptive-knowledge-graph")
    except PackageNotFoundError:  # a source tree that was never installed
        return "0.0.0+unknown"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Adaptive Knowledge Graph"
    app_version: str = Field(default_factory=_package_version)
    # "production" refuses to start without API_KEY and hides the API docs by default;
    # "development" allows the keyless local quickstart (with a startup warning).
    app_env: Literal["development", "production"] = "development"
    # /docs, /redoc and /openapi.json. Unset or empty: on in development, off in production.
    api_docs_enabled: bool | None = None
    debug: bool = False
    log_level: str = "INFO"

    @field_validator("api_docs_enabled", mode="before")
    @classmethod
    def _empty_docs_flag_means_unset(cls, value: object) -> object:
        """``API_DOCS_ENABLED=`` (empty, as in a copied .env) falls back to the APP_ENV default."""
        return None if isinstance(value, str) and not value.strip() else value

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    api_key: str = ""  # Set via API_KEY env var for authentication

    # Rate Limiting
    rate_limit_enabled: bool = True
    # Every endpoint except health checks, per client and endpoint, counted before auth
    rate_limit_default: str = "100/minute"
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
    opensearch_index: str = "textbook_chunks"
    opensearch_use_ssl: bool = False
    opensearch_verify_certs: bool = True
    opensearch_user: str = "admin"
    opensearch_password: str = ""  # Set via OPENSEARCH_PASSWORD env var

    # LLM Configuration
    llm_mode: Literal["local", "remote", "hybrid"] = "local"
    llm_local_backend: Literal["ollama", "llamacpp"] = "ollama"
    llm_ollama_host: str = "http://localhost:11434"
    llm_local_model: str = "llama3.1:8b-instruct-q4_K_M"
    llm_max_context: int = 8192
    llm_temperature: float = 0.1
    llm_timeout: int = 60  # Non-streaming timeout (seconds)
    llm_stream_timeout: int = 120  # Streaming timeout (seconds)
    llm_retry_attempts: int = 3  # Max retries for non-streaming calls
    llm_retry_min_wait: float = 1.0  # Min backoff (seconds)
    llm_retry_max_wait: float = 10.0  # Max backoff (seconds)

    # OpenRouter (remote fallback)
    openrouter_api_key: str = ""
    openrouter_model: str = "mistralai/mixtral-8x7b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_verify_ssl: bool = True

    # Embeddings
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"  # cuda or cpu
    embedding_batch_size: int = 32

    # Reranker
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_k: int = 10
    reranker_device: str = "cuda"

    # RAG
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 128
    rag_retrieval_top_k: int = 20
    rag_final_top_k: int = 5
    rag_kg_expansion: bool = True
    rag_kg_expansion_hops: int = 1

    # Retrieval mode for OpenSearch: "knn" (vector only) or "hybrid" (BM25 + kNN with RRF)
    retrieval_mode: Literal["knn", "hybrid"] = "hybrid"

    # Enterprise RAG: Vector Backend
    # "opensearch" = original behavior (OpenSearch kNN)
    # "neo4j" = Neo4j native vector index
    # "hybrid" = query both, merge results
    vector_backend: Literal["opensearch", "neo4j", "hybrid"] = "opensearch"

    # Neo4j Vector Index Settings
    neo4j_vector_index_name: str = "chunk_embeddings"
    neo4j_vector_dimension: int = 1024  # BGE-M3 dimension

    # Window Retrieval Settings
    rag_window_retrieval: bool = True  # Enable window context via NEXT
    rag_window_size: int = 1  # Chunks before/after to include

    # Student Model
    student_bkt_enabled: bool = True
    student_irt_enabled: bool = False
    student_initial_mastery: float = 0.3
    student_storage_backend: Literal["sqlite", "json"] = "sqlite"
    student_profiles_db: str = "data/processed/student_profiles.sqlite3"

    # CORS (comma-separated lists; production refuses "*")
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    cors_allow_methods: str = "GET,POST,OPTIONS"
    cors_allow_headers: str = "Content-Type,X-API-Key,X-Request-ID"
    # Rate-limit by the right-most X-Forwarded-For hop; enable only behind a reverse proxy
    # that appends the client address.
    trust_proxy_headers: bool = False

    # Privacy & Compliance
    privacy_local_only: bool = True  # Toggle for local-only mode
    privacy_no_tracking: bool = False
    attribution_openstax: str = (
        "Content adapted from OpenStax (various), "
        "licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
    )

    # Data paths
    data_raw_dir: str = "data/raw"
    data_processed_dir: str = "data/processed"
    data_books_jsonl: str = "data/processed/books.jsonl"

    # Graph Analytics
    graph_compute_centrality: bool = True
    graph_compute_communities: bool = True


# Global settings instance
settings = Settings()
