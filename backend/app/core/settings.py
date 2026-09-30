"""
Application settings and configuration.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRIVACY_LLM_MODE_ERROR = (
    "PRIVACY_LOCAL_ONLY=true requires LLM_MODE=local "
    "(set LLM_MODE=local or PRIVACY_LOCAL_ONLY=false)"
)


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
    api_prefix: str = "/api/v1"
    api_key: str = ""  # Set via API_KEY env var for authentication

    # Rate Limiting (per client; per-route limits are read when the route modules are imported)
    rate_limit_enabled: bool = True
    # Every endpoint except health checks, per client and endpoint, counted before auth
    rate_limit_default: str = "100/minute"
    rate_limit_ask: str = "10/minute"  # /ask and /ask/stream
    rate_limit_quiz: str = "5/minute"  # /quiz/generate and /quiz/generate-adaptive
    rate_limit_graph: str = "30/minute"  # /graph/stats and /graph/data
    rate_limit_graph_query: str = "10/minute"  # /graph/query (LLM-generated Cypher)
    rate_limit_student_write: str = "30/minute"  # /student/mastery and /student/reset
    rate_limit_recommendations: str = "10/minute"  # /quiz/recommendations (KG + LLM calls)

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
    opensearch_number_of_replicas: int = Field(
        default=0,
        ge=0,
        description=(
            "Replicas for newly created chunk indices. 0 keeps a single-node cluster green; "
            "raise it on multi-node clusters."
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

    # CORS (comma-separated lists; production refuses "*")
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    cors_allow_methods: str = "GET,POST,OPTIONS"
    cors_allow_headers: str = "Content-Type,X-API-Key,X-Request-ID"
    # Rate-limit by the right-most X-Forwarded-For hop; enable only behind a reverse proxy
    # that appends the client address.
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
