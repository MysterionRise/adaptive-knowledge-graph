"""
Counterfactual tests for the learner-state decision (#210).

The code takes one decision from learner state. ``StudentProfile.get_target_difficulty``
(``backend/app/student/models.py``) maps the mastery level stored for the asked concept to a
band, and ``POST /api/v1/quiz/generate-adaptive`` puts that band's instruction text into the
quiz prompt. The rule as coded: mastery < 0.4 is "easy", mastery <= 0.7 is "medium" and
anything above is "hard".

Each test compares learner states that differ in one field. The tables list what must change
the band and what must not. ``BAND_CHANGES``, ``BAND_BOUNDARIES``, ``UNSEEN_CONCEPT_BANDS``,
``INVARIANTS``, ``ROUTE_BANDS``, ``ROUTE_ROUNDING_PAIRS`` and ``REQUEST_INVARIANTS`` hold the
same rows as parametrised cases.

Expected changes (x - e and x + e are the nearest floats below and above x):

| Field that differs, nothing else            | Values                | Band of each value   |
| ------------------------------------------- | --------------------- | -------------------- |
| ``mastery_level`` of the asked concept      | 0.39, 0.41            | easy, medium         |
| ``mastery_level`` of the asked concept      | 0.70, 0.71            | medium, hard         |
| ``mastery_level`` of the asked concept      | 0.4 - e, 0.4, 0.4 + e | easy, medium, medium |
| ``mastery_level`` of the asked concept      | 0.7 - e, 0.7, 0.7 + e | medium, medium, hard |
| ``mastery_level`` of the asked concept      | 0.0, 1.0              | easy, hard           |
| ``STUDENT_INITIAL_MASTERY``, concept unseen | 0.3, 0.5, 0.8         | easy, medium, hard   |
| ``STUDENT_INITIAL_MASTERY``, concept unseen | 0.4, 0.7              | medium, medium       |

Invariants (the band is the same before and after, at mastery levels in all three bands):

| Field that differs, nothing else                                                |
| ------------------------------------------------------------------------------- |
| ``attempts``, ``correct_attempts``, ``last_assessed`` of the asked concept      |
| ``bkt_p_known``, ``bkt_p_transit``, ``bkt_p_slip``, ``bkt_p_guess`` of the same |
| ``concept_name`` inside the record (the key of ``mastery_map`` decides)         |
| another concept's ``mastery_level``; another concept added; another one removed |
| ``overall_ability``, ``student_id``, ``created_at``, ``updated_at``             |
| at the route: another learner's stored profile; ``num_questions``; ``subject``  |

Today's behaviour, expected to become an invariant with #108: the spelling of the concept.
``mastery_map`` is keyed by the exact string, so another casing or a leading "The" is an
unseen concept and gets the band of ``STUDENT_INITIAL_MASTERY``. Two plain tests pin it, one
on ``StudentProfile`` and one on the adaptive route. The route pin flips wherever #108 maps
topics to concepts; the profile pin flips only if #108 changes the lookup in the model.

At the route the same rule holds for the stored mastery (``ROUTE_BANDS``). The response
reports the mastery rounded to three places and the band comes from the stored value, so a
stored 0.4 - e is reported as 0.4 with the band "easy" and a stored 0.4 as 0.4 with "medium"
(``ROUTE_ROUNDING_PAIRS``).

The profile tests use in-memory models only. The route tests use a real ``StudentService`` on
a ``tmp_path`` SQLite file and a real ``QuizGenerator`` whose LLM and retriever are stubs.
They check what the LLM is asked for, not what a model would return: nothing in the code
checks the difficulty of the questions that come back.
"""

import json
import math
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.settings import settings
from backend.app.student.models import ConceptMastery, StudentProfile
from backend.app.student.quiz_generator import QuizGenerator
from backend.app.student.student_service import StudentService
from backend.app.ui_payloads.constraints import DEFAULT_STUDENT_ID

