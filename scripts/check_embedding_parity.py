"""
Check that the installed embedding stack reproduces the vectors stored in a subject's index.

Run it after upgrading transformers, sentence-transformers, huggingface-hub, tokenizers or
torch (#71, #79), against an index that the previous stack built. It reads a fixed sample of
chunks (the lowest --sample chunk ids), re-embeds their text with the installed stack and
compares each new vector with the stored one by cosine similarity.

Exit status 1 when the lowest similarity is below --threshold (default 0.999). The index then
needs new embeddings: re-run ``make index-rag`` (plus ``make build-windows`` when window
retrieval is used) and attach a ``make eval-compare`` delta to the upgrade.

--reranker also smoke-tests the cross-encoder: each of the first 5 sampled chunks is queried
with its own opening words and must rank first among those 5, for at least 4 of them.

The report lists the library versions, the inference device and the model revisions (the
configured one and the one cached under refs/main), which is what a revision pin needs.

Usage:
    poetry run python scripts/check_embedding_parity.py --subject us_history
    poetry run python scripts/check_embedding_parity.py --subject economics --reranker --json
    make embedding-parity SUBJECT=us_history RERANKER=1
"""

import argparse
import json
import math
from collections.abc import Callable, Sequence
from importlib import metadata
from typing import Any

from backend.app.core.privacy import hf_hub_cache_dir
from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject

DEFAULT_SAMPLE = 50
DEFAULT_THRESHOLD = 0.999
RERANK_CANDIDATES = 5
RERANK_REQUIRED_HITS = 4
QUERY_WORDS = 12
WORST_SHOWN = 5
LIBRARIES = (
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "tokenizers",
    "safetensors",
    "torch",
)

Encode = Callable[[list[str]], list[list[float]]]
Rerank = Callable[[str, list[dict[str, Any]], int], list[dict[str, Any]]]


def sample_chunks(client: Any, index: str, size: int) -> list[dict[str, Any]]:
    """The first ``size`` chunks by id that have both text and a stored vector."""
    response = client.search(
        index=index,
        body={
            "size": size,
            "query": {"match_all": {}},
            "sort": [{"id": "asc"}],
            "_source": ["id", "text", "embedding"],
        },
    )
    chunks = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        if source.get("text") and source.get("embedding"):
            chunks.append(
                {
                    "id": source.get("id") or hit.get("_id"),
                    "text": source["text"],
                    "embedding": source["embedding"],
                }
            )
    return chunks


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is empty, zero or of another length."""
    if len(a) != len(b) or not a:
        return 0.0
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def compare(chunks: list[dict[str, Any]], encode: Encode, threshold: float) -> dict[str, Any]:
    """Re-embed the chunks and compare each new vector with the stored one."""
    vectors = encode([chunk["text"] for chunk in chunks])
    scores = sorted(
        (
            (cosine(chunk["embedding"], vector), str(chunk["id"]))
            for chunk, vector in zip(chunks, vectors, strict=True)
        ),
    )
    values = [score for score, _ in scores]
    lowest = values[0] if values else None
    return {
        "chunks": len(values),
        "min_cosine": lowest,
        "mean_cosine": sum(values) / len(values) if values else None,
        "below_threshold": sum(1 for value in values if value < threshold),
        "worst": [{"id": chunk_id, "cosine": score} for score, chunk_id in scores[:WORST_SHOWN]],
        "passed": lowest is not None and lowest >= threshold,
    }


def rerank_smoke(chunks: list[dict[str, Any]], rerank: Rerank) -> dict[str, Any]:
    """Each candidate, queried with its own opening words, should rank first."""
    candidates = [{"id": chunk["id"], "text": chunk["text"]} for chunk in chunks]
    candidates = candidates[:RERANK_CANDIDATES]
    results = []
    for candidate in candidates:
        query = " ".join(candidate["text"].split()[:QUERY_WORDS])
        ranked = rerank(query, candidates, len(candidates))
        top = ranked[0]["id"] if ranked else None
        results.append({"id": candidate["id"], "top": top, "hit": top == candidate["id"]})
    hits = sum(1 for result in results if result["hit"])
    required = min(RERANK_REQUIRED_HITS, len(candidates))
    return {
        "candidates": len(candidates),
        "hits": hits,
        "required": required,
        "results": results,
        "passed": len(candidates) > 0 and hits >= required,
    }


def cached_revision(model: str) -> str | None:
    """The commit that refs/main points to in the Hugging Face cache, if the model is cached."""
    ref = hf_hub_cache_dir() / f"models--{model.replace('/', '--')}" / "refs" / "main"
    try:
        return ref.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _print_report(report: dict[str, Any]) -> None:
    parity = report["parity"]
    print(f"Embedding parity for {report['subject']} (index {report['index']})")
    print(f"  model: {report['embedding']['model']} on {report['embedding']['device']}")
    print(
        f"  revision: configured {report['embedding']['configured_revision']}, "
        f"cached {report['embedding']['cached_revision']}"
    )
    print("  libraries: " + ", ".join(f"{k} {v}" for k, v in report["libraries"].items()))
    if parity["min_cosine"] is not None:
        print(
            f"  {parity['chunks']} chunks: min cosine {parity['min_cosine']:.6f}, "
            f"mean {parity['mean_cosine']:.6f}, {parity['below_threshold']} below "
            f"{report['threshold']}"
        )
        for worst in parity["worst"]:
            print(f"    {worst['id']}: {worst['cosine']:.6f}")
    reranker = report.get("reranker")
    if reranker:
        print(
            f"  reranker {reranker['model']} (cached revision {reranker['cached_revision']}): "
            f"{reranker['hits']}/{reranker['candidates']} chunks ranked first by their own "
            f"opening words (need {reranker['required']})"
        )
    print("PASS" if report["passed"] else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare re-embedded chunks with the index")
    parser.add_argument("--subject", default=None, help="Subject id (default subject if unset)")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--reranker", action="store_true", help="Smoke-test the cross-encoder")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)

    # Imported here: building the retriever loads the embedding model
    from backend.app.rag.reranker import get_reranker
    from backend.app.rag.retriever import OpenSearchRetriever

    subject = get_subject(args.subject)
    index = subject.database.opensearch_index
    retriever = OpenSearchRetriever(index_name=index)
    retriever.connect()
    chunks = sample_chunks(retriever.client, index, args.sample)
    if not chunks:
        print(f"No chunks with stored vectors in {index}; seed it first (make seed)")
        return 2

    model = retriever.embedding_model
    parity = compare(
        chunks, lambda texts: model.encode(texts, normalize=True), threshold=args.threshold
    )
    report: dict[str, Any] = {
        "subject": subject.id,
        "index": index,
        "threshold": args.threshold,
        "embedding": {
            "model": model.model_name,
            "device": model.device,
            "configured_revision": settings.embedding_model_revision,
            "cached_revision": cached_revision(model.model_name),
        },
        "libraries": library_versions(),
        "parity": parity,
    }
    passed = bool(parity["passed"])

    if args.reranker:
        reranker = get_reranker()
        reranker.load()
        smoke = rerank_smoke(chunks, reranker.rerank)
        report["reranker"] = {
            "model": settings.reranker_model,
            "device": reranker.device,
            "configured_revision": settings.reranker_model_revision,
            "cached_revision": cached_revision(settings.reranker_model),
            **smoke,
        }
        passed = passed and bool(smoke["passed"])

    report["passed"] = passed
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
