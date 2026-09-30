"""
Build knowledge graph from normalized textbook data.

This script:
1. Loads normalized JSONL data
2. Extracts concepts and relationships using KGBuilder
3. Writes a JSON copy to data/processed/build/ (ignored by git; nothing reads it at runtime)
4. Persists the graph to Neo4j
5. Outputs statistics and top concepts

Usage:
    poetry run python scripts/build_knowledge_graph.py
    poetry run python scripts/build_knowledge_graph.py --subject economics --clear
    poetry run python scripts/build_knowledge_graph.py --subject us_history --max-concepts 300
    poetry run python scripts/build_knowledge_graph.py --subject us_history --cooccurrence-threshold 3

Without --clear the script asks whether to clear the subject's existing nodes when it runs in a
terminal, and keeps them (MERGE on top) when it does not. Exits non-zero on failure.

Builder tuning (passed only when the installed KGBuilder supports it):
    --cooccurrence-threshold N   paragraphs two concepts must share for a RELATED edge; defaults to
                                 KG_COOCCURRENCE_THRESHOLD_<SUBJECT>, then KG_COOCCURRENCE_THRESHOLD,
                                 then the builder default (so `make seed` can be tuned per subject:
                                 KG_COOCCURRENCE_THRESHOLD_US_HISTORY=3 make seed)
    --prereq-patterns            also derive PREREQ edges from cue phrases (KG_PREREQ_PATTERNS=1)
"""

import argparse
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.kg.builder import KGBuilder
from backend.app.kg.neo4j_adapter import get_neo4j_adapter


def load_records(jsonl_path: Path) -> list:
    """Load records from JSONL file."""
    records = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _should_clear(subject_id: str, clear_flag: bool) -> bool:
    """--clear wins; otherwise ask in a terminal and keep existing data when non-interactive."""
    if clear_flag:
        return True
    if not sys.stdin.isatty():
        logger.info("Non-interactive run without --clear: keeping existing Neo4j data")
        return False
    try:
        response = input(f"Clear existing Neo4j data for {subject_id}? (yes/no): ")
    except EOFError:
        return False
    return response.strip().lower() == "yes"


def _env_threshold(subject_id: str) -> int | None:
    """KG_COOCCURRENCE_THRESHOLD_<SUBJECT>, then KG_COOCCURRENCE_THRESHOLD."""
    for name in (f"KG_COOCCURRENCE_THRESHOLD_{subject_id.upper()}", "KG_COOCCURRENCE_THRESHOLD"):
        value = os.environ.get(name, "").strip()
        if value:
            try:
                return int(value)
            except ValueError:
                raise SystemExit(f"{name} must be an integer, got {value!r}") from None
    return None


def builder_options(
    subject_id: str, cooccurrence_threshold: int | None, prereq_patterns: bool
) -> dict[str, Any]:
    """KGBuilder keyword options the caller asked for, limited to what this builder accepts."""
    requested: dict[str, Any] = {}
    threshold = (
        cooccurrence_threshold if cooccurrence_threshold is not None else _env_threshold(subject_id)
    )
    if threshold is not None:
        requested["cooccurrence_threshold"] = threshold
    if prereq_patterns or os.environ.get("KG_PREREQ_PATTERNS", "").strip() == "1":
        requested["prereq_patterns"] = True

    supported = inspect.signature(KGBuilder.__init__).parameters
    options: dict[str, Any] = {}
    for name, value in requested.items():
        if name in supported:
            options[name] = value
        else:
            logger.warning(f"This KGBuilder has no '{name}' option; ignoring it")
    return options


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Build knowledge graph from textbook data")
    parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Subject ID to build KG for. Defaults to us_history.",
    )
    parser.add_argument(
        "--max-concepts",
        type=int,
        default=200,
        help="Maximum number of concepts to extract (default: 200)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing Neo4j data before building (skips interactive prompt)",
    )
    parser.add_argument(
        "--cooccurrence-threshold",
        type=int,
        default=None,
        help="Paragraphs two concepts must share for a RELATED edge "
        "(default: KG_COOCCURRENCE_THRESHOLD[_<SUBJECT>] or the builder default)",
    )
    parser.add_argument(
        "--prereq-patterns",
        action="store_true",
        help="Also create PREREQ edges from cue phrases (or KG_PREREQ_PATTERNS=1)",
    )
    args = parser.parse_args()

    # Resolve subject
    subject_config = get_subject(args.subject)
    subject_id = subject_config.id

    logger.info(f"Starting knowledge graph construction for subject: {subject_id}")

    # Load data from subject-specific JSONL
    jsonl_path = Path(settings.data_processed_dir) / f"books_{subject_id}.jsonl"
    if not jsonl_path.exists():
        logger.error(f"Data file not found: {jsonl_path}")
        logger.error(
            f"Run 'poetry run python scripts/ingest_books.py --subject {subject_id}' first"
        )
        sys.exit(1)

    records = load_records(jsonl_path)
    logger.info(f"Loaded {len(records)} text records from {jsonl_path}")

    # Build knowledge graph
    options = builder_options(subject_id, args.cooccurrence_threshold, args.prereq_patterns)
    if options:
        logger.info(f"KGBuilder options: {options}")
    builder = KGBuilder(max_concepts=args.max_concepts, **options)
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

    # Save a JSON copy for inspection under build/, so seeding leaves the tracked files alone
    build_dir = Path(settings.data_processed_dir) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    graph_json_path = build_dir / f"knowledge_graph_{subject_id}.json"
    graph_json_path.write_text(kg.model_dump_json(indent=2), encoding="utf-8")
    logger.success(f"Saved graph to {graph_json_path}")

    # Persist to Neo4j
    logger.info("\nConnecting to Neo4j...")
    adapter = get_neo4j_adapter(subject_id)

    try:
        # Clear existing data
        if _should_clear(subject_id, args.clear):
            adapter.clear_database()

        # Persist graph
        adapter.persist_knowledge_graph(kg)

        # Verify
        neo4j_stats = adapter.get_graph_stats()
        logger.info("\nNeo4j Statistics:")
        for key, value in neo4j_stats.items():
            logger.info(f"  {key}: {value}")

        logger.success(f"\n✓ Knowledge graph build complete for {subject_id}!")
        logger.info("View graph at: http://localhost:7474")
        logger.info("Next step: run 'make index-rag' to index content for RAG")

    except Exception as e:
        logger.error(f"Error persisting to Neo4j: {e}")
        logger.info(f"Graph saved to {graph_json_path}, but not persisted to Neo4j")
        sys.exit(1)

    finally:
        adapter.close()


if __name__ == "__main__":
    main()
