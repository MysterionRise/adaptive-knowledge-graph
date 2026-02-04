import json
import re
import uuid
from typing import Literal

from loguru import logger

from backend.app.nlp.llm_client import get_llm_client
from backend.app.rag.retriever import get_retriever
from backend.app.ui_payloads.quiz import Quiz, QuizOption, QuizQuestion


class QuizGenerator:
    """Generates adaptive quizzes from knowledge graph content."""

    def __init__(self):
        self.llm = get_llm_client()
        self.retriever = get_retriever()

    async def generate_from_topic(self, topic: str, num_questions: int = 3) -> Quiz:
        """
        Generate a quiz based on a topic string.
        Retrieves relevant chunks -> Generates MCQ -> Returns Quiz object.
        """
        logger.info(f"Generating quiz for topic: {topic}")

        # 1. Retrieve content
        chunks = self.retriever.retrieve(query=topic, top_k=2)  # Get top 2 chunks for context
        if not chunks:
            logger.warning(f"No content found for topic: {topic}")
            raise ValueError(f"No content found for {topic}")

        # 2. Use the most relevant chunk for the quiz base
        # simpler MVP: generate questions from the top chunk
        base_chunk = chunks[0]
        context_text = base_chunk["text"]
        chunk_id = base_chunk.get("id")

        # 3. Prompt LLM with difficulty estimation
        system_prompt = """You are an expert exam creator for adult professional certification.
Create multiple-choice questions based ONLY on the provided text.
For each question, estimate its difficulty level:
- "easy": Direct recall from text, single fact
- "medium": Requires understanding of concepts, some inference
- "hard": Requires synthesis, analysis, or application of multiple concepts

Return the output as a valid JSON object with the following structure:
{
  "questions": [
    {
      "text": "Question text here?",
      "options": [
        {"id": "a", "text": "Option A"},
        {"id": "b", "text": "Option B"},
        {"id": "c", "text": "Option C"},
        {"id": "d", "text": "Option D"}
      ],
      "correct_option_id": "b",
      "explanation": "Brief explanation of why B is correct, based on the text.",
      "difficulty": "medium"
    }
  ]
}
"""
        user_prompt = f"""Create {num_questions} multiple-choice questions of varying difficulty based on this text:

TEXT:
{context_text}

Include a mix of easy, medium, and hard questions.
Ensure questions test understanding, not just recall.
JSON Output:"""

        try:
            response_text = await self.llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,  # low temp for structured output
                max_tokens=2048,
            )

            # Clean up potential markdown formatting (```json ... ```)
            cleaned_json = self._clean_json_response(response_text)
            data = json.loads(cleaned_json)

            questions = []
            total_difficulty = 0.0

            for q_data in data.get("questions", []):
                # Extract difficulty from LLM response
                difficulty_str = q_data.get("difficulty", "medium")
                difficulty, difficulty_score = self._parse_difficulty(difficulty_str)

                total_difficulty += difficulty_score

                q = QuizQuestion(
                    id=str(uuid.uuid4()),
                    text=q_data["text"],
                    options=[QuizOption(**opt) for opt in q_data["options"]],
                    correct_option_id=q_data["correct_option_id"],
                    explanation=q_data["explanation"],
                    source_chunk_id=chunk_id,
                    related_concept=topic,
                    difficulty=difficulty,
                    difficulty_score=difficulty_score,
                )
                questions.append(q)

            # Calculate average difficulty
            avg_difficulty = total_difficulty / len(questions) if questions else 0.5

            return Quiz(
                id=str(uuid.uuid4()),
                title=f"Assessment: {topic}",
                questions=questions,
                average_difficulty=round(avg_difficulty, 2),
            )

        except Exception as e:
            logger.error(f"Quiz generation failed: {e}")
            raise

    def _parse_difficulty(
        self, difficulty_str: str
    ) -> tuple[Literal["easy", "medium", "hard"], float]:
        """
        Parse difficulty string and return normalized level and score.

        Args:
            difficulty_str: Difficulty level from LLM (easy/medium/hard)

        Returns:
            Tuple of (difficulty level, IRT-style score 0.0-1.0)
        """
        difficulty_str = difficulty_str.lower().strip()

        if difficulty_str == "easy":
            return "easy", 0.3
        elif difficulty_str == "hard":
            return "hard", 0.8
        else:
            return "medium", 0.5

    def _clean_json_response(self, text: str) -> str:
        """Extract JSON from potential markdown blocks."""
        if "```json" in text:
            pattern = r"```json(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        if "```" in text:
            pattern = r"```(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        return text.strip()


# Global singleton
_quiz_generator: QuizGenerator | None = None


def get_quiz_generator() -> QuizGenerator:
    """Get global instance."""
    global _quiz_generator
    if _quiz_generator is None:
        _quiz_generator = QuizGenerator()
    return _quiz_generator
