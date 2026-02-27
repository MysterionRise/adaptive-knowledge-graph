"""
Pydantic models for post-quiz recommendation request/response payloads.
"""

from pydantic import BaseModel, Field


class QuizQuestionResult(BaseModel):
    question_id: str = Field(..., max_length=200)
    related_concept: str = Field(..., max_length=200)
    correct: bool


class RecommendationRequest(BaseModel):
    topic: str = Field(..., max_length=500)
    question_results: list[QuizQuestionResult]
    student_id: str = Field(default="default", max_length=100)
    subject: str | None = Field(default=None, max_length=100)


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
