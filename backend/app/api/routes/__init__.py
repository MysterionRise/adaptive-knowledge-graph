"""
API route modules.

This package contains the API endpoints split into logical modules:
- ask: Q&A endpoint with KG-aware RAG
- graph: Knowledge graph queries and visualization data
- quiz: Quiz generation endpoints
- learning_path: Prerequisite chains and learning paths
- subjects: Subject configuration and management
"""

from backend.app.api.routes.ask import router as ask_router
from backend.app.api.routes.graph import router as graph_router
from backend.app.api.routes.learning_path import router as learning_path_router
from backend.app.api.routes.quiz import router as quiz_router
from backend.app.api.routes.subjects import router as subjects_router

__all__ = [
    "ask_router",
    "graph_router",
    "quiz_router",
    "learning_path_router",
    "subjects_router",
]
