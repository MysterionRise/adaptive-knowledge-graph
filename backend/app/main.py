"""
Main FastAPI application entry point.

``create_app()`` builds the application from ``Settings``; ``app = create_app()`` is the
instance uvicorn serves (``backend.app.main:app``). Tests build apps from their own
settings, e.g. ``create_app(Settings(app_env="production", api_key="..."))``.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

from backend.app.api import (
    ask_router,
    demo_router,
    graph_router,
    learning_path_router,
    quiz_router,
    subjects_router,
)
from backend.app.core.auth import get_request_settings
from backend.app.core.exceptions import ConfigurationError, request_validation_exception_handler
from backend.app.core.logging import setup_logging
from backend.app.core.middleware import RequestIDMiddleware
from backend.app.core.rate_limit import (
    DefaultRateLimitExceeded,
    default_rate_limit_exceeded_handler,
    enforce_default_rate_limit,
    limiter,
    parse_rate_limit,
    rate_limit_exceeded_handler,
)
from backend.app.core.settings import Settings, settings

PROJECT_URL = "https://github.com/MysterionRise/adaptive-knowledge-graph"
MIN_PRODUCTION_API_KEY_LENGTH = 16

_KEYLESS_WARNING = "\n".join(
    [
        "=" * 78,
        "API_KEY is not set: API key authentication is DISABLED (APP_ENV=development).",
        "Anyone who can reach this server can read and reset learner profiles and run",
        "graph queries. Keep it on localhost, or set API_KEY and APP_ENV=production",
        "before exposing it to a network.",
        "=" * 78,
    ]
)


def _csv(value: str) -> list[str]:
    """Split a comma-separated setting into its non-empty, stripped items."""
    return [item.strip() for item in value.split(",") if item.strip()]


def docs_enabled(app_settings: Settings) -> bool:
    """Whether /docs, /redoc and /openapi.json are served (API_DOCS_ENABLED, else APP_ENV)."""
    if app_settings.api_docs_enabled is not None:
        return app_settings.api_docs_enabled
    return app_settings.app_env == "development"


def validate_settings(app_settings: Settings) -> None:
    """Refuse to build an app from a broken or, in production, insecure configuration.

    Raises:
        ConfigurationError: an ``API_KEY`` no client could ever send (not printable
            ASCII, or with surrounding whitespace), an invalid ``RATE_LIMIT_DEFAULT``, or
            ``APP_ENV=production`` without ``API_KEY`` or with a ``*`` in the CORS lists.
    """
    problems = []
    api_key = app_settings.api_key
    # Header values arrive as latin-1 with surrounding whitespace stripped, so such a key
    # could never match; fail at startup instead of rejecting every request.
    if api_key and not (api_key.isascii() and api_key.isprintable() and api_key == api_key.strip()):
        problems.append("API_KEY must be printable ASCII without leading or trailing whitespace")
    try:
        parse_rate_limit(app_settings.rate_limit_default)
    except ValueError:
        problems.append(
            f"RATE_LIMIT_DEFAULT is not a valid rate limit: {app_settings.rate_limit_default!r}"
        )

    if app_settings.app_env == "production":
        if not api_key.strip():
            problems.append("API_KEY must be set")
        elif len(api_key) < MIN_PRODUCTION_API_KEY_LENGTH:
            problems.append(
                f"API_KEY must be at least {MIN_PRODUCTION_API_KEY_LENGTH} characters long"
            )
        for name, value in (
            ("CORS_ORIGINS", app_settings.cors_origins),
            ("CORS_ALLOW_METHODS", app_settings.cors_allow_methods),
            ("CORS_ALLOW_HEADERS", app_settings.cors_allow_headers),
        ):
            if "*" in _csv(value):
                problems.append(f"{name} must list explicit values, not '*'")

    if problems:
        raise ConfigurationError(
            f"Refusing to start with APP_ENV={app_settings.app_env}: " + "; ".join(problems) + "."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    app_settings: Settings = app.state.settings

    # Startup
    setup_logging(app_settings)
    logger.info(
        f"Starting {app_settings.app_name} v{app_settings.app_version} "
        f"(APP_ENV={app_settings.app_env})"
    )
    logger.info(f"LLM Mode: {app_settings.llm_mode}")
    logger.info(f"Privacy Local-Only: {app_settings.privacy_local_only}")
    logger.info(f"Rate Limiting: {'enabled' if limiter.enabled else 'disabled'}")
    logger.info(f"API docs: {'enabled' if docs_enabled(app_settings) else 'disabled'}")
    if app_settings.api_key:
        logger.info("API Key Auth: enabled")
    else:
        logger.warning(_KEYLESS_WARNING)

    yield

    # Shutdown
    logger.info("Shutting down application")


OPENAPI_TAGS = [
    {
        "name": "Q&A",
        "description": "Knowledge graph-aware RAG question answering with streaming support.",
    },
    {
        "name": "Quiz & Adaptive Learning",
        "description": "Adaptive quiz generation, student mastery tracking, and post-quiz recommendations.",
    },
    {
        "name": "Knowledge Graph",
        "description": "Graph visualization, statistics, natural language Cypher queries, and concept search.",
    },
    {
        "name": "Learning Paths",
        "description": "Prerequisite traversal and learning path generation from the knowledge graph.",
    },
    {
        "name": "Subjects",
        "description": "Multi-subject configuration, themes, and book metadata.",
    },
    {
        "name": "Health",
        "description": "Service health checks including dependency status for Neo4j, OpenSearch, and Ollama.",
    },
]

API_DESCRIPTION = (
    "**Adaptive Knowledge Graph** is a proof-of-concept adaptive learning API. It combines "
    "a knowledge graph (Neo4j), hybrid retrieval (OpenSearch BM25 + vector search) and an "
    "LLM to answer questions and generate quizzes over OpenStax textbooks.\n\n"
    "## Key Features\n"
    "- **KG-Aware RAG**: Query expansion via knowledge graph traversal + hybrid retrieval, "
    "with cited answers\n"
    "- **Adaptive Quizzes**: Difficulty targeting with BKT-inspired mastery updates\n"
    "- **Streaming Responses**: SSE-based token streaming for real-time answer generation\n"
    "- **Multi-Subject**: Separate knowledge graphs and search indices per subject\n"
    "- **Local-first**: Answers come from a local Ollama model by default; remote LLM calls "
    "(OpenRouter) happen only when `LLM_MODE` is `remote` or `hybrid`\n\n"
    "## Authentication\n"
    "Endpoints that read or change learner data, and the natural-language graph query, "
    "require an `X-API-Key` header when `API_KEY` is set. With `APP_ENV=production` the "
    "key is mandatory, and these docs are disabled unless `API_DOCS_ENABLED=true`.\n\n"
    "## Architecture\n"
    "Frontend (Next.js) → FastAPI → Neo4j + OpenSearch + Ollama/OpenRouter\n\n"
    "*Content adapted from OpenStax, licensed under CC BY 4.0.*"
)


router = APIRouter()


@router.get("/")
async def root(request: Request):
    """Root endpoint."""
    app_settings = get_request_settings(request)
    return {
        "name": app_settings.app_name,
        "version": app_settings.app_version,
        "status": "running",
        "llm_mode": app_settings.llm_mode,
        "privacy_local_only": app_settings.privacy_local_only,
    }


@router.get("/health", tags=["Health"])
@limiter.exempt  # probes must never be rate limited (see enforce_default_rate_limit)
async def health():
    """Basic health check endpoint (always returns healthy if API is up)."""
    return {
        "status": "healthy",
        "attribution": settings.attribution_openstax,
    }


class ServiceStatus(str, Enum):
    """Status of a service dependency."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class ServiceHealth(BaseModel):
    """Health status of a single service."""

    status: ServiceStatus
    message: str | None = None
    latency_ms: float | None = None


