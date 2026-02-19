"""
Q&A endpoint with KG-aware RAG.

Supports enterprise patterns:
- Window retrieval via NEXT relationships
- Unified vector+graph queries (when vector_backend=neo4j/hybrid)
- SSE streaming for real-time token delivery
"""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.app.core.exceptions import ContentNotFoundError, LLMGenerationError
from backend.app.core.rate_limit import limiter
from backend.app.core.settings import settings
from backend.app.nlp.llm_client import get_llm_client
from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j, get_kg_expander
from backend.app.rag.retriever import get_retriever

router = APIRouter(tags=["Q&A"])


class QuestionRequest(BaseModel):
    """Request for Q&A endpoint."""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "What caused the American Revolution?",
                    "subject": "us_history",
                    "use_kg_expansion": True,
                    "top_k": 5,
                }
            ]
        }
    }

    question: str = Field(..., description="User's question", min_length=3)
    subject: str | None = Field(
        default=None,
        description="Subject ID (e.g., 'us_history', 'biology'). Defaults to us_history.",
    )
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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "What caused the American Revolution?",
                    "answer": "The American Revolution was caused by a combination of factors...",
                    "sources": [
                        {
                            "text": "The colonists' growing dissatisfaction with British rule...",
                            "module_title": "The American Revolution",
                            "section": "Causes of the Revolution",
                            "score": 0.89,
                        }
                    ],
                    "expanded_concepts": [
                        "taxation without representation",
                        "Boston Tea Party",
                        "Continental Congress",
                    ],
                    "retrieved_count": 5,
                    "model": "llama3.1:8b-instruct-q4_K_M",
                    "attribution": "Content from OpenStax US History, CC BY 4.0",
                }
            ]
        }
    }

    question: str
    answer: str
    sources: list[dict]
    expanded_concepts: list[str] | None = None
    retrieved_count: int
    window_expanded_count: int | None = None  # Chunks after window expansion
    model: str
    attribution: str