pytestmark = pytest.mark.unit

Band = Literal["easy", "medium", "hard"]
FieldPath = tuple[str, ...]

CONCEPT = "Civil War"
OTHER_CONCEPT = "Reconstruction"
LEARNER = "learner_210"

# Mastery levels the invariants are tried at: all three bands, both sides of each boundary.
MASTERY_LEVELS: dict[float, Band] = {
    0.2: "easy",
    0.39: "easy",
    0.4: "medium",
    0.55: "medium",
    0.7: "medium",
    0.71: "hard",
    0.9: "hard",
}

# (one mastery level, the other, band of the first, band of the second)
BAND_CHANGES: list[tuple[float, float, Band, Band]] = [
    (0.39, 0.41, "easy", "medium"),
    (0.70, 0.71, "medium", "hard"),
    (math.nextafter(0.4, 0.0), 0.4, "easy", "medium"),
    (0.7, math.nextafter(0.7, 1.0), "medium", "hard"),
]

# The boundaries exactly as coded, with the nearest floats on either side.
BAND_BOUNDARIES: list[tuple[float, Band]] = [
    (0.0, "easy"),
    (math.nextafter(0.4, 0.0), "easy"),
    (0.4, "medium"),
    (math.nextafter(0.4, 1.0), "medium"),
    (math.nextafter(0.7, 0.0), "medium"),
    (0.7, "medium"),
    (math.nextafter(0.7, 1.0), "hard"),
    (1.0, "hard"),
]

# (STUDENT_INITIAL_MASTERY, band of a concept without history), both boundaries included
UNSEEN_CONCEPT_BANDS: list[tuple[float, Band]] = [
    (0.3, "easy"),
    (0.4, "medium"),
    (0.5, "medium"),
    (0.7, "medium"),
    (0.8, "hard"),
]

_RECORD: FieldPath = ("mastery_map", CONCEPT)
_OTHER_RECORD: FieldPath = ("mastery_map", OTHER_CONCEPT)
_NEW_RECORD = {"concept_name": "Gilded Age", "mastery_level": 0.95, "attempts": 9}

# (field, other values to try). Every value differs from the one in ``_profile``. A path that
# ends at a concept is a whole record: a dict adds it and None removes it.
INVARIANTS: list[tuple[FieldPath, tuple[Any, ...]]] = [
    ((*_RECORD, "attempts"), (0, 1, 3, 1000)),
    ((*_RECORD, "correct_attempts"), (0, 1, 5)),
    ((*_RECORD, "last_assessed"), (None, datetime(2020, 1, 1), datetime(2031, 6, 1, 12, 0))),
    ((*_RECORD, "bkt_p_known"), (None, 0.01, 0.5, 0.99)),
    ((*_RECORD, "bkt_p_transit"), (0.0, 0.5, 1.0)),
    ((*_RECORD, "bkt_p_slip"), (0.0, 0.49, 1.0)),
    ((*_RECORD, "bkt_p_guess"), (0.0, 0.49, 1.0)),
    ((*_RECORD, "concept_name"), ("civil war", "Reconstruction")),
    ((*_OTHER_RECORD, "mastery_level"), (0.0, 0.39, 0.41, 0.71, 1.0)),
    (("mastery_map", "Gilded Age"), (_NEW_RECORD,)),
    (_OTHER_RECORD, (None,)),
    (("overall_ability",), (0.0, 0.39, 0.41, 0.71, 1.0)),
    (("student_id",), ("another_learner",)),
    (("created_at",), (datetime(2020, 1, 1),)),
    (("updated_at",), (datetime(2031, 6, 1, 12, 0),)),
]

# Model fields without a row in INVARIANTS, and why.
_NOT_AN_INVARIANT = {
    "ConceptMastery.mastery_level": "the field the band reads (BAND_CHANGES, BAND_BOUNDARIES)",
    "StudentProfile.mastery_map": "the container; its records and their fields have rows",
}


