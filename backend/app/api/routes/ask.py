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
from dataclasses import dataclass, field
from typing import Literal

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
from backend.app.rag.kg_expansion import get_kg_expander, get_known_concepts
from backend.app.rag.retriever import get_retriever
from backend.app.rag.trace import NO_TRACE, RetrievalTrace
from backend.app.rag.trace import sources as trace_sources

router = APIRouter(tags=["Q&A"])

EMPTY_ANSWER_DETAIL = "The language model returned an empty answer"
_SOURCE_PREVIEW_CHARS = 200

# What KG expansion did for a request:
#   ok       - concepts from the question were found in the graph and added to the
#              keyword query
#   empty    - the graph was queried, but no concept in the question matched or had neighbours
#   failed   - a Neo4j error (or a graph with no concepts) stopped expansion; the request
#              continues with plain retrieval
#   disabled - expansion was off for the request (use_kg_expansion=false or RAG_KG_EXPANSION)
KGExpansionStatus = Literal["ok", "empty", "failed", "disabled"]
KG_EXPANSION_STATUS_DESCRIPTION = (
    "KG expansion outcome: ok (concepts added), empty (no matching concepts), failed (a "
    "graph error: the subject's concepts could not be loaded or a neighbour lookup failed; "
    "retrieval used the question plus any concepts found before the error) or disabled."
)


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
    include_trace: bool | None = Field(
        default=None,
        description=(
            "Return the retrieval trace: each stage (resolve, expand, knn, bm25, fuse, "
            "window, rerank, select) with its timing, the channel ranks and the fusion "
            "contributions. Default: on for /retrieve, off for /ask and /ask/stream."
        ),
    )


class ResolvedTerm(BaseModel):
    """A span of the question and the concept it resolved to (#212)."""

    surface: str  # the span as the question has it
    canonical: str | None  # the concept; None when the span is ambiguous
    via: Literal["name", "alias"]  # what the span matched in the concept lexicon
    strategy: str  # the extraction strategy that found the span (ner, yake, ensemble, simple)
    status: Literal["resolved", "ambiguous"]
    candidates: list[str] | None = None  # the concepts an ambiguous span could mean


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
                            "module_title": "Imperial Reforms and Colonial Protests, "
                            "1763-1774 - The Stamp Act and the Sons and Daughters of Liberty",
                            "chapter": "Imperial Reforms and Colonial Protests, 1763-1774",
                            "section": "The Stamp Act and the Sons and Daughters of Liberty",
                            "score": 0.89,
                        }
                    ],
                    "expanded_concepts": [
                        "taxation without representation",
                        "Boston Tea Party",
                        "Continental Congress",
                    ],
                    "kg_expansion_status": "ok",
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
    expanded_concepts: list[str] | None = None  # KG concepts the retrieval used
    related_concepts: list[str] | None = None  # Their graph neighbours, not used (#282)
    resolved_terms: list[ResolvedTerm] | None = None  # How the question's spans resolved
    kg_expansion_status: KGExpansionStatus = Field(description=KG_EXPANSION_STATUS_DESCRIPTION)
    retrieved_count: int
    window_expanded_count: int | None = None  # Chunks after window expansion
    model: str
    attribution: str
    trace: dict | None = None  # The retrieval trace when include_trace is on (#216)


class RetrieveResponse(BaseModel):
    """Response from the retrieval-only endpoint (no LLM call)."""

    question: str
    sources: list[dict]
    expanded_concepts: list[str] | None = None
    related_concepts: list[str] | None = None
    resolved_terms: list[ResolvedTerm] | None = None
    kg_expansion_status: KGExpansionStatus = Field(description=KG_EXPANSION_STATUS_DESCRIPTION)
    retrieved_count: int
    window_expanded_count: int | None = None
    trace: dict | None = None  # The retrieval trace; on unless include_trace is false (#216)


def _new_trace(body: QuestionRequest, request: Request, default: bool) -> RetrievalTrace:
    """The request's trace, keyed by its X-Request-ID, or NO_TRACE when tracing is off."""
    wanted = default if body.include_trace is None else body.include_trace
    if not wanted:
        return NO_TRACE
    return RetrievalTrace(getattr(request.state, "request_id", None))


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
        ctx = await _retrieve_context(body, _new_trace(body, request, default=False))
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
            related_concepts=ctx.related_concepts or None,
            resolved_terms=_terms(ctx.resolved_terms),
            kg_expansion_status=ctx.kg_expansion_status,
            retrieved_count=ctx.initial_count,
            window_expanded_count=ctx.window_expanded_count,
            model=answer_result["model"],
            attribution=subject_config.attribution,
            trace=ctx.trace.to_dict(),
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
    related_concepts: list[str]
    resolved_terms: list[dict]
    kg_expansion_status: KGExpansionStatus
    retrieved_chunks: list[dict]
    initial_count: int
    window_expanded_count: int | None
    trace: RetrievalTrace = NO_TRACE


