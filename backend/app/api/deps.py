"""
FastAPI dependency injection providers.

Provides factory functions for retrieving service instances:
- Retriever: For RAG document retrieval
- LLM Client: For language model interactions
- Quiz Generator: For generating quizzes
- Neo4j Adapter: For graph database operations
- KG Expander: For knowledge graph query expansion

Using dependency injection instead of global singletons improves:
- Testability: Easy to mock services in tests
- Thread safety: Each request gets its own instance if needed
- Configurability: Can swap implementations easily
"""

from typing import Annotated

from fastapi import Depends

from backend.app.core.auth import RequireApiKey, verify_api_key


def get_retriever():
    """
    Get the RAG retriever instance.

    Yields:
        Retriever instance for document retrieval
    """
    from backend.app.rag.retriever import get_retriever as _get_retriever

    return _get_retriever()


def get_llm_client():
    """
    Get the LLM client instance.

    Yields:
        LLM client for answer generation
    """
    from backend.app.nlp.llm_client import get_llm_client as _get_llm_client

    return _get_llm_client()


def get_quiz_generator():
    """
    Get the quiz generator instance.

    Yields:
        Quiz generator for creating quizzes
    """
    from backend.app.student.quiz_generator import get_quiz_generator as _get_quiz_generator

    return _get_quiz_generator()


def get_neo4j_adapter():
    """
    Get a Neo4j adapter instance.

    Note: The adapter needs to be connected and closed by the caller.

    Yields:
        Neo4j adapter for graph operations
    """
    from backend.app.kg.neo4j_adapter import Neo4jAdapter

    adapter = Neo4jAdapter()
    try:
        adapter.connect()
        yield adapter
    finally:
        adapter.close()


def get_kg_expander():
    """
    Get the knowledge graph query expander.

    Yields:
        KG expander for query enhancement
    """
    from backend.app.rag.kg_expansion import get_kg_expander as _get_kg_expander

    return _get_kg_expander()


def get_cypher_qa_service():
    """
    Get the Cypher QA service for natural language graph queries.

    Yields:
        Cypher QA service instance
    """
    from backend.app.kg.cypher_qa import get_cypher_qa_service as _get_cypher_qa_service

    return _get_cypher_qa_service()


# Type aliases for dependency injection
Retriever = Annotated[object, Depends(get_retriever)]
LLMClient = Annotated[object, Depends(get_llm_client)]
QuizGenerator = Annotated[object, Depends(get_quiz_generator)]
KGExpander = Annotated[object, Depends(get_kg_expander)]
CypherQAService = Annotated[object, Depends(get_cypher_qa_service)]


def require_auth() -> str:
    """
    Dependency that requires API key authentication.

    Use this to protect endpoints that require authentication.

    Usage:
        @router.get("/protected", dependencies=[Depends(require_auth)])
        async def protected_endpoint():
            ...

    Or directly in the function:
        @router.get("/protected")
        async def protected_endpoint(api_key: RequireApiKey):
            ...

    Returns:
        The validated API key
    """
    return Depends(verify_api_key)  # type: ignore[no-any-return]


# Re-export auth dependencies for convenience
__all__ = [
    "get_retriever",
    "get_llm_client",
    "get_quiz_generator",
    "get_neo4j_adapter",
    "get_kg_expander",
    "get_cypher_qa_service",
    "Retriever",
    "LLMClient",
    "QuizGenerator",
    "KGExpander",
    "CypherQAService",
    "RequireApiKey",
    "require_auth",
]