def _field_id(path: FieldPath) -> str:
    return ".".join(path)


def _profile(mastery: float) -> StudentProfile:
    """A learner with history on CONCEPT at the given mastery and on one other concept."""
    assessed = datetime(2026, 11, 1, 9, 30)
    return StudentProfile(
        student_id=LEARNER,
        mastery_map={
            CONCEPT: ConceptMastery(
                concept_name=CONCEPT,
                mastery_level=mastery,
                attempts=5,
                correct_attempts=2,
                last_assessed=assessed,
                bkt_p_known=mastery,
            ),
            OTHER_CONCEPT: ConceptMastery(
                concept_name=OTHER_CONCEPT, mastery_level=0.55, attempts=2, correct_attempts=1
            ),
        },
        overall_ability=0.3,
        created_at=datetime(2026, 10, 1, 8, 0),
        updated_at=assessed,
    )


def _changed(profile: StudentProfile, path: FieldPath, value: Any) -> StudentProfile:
    """A copy of the profile with one field set to ``value`` (None removes a whole record)."""
    state = profile.model_dump()
    parent = state
    for key in path[:-1]:
        parent = parent[key]
    if value is None and path[:-1] == ("mastery_map",):
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return StudentProfile.model_validate(state)


def _flatten(value: Any, prefix: FieldPath = ()) -> dict[FieldPath, Any]:
    if isinstance(value, dict):
        flat: dict[FieldPath, Any] = {}
        for key, item in value.items():
            flat.update(_flatten(item, (*prefix, key)))
        return flat
    return {prefix: value}


def _differing_fields(before: StudentProfile, after: StudentProfile) -> set[FieldPath]:
    """Paths of the leaf fields whose values differ between two profiles."""
    missing = object()
    a, b = _flatten(before.model_dump()), _flatten(after.model_dump())
    return {path for path in a.keys() | b.keys() if a.get(path, missing) != b.get(path, missing)}


# ---------------------------------------------------------------------------
# What changes the band: the mastery level of the asked concept
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("before", "after", "band_before", "band_after"), BAND_CHANGES)
def test_band_changes_when_only_the_mastery_level_crosses_a_boundary(
    before, after, band_before, band_after
):
    first = _profile(before)
    second = _changed(first, (*_RECORD, "mastery_level"), after)

    assert _differing_fields(first, second) == {(*_RECORD, "mastery_level")}
    assert first.get_target_difficulty(CONCEPT) == band_before
    assert second.get_target_difficulty(CONCEPT) == band_after


@pytest.mark.parametrize(("mastery", "band"), BAND_BOUNDARIES)
def test_band_boundaries_are_as_coded(mastery, band):
    """mastery < 0.4 is easy, mastery <= 0.7 is medium, anything above is hard."""
    assert _profile(mastery).get_target_difficulty(CONCEPT) == band


def test_band_switches_exactly_twice_between_0_and_1():
    """Over the mastery levels k/1000 the bands are 400 easy, then 301 medium, then 300 hard."""
    bands = [_profile(k / 1000).get_target_difficulty(CONCEPT) for k in range(1001)]

    assert bands == ["easy"] * 400 + ["medium"] * 301 + ["hard"] * 300


# ---------------------------------------------------------------------------
# What does not change the band: every other field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "values"), INVARIANTS, ids=[_field_id(path) for path, _ in INVARIANTS]
)
def test_band_ignores_every_field_but_the_mastery_level(path, values):
    for mastery, band in MASTERY_LEVELS.items():
        base = _profile(mastery)
        for value in values:
            changed = _changed(base, path, value)
            differing = _differing_fields(base, changed)

            assert differing, f"{_field_id(path)}={value!r} is the base value"
            assert all(field[: len(path)] == path for field in differing), differing
            assert base.get_target_difficulty(CONCEPT) == band
            assert changed.get_target_difficulty(CONCEPT) == band, (
                f"mastery {mastery}: {_field_id(path)}={value!r} changed the band"
            )


