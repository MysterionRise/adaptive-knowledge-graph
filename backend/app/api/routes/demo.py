"""
Client-demo readiness endpoints.

These endpoints expose a bounded, read-only summary of local demo health without
leaking secrets, file paths, or raw driver errors: failures are reported with fixed
messages, and the underlying error is only logged. /demo/provenance, which names the exact
build, models and settings, requires the API key when one is configured.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.app.api.validators import error_responses
from backend.app.core.auth import verify_api_key
from backend.app.core.eval_report import as_dict, is_set, provenance_errors, report_errors
from backend.app.core.settings import settings
from backend.app.core.subjects import SubjectConfig, get_all_subjects

router = APIRouter(prefix="/demo", tags=["Demo Readiness"])


DemoStatus = Literal["ok", "degraded", "error", "missing"]


class DemoServiceStatus(BaseModel):
    """Readiness status for one demo dependency."""

    status: DemoStatus
    message: str | None = None
    latency_ms: float | None = None


class DemoSubjectStatus(BaseModel):
    """Indexed graph status for a subject."""

    id: str
    name: str
    status: DemoStatus
    concept_count: int = 0
    module_count: int = 0
    relationship_count: int = 0
    message: str | None = None


class DemoEvalStatus(BaseModel):
    """Latest live evaluation status."""

    status: DemoStatus
    environment_valid: bool = False
    generated_at: str | None = None
    cases: int = 0
    kg_successful_cases: int = 0
    plain_successful_cases: int = 0
    citation_hit_rate_delta: float | None = None
    mrr_delta: float | None = None
    unsupported_refusal_rate: float | None = None
    prompt_injection_resistance_rate: float | None = None
    kg_expansion_failures: int | None = None
    has_provenance: bool = False
    git_sha: str | None = None
    golden_set_sha256: str | None = None
    message: str | None = None


class DemoStatusResponse(BaseModel):
    """Aggregated local client-demo readiness."""

    status: Literal["ready", "degraded", "not_ready"]
    positioning: str
    services: dict[str, DemoServiceStatus]
    subjects: list[DemoSubjectStatus]
    latest_eval: DemoEvalStatus
    script_readiness: dict[str, bool]
    next_actions: list[str]


async def _check_neo4j() -> DemoServiceStatus:
    """Check Neo4j through the app adapter."""
    start = time.perf_counter()
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        adapter = get_neo4j_adapter()
        stats = adapter.get_graph_stats()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        concept_count = int(stats.get("Concept_count", 0))
        if concept_count == 0:
            return DemoServiceStatus(
                status="degraded",
                message="Connected, but no default-subject graph concepts were found.",
                latency_ms=latency_ms,
            )
        return DemoServiceStatus(status="ok", latency_ms=latency_ms)
    except Exception:
        logger.opt(exception=True).warning("Demo status: Neo4j check failed")
        return DemoServiceStatus(status="error", message="Neo4j unavailable")


async def _opensearch_get(path: str) -> httpx.Response:
    """GET ``path`` from OpenSearch with the configured TLS settings and credentials."""
    protocol = "https" if settings.opensearch_use_ssl else "http"
    url = f"{protocol}://{settings.opensearch_host}:{settings.opensearch_port}/{path}"
    auth = (
        (settings.opensearch_user, settings.opensearch_password)
        if settings.opensearch_password
        else None
    )
    async with httpx.AsyncClient(verify=settings.opensearch_verify_certs, timeout=5.0) as client:
        return await client.get(url, auth=auth)


async def _check_opensearch() -> DemoServiceStatus:
    """Check OpenSearch cluster health."""
    start = time.perf_counter()
    try:
        response = await _opensearch_get("_cluster/health")
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        if response.status_code != 200:
            return DemoServiceStatus(
                status="error",
                message=f"HTTP {response.status_code}",
                latency_ms=latency_ms,
            )

        cluster_status = response.json().get("status", "unknown")
        if cluster_status == "green":
            return DemoServiceStatus(status="ok", latency_ms=latency_ms)
        if cluster_status == "yellow":
            return DemoServiceStatus(
                status="degraded",
                message="Cluster status: yellow",
                latency_ms=latency_ms,
            )
        return DemoServiceStatus(
            status="error",
            message=f"Cluster status: {cluster_status}",
            latency_ms=latency_ms,
        )
    except Exception:
        logger.opt(exception=True).warning("Demo status: OpenSearch check failed")
        return DemoServiceStatus(status="error", message="OpenSearch unavailable")


async def _check_ollama() -> DemoServiceStatus:
    """Check local Ollama model availability."""
    if settings.llm_mode != "local":
        return DemoServiceStatus(status="degraded", message=f"LLM mode is {settings.llm_mode}")

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.llm_ollama_host}/api/tags")
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        if response.status_code != 200:
            return DemoServiceStatus(
                status="error",
                message=f"HTTP {response.status_code}",
                latency_ms=latency_ms,
            )

        model_names = [m.get("name", "") for m in response.json().get("models", [])]
        if any(settings.llm_local_model in name for name in model_names):
            return DemoServiceStatus(status="ok", latency_ms=latency_ms)
        return DemoServiceStatus(
            status="degraded",
            message=f"Configured model not found: {settings.llm_local_model}",
            latency_ms=latency_ms,
        )
    except Exception:
        logger.opt(exception=True).warning("Demo status: Ollama check failed")
        return DemoServiceStatus(status="error", message="Ollama unavailable")


def _subject_statuses() -> list[DemoSubjectStatus]:
    """Get graph counts for configured demo subjects."""
    statuses: list[DemoSubjectStatus] = []
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        for subject in get_all_subjects():
            try:
                adapter = get_neo4j_adapter(subject.id)
                stats = adapter.get_graph_stats()
                relationship_count = sum(
                    int(value) for key, value in stats.items() if key.endswith("_relationships")
                )
                concept_count = int(stats.get("Concept_count", 0))
                statuses.append(
                    DemoSubjectStatus(
                        id=subject.id,
                        name=subject.name,
                        status="ok" if concept_count > 0 else "degraded",
                        concept_count=concept_count,
                        module_count=int(stats.get("Module_count", 0)),
                        relationship_count=relationship_count,
                        message=None
                        if concept_count > 0
                        else "Configured, but no graph concepts were found.",
                    )
                )
            except Exception:
                logger.opt(exception=True).warning(
                    "Demo status: graph statistics failed for subject {}", subject.id
                )
                statuses.append(
                    DemoSubjectStatus(
                        id=subject.id,
                        name=subject.name,
                        status="error",
                        message="Graph statistics unavailable",
                    )
                )
    except Exception:
        logger.opt(exception=True).warning("Demo status: subject configuration failed to load")
        statuses.append(
            DemoSubjectStatus(
                id="subjects",
                name="Subject configuration",
                status="error",
                message="Subject configuration could not be loaded",
            )
        )
    return statuses


# Error messages shown on the demo page for an invalid report (the rest are counted).
MAX_EVAL_ERRORS_SHOWN = 3


def _latest_eval_status(path: Path = Path("docs/evals/latest.json")) -> DemoEvalStatus:
    """Read latest eval summary without exposing local paths.

    A report counts ("ok") only when it passes the demo gate's rules (shared with
    scripts/check_demo_eval.py in backend/app/core/eval_report.py) and, when both SHAs are
    known, was produced by this server's build.
    """
    if not path.exists():
        return DemoEvalStatus(status="missing", message="No latest eval report found.")

    try:
        report = as_dict(json.loads(path.read_text(encoding="utf-8")))
        summary = as_dict(report.get("summary"))
        provenance = as_dict(report.get("provenance"))
        server = as_dict(provenance.get("server"))
        golden_set = as_dict(provenance.get("golden_set"))
        environment_valid = bool(report.get("environment_valid"))
        kg_failures = summary.get("kg_expansion_failures")

        errors = report_errors(report)
        report_sha = server.get("git_sha")
        if is_set(report_sha) and is_set(settings.git_sha) and report_sha != settings.git_sha:
            errors.append("it was produced by a different server build")
        message = None
        if errors:
            shown = "; ".join(errors[:MAX_EVAL_ERRORS_SHOWN])
            if len(errors) > MAX_EVAL_ERRORS_SHOWN:
                shown += f" (and {len(errors) - MAX_EVAL_ERRORS_SHOWN} more)"
            message = f"Latest eval is not demo-ready: {shown}. Re-run make demo-eval."
        status: DemoStatus = "ok" if message is None else "error"
        return DemoEvalStatus(
            status=status,
            environment_valid=environment_valid,
            generated_at=report.get("generated_at"),
            cases=int(summary.get("cases", 0) or 0),
            kg_successful_cases=int(summary.get("kg_successful_cases", 0) or 0),
            plain_successful_cases=int(summary.get("plain_successful_cases", 0) or 0),
            citation_hit_rate_delta=summary.get("citation_hit_rate_delta"),
            mrr_delta=summary.get("mrr_delta"),
            unsupported_refusal_rate=summary.get("kg_unsupported_refusal_rate"),
            prompt_injection_resistance_rate=summary.get("kg_prompt_injection_resistance_rate"),
            kg_expansion_failures=int(kg_failures) if kg_failures is not None else None,
            has_provenance=not provenance_errors(report),
            git_sha=str(server["git_sha"]) if server.get("git_sha") else None,
            golden_set_sha256=str(golden_set["sha256"]) if golden_set.get("sha256") else None,
            message=message,
        )
    except Exception:
        logger.opt(exception=True).warning("Demo status: latest eval report could not be read")
        return DemoEvalStatus(status="error", message="Latest eval report could not be read")


def _overall_status(
    services: dict[str, DemoServiceStatus],
    subjects: list[DemoSubjectStatus],
    latest_eval: DemoEvalStatus,
) -> Literal["ready", "degraded", "not_ready"]:
    critical_services = (services["neo4j"].status, services["opensearch"].status)
    has_indexed_subject = any(subject.status == "ok" for subject in subjects)
    if any(status == "error" for status in critical_services) or not has_indexed_subject:
        return "not_ready"
    if latest_eval.status != "ok" or services["ollama"].status != "ok":
        return "degraded"
    return "ready"


@router.get("/status", response_model=DemoStatusResponse)
async def get_demo_status():
    """
    Return local client-demo readiness for a seeded OpenStax demo.

    This endpoint is designed for demo operators and hides raw infrastructure
    details. It does not assert production readiness or compliance.
    """
    services = {
        "neo4j": await _check_neo4j(),
        "opensearch": await _check_opensearch(),
        "ollama": await _check_ollama(),
    }
    subjects = _subject_statuses()
    latest_eval = _latest_eval_status()
    overall = _overall_status(services, subjects, latest_eval)

    script_readiness = {
        "critical_services_ready": services["neo4j"].status == "ok"
        and services["opensearch"].status in ("ok", "degraded"),
        "local_llm_ready": services["ollama"].status == "ok",
        "openstax_subject_seeded": any(subject.status == "ok" for subject in subjects),
        "latest_eval_valid": latest_eval.status == "ok",
    }

    next_actions = []
    if not script_readiness["critical_services_ready"]:
        next_actions.append("Start Neo4j and OpenSearch, then run make demo-client-prep.")
    if not script_readiness["local_llm_ready"]:
        next_actions.append("Start Ollama and pull the configured local model.")
    if not script_readiness["openstax_subject_seeded"]:
        next_actions.append("Seed OpenStax demo data with make demo-client-prep.")
    if not script_readiness["latest_eval_valid"]:
        next_actions.append("Run make demo-eval after the API and demo data are available.")

    return DemoStatusResponse(
        status=overall,
        positioning="Controlled local OpenStax client demo; not production certification infrastructure.",
        services=services,
        subjects=subjects,
        latest_eval=latest_eval,
        script_readiness=script_readiness,
        next_actions=next_actions,
    )


# Retrieval settings reported by /demo/provenance. This is an explicit allowlist: settings
# also hold passwords and API keys, so they are never dumped wholesale.
PROVENANCE_RETRIEVAL_SETTINGS: tuple[str, ...] = (
    "retrieval_mode",
    "vector_backend",
    "rag_retrieval_top_k",
    "rag_kg_expansion",
    "rag_kg_expansion_hops",
    "rag_chunk_size",
    "rag_chunk_overlap",
    "rag_window_retrieval",
    "rag_window_size",
    "reranker_enabled",
    "embedding_batch_size",
    "neo4j_vector_dimension",
)


class ModelProvenance(BaseModel):
    """A model the retrieval pipeline loads."""

    model: str
    revision: str | None = None  # None: the model's default branch (not pinned)
    device: str  # configured device (auto, cuda, mps or cpu)
    resolved_device: str | None = None  # the device in use, once the model is loaded
    enabled: bool = True


class LLMProvenance(BaseModel):
    """The configured answer model and its sampling settings."""

    mode: str
    model: str
    temperature: float
    seed: int | None = None


class SubjectProvenance(BaseModel):
    """Data counts for one configured subject (None: the store could not be read)."""

    id: str
    concept_count: int | None = None
    chunk_count: int | None = None


class ProvenanceResponse(BaseModel):
    """What produced this server's answers: code, models, retrieval settings and data."""

    app_version: str
    git_sha: str
    embedding: ModelProvenance
    reranker: ModelProvenance
    llm: LLMProvenance
    retrieval: dict[str, str | int | float | bool | None]
    subjects: list[SubjectProvenance]


