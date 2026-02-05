"""API routes module."""

from backend.app.api.routes import (
    ask_router,
    graph_router,
    learning_path_router,
    quiz_router,
    subjects_router,
)

__all__ = [
    "ask_router",
    "graph_router",
    "quiz_router",
    "learning_path_router",
    "subjects_router",
]
