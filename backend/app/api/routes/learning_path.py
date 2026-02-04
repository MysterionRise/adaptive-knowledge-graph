"""
Learning path and prerequisite chain endpoints.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from backend.app.core.exceptions import Neo4jConnectionError

router = APIRouter(tags=["Learning Path"])


class ConceptNode(BaseModel):
    """A concept in the learning path."""

    id: str
    name: str
    importance: float
    chapter: str | None = None
    depth: int  # Distance from target concept


class LearningPathResponse(BaseModel):
    """Response for learning path query."""

    target_concept: str
    prerequisites: list[ConceptNode]
    total_concepts: int


class PrerequisiteResponse(BaseModel):
    """Response for prerequisite query."""

    concept: str
    prerequisites: list[dict]
    depth: int


@router.get("/learning-path/{concept_name}", response_model=LearningPathResponse)
async def get_learning_path(concept_name: str, max_depth: int = 3):
    """
    Get the prerequisite chain for a concept.

    Returns concepts in learning order (prerequisites first, target last).

    Args:
        concept_name: Name of the target concept
        max_depth: Maximum depth to traverse (default 3)
    """
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            # Find prerequisites recursively using variable-length path
            result = session.run(
                """
                MATCH path = (prereq:Concept)-[:PREREQUISITE*1..]->(target:Concept {name: $name})
                WHERE length(path) <= $max_depth
                WITH prereq, length(path) as depth
                RETURN DISTINCT
                    elementId(prereq) as id,
                    prereq.name as name,
                    coalesce(prereq.importance_score, 0.5) as importance,
                    prereq.chapter as chapter,
                    depth
                ORDER BY depth DESC, importance DESC
                """,
                name=concept_name,
                max_depth=max_depth,
            )

            prerequisites = [
                ConceptNode(
                    id=record["id"],
                    name=record["name"],
                    importance=float(record["importance"]),
                    chapter=record["chapter"],
                    depth=record["depth"],
                )
                for record in result
            ]

        adapter.close()

        return LearningPathResponse(
            target_concept=concept_name,
            prerequisites=prerequisites,
            total_concepts=len(prerequisites) + 1,  # +1 for target
        )

    except Neo4jConnectionError as e:
        logger.error(f"Neo4j connection failed: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed") from e
    except Exception as e:
        logger.error(f"Error getting learning path: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/concepts/{concept_name}/prerequisites", response_model=PrerequisiteResponse)
async def get_prerequisites(concept_name: str, depth: int = 2):
    """
    Get prerequisites for a concept up to N levels deep.

    Args:
        concept_name: Name of the concept
        depth: Maximum depth to traverse (default 2)
    """
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            # Get direct and indirect prerequisites
            result = session.run(
                """
                MATCH (target:Concept {name: $name})
                OPTIONAL MATCH path = (prereq:Concept)-[:PREREQUISITE*1..]->(target)
                WHERE length(path) <= $depth
                WITH prereq, length(path) as level
                WHERE prereq IS NOT NULL
                RETURN DISTINCT
                    prereq.name as name,
                    coalesce(prereq.importance_score, 0.5) as importance,
                    prereq.chapter as chapter,
                    level
                ORDER BY level ASC, importance DESC
                """,
                name=concept_name,
                depth=depth,
            )

            prerequisites = [
                {
                    "name": record["name"],
                    "importance": float(record["importance"]),
                    "chapter": record["chapter"],
                    "level": record["level"],
                }
                for record in result
            ]

        adapter.close()

        return PrerequisiteResponse(
            concept=concept_name,
            prerequisites=prerequisites,
            depth=depth,
        )

    except Exception as e:
        logger.error(f"Error getting prerequisites: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/concepts/{concept_name}/dependents")
async def get_dependents(concept_name: str, depth: int = 2):
    """
    Get concepts that depend on this concept (reverse prerequisites).

    Args:
        concept_name: Name of the concept
        depth: Maximum depth to traverse (default 2)
    """
    try:
        from backend.app.kg.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        adapter.connect()

        with adapter.driver.session() as session:
            # Get concepts that have this as a prerequisite
            result = session.run(
                """
                MATCH (source:Concept {name: $name})
                OPTIONAL MATCH path = (source)-[:PREREQUISITE*1..]->(dependent:Concept)
                WHERE length(path) <= $depth
                WITH dependent, length(path) as level
                WHERE dependent IS NOT NULL
                RETURN DISTINCT
                    dependent.name as name,
                    coalesce(dependent.importance_score, 0.5) as importance,
                    dependent.chapter as chapter,
                    level
                ORDER BY level ASC, importance DESC
                """,
                name=concept_name,
                depth=depth,
            )

            dependents = [
                {
                    "name": record["name"],
                    "importance": float(record["importance"]),
                    "chapter": record["chapter"],
                    "level": record["level"],
                }
                for record in result
            ]

        adapter.close()

        return {
            "concept": concept_name,
            "dependents": dependents,
            "depth": depth,
        }

    except Exception as e:
        logger.error(f"Error getting dependents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