def test_every_model_field_is_a_change_or_an_invariant():
    """A field added to the learner models needs a row in the tables before this passes."""
    covered = {f"ConceptMastery.{path[2]}" for path, _ in INVARIANTS if path[:2] == _RECORD}
    covered |= {f"StudentProfile.{path[0]}" for path, _ in INVARIANTS if len(path) == 1}
    fields = {f"ConceptMastery.{name}" for name in ConceptMastery.model_fields}
    fields |= {f"StudentProfile.{name}" for name in StudentProfile.model_fields}
    listed = covered | set(_NOT_AN_INVARIANT)

    assert not fields - listed, "say in the tables whether these fields change the band"
    assert not listed - fields, "the tables name fields the models no longer have"
    assert not covered & set(_NOT_AN_INVARIANT)


# ---------------------------------------------------------------------------
# A concept without history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("initial_mastery", "band"), UNSEEN_CONCEPT_BANDS)
def test_unseen_concept_gets_the_band_of_the_initial_mastery(monkeypatch, initial_mastery, band):
    monkeypatch.setattr(settings, "student_initial_mastery", initial_mastery)
    fresh = StudentProfile(student_id=LEARNER)

    assert fresh.get_mastery("Unseen Concept") == initial_mastery
    assert fresh.get_target_difficulty("Unseen Concept") == band
    # History on other concepts and the overall ability do not move it.
    for mastery in MASTERY_LEVELS:
        for overall in (0.0, 1.0):
            tracked = _changed(_profile(mastery), ("overall_ability",), overall)
            assert tracked.get_mastery("Unseen Concept") == initial_mastery
            assert tracked.get_target_difficulty("Unseen Concept") == band


# Spellings that #210 expects to mean CONCEPT once #108 maps quiz topics to graph concepts.
OTHER_SPELLINGS = ("civil war", "CIVIL WAR", "The Civil War", "the civil war")


def test_concept_spelling_is_a_separate_key_today_and_flips_when_108_lands(monkeypatch):
    """Documents today's behaviour; not a statement of what should happen.

    ``mastery_map`` is keyed by the exact concept string, so another casing or a leading
    "The" is an unseen concept: it gets the band of ``STUDENT_INITIAL_MASTERY``, not the band
    stored for "Civil War". The concept validator already treats these spellings as one
    concept (``kg_concept_exists``). #210 expects the band to ignore the spelling once #108
    maps quiz topics to graph concepts. If #108 changes the lookup in ``StudentProfile``, this
    test fails and its expectations flip: every spelling then returns the stored mastery and
    band. If #108 resolves the topic before it reaches the model, this test stays green and
    the pin that flips is the route test further down
    (``test_topic_spelling_is_a_separate_key_at_the_route_today_and_flips_when_108_lands``).
    """
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    profile = _profile(0.9)

    assert profile.get_target_difficulty(CONCEPT) == "hard"
    for spelling in OTHER_SPELLINGS:
        assert profile.get_mastery(spelling) == 0.3, spelling
        assert profile.get_target_difficulty(spelling) == "easy", spelling


# ---------------------------------------------------------------------------
# The adaptive route: the band's instruction text reaches the prompt
# ---------------------------------------------------------------------------

