"""
Tests for the recommendation service module.

Tests cover:
- Path type classification based on quiz score (remediation, advancement, mixed)
- Remediation block construction (prerequisites, fallback to RELATED, mastery, reading materials)
- Advancement block construction (dependents, deep dive generation, timeout/error handling)
- Summary text generation for each path type
- Concept deduplication across multiple quiz questions
- Graceful error handling for Neo4j and retriever failures
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.student.recommendation_service import RecommendationService
from backend.app.ui_payloads.recommendations import QuizQuestionResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_question(concept: str, correct: bool, qid: str = "q1") -> QuizQuestionResult:
    """Create a QuizQuestionResult with sensible defaults."""
    return QuizQuestionResult(question_id=qid, related_concept=concept, correct=correct)


def _make_questions(n_correct: int, n_total: int) -> list[QuizQuestionResult]:
    """Generate a list of quiz results with the given correct/total split.

    The first *n_correct* items are correct, the rest are incorrect.
    Each question uses a unique concept so deduplication does not interfere.
    """
    results: list[QuizQuestionResult] = []
    for i in range(n_total):
        results.append(
            _make_question(
                concept=f"concept_{i}",
                correct=i < n_correct,
                qid=f"q{i}",
            )
        )
    return results


def _build_mocks():
    """Create a full set of mocks matching RecommendationService dependencies.

    Returns (service, mock_neo4j, mock_retriever, mock_llm, mock_student, mock_session).
    """
    # Neo4j mock with context-manager session
    mock_neo4j = MagicMock()
    mock_neo4j._get_label.side_effect = lambda base: f"test_{base}"
    mock_session = MagicMock()
    mock_neo4j._get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_neo4j._get_session.return_value.__exit__ = MagicMock(return_value=False)
    # Default: no records from Neo4j
    mock_session.run.return_value = []

    # Retriever mock
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []

    # LLM mock (async) – default return must be a string to satisfy Pydantic
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "Default deep dive content."

    # Student service mock
    mock_student = MagicMock()
    mock_profile = MagicMock()
    mock_profile.get_mastery.return_value = 0.5
    mock_student.get_profile.return_value = mock_profile

    service = RecommendationService(
        neo4j=mock_neo4j,
        retriever=mock_retriever,
        llm=mock_llm,
        student_service=mock_student,
    )

    return service, mock_neo4j, mock_retriever, mock_llm, mock_student, mock_session


# ---------------------------------------------------------------------------
# 1. Path-type classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathTypeClassification:
    """Verify that score_pct maps to the correct path_type string."""

    @pytest.mark.asyncio
    async def test_remediation_below_50(self):
        """Score < 50% should produce 'remediation'."""
        svc, *_ = _build_mocks()
        # 2 out of 5 correct -> 40%
        result = await svc.generate_recommendations("topic", _make_questions(2, 5))
        assert result.path_type == "remediation"
        assert result.score_pct == 40.0

    @pytest.mark.asyncio
    async def test_advancement_above_80(self):
        """Score > 80% should produce 'advancement'."""
        svc, *_ = _build_mocks()
        # 9 out of 10 correct -> 90%
        result = await svc.generate_recommendations("topic", _make_questions(9, 10))
        assert result.path_type == "advancement"
        assert result.score_pct == 90.0

    @pytest.mark.asyncio
    async def test_mixed_between_50_and_80(self):
        """50% <= score <= 80% should produce 'mixed'."""
        svc, *_ = _build_mocks()
        # 3 out of 5 correct -> 60%
        result = await svc.generate_recommendations("topic", _make_questions(3, 5))
        assert result.path_type == "mixed"
        assert result.score_pct == 60.0

    @pytest.mark.asyncio
    async def test_edge_exactly_50(self):
        """Exactly 50% is NOT < 50, so path_type should be 'mixed'."""
        svc, *_ = _build_mocks()
        # 5 out of 10 -> 50%
        result = await svc.generate_recommendations("topic", _make_questions(5, 10))
        assert result.path_type == "mixed"
        assert result.score_pct == 50.0

    @pytest.mark.asyncio
    async def test_edge_exactly_80(self):
        """Exactly 80% is NOT > 80, so path_type should be 'mixed'."""
        svc, *_ = _build_mocks()
        # 4 out of 5 -> 80%
        result = await svc.generate_recommendations("topic", _make_questions(4, 5))
        assert result.path_type == "mixed"
        assert result.score_pct == 80.0

    @pytest.mark.asyncio
    async def test_edge_zero_percent(self):
        """0% (all wrong) should produce 'remediation'."""
        svc, *_ = _build_mocks()
        result = await svc.generate_recommendations("topic", _make_questions(0, 5))
        assert result.path_type == "remediation"
        assert result.score_pct == 0.0

    @pytest.mark.asyncio
    async def test_edge_hundred_percent(self):
        """100% (all correct) should produce 'advancement'."""
        svc, *_ = _build_mocks()
        result = await svc.generate_recommendations("topic", _make_questions(5, 5))
        assert result.path_type == "advancement"
        assert result.score_pct == 100.0


# ---------------------------------------------------------------------------
# 2. Remediation blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemediationBlock:
    """Verify remediation block construction logic."""

    @pytest.mark.asyncio
    async def test_prerequisites_from_kg(self):
        """When the KG has PREREQ edges, they appear as prerequisites."""
        svc, mock_neo4j, _, _, _, mock_session = _build_mocks()

        # First session.run call returns PREREQ records
        mock_session.run.return_value = [
            {"name": "algebra", "importance": 0.9},
            {"name": "arithmetic", "importance": 0.7},
        ]

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "remediation"
        assert len(result.remediation) == 1
        block = result.remediation[0]
        assert block.concept == "calculus"
        assert len(block.prerequisites) == 2
        assert block.prerequisites[0].name == "algebra"
        assert block.prerequisites[0].importance == 0.9
        assert block.prerequisites[0].relationship_type == "PREREQ"

    @pytest.mark.asyncio
    async def test_fallback_to_related_when_no_prereqs(self):
        """When PREREQ query returns nothing, RELATED concepts are used."""
        svc, mock_neo4j, _, _, _, mock_session = _build_mocks()

        # First call (PREREQ) -> empty, second call (RELATED) -> results
        mock_session.run.side_effect = [
            [],  # _query_prerequisites returns empty
            [{"name": "linear_algebra", "importance": 0.6}],  # _query_related
        ]

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        block = result.remediation[0]
        assert len(block.prerequisites) == 1
        assert block.prerequisites[0].name == "linear_algebra"
        assert block.prerequisites[0].relationship_type == "RELATED"

    @pytest.mark.asyncio
    async def test_mastery_enrichment_from_student_profile(self):
        """Prerequisites should have mastery scores from the student profile."""
        svc, _, _, _, mock_student, mock_session = _build_mocks()

        mock_profile = MagicMock()
        mock_profile.get_mastery.side_effect = lambda name: {"algebra": 0.3, "arithmetic": 0.8}.get(
            name, 0.0
        )
        mock_student.get_profile.return_value = mock_profile

        mock_session.run.return_value = [
            {"name": "algebra", "importance": 0.9},
            {"name": "arithmetic", "importance": 0.7},
        ]

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        prereqs = result.remediation[0].prerequisites
        assert prereqs[0].mastery == 0.3
        assert prereqs[1].mastery == 0.8

    @pytest.mark.asyncio
    async def test_reading_materials_from_retriever(self):
        """Retriever results should populate reading_materials."""
        svc, _, mock_retriever, _, _, mock_session = _build_mocks()

        mock_session.run.return_value = [{"name": "prereq", "importance": 0.5}]
        mock_retriever.retrieve.return_value = [
            {
                "text": "Calculus is the study of continuous change.",
                "section": "Chapter 3",
                "module_title": "Introduction to Calculus",
                "score": 0.92,
            },
            {
                "text": "Limits form the foundation of calculus.",
                "section": "Chapter 3.1",
                "module_title": "Introduction to Calculus",
                "score": 0.87,
            },
        ]

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        materials = result.remediation[0].reading_materials
        assert len(materials) == 2
        assert materials[0].text == "Calculus is the study of continuous change."
        assert materials[0].section == "Chapter 3"
        assert materials[0].module_title == "Introduction to Calculus"
        assert materials[0].relevance_score == 0.92
        assert materials[1].text == "Limits form the foundation of calculus."

        # Verify retrieve was called with the concept and top_k=2
        mock_retriever.retrieve.assert_called_once_with(query="calculus", top_k=2)

    @pytest.mark.asyncio
    async def test_no_remediation_for_advancement_path(self):
        """When path is 'advancement', remediation list should be empty."""
        svc, *_ = _build_mocks()
        # All correct -> advancement path
        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)
        assert result.path_type == "advancement"
        assert result.remediation == []


# ---------------------------------------------------------------------------
# 3. Advancement blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdvancementBlock:
    """Verify advancement block construction logic."""

    @pytest.mark.asyncio
    async def test_dependent_concepts(self):
        """Advancement block should contain dependent concepts from the KG."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()

        mock_session.run.return_value = [
            {"name": "multivariable_calculus", "importance": 0.85},
        ]
        mock_llm.generate.return_value = "Deep dive content."

        # All correct -> advancement
        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "advancement"
        assert len(result.advancement) >= 1
        # First strong concept block
        block = result.advancement[0]
        assert len(block.advanced_topics) == 1
        assert block.advanced_topics[0].name == "multivariable_calculus"
        assert block.advanced_topics[0].relationship_type == "PREREQ"

    @pytest.mark.asyncio
    async def test_deep_dive_generation(self):
        """LLM should generate deep-dive content for strong concepts."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()

        mock_session.run.return_value = []
        mock_llm.generate.return_value = "A nuanced exploration of this concept."

        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        block = result.advancement[0]
        assert block.deep_dive_content == "A nuanced exploration of this concept."
        mock_llm.generate.assert_called()
        call_kwargs = mock_llm.generate.call_args[1]
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_deep_dive_timeout_returns_none(self):
        """When LLM generation exceeds the timeout, deep_dive_content should be None."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()
        mock_session.run.return_value = []

        # Simulate a timeout by making generate raise TimeoutError
        async def slow_generate(**kwargs):
            raise asyncio.TimeoutError()

        mock_llm.generate.side_effect = slow_generate

        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        block = result.advancement[0]
        assert block.deep_dive_content is None

    @pytest.mark.asyncio
    async def test_deep_dive_error_returns_none(self):
        """When LLM generation fails with a generic exception, deep_dive_content should be None."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()
        mock_session.run.return_value = []

        async def failing_generate(**kwargs):
            raise RuntimeError("LLM service unavailable")

        mock_llm.generate.side_effect = failing_generate

        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        block = result.advancement[0]
        assert block.deep_dive_content is None

    @pytest.mark.asyncio
    async def test_no_advancement_for_remediation_path(self):
        """When path is 'remediation', advancement list should be empty."""
        svc, *_ = _build_mocks()
        # All wrong -> remediation path
        questions = _make_questions(0, 5)
        result = await svc.generate_recommendations("topic", questions)
        assert result.path_type == "remediation"
        assert result.advancement == []

    @pytest.mark.asyncio
    async def test_mastery_on_advanced_topics(self):
        """Advanced topics should get mastery values from the student profile."""
        svc, _, _, mock_llm, mock_student, mock_session = _build_mocks()

        mock_profile = MagicMock()
        mock_profile.get_mastery.return_value = 0.123
        mock_student.get_profile.return_value = mock_profile

        mock_session.run.return_value = [
            {"name": "advanced_topic_1", "importance": 0.9},
        ]
        mock_llm.generate.return_value = "Content."

        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        adv = result.advancement[0].advanced_topics[0]
        assert adv.mastery == 0.123


# ---------------------------------------------------------------------------
# 4. Summary generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateSummary:
    """Verify summary text reflects path type, score, and concepts."""

    @pytest.mark.asyncio
    async def test_remediation_summary(self):
        """Remediation summary mentions the score and weak areas."""
        svc, *_ = _build_mocks()
        # 1 out of 5 -> 20% remediation
        questions = [
            _make_question("algebra", correct=False, qid="q0"),
            _make_question("geometry", correct=False, qid="q1"),
            _make_question("calculus", correct=False, qid="q2"),
            _make_question("topology", correct=False, qid="q3"),
            _make_question("statistics", correct=True, qid="q4"),
        ]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "remediation"
        assert "20%" in result.summary
        assert "reviewing" in result.summary
        # At most 3 weak concepts shown in summary
        assert "algebra" in result.summary

    @pytest.mark.asyncio
    async def test_advancement_summary(self):
        """Advancement summary congratulates and mentions strong areas."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()
        mock_session.run.return_value = []
        mock_llm.generate.return_value = "Deep dive."

        questions = [
            _make_question("algebra", correct=True, qid="q0"),
            _make_question("geometry", correct=True, qid="q1"),
            _make_question("calculus", correct=True, qid="q2"),
            _make_question("topology", correct=True, qid="q3"),
            _make_question("statistics", correct=True, qid="q4"),
        ]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "advancement"
        assert "Excellent" in result.summary
        assert "100%" in result.summary
        assert "mastery" in result.summary.lower()
        assert "algebra" in result.summary

    @pytest.mark.asyncio
    async def test_mixed_summary(self):
        """Mixed summary mentions both strong and weak areas."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()
        mock_session.run.return_value = []
        mock_llm.generate.return_value = "Deep dive."

        questions = [
            _make_question("algebra", correct=True, qid="q0"),
            _make_question("geometry", correct=True, qid="q1"),
            _make_question("calculus", correct=True, qid="q2"),
            _make_question("topology", correct=False, qid="q3"),
            _make_question("statistics", correct=False, qid="q4"),
        ]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "mixed"
        assert "60%" in result.summary
        # Mixed summary mentions both strengths and weaknesses
        assert "doing well" in result.summary.lower() or "well on" in result.summary.lower()
        assert "strengthen" in result.summary.lower()


# ---------------------------------------------------------------------------
# 5. Concept deduplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConceptDeduplication:
    """Ensure duplicate concepts across questions are counted only once."""

    @pytest.mark.asyncio
    async def test_same_weak_concept_multiple_questions(self):
        """A concept appearing in multiple wrong answers should produce one remediation block."""
        svc, *_ = _build_mocks()

        questions = [
            _make_question("algebra", correct=False, qid="q0"),
            _make_question("algebra", correct=False, qid="q1"),
            _make_question("algebra", correct=False, qid="q2"),
            _make_question("geometry", correct=True, qid="q3"),
            _make_question("geometry", correct=True, qid="q4"),
        ]
        # 2 out of 5 correct -> 40% remediation
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "remediation"
        # Only one remediation block for "algebra", not three
        assert len(result.remediation) == 1
        assert result.remediation[0].concept == "algebra"

    @pytest.mark.asyncio
    async def test_same_strong_concept_multiple_questions(self):
        """A concept appearing in multiple correct answers should produce one advancement block."""
        svc, _, _, mock_llm, _, mock_session = _build_mocks()
        mock_session.run.return_value = []
        mock_llm.generate.return_value = "Deep dive."

        questions = [
            _make_question("algebra", correct=True, qid="q0"),
            _make_question("algebra", correct=True, qid="q1"),
            _make_question("algebra", correct=True, qid="q2"),
            _make_question("geometry", correct=True, qid="q3"),
            _make_question("calculus", correct=True, qid="q4"),
        ]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "advancement"
        # Three unique concepts, not five blocks
        concept_names = [b.concept for b in result.advancement]
        assert concept_names == ["algebra", "geometry", "calculus"]

    @pytest.mark.asyncio
    async def test_concept_wrong_then_right_counted_as_weak(self):
        """If a concept is answered wrong first, it is a weak concept;
        a later correct answer for the same concept does not add it to strong."""
        svc, *_ = _build_mocks()

        questions = [
            _make_question("algebra", correct=False, qid="q0"),
            _make_question("algebra", correct=True, qid="q1"),
            _make_question("geometry", correct=False, qid="q2"),
            _make_question("topology", correct=False, qid="q3"),
            _make_question("calculus", correct=False, qid="q4"),
        ]
        # 1 correct out of 5 -> 20% remediation
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "remediation"
        # Algebra should appear as weak (first encounter was wrong)
        remediation_concepts = [b.concept for b in result.remediation]
        assert "algebra" in remediation_concepts
        # Algebra should NOT also be in advancement (empty for remediation path anyway)
        assert result.advancement == []


# ---------------------------------------------------------------------------
# 6. Query error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryErrors:
    """Ensure Neo4j and retriever failures degrade gracefully."""

    @pytest.mark.asyncio
    async def test_neo4j_query_failure_returns_empty_prerequisites(self):
        """When Neo4j raises, _query_prerequisites returns []."""
        svc, mock_neo4j, _, _, _, _ = _build_mocks()

        # Make _get_session raise to simulate connection failure
        mock_neo4j._get_session.return_value.__enter__.side_effect = RuntimeError(
            "Neo4j connection refused"
        )

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        # Should not raise; block should have no prerequisites
        assert result.path_type == "remediation"
        assert len(result.remediation) == 1
        assert result.remediation[0].prerequisites == []

    @pytest.mark.asyncio
    async def test_retriever_failure_returns_empty_reading_materials(self):
        """When retriever.retrieve() raises, reading_materials should be []."""
        svc, _, mock_retriever, _, _, mock_session = _build_mocks()

        mock_session.run.return_value = [{"name": "prereq", "importance": 0.5}]
        mock_retriever.retrieve.side_effect = RuntimeError("OpenSearch cluster down")

        questions = [_make_question("calculus", correct=False)]
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "remediation"
        assert len(result.remediation) == 1
        assert result.remediation[0].reading_materials == []
        # Prerequisites should still be populated despite retriever failure
        assert len(result.remediation[0].prerequisites) == 1

    @pytest.mark.asyncio
    async def test_neo4j_dependents_failure_returns_empty_advanced_topics(self):
        """When _query_dependents fails, advancement block should have no advanced_topics."""
        svc, mock_neo4j, _, mock_llm, _, _ = _build_mocks()

        mock_neo4j._get_session.return_value.__enter__.side_effect = RuntimeError("Neo4j timeout")
        mock_llm.generate.return_value = "Deep dive content."

        questions = _make_questions(5, 5)
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "advancement"
        assert len(result.advancement) >= 1
        assert result.advancement[0].advanced_topics == []

    @pytest.mark.asyncio
    async def test_all_services_fail_still_returns_response(self):
        """Even with all services failing, a valid response with empty blocks is returned."""
        svc, mock_neo4j, mock_retriever, mock_llm, mock_student, _ = _build_mocks()

        mock_neo4j._get_session.return_value.__enter__.side_effect = RuntimeError("Neo4j down")
        mock_retriever.retrieve.side_effect = RuntimeError("OpenSearch down")

        async def llm_fail(**kwargs):
            raise RuntimeError("LLM down")

        mock_llm.generate.side_effect = llm_fail

        # Mixed path: some correct, some incorrect
        questions = _make_questions(3, 5)
        result = await svc.generate_recommendations("topic", questions)

        assert result.path_type == "mixed"
        assert result.score_pct == 60.0
        # All blocks should be present but with empty/None sub-fields
        for block in result.remediation:
            assert block.prerequisites == []
            assert block.reading_materials == []
        for block in result.advancement:
            assert block.advanced_topics == []
            assert block.deep_dive_content is None
        # Summary should still be generated (it's pure string formatting)
        assert len(result.summary) > 0