def _terms(terms: list[dict]) -> list[ResolvedTerm] | None:
    return [ResolvedTerm(**term) for term in terms] or None


def _format_sources(chunks: list[dict]) -> list[dict]:
    """Build the client-facing source list, truncating each chunk's text for display.

    Each source names where it comes from: ``chapter`` (None outside chapters, and for
    chunks indexed before ingest kept titles), ``section`` (the module's title) and
    ``module_title`` (``"<chapter> - <section>"``).
    """
    return [
        {
            "text": chunk["text"][:_SOURCE_PREVIEW_CHARS] + "..."
            if len(chunk["text"]) > _SOURCE_PREVIEW_CHARS
            else chunk["text"],
            "module_title": chunk.get("module_title"),
            "chapter": chunk.get("chapter"),
            "section": chunk.get("section"),
            "score": chunk.get("score", 0.0),
        }
        for chunk in chunks
    ]


def _sse_event(payload: dict) -> str:
    """Encode one server-sent event."""
    return f"data: {json.dumps(payload)}\n\n"


@dataclass
class _Expansion:
    """What KG expansion contributes to one question's retrieval."""

    concepts: list[str]  # used by the retrieval (the keyword channel)
    related: list[str]  # graph neighbours of the recognised concepts, for display
    keyword_query: str  # BM25 text: the question plus ``concepts``
    status: KGExpansionStatus
    terms: list[dict] = field(default_factory=list)  # how the question's spans resolved


def _expand_query(subject_id: str, question: str, trace: RetrievalTrace = NO_TRACE) -> _Expansion:
    """Expand the question with KG concepts for the keyword channel (blocking: Neo4j + NLP)."""
    all_concepts = get_known_concepts(subject_id)
    if not all_concepts:
        # Neo4j was unreachable or the subject's graph is empty: expansion could not run
        logger.warning("KG expansion failed: no concepts loaded for subject {}", subject_id)
        return _Expansion([], [], question, "failed")

    expander = get_kg_expander(subject_id)
    expansion_result = expander.expand_query(question, all_concepts, trace=trace)
    expanded_concepts: list[str] = expansion_result["expanded_concepts"]
    related: list[str] = expansion_result.get("related_concepts") or []
    logger.info(
        f"KG Expansion: {len(expansion_result['extracted_concepts'])} recognised -> "
        f"{len(expanded_concepts)} used, {len(related)} related"
    )
    status: KGExpansionStatus
    if expansion_result.get("failed_lookups", 0):
        status = "failed"
    elif expanded_concepts:
        status = "ok"
    else:
        status = "empty"
    return _Expansion(
        expanded_concepts,
        related,
        expansion_result["expanded_query"],
        status,
        expansion_result.get("resolved_terms") or [],
    )


def _retrieve_chunks(
    subject_id: str,
    query: str,
    top_k: int,
    keyword_query: str | None = None,
    trace: RetrievalTrace = NO_TRACE,
) -> list[dict]:
    """Retrieve chunks from OpenSearch (blocking: embedding + search).

    The kNN channel embeds ``query`` (the question); ``keyword_query`` (the question plus
    KG expansion terms) goes to the BM25 channel.
    """
    retriever = get_retriever(subject_id)
    return retriever.retrieve(query, top_k=top_k, keyword_query=keyword_query, trace=trace)


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
            "module_title": r.get("module_title"),
            "chapter": r.get("chapter"),
            "section": r.get("section"),
            "score": 1.0,
            "chunk_count": r.get("chunk_count", 1),
        }
        for r in window_results
    ]
    return expanded_chunks, sum(r.get("chunk_count", 1) for r in window_results)


