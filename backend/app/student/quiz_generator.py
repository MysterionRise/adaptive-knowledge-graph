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

    def __init__(self, subject_id: str | None = None):
        """
        Initialize quiz generator.

        Args:
            subject_id: Subject identifier for multi-subject support.
                       If None, uses the default subject.
        """
        self.subject_id = subject_id
        self.llm = get_llm_client()
        self.retriever = get_retriever(subject_id)

    async def generate_from_topic(
        self,
        topic: str,
        num_questions: int = 3,
        target_difficulty: Literal["easy", "medium", "hard"] | None = None,
    ) -> Quiz:
        """
        Generate a quiz based on a topic string.

        Args:
            topic: The topic to generate questions about
            num_questions: Number of questions to generate
            target_difficulty: Optional specific difficulty level to target.
                               If None, generates mixed difficulty questions.

        Returns:
            Quiz object with generated questions
        """
        logger.info(
            f"Generating quiz for topic: {topic} "
            f"(target_difficulty={target_difficulty or 'mixed'})"
        )

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

        # 3. Build system prompt based on whether we're targeting a specific difficulty
        system_prompt = self._build_system_prompt(target_difficulty)
        user_prompt = self._build_user_prompt(num_questions, context_text, target_difficulty)

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
                # Use LLM-provided score if available, otherwise fall back to parsing
                llm_score = q_data.get("difficulty_score")
                if llm_score is not None:
                    difficulty_score = float(llm_score)
                    difficulty = self._score_to_difficulty(difficulty_score)
                else:
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

    def _build_system_prompt(
        self,
        target_difficulty: Literal["easy", "medium", "hard"] | None = None,
    ) -> str:
        """Build system prompt based on difficulty targeting."""
        base_prompt = """You are an expert exam creator for adult professional certification.
Create multiple-choice questions based ONLY on the provided text.
For each question, estimate its difficulty:
- "difficulty": one of "easy", "medium", or "hard"
- "difficulty_score": a precise number from 0.0 to 1.0 where:
  - 0.0-0.3: Easy (direct recall, single fact)
  - 0.3-0.6: Medium (requires understanding, some inference)
  - 0.6-1.0: Hard (synthesis, analysis, application of multiple concepts)

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
      "difficulty": "medium",
      "difficulty_score": 0.45
    }
  ]
}
"""
        if target_difficulty:
            difficulty_guidance = {
                "easy": """
IMPORTANT: Generate ONLY EASY questions with difficulty_score between 0.1 and 0.3. Easy questions should:
- Test direct recall of facts stated in the text
- Have one clearly correct answer that is explicitly stated
- Avoid requiring inference or connecting multiple concepts
- Use simple, straightforward language""",
                "medium": """
IMPORTANT: Generate ONLY MEDIUM difficulty questions with difficulty_score between 0.35 and 0.6. Medium questions should:
- Require understanding and application of concepts
- May need connecting two related facts from the text
- Test comprehension, not just memorization
- Have plausible distractors but a clear correct answer""",
                "hard": """
IMPORTANT: Generate ONLY HARD questions with difficulty_score between 0.65 and 0.9. Hard questions should:
- Require synthesis or analysis of multiple concepts
- Test application to new scenarios or deeper understanding
- May require making inferences beyond what's explicitly stated
- Have sophisticated distractors that require careful analysis""",
            }
            return base_prompt + difficulty_guidance.get(target_difficulty, "")

        return base_prompt

    def _build_user_prompt(
        self,
        num_questions: int,
        context_text: str,
        target_difficulty: Literal["easy", "medium", "hard"] | None = None,
    ) -> str:
        """Build user prompt based on difficulty targeting."""
        if target_difficulty:
            return f"""Create {num_questions} multiple-choice questions at the {target_difficulty.upper()} difficulty level based on this text:

TEXT:
{context_text}

REMEMBER: ALL questions must be {target_difficulty.upper()} difficulty.
Ensure questions test understanding appropriate for {target_difficulty} level.
JSON Output:"""
        else:
            return f"""Create {num_questions} multiple-choice questions of varying difficulty based on this text:

TEXT:
{context_text}

Include a mix of easy, medium, and hard questions.
Ensure questions test understanding, not just recall.
JSON Output:"""

    def _score_to_difficulty(self, score: float) -> Literal["easy", "medium", "hard"]:
        """Convert numeric score to difficulty label."""
        if score < 0.35:
            return "easy"
        elif score < 0.65:
            return "medium"
        else:
            return "hard"

    def _parse_difficulty(
        self, difficulty_str: str
    ) -> tuple[Literal["easy", "medium", "hard"], float]:
        """
        Parse difficulty string and return normalized level and score.
        Fallback when LLM doesn't provide numeric score.

        Args:
            difficulty_str: Difficulty level from LLM (easy/medium/hard)

        Returns:
            Tuple of (difficulty level, IRT-style score 0.0-1.0)
        """
        difficulty_str = difficulty_str.lower().strip()

        if difficulty_str == "easy":
            return "easy", 0.25
        elif difficulty_str == "hard":
            return "hard", 0.75
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


# Global singleton for backward compatibility
_quiz_generator: QuizGenerator | None = None

# Registry of quiz generators per subject
_quiz_generators: dict[str, QuizGenerator] = {}


def get_quiz_generator(subject_id: str | None = None) -> QuizGenerator:
    """
    Get or create a quiz generator instance for a specific subject.

    Args:
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, uses the default singleton for backward compatibility.

    Returns:
        QuizGenerator instance configured for the subject
    """
    global _quiz_generator

    # Backward compatibility: if no subject_id, use default singleton
    if subject_id is None:
        if _quiz_generator is None:
            _quiz_generator = QuizGenerator()
        return _quiz_generator

    # Return cached generator if available
    if subject_id in _quiz_generators:
        return _quiz_generators[subject_id]

    # Create new generator with subject-specific configuration
    generator = QuizGenerator(subject_id=subject_id)

    # Cache the generator
    _quiz_generators[subject_id] = generator

    return generator


def clear_quiz_generators() -> None:
    """Clear all cached quiz generators."""
    global _quiz_generator
    _quiz_generator = None
    _quiz_generators.clear()
    logger.info("Cleared all cached quiz generators")
