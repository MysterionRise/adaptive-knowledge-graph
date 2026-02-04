"""
Custom exceptions for the Adaptive Knowledge Graph application.
"""


class AdaptiveKGException(Exception):
    """Base exception for the application."""

    pass


class Neo4jConnectionError(AdaptiveKGException):
    """Failed to connect to Neo4j."""

    pass


class Neo4jQueryError(AdaptiveKGException):
    """Failed to execute Neo4j query."""

    pass


class OpenSearchConnectionError(AdaptiveKGException):
    """Failed to connect to OpenSearch."""

    pass


class OpenSearchQueryError(AdaptiveKGException):
    """Failed to execute OpenSearch query."""

    pass


class LLMGenerationError(AdaptiveKGException):
    """LLM failed to generate response."""

    pass


class LLMConnectionError(AdaptiveKGException):
    """Failed to connect to LLM service."""

    pass


class QuizGenerationError(AdaptiveKGException):
    """Failed to generate quiz."""

    pass


class ContentNotFoundError(AdaptiveKGException):
    """No relevant content found for the query."""

    pass
