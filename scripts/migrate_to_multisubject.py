#!/usr/bin/env python3
"""
Migration script to convert single-subject data to multi-subject format.

This script:
1. Exports existing Neo4j data
2. Re-imports it with subject-specific label prefixes
3. Creates subject-specific indexes
4. Optionally reindexes OpenSearch data

Usage:
    python scripts/migrate_to_multisubject.py
    python scripts/migrate_to_multisubject.py --dry-run
    python scripts/migrate_to_multisubject.py --reindex-opensearch
"""

import argparse
import os
import sys

from loguru import logger

# Add project root to path
sys.path.append(os.getcwd())

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject


def migrate_neo4j_labels(subject_id: str = "us_history", dry_run: bool = False):
    """
    Migrate existing Neo4j nodes to use subject-specific label prefixes.

    This is the "soft isolation" approach for Neo4j Community Edition.
    Existing :Concept, :Module, :Chunk nodes get additional labels like
    :us_history_Concept, :us_history_Module, :us_history_Chunk.

    Args:
        subject_id: Subject identifier for the existing data
        dry_run: If True, only show what would be done without making changes
    """
    from backend.app.kg.neo4j_adapter import Neo4jAdapter

    logger.info(f"Migrating Neo4j labels for subject: {subject_id}")
    logger.info(f"Dry run: {dry_run}")

    adapter = Neo4jAdapter()
    adapter.connect()

    subject_config = get_subject(subject_id)
    label_prefix = subject_config.database.label_prefix

    try:
        with adapter._get_session() as session:
            # Check existing data
            result = session.run("MATCH (c:Concept) RETURN count(c) as count")
            concept_count = result.single()["count"]  # type: ignore[index]

            result = session.run("MATCH (m:Module) RETURN count(m) as count")
            module_count = result.single()["count"]  # type: ignore[index]

            result = session.run("MATCH (c:Chunk) RETURN count(c) as count")
            chunk_count = result.single()["count"]  # type: ignore[index]

            logger.info("Found existing data:")
            logger.info(f"  - {concept_count} Concept nodes")
            logger.info(f"  - {module_count} Module nodes")
            logger.info(f"  - {chunk_count} Chunk nodes")

            if concept_count == 0 and module_count == 0:
                logger.warning("No existing data found to migrate")
                return

            # Check if migration already done
            new_concept_label = f"{label_prefix}_Concept"
            result = session.run(f"MATCH (c:{new_concept_label}) RETURN count(c) as count")
            existing_migrated = result.single()["count"]  # type: ignore[index]

            if existing_migrated > 0:
                logger.warning(
                    f"Found {existing_migrated} nodes already with {new_concept_label} label. "
                    "Migration may have already been run."
                )
                if not dry_run:
                    response = input("Continue anyway? (y/N): ")
                    if response.lower() != "y":
                        logger.info("Migration cancelled")
                        return

            if dry_run:
                logger.info("DRY RUN - Would execute the following migrations:")
                logger.info(
                    f"  - Add :{label_prefix}_Concept label to {concept_count} Concept nodes"
                )
                logger.info(f"  - Add :{label_prefix}_Module label to {module_count} Module nodes")
                logger.info(f"  - Add :{label_prefix}_Chunk label to {chunk_count} Chunk nodes")
                return

            # Add subject-specific labels to existing nodes
            # We keep the original labels for backward compatibility

            logger.info(f"Adding {label_prefix}_Concept label to Concept nodes...")
            result = session.run(
                f"""
                MATCH (c:Concept)
                WHERE NOT c:{label_prefix}_Concept
                SET c:{label_prefix}_Concept
                RETURN count(c) as count
                """
            )
            migrated = result.single()["count"]  # type: ignore[index]
            logger.info(f"  Migrated {migrated} Concept nodes")

            logger.info(f"Adding {label_prefix}_Module label to Module nodes...")
            result = session.run(
                f"""
                MATCH (m:Module)
                WHERE NOT m:{label_prefix}_Module
                SET m:{label_prefix}_Module
                RETURN count(m) as count
                """
            )
            migrated = result.single()["count"]  # type: ignore[index]
            logger.info(f"  Migrated {migrated} Module nodes")

            logger.info(f"Adding {label_prefix}_Chunk label to Chunk nodes...")
            result = session.run(
                f"""
                MATCH (c:Chunk)
                WHERE NOT c:{label_prefix}_Chunk
                SET c:{label_prefix}_Chunk
                RETURN count(c) as count
                """
            )
            migrated = result.single()["count"]  # type: ignore[index]
            logger.info(f"  Migrated {migrated} Chunk nodes")

        logger.success(f"Neo4j label migration complete for {subject_id}")

    finally:
        adapter.close()


