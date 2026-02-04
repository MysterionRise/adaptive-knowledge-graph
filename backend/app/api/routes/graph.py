"""
Knowledge graph query and visualization endpoints.

Includes:
- Graph statistics and visualization data
- Natural language to Cypher (GraphCypherQAChain)
- Concept search with fulltext index
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from backend.app.core.exceptions import Neo4jConnectionError, Neo4jQueryError

router = APIRouter(tags=["Graph"])


class GraphStatsResponse(BaseModel):
    """Response for graph statistics."""

    concept_count: int
    module_count: int
    relationship_count: int


@router.get("/graph/stats", response_model=GraphStatsResponse)
async def get_graph_stats():
    """Get knowledge graph statistics."""
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        stats = adapter.get_graph_stats()
        adapter.close()

        return GraphStatsResponse(
            concept_count=stats.get("Concept_count", 0),
            module_count=stats.get("Module_count", 0),
            relationship_count=sum(v for k, v in stats.items() if k.endswith("_relationships")),
        )

    except Neo4jConnectionError as e:
        logger.error(f"Neo4j connection failed: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed") from e
    except Neo4jQueryError as e:
        logger.error(f"Neo4j query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/concepts/top", response_model=list[dict])
async def get_top_concepts(limit: int = 20):
    """Get top concepts by importance."""
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Concept)
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

        adapter.close()
        return concepts

    except Exception as e:
        logger.error(f"Error getting top concepts: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/graph/data")
async def get_graph_data(limit: int = 100):
    """
    Get graph data for visualization (concepts and relationships).

    This endpoint returns nodes and edges formatted for Cytoscape.js visualization.
    Limits to top N concepts by importance to prevent overwhelming the frontend.

    Args:
        limit: Maximum number of concepts to return (default 100)

    Returns:
        GraphData with nodes and edges arrays
    """
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            # Get top concepts by importance
            concept_result = session.run(
                """
                MATCH (c:Concept)
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
                    """
                    MATCH (c1:Concept)-[r]->(c2:Concept)
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

        adapter.close()

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

        return {"nodes": nodes, "edges": edges}

    except Exception as e:
        logger.error(f"Error getting graph data: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ==========================================================================
# Natural Language Graph Query (GraphCypherQAChain)
# ==========================================================================


class GraphQueryRequest(BaseModel):
    """Request for natural language graph query."""

    question: str = Field(..., description="Natural language question about the graph")
    preview_only: bool = Field(
        default=False, description="If True, generate Cypher without executing"
    )


class GraphQueryResponse(BaseModel):
    """Response from natural language graph query."""

    question: str
    cypher: str | None = None
    result: list | str | None = None
    answer: str | None = None
    error: str | None = None


@router.post("/graph/query", response_model=GraphQueryResponse)
async def query_graph_natural_language(request: GraphQueryRequest):
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
    """
    try:
        from backend.app.kg.cypher_qa import get_cypher_qa_service

        service = get_cypher_qa_service()

        if request.preview_only:
            # Generate Cypher without executing
            cypher = service.generate_cypher_only(request.question)
            return GraphQueryResponse(
                question=request.question,
                cypher=cypher,
                result=None,
                answer="Preview only - query not executed",
            )

        # Full query execution
        result = service.query(request.question)

        return GraphQueryResponse(
            question=result.get("question", request.question),
            cypher=result.get("cypher"),
            result=result.get("result"),
            answer=result.get("answer"),
            error=result.get("error"),
        )

    except Exception as e:
        logger.error(f"Graph query error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ==========================================================================
# Concept Search with Fulltext Index
# ==========================================================================


class ConceptSearchRequest(BaseModel):
    """Request for fuzzy concept search."""

    query: str = Field(..., description="Search query for concepts")
    limit: int = Field(default=10, description="Maximum results", ge=1, le=50)


class ConceptSearchResult(BaseModel):
    """A single concept search result."""

    name: str
    importance_score: float | None = None
    key_term: bool | None = None
    score: float  # Fulltext search score


@router.post("/concepts/search", response_model=list[ConceptSearchResult])
async def search_concepts(request: ConceptSearchRequest):
    """
    Search for concepts using fulltext index with fuzzy matching.

    Supports:
    - Partial matches
    - Fuzzy matching (typo tolerance)
    - Relevance ranking
    """
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        results = adapter.fulltext_concept_search(
            query_text=request.query,
            limit=request.limit,
        )

        adapter.close()

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
        logger.error(f"Concept search error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


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
        logger.error(f"Error getting graph schema: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
