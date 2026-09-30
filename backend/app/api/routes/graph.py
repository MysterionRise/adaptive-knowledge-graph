"""
Knowledge graph query and visualization endpoints.

Includes:
- Graph statistics and visualization data
- Natural language to Cypher (GraphCypherQAChain)
- Concept search with fulltext index
"""

import re
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from backend.app.api.validators import (
    NonBlankStr,
    SearchQueryStr,
    SubjectParam,
    error_responses,
    escape_lucene,
)
from backend.app.core.auth import verify_api_key
from backend.app.core.exceptions import (
    LLMConnectionError,
    LLMGenerationError,
    Neo4jConnectionError,
    Neo4jQueryError,
)
from backend.app.core.rate_limit import limiter
from backend.app.core.settings import settings

_DESTRUCTIVE_VERBS = r"(?:delete|remove|drop|destroy|truncate|erase|wipe|purge|detach)"
_GRAPH_OBJECTS = (
    r"(?:nodes?|relationships?|rels?|edges?|labels?|propert(?:y|ies)|index(?:es)?|indices"
    r"|constraints?|databases?|db|graphs?|data|everything|concepts?|modules?|chunks?)"
)
_DETERMINERS = r"(?:all|every|each|any|a|an|the|these|those|this|that|of|existing|entire|whole)"
# Start of a Cypher node pattern: "(", an optional variable, then ":", ")" or "{"
_NODE_PATTERN = r"\(\s*(?:[a-z_]\w*)?\s*[:){]"

# Signals of a write or destructive request in a natural-language graph question.
# Questions that merely use these words ("What caused the drop in GDP?") do not match.
_DESTRUCTIVE_REQUEST_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        # Cypher write clauses typed into the question
        r"\bdetach\s+delete\b",
        r"\b(?:create|drop)\s+(?:(?:fulltext|vector|range|text|point|lookup|unique)\s+)?"
        r"(?:index|constraint|database)\b",
        rf"\b(?:create|merge)\s*{_NODE_PATTERN}",
        rf"\bmatch\s*{_NODE_PATTERN}.*\b(?:delete|set|remove|merge|create)\b",
        r"\b(?:set|remove)\s+[a-z_]\w*[.:][a-z_]",
        # Requests to destroy graph objects: "delete all nodes", "clear the database"
        rf"\b{_DESTRUCTIVE_VERBS}\s+(?:{_DETERMINERS}\s+){{0,3}}{_GRAPH_OBJECTS}\b",
        rf"\bclear\s+(?:{_DETERMINERS}\s+){{1,3}}{_GRAPH_OBJECTS}\b",
        # Imperatives that open with a destructive verb: "Remove the Photosynthesis concept"
        r"^\W*(?:please\s+|(?:can|could|would|will)\s+you\s+(?:please\s+)?"
        rf"|i\s+(?:want|need)\s+(?:you\s+)?to\s+|let'?s\s+)?{_DESTRUCTIVE_VERBS}\b",
    )
)

_READ_ONLY_DETAIL = "This endpoint only supports read queries against the knowledge graph."


def _is_destructive_request(question: str) -> bool:
    """Return True when a natural-language graph question asks for a write operation."""
    return any(pattern.search(question) for pattern in _DESTRUCTIVE_REQUEST_PATTERNS)


router = APIRouter(tags=["Knowledge Graph"])

# Simple TTL cache for graph endpoints (data doesn't change during demo)
_graph_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_get(key: str) -> object | None:
    """Get a value from the TTL cache, or None if expired/missing."""
    if key in _graph_cache:
        timestamp, value = _graph_cache[key]
        if time.time() - timestamp < _CACHE_TTL:
            return value
        del _graph_cache[key]
    return None


def _cache_set(key: str, value: object) -> None:
    """Store a value in the TTL cache."""
    _graph_cache[key] = (time.time(), value)


def clear_graph_cache() -> None:
    """Clear the graph data cache. Used in tests and after data updates."""
    _graph_cache.clear()


class GraphStatsResponse(BaseModel):
    """Response for graph statistics."""

    concept_count: int
    module_count: int
    relationship_count: int


