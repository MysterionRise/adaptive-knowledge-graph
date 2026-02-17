"""
Pydantic models for post-quiz recommendation request/response payloads.
"""

from pydantic import BaseModel


class QuizQuestionResult(BaseModel):
    question_id: str
    related_concept: str
    correct: bool


class RecommendationRequest(BaseModel):
    topic: str
    question_results: list[QuizQuestionResult]
    student_id: str = "default"
    subject: str | None = None


class ReadingMaterial(BaseModel):
    text: str
    section: str | None = None
    module_title: str | None = None
    relevance_score: float | None = None


class ConceptRecommendation(BaseModel):
    name: str
    importance: float | None = None
    mastery: float | None = None
    relationship_type: str | None = None


class RemediationBlock(BaseModel):
    concept: str
    prerequisites: list[ConceptRecommendation] = []
    reading_materials: list[ReadingMaterial] = []


class AdvancementBlock(BaseModel):
    concept: str
    advanced_topics: list[ConceptRecommendation] = []
    deep_dive_content: str | None = None


class RecommendationResponse(BaseModel):
    path_type: str  # "remediation", "advancement", or "mixed"
    score_pct: float
    remediation: list[RemediationBlock] = []
    advancement: list[AdvancementBlock] = []
    summary: str
