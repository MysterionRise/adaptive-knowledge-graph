#!/usr/bin/env python3
"""
Migration script: Upgrade to enterprise RAG patterns.

This script migrates existing data to the enterprise knowledge graph pattern:
1. Loads existing chunks from OpenSearch
2. Generates embeddings for each chunk
3. Creates Chunk nodes in Neo4j with embeddings
4. Creates NEXT relationships between sequential chunks
5. Creates MENTIONS relationships (Chunk -> Concept) based on text
6. Creates vector and fulltext indexes
7. Verifies migration with test queries

Usage:
    poetry run python scripts/migrate_to_enterprise.py [--dry-run] [--batch-size 100]
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from backend.app.core.settings import settings
from backend.app.kg.neo4j_adapter import Neo4jAdapter
from backend.app.kg.schema import ChunkNode
from backend.app.nlp.embeddings import get_embedding_model
from backend.app.rag.retriever import OpenSearchRetriever


def load_chunks_from_opensearch(batch_size: int = 1000) -> list[dict]:
    """
    Load all existing chunks from OpenSearch.

    Returns:
        List of chunk dicts with text and metadata
    """
    logger.info("Loading chunks from OpenSearch...")

    retriever = OpenSearchRetriever(
        username=settings.opensearch_user,
        password=settings.opensearch_password,
    )
    retriever.connect()

    # Use scroll API for large datasets
    all_chunks = []
    scroll_id = None

    try:
        # Initial search
        response = retriever.client.search(
            index=retriever.index_name,
            body={"query": {"match_all": {}}, "size": batch_size},
            scroll="2m",
        )

        scroll_id = response["_scroll_id"]
        hits = response["hits"]["hits"]

        while hits:
            for hit in hits:
                source = hit["_source"]
                chunk = {
                    "id": hit["_id"],
                    "text": source.get("text", ""),
                    "module_id": source.get("module_id"),
                    "module_title": source.get("module_title"),
                    "section": source.get("section"),
                    "key_terms": source.get("key_terms", []),
                    "attribution": source.get("attribution"),
                    # Try to get existing embedding
                    "existing_embedding": source.get("embedding"),
                }
                all_chunks.append(chunk)

            # Get next batch
            response = retriever.client.scroll(scroll_id=scroll_id, scroll="2m")
            scroll_id = response["_scroll_id"]
            hits = response["hits"]["hits"]

    finally:
        # Clear scroll
        if scroll_id:
            try:
                retriever.client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    logger.info(f"Loaded {len(all_chunks)} chunks from OpenSearch")
    return all_chunks


def generate_embeddings(chunks: list[dict], batch_size: int = 32) -> list[dict]:
    """
    Generate embeddings for chunks that don't have them.

    Args:
        chunks: List of chunk dicts
        batch_size: Batch size for embedding generation

    Returns:
        Updated chunks with embeddings
    """
    logger.info("Generating embeddings for chunks...")

    embedding_model = get_embedding_model()

    # Find chunks needing embeddings
    needs_embedding = [c for c in chunks if not c.get("existing_embedding")]

    if not needs_embedding:
        logger.info("All chunks already have embeddings")
        # Copy existing embeddings to text_embedding field
        for chunk in chunks:
            chunk["text_embedding"] = chunk.get("existing_embedding")
        return chunks

    logger.info(f"Generating embeddings for {len(needs_embedding)} chunks...")

    # Process in batches
    for i in range(0, len(needs_embedding), batch_size):
        batch = needs_embedding[i : i + batch_size]
        texts = [c["text"] for c in batch]

        embeddings = embedding_model.encode_batch(texts)

        for chunk, embedding in zip(batch, embeddings, strict=False):
            chunk["text_embedding"] = embedding

        logger.info(f"Processed {min(i + batch_size, len(needs_embedding))}/{len(needs_embedding)}")

    # Copy existing embeddings for chunks that had them
    for chunk in chunks:
        if "text_embedding" not in chunk:
            chunk["text_embedding"] = chunk.get("existing_embedding")

    return chunks


def group_chunks_by_module(chunks: list[dict]) -> dict[str, list[dict]]:
    """Group chunks by module_id for sequential linking."""
    grouped: dict[str, list[dict]] = {}

    for chunk in chunks:
        module_id = chunk.get("module_id", "unknown")
        if module_id not in grouped:
            grouped[module_id] = []
        grouped[module_id].append(chunk)

    # Sort chunks within each module by ID (assumes IDs are sequential)
    for module_id in grouped:
        grouped[module_id].sort(key=lambda c: c.get("id", ""))

    return grouped


def add_sequential_linking(chunks: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    Add previous_chunk_id/next_chunk_id for NEXT relationships.

    Returns:
        Tuple of (updated chunks, first_chunk_per_module dict)
    """
    logger.info("Adding sequential linking metadata...")

    grouped = group_chunks_by_module(chunks)
    first_chunks: dict[str, str] = {}

    for module_id, module_chunks in grouped.items():
        # Track first chunk per module
        if module_chunks:
            first_chunks[module_id] = module_chunks[0]["id"]

        # Add sequential links
        for i, chunk in enumerate(module_chunks):
            chunk["previous_chunk_id"] = module_chunks[i - 1]["id"] if i > 0 else None
            chunk["next_chunk_id"] = (
                module_chunks[i + 1]["id"] if i < len(module_chunks) - 1 else None
            )
            chunk["chunk_index"] = i

    logger.info(f"Added linking for {len(chunks)} chunks across {len(grouped)} modules")
    return chunks, first_chunks