@router.get(
    "/graph/stats",
    response_model=GraphStatsResponse,
    responses=error_responses(404, 429, 503),
)
@limiter.limit(settings.rate_limit_graph)
async def get_graph_stats(request: Request, subject: SubjectParam):
    """
    Get knowledge graph statistics.

    Args:
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.
    """
    cache_key = f"stats:{subject or 'default'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        adapter = get_neo4j_adapter(subject)
        stats = adapter.get_graph_stats()

        result = GraphStatsResponse(
            concept_count=stats.get("Concept_count", 0),
            module_count=stats.get("Module_count", 0),
            relationship_count=sum(v for k, v in stats.items() if k.endswith("_relationships")),
        )
        _cache_set(cache_key, result)
        return result

    except Neo4jConnectionError as e:
        logger.exception("Neo4j connection failed: {}", e)
        raise HTTPException(status_code=503, detail="Database connection failed") from e
    except Neo4jQueryError as e:
        logger.exception("Neo4j query failed: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
    except Exception as e:
        logger.exception("Error getting graph stats: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/concepts/top", response_model=list[dict], responses=error_responses(404))
async def get_top_concepts(
    subject: SubjectParam,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum number of concepts to return (1-100)")
    ] = 20,
):
    """
    Get top concepts by importance.

    Args:
        limit: Maximum number of concepts to return (1-100)
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.
    """
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        adapter = get_neo4j_adapter(subject)
        concept_label = adapter._get_label("Concept")

        with adapter._get_session() as session:
            result = session.run(
                f"""
                MATCH (c:{concept_label})
                RETURN c.name as name,
                       c.importance_score as score,
                       c.key_term as is_key_term,
                       c.frequency as frequency
                ORDER BY c.importance_score DESC
                LIMIT $limit
                """,
                limit=limit,
            )

            concepts = [dict(record) for record in result]

        return concepts

    except Exception as e:
        logger.exception("Error getting top concepts: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/graph/data", responses=error_responses(404, 429))