@router.post("/ask", response_model=QuestionResponse)
@limiter.limit("10/minute")
async def ask_question(body: QuestionRequest, request: Request):
    """
    Answer a question using KG-aware RAG.

    This is the main demo endpoint that showcases:
    1. Knowledge graph query expansion (if enabled)
    2. Semantic retrieval from OpenSearch
    3. LLM-based answer generation
    4. Subject-specific attribution and prompts
    """
    try:
        logger.info(f"Question: {body.question} (subject: {body.subject or 'default'})")

        # Get subject configuration for prompts and attribution
        from backend.app.core.subjects import get_subject

        subject_config = get_subject(body.subject)
        subject_id = subject_config.id

        # Step 1: Knowledge Graph Expansion (if enabled)
        expanded_concepts = []
        query = body.question

        if body.use_kg_expansion and settings.rag_kg_expansion:
            try:
                all_concepts = get_all_concepts_from_neo4j(subject_id)
                if all_concepts:
                    expander = get_kg_expander(subject_id)
                    expansion_result = expander.expand_query(body.question, all_concepts)

                    expanded_concepts = expansion_result["expanded_concepts"]
                    query = expansion_result["expanded_query"]

                    logger.info(
                        f"KG Expansion: {len(expansion_result['extracted_concepts'])} -> "
                        f"{len(expanded_concepts)} concepts"
                    )
            except Exception as e:
                logger.warning(f"KG expansion failed, continuing without it: {e}")

        # Step 2: Retrieve relevant chunks from subject-specific index
        retriever = get_retriever(subject_id)
        retrieved_chunks = retriever.retrieve(query, top_k=body.top_k)

        if not retrieved_chunks:
            raise ContentNotFoundError("No relevant content found for this question")

        initial_count = len(retrieved_chunks)
        window_expanded_count = None

        # Step 2b: Window expansion via NEXT relationships (enterprise pattern)
        if (
            body.use_window_retrieval
            and settings.rag_window_retrieval
            and settings.vector_backend in ("neo4j", "hybrid")
        ):
            try:
                from backend.app.rag.window_retriever import get_window_retriever

                window_retriever = get_window_retriever()
                chunk_ids: list[str] = [c["id"] for c in retrieved_chunks if c.get("id")]

                if chunk_ids:
                    window_results = window_retriever.retrieve_window_text(
                        chunk_ids=chunk_ids,
                        window_size=body.window_size,
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

        # Step 3: Generate answer using LLM with subject-specific prompts
        llm_client = get_llm_client()
        context_texts = [chunk["text"] for chunk in retrieved_chunks]

        answer_result = await llm_client.answer_question(
            question=body.question,
            context=context_texts,
            attribution=subject_config.attribution,
            system_prompt=subject_config.prompts.system_prompt,
            context_label=subject_config.prompts.context_label,
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
            question=body.question,
            answer=answer_result["answer"],
            sources=sources,
            expanded_concepts=expanded_concepts if expanded_concepts else None,
            retrieved_count=initial_count,
            window_expanded_count=window_expanded_count,
            model=answer_result["model"],
            attribution=subject_config.attribution,
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


async def _retrieve_context(body: QuestionRequest):
    """Shared retrieval logic for both regular and streaming ask endpoints."""
    from backend.app.core.subjects import get_subject

    subject_config = get_subject(body.subject)
    subject_id = subject_config.id

    # Step 1: Knowledge Graph Expansion
    expanded_concepts: list[str] = []
    query = body.question

    if body.use_kg_expansion and settings.rag_kg_expansion:
        try:
            all_concepts = get_all_concepts_from_neo4j(subject_id)
            if all_concepts:
                expander = get_kg_expander(subject_id)
                expansion_result = expander.expand_query(body.question, all_concepts)
                expanded_concepts = expansion_result["expanded_concepts"]
                query = expansion_result["expanded_query"]
                logger.info(
                    f"KG Expansion: {len(expansion_result['extracted_concepts'])} -> "
                    f"{len(expanded_concepts)} concepts"
                )
        except Exception as e:
            logger.warning(f"KG expansion failed, continuing without it: {e}")

    # Step 2: Retrieve chunks
    retriever = get_retriever(subject_id)
    retrieved_chunks = retriever.retrieve(query, top_k=body.top_k)

    if not retrieved_chunks:
        raise ContentNotFoundError("No relevant content found for this question")

    initial_count = len(retrieved_chunks)
    window_expanded_count = None

    # Step 2b: Window expansion
    if (
        body.use_window_retrieval
        and settings.rag_window_retrieval
        and settings.vector_backend in ("neo4j", "hybrid")
    ):
        try:
            from backend.app.rag.window_retriever import get_window_retriever

            window_retriever = get_window_retriever()
            chunk_ids: list[str] = [c["id"] for c in retrieved_chunks if c.get("id")]

            if chunk_ids:
                window_results = window_retriever.retrieve_window_text(
                    chunk_ids=chunk_ids,
                    window_size=body.window_size,
                )
                if window_results:
                    retrieved_chunks = [
                        {
                            "text": r["text"],
                            "module_id": r.get("module_id"),
                            "section": r.get("section"),
                            "score": 1.0,
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

    return {
        "subject_config": subject_config,
        "expanded_concepts": expanded_concepts,
        "retrieved_chunks": retrieved_chunks,
        "initial_count": initial_count,
        "window_expanded_count": window_expanded_count,
    }


@router.post("/ask/stream")
@limiter.limit("10/minute")
async def ask_question_stream(body: QuestionRequest, request: Request):
    """
    Answer a question using KG-aware RAG with SSE streaming.

    Streams tokens as they arrive from the LLM. Sends metadata
    (sources, expanded_concepts) as the first SSE event, then
    streams answer tokens, and finally sends a [DONE] event.
    """
    try:
        ctx = await _retrieve_context(body)
    except ContentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error in streaming ask retrieval: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    subject_config = ctx["subject_config"]
    expanded_concepts = ctx["expanded_concepts"]
    retrieved_chunks = ctx["retrieved_chunks"]

    # Build sources list
    sources = [
        {
            "text": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"],
            "module_title": chunk.get("module_title"),
            "section": chunk.get("section"),
            "score": chunk.get("score", 0.0),
        }
        for chunk in retrieved_chunks
    ]

    llm_client = get_llm_client()
    context_texts = [chunk["text"] for chunk in retrieved_chunks]

    async def event_stream():
        # First event: metadata
        metadata = {
            "type": "metadata",
            "sources": sources,
            "expanded_concepts": expanded_concepts if expanded_concepts else None,
            "retrieved_count": ctx["initial_count"],
            "window_expanded_count": ctx["window_expanded_count"],
            "model": llm_client.model_name,
            "attribution": subject_config.attribution,
        }
        yield f"data: {json.dumps(metadata)}\n\n"

        # Stream answer tokens
        try:
            async for token in llm_client.answer_question_stream(
                question=body.question,
                context=context_texts,
                attribution=subject_config.attribution,
                system_prompt=subject_config.prompts.system_prompt,
                context_label=subject_config.prompts.context_label,
            ):
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        except Exception as e:
            logger.error(f"Streaming LLM error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        # Final event
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