async def _retrieve_context(
    body: QuestionRequest, trace: RetrievalTrace = NO_TRACE
) -> _RetrievalContext:
    """Shared retrieval logic for the ask, streaming and retrieval-only endpoints.

    ``trace`` records each stage (#216); the retrieval is the same with it or NO_TRACE.
    """
    subject_config = get_subject_or_404(body.subject)
    subject_id = subject_config.id

    # Step 1: Knowledge Graph Expansion (keyword channel only, #282)
    expansion = _Expansion([], [], body.question, "disabled")

    if body.use_kg_expansion and settings.rag_kg_expansion:
        try:
            expansion = await run_in_threadpool(_expand_query, subject_id, body.question, trace)
        except Exception as e:
            expansion = _Expansion([], [], body.question, "failed")
            logger.warning("KG expansion failed, continuing without it: {}", e)

    # Step 2: Retrieve chunks
    retrieval_top_k = settings.rag_retrieval_top_k if settings.reranker_enabled else body.top_k
    keyword_query = expansion.keyword_query if expansion.keyword_query != body.question else None
    retrieved_chunks = await run_in_threadpool(
        _retrieve_chunks, subject_id, body.question, retrieval_top_k, keyword_query, trace
    )

    if not retrieved_chunks:
        raise ContentNotFoundError("No relevant content found for this question")

    initial_count = len(retrieved_chunks)
    window_expanded_count = None

    # Step 2b: Window expansion
    with trace.stage("window") as stage:
        stage["ran"] = False
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
                    logger.info(
                        f"Window expansion: {initial_count} -> {window_expanded_count} chunks"
                    )
                    stage.update(
                        ran=True, chunks_in=initial_count, chunks_out=window_expanded_count
                    )
            except Exception as e:
                logger.warning("Window retrieval failed, using original chunks: {}", e)

    # Step 2c: Rerank chunks (if enabled)
    with trace.stage("rerank") as stage:
        stage["ran"] = settings.reranker_enabled
        if settings.reranker_enabled:
            retrieved_chunks = await run_in_threadpool(
                _maybe_rerank, body.question, retrieved_chunks, body.top_k
            )
            stage["order"] = [chunk.get("id") for chunk in retrieved_chunks]

    with trace.stage("select") as stage:
        stage["sources"] = trace_sources(retrieved_chunks)

    return _RetrievalContext(
        subject_config=subject_config,
        expanded_concepts=expansion.concepts,
        related_concepts=expansion.related,
        resolved_terms=expansion.terms,
        kg_expansion_status=expansion.status,
        retrieved_chunks=retrieved_chunks,
        initial_count=initial_count,
        window_expanded_count=window_expanded_count,
        trace=trace,
    )


async def _retrieve_context_or_http_error(
    body: QuestionRequest, label: str, trace: RetrievalTrace = NO_TRACE
) -> _RetrievalContext:
    """Run retrieval and map its failures to HTTP errors (streaming and retrieval-only)."""
    try:
        return await _retrieve_context(body, trace)
    except HTTPException:
        raise
    except ContentNotFoundError:
        raise HTTPException(
            status_code=404, detail="No relevant content found for this question"
        ) from None
    except (LLMGenerationError, LLMConnectionError) as e:
        logger.exception("LLM error in {}: {}", label, e)
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable") from e
    except aiohttp.ClientError as e:
        logger.exception("Service connection error in {}: {}", label, e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        logger.exception("Error in {}: {}", label, e)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    responses=error_responses(404, 429, 503),
)
@limiter.limit(settings.rate_limit_ask)
async def retrieve_sources(body: QuestionRequest, request: Request):
    """
    Run the /ask retrieval pipeline without calling the LLM.

    KG expansion, OpenSearch retrieval, window expansion and reranking behave exactly as in
    /ask, and the response carries the same sources. Used by
    `scripts/evaluate_rag.py --retrieval-only` for cheap retrieval comparisons; it shares
    the /ask rate limit (RATE_LIMIT_ASK) and access rules. The response carries the
    retrieval trace unless `include_trace` is false.

    Errors: 404 unknown subject or no relevant content, 422 invalid input (including
    HTML markup), 503 search backend unavailable.
    """
    ensure_no_markup(body.question, field="question")
    ctx = await _retrieve_context_or_http_error(
        body, "retrieval-only request", _new_trace(body, request, default=True)
    )
    return RetrieveResponse(
        question=body.question,
        sources=_format_sources(ctx.retrieved_chunks),
        expanded_concepts=ctx.expanded_concepts or None,
        related_concepts=ctx.related_concepts or None,
        resolved_terms=_terms(ctx.resolved_terms),
        kg_expansion_status=ctx.kg_expansion_status,
        retrieved_count=ctx.initial_count,
        window_expanded_count=ctx.window_expanded_count,
        trace=ctx.trace.to_dict(),
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
    ctx = await _retrieve_context_or_http_error(
        body, "streaming ask retrieval", _new_trace(body, request, default=False)
    )

    subject_config = ctx.subject_config
    sources = _format_sources(ctx.retrieved_chunks)
    llm_client = get_llm_client()
    context_texts = [chunk["text"] for chunk in ctx.retrieved_chunks]

    metadata: dict = {
        "type": "metadata",
        "sources": sources,
        "expanded_concepts": ctx.expanded_concepts or None,
        "related_concepts": ctx.related_concepts or None,
        "resolved_terms": ctx.resolved_terms or None,
        "kg_expansion_status": ctx.kg_expansion_status,
        "retrieved_count": ctx.initial_count,
        "window_expanded_count": ctx.window_expanded_count,
        "model": llm_client.model_name,
        "attribution": subject_config.attribution,
    }
    trace = ctx.trace.to_dict()
    if trace is not None:  # include_trace: the metadata event carries it
        metadata["trace"] = trace

    async def event_stream():
        # First event: metadata
        yield _sse_event(metadata)

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