class ReadinessResponse(BaseModel):
    """Response for /health/ready endpoint."""

    status: Literal["healthy", "degraded", "unhealthy"]
    services: dict[str, ServiceHealth]
    attribution: str


async def check_neo4j_health() -> ServiceHealth:
    """Check Neo4j connectivity."""
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        start = time.perf_counter()
        adapter = Neo4jAdapter()
        adapter.connect()

        # Run a simple query to verify
        with adapter._get_session() as session:
            result = session.run("RETURN 1 as n")
            _ = list(result)

        latency = (time.perf_counter() - start) * 1000
        adapter.close()

        return ServiceHealth(status=ServiceStatus.OK, latency_ms=round(latency, 2))

    except Exception as e:
        # Full detail (with the request id) goes to the logs only: the unauthenticated
        # response gets a fixed message, since no redaction catches every host name
        # (Docker service names such as "neo4j-core-0"). The error text is a loguru
        # argument, so braces in it (JSON error bodies) are never parsed as format fields.
        logger.warning("Neo4j health check failed: {}", e)
        return ServiceHealth(status=ServiceStatus.ERROR, message="Neo4j unavailable")


async def check_opensearch_health() -> ServiceHealth:
    """Check OpenSearch connectivity."""
    try:
        start = time.perf_counter()

        # Use httpx for async HTTP request
        protocol = "https" if settings.opensearch_use_ssl else "http"
        url = f"{protocol}://{settings.opensearch_host}:{settings.opensearch_port}/_cluster/health"

        async with httpx.AsyncClient(
            verify=settings.opensearch_verify_certs,
            timeout=5.0,
        ) as client:
            if settings.opensearch_password:
                auth = (settings.opensearch_user, settings.opensearch_password)
                response = await client.get(url, auth=auth)
            else:
                response = await client.get(url)

        latency = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            health_data = response.json()
            cluster_status = health_data.get("status", "unknown")

            if cluster_status == "green":
                return ServiceHealth(status=ServiceStatus.OK, latency_ms=round(latency, 2))
            elif cluster_status == "yellow":
                return ServiceHealth(
                    status=ServiceStatus.DEGRADED,
                    message="Cluster status: yellow",
                    latency_ms=round(latency, 2),
                )
            else:
                return ServiceHealth(
                    status=ServiceStatus.ERROR,
                    message=f"Cluster status: {cluster_status}",
                    latency_ms=round(latency, 2),
                )
        else:
            return ServiceHealth(
                status=ServiceStatus.ERROR,
                message=f"HTTP {response.status_code}",
            )

    except Exception as e:
        logger.warning("OpenSearch health check failed: {}", e)
        return ServiceHealth(status=ServiceStatus.ERROR, message="OpenSearch unavailable")


