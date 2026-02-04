"""
Q&A endpoint with KG-aware RAG.

Supports enterprise patterns:
- Window retrieval via NEXT relationships
- Unified vector+graph queries (when vector_backend=neo4j/hybrid)
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from backend.app.core.exceptions import ContentNotFoundError, LLMGenerationError
from backend.app.core.settings import settings
from backend.app.nlp.llm_client import get_llm_client
from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j, get_kg_expander
from backend.app.rag.retriever import get_retriever

router = APIRouter(tags=["Q&A"])


class QuestionRequest(BaseModel):
    """Request for Q&A endpoint."""

    question: str = Field(..., description="User's question", min_length=3)
    use_kg_expansion: bool = Field(default=True, description="Use knowledge graph expansion")
    use_window_retrieval: bool = Field(
        default=True, description="Include surrounding chunks via NEXT traversal"
    )
    window_size: int = Field(
        default=1, description="Chunks before/after to include in window", ge=0, le=3
    )
    top_k: int = Field(default=5, description="Number of chunks to retrieve", ge=1, le=20)


class QuestionResponse(BaseModel):
    """Response from Q&A endpoint."""

    question: str
    answer: str
    sources: list[dict]
    expanded_concepts: list[str] | None = None
    retrieved_count: int
    window_expanded_count: int | None = None  # Chunks after window expansion
    model: str
    attribution: str


@router.post("/ask", response_model=QuestionResponse)
async def ask_question(request: QuestionRequest):
    """
    Answer a question using KG-aware RAG.

    This is the main demo endpoint that showcases:
    1. Knowledge graph query expansion (if enabled)
    2. Semantic retrieval from OpenSearch
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
            raise ContentNotFoundError("No relevant content found for this question")

        initial_count = len(retrieved_chunks)
        window_expanded_count = None

        # Step 2b: Window expansion via NEXT relationships (enterprise pattern)
        if (
            request.use_window_retrieval
            and settings.rag_window_retrieval
            and settings.vector_backend in ("neo4j", "hybrid")
        ):
            try:
                from backend.app.rag.window_retriever import get_window_retriever

                window_retriever = get_window_retriever()
                chunk_ids = [c.get("id") for c in retrieved_chunks if c.get("id")]

                if chunk_ids:
                    window_results = window_retriever.retrieve_window_text(
                        chunk_ids=chunk_ids,
                        window_size=request.window_size,
                    )

                    # Replace retrieved chunks with window-expanded results
                    if window_results:
                        retrieved_chunks = [
                            {
                                "text": r["text"],
                                "module_id": r.get("module_id"),
                                "section": r.get("section"),
                                "score": 1.0,  # Window chunks don't have scores
                                "chunk_count": r.get("chunk_count", 1),
                            }
                            for r in window_results
                        ]
                        window_expanded_count = sum(r.get("chunk_count", 1) for r in window_results)
                        logger.info(
                            f"Window expansion: {initial_count} -> {window_expanded_count} chunks"
                        )
            except Exception as e:
                logger.warning(f"Window retrieval failed, using original chunks: {e}")

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
            retrieved_count=initial_count,
            window_expanded_count=window_expanded_count,
            model=answer_result["model"],
            attribution=settings.attribution_openstax,
        )

    except ContentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except LLMGenerationError as e:
        logger.error(f"LLM generation failed: {e}")
        raise HTTPException(status_code=503, detail=f"LLM service error: {str(e)}") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ask endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") from e