# The instruction text of each band, line by line (``QuizGenerator._build_system_prompt`` and
# ``_build_user_prompt``). The shared part of the system prompt names all three bands in
# lower case and capitalised, never in upper case.
SYSTEM_PROMPT_TEXT: dict[Band, tuple[str, ...]] = {
    "easy": (
        "Generate ONLY EASY questions with difficulty_score between 0.1 and 0.3",
        "Test direct recall of facts stated in the text",
        "Have one clearly correct answer that is explicitly stated",
        "Avoid requiring inference or connecting multiple concepts",
        "Use simple, straightforward language",
    ),
    "medium": (
        "Generate ONLY MEDIUM difficulty questions with difficulty_score between 0.35 and 0.6",
        "Require understanding and application of concepts",
        "May need connecting two related facts from the text",
        "Test comprehension, not just memorization",
        "Have plausible distractors but a clear correct answer",
    ),
    "hard": (
        "Generate ONLY HARD questions with difficulty_score between 0.65 and 0.9",
        "Require synthesis or analysis of multiple concepts",
        "Test application to new scenarios or deeper understanding",
        "May require making inferences beyond what's explicitly stated",
        "Have sophisticated distractors that require careful analysis",
    ),
}
USER_PROMPT_TEXT: dict[Band, tuple[str, ...]] = {
    "easy": (
        "at the EASY difficulty level",
        "ALL questions must be EASY difficulty",
        "appropriate for easy level",
    ),
    "medium": (
        "at the MEDIUM difficulty level",
        "ALL questions must be MEDIUM difficulty",
        "appropriate for medium level",
    ),
    "hard": (
        "at the HARD difficulty level",
        "ALL questions must be HARD difficulty",
        "appropriate for hard level",
    ),
}

# (stored mastery of the asked topic, band in the response and in the prompt)
ROUTE_BANDS: list[tuple[float, Band]] = [
    (0.39, "easy"),
    (0.4, "medium"),
    (0.41, "medium"),
    (0.70, "medium"),
    (0.71, "hard"),
]

# (stored mastery below the boundary, stored mastery above it, the mastery the response
# reports for both, band of the first, band of the second)
ROUTE_ROUNDING_PAIRS: list[tuple[float, float, float, Band, Band]] = [
    (math.nextafter(0.4, 0.0), 0.4, 0.4, "easy", "medium"),
    (0.7, math.nextafter(0.7, 1.0), 0.7, "medium", "hard"),
]

# (query parameter of the adaptive request, value) that does not change the band. The learner
# store is not keyed by subject today, so a topic asked under another subject reads the same
# mastery.
REQUEST_INVARIANTS: list[tuple[str, Any]] = [
    ("num_questions", 1),
    ("num_questions", 7),
    ("subject", "economics"),
]

PASSAGE = "Fort Sumter fell in April 1861, and four more states left the Union."

# The stub returns this reply whatever band was asked for; the tests read the prompts only.
LLM_REPLY = json.dumps(
    {
        "questions": [
            {
                "text": "When did Fort Sumter fall?",
                "options": [
                    {"id": "a", "text": "April 1861"},
                    {"id": "b", "text": "July 1863"},
                    {"id": "c", "text": "April 1865"},
                    {"id": "d", "text": "December 1860"},
                ],
                "correct_option_id": "a",
                "explanation": "The passage dates the fall of Fort Sumter to April 1861.",
                "difficulty": "medium",
                "difficulty_score": 0.5,
            }
        ]
    }
)


@pytest.fixture
def learner_store(tmp_path) -> Iterator[StudentService]:
    """A real StudentService on a temporary SQLite file, served to the quiz routes."""
    service = StudentService(storage_path=tmp_path / "profiles.sqlite3")
    with patch("backend.app.api.routes.quiz.get_student_service", return_value=service):
        yield service


@pytest.fixture
def quiz_llm() -> Iterator[AsyncMock]:
    """The LLM stub of a real QuizGenerator that the quiz routes use; the retriever is a stub."""
    with (
        patch("backend.app.student.quiz_generator.get_llm_client") as get_llm_client,
        patch("backend.app.student.quiz_generator.get_retriever") as get_retriever,
    ):
        llm = AsyncMock()
        llm.generate.return_value = LLM_REPLY
        get_llm_client.return_value = llm
        retriever = MagicMock()
        retriever.retrieve.return_value = [{"id": "chunk_1", "text": PASSAGE}]
        get_retriever.return_value = retriever
        generator = QuizGenerator(subject_id="us_history")

    with patch("backend.app.api.routes.quiz.get_quiz_generator", return_value=generator):
        yield llm


