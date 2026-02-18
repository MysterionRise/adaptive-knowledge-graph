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
"""

import argparse
import json
from pathlib import Path

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_all_subjects, get_subject
from backend.app.nlp.embeddings import get_embedding_model
from backend.app.rag.chunker import chunk_for_rag
from backend.app.rag.retriever import get_retriever


def load_records(jsonl_path: Path) -> list:
    """Load records from JSONL file."""
    records = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


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
        return

    records = load_records(jsonl_path)
    logger.info(f"Loaded {len(records)} text records from {jsonl_path}")

    # Chunk text
    logger.info("Chunking text...")
    chunks = chunk_for_rag(records)
    logger.info(f"Created {len(chunks)} chunks")

    # Save chunks for inspection
    processed_dir = Path(settings.data_processed_dir)
    chunks_path = processed_dir / f"chunks_{subject_id}.json"
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
    retriever.create_collection(embedding_dim, recreate=args.recreate)
    logger.info(f"Index '{retriever.index_name}' ready (recreate={args.recreate})")

    # Index chunks
    logger.info("Indexing chunks to OpenSearch...")
    if isinstance(chunks, tuple):
        chunks = chunks[0]
    retriever.index_chunks(chunks, show_progress=True)

    # Verify
    info = retriever.get_collection_info()
    logger.info(f"Index info: {info}")

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
                    f"  {i}. [{result['score']:.3f}] "
                    f"{result['section']}: {result['text'][:100]}..."
                )

    logger.success(f"\n✓ RAG indexing complete for {subject_id}!")
    logger.info(f"Index: {retriever.index_name}")
    logger.info("OpenSearch dashboard: http://localhost:9200")


if __name__ == "__main__":
    main()
