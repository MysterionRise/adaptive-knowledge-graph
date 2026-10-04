#!/usr/bin/env python3
"""
Build Neo4j chunk windows for one subject: Chunk nodes linked by NEXT edges (window retrieval),
FIRST_CHUNK edges from modules and MENTIONS edges to concepts.

Replaces scripts/migrate_to_enterprise.py, which read the pre-multi-subject index and ordered
chunks by sorting their ids as strings. For the chosen subject this script:
1. re-chunks data/processed/books_<subject>.jsonl with the chunker used by
   scripts/index_to_opensearch.py, so chunk ids match the OpenSearch documents and the chunker's
   own previous/next links give the reading order;
2. copies each chunk's embedding from the subject's OpenSearch index (skip with
   --skip-embeddings);
3. writes {prefix}_Chunk nodes, NEXT and FIRST_CHUNK edges, and MENTIONS edges to the
   {prefix}_Concept nodes whose name appears in the chunk text (word boundaries, any case);
4. creates the subject's chunk-id index and, when embeddings were copied, its vector index.

The API only uses these windows with VECTOR_BACKEND=neo4j or hybrid. Run it after `make seed`
(the graph and the OpenSearch index must exist); `build_knowledge_graph.py --clear` removes the
Chunk nodes again.

Usage:
    poetry run python scripts/build_chunk_windows.py --subject us_history
    poetry run python scripts/build_chunk_windows.py --subject economics --dry-run
    make build-windows SUBJECT=economics
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from opensearchpy import OpenSearch, helpers

from backend.app.core.settings import settings
from backend.app.core.subjects import SubjectConfig, get_subject
from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter
from backend.app.kg.schema import ChunkNode
from backend.app.rag.chunker import chunk_for_rag


def load_chunks(jsonl_path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Chunk the subject's records exactly like index_to_opensearch.py does."""
    with jsonl_path.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    chunked = chunk_for_rag(records, with_sequential_linking=True)
    if not isinstance(chunked, tuple):  # pragma: no cover - guarded by the flag above
        raise TypeError("chunk_for_rag did not return sequential links")
    chunks, first_chunks = chunked
    logger.info(f"Chunked {len(records)} records from {jsonl_path} into {len(chunks)} chunks")
    return chunks, first_chunks


def load_embeddings(subject: SubjectConfig, batch_size: int) -> dict[str, list[float]]:
    """Return {chunk id: embedding} for every document in the subject's OpenSearch index."""
    # A plain client with the retriever's connection settings: the retriever itself would load
    # the embedding model, which is not needed to copy stored vectors.
    client = OpenSearch(
        hosts=[{"host": settings.opensearch_host, "port": settings.opensearch_port}],
        http_compress=True,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
        ssl_show_warn=False,
        http_auth=(
            (settings.opensearch_user, settings.opensearch_password)
            if settings.opensearch_password
            else None
        ),
    )
    index_name = subject.database.opensearch_index
    if not client.indices.exists(index=index_name):
        raise SystemExit(
            f"OpenSearch index '{index_name}' does not exist; run: make seed SUBJECT={subject.id}"
        )

    embeddings: dict[str, list[float]] = {}
    for hit in helpers.scan(
        client,
        index=index_name,
        query={"query": {"match_all": {}}, "_source": ["embedding"]},
        size=batch_size,
    ):
        embedding = hit.get("_source", {}).get("embedding")
        if embedding:
            embeddings[hit["_id"]] = embedding
    logger.info(f"Loaded {len(embeddings)} embeddings from '{index_name}'")
    return embeddings


def find_mentions(chunks: list[dict[str, Any]], concepts: set[str]) -> list[tuple[str, str]]:
    """Return (chunk id, concept name) pairs for concept names found in each chunk's text."""
    patterns = [
        (name, re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE))
        for name in sorted(concepts)
        if name.strip()
    ]
    mentions = [
        (chunk["id"], name)
        for chunk in chunks
        for name, pattern in patterns
        if pattern.search(chunk["text"])
    ]
    logger.info(f"Found {len(mentions)} chunk-concept mentions")
    return mentions


def to_chunk_nodes(
    chunks: list[dict[str, Any]], embeddings: dict[str, list[float]]
) -> list[ChunkNode]:
    return [
        ChunkNode(
            chunk_id=chunk["id"],
            text=chunk["text"],
            chunk_index=chunk.get("chunk_index", 0),
            start_char=chunk.get("start_char", 0),
            end_char=chunk.get("end_char", len(chunk["text"])),
            module_id=chunk.get("module_id"),
            section=chunk.get("section"),
            text_embedding=embeddings.get(chunk["id"]),
            previous_chunk_id=chunk.get("previous_chunk_id"),
            next_chunk_id=chunk.get("next_chunk_id"),
        )
        for chunk in chunks
    ]