def _bands_asked_for(prompt: str, band_text: dict[Band, tuple[str, ...]]) -> set[Band]:
    """The bands whose instruction text, or upper-case name, appears in the prompt."""
    return {
        band
        for band, texts in band_text.items()
        if band.upper() in prompt or any(text in prompt for text in texts)
    }


def _stored_row_count(service: StudentService) -> int:
    with sqlite3.connect(service.storage_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0]


def _adaptive_prompts(client, llm: AsyncMock, **params: Any) -> tuple[dict, str, str]:
    """Request an adaptive quiz; returns the response body and the prompts the LLM stub got.

    The request asks for CONCEPT as LEARNER; ``params`` add or replace query parameters.
    """
    llm.generate.reset_mock()
    response = client.post(
        "/api/v1/quiz/generate-adaptive",
        params={"topic": CONCEPT, "student_id": LEARNER, **params},
    )

    assert response.status_code == 200, response.text
    llm.generate.assert_awaited_once()
    prompts = llm.generate.await_args.kwargs
    return response.json(), prompts["system_prompt"], prompts["prompt"]


def _assert_prompts_ask_for(band: Band, system_prompt: str, user_prompt: str) -> None:
    """Every line of the band's instruction text is in the prompts, and no other band's."""
    for text in SYSTEM_PROMPT_TEXT[band]:
        assert text in system_prompt, text
    for text in USER_PROMPT_TEXT[band]:
        assert text in user_prompt, text
    assert _bands_asked_for(system_prompt, SYSTEM_PROMPT_TEXT) == {band}
    assert _bands_asked_for(user_prompt, USER_PROMPT_TEXT) == {band}


@pytest.mark.parametrize(("mastery", "band"), ROUTE_BANDS)
def test_adaptive_prompt_has_the_target_band_text_and_no_other(
    client, learner_store, quiz_llm, mastery, band
):
    learner_store.save_profile(_profile(mastery))

    body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm)

    assert body["target_difficulty"] == band
    assert body["student_mastery"] == mastery
    _assert_prompts_ask_for(band, system_prompt, user_prompt)
    assert PASSAGE in user_prompt


@pytest.mark.parametrize(
    ("below", "above", "reported", "band_below", "band_above"), ROUTE_ROUNDING_PAIRS
)
def test_adaptive_route_takes_the_band_from_the_stored_mastery_not_the_reported_one(
    client, learner_store, quiz_llm, below, above, reported, band_below, band_above
):
    """Two stored values one float apart are reported as the same number with different bands.

    ``StudentService.get_target_difficulty`` rounds the mastery it reports to three places
    and takes the band from the stored value. A client that applies the band rule to the
    reported number gets "medium" for a stored 0.4 - e, where the prompt asks for "easy".
    """
    first = _profile(below)
    second = _changed(first, (*_RECORD, "mastery_level"), above)
    assert _differing_fields(first, second) == {(*_RECORD, "mastery_level")}

    learner_store.save_profile(first)
    body_below, system_prompt_below, user_prompt_below = _adaptive_prompts(client, quiz_llm)
    learner_store.save_profile(second)
    body_above, system_prompt_above, user_prompt_above = _adaptive_prompts(client, quiz_llm)

    assert body_below["student_mastery"] == body_above["student_mastery"] == reported
    assert body_below["target_difficulty"] == band_below
    assert body_above["target_difficulty"] == band_above
    _assert_prompts_ask_for(band_below, system_prompt_below, user_prompt_below)
    _assert_prompts_ask_for(band_above, system_prompt_above, user_prompt_above)


