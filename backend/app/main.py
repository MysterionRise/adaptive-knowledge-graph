"""
Main FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.app.api.routes import router as api_router
from backend.app.core.logging import setup_logging
from backend.app.core.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    setup_logging()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"LLM Mode: {settings.llm_mode}")
    logger.info(f"Privacy Local-Only: {settings.privacy_local_only}")

    yield

    # Shutdown
    logger.info("Shutting down application")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="PoC Adaptive Knowledge Graph in Education",
    lifespan=lifespan,
)

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
    """Health check endpoint."""
    return {
        "status": "healthy",
        "attribution": settings.attribution_openstax,
    }


# Include routers
app.include_router(api_router, prefix=settings.api_prefix, tags=["Q&A and Graph"])