def _retrieval_settings() -> dict[str, str | int | float | bool | None]:
    """The allowlisted retrieval settings, by name."""
    return {name: getattr(settings, name) for name in PROVENANCE_RETRIEVAL_SETTINGS}


def _concept_count(subject_id: str) -> int | None:
    """Concepts in the subject's graph (blocking: Neo4j); None when Neo4j fails."""
    try:
        from backend.app.kg.neo4j_adapter import get_neo4j_adapter

        return get_neo4j_adapter(subject_id).count_concepts()
    except Exception:
        logger.opt(exception=True).warning(
            "Provenance: concept count failed for subject {}", subject_id
        )
        return None


async def _chunk_count(index: str) -> int | None:
    """Documents in an OpenSearch index (0 when it does not exist); None when it fails.

    Queries ``_count`` directly: the retriever would load the embedding model.
    """
    try:
        response = await _opensearch_get(f"{index}/_count")
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        return int(response.json()["count"])
    except Exception:
        logger.opt(exception=True).warning("Provenance: chunk count failed for index {}", index)
        return None


async def _subject_provenance(subject: SubjectConfig) -> SubjectProvenance:
    """A subject's concept and chunk counts, read concurrently."""
    concept_count, chunk_count = await asyncio.gather(
        run_in_threadpool(_concept_count, subject.id),
        _chunk_count(subject.database.opensearch_index),
    )
    return SubjectProvenance(id=subject.id, concept_count=concept_count, chunk_count=chunk_count)


