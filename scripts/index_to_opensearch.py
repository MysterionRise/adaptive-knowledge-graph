"""
Index textbook content to OpenSearch for RAG.

This script:
1. Loads normalized JSONL data
2. Chunks text into retrievable segments
3. Generates embeddings
4. Indexes to OpenSearch vector database
"""

import json
from pathlib import Path

from loguru import logger

from backend.app.core.settings import settings
from backend.app.nlp.embeddings import get_embedding_model
from backend.app.rag.chunker import chunk_for_rag
from backend.app.rag.retriever import OpenSearchRetriever


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
    logger.info("Starting RAG indexing")

    # Load data
    jsonl_path = Path(settings.data_books_jsonl)
    if not jsonl_path.exists():
        logger.error(f"Data file not found: {jsonl_path}")
        logger.error("Run 'make normalize-data' first")
        return

    records = load_records(jsonl_path)
    logger.info(f"Loaded {len(records)} text records")

    # Chunk text
    logger.info("Chunking text...")
    chunks = chunk_for_rag(records)
    logger.info(f"Created {len(chunks)} chunks")

    # Save chunks for inspection
    processed_dir = Path(settings.data_processed_dir)
    chunks_path = processed_dir / "chunks.json"
    chunks_path.write_text(json.dumps(chunks[:10], indent=2), encoding="utf-8")
    logger.info(f"Sample chunks saved to {chunks_path}")

    # Initialize embedding model
    logger.info("Loading embedding model...")
    embedding_model = get_embedding_model()
    embedding_dim = embedding_model.get_embedding_dimension()
    logger.info(f"Embedding dimension: {embedding_dim}")

    # Initialize OpenSearch retriever
    logger.info("Connecting to OpenSearch...")
    retriever = OpenSearchRetriever(username="admin", password="Opensearch-adaptive-graph123!")
    retriever.connect()

    # Create index
    response = input(f"Recreate index '{retriever.index_name}'? (yes/no): ").strip().lower()
    recreate = response == "yes"
    retriever.create_collection(embedding_dim, recreate=recreate)

    # Index chunks
    logger.info("Indexing chunks to OpenSearch...")
    retriever.index_chunks(chunks, show_progress=True)

    # Verify
    info = retriever.get_collection_info()
    logger.info(f"Index info: {info}")

    # Test retrieval
    logger.info("\n--- Testing Retrieval ---")
    test_queries = [
        "What is photosynthesis?",
        "How do cells produce energy?",
        "What is the structure of DNA?",
    ]

    for query in test_queries:
        results = retriever.retrieve(query, top_k=3)
        logger.info(f"\nQuery: {query}")
        for i, result in enumerate(results, 1):
            logger.info(
                f"  {i}. [{result['score']:.3f}] {result['section']}: {result['text'][:100]}..."
            )

    logger.success("\n✓ RAG indexing complete!")
    logger.info("OpenSearch dashboard: http://localhost:9200")
    logger.info("Next step: Implement LLM integration and Q&A endpoint")


if __name__ == "__main__":
    main()
