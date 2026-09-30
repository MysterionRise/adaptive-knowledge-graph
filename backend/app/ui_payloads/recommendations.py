"""
Pydantic models for post-quiz recommendation request/response payloads.
"""

from pydantic import BaseModel, Field

from backend.app.ui_payloads.constraints import (
    DEFAULT_STUDENT_ID,
    ConceptStr,
    StudentId,
    SubjectId,
    TopicStr,
)

# Each concept can trigger KG queries and an LLM call, so a request is bounded
# (a generated quiz has at most 20 questions).
MAX_QUESTION_RESULTS = 50


class QuizQuestionResult(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=200)
    related_concept: ConceptStr
    correct: bool


class RecommendationRequest(BaseModel):
    topic: TopicStr
    question_results: list[QuizQuestionResult] = Field(..., max_length=MAX_QUESTION_RESULTS)
    student_id: StudentId = DEFAULT_STUDENT_ID
    subject: SubjectId | None = None


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
