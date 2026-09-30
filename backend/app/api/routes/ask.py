"""
Q&A endpoint with KG-aware RAG.

Supports enterprise patterns:
- Window retrieval via NEXT relationships
- Unified vector+graph queries (when vector_backend=neo4j/hybrid)
- SSE streaming for real-time token delivery

Retrieval is synchronous (Neo4j, spaCy/YAKE, OpenSearch + embeddings, reranker), so it
runs in the threadpool to keep the event loop free.
"""

import json
from dataclasses import dataclass

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.api.validators import (
    QuestionStr,
    SubjectId,
    ensure_no_markup,
    error_responses,
    get_subject_or_404,
)
from backend.app.core.exceptions import ContentNotFoundError, LLMConnectionError, LLMGenerationError
from backend.app.core.rate_limit import limiter
from backend.app.core.settings import settings
from backend.app.core.subjects import SubjectConfig
from backend.app.nlp.llm_client import get_llm_client
from backend.app.rag.kg_expansion import get_all_concepts_from_neo4j, get_kg_expander
from backend.app.rag.retriever import get_retriever

router = APIRouter(tags=["Q&A"])

EMPTY_ANSWER_DETAIL = "The language model returned an empty answer"
_SOURCE_PREVIEW_CHARS = 200


def _maybe_rerank(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Rerank chunks if reranker is enabled, otherwise pass through."""
    if not settings.reranker_enabled:
        return chunks

    try:
        from backend.app.rag.reranker import get_reranker

        reranker = get_reranker()
        if not reranker.is_loaded:
            reranker.load()
        reranked = reranker.rerank(query, chunks, top_k)
        logger.info(f"Reranked {len(chunks)} chunks, kept top {len(reranked)}")
        return reranked
    except Exception as e:
        logger.warning("Reranking failed, using original chunks: {}", e)
        return chunks


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

    question: QuestionStr = Field(
        ...,
        description=(
            "User's question: 3-2000 characters after trimming whitespace. "
            "HTML or script markup is rejected."
        ),
    )
    subject: SubjectId | None = Field(
        default=None,
        description=(
            "Subject ID (e.g., 'us_history', 'biology'). "
            "Defaults to the configured default subject."
        ),
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

    question: str  # The validated (trimmed, markup-free) question
    answer: str
    sources: list[dict]
    expanded_concepts: list[str] | None = None
    retrieved_count: int
    window_expanded_count: int | None = None  # Chunks after window expansion
    model: str
    attribution: str


@router.post(
    "/ask",
    response_model=QuestionResponse,
    responses=error_responses(404, 429, 502, 503),
)
@limiter.limit(settings.rate_limit_ask)
async def ask_question(body: QuestionRequest, request: Request):
    """
    Answer a question using KG-aware RAG.

    This is the main demo endpoint that showcases:
    1. Knowledge graph query expansion (if enabled)
    2. Semantic retrieval from OpenSearch
    3. LLM-based answer generation
    4. Subject-specific attribution and prompts

    Errors: 404 unknown subject or no relevant content, 422 invalid input (including
    HTML markup), 502 empty LLM answer, 503 LLM or search backend unavailable.
    """
    ensure_no_markup(body.question, field="question")
    try:
        logger.info("Question: {} (subject: {})", body.question, body.subject or "default")
        ctx = await _retrieve_context(body)
        subject_config = ctx.subject_config

        # Step 3: Generate answer using LLM with subject-specific prompts
        llm_client = get_llm_client()
        context_texts = [chunk["text"] for chunk in ctx.retrieved_chunks]

        answer_result = await llm_client.answer_question(
            question=body.question,
            context=context_texts,
            attribution=subject_config.attribution,
            system_prompt=subject_config.prompts.system_prompt,
            context_label=subject_config.prompts.context_label,
        )

        answer = answer_result.get("answer") or ""
        if not answer.strip():
            logger.warning("LLM returned an empty answer")
            raise HTTPException(status_code=502, detail=EMPTY_ANSWER_DETAIL)

        # Step 4: Format response
        return QuestionResponse(
            question=body.question,
            answer=answer,
            sources=_format_sources(ctx.retrieved_chunks),
            expanded_concepts=ctx.expanded_concepts or None,
            retrieved_count=ctx.initial_count,
            window_expanded_count=ctx.window_expanded_count,
            model=answer_result["model"],
            attribution=subject_config.attribution,
        )

    except HTTPException:
        raise
    except ContentNotFoundError:
        raise HTTPException(
            status_code=404, detail="No relevant content found for this question"
        ) from None
    except (LLMGenerationError, LLMConnectionError) as e:
        logger.exception("LLM generation failed: {}", e)
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable") from e
    except aiohttp.ClientError as e:
        logger.exception("Service connection error: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        logger.exception("Error in ask endpoint: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@dataclass
class _RetrievalContext:
    """Retrieval results shared by the regular and streaming endpoints."""

    subject_config: SubjectConfig
    expanded_concepts: list[str]
    retrieved_chunks: list[dict]
    initial_count: int
    window_expanded_count: int | None


def _format_sources(chunks: list[dict]) -> list[dict]:
    """Build the client-facing source list, truncating each chunk's text for display."""
    return [
        {
            "text": chunk["text"][:_SOURCE_PREVIEW_CHARS] + "..."
            if len(chunk["text"]) > _SOURCE_PREVIEW_CHARS
            else chunk["text"],
            "module_title": chunk.get("module_title"),
            "section": chunk.get("section"),
            "score": chunk.get("score", 0.0),
        }
        for chunk in chunks
    ]


def _sse_event(payload: dict) -> str:
    """Encode one server-sent event."""
    return f"data: {json.dumps(payload)}\n\n"


def _expand_query(subject_id: str, question: str) -> tuple[list[str], str]:
    """Expand the question with related KG concepts (blocking: Neo4j + NLP)."""
    all_concepts = get_all_concepts_from_neo4j(subject_id)
    if not all_concepts:
        return [], question

    expander = get_kg_expander(subject_id)
    expansion_result = expander.expand_query(question, all_concepts)
    expanded_concepts: list[str] = expansion_result["expanded_concepts"]
    logger.info(
        f"KG Expansion: {len(expansion_result['extracted_concepts'])} -> "
        f"{len(expanded_concepts)} concepts"
    )
    return expanded_concepts, expansion_result["expanded_query"]


def _retrieve_chunks(subject_id: str, query: str, top_k: int) -> list[dict]:
    """Retrieve chunks from OpenSearch (blocking: embedding + search)."""
    retriever = get_retriever(subject_id)
    return retriever.retrieve(query, top_k=top_k)


def _expand_window(chunks: list[dict], window_size: int) -> tuple[list[dict], int | None]:
    """
    Replace retrieved chunks with their NEXT-window context (blocking: Neo4j).

    Returns the chunks to use and the number of chunks after expansion, or the
    original chunks and ``None`` when there is nothing to expand.
    """
    from backend.app.rag.window_retriever import get_window_retriever

    window_retriever = get_window_retriever()
    chunk_ids: list[str] = [c["id"] for c in chunks if c.get("id")]
    if not chunk_ids:
        return chunks, None

    window_results = window_retriever.retrieve_window_text(
        chunk_ids=chunk_ids,
        window_size=window_size,
    )
    if not window_results:
        return chunks, None

    expanded_chunks = [
        {
            "text": r["text"],
            "module_id": r.get("module_id"),
            "section": r.get("section"),
            "score": 1.0,
            "chunk_count": r.get("chunk_count", 1),
        }
        for r in window_results
    ]
    return expanded_chunks, sum(r.get("chunk_count", 1) for r in window_results)


async def _retrieve_context(body: QuestionRequest) -> _RetrievalContext:
    """Shared retrieval logic for both regular and streaming ask endpoints."""
    subject_config = get_subject_or_404(body.subject)
    subject_id = subject_config.id

    # Step 1: Knowledge Graph Expansion
    expanded_concepts: list[str] = []
    query = body.question

    if body.use_kg_expansion and settings.rag_kg_expansion:
        try:
            expanded_concepts, query = await run_in_threadpool(
                _expand_query, subject_id, body.question
            )
        except Exception as e:
            logger.warning("KG expansion failed, continuing without it: {}", e)

    # Step 2: Retrieve chunks
    retrieval_top_k = settings.rag_retrieval_top_k if settings.reranker_enabled else body.top_k
    retrieved_chunks = await run_in_threadpool(_retrieve_chunks, subject_id, query, retrieval_top_k)

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
            retrieved_chunks, window_expanded_count = await run_in_threadpool(
                _expand_window, retrieved_chunks, body.window_size
            )
            if window_expanded_count is not None:
                logger.info(f"Window expansion: {initial_count} -> {window_expanded_count} chunks")
        except Exception as e:
            logger.warning("Window retrieval failed, using original chunks: {}", e)

    # Step 2c: Rerank chunks (if enabled)
    if settings.reranker_enabled:
        retrieved_chunks = await run_in_threadpool(
            _maybe_rerank, body.question, retrieved_chunks, body.top_k
        )

    return _RetrievalContext(
        subject_config=subject_config,
        expanded_concepts=expanded_concepts,
        retrieved_chunks=retrieved_chunks,
        initial_count=initial_count,
        window_expanded_count=window_expanded_count,
    )


@router.post(
    "/ask/stream",
    responses={
        200: {
            "description": (
                "Server-sent events: one `metadata` event, then `token` events, an `error` "
                "event if generation fails or the answer is empty, and finally `[DONE]`."
            ),
            "content": {"text/event-stream": {}},
        },
        **error_responses(404, 429, 503),
    },
)
@limiter.limit(settings.rate_limit_ask)
async def ask_question_stream(body: QuestionRequest, request: Request):
    """
    Answer a question using KG-aware RAG with SSE streaming.

    Streams tokens as they arrive from the LLM. Sends metadata
    (sources, expanded_concepts) as the first SSE event, then
    streams answer tokens, and finally sends a [DONE] event.
    If the LLM fails mid-stream or produces an empty answer, an
    `error` event is sent before [DONE].
    """
    ensure_no_markup(body.question, field="question")
    try:
        ctx = await _retrieve_context(body)
    except HTTPException:
        raise
    except ContentNotFoundError:
        raise HTTPException(
            status_code=404, detail="No relevant content found for this question"
        ) from None
    except (LLMGenerationError, LLMConnectionError) as e:
        logger.exception("LLM error in streaming ask retrieval: {}", e)
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable") from e
    except aiohttp.ClientError as e:
        logger.exception("Service connection error in streaming ask retrieval: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        logger.exception("Error in streaming ask retrieval: {}", e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    subject_config = ctx.subject_config
    sources = _format_sources(ctx.retrieved_chunks)
    llm_client = get_llm_client()
    context_texts = [chunk["text"] for chunk in ctx.retrieved_chunks]

    async def event_stream():
        # First event: metadata
        yield _sse_event(
            {
                "type": "metadata",
                "sources": sources,
                "expanded_concepts": ctx.expanded_concepts or None,
                "retrieved_count": ctx.initial_count,
                "window_expanded_count": ctx.window_expanded_count,
                "model": llm_client.model_name,
                "attribution": subject_config.attribution,
            }
        )

        # Stream answer tokens
        received_text = False
        stream_failed = False
        client_disconnected = False
        try:
            async for token in llm_client.answer_question_stream(
                question=body.question,
                context=context_texts,
                attribution=subject_config.attribution,
                system_prompt=subject_config.prompts.system_prompt,
                context_label=subject_config.prompts.context_label,
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected during streaming")
                    client_disconnected = True
                    break
                if isinstance(token, str) and token.strip():
                    received_text = True
                yield _sse_event({"type": "token", "content": token})
        except Exception as e:
            stream_failed = True
            logger.exception("Streaming LLM error: {}", e)
            yield _sse_event({"type": "error", "content": "An error occurred during streaming"})

        if not (received_text or stream_failed or client_disconnected):
            logger.warning("LLM stream produced an empty answer")
            yield _sse_event({"type": "error", "content": EMPTY_ANSWER_DETAIL})

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