def extract_chunk_concept_mentions(
    chunks: list[dict], all_concepts: set[str]
) -> list[tuple[str, str]]:
    """
    Extract MENTIONS relationships between chunks and concepts.

    Args:
        chunks: List of chunk dicts with text
        all_concepts: Set of all concept names in the graph

    Returns:
        List of (chunk_id, concept_name) tuples
    """
    logger.info("Extracting chunk-concept mentions...")

    mentions = []

    for chunk in chunks:
        chunk_id = chunk["id"]
        text_lower = chunk["text"].lower()

        for concept in all_concepts:
            if concept.lower() in text_lower:
                mentions.append((chunk_id, concept))

    logger.info(f"Found {len(mentions)} chunk-concept mentions")
    return mentions


def migrate_to_neo4j(
    chunks: list[dict],
    first_chunks: dict[str, str],
    mentions: list[tuple[str, str]],
    adapter: Neo4jAdapter,
    batch_size: int = 100,
    dry_run: bool = False,
):
    """
    Migrate chunks to Neo4j with enterprise patterns.

    Args:
        chunks: List of chunk dicts with embeddings and linking
        first_chunks: Dict mapping module_id to first chunk_id
        mentions: List of (chunk_id, concept_name) for MENTIONS relationships
        adapter: Neo4j adapter
        batch_size: Batch size for operations
        dry_run: If True, don't actually write to Neo4j
    """
    if dry_run:
        logger.info("[DRY RUN] Would create the following in Neo4j:")
        logger.info(f"  - {len(chunks)} Chunk nodes")
        logger.info(
            f"  - {sum(1 for c in chunks if c.get('previous_chunk_id'))} NEXT relationships"
        )
        logger.info(f"  - {len(first_chunks)} FIRST_CHUNK relationships")
        logger.info(f"  - {len(mentions)} MENTIONS relationships")
        return

    # Convert to ChunkNode objects
    chunk_nodes = [
        ChunkNode(
            chunk_id=c["id"],
            text=c["text"],
            chunk_index=c.get("chunk_index", 0),
            start_char=c.get("start_char", 0),
            end_char=c.get("end_char", len(c["text"])),
            module_id=c.get("module_id"),
            section=c.get("section"),
            text_embedding=c.get("text_embedding"),
            previous_chunk_id=c.get("previous_chunk_id"),
            next_chunk_id=c.get("next_chunk_id"),
        )
        for c in chunks
    ]

    # Create chunk nodes
    logger.info(f"Creating {len(chunk_nodes)} chunk nodes...")
    adapter.create_chunk_nodes(chunk_nodes, batch_size=batch_size)

    # Create NEXT relationships
    logger.info("Creating NEXT relationships...")
    adapter.create_next_relationships(chunk_nodes)

    # Create FIRST_CHUNK relationships
    logger.info("Creating FIRST_CHUNK relationships...")
    adapter.create_first_chunk_relationships(first_chunks)

    # Create MENTIONS relationships
    logger.info("Creating MENTIONS relationships...")
    adapter.create_chunk_mentions_relationships(mentions, batch_size=batch_size)


