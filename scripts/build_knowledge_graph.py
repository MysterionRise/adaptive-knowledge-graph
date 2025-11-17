"""
Build knowledge graph from normalized textbook data.

This script:
1. Loads normalized JSONL data
2. Extracts concepts and relationships using KGBuilder
3. Persists the graph to Neo4j
4. Outputs statistics and top concepts
"""

import json
from pathlib import Path

from loguru import logger

from backend.app.core.settings import settings
from backend.app.kg.builder import KGBuilder
from backend.app.kg.neo4j_adapter import Neo4jAdapter


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
    logger.info("Starting knowledge graph construction")

    # Load data
    jsonl_path = Path(settings.data_books_jsonl)
    if not jsonl_path.exists():
        logger.error(f"Data file not found: {jsonl_path}")
        logger.error("Run 'make normalize-data' first")
        return

    records = load_records(jsonl_path)
    logger.info(f"Loaded {len(records)} text records")

    # Build knowledge graph
    builder = KGBuilder(max_concepts=200)  # Limit for demo
    kg = builder.build_from_records(records)

    # Print statistics
    stats = kg.get_stats()
    logger.info("Knowledge Graph Statistics:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    # Print top concepts
    top_concepts = builder.get_top_concepts(n=20)
    logger.info("\nTop 20 Concepts by Importance:")
    for i, (concept, score) in enumerate(top_concepts, 1):
        logger.info(f"  {i}. {concept} (score: {score:.3f})")

    # Save graph to JSON for backup
    processed_dir = Path(settings.data_processed_dir)
    graph_json_path = processed_dir / "knowledge_graph.json"
    graph_json_path.write_text(kg.model_dump_json(indent=2), encoding="utf-8")
    logger.success(f"Saved graph to {graph_json_path}")

    # Persist to Neo4j
    logger.info("\nConnecting to Neo4j...")
    adapter = Neo4jAdapter()

    try:
        adapter.connect()

        # Clear existing data (for fresh build)
        response = input("Clear existing Neo4j data? (yes/no): ").strip().lower()
        if response == "yes":
            adapter.clear_database()

        # Persist graph
        adapter.persist_knowledge_graph(kg)

        # Verify
        neo4j_stats = adapter.get_graph_stats()
        logger.info("\nNeo4j Statistics:")
        for key, value in neo4j_stats.items():
            logger.info(f"  {key}: {value}")

        logger.success("\n✓ Knowledge graph build complete!")
        logger.info("View graph at: http://localhost:7474")
        logger.info("Next step: run 'make index-rag' to index content for RAG")

    except Exception as e:
        logger.error(f"Error persisting to Neo4j: {e}")
        logger.info("Graph saved to JSON file, but not persisted to Neo4j")

    finally:
        adapter.close()


if __name__ == "__main__":
    main()
