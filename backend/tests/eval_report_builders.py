"""
Builders for evaluation reports (scripts/evaluate_rag.py, schema 2) shared by the tests.

``build_report()`` returns a complete, valid, demo-ready report: the server and harness ran
the same commit, and the golden-set hash is that of the committed golden set.
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import evaluate_rag

GOLDEN_SET_PATH = "data/evals/golden_qa.yaml"
SERVER_SHA = "a" * 40

SERVER_PROVENANCE: dict[str, Any] = {
    "app_version": "0.3.0",
    "git_sha": SERVER_SHA,
    "embedding": {
        "model": "BAAI/bge-m3",
        "revision": None,
        "device": "auto",
        "resolved_device": "cpu",
        "enabled": True,
    },
    "reranker": {
        "model": "BAAI/bge-reranker-v2-m3",
        "revision": None,
        "device": "cpu",
        "resolved_device": None,
        "enabled": False,
    },
    "llm": {"mode": "local", "model": "llama3.1:8b", "temperature": 0.0, "seed": 42},
    "retrieval": {"retrieval_mode": "hybrid", "rag_kg_expansion": True},
    "subjects": [
        {"id": "us_history", "concept_count": 120, "chunk_count": 900},
        {"id": "economics", "concept_count": 80, "chunk_count": 700},
    ],
}


def golden_set_sha256() -> str:
    return hashlib.sha256(Path(GOLDEN_SET_PATH).read_bytes()).hexdigest()


def mode_result(hit: bool | None = True, mrr: float = 1.0, **overrides: Any) -> dict[str, Any]:
    """One mode (kg or plain) of one case."""
    result = {
        "status_code": 200,
        "latency_ms": 10.0,
        "kg_expansion_status": "ok",
        "citation_hit": hit,
        "mrr": mrr if hit else 0.0,
        "answer_term_recall": 1.0,
        "sources": [{"module_title": "Chapter"}],
        "answer": "An answer",
    }
    result.update(overrides)
    return result


def case_result(case_id: str, subject: str = "us_history", **kg: Any) -> dict[str, Any]:
    """One case; keyword arguments override its KG-mode result."""
    return {
        "id": case_id,
        "subject": subject,
        "question": f"Question {case_id}?",
        "tags": ["answerable"],
        "case_hash": f"hash-{case_id}",
        "kg": mode_result(**kg),
        "plain": mode_result(kg_expansion_status="disabled"),
    }


def build_report(results: list[dict[str, Any]] | None = None, **run_config: Any) -> dict[str, Any]:
    """A complete report; keyword arguments override its run_config."""
    results = (
        results if results is not None else [case_result("c1"), case_result("c2", "economics")]
    )
    config = {"subjects": [], "limit": None, "retrieval_only": False, "partial": False}
    config.update(run_config)
    validity = evaluate_rag._validity(results, SERVER_PROVENANCE, ["us_history", "economics"])
    return {
        "schema_version": 2,
        "generated_at": "2026-10-05T12:00:00+00:00",
        "api_url": "http://localhost:8000",
        "environment_valid": validity["valid"],
        "validity": validity,
        "provenance": {
            "server": copy.deepcopy(SERVER_PROVENANCE),
            "llm": {"model": "llama3.1:8b", "ollama_digest": "sha256:abc"},
            "golden_set": {"path": GOLDEN_SET_PATH, "sha256": golden_set_sha256()},
            "harness": {"git_sha": SERVER_SHA},
        },
        "run_config": config,
        "summary": evaluate_rag._summarize(results),
        "results": results,
    }


def write_report(tmp_path: Path, report: dict[str, Any], name: str = "latest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(report), encoding="utf-8")
    return path
