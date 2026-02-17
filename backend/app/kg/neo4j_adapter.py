"""
Neo4j adapter for persisting knowledge graphs.

Handles connection to Neo4j and CRUD operations for graph data.
Supports multi-subject isolation via database parameter or label prefixes.
"""

from typing import Any

from loguru import logger
from neo4j import Driver, GraphDatabase, Session

from backend.app.core.settings import settings
from backend.app.kg.schema import ChunkNode, KnowledgeGraph, RelationshipType


class Neo4jAdapter:
    """Adapter for Neo4j graph database operations."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        label_prefix: str | None = None,
    ):
        """
        Initialize Neo4j adapter.

        Args:
            uri: Neo4j URI (defaults to settings)
            user: Neo4j user (defaults to settings)
            password: Neo4j password (defaults to settings)
            database: Neo4j database name (for Enterprise Edition multi-db)
            label_prefix: Prefix for node labels (for Community Edition soft isolation)
        """
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self.database = database or settings.neo4j_database
        self.label_prefix = label_prefix  # e.g., "us_history" -> "us_history_Concept"
        self.driver: Driver | None = None

    def _get_label(self, base_label: str) -> str:
        """Get the full label name with optional prefix for isolation."""
        if self.label_prefix:
            return f"{self.label_prefix}_{base_label}"
        return base_label

    def _get_session(self) -> Session:
        """Get a session for the configured database."""
        assert self.driver is not None, "Not connected. Call connect() first."
        return self.driver.session(database=self.database)

    def connect(self):
        """Connect to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # Test connection
            with self._get_session() as session:
                result = session.run("RETURN 1 as test")
                result.single()
            db_info = f"{self.uri} (db: {self.database})"
            if self.label_prefix:
                db_info += f" [prefix: {self.label_prefix}]"
            logger.success(f"✓ Connected to Neo4j at {db_info}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def close(self):
        """Close Neo4j connection."""
        if self.driver is not None:
            self.driver.close()
            logger.info("Closed Neo4j connection")

    def clear_database(self):
        """Clear all nodes and relationships (use with caution!)."""
        with self._get_session() as session:
            if self.label_prefix:
                # Only clear nodes with our prefix (soft isolation)
                concept_label = self._get_label("Concept")
                module_label = self._get_label("Module")
                chunk_label = self._get_label("Chunk")
                session.run(f"MATCH (n:{concept_label}) DETACH DELETE n")
                session.run(f"MATCH (n:{module_label}) DETACH DELETE n")
                session.run(f"MATCH (n:{chunk_label}) DETACH DELETE n")
                logger.warning(f"⚠️  Cleared Neo4j nodes with prefix: {self.label_prefix}")
            else:
                session.run("MATCH (n) DETACH DELETE n")
                logger.warning("⚠️  Cleared Neo4j database")

    def persist_knowledge_graph(self, kg: KnowledgeGraph):
        """
        Persist complete knowledge graph to Neo4j.

        Args:
            kg: KnowledgeGraph to persist
        """
        prefix_info = f" (prefix: {self.label_prefix})" if self.label_prefix else ""
        logger.info(f"Persisting knowledge graph to Neo4j{prefix_info}")

        with self._get_session() as session:
            # Create concept nodes
            self._create_concept_nodes(session, kg)

            # Create module nodes
            self._create_module_nodes(session, kg)

            # Create relationships
            self._create_relationships(session, kg)

        logger.success(
            f"✓ Persisted KG with {len(kg.concepts)} concepts and {len(kg.relationships)} relationships"
        )

    def _create_concept_nodes(self, session: Session, kg: KnowledgeGraph):
        """Create concept nodes in Neo4j."""
        concept_label = self._get_label("Concept")
        for _, concept in kg.concepts.items():
            query = f"""
            MERGE (c:{concept_label} {{name: $name}})
            SET c.key_term = $key_term,
                c.frequency = $frequency,
                c.importance_score = $importance_score,
                c.source_modules = $source_modules
            """
            session.run(
                query,
                name=concept.name,
                key_term=concept.key_term,
                frequency=concept.frequency,
                importance_score=concept.importance_score,
                source_modules=concept.source_modules,
            )
        logger.info(f"Created {len(kg.concepts)} concept nodes")

    def _create_module_nodes(self, session: Session, kg: KnowledgeGraph):
        """Create module nodes in Neo4j."""
        module_label = self._get_label("Module")
        for _, module in kg.modules.items():
            query = f"""
            MERGE (m:{module_label} {{module_id: $module_id}})
            SET m.title = $title,
                m.key_terms = $key_terms
            """
            session.run(
                query,
                module_id=module.module_id,
                title=module.title,
                key_terms=module.key_terms,
            )
        logger.info(f"Created {len(kg.modules)} module nodes")

    def _create_relationships(self, session: Session, kg: KnowledgeGraph):
        """Create relationships in Neo4j."""
        concept_label = self._get_label("Concept")
        module_label = self._get_label("Module")

        for rel in kg.relationships:
            if rel.type == RelationshipType.COVERS:
                # Module -> Concept
                query = f"""
                MATCH (m:{module_label} {{module_id: $source}})
                MATCH (c:{concept_label} {{name: $target}})
                MERGE (m)-[r:COVERS]->(c)
                SET r.weight = $weight,
                    r.confidence = $confidence
                """
            elif rel.type == RelationshipType.RELATED:
                # Concept -> Concept
                query = f"""
                MATCH (c1:{concept_label} {{name: $source}})
                MATCH (c2:{concept_label} {{name: $target}})
                MERGE (c1)-[r:RELATED]-(c2)
                SET r.weight = $weight,
                    r.confidence = $confidence
                """
            elif rel.type == RelationshipType.PREREQ:
                # Concept -> Concept (prerequisite)
                query = f"""
                MATCH (c1:{concept_label} {{name: $source}})
                MATCH (c2:{concept_label} {{name: $target}})
                MERGE (c1)-[r:PREREQ]->(c2)
                SET r.weight = $weight,
                    r.confidence = $confidence
                """
            else:
                continue

            session.run(
                query,
                source=rel.source,
                target=rel.target,
                weight=rel.weight,
                confidence=rel.confidence,
            )

        logger.info(f"Created {len(kg.relationships)} relationships")

    def query_concept_neighbors(self, concept_name: str, max_hops: int = 1) -> list[dict]:
        """
        Query neighboring concepts.

        Args:
            concept_name: Name of the concept
            max_hops: Maximum number of relationship hops

        Returns:
            List of neighbor concept dicts
        """
        concept_label = self._get_label("Concept")
        with self._get_session() as session:
            query = f"""
            MATCH (c:{concept_label} {{name: $name}})-[r*1..{max_hops}]-(neighbor:{concept_label})
            RETURN DISTINCT neighbor.name as name,
                   neighbor.importance_score as importance_score,
                   neighbor.key_term as key_term
            ORDER BY importance_score DESC
            LIMIT 20
            """
            result = session.run(query, name=concept_name)
            neighbors = [dict(record) for record in result]
            return neighbors

    def get_graph_stats(self) -> dict:
        """Get graph statistics from Neo4j."""
        concept_label = self._get_label("Concept")
        module_label = self._get_label("Module")
        chunk_label = self._get_label("Chunk")

        with self._get_session() as session:
            stats = {}

            if self.label_prefix:
                # Count nodes with our prefix labels
                result = session.run(f"MATCH (n:{concept_label}) RETURN count(n) as count")
                record: Any = result.single()
                stats["Concept_count"] = record["count"]

                result = session.run(f"MATCH (n:{module_label}) RETURN count(n) as count")
                record = result.single()
                stats["Module_count"] = record["count"]

                result = session.run(f"MATCH (n:{chunk_label}) RETURN count(n) as count")
                record = result.single()
                stats["Chunk_count"] = record["count"]

                # Count relationships between our nodes
                result = session.run(
                    f"MATCH (:{concept_label})-[r]->() RETURN type(r) as type, count(r) as count"
                )
                for record in result:
                    stats[f"{record['type']}_relationships"] = record["count"]

                result = session.run(
                    f"MATCH (:{module_label})-[r]->() RETURN type(r) as type, count(r) as count"
                )
                for record in result:
                    key = f"{record['type']}_relationships"
                    stats[key] = stats.get(key, 0) + record["count"]
            else:
                # Original behavior - count all nodes
                result = session.run("MATCH (n) RETURN labels(n) as labels, count(n) as count")
                for record in result:
                    label = record["labels"][0] if record["labels"] else "Unknown"
                    stats[f"{label}_count"] = record["count"]

                # Count relationships by type
                result = session.run("MATCH ()-[r]->() RETURN type(r) as type, count(r) as count")
                for record in result:
                    stats[f"{record['type']}_relationships"] = record["count"]

            return stats

    # ==========================================================================
    # Enterprise RAG: Chunk Operations
    # ==========================================================================

    def create_chunk_nodes(self, chunks: list[ChunkNode], batch_size: int = 100):
        """
        Create Chunk nodes in Neo4j.

        Args:
            chunks: List of ChunkNode objects
            batch_size: Number of chunks to process per batch
        """
        if not chunks:
            return

        chunk_label = self._get_label("Chunk")
        with self._get_session() as session:
            # Process in batches for performance
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]

                query = f"""
                UNWIND $chunks AS chunk
                MERGE (c:{chunk_label} {{chunkId: chunk.chunk_id}})
                SET c.text = chunk.text,
                    c.chunkIndex = chunk.chunk_index,
                    c.startChar = chunk.start_char,
                    c.endChar = chunk.end_char,
                    c.moduleId = chunk.module_id,
                    c.section = chunk.section,
                    c.textEmbedding = chunk.text_embedding
                """

                chunk_data = [
                    {
                        "chunk_id": c.chunk_id,
                        "text": c.text,
                        "chunk_index": c.chunk_index,
                        "start_char": c.start_char,
                        "end_char": c.end_char,
                        "module_id": c.module_id,
                        "section": c.section,
                        "text_embedding": c.text_embedding,
                    }
                    for c in batch
                ]

                session.run(query, chunks=chunk_data)

        logger.info(f"Created {len(chunks)} chunk nodes")

    def create_next_relationships(self, chunks: list[ChunkNode]):
        """
        Create NEXT relationships between sequential chunks.

        Uses the previous_chunk_id field to link chunks.

        Args:
            chunks: List of ChunkNode objects with sequential linking metadata
        """
        chunk_label = self._get_label("Chunk")
        with self._get_session() as session:
            query = f"""
            UNWIND $pairs AS pair
            MATCH (c1:{chunk_label} {{chunkId: pair.from_id}})
            MATCH (c2:{chunk_label} {{chunkId: pair.to_id}})
            MERGE (c1)-[:NEXT]->(c2)
            """

            pairs = [
                {"from_id": c.previous_chunk_id, "to_id": c.chunk_id}
                for c in chunks
                if c.previous_chunk_id is not None
            ]

            if pairs:
                session.run(query, pairs=pairs)

        logger.info(f"Created {len(pairs)} NEXT relationships")

    def create_first_chunk_relationships(self, module_first_chunks: dict[str, str]):
        """
        Create FIRST_CHUNK relationships from Modules to their first Chunks.

        Args:
            module_first_chunks: Dict mapping module_id to first chunk_id
        """
        module_label = self._get_label("Module")
        chunk_label = self._get_label("Chunk")
        with self._get_session() as session:
            query = f"""
            UNWIND $links AS link
            MATCH (m:{module_label} {{module_id: link.module_id}})
            MATCH (c:{chunk_label} {{chunkId: link.chunk_id}})
            MERGE (m)-[:FIRST_CHUNK]->(c)
            """

            links = [
                {"module_id": module_id, "chunk_id": chunk_id}
                for module_id, chunk_id in module_first_chunks.items()
            ]

            if links:
                session.run(query, links=links)

        logger.info(f"Created {len(links)} FIRST_CHUNK relationships")

    def create_chunk_mentions_relationships(
        self, chunk_concept_pairs: list[tuple[str, str]], batch_size: int = 500
    ):
        """
        Create MENTIONS relationships between Chunks and Concepts.

        Args:
            chunk_concept_pairs: List of (chunk_id, concept_name) tuples
            batch_size: Number of relationships to process per batch
        """
        if not chunk_concept_pairs:
            return

        chunk_label = self._get_label("Chunk")
        concept_label = self._get_label("Concept")
        with self._get_session() as session:
            for i in range(0, len(chunk_concept_pairs), batch_size):
                batch = chunk_concept_pairs[i : i + batch_size]

                query = f"""
                UNWIND $pairs AS pair
                MATCH (chunk:{chunk_label} {{chunkId: pair.chunk_id}})
                MATCH (concept:{concept_label} {{name: pair.concept_name}})
                MERGE (chunk)-[:MENTIONS]->(concept)
                """

                pairs = [
                    {"chunk_id": chunk_id, "concept_name": concept_name}
                    for chunk_id, concept_name in batch
                ]

                session.run(query, pairs=pairs)

        logger.info(f"Created {len(chunk_concept_pairs)} MENTIONS relationships")

    # ==========================================================================
    # Enterprise RAG: Index Operations
    # ==========================================================================

    def create_vector_index(
        self,
        index_name: str | None = None,
        dimension: int = 1024,
        similarity_function: str = "cosine",
    ):
        """
        Create Neo4j native vector index on Chunk embeddings.

        Requires Neo4j 5.x with vector index support.

        Args:
            index_name: Name for the vector index (auto-generated if label_prefix set)
            dimension: Embedding dimension (1024 for BGE-M3)
            similarity_function: 'cosine' or 'euclidean'
        """
        chunk_label = self._get_label("Chunk")

        # Auto-generate index name if using label prefix
        if index_name is None:
            if self.label_prefix:
                index_name = f"{self.label_prefix}_chunk_embeddings"
            else:
                index_name = "chunk_embeddings"

        with self._get_session() as session:
            # Check if index already exists
            result = session.run("SHOW INDEXES YIELD name WHERE name = $name", name=index_name)
            if result.single():
                logger.info(f"Vector index '{index_name}' already exists")
                return

            # Create vector index (Neo4j 5.x syntax)
            query = f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (c:{chunk_label}) ON (c.textEmbedding)
            OPTIONS {{
                indexConfig: {{
                    `vector.dimensions`: {dimension},
                    `vector.similarity_function`: '{similarity_function}'
                }}
            }}
            """
            session.run(query)

        logger.success(f"✓ Created vector index: {index_name}")

    def create_fulltext_index(self, index_name: str | None = None):
        """
        Create fulltext index for fuzzy concept name search.

        Args:
            index_name: Name for the fulltext index (auto-generated if label_prefix set)
        """
        concept_label = self._get_label("Concept")

        # Auto-generate index name if using label prefix
        if index_name is None:
            if self.label_prefix:
                index_name = f"{self.label_prefix}_fullTextConceptNames"
            else:
                index_name = "fullTextConceptNames"

        with self._get_session() as session:
            # Check if index already exists
            result = session.run("SHOW INDEXES YIELD name WHERE name = $name", name=index_name)
            if result.single():
                logger.info(f"Fulltext index '{index_name}' already exists")
                return

            # Create fulltext index
            query = f"""
            CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
            FOR (c:{concept_label}) ON EACH [c.name]
            """
            session.run(query)

        logger.success(f"✓ Created fulltext index: {index_name}")

    def create_chunk_id_index(self):
        """Create index on Chunk.chunkId for faster lookups."""
        chunk_label = self._get_label("Chunk")
        index_name = (
            f"{self.label_prefix}_chunk_id_index" if self.label_prefix else "chunk_id_index"
        )

        with self._get_session() as session:
            query = f"""
            CREATE INDEX {index_name} IF NOT EXISTS
            FOR (c:{chunk_label}) ON (c.chunkId)
            """
            session.run(query)

        logger.success(f"✓ Created index on {chunk_label}.chunkId")

    # ==========================================================================
    # Enterprise RAG: Vector Search Operations
    # ==========================================================================

    def vector_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        index_name: str | None = None,
    ) -> list[dict]:
        """
        Perform vector similarity search on chunk embeddings.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            index_name: Name of the vector index (auto-generated if label_prefix set)

        Returns:
            List of chunk dicts with similarity scores
        """
        # Auto-generate index name if using label prefix
        if index_name is None:
            if self.label_prefix:
                index_name = f"{self.label_prefix}_chunk_embeddings"
            else:
                index_name = "chunk_embeddings"

        with self._get_session() as session:
            query = """
            CALL db.index.vector.queryNodes($index_name, $top_k, $query_embedding)
            YIELD node, score
            RETURN node.chunkId AS chunk_id,
                   node.text AS text,
                   node.moduleId AS module_id,
                   node.section AS section,
                   node.chunkIndex AS chunk_index,
                   score
            """

            result = session.run(
                query,
                index_name=index_name,
                top_k=top_k,
                query_embedding=query_embedding,
            )

            return [dict(record) for record in result]

    def get_chunk_window(
        self, chunk_id: str, window_before: int = 1, window_after: int = 1
    ) -> list[dict]:
        """
        Get a chunk with its surrounding context via NEXT relationships.

        Args:
            chunk_id: ID of the central chunk
            window_before: Number of preceding chunks to include
            window_after: Number of following chunks to include

        Returns:
            List of chunk dicts in sequential order
        """
        chunk_label = self._get_label("Chunk")
        with self._get_session() as session:
            # Get preceding chunks (traverse NEXT backwards)
            # Get following chunks (traverse NEXT forwards)
            # Combine and order by chunk_index
            query = f"""
            MATCH (center:{chunk_label} {{chunkId: $chunk_id}})
            OPTIONAL MATCH path_before = (prev:{chunk_label})-[:NEXT*1..{window_before}]->(center)
            OPTIONAL MATCH path_after = (center)-[:NEXT*1..{window_after}]->(next:{chunk_label})
            WITH center,
                 collect(DISTINCT prev) AS before_chunks,
                 collect(DISTINCT next) AS after_chunks
            WITH before_chunks + [center] + after_chunks AS all_chunks
            UNWIND all_chunks AS chunk
            WITH DISTINCT chunk
            RETURN chunk.chunkId AS chunk_id,
                   chunk.text AS text,
                   chunk.moduleId AS module_id,
                   chunk.section AS section,
                   chunk.chunkIndex AS chunk_index
            ORDER BY chunk.chunkIndex
            """

            result = session.run(query, chunk_id=chunk_id)
            return [dict(record) for record in result]

    def fulltext_concept_search(
        self, query_text: str, limit: int = 10, index_name: str | None = None
    ) -> list[dict]:
        """
        Fuzzy search for concepts using fulltext index.

        Args:
            query_text: Search query
            limit: Maximum results
            index_name: Name of the fulltext index (auto-generated if label_prefix set)

        Returns:
            List of matching concepts with scores
        """
        # Auto-generate index name if using label prefix
        if index_name is None:
            if self.label_prefix:
                index_name = f"{self.label_prefix}_fullTextConceptNames"
            else:
                index_name = "fullTextConceptNames"

        with self._get_session() as session:
            query = """
            CALL db.index.fulltext.queryNodes($index_name, $query_text)
            YIELD node, score
            RETURN node.name AS name,
                   node.importance_score AS importance_score,
                   node.key_term AS key_term,
                   score
            LIMIT $limit
            """

            result = session.run(
                query,
                index_name=index_name,
                query_text=query_text,
                limit=limit,
            )

            return [dict(record) for record in result]


# ==========================================================================
# Factory Functions for Multi-Subject Support
# ==========================================================================

# Registry of adapters per subject
_neo4j_adapters: dict[str, Neo4jAdapter] = {}


def get_neo4j_adapter(subject_id: str | None = None) -> Neo4jAdapter:
    """
    Get or create a Neo4j adapter for a specific subject.

    Uses a registry pattern to reuse adapters per subject.

    Args:
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, uses the default subject.

    Returns:
        Neo4jAdapter configured for the subject
    """
    from backend.app.core.subjects import get_default_subject_id, get_subject

    # Use default subject if not specified
    if subject_id is None:
        subject_id = get_default_subject_id()

    # Return cached adapter if available
    if subject_id in _neo4j_adapters:
        adapter = _neo4j_adapters[subject_id]
        # Reconnect if driver is None
        if adapter.driver is None:
            adapter.connect()
        return adapter

    # Get subject configuration
    subject_config = get_subject(subject_id)

    # Create new adapter with subject-specific configuration
    adapter = Neo4jAdapter(
        database=subject_config.database.neo4j_database,
        label_prefix=subject_config.database.label_prefix,
    )
    adapter.connect()

    # Cache the adapter
    _neo4j_adapters[subject_id] = adapter

    return adapter


def clear_neo4j_adapters() -> None:
    """Close and clear all cached Neo4j adapters."""
    for adapter in _neo4j_adapters.values():
        adapter.close()
    _neo4j_adapters.clear()
    logger.info("Cleared all cached Neo4j adapters")
