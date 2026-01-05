from typing import List, Optional
from pydantic import BaseModel

class QuizOption(BaseModel):
    id: str
    text: str

class QuizQuestion(BaseModel):
    id: str
    text: str
    options: List[QuizOption]
    correct_option_id: str
    explanation: str
    source_chunk_id: Optional[str] = None
    related_concept: Optional[str] = None

class Quiz(BaseModel):
    id: str
    title: str
    questions: List[QuizQuestion]
