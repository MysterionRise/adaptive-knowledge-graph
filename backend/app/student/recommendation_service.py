"""
Post-quiz recommendation service.

Orchestrates KG queries, RAG retrieval, and LLM generation to produce
personalized recommendations after a quiz attempt.
"""

import asyncio

from loguru import logger

from backend.app.kg.neo4j_adapter import Neo4jAdapter, get_neo4j_adapter
from backend.app.nlp.llm_client import LLMClient, get_llm_client
from backend.app.rag.retriever import OpenSearchRetriever, get_retriever
from backend.app.student.student_service import StudentService, get_student_service
from backend.app.ui_payloads.recommendations import (
    AdvancementBlock,
    ConceptRecommendation,
    QuizQuestionResult,
    ReadingMaterial,
    RecommendationResponse,
    RemediationBlock,
)

# LLM timeout for deep-dive generation
_DEEP_DIVE_TIMEOUT_SECONDS = 30


class RecommendationService:
    """Generates post-quiz recommendations using KG + RAG + LLM."""

    def __init__(
        self,
        neo4j: Neo4jAdapter,
        retriever: OpenSearchRetriever,
        llm: LLMClient,
        student_service: StudentService,
    ):
        self.neo4j = neo4j
        self.retriever = retriever
        self.llm = llm
        self.student_service = student_service

    async def generate_recommendations(
        self,
        topic: str,
        question_results: list[QuizQuestionResult],
        student_id: str = "default",
    ) -> RecommendationResponse:
        total = len(question_results)
        correct_count = sum(1 for qr in question_results if qr.correct)
        score_pct = (correct_count / total * 100) if total > 0 else 0

        # Classify path type
        if score_pct < 50:
            path_type = "remediation"
        elif score_pct > 80:
            path_type = "advancement"
        else:
            path_type = "mixed"

        # Deduplicate concepts and group by correctness
        weak_concepts: list[str] = []
        strong_concepts: list[str] = []
        seen_weak: set[str] = set()
        seen_strong: set[str] = set()

        for qr in question_results:
            concept = qr.related_concept
            if not qr.correct and concept not in seen_weak:
                weak_concepts.append(concept)
                seen_weak.add(concept)
            elif qr.correct and concept not in seen_strong:
                strong_concepts.append(concept)
                seen_strong.add(concept)

        # Build remediation blocks for weak concepts
        remediation: list[RemediationBlock] = []
        if path_type in ("remediation", "mixed"):
            for concept in weak_concepts:
                block = self._build_remediation_block(concept, student_id)
                remediation.append(block)

        # Build advancement blocks for strong concepts (only when score > 80%)
        advancement: list[AdvancementBlock] = []
        if path_type in ("advancement", "mixed"):
            for concept in strong_concepts:
                adv_block = await self._build_advancement_block(concept, student_id)
                advancement.append(adv_block)

        # Generate summary
        summary = self._generate_summary(path_type, score_pct, weak_concepts, strong_concepts)

        return RecommendationResponse(
            path_type=path_type,
            score_pct=round(score_pct, 1),
            remediation=remediation,
            advancement=advancement,
            summary=summary,
        )

    def _build_remediation_block(self, concept: str, student_id: str) -> RemediationBlock:
        """Build a remediation block for a weak concept."""
        # Query prerequisites from KG
        prerequisites = self._query_prerequisites(concept)

        # If no prerequisites, fall back to RELATED concepts
        if not prerequisites:
            prerequisites = self._query_related(concept)

        # Add mastery levels from student profile
        profile = self.student_service.get_profile(student_id)
        for prereq in prerequisites:
            prereq.mastery = round(profile.get_mastery(prereq.name), 3)

        # Fetch reading materials via OpenSearch
        reading_materials = self._fetch_reading_materials(concept, top_k=2)

        return RemediationBlock(
            concept=concept,
            prerequisites=prerequisites,
            reading_materials=reading_materials,
        )

    async def _build_advancement_block(self, concept: str, student_id: str) -> AdvancementBlock:
        """Build an advancement block for a strong concept."""
        # Query dependent/advanced concepts from KG
        advanced_topics = self._query_dependents(concept)

        # Add mastery levels
        profile = self.student_service.get_profile(student_id)
        for adv in advanced_topics:
            adv.mastery = round(profile.get_mastery(adv.name), 3)

        # Generate deep dive for the top concept (with timeout)
        deep_dive_content = await self._generate_deep_dive(concept)

        return AdvancementBlock(
            concept=concept,
            advanced_topics=advanced_topics,
            deep_dive_content=deep_dive_content,
        )

    def _query_prerequisites(self, concept: str) -> list[ConceptRecommendation]:
        """Query prerequisite concepts from Neo4j via PREREQ relationships."""
        concept_label = self.neo4j._get_label("Concept")
        try:
            with self.neo4j._get_session() as session:
                query = f"""
                MATCH (c:{concept_label} {{name: $name}})<-[:PREREQ]-(prereq:{concept_label})
                RETURN prereq.name AS name,
                       prereq.importance_score AS importance
                ORDER BY prereq.importance_score DESC
                LIMIT 5
                """
                result = session.run(query, name=concept)
                return [
                    ConceptRecommendation(
                        name=record["name"],
                        importance=record["importance"],
                        relationship_type="PREREQ",
                    )
                    for record in result
                ]
        except Exception as e:
            logger.warning(f"Failed to query prerequisites for {concept}: {e}")
            return []

    def _query_related(self, concept: str) -> list[ConceptRecommendation]:
        """Fallback: query RELATED concepts when no prerequisites exist."""
        concept_label = self.neo4j._get_label("Concept")
        try:
            with self.neo4j._get_session() as session:
                query = f"""
                MATCH (c:{concept_label} {{name: $name}})-[:RELATED]-(related:{concept_label})
                RETURN related.name AS name,
                       related.importance_score AS importance
                ORDER BY related.importance_score DESC
                LIMIT 5
                """
                result = session.run(query, name=concept)
                return [
                    ConceptRecommendation(
                        name=record["name"],
                        importance=record["importance"],
                        relationship_type="RELATED",
                    )
                    for record in result
                ]
        except Exception as e:
            logger.warning(f"Failed to query related concepts for {concept}: {e}")
            return []

    def _query_dependents(self, concept: str) -> list[ConceptRecommendation]:
        """Query concepts that depend on this one (i.e., this concept is their prerequisite)."""
        concept_label = self.neo4j._get_label("Concept")
        try:
            with self.neo4j._get_session() as session:
                query = f"""
                MATCH (c:{concept_label} {{name: $name}})-[:PREREQ]->(dependent:{concept_label})
                RETURN dependent.name AS name,
                       dependent.importance_score AS importance
                ORDER BY dependent.importance_score DESC
                LIMIT 5
                """
                result = session.run(query, name=concept)
                topics = [
                    ConceptRecommendation(
                        name=record["name"],
                        importance=record["importance"],
                        relationship_type="PREREQ",
                    )
                    for record in result
                ]

                # If no dependents via PREREQ, try RELATED
                if not topics:
                    query = f"""
                    MATCH (c:{concept_label} {{name: $name}})-[:RELATED]-(related:{concept_label})
                    RETURN related.name AS name,
                           related.importance_score AS importance
                    ORDER BY related.importance_score DESC
                    LIMIT 5
                    """
                    result = session.run(query, name=concept)
                    topics = [
                        ConceptRecommendation(
                            name=record["name"],
                            importance=record["importance"],
                            relationship_type="RELATED",
                        )
                        for record in result
                    ]

                return topics
        except Exception as e:
            logger.warning(f"Failed to query dependents for {concept}: {e}")
            return []

    def _fetch_reading_materials(self, concept: str, top_k: int = 2) -> list[ReadingMaterial]:
        """Fetch reading material chunks from OpenSearch."""
        try:
            chunks = self.retriever.retrieve(query=concept, top_k=top_k)
            return [
                ReadingMaterial(
                    text=chunk["text"],
                    section=chunk.get("section"),
                    module_title=chunk.get("module_title"),
                    relevance_score=chunk.get("score"),
                )
                for chunk in chunks
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch reading materials for {concept}: {e}")
            return []

    async def _generate_deep_dive(self, concept: str) -> str | None:
        """Generate a deep-dive explanation using LLM with timeout."""
        prompt = (
            f"Provide a concise deep-dive explanation (2-3 paragraphs) of '{concept}' "
            f"for a student who has already demonstrated mastery of the basics. "
            f"Focus on nuances, historical significance, and connections to broader themes."
        )
        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt=prompt, temperature=0.7, max_tokens=512),
                timeout=_DEEP_DIVE_TIMEOUT_SECONDS,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Deep dive generation timed out for {concept}")
            return None
        except Exception as e:
            logger.warning(f"Deep dive generation failed for {concept}: {e}")
            return None

    def _generate_summary(
        self,
        path_type: str,
        score_pct: float,
        weak_concepts: list[str],
        strong_concepts: list[str],
    ) -> str:
        """Generate a human-readable summary of the recommendations."""
        if path_type == "remediation":
            areas = ", ".join(weak_concepts[:3]) or "the quiz topics"
            return (
                f"You scored {score_pct:.0f}%. "
                f"We recommend reviewing {areas} and their prerequisites before moving on."
            )
        elif path_type == "advancement":
            areas = ", ".join(strong_concepts[:3]) or "the quiz topics"
            return (
                f"Excellent! You scored {score_pct:.0f}%. "
                f"You've demonstrated strong mastery of {areas}. "
                f"Explore the advanced topics below to deepen your understanding."
            )
        else:
            weak = ", ".join(weak_concepts[:2]) or "some areas"
            strong = ", ".join(strong_concepts[:2]) or "other areas"
            return (
                f"You scored {score_pct:.0f}%. "
                f"You're doing well on {strong}, but could strengthen {weak}. "
                f"See targeted recommendations below."
            )


# Singleton registry
_recommendation_services: dict[str, RecommendationService] = {}


def get_recommendation_service(subject: str | None = None) -> RecommendationService:
    """Get or create a RecommendationService instance for a subject."""
    key = subject or "_default"

    if key not in _recommendation_services:
        _recommendation_services[key] = RecommendationService(
            neo4j=get_neo4j_adapter(subject),
            retriever=get_retriever(subject),
            llm=get_llm_client(),
            student_service=get_student_service(),
        )

    return _recommendation_services[key]