@pytest.mark.parametrize(("initial_mastery", "band"), UNSEEN_CONCEPT_BANDS)
def test_adaptive_prompt_for_an_unseen_topic_follows_the_initial_mastery(
    client, learner_store, quiz_llm, monkeypatch, initial_mastery, band
):
    monkeypatch.setattr(settings, "student_initial_mastery", initial_mastery)

    body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm)

    assert body["target_difficulty"] == band
    assert body["student_mastery"] == initial_mastery
    _assert_prompts_ask_for(band, system_prompt, user_prompt)


def test_topic_spelling_is_a_separate_key_at_the_route_today_and_flips_when_108_lands(
    client, learner_store, quiz_llm, monkeypatch
):
    """Documents today's behaviour at the route; not a statement of what should happen.

    The route trims the topic and passes it on as the mastery key. With "Civil War" stored at
    0.9, the topic " Civil War " gets the stored band, and another casing or a leading "The"
    is an unseen concept: the prompt asks for the band of ``STUDENT_INITIAL_MASTERY``. #210
    expects the band to ignore the spelling once #108 maps quiz topics to graph concepts.
    Wherever that mapping lands (route, service or model), this test fails and its
    expectations flip: every spelling then gets the stored mastery, band and prompt.
    """
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    learner_store.save_profile(_profile(0.9))

    for topic in (CONCEPT, f" {CONCEPT} "):
        body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm, topic=topic)

        assert body["student_mastery"] == 0.9, topic
        assert body["target_difficulty"] == "hard", topic
        _assert_prompts_ask_for("hard", system_prompt, user_prompt)

    for topic in OTHER_SPELLINGS:
        body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm, topic=topic)

        assert body["student_mastery"] == 0.3, topic
        assert body["target_difficulty"] == "easy", topic
        _assert_prompts_ask_for("easy", system_prompt, user_prompt)


def test_adaptive_prompt_is_unchanged_when_only_an_invariant_field_changes(
    client, learner_store, quiz_llm
):
    """The stored profile changes in one field at a time; both prompts stay the same."""
    base = _profile(0.55)
    learner_store.save_profile(base)
    _, base_system_prompt, base_user_prompt = _adaptive_prompts(client, quiz_llm)
    assert _bands_asked_for(base_system_prompt, SYSTEM_PROMPT_TEXT) == {"medium"}

    for path, values in INVARIANTS:
        changed = _changed(base, path, values[-1])
        learner_store.save_profile(changed)  # replaces the stored profile of that student_id

        _, system_prompt, user_prompt = _adaptive_prompts(
            client, quiz_llm, student_id=changed.student_id
        )

        assert system_prompt == base_system_prompt, _field_id(path)
        assert user_prompt == base_user_prompt, _field_id(path)

    # Control: the same comparison does see a change of band.
    learner_store.save_profile(_changed(base, (*_RECORD, "mastery_level"), 0.71))
    _, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm)
    assert system_prompt != base_system_prompt
    assert user_prompt != base_user_prompt


def test_adaptive_prompt_ignores_another_learners_mastery(client, learner_store, quiz_llm):
    """A second stored learner, in another band on the same topic, changes nothing."""
    learner_store.save_profile(_profile(0.55))
    _, base_system_prompt, base_user_prompt = _adaptive_prompts(client, quiz_llm)

    for mastery in (0.2, 0.9):
        other = _changed(_profile(mastery), ("student_id",), "another_learner")
        learner_store.save_profile(other)

        body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm)

        assert body["target_difficulty"] == "medium"
        assert system_prompt == base_system_prompt
        assert user_prompt == base_user_prompt

    # Control: the other learner is stored and gets the band of their own mastery.
    assert _stored_row_count(learner_store) == 2
    body, system_prompt, user_prompt = _adaptive_prompts(
        client, quiz_llm, student_id="another_learner"
    )
    assert body["target_difficulty"] == "hard"
    _assert_prompts_ask_for("hard", system_prompt, user_prompt)