def create_subject_indexes(subject_id: str = "us_history", dry_run: bool = False):
    """
    Create subject-specific indexes in Neo4j.

    Args:
        subject_id: Subject identifier
        dry_run: If True, only show what would be done
    """
    from backend.app.kg.neo4j_adapter import Neo4jAdapter

    logger.info(f"Creating indexes for subject: {subject_id}")

    subject_config = get_subject(subject_id)
    label_prefix = subject_config.database.label_prefix

    if dry_run:
        logger.info("DRY RUN - Would create the following indexes:")
        logger.info(
            f"  - {label_prefix}_fullTextConceptNames (fulltext on {label_prefix}_Concept.name)"
        )
        logger.info(f"  - {label_prefix}_chunk_id_index (on {label_prefix}_Chunk.chunkId)")
        return

    adapter = Neo4jAdapter(label_prefix=label_prefix)
    adapter.connect()

    try:
        # Create fulltext index for concept search
        adapter.create_fulltext_index()

        # Create chunk ID index
        adapter.create_chunk_id_index()

        logger.success(f"Indexes created for {subject_id}")

    finally:
        adapter.close()


def migrate_opensearch_index(
    subject_id: str = "us_history",
    dry_run: bool = False,
):
    """
    Migrate OpenSearch index to subject-specific index.

    This copies data from the default index to a subject-specific index.

    Args:
        subject_id: Subject identifier
        dry_run: If True, only show what would be done
    """
    from opensearchpy import OpenSearch

    logger.info(f"Migrating OpenSearch index for subject: {subject_id}")

    subject_config = get_subject(subject_id)
    new_index = subject_config.database.opensearch_index
    old_index = settings.opensearch_index  # Default index

    if dry_run:
        logger.info("DRY RUN - Would execute the following:")
        logger.info(f"  - Copy data from '{old_index}' to '{new_index}'")
        logger.info("  - Add subject_id field to all documents")
        return

    # Connect to OpenSearch
    client = OpenSearch(
        hosts=[{"host": settings.opensearch_host, "port": settings.opensearch_port}],
        http_compress=True,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
        ssl_show_warn=False,
        http_auth=(settings.opensearch_user, settings.opensearch_password)
        if settings.opensearch_password
        else None,
    )

    # Check if old index exists
    if not client.indices.exists(index=old_index):
        logger.warning(f"Source index '{old_index}' does not exist. Nothing to migrate.")
        return

    # Check document count in old index
    stats = client.indices.stats(index=old_index)
    doc_count = stats["indices"][old_index]["total"]["docs"]["count"]
    logger.info(f"Found {doc_count} documents in '{old_index}'")

    if doc_count == 0:
        logger.warning("No documents to migrate")
        return

    # Check if new index already exists
    if client.indices.exists(index=new_index):
        new_stats = client.indices.stats(index=new_index)
        new_doc_count = new_stats["indices"][new_index]["total"]["docs"]["count"]
        if new_doc_count > 0:
            logger.warning(
                f"Destination index '{new_index}' already has {new_doc_count} documents. "
                "Skipping migration to avoid duplicates."
            )
            return

    # Reindex with subject_id field added
    logger.info(f"Reindexing from '{old_index}' to '{new_index}'...")

    reindex_body = {
        "source": {"index": old_index},
        "dest": {"index": new_index},
        "script": {
            "source": f"ctx._source.subject_id = '{subject_id}'",
            "lang": "painless",
        },
    }

    try:
        response = client.reindex(body=reindex_body, wait_for_completion=True)
        created = response.get("created", 0)
        logger.success(f"Reindexed {created} documents to '{new_index}'")
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Migrate existing data to multi-subject format.")
    parser.add_argument(
        "--subject",
        type=str,
        default="us_history",
        help="Subject ID for the existing data (default: us_history)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--neo4j-only",
        action="store_true",
        help="Only migrate Neo4j labels",
    )
    parser.add_argument(
        "--opensearch-only",
        action="store_true",
        help="Only migrate OpenSearch index",
    )
    parser.add_argument(
        "--indexes-only",
        action="store_true",
        help="Only create subject-specific indexes",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Multi-Subject Migration Script")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Running in DRY RUN mode - no changes will be made")

    try:
        # Run specific migration or all
        if args.neo4j_only:
            migrate_neo4j_labels(args.subject, args.dry_run)
        elif args.opensearch_only:
            migrate_opensearch_index(args.subject, args.dry_run)
        elif args.indexes_only:
            create_subject_indexes(args.subject, args.dry_run)
        else:
            # Run all migrations
            logger.info("\n--- Step 1: Migrate Neo4j labels ---")
            migrate_neo4j_labels(args.subject, args.dry_run)

            logger.info("\n--- Step 2: Create subject-specific indexes ---")
            create_subject_indexes(args.subject, args.dry_run)

            logger.info("\n--- Step 3: Migrate OpenSearch index ---")
            migrate_opensearch_index(args.subject, args.dry_run)

        logger.info("\n" + "=" * 60)
        logger.success("Migration complete!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