def verify_migration(adapter: Neo4jAdapter):
    """Run verification queries after migration."""
    logger.info("Verifying migration...")

    stats = adapter.get_graph_stats()

    logger.info("Post-migration statistics:")
    logger.info(f"  Chunk nodes: {stats.get('Chunk_count', 0)}")
    logger.info(f"  NEXT relationships: {stats.get('NEXT_relationships', 0)}")
    logger.info(f"  FIRST_CHUNK relationships: {stats.get('FIRST_CHUNK_relationships', 0)}")
    logger.info(f"  MENTIONS relationships: {stats.get('MENTIONS_relationships', 0)}")

    # Test window query
    with adapter.driver.session() as session:
        result = session.run(
            """
            MATCH (c:Chunk)
            WITH c LIMIT 1
            OPTIONAL MATCH (prev:Chunk)-[:NEXT]->(c)
            OPTIONAL MATCH (c)-[:NEXT]->(next:Chunk)
            RETURN c.chunkId as chunk_id,
                   prev.chunkId as prev_id,
                   next.chunkId as next_id
            """
        )
        record = result.single()
        if record:
            logger.info("Window query test:")
            logger.info(f"  Chunk: {record['chunk_id']}")
            logger.info(f"  Previous: {record['prev_id']}")
            logger.info(f"  Next: {record['next_id']}")


def main():
    parser = argparse.ArgumentParser(description="Migrate to enterprise RAG patterns")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to Neo4j",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for operations",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (use existing)",
    )
    args = parser.parse_args()

    logger.info("=== Enterprise RAG Migration ===")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Batch size: {args.batch_size}")

    # Connect to Neo4j
    adapter = Neo4jAdapter()
    adapter.connect()

    try:
        # Step 1: Load chunks from OpenSearch
        chunks = load_chunks_from_opensearch(batch_size=args.batch_size)

        if not chunks:
            logger.warning("No chunks found in OpenSearch. Nothing to migrate.")
            return

        # Step 2: Generate embeddings
        if not args.skip_embeddings:
            chunks = generate_embeddings(chunks, batch_size=32)

        # Step 3: Add sequential linking
        chunks, first_chunks = add_sequential_linking(chunks)

        # Step 4: Get all concepts for MENTIONS relationships
        with adapter.driver.session() as session:
            result = session.run("MATCH (c:Concept) RETURN c.name as name")
            all_concepts = {record["name"] for record in result}
        logger.info(f"Found {len(all_concepts)} concepts in graph")

        # Step 5: Extract chunk-concept mentions
        mentions = extract_chunk_concept_mentions(chunks, all_concepts)

        # Step 6: Migrate to Neo4j
        migrate_to_neo4j(
            chunks=chunks,
            first_chunks=first_chunks,
            mentions=mentions,
            adapter=adapter,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )

        # Step 7: Verify migration
        if not args.dry_run:
            verify_migration(adapter)

        logger.success("=== Migration Complete ===")

    finally:
        adapter.close()


if __name__ == "__main__":
    main()
