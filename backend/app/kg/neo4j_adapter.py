"""
Neo4j adapter for persisting knowledge graphs.

Handles connection to Neo4j and CRUD operations for graph data.
"""


from loguru import logger
from neo4j import GraphDatabase, Session

from backend.app.core.settings import settings
from backend.app.kg.schema import KnowledgeGraph, RelationshipType


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

        logger.success(f"✓ Persisted KG with {len(kg.concepts)} concepts and {len(kg.relationships)} relationships")

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

    def query_concept_neighbors(
        self, concept_name: str, max_hops: int = 1
    ) -> list[dict]:
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
