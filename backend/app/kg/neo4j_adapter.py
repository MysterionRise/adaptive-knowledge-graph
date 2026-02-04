"""
Neo4j adapter for persisting knowledge graphs.

Handles connection to Neo4j and CRUD operations for graph data.
"""

from loguru import logger
from neo4j import GraphDatabase, Session

from backend.app.core.settings import settings
from backend.app.kg.schema import ChunkNode, KnowledgeGraph, RelationshipType


class Neo4jAdapter:
    """Adapter for Neo4j graph database operations."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        """
        Initialize Neo4j adapter.

        Args:
            uri: Neo4j URI (defaults to settings)
            user: Neo4j user (defaults to settings)
            password: Neo4j password (defaults to settings)
        """
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self.driver = None

    def connect(self):
        """Connect to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # Test connection
            with self.driver.session() as session:
                result = session.run("RETURN 1 as test")
                result.single()
            logger.success(f"✓ Connected to Neo4j at {self.uri}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            logger.info("Closed Neo4j connection")

    def clear_database(self):
        """Clear all nodes and relationships (use with caution!)."""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        logger.warning("⚠️  Cleared Neo4j database")

    def persist_knowledge_graph(self, kg: KnowledgeGraph):
        """
        Persist complete knowledge graph to Neo4j.

        Args:
            kg: KnowledgeGraph to persist
        """
        logger.info("Persisting knowledge graph to Neo4j")

        with self.driver.session() as session:
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
        for _, concept in kg.concepts.items():
            query = """
            MERGE (c:Concept {name: $name})
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
        for _, module in kg.modules.items():
            query = """
            MERGE (m:Module {module_id: $module_id})
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
        for rel in kg.relationships:
            if rel.type == RelationshipType.COVERS:
                # Module -> Concept
                query = """
                MATCH (m:Module {module_id: $source})
                MATCH (c:Concept {name: $target})
                MERGE (m)-[r:COVERS]->(c)
                SET r.weight = $weight,
                    r.confidence = $confidence
                """
            elif rel.type == RelationshipType.RELATED:
                # Concept -> Concept
                query = """
                MATCH (c1:Concept {name: $source})
                MATCH (c2:Concept {name: $target})
                MERGE (c1)-[r:RELATED]-(c2)
                SET r.weight = $weight,
                    r.confidence = $confidence
                """
            elif rel.type == RelationshipType.PREREQ:
                # Concept -> Concept (prerequisite)
                query = """
                MATCH (c1:Concept {name: $source})
                MATCH (c2:Concept {name: $target})
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
        with self.driver.session() as session:
            query = f"""
            MATCH (c:Concept {{name: $name}})-[r*1..{max_hops}]-(neighbor:Concept)
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
        with self.driver.session() as session:
            stats = {}

            # Count nodes by type
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

        with self.driver.session() as session:
            # Process in batches for performance
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]

                query = """
                UNWIND $chunks AS chunk
                MERGE (c:Chunk {chunkId: chunk.chunk_id})
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
        with self.driver.session() as session:
            query = """
            UNWIND $pairs AS pair
            MATCH (c1:Chunk {chunkId: pair.from_id})
            MATCH (c2:Chunk {chunkId: pair.to_id})
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
        with self.driver.session() as session:
            query = """
            UNWIND $links AS link
            MATCH (m:Module {module_id: link.module_id})
            MATCH (c:Chunk {chunkId: link.chunk_id})
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

        with self.driver.session() as session:
            for i in range(0, len(chunk_concept_pairs), batch_size):
                batch = chunk_concept_pairs[i : i + batch_size]

                query = """
                UNWIND $pairs AS pair
                MATCH (chunk:Chunk {chunkId: pair.chunk_id})
                MATCH (concept:Concept {name: pair.concept_name})
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
        index_name: str = "chunk_embeddings",
        dimension: int = 1024,
        similarity_function: str = "cosine",
    ):
        """
        Create Neo4j native vector index on Chunk embeddings.

        Requires Neo4j 5.x with vector index support.

        Args:
            index_name: Name for the vector index
            dimension: Embedding dimension (1024 for BGE-M3)
            similarity_function: 'cosine' or 'euclidean'
        """
        with self.driver.session() as session:
            # Check if index already exists
            result = session.run("SHOW INDEXES YIELD name WHERE name = $name", name=index_name)
            if result.single():
                logger.info(f"Vector index '{index_name}' already exists")
                return

            # Create vector index (Neo4j 5.x syntax)
            query = f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (c:Chunk) ON (c.textEmbedding)
            OPTIONS {{
                indexConfig: {{
                    `vector.dimensions`: {dimension},
                    `vector.similarity_function`: '{similarity_function}'
                }}
            }}
            """
            session.run(query)

        logger.success(f"✓ Created vector index: {index_name}")

    def create_fulltext_index(self, index_name: str = "fullTextConceptNames"):
        """
        Create fulltext index for fuzzy concept name search.

        Args:
            index_name: Name for the fulltext index
        """
        with self.driver.session() as session:
            # Check if index already exists
            result = session.run("SHOW INDEXES YIELD name WHERE name = $name", name=index_name)
            if result.single():
                logger.info(f"Fulltext index '{index_name}' already exists")
                return

            # Create fulltext index
            query = f"""
            CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
            FOR (c:Concept) ON EACH [c.name]
            """
            session.run(query)

        logger.success(f"✓ Created fulltext index: {index_name}")

    def create_chunk_id_index(self):
        """Create index on Chunk.chunkId for faster lookups."""
        with self.driver.session() as session:
            query = """
            CREATE INDEX chunk_id_index IF NOT EXISTS
            FOR (c:Chunk) ON (c.chunkId)
            """
            session.run(query)

        logger.success("✓ Created index on Chunk.chunkId")

    # ==========================================================================
    # Enterprise RAG: Vector Search Operations
    # ==========================================================================

    def vector_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        index_name: str = "chunk_embeddings",
    ) -> list[dict]:
        """
        Perform vector similarity search on chunk embeddings.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            index_name: Name of the vector index

        Returns:
            List of chunk dicts with similarity scores
        """
        with self.driver.session() as session:
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
        with self.driver.session() as session:
            # Get preceding chunks (traverse NEXT backwards)
            # Get following chunks (traverse NEXT forwards)
            # Combine and order by chunk_index
            query = f"""
            MATCH (center:Chunk {{chunkId: $chunk_id}})
            OPTIONAL MATCH path_before = (prev:Chunk)-[:NEXT*1..{window_before}]->(center)
            OPTIONAL MATCH path_after = (center)-[:NEXT*1..{window_after}]->(next:Chunk)
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
        self, query_text: str, limit: int = 10, index_name: str = "fullTextConceptNames"
    ) -> list[dict]:
        """
        Fuzzy search for concepts using fulltext index.

        Args:
            query_text: Search query
            limit: Maximum results
            index_name: Name of the fulltext index

        Returns:
            List of matching concepts with scores
        """
        with self.driver.session() as session:
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
