"""
API routes for the application.

Includes Q&A, graph queries, and other endpoints.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from backend.app.core.settings import settings
from backend.app.nlp.llm_client import get_llm_client
from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j, get_kg_expander
from backend.app.rag.retriever import get_retriever

router = APIRouter()


# Request/Response models
class QuestionRequest(BaseModel):
    """Request for Q&A endpoint."""

    question: str = Field(..., description="User's question", min_length=3)
    use_kg_expansion: bool = Field(
        default=True, description="Use knowledge graph expansion"
    )
    top_k: int = Field(default=5, description="Number of chunks to retrieve", ge=1, le=20)


class QuestionResponse(BaseModel):
    """Response from Q&A endpoint."""

    question: str
    answer: str
    sources: List[Dict]
    expanded_concepts: Optional[List[str]] = None
    retrieved_count: int
    model: str
    attribution: str


class GraphStatsResponse(BaseModel):
    """Response for graph statistics."""

    concept_count: int
    module_count: int
    relationship_count: int


# Q&A Endpoint
@router.post("/ask", response_model=QuestionResponse)
async def ask_question(request: QuestionRequest):
    """
    Answer a question using KG-aware RAG.

    This is the main demo endpoint that showcases:
    1. Knowledge graph query expansion (if enabled)
    2. Semantic retrieval from Qdrant
    3. LLM-based answer generation
    4. OpenStax attribution
    """
    try:
        logger.info(f"Question: {request.question}")

        # Step 1: Knowledge Graph Expansion (if enabled)
        expanded_concepts = []
        query = request.question

        if request.use_kg_expansion and settings.rag_kg_expansion:
            try:
                all_concepts = get_all_concepts_from_neo4j()
                if all_concepts:
                    expander = get_kg_expander()
                    expansion_result = expander.expand_query(request.question, all_concepts)

                    expanded_concepts = expansion_result["expanded_concepts"]
                    query = expansion_result["expanded_query"]

                    logger.info(
                        f"KG Expansion: {len(expansion_result['extracted_concepts'])} -> "
                        f"{len(expanded_concepts)} concepts"
                    )
            except Exception as e:
                logger.warning(f"KG expansion failed, continuing without it: {e}")

        # Step 2: Retrieve relevant chunks
        retriever = get_retriever()
        retrieved_chunks = retriever.retrieve(query, top_k=request.top_k)

        if not retrieved_chunks:
            raise HTTPException(
                status_code=404,
                detail="No relevant content found for this question",
            )

        # Step 3: Generate answer using LLM
        llm_client = get_llm_client()
        context_texts = [chunk["text"] for chunk in retrieved_chunks]

        answer_result = await llm_client.answer_question(
            question=request.question,
            context=context_texts,
            attribution=settings.attribution_openstax,
        )

        # Step 4: Format response
        sources = [
            {
                "text": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"],
                "module_title": chunk.get("module_title"),
                "section": chunk.get("section"),
                "score": chunk.get("score", 0.0),
            }
            for chunk in retrieved_chunks
        ]

        return QuestionResponse(
            question=request.question,
            answer=answer_result["answer"],
            sources=sources,
            expanded_concepts=expanded_concepts if expanded_concepts else None,
            retrieved_count=len(retrieved_chunks),
            model=answer_result["model"],
            attribution=settings.attribution_openstax,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ask endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
            relationship_count=sum(
                v for k, v in stats.items() if k.endswith("_relationships")
            ),
        )

    except Exception as e:
        logger.error(f"Error getting graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/concepts/top", response_model=List[Dict])
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
        raise HTTPException(status_code=500, detail=str(e))