@router.get(
    "/provenance",
    response_model=ProvenanceResponse,
    dependencies=[Depends(verify_api_key)],
    responses=error_responses(401, 429),
)
async def get_provenance():
    """
    Report what produces this server's answers, for evaluation reports.

    Covers the server's git SHA (`GIT_SHA`), the embedding and reranker models with their
    revisions and devices, the LLM and its sampling settings, an allowlist of retrieval
    settings and per-subject concept and chunk counts. It never includes credentials,
    hosts or file paths. Requires `X-API-Key` when an API key is configured. Read by
    `scripts/evaluate_rag.py`.
    """
    from backend.app.nlp.embeddings import loaded_embedding_device
    from backend.app.rag.reranker import loaded_reranker_device

    try:
        configured = get_all_subjects()
    except Exception:
        logger.opt(exception=True).warning("Provenance: subject configuration failed to load")
        configured = []
    subjects = list(await asyncio.gather(*(_subject_provenance(s) for s in configured)))

    return ProvenanceResponse(
        app_version=settings.app_version,
        git_sha=settings.git_sha,
        embedding=ModelProvenance(
            model=settings.embedding_model,
            revision=settings.embedding_model_revision,
            device=settings.embedding_device,
            resolved_device=loaded_embedding_device(),
        ),
        reranker=ModelProvenance(
            model=settings.reranker_model,
            revision=settings.reranker_model_revision,
            device=settings.reranker_device,
            resolved_device=loaded_reranker_device(),
            enabled=settings.reranker_enabled,
        ),
        llm=LLMProvenance(
            mode=settings.llm_mode,
            model=settings.openrouter_model
            if settings.llm_mode == "remote"
            else settings.llm_local_model,
            temperature=settings.llm_temperature,
            seed=settings.llm_seed,
        ),
        retrieval=_retrieval_settings(),
        subjects=subjects,
    )
