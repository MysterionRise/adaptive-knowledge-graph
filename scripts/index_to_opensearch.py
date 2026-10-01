"""
Index textbook content to OpenSearch for RAG.

This script:
1. Loads normalized JSONL data for a subject
2. Chunks text into retrievable segments
3. Generates embeddings
4. Indexes to OpenSearch vector database

Usage:
    poetry run python scripts/index_to_opensearch.py --subject us_history
    poetry run python scripts/index_to_opensearch.py --subject economics --recreate

Exits non-zero when the source data is missing or the index ends up empty.
"""

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_all_subjects, get_subject
from backend.app.nlp.embeddings import get_embedding_model
from backend.app.rag.chunker import chunk_for_rag
from backend.app.rag.retriever import OpenSearchRetriever, get_retriever


def load_records(jsonl_path: Path) -> list:
    """Load records from JSONL file."""
    records = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def index_records(
    subject_id: str, records: list[dict], recreate: bool = False
) -> OpenSearchRetriever:
    """Chunk, embed and index a subject's records; the one indexing path for every script.

    Uses backend.app.rag.chunker.chunk_for_rag (the chunker the KG and window builders share), so
    `ingest_books.py --index-rag` and this script produce identical documents. Exits non-zero when
    the index ends up empty.
    """
    # chunk_for_rag returns (chunks, first_chunk_per_module) with sequential linking
    logger.info("Chunking text...")
    chunked = chunk_for_rag(records)
    chunks = chunked[0] if isinstance(chunked, tuple) else chunked
    logger.info(f"Created {len(chunks)} chunks")

    # Save a small sample for inspection under build/, so seeding leaves the tracked files alone
    build_dir = Path(settings.data_processed_dir) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = build_dir / f"chunks_{subject_id}.json"
    chunks_path.write_text(json.dumps(chunks[:10], indent=2), encoding="utf-8")
    logger.info(f"Sample chunks saved to {chunks_path}")

    # Initialize embedding model
    logger.info("Loading embedding model...")
    embedding_model = get_embedding_model()
    embedding_dim = embedding_model.get_embedding_dimension()
    logger.info(f"Embedding dimension: {embedding_dim}")

    # Initialize subject-specific OpenSearch retriever (uses settings for credentials)
    logger.info("Connecting to OpenSearch...")
    retriever = get_retriever(subject_id)

    # Create index
    retriever.create_collection(embedding_dim, recreate=recreate)
    logger.info(f"Index '{retriever.index_name}' ready (recreate={recreate})")

    # Index chunks
    logger.info("Indexing chunks to OpenSearch...")
    retriever.index_chunks(chunks, show_progress=True)

    # Verify
    info = retriever.get_collection_info()
    logger.info(f"Index info: {info}")
    if not info.get("exists") or not info.get("doc_count"):
        logger.error(f"Index '{retriever.index_name}' has no documents after indexing")
        sys.exit(1)
    return retriever


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Index textbook content to OpenSearch for RAG")
    parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Subject ID to index. Use --list-subjects to see options. Defaults to us_history.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the OpenSearch index (drops existing data).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip retrieval verification tests after indexing.",
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
            print(f"  - {subject.id}: {subject.name} (index: {subject.database.opensearch_index})")
        return

    # Resolve subject
    subject_config = get_subject(args.subject)
    subject_id = subject_config.id

    logger.info(f"Starting RAG indexing for subject: {subject_id}")

    # Load subject-specific data
    jsonl_path = Path(settings.data_processed_dir) / f"books_{subject_id}.jsonl"
    if not jsonl_path.exists():
        logger.error(f"Data file not found: {jsonl_path}")
        logger.error(
            f"Run 'poetry run python scripts/ingest_books.py --subject {subject_id}' first"
        )
        sys.exit(1)

    records = load_records(jsonl_path)
    logger.info(f"Loaded {len(records)} text records from {jsonl_path}")

    retriever = index_records(subject_id, records, recreate=args.recreate)

    # Test retrieval
    if not args.skip_tests:
        logger.info("\n--- Testing Retrieval ---")
        test_queries = [
            "What are the main topics covered?",
            "Explain the key concepts",
        ]

        for query in test_queries:
            results = retriever.retrieve(query, top_k=3)
            logger.info(f"\nQuery: {query}")
            for i, result in enumerate(results, 1):
                logger.info(
                    f"  {i}. [{result['score']:.3f}] {result['section']}: {result['text'][:100]}..."
                )

    logger.success(f"\n✓ RAG indexing complete for {subject_id}!")
    logger.info(f"Index: {retriever.index_name}")
    logger.info("OpenSearch dashboard: http://localhost:9200")


if __name__ == "__main__":
    main()
