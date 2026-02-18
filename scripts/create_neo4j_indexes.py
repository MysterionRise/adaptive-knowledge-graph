#!/usr/bin/env python3
"""
Create Neo4j indexes for enterprise RAG patterns.

This script creates:
1. Vector index on Chunk.textEmbedding for native vector search
2. Fulltext index on Concept.name for fuzzy search
3. Standard indexes for performance optimization

Usage:
    poetry run python scripts/create_neo4j_indexes.py [--drop-existing]

Requirements:
    - Neo4j 5.x with vector index support
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_all_subjects, get_subject
from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter


def drop_existing_indexes(adapter: Neo4jAdapter):
    """Drop existing indexes (use with caution)."""
    logger.warning("Dropping existing indexes...")

    with adapter._get_session() as session:
        # Get all indexes
        result = session.run("SHOW INDEXES YIELD name, type")
        indexes = [(r["name"], r["type"]) for r in result]

        for name, idx_type in indexes:
            if name.startswith("index_"):
                # Skip constraint-backing indexes
                continue

            try:
                session.run(f"DROP INDEX {name} IF EXISTS")
                logger.info(f"Dropped index: {name} ({idx_type})")
            except Exception as e:
                logger.warning(f"Could not drop {name}: {e}")


def create_vector_index(adapter: Neo4jAdapter):
    """Create vector index on Chunk embeddings."""
    logger.info("Creating vector index on Chunk.textEmbedding...")

    try:
        adapter.create_vector_index(
            index_name=settings.neo4j_vector_index_name,
            dimension=settings.neo4j_vector_dimension,
            similarity_function="cosine",
        )
    except Exception as e:
        if "already exists" in str(e).lower():
            logger.info("Vector index already exists")
        else:
            raise


def create_fulltext_index(adapter: Neo4jAdapter):
    """Create fulltext index on Concept names."""
    logger.info("Creating fulltext index on Concept.name...")

    try:
        # Pass None to let adapter auto-generate name with label_prefix
        adapter.create_fulltext_index(index_name=None)
    except Exception as e:
        if "already exists" in str(e).lower():
            logger.info("Fulltext index already exists")
        else:
            raise


def create_standard_indexes(adapter: Neo4jAdapter):
    """Create standard indexes for performance using subject-specific labels."""
    logger.info("Creating standard indexes...")
    prefix = f"{adapter.label_prefix}_" if adapter.label_prefix else ""

    # Build label names via the adapter's labeling convention
    chunk_label = adapter._get_label("Chunk")
    concept_label = adapter._get_label("Concept")
    module_label = adapter._get_label("Module")

    with adapter._get_session() as session:
        indexes = [
            # Chunk indexes
            (
                f"{prefix}chunk_id_index",
                f"CREATE INDEX {prefix}chunk_id_index IF NOT EXISTS "
                f"FOR (c:{chunk_label}) ON (c.chunkId)",
            ),
            (
                f"{prefix}chunk_module_index",
                f"CREATE INDEX {prefix}chunk_module_index IF NOT EXISTS "
                f"FOR (c:{chunk_label}) ON (c.moduleId)",
            ),
            # Concept indexes
            (
                f"{prefix}concept_name_index",
                f"CREATE INDEX {prefix}concept_name_index IF NOT EXISTS "
                f"FOR (c:{concept_label}) ON (c.name)",
            ),
            (
                f"{prefix}concept_importance_index",
                f"CREATE INDEX {prefix}concept_importance_index IF NOT EXISTS "
                f"FOR (c:{concept_label}) ON (c.importance_score)",
            ),
            # Module indexes
            (
                f"{prefix}module_id_index",
                f"CREATE INDEX {prefix}module_id_index IF NOT EXISTS "
                f"FOR (m:{module_label}) ON (m.module_id)",
            ),
        ]

        for name, query in indexes:
            try:
                session.run(query)
                logger.info(f"Created index: {name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"Index already exists: {name}")
                else:
                    logger.warning(f"Failed to create {name}: {e}")


def verify_indexes(adapter: Neo4jAdapter):
    """Verify all indexes are created and populated."""
    logger.info("Verifying indexes...")

    with adapter._get_session() as session:
        result = session.run(
            """
            SHOW INDEXES
            YIELD name, type, labelsOrTypes, properties, state
            RETURN name, type, labelsOrTypes, properties, state
            ORDER BY name
            """
        )

        logger.info("Current indexes:")
        for record in result:
            status = "ONLINE" if record["state"] == "ONLINE" else record["state"]
            labels = record["labelsOrTypes"]
            props = record["properties"]
            logger.info(f"  {record['name']}: {record['type']} on {labels}.{props} [{status}]")


def test_vector_search(adapter: Neo4jAdapter):
    """Test vector search functionality."""
    logger.info("Testing vector search...")

    try:
        # Check if there are chunks with embeddings
        with adapter._get_session() as session:
            result = session.run(
                """
                MATCH (c:Chunk)
                WHERE c.textEmbedding IS NOT NULL
                RETURN count(c) as count
                """
            )
            count = result.single()["count"]  # type: ignore[index]

            if count == 0:
                logger.warning("No chunks with embeddings found. Vector search test skipped.")
                return

            logger.info(f"Found {count} chunks with embeddings")

            # Get a sample embedding
            result = session.run(
                """
                MATCH (c:Chunk)
                WHERE c.textEmbedding IS NOT NULL
                RETURN c.textEmbedding as embedding
                LIMIT 1
                """
            )
            sample_embedding = result.single()["embedding"]  # type: ignore[index]

            # Test vector search
            search_result = adapter.vector_search(
                query_embedding=sample_embedding,
                top_k=3,
                index_name=settings.neo4j_vector_index_name,
            )

            logger.info(f"Vector search test returned {len(search_result)} results")
            for i, r in enumerate(search_result, 1):
                logger.info(f"  {i}. {r['chunk_id'][:40]}... (score: {r['score']:.4f})")

    except Exception as e:
        logger.error(f"Vector search test failed: {e}")
        logger.info("This may indicate the vector index is not ready or no data exists")


def test_fulltext_search(adapter: Neo4jAdapter):
    """Test fulltext search functionality."""
    logger.info("Testing fulltext search...")

    try:
        # Check if there are concepts
        with adapter._get_session() as session:
            result = session.run("MATCH (c:Concept) RETURN count(c) as count")
            count = result.single()["count"]  # type: ignore[index]

            if count == 0:
                logger.warning("No concepts found. Fulltext search test skipped.")
                return

        # Test fulltext search
        results = adapter.fulltext_concept_search("photo", limit=3)

        logger.info(f"Fulltext search for 'photo' returned {len(results)} results")
        for r in results:
            logger.info(f"  - {r['name']} (score: {r['score']:.4f})")

    except Exception as e:
        logger.error(f"Fulltext search test failed: {e}")
        logger.info("This may indicate the fulltext index is not ready")


def main():
    parser = argparse.ArgumentParser(description="Create Neo4j indexes for enterprise RAG")
    parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Subject ID for subject-specific indexes. Defaults to us_history.",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing indexes before creating new ones",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip index verification tests",
    )
    parser.add_argument(
        "--list-subjects",
        action="store_true",
        help="List all available subjects and exit.",
    )
    args = parser.parse_args()

    if args.list_subjects:
        print("Available subjects:")
        for subject in get_all_subjects():
            print(f"  - {subject.id}: {subject.name} (prefix: {subject.database.label_prefix})")
        return

    # Resolve subject
    subject_config = get_subject(args.subject)
    subject_id = subject_config.id

    logger.info("=== Neo4j Index Creation ===")
    logger.info(f"Subject: {subject_id}")
    logger.info(f"Neo4j URI: {settings.neo4j_uri}")
    logger.info(f"Label prefix: {subject_config.database.label_prefix}")
    logger.info(f"Vector dimension: {settings.neo4j_vector_dimension}")

    # Connect to Neo4j using subject-specific adapter (with label_prefix)
    adapter = get_neo4j_adapter(subject_id)

    try:
        # Optionally drop existing indexes
        if args.drop_existing:
            drop_existing_indexes(adapter)

        # Create indexes
        create_vector_index(adapter)
        create_fulltext_index(adapter)
        create_standard_indexes(adapter)

        # Verify indexes
        verify_indexes(adapter)

        # Test indexes
        if not args.skip_tests:
            test_vector_search(adapter)
            test_fulltext_search(adapter)

        logger.success("=== Index Creation Complete ===")

    finally:
        adapter.close()


if __name__ == "__main__":
    main()
