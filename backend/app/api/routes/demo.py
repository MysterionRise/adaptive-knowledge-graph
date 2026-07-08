"""
Client-demo readiness endpoints.

These endpoints expose a bounded, read-only summary of local demo health without
leaking secrets, file paths, or raw driver errors.
"""

import json
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.core.exceptions import safe_error_message
from backend.app.core.settings import settings
from backend.app.core.subjects import get_all_subjects

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
    except Exception as e:
        return DemoServiceStatus(status="error", message=safe_error_message(e))


async def _check_opensearch() -> DemoServiceStatus:
    """Check OpenSearch cluster health."""
    start = time.perf_counter()
    protocol = "https" if settings.opensearch_use_ssl else "http"
    url = f"{protocol}://{settings.opensearch_host}:{settings.opensearch_port}/_cluster/health"

    try:
        async with httpx.AsyncClient(
            verify=settings.opensearch_verify_certs,
            timeout=5.0,
        ) as client:
            auth = (
                (settings.opensearch_user, settings.opensearch_password)
                if settings.opensearch_password
                else None
            )
            response = await client.get(url, auth=auth)
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
    except Exception as e:
        return DemoServiceStatus(status="error", message=safe_error_message(e))


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
    except Exception as e:
        return DemoServiceStatus(status="error", message=safe_error_message(e))


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
            except Exception as e:
                statuses.append(
                    DemoSubjectStatus(
                        id=subject.id,
                        name=subject.name,
                        status="error",
                        message=safe_error_message(e),
                    )
                )
    except Exception as e:
        statuses.append(
            DemoSubjectStatus(
                id="subjects",
                name="Subject configuration",
                status="error",
                message=safe_error_message(e),
            )
        )
    return statuses


def _latest_eval_status(path: Path = Path("docs/evals/latest.json")) -> DemoEvalStatus:
    """Read latest eval summary without exposing local paths."""
    if not path.exists():
        return DemoEvalStatus(status="missing", message="No latest eval report found.")

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        summary = report.get("summary", {})
        environment_valid = bool(report.get("environment_valid"))
        kg_successful = int(summary.get("kg_successful_cases", 0) or 0)
        plain_successful = int(summary.get("plain_successful_cases", 0) or 0)
        status: DemoStatus = (
            "ok" if environment_valid and kg_successful > 0 and plain_successful > 0 else "error"
        )
        return DemoEvalStatus(
            status=status,
            environment_valid=environment_valid,
            generated_at=report.get("generated_at"),
            cases=int(summary.get("cases", 0) or 0),
            kg_successful_cases=kg_successful,
            plain_successful_cases=plain_successful,
            citation_hit_rate_delta=summary.get("citation_hit_rate_delta"),
            mrr_delta=summary.get("mrr_delta"),
            unsupported_refusal_rate=summary.get("kg_unsupported_refusal_rate"),
            message=None
            if status == "ok"
            else "Latest eval is missing successful live KG/plain cases.",
        )
    except Exception as e:
        return DemoEvalStatus(status="error", message=safe_error_message(e))


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