@pytest.mark.parametrize(("parameter", "value"), REQUEST_INVARIANTS)
def test_adaptive_band_ignores_the_rest_of_the_request(
    client, learner_store, quiz_llm, parameter, value
):
    """The band follows the learner and the topic, not ``num_questions`` or ``subject``."""
    for mastery, band in ((0.39, "easy"), (0.70, "medium"), (0.71, "hard")):
        learner_store.save_profile(_profile(mastery))
        _, base_system_prompt, _ = _adaptive_prompts(client, quiz_llm)

        body, system_prompt, user_prompt = _adaptive_prompts(client, quiz_llm, **{parameter: value})

        assert body["target_difficulty"] == band
        assert body["student_mastery"] == mastery
        assert system_prompt == base_system_prompt
        _assert_prompts_ask_for(band, system_prompt, user_prompt)


def test_adaptive_request_reads_the_learner_store_and_writes_nothing(
    client, learner_store, quiz_llm
):
    """Asking for a band is a read: no row for a new learner, no change to a stored one."""
    _adaptive_prompts(client, quiz_llm)

    assert _stored_row_count(learner_store) == 0

    stored = _profile(0.55)
    learner_store.save_profile(stored)
    _adaptive_prompts(client, quiz_llm)
    _adaptive_prompts(client, quiz_llm, topic="Unseen Concept")

    assert _stored_row_count(learner_store) == 1
    assert learner_store.get_profile(LEARNER) == stored


def test_non_adaptive_prompt_has_no_band_text(client, learner_store, quiz_llm):
    """Control: ``/quiz/generate`` takes no learner and asks for mixed difficulty.

    A hard-band profile stored for the default learner does not put band text in its prompt.
    """
    learner_store.save_profile(_changed(_profile(0.9), ("student_id",), DEFAULT_STUDENT_ID))

    response = client.post("/api/v1/quiz/generate", params={"topic": CONCEPT})

    assert response.status_code == 200, response.text
    prompts = quiz_llm.generate.await_args.kwargs
    assert _bands_asked_for(prompts["system_prompt"], SYSTEM_PROMPT_TEXT) == set()
    assert _bands_asked_for(prompts["prompt"], USER_PROMPT_TEXT) == set()
    assert "varying difficulty" in prompts["prompt"]

    # Control: the adaptive route does read that learner, and asks for the hard band.
    body, system_prompt, user_prompt = _adaptive_prompts(
        client, quiz_llm, student_id=DEFAULT_STUDENT_ID
    )
    assert body["target_difficulty"] == "hard"
    _assert_prompts_ask_for("hard", system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# The answer route: the mastery level the band reads is stored with a floor of 0.1
# ---------------------------------------------------------------------------


def test_answer_route_stores_the_mastery_floor_and_the_p_known_clamp(
    client, learner_store, monkeypatch
):
    """Property (e) of ``test_student_bkt_properties.py`` on the public path.

    A stored record with transit 0 and p_known 0.05 gets a wrong answer through
    ``POST /student/mastery``: p_known falls to its 0.01 clamp, the mastery level stops at
    the 0.1 floor, and both are persisted. The test is in this module because it needs the
    learner store; the property module uses no database.
    """
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    profile = _profile(0.2)
    profile = _changed(profile, (*_RECORD, "bkt_p_known"), 0.05)
    profile = _changed(profile, (*_RECORD, "bkt_p_transit"), 0.0)
    learner_store.save_profile(profile)

    response = client.post(
        "/api/v1/student/mastery",
        params={"student_id": LEARNER},
        json={"concept": CONCEPT, "correct": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_mastery"] == 0.2
    assert body["bkt_p_known"] == 0.01
    assert body["new_mastery"] == 0.1
    assert body["target_difficulty"] == "easy"
    stored = learner_store.get_profile(LEARNER).mastery_map[CONCEPT]
    assert stored.bkt_p_known == 0.01
    assert stored.mastery_level == 0.1
    assert stored.attempts == 6