async def check_ollama_health() -> ServiceHealth:
    """Check Ollama LLM service connectivity."""
    # Skip check if not using local LLM
    if settings.llm_mode == "remote":
        return ServiceHealth(status=ServiceStatus.OK, message="Using remote LLM (skipped)")

    try:
        start = time.perf_counter()

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.llm_ollama_host}/api/tags")

        latency = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])

            # Check if the configured model is available
            model_names = [m.get("name", "") for m in models]
            if any(settings.llm_local_model in name for name in model_names):
                return ServiceHealth(status=ServiceStatus.OK, latency_ms=round(latency, 2))
            else:
                return ServiceHealth(
                    status=ServiceStatus.DEGRADED,
                    message=f"Model {settings.llm_local_model} not found",
                    latency_ms=round(latency, 2),
                )
        else:
            return ServiceHealth(
                status=ServiceStatus.ERROR,
                message=f"HTTP {response.status_code}",
            )

    except Exception as e:
        logger.warning("Ollama health check failed: {}", e)
        return ServiceHealth(status=ServiceStatus.ERROR, message="Ollama unavailable")


@router.get("/health/ready", response_model=ReadinessResponse, tags=["Health"])
@limiter.exempt
async def health_ready(response: Response):
    """
    Readiness check endpoint with service dependency verification.

    Checks:
    - Neo4j: Graph database connectivity
    - OpenSearch: Vector search connectivity
    - Ollama: LLM service connectivity (if using local mode)

    Returns:
    - healthy: All services operational
    - degraded: Some services have warnings
    - unhealthy: Critical services are down
    """
    # Check all services concurrently
    neo4j_health, opensearch_health, ollama_health = await asyncio.gather(
        check_neo4j_health(),
        check_opensearch_health(),
        check_ollama_health(),
    )

    services = {
        "neo4j": neo4j_health,
        "opensearch": opensearch_health,
        "ollama": ollama_health,
    }

    # Determine overall status
    statuses = [s.status for s in services.values()]

    if all(s == ServiceStatus.OK for s in statuses):
        overall_status = "healthy"
    elif any(s == ServiceStatus.ERROR for s in statuses):
        # Neo4j and OpenSearch are critical
        critical_services = ["neo4j", "opensearch"]
        if any(services[svc].status == ServiceStatus.ERROR for svc in critical_services):
            overall_status = "unhealthy"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            overall_status = "degraded"
            response.status_code = status.HTTP_200_OK
    else:
        overall_status = "degraded"
        response.status_code = status.HTTP_200_OK

    return ReadinessResponse(
        status=overall_status,  # type: ignore[arg-type]
        services=services,
        attribution=settings.attribution_openstax,
    )