def load_concepts(adapter: Neo4jAdapter) -> set[str]:
    concept_label = adapter._get_label("Concept")
    with adapter._get_session() as session:
        result = session.run(f"MATCH (c:{concept_label}) RETURN c.name AS name")
        return {record["name"] for record in result if record["name"]}


def verify(adapter: Neo4jAdapter) -> None:
    """Log the resulting counts and one sample window."""
    chunk_label = adapter._get_label("Chunk")
    with adapter._get_session() as session:
        counts = session.run(
            f"""
            MATCH (c:{chunk_label})
            OPTIONAL MATCH (c)-[n:NEXT]->(:{chunk_label})
            WITH count(DISTINCT c) AS chunks, count(n) AS next_edges
            OPTIONAL MATCH (:{chunk_label})-[m:MENTIONS]->()
            RETURN chunks, next_edges, count(m) AS mentions
            """
        ).single()
        sample = session.run(
            f"""
            MATCH (prev:{chunk_label})-[:NEXT]->(c:{chunk_label})-[:NEXT]->(next:{chunk_label})
            RETURN prev.chunkId AS prev_id, c.chunkId AS chunk_id, next.chunkId AS next_id
            LIMIT 1
            """
        ).single()
    if counts:
        logger.info(
            f"{chunk_label}: {counts['chunks']} nodes, {counts['next_edges']} NEXT edges, "
            f"{counts['mentions']} MENTIONS edges"
        )
    if sample:
        logger.info(
            f"Sample window: {sample['prev_id']} -> {sample['chunk_id']} -> {sample['next_id']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Neo4j chunk windows (NEXT edges)")
    parser.add_argument("--subject", default=None, help="Subject ID (defaults to us_history)")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing to Neo4j")
    parser.add_argument("--batch-size", type=int, default=100, help="Neo4j write batch size")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Do not copy embeddings from OpenSearch (no Neo4j vector search)",
    )
    parser.add_argument(
        "--skip-mentions", action="store_true", help="Do not create MENTIONS edges to concepts"
    )
    args = parser.parse_args()

    subject = get_subject(args.subject)
    jsonl_path = Path(settings.data_processed_dir) / f"books_{subject.id}.jsonl"
    if not jsonl_path.exists():
        logger.error(f"Data file not found: {jsonl_path} (run: make seed SUBJECT={subject.id})")
        sys.exit(1)

    chunks, first_chunks = load_chunks(jsonl_path)
    if not chunks:
        logger.error("No chunks to write")
        sys.exit(1)

    embeddings: dict[str, list[float]] = {}
    if not args.skip_embeddings:
        embeddings = load_embeddings(subject, batch_size=500)
        missing = sum(1 for chunk in chunks if chunk["id"] not in embeddings)
        if missing:
            logger.warning(
                f"{missing} of {len(chunks)} chunks have no embedding in OpenSearch "
                "(was the JSONL changed after indexing? rerun: make seed SUBJECT=... --reset)"
            )

    adapter = get_neo4j_adapter(subject.id)
    try:
        concepts = set() if args.skip_mentions else load_concepts(adapter)
        mentions = find_mentions(chunks, concepts) if concepts else []
        nodes = to_chunk_nodes(chunks, embeddings)
        next_edges = sum(1 for node in nodes if node.previous_chunk_id)

        if args.dry_run:
            logger.info(
                f"[dry run] would write {len(nodes)} {adapter._get_label('Chunk')} nodes, "
                f"{next_edges} NEXT, {len(first_chunks)} FIRST_CHUNK and {len(mentions)} "
                "MENTIONS edges"
            )
            return

        adapter.create_chunk_nodes(nodes, batch_size=args.batch_size)
        adapter.create_next_relationships(nodes)
        adapter.create_first_chunk_relationships(first_chunks)
        adapter.create_chunk_mentions_relationships(mentions, batch_size=args.batch_size * 5)
        adapter.create_chunk_id_index()
        if embeddings:
            dimension = len(next(iter(embeddings.values())))
            adapter.create_vector_index(index_name=None, dimension=dimension)
        verify(adapter)
        logger.success(f"Chunk windows built for {subject.id}")
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