@limiter.limit(settings.rate_limit_graph)
async def get_graph_data(
    request: Request,
    subject: SubjectParam,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Maximum number of concepts to return (1-500)")
    ] = 100,
):
    """
    Get graph data for visualization (concepts and relationships).

    This endpoint returns nodes and edges formatted for Cytoscape.js visualization.
    Limits to top N concepts by importance to prevent overwhelming the frontend.

    Args:
        limit: Maximum number of concepts to return (1-500, default 100)
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.

    Returns:
        GraphData with nodes and edges arrays
    """
    cache_key = f"data:{subject or 'default'}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        adapter = get_neo4j_adapter(subject)
        concept_label = adapter._get_label("Concept")

        with adapter._get_session() as session:
            # Get top concepts by importance
            concept_result = session.run(
                f"""
                MATCH (c:{concept_label})
                RETURN elementId(c) as id,
                       c.name as label,
                       coalesce(c.importance_score, 0.5) as importance,
                       c.chapter as chapter,
                       c.key_term as is_key_term
                ORDER BY c.importance_score DESC
                LIMIT $limit
                """,
                limit=limit,
            )

            concepts = list(concept_result)
            concept_ids = [c["id"] for c in concepts]

            # Get relationships between these concepts
            if concept_ids:
                relationship_result = session.run(
                    f"""
                    MATCH (c1:{concept_label})-[r]->(c2:{concept_label})
                    WHERE elementId(c1) IN $ids AND elementId(c2) IN $ids
                    RETURN elementId(c1) as source,
                           elementId(c2) as target,
                           type(r) as type,
                           coalesce(r.weight, 1.0) as weight
                    """,
                    ids=concept_ids,
                )

                relationships = list(relationship_result)
            else:
                relationships = []

        # Format for Cytoscape
        nodes = [
            {
                "data": {
                    "id": concept["id"],
                    "label": concept["label"],
                    "importance": float(concept["importance"]),
                    "chapter": concept.get("chapter"),
                }
            }
            for concept in concepts
        ]

        edges = [
            {
                "data": {
                    "id": f"e{i}",
                    "source": rel["source"],
                    "target": rel["target"],
                    "type": rel["type"],
                    "label": rel["type"].lower().replace("_", " "),
                }
            }
            for i, rel in enumerate(relationships)
        ]

        logger.info(f"Returning graph data: {len(nodes)} nodes, {len(edges)} edges")

        result = {"nodes": nodes, "edges": edges}
        _cache_set(cache_key, result)
        return result

    except Exception as e:
        logger.exception("Error getting graph data: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


# ==========================================================================
# Natural Language Graph Query (GraphCypherQAChain)
# ==========================================================================


class GraphQueryRequest(BaseModel):
    """Request for natural language graph query."""

    question: NonBlankStr = Field(
        ..., description="Natural language question about the graph (1-2000 characters)"
    )
    preview_only: bool = Field(
        default=False, description="If True, generate Cypher without executing"
    )


class GraphQueryResponse(BaseModel):
    """Response from natural language graph query."""

    question: str
    cypher: str | None = None
    result: list | str | None = None
    answer: str | None = None


@router.post(
    "/graph/query",
    response_model=GraphQueryResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(400, 401, 429, 502, 503),
)
@limiter.limit(settings.rate_limit_graph_query)
async def query_graph_natural_language(request: Request, body: GraphQueryRequest):
    """
    Query the knowledge graph using natural language.

    Uses LangChain's GraphCypherQAChain to:
    1. Translate the question to Cypher
    2. Execute the query against Neo4j
    3. Return formatted results

    Examples:
    - "What concepts are prerequisites for Photosynthesis?"
    - "Which modules cover DNA replication?"
    - "Find the most important concepts"
    - "What concepts are related to mitosis?"

    Requests to modify the graph ("delete all nodes", raw Cypher write clauses)
    are rejected with 400. A query the model generated that Neo4j cannot run answers
    502; an unavailable LLM or Neo4j answers 503.
    """
    # Route-level guard: reject requests with obvious write/destructive intent
    if _is_destructive_request(body.question):
        raise HTTPException(status_code=400, detail=_READ_ONLY_DETAIL)

    # Imported here so LangChain loads only when the endpoint is used
    from backend.app.kg.cypher_qa import GeneratedCypherError, get_cypher_qa_service

    try:
        service = get_cypher_qa_service()

        if body.preview_only:
            # Generate Cypher without executing
            cypher = await run_in_threadpool(service.generate_cypher_only, body.question)
            return GraphQueryResponse(
                question=body.question,
                cypher=cypher,
                result=None,
                answer="Preview only - query not executed",
            )

        # Full query execution (LLM + Neo4j, blocking)
        result = await run_in_threadpool(service.query, body.question)

        return GraphQueryResponse(
            question=result.get("question", body.question),
            cypher=result.get("cypher"),
            result=result.get("result"),
            answer=result.get("answer"),
        )

    except ValidationError as e:
        # Malformed service output; must not be mistaken for a blocked query below
        logger.exception("Graph query returned an invalid result: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
    except ValueError as e:
        # CypherQAService raises CypherValidationError (a ValueError) for blocked queries
        logger.warning("Blocked graph query: {}", e)
        raise HTTPException(status_code=400, detail=_READ_ONLY_DETAIL) from e
    except Neo4jConnectionError as e:
        logger.exception("Neo4j unavailable for graph query: {}", e)
        raise HTTPException(status_code=503, detail="Database connection failed") from e
    except GeneratedCypherError as e:
        # Subclass of LLMGenerationError, so it must be caught before the 503 below
        logger.exception("The model generated a query Neo4j could not run: {}", e)
        raise HTTPException(status_code=502, detail="The model generated an invalid query") from e
    except (LLMGenerationError, LLMConnectionError) as e:
        logger.exception("LLM failed during graph query: {}", e)
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable") from e
    except Exception as e:
        logger.exception("Graph query error: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


# ==========================================================================
# Concept Search with Fulltext Index
# ==========================================================================


class ConceptSearchRequest(BaseModel):
    """Request for concept search."""

    query: SearchQueryStr = Field(
        ...,
        description=(
            "Search query for concepts (1-500 characters). Lucene syntax is matched literally."
        ),
    )
    limit: int = Field(default=10, description="Maximum results", ge=1, le=50)


class ConceptSearchResult(BaseModel):
    """A single concept search result."""

    name: str
    importance_score: float | None = None
    key_term: bool | None = None
    score: float  # Fulltext search score


@router.post(
    "/concepts/search",
    response_model=list[ConceptSearchResult],
    responses=error_responses(404),
)
async def search_concepts(body: ConceptSearchRequest, subject: SubjectParam):
    """
    Search for concepts using the fulltext index.

    Results are ranked by fulltext relevance. Lucene query syntax in the query
    (wildcards, fuzzy operators, field prefixes, boolean operators) is escaped, so the
    text is matched literally.

    Args:
        body: Search request with query and limit
        subject: Subject ID (e.g., 'us_history', 'biology'). Defaults to the default subject.
    """
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        adapter = get_neo4j_adapter(subject)

        results = adapter.fulltext_concept_search(
            query_text=escape_lucene(body.query),
            limit=body.limit,
        )

        return [
            ConceptSearchResult(
                name=r["name"],
                importance_score=r.get("importance_score"),
                key_term=r.get("key_term"),
                score=r.get("score", 0.0),
            )
            for r in results
        ]

    except Exception as e:
        logger.exception("Concept search error: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/graph/schema")
async def get_graph_schema():
    """
    Get the current knowledge graph schema.

    Returns node types, relationship types, and their properties.
    Useful for understanding the graph structure and writing queries.
    """
    try:
        from backend.app.kg.cypher_qa import get_cypher_qa_service

        service = get_cypher_qa_service()
        schema = service.get_schema()

        return {"schema": schema}

    except Exception as e:
        logger.exception("Error getting graph schema: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