@router.get("/health/live", tags=["Health"])
@limiter.exempt
async def health_live():
    """
    Liveness check endpoint.

    Simple check that the API process is running.
    Used by Kubernetes liveness probes.
    """
    return {"status": "alive"}


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """
    Build the FastAPI application.

    Args:
        app_settings: Settings for this app; defaults to the process-wide ``settings``.
            They are stored on ``app.state.settings`` and drive authentication, the rate
            limit key, CORS and the API docs.

    Raises:
        ConfigurationError: the settings fail ``validate_settings`` (e.g.
            ``APP_ENV=production`` without a usable ``API_KEY`` or with wildcard CORS).
    """
    app_settings = app_settings or settings
    validate_settings(app_settings)
    show_docs = docs_enabled(app_settings)

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        contact={"name": "Adaptive Knowledge Graph on GitHub", "url": PROJECT_URL},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
        # Runs before every route's own dependencies (verify_api_key included), so
        # requests that go on to fail authentication are still counted.
        dependencies=[Depends(enforce_default_rate_limit)],
    )
    app.state.settings = app_settings

    # Rate limiter state and error handlers. The limiter is process-wide: RATE_LIMIT_ENABLED
    # and the @limiter.limit decorators are bound from the process settings at import;
    # app_settings pick the default limit and the client key (see core/rate_limit.py).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DefaultRateLimitExceeded, default_rate_limit_exceeded_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

    # The middleware added last runs first: request ID -> CORS -> routing. CORS answers
    # preflight requests before routing (so they are not rate limited), and 429 responses
    # pass back through it, so they carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_csv(app_settings.cors_origins),
        allow_credentials=True,
        allow_methods=_csv(app_settings.cors_allow_methods),
        allow_headers=_csv(app_settings.cors_allow_headers),
    )
    app.add_middleware(RequestIDMiddleware)

    # Include routers
    app.include_router(router)
    app.include_router(ask_router, prefix=app_settings.api_prefix)
    app.include_router(demo_router, prefix=app_settings.api_prefix)
    app.include_router(graph_router, prefix=app_settings.api_prefix)
    app.include_router(quiz_router, prefix=app_settings.api_prefix)
    app.include_router(learning_path_router, prefix=app_settings.api_prefix)
    app.include_router(subjects_router, prefix=app_settings.api_prefix)

    return app


app = create_app()
