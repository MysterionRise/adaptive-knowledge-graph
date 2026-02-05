"""
Main FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from enum import Enum
from typing import Literal

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

from backend.app.api import (
    ask_router,
    graph_router,
    learning_path_router,
    quiz_router,
    subjects_router,
)
from backend.app.core.logging import setup_logging
from backend.app.core.rate_limit import limiter, rate_limit_exceeded_handler
from backend.app.core.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    setup_logging()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"LLM Mode: {settings.llm_mode}")
    logger.info(f"Privacy Local-Only: {settings.privacy_local_only}")
    logger.info(f"Rate Limiting: {'enabled' if settings.rate_limit_enabled else 'disabled'}")
    logger.info(f"API Key Auth: {'enabled' if settings.api_key else 'disabled (dev mode)'}")

    yield

    # Shutdown
    logger.info("Shutting down application")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="PoC Adaptive Knowledge Graph in Education",
    lifespan=lifespan,
)

# Add rate limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "llm_mode": settings.llm_mode,
        "privacy_local_only": settings.privacy_local_only,
    }


@app.get("/health")
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
    import time

    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        start = time.perf_counter()
        adapter = Neo4jAdapter()
        adapter.connect()

        # Run a simple query to verify
        with adapter.driver.session() as session:
            result = session.run("RETURN 1 as n")
            _ = list(result)

        latency = (time.perf_counter() - start) * 1000
        adapter.close()

        return ServiceHealth(status=ServiceStatus.OK, latency_ms=round(latency, 2))

    except Exception as e:
        logger.warning(f"Neo4j health check failed: {e}")
        return ServiceHealth(status=ServiceStatus.ERROR, message=str(e)[:100])


async def check_opensearch_health() -> ServiceHealth:
    """Check OpenSearch connectivity."""
    import time

    try:
        start = time.perf_counter()

        # Use httpx for async HTTP request
        protocol = "https" if settings.opensearch_use_ssl else "http"
        url = f"{protocol}://{settings.opensearch_host}:{settings.opensearch_port}/_cluster/health"

        async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
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
        logger.warning(f"OpenSearch health check failed: {e}")
        return ServiceHealth(status=ServiceStatus.ERROR, message=str(e)[:100])


async def check_ollama_health() -> ServiceHealth:
    """Check Ollama LLM service connectivity."""
    import time

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
        logger.warning(f"Ollama health check failed: {e}")
        return ServiceHealth(status=ServiceStatus.ERROR, message=str(e)[:100])


@app.get("/health/ready", response_model=ReadinessResponse)
async def health_ready():
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
    import asyncio

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
        else:
            overall_status = "degraded"
    else:
        overall_status = "degraded"

    return ReadinessResponse(
        status=overall_status,
        services=services,
        attribution=settings.attribution_openstax,
    )


@app.get("/health/live")
async def health_live():
    """
    Liveness check endpoint.

    Simple check that the API process is running.
    Used by Kubernetes liveness probes.
    """
    return {"status": "alive"}


# Include routers
app.include_router(ask_router, prefix=settings.api_prefix)
app.include_router(graph_router, prefix=settings.api_prefix)
app.include_router(quiz_router, prefix=settings.api_prefix)
app.include_router(learning_path_router, prefix=settings.api_prefix)
app.include_router(subjects_router, prefix=settings.api_prefix)
