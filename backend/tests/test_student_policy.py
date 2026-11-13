"""
Tests for the policy interface, decision records and the band rule as ``band-v1`` (#306).

``backend/app/student/policy/`` holds the interface (``base.py``), the band rule (``band.py``)
and the registry (``registry.py``). ``StudentProfile.get_target_difficulty`` is a shim over
``band-v1``; ``test_student_counterfactual.py`` (#210) pins the bands it returns, and this
module pins the record behind them.

What ``band-v1`` declares, and what the tests hold it to:

| Input                                                    | Declared | Where it shows in the record    |
| -------------------------------------------------------- | -------- | ------------------------------- |
| ``context.concept``                                      | yes      | ``context_used.concept``        |
| mastery level of that concept, if it has history         | yes      | ``state_used.mastery``, tracked |
| the initial mastery, if it has none                      | yes      | ``state_used.mastery``, initial |
| every other field of the profile (``UNDECLARED``)        | no       | nowhere                         |
| every other context field (``UNDECLARED_CONTEXT``)       | no       | nowhere                         |
| the time of the decision                                 | no       | nowhere; it is ``decided_at``   |

A declared input that changes must change the record; an undeclared one must change neither
the action nor the record. ``UNDECLARED`` has a row for every field of ``ConceptMastery`` and
``StudentProfile`` except the mastery level and its container, and
``UNDECLARED_CONTEXT`` one for every field of ``DecisionContext`` except the concept; two
tests fail when a field is added without a row.

Two records are equal exactly when their canonical JSON is equal, so equal records have equal
ids: 1, 1.0 and True make three records, and -0.0 is stored as 0.0.

The profile tests use in-memory models. The service tests use a real ``StudentService`` on a
``tmp_path`` SQLite file with a fixed clock. The routes are covered in ``test_api_quiz.py``.
"""

import ast
import copy
import hashlib
import inspect
import json
import math
import os
import pickle
import random
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.core.settings import settings
from backend.app.student.models import DIFFICULTY_POLICY, ConceptMastery, StudentProfile
from backend.app.student.policy import (
    BAND_V1,
    EASY_BELOW,
    MEDIUM_UP_TO,
    BandPolicyV1,
    DecisionContext,
    DecisionRecord,
    EdgeUse,
    LearnerState,
    Policy,
    band_for,
    difficulty_of,
    get_policy,
    policy_key,
    registered_policies,
)
from backend.app.student.student_service import StudentService
from backend.app.ui_payloads.decisions import DecisionRecordPayload

pytestmark = pytest.mark.unit

FieldPath = tuple[str, ...]

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = REPO_ROOT / "backend" / "app" / "student" / "policy"
POLICY_MODULES = sorted(path.name for path in POLICY_DIR.glob("*.py"))

CONCEPT = "Civil War"
OTHER_CONCEPT = "Reconstruction"
LEARNER = "learner_306"
DECIDED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

# Other spellings of CONCEPT: a step that trims or re-cases the concept would change each of
# them. The exact string is the lookup key, so none of them has history in ``_profile``.
OTHER_SPELLINGS = ["civil war", "CIVIL WAR", " Civil War ", "The Civil War", "Civil  War"]

# Mastery levels in all three bands, on both sides of each boundary.
MASTERY_LEVELS = {
    0.2: "easy",
    0.39: "easy",
    0.4: "medium",
    0.55: "medium",
    0.7: "medium",
    0.71: "hard",
    0.9: "hard",
}

# The boundaries with the nearest floats on either side.
BOUNDARIES = [
    (0.0, "easy"),
    (math.nextafter(0.4, 0.0), "easy"),
    (0.4, "medium"),
    (math.nextafter(0.4, 1.0), "medium"),
    (math.nextafter(0.7, 0.0), "medium"),
    (0.7, "medium"),
    (math.nextafter(0.7, 1.0), "hard"),
    (1.0, "hard"),
]

# (STUDENT_INITIAL_MASTERY, band of a concept without history)
INITIAL_MASTERY_BANDS = [
    (0.0, "easy"),
    (0.3, "easy"),
    (math.nextafter(0.4, 0.0), "easy"),
    (0.4, "medium"),
    (0.5, "medium"),
    (0.7, "medium"),
    (math.nextafter(0.7, 1.0), "hard"),
    (0.8, "hard"),
    (1.0, "hard"),
]

_RECORD: FieldPath = ("mastery_map", CONCEPT)
_OTHER_RECORD: FieldPath = ("mastery_map", OTHER_CONCEPT)

# (profile field, another value): inputs band-v1 does not declare. A path that ends at a
# concept is a whole record: a dict adds it and None removes it.
UNDECLARED: list[tuple[FieldPath, Any]] = [
    ((*_RECORD, "attempts"), 1000),
    ((*_RECORD, "correct_attempts"), 0),
    ((*_RECORD, "last_assessed"), None),
    ((*_RECORD, "last_assessed"), datetime(2031, 6, 1, 12, 0)),
    ((*_RECORD, "bkt_p_known"), 0.99),
    ((*_RECORD, "bkt_p_transit"), 0.5),
    ((*_RECORD, "bkt_p_slip"), 0.49),
    ((*_RECORD, "bkt_p_guess"), 0.49),
    ((*_RECORD, "concept_name"), OTHER_CONCEPT),
    ((*_OTHER_RECORD, "mastery_level"), 0.95),
    ((*_OTHER_RECORD, "attempts"), 77),
    (("mastery_map", "Gilded Age"), {"concept_name": "Gilded Age", "mastery_level": 0.95}),
    (_OTHER_RECORD, None),
    (("overall_ability",), 1.0),
    (("student_id",), "another_learner"),
    (("created_at",), datetime(2020, 1, 1)),
    (("updated_at",), datetime(2031, 6, 1, 12, 0)),
]

# The model fields band-v1 declares, and how: they have no row in UNDECLARED.
_DECLARED = {
    "ConceptMastery.mastery_level": "state_used.mastery of a concept with history",
    "StudentProfile.mastery_map": "the container; its records and their fields have rows",
}

# Context fields band-v1 does not declare, each with a value other than the default.
UNDECLARED_CONTEXT: dict[str, Any] = {
    "candidates": (OTHER_CONCEPT, "Gilded Age"),
    "edges": (EdgeUse(OTHER_CONCEPT, CONCEPT, "PREREQ", "test"),),
    "step": 7,
    "now": datetime(2031, 6, 1, 12, 0, tzinfo=UTC),
    "seed": 306,
}

RECORD_FIELDS = [
    "policy_id",
    "policy_version",
    "action",
    "state_used",
    "context_used",
    "edges_used",
]
MAPPING_FIELDS = ["action", "state_used", "context_used"]

EDGE = EdgeUse(source="Secession", target=CONCEPT, relation="PREREQ", provenance="curated:t@v1")


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


def _legacy_band(mastery: float) -> str:
    """The rule as ``StudentProfile.get_target_difficulty`` coded it before #306."""
    if mastery < 0.4:
        return "easy"
    elif mastery <= 0.7:
        return "medium"
    else:
        return "hard"


def _band_record(difficulty: str, mastery: float, source: str, concept: str) -> DecisionRecord:
    """The record band-v1 is expected to return, written out field by field."""
    return DecisionRecord(
        policy_id="band",
        policy_version="v1",
        action={"kind": "difficulty", "difficulty": difficulty},
        state_used={"mastery": mastery, "mastery_source": source},
        context_used={"concept": concept},
        edges_used=(),
    )


@pytest.fixture
def service(tmp_path) -> StudentService:
    """A real StudentService on a temporary SQLite file; its clock always says DECIDED_AT."""
    return StudentService(storage_path=tmp_path / "profiles.sqlite3", clock=lambda: DECIDED_AT)


# ---------------------------------------------------------------------------
# Identity and registry
# ---------------------------------------------------------------------------


def test_band_v1_identity_and_registry():
    assert BAND_V1.id == "band"
    assert BAND_V1.version == "v1"
    assert policy_key(BAND_V1) == "band-v1"
    assert isinstance(BAND_V1, Policy)
    assert not isinstance(object(), Policy)

    assert registered_policies() == ("band-v1",)
    assert get_policy("band-v1") is BAND_V1
    assert get_policy("band-v1") is get_policy("band-v1")
    assert DIFFICULTY_POLICY == "band-v1"

    # A record leads back to the policy that made it.
    record = _profile(0.2).decide_difficulty(CONCEPT)
    assert get_policy(f"{record.policy_id}-{record.policy_version}") is BAND_V1


def test_an_object_without_one_of_the_three_members_is_not_a_policy():
    class NoDecide:
        id = "band"
        version = "v1"

    class NoVersion:
        id = "band"

        def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
            raise NotImplementedError

    assert not isinstance(NoDecide(), Policy)
    assert not isinstance(NoVersion(), Policy)


@pytest.mark.parametrize("key", ["band", "v1", "band-v2", "BAND-V1", "band_v1", ""])
def test_get_policy_rejects_an_unknown_key(key):
    with pytest.raises(KeyError, match="Registered policies: band-v1"):
        get_policy(key)


def test_another_class_with_the_three_members_is_a_policy():
    """The interface is structural: an id, a version and ``decide``."""

    class AlwaysHard:
        id = "always-hard"
        version = "v0"

        def decide(self, state: LearnerState, context: DecisionContext) -> DecisionRecord:
            return DecisionRecord(
                policy_id=self.id,
                policy_version=self.version,
                action={"kind": "difficulty", "difficulty": "hard"},
                state_used={},
                context_used={},
            )

    policy = AlwaysHard()
    record = policy.decide(LearnerState(mastery={}, initial_mastery=0.3), DecisionContext())

    assert isinstance(policy, Policy)
    assert policy_key(policy) == "always-hard-v0"
    assert difficulty_of(record) == "hard"
    assert record.to_dict() == {
        "policy_id": "always-hard",
        "policy_version": "v0",
        "action": {"kind": "difficulty", "difficulty": "hard"},
        "state_used": {},
        "context_used": {},
        "edges_used": [],
    }


@pytest.mark.parametrize("module", POLICY_MODULES)
def test_policy_modules_import_the_standard_library_only(module):
    """Every module of the package, ``__init__.py`` included, and any module added later."""
    source = (POLICY_DIR / module).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imported.add(node.module)

    outside = {
        name
        for name in imported
        if name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith("backend.app.student.policy.")
    }
    assert imported
    assert not outside


def test_policy_package_imports_without_the_rest_of_the_application():
    """A script or a simulator can import the policies without settings or pydantic.

    A fresh interpreter imports the package, which also runs the ``__init__.py`` of every
    parent package, and reports which application modules that loaded.
    """
    assert {"__init__.py", "band.py", "base.py", "registry.py"} <= set(POLICY_MODULES)
    assert Path(sys.modules[BandPolicyV1.__module__].__file__).resolve().parent == POLICY_DIR

    code = (
        "import sys\n"
        "import backend.app.student.policy as policy\n"
        "assert policy.get_policy('band-v1') is policy.BAND_V1\n"
        "heavy = ('pydantic', 'fastapi', 'backend.app.core.settings',\n"
        "         'backend.app.student.models', 'backend.app.ui_payloads.decisions')\n"
        "print([name for name in heavy if name in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    "module",
    [
        "backend.app.ui_payloads.decisions",
        "backend.app.ui_payloads.quiz",
        "backend.app.student.models",
    ],
)
def test_modules_that_carry_the_record_import_first_without_a_cycle(module):
    """The payload imports the policy package and the learner models import both.

    Each of them must load as the first import of a fresh interpreter.
    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]


# ---------------------------------------------------------------------------
# The rule: the same bands at the same boundaries
# ---------------------------------------------------------------------------


def test_band_for_matches_the_legacy_rule_on_a_grid():
    """k/1000 from -0.1 to 1.1, the floats next to both boundaries, 5000 seeded floats.

    Also 1.5 and the integers 0 and 1.
    """
    rng = random.Random(306)
    grid = [k / 1000 for k in range(-100, 1101)]
    grid += [mastery for mastery, _ in BOUNDARIES]
    grid += [rng.random() for _ in range(5000)]
    grid += [0, 1, 1.5]

    assert (EASY_BELOW, MEDIUM_UP_TO) == (0.4, 0.7)
    assert [band_for(mastery) for mastery in grid] == [_legacy_band(mastery) for mastery in grid]
    assert [band_for(k / 1000) for k in range(1001)] == (
        ["easy"] * 400 + ["medium"] * 301 + ["hard"] * 300
    )


@pytest.mark.parametrize(("mastery", "band"), BOUNDARIES)
def test_boundaries_in_the_rule_the_record_and_the_shim(mastery, band):
    profile = _profile(mastery)
    record = profile.decide_difficulty(CONCEPT)

    assert band_for(mastery) == band
    assert record == _band_record(band, mastery, "tracked", CONCEPT)
    assert difficulty_of(record) == band
    assert profile.get_target_difficulty(CONCEPT) == band


# ---------------------------------------------------------------------------
# The shim and the service decide through the policy
# ---------------------------------------------------------------------------


def test_shim_delegates_to_band_v1(monkeypatch):
    calls: list[tuple[Any, LearnerState, DecisionContext]] = []
    decide = BandPolicyV1.decide

    def spy(self, state, context):
        calls.append((self, state, context))
        return decide(self, state, context)

    monkeypatch.setattr(BandPolicyV1, "decide", spy)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)

    assert _profile(0.55).get_target_difficulty(CONCEPT) == "medium"
    assert calls == [
        (
            BAND_V1,
            LearnerState(mastery={CONCEPT: 0.55}, initial_mastery=0.3),
            DecisionContext(concept=CONCEPT),
        )
    ]


def test_shim_and_service_return_what_the_policy_decides(monkeypatch, service):
    """With the policy replaced by one that always says "hard", every path says "hard".

    The profile is in the easy band, so a copy of the rule kept outside the policy would
    answer "easy".
    """

    def always_hard(self, state, context):
        return _band_record("hard", 0.1, "tracked", CONCEPT)

    profile = _profile(0.1)
    service.save_profile(profile)
    assert profile.get_target_difficulty(CONCEPT) == "easy"

    monkeypatch.setattr(BandPolicyV1, "decide", always_hard)

    assert profile.get_target_difficulty(CONCEPT) == "hard"
    assert profile.get_target_difficulty("Unseen Concept") == "hard"
    response = service.get_target_difficulty(CONCEPT, LEARNER)
    assert response.target_difficulty == "hard"
    assert response.decision.action == {"kind": "difficulty", "difficulty": "hard"}
    assert service.get_all_target_difficulties(LEARNER) == {CONCEPT: "hard", OTHER_CONCEPT: "hard"}
    assert service.update_mastery(CONCEPT, False, LEARNER).target_difficulty == "hard"


def test_shim_and_service_keep_their_signatures():
    """Existing callers and stubs keep working: the same arguments, and nothing new is required."""
    shim = inspect.signature(StudentProfile.get_target_difficulty)
    service_method = inspect.signature(StudentService.get_target_difficulty)
    init = inspect.signature(StudentService.__init__)

    assert list(shim.parameters) == ["self", "concept"]
    assert list(service_method.parameters) == ["self", "concept", "student_id"]
    assert service_method.parameters["student_id"].default == "default"
    # The clock comes after the arguments the service had before, and all of them are optional.
    assert list(init.parameters) == ["self", "storage_path", "concept_validator", "clock"]
    assert all(
        parameter.default is not inspect.Parameter.empty
        for name, parameter in init.parameters.items()
        if name != "self"
    )


def test_difficulty_of_rejects_a_record_without_a_difficulty():
    record = DecisionRecord("other", "v1", {"kind": "next_concept"}, {}, {})

    with pytest.raises(ValueError, match="holds no difficulty"):
        difficulty_of(record)
    with pytest.raises(ValueError, match="holds no difficulty"):
        difficulty_of(DecisionRecord("other", "v1", {"difficulty": "extreme"}, {}, {}))


def test_band_v1_needs_a_concept():
    state = LearnerState(mastery={CONCEPT: 0.55}, initial_mastery=0.3)

    with pytest.raises(ValueError, match="context.concept"):
        BAND_V1.decide(state, DecisionContext())


# ---------------------------------------------------------------------------
# What the record holds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("mastery", "band"), MASTERY_LEVELS.items())
def test_record_fields_for_a_tracked_concept(mastery, band):
    record = _profile(mastery).decide_difficulty(CONCEPT)

    assert record == _band_record(band, mastery, "tracked", CONCEPT)
    assert record.policy_id == "band"
    assert record.policy_version == "v1"
    assert dict(record.action) == {"kind": "difficulty", "difficulty": band}
    assert dict(record.state_used) == {"mastery": mastery, "mastery_source": "tracked"}
    assert dict(record.context_used) == {"concept": CONCEPT}
    assert record.edges_used == ()


@pytest.mark.parametrize(("initial_mastery", "band"), INITIAL_MASTERY_BANDS)
def test_record_for_an_unseen_concept_uses_the_initial_mastery(monkeypatch, initial_mastery, band):
    monkeypatch.setattr(settings, "student_initial_mastery", initial_mastery)
    expected = _band_record(band, initial_mastery, "initial", "Unseen Concept")

    assert StudentProfile(student_id=LEARNER).decide_difficulty("Unseen Concept") == expected
    # History on other concepts does not move it.
    for mastery in MASTERY_LEVELS:
        assert _profile(mastery).decide_difficulty("Unseen Concept") == expected


def test_record_names_the_concept_that_was_asked():
    """Two concepts of one profile: each record names its own concept and mastery."""
    profile = _profile(0.9)

    assert profile.decide_difficulty(CONCEPT) == _band_record("hard", 0.9, "tracked", CONCEPT)
    assert profile.decide_difficulty(OTHER_CONCEPT) == _band_record(
        "medium", 0.55, "tracked", OTHER_CONCEPT
    )


@pytest.mark.parametrize("asked", OTHER_SPELLINGS)
def test_record_names_the_concept_exactly_as_asked(monkeypatch, service, asked):
    """Nothing trims or re-cases the concept between the caller and the record.

    The profile has history on "Civil War" at 0.9. Another spelling is another key, so it is
    decided with the initial mastery, and the record names the spelling that was asked.
    """
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    profile = _profile(0.9)
    service.save_profile(profile)
    assert asked != CONCEPT

    # Through the profile: no history under this spelling.
    assert profile.learner_state(asked) == LearnerState(mastery={}, initial_mastery=0.3)
    assert profile.decide_difficulty(asked) == _band_record("easy", 0.3, "initial", asked)
    # At the policy, with history under exactly this spelling.
    state = LearnerState(mastery={asked: 0.9, CONCEPT: 0.1}, initial_mastery=0.3)
    assert BAND_V1.decide(state, DecisionContext(concept=asked)) == _band_record(
        "hard", 0.9, "tracked", asked
    )
    # Through the service, which does not trim either (the routes do, before they call it).
    response = service.get_target_difficulty(asked, LEARNER)
    assert response.concept == asked
    assert response.decision.context_used == {"concept": asked}
    assert response.decision.state_used == {"mastery": 0.3, "mastery_source": "initial"}


def test_record_holds_the_unrounded_mastery(service):
    """The response rounds the mastery to three places; the record keeps what the policy read.

    A stored 0.4 - e is reported as 0.4, where the band rule says "medium". The record shows
    the value behind "easy".
    """
    stored = math.nextafter(0.4, 0.0)
    service.save_profile(_profile(stored))

    response = service.get_target_difficulty(CONCEPT, LEARNER)

    assert response.mastery_level == 0.4
    assert response.target_difficulty == "easy"
    assert response.decision.state_used == {"mastery": stored, "mastery_source": "tracked"}
    assert response.decision.state_used["mastery"] != response.mastery_level
    as_json = json.loads(response.model_dump_json())
    assert as_json["decision"]["state_used"]["mastery"] == stored
    assert as_json["mastery_level"] == 0.4


def test_record_stores_the_mastery_as_a_float():
    """An integer mastery gives the record, and the id, of the equal float."""
    as_int = BAND_V1.decide(
        LearnerState(mastery={CONCEPT: 1}, initial_mastery=0), DecisionContext(concept=CONCEPT)
    )
    as_float = BAND_V1.decide(
        LearnerState(mastery={CONCEPT: 1.0}, initial_mastery=0.0), DecisionContext(concept=CONCEPT)
    )

    assert type(as_int.state_used["mastery"]) is float
    assert as_int == as_float
    assert as_int.record_id() == as_float.record_id()


# ---------------------------------------------------------------------------
# Undeclared inputs change neither the action nor the record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "value"), UNDECLARED, ids=[_field_id(path) for path, _ in UNDECLARED]
)
def test_undeclared_inputs_change_neither_action_nor_record(path, value):
    for mastery, band in MASTERY_LEVELS.items():
        base = _profile(mastery)
        changed = _changed(base, path, value)
        assert changed != base, f"{_field_id(path)}={value!r} is the base value"

        record, record_after = base.decide_difficulty(CONCEPT), changed.decide_difficulty(CONCEPT)

        assert record_after.action == record.action == {"kind": "difficulty", "difficulty": band}
        assert record_after == record
        assert record_after.record_id() == record.record_id()
        assert record_after.to_dict() == record.to_dict()


def test_every_profile_field_is_declared_or_has_an_undeclared_row():
    """A field added to the learner models needs a row in the tables before this passes."""
    undeclared = {f"ConceptMastery.{path[2]}" for path, _ in UNDECLARED if path[:2] == _RECORD}
    undeclared |= {f"StudentProfile.{path[0]}" for path, _ in UNDECLARED if len(path) == 1}
    model_fields = {f"ConceptMastery.{name}" for name in ConceptMastery.model_fields}
    model_fields |= {f"StudentProfile.{name}" for name in StudentProfile.model_fields}

    assert model_fields == undeclared | set(_DECLARED)
    assert not undeclared & set(_DECLARED)


@pytest.mark.parametrize("field", UNDECLARED_CONTEXT)
def test_undeclared_context_changes_neither_action_nor_record(field):
    state = LearnerState(mastery={CONCEPT: 0.55}, initial_mastery=0.3)
    plain = DecisionContext(concept=CONCEPT)
    other = DecisionContext(concept=CONCEPT, **{field: UNDECLARED_CONTEXT[field]})
    assert other != plain

    record, record_after = BAND_V1.decide(state, plain), BAND_V1.decide(state, other)

    assert record_after == record == _band_record("medium", 0.55, "tracked", CONCEPT)
    assert record_after.record_id() == record.record_id()
    assert record_after.edges_used == ()


def test_every_context_field_is_declared_or_has_an_undeclared_row():
    context_fields = {field.name for field in fields(DecisionContext)}

    assert context_fields == {"concept"} | set(UNDECLARED_CONTEXT)


def test_state_the_policy_does_not_use_stays_out_of_the_record(monkeypatch):
    """With history, the initial mastery is unused; without, every tracked mastery is."""
    context = DecisionContext(concept=CONCEPT)
    tracked = BAND_V1.decide(LearnerState({CONCEPT: 0.55}, initial_mastery=0.3), context)
    unseen = BAND_V1.decide(LearnerState({}, initial_mastery=0.3), context)

    for initial_mastery in (0.0, 0.5, 0.9):
        state = LearnerState({CONCEPT: 0.55, OTHER_CONCEPT: 0.9}, initial_mastery=initial_mastery)
        assert BAND_V1.decide(state, context) == tracked
    for other_mastery in (0.0, 0.5, 0.9):
        state = LearnerState({OTHER_CONCEPT: other_mastery}, initial_mastery=0.3)
        assert BAND_V1.decide(state, context) == unseen

    # The same through the profile: the setting does not reach a concept with history.
    before = _profile(0.55).decide_difficulty(CONCEPT)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.9)
    assert _profile(0.55).decide_difficulty(CONCEPT) == before == tracked


def test_learner_state_exposes_only_the_asked_concept(monkeypatch):
    monkeypatch.setattr(settings, "student_initial_mastery", 0.25)
    profile = _profile(0.9)

    state = profile.learner_state(CONCEPT)

    assert [field.name for field in fields(LearnerState)] == ["mastery", "initial_mastery"]
    assert state == LearnerState(mastery={CONCEPT: 0.9}, initial_mastery=0.25)
    assert dict(state.mastery) == {CONCEPT: 0.9}
    assert dict(profile.learner_state(OTHER_CONCEPT).mastery) == {OTHER_CONCEPT: 0.55}
    assert profile.learner_state("Unseen Concept") == LearnerState(mastery={}, initial_mastery=0.25)
    # Undeclared profile fields do not reach the state either.
    for path, value in UNDECLARED:
        assert _changed(profile, path, value).learner_state(CONCEPT) == state, _field_id(path)


# ---------------------------------------------------------------------------
# Declared inputs change the record
# ---------------------------------------------------------------------------


def test_declared_state_changes_the_record():
    low, above, higher = (_profile(m).decide_difficulty(CONCEPT) for m in (0.39, 0.41, 0.45))

    # Across the boundary: another action, another record, another id.
    assert (difficulty_of(low), difficulty_of(above)) == ("easy", "medium")
    assert low != above
    assert low.record_id() != above.record_id()
    # Inside one band: the same action, another state used, another id.
    assert above.action == higher.action
    assert above.state_used != higher.state_used
    assert above != higher
    assert above.record_id() != higher.record_id()


def test_mastery_source_and_concept_are_part_of_the_record(monkeypatch):
    """The same number from history and from the default, and for another concept."""
    monkeypatch.setattr(settings, "student_initial_mastery", 0.55)
    profile = _profile(0.55)

    tracked = profile.decide_difficulty(CONCEPT)
    initial = profile.decide_difficulty("Unseen Concept")
    other = profile.decide_difficulty(OTHER_CONCEPT)

    assert tracked.action == initial.action == other.action
    assert tracked.state_used["mastery"] == initial.state_used["mastery"] == 0.55
    assert (tracked.state_used["mastery_source"], initial.state_used["mastery_source"]) == (
        "tracked",
        "initial",
    )
    assert tracked.state_used == other.state_used
    assert len({tracked, initial, other}) == 3
    assert len({record.record_id() for record in (tracked, initial, other)}) == 3


# ---------------------------------------------------------------------------
# Record identity: equality and the id; no time, no random part
# ---------------------------------------------------------------------------


def test_record_has_no_time_and_no_random_part():
    assert [field.name for field in fields(DecisionRecord)] == RECORD_FIELDS

    first = _profile(0.55).decide_difficulty(CONCEPT)
    second = _profile(0.55).decide_difficulty(CONCEPT)

    assert list(first.to_dict()) == RECORD_FIELDS
    assert first is not second
    assert first == second
    assert hash(first) == hash(second)
    assert first.record_id() == second.record_id() == first.record_id()


def test_record_id_is_pinned_for_a_fixed_input():
    """Guards the canonical JSON: sorted keys, no whitespace, UTF-8, floats as Python writes them."""
    record = _profile(0.55).decide_difficulty(CONCEPT)
    canonical = (
        '{"action":{"difficulty":"medium","kind":"difficulty"},'
        '"context_used":{"concept":"Civil War"},"edges_used":[],'
        '"policy_id":"band","policy_version":"v1",'
        '"state_used":{"mastery":0.55,"mastery_source":"tracked"}}'
    )

    assert record.canonical_json() == canonical
    assert record.record_id() == "76dfd3041ebb5cea"
    assert record.record_id() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def test_record_id_with_edges_and_non_ascii_text():
    record = DecisionRecord(
        policy_id="band",
        policy_version="v1",
        action={"kind": "difficulty", "difficulty": "easy"},
        state_used={"mastery": 0.3, "mastery_source": "initial"},
        context_used={"concept": "Révolution française"},
        edges_used=[EdgeUse("A", "B", "PREREQ", "curated")],
    )

    assert record.edges_used == (EdgeUse("A", "B", "PREREQ", "curated"),)
    assert '"concept":"Révolution française"' in record.canonical_json()
    assert record.record_id() == "8d2e05cbf4b33e2f"
    # Key order of the mappings passed in does not matter.
    reordered = DecisionRecord(
        policy_id="band",
        policy_version="v1",
        action={"difficulty": "easy", "kind": "difficulty"},
        state_used={"mastery_source": "initial", "mastery": 0.3},
        context_used={"concept": "Révolution française"},
        edges_used=(EdgeUse("A", "B", "PREREQ", "curated"),),
    )
    assert reordered == record
    assert reordered.record_id() == record.record_id()
    # The edges are part of the record.
    without_edges = DecisionRecord(
        record.policy_id,
        record.policy_version,
        record.action,
        record.state_used,
        record.context_used,
    )
    assert without_edges != record
    assert without_edges.record_id() != record.record_id()


@pytest.mark.parametrize("field", ["policy_id", "policy_version"])
def test_policy_id_and_version_are_part_of_the_record(field):
    record = _profile(0.55).decide_difficulty(CONCEPT)
    other = DecisionRecord(**{**record.to_dict(), "edges_used": (), field: "other"})

    assert other != record
    assert other.record_id() != record.record_id()


@pytest.mark.parametrize(
    "change",
    [
        {"action": {"kind": "difficulty", "difficulty": "easy"}},
        {"action": {"kind": "difficulty", "difficulty": "medium", "extra": None}},
        {"state_used": {"mastery": 0.55, "mastery_source": "initial"}},
        {"state_used": {"mastery": 0.55, "mastery_source": "tracked", "attempts": 5}},
        {"context_used": {"concept": OTHER_CONCEPT}},
        {"context_used": {"concept": CONCEPT, "seed": 1}},
        {"edges_used": (EDGE,)},
    ],
    ids=["action", "action-key", "state", "state-key", "context", "context-key", "edges"],
)
def test_each_part_of_the_record_counts_for_equality_and_for_the_id(change):
    record = _band_record("medium", 0.55, "tracked", CONCEPT)
    other = replace(record, **change)

    assert other != record
    assert other.record_id() != record.record_id()
    assert replace(other, **{name: getattr(record, name) for name in change}) == record


def test_edge_fields_and_edge_order_count():
    second = EdgeUse(source="A", target="B", relation="PREREQ", provenance="curated:t@v1")
    record = replace(_band_record("medium", 0.55, "tracked", CONCEPT), edges_used=(EDGE, second))
    reordered = replace(record, edges_used=(second, EDGE))
    other_provenance = replace(record, edges_used=(replace(EDGE, provenance="extracted"), second))

    assert reordered != record
    assert reordered.record_id() != record.record_id()
    assert other_provenance != record
    assert other_provenance.record_id() != record.record_id()


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        (0.5, 0.5, True),
        (0.0, -0.0, True),
        (1, 1.0, False),
        (True, 1, False),
        (False, 0.0, False),
        (None, "null", False),
        (math.nan, math.nan, True),
    ],
    ids=["float", "negative-zero", "int-float", "bool-int", "bool-float", "none-text", "nan"],
)
def test_records_are_equal_exactly_when_their_canonical_json_is(first, second, same):
    """Equality, hash and id follow one text, so equal records cannot have different ids.

    Python compares 1 == 1.0 == True, and JSON writes the three differently: they make three
    records. -0.0 is stored as 0.0. Two NaN values are written alike and make one record.
    """
    a = DecisionRecord("p", "v1", {"value": first}, {"value": first}, {"value": first})
    b = DecisionRecord("p", "v1", {"value": second}, {"value": second}, {"value": second})

    assert (a == b) is same
    assert (a != b) is not same
    assert (a.canonical_json() == b.canonical_json()) is same
    assert (a.record_id() == b.record_id()) is same
    assert len({a, b}) == (1 if same else 2)
    if same:
        assert hash(a) == hash(b)


def test_record_is_equal_to_records_only():
    record = _band_record("medium", 0.55, "tracked", CONCEPT)

    assert record != record.to_dict()
    assert record != record.canonical_json()
    assert record != object()
    assert record == copy.copy(record)


def test_negative_zero_gives_the_record_of_zero():
    """A stored mastery of -0.0 passes ``ge=0.0``; its record and id are those of 0.0."""
    plus, minus = (_profile(mastery).decide_difficulty(CONCEPT) for mastery in (0.0, -0.0))
    unseen_plus, unseen_minus = (
        BAND_V1.decide(LearnerState({}, initial), DecisionContext(concept=CONCEPT))
        for initial in (0.0, -0.0)
    )

    assert minus == plus == _band_record("easy", 0.0, "tracked", CONCEPT)
    assert minus.record_id() == plus.record_id()
    assert minus.canonical_json() == plus.canonical_json()
    assert math.copysign(1.0, minus.state_used["mastery"]) == 1.0
    assert unseen_minus == unseen_plus == _band_record("easy", 0.0, "initial", CONCEPT)
    assert unseen_minus.record_id() == unseen_plus.record_id()
    # The learner state stores it the same way.
    assert math.copysign(1.0, LearnerState({CONCEPT: -0.0}, 0.3).mastery[CONCEPT]) == 1.0


def test_decide_and_record_id_read_no_clock_and_no_random_source(monkeypatch):
    profile = _profile(0.55)
    expected = profile.decide_difficulty(CONCEPT)

    def forbidden(*args, **kwargs):
        raise AssertionError("a policy or a record read the clock or a random source")

    with monkeypatch.context() as patched:
        for module, name in (
            (time, "time"),
            (time, "time_ns"),
            (time, "monotonic"),
            (time, "monotonic_ns"),
            (uuid, "uuid1"),
            (uuid, "uuid4"),
            (random, "random"),
            (random, "getrandbits"),
            (random, "randint"),
            (os, "urandom"),
        ):
            patched.setattr(module, name, forbidden)
        record = profile.decide_difficulty(CONCEPT)
        record_id = record.record_id()

    assert record == expected
    assert record_id == expected.record_id() == "76dfd3041ebb5cea"


def test_record_id_is_the_same_in_a_fresh_interpreter_with_another_hash_seed():
    """The id does not depend on the process: not on string hashing, not on dict order."""
    code = (
        "from backend.app.student.policy import BAND_V1, DecisionContext, LearnerState\n"
        "state = LearnerState(mastery={'Civil War': 0.55}, initial_mastery=0.3)\n"
        "print(BAND_V1.decide(state, DecisionContext(concept='Civil War')).record_id())\n"
    )
    ids = set()
    for seed in ("0", "306"):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            timeout=50,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        ids.add(result.stdout.strip())

    assert ids == {"76dfd3041ebb5cea"}


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_record_is_immutable_and_json_serialisable():
    action = {"kind": "difficulty", "difficulty": "easy"}
    record = DecisionRecord("band", "v1", action, {"mastery": 0.3}, {"concept": CONCEPT})
    record_id = record.record_id()

    for mapping in (record.action, record.state_used, record.context_used):
        assert not isinstance(mapping, dict)
        with pytest.raises(TypeError):
            mapping["difficulty"] = "hard"
        with pytest.raises(TypeError):
            del mapping["kind"]
        assert not hasattr(mapping, "update")
    with pytest.raises(FrozenInstanceError):
        record.action = {"kind": "difficulty", "difficulty": "hard"}
    with pytest.raises(FrozenInstanceError):
        record.policy_version = "v2"

    # The record holds copies: neither the mapping passed in nor to_dict() leads back to it.
    action["difficulty"] = "hard"
    record.to_dict()["action"]["difficulty"] = "hard"
    record.to_dict()["edges_used"].append("edge")
    assert record.action == {"kind": "difficulty", "difficulty": "easy"}
    assert record.edges_used == ()
    assert record.record_id() == record_id

    assert json.loads(json.dumps(record.to_dict())) == record.to_dict()
    assert copy.deepcopy(record) == record
    assert pickle.loads(pickle.dumps(record)) == record
    assert pickle.loads(pickle.dumps(record)).record_id() == record_id


@pytest.mark.parametrize("name", MAPPING_FIELDS)
def test_record_mappings_have_no_way_to_change(name):
    """No item assignment, no deletion and none of the dict methods that write."""
    source = {
        "action": {"kind": "difficulty", "difficulty": "medium"},
        "state_used": {"mastery": 0.55, "mastery_source": "tracked"},
        "context_used": {"concept": CONCEPT},
    }
    record = DecisionRecord("band", "v1", **source)
    mapping = getattr(record, name)
    key = next(iter(mapping))
    before, id_before = record.to_dict(), record.record_id()

    with pytest.raises(TypeError):
        mapping[key] = "changed"
    with pytest.raises(TypeError):
        mapping["new_key"] = 1
    with pytest.raises(TypeError):
        del mapping[key]
    for method, arguments in (
        ("update", ({key: "changed"},)),
        ("pop", (key,)),
        ("popitem", ()),
        ("clear", ()),
        ("setdefault", ("new_key", 1)),
    ):
        with pytest.raises(AttributeError):
            getattr(mapping, method)(*arguments)

    # The dict the record was built from is not shared with it.
    source[name]["injected"] = "later"
    del source[name][key]

    assert isinstance(mapping, Mapping)
    assert not isinstance(mapping, dict)
    assert record.to_dict() == before
    assert record.record_id() == id_before == "76dfd3041ebb5cea"


@pytest.mark.parametrize(
    "mapping",
    [
        {"kind": ["difficulty"]},
        {"kind": {"nested": "mapping"}},
        {"kind": ("a", "tuple")},
        {"when": datetime(2026, 11, 11, 12, 0)},
        {1: "a key that is not a string"},
    ],
    ids=["list", "dict", "tuple", "datetime", "non-string-key"],
)
def test_record_mappings_hold_json_scalars_only(mapping):
    """A nested value could be changed after creation, so the record refuses it."""
    for field in ("action", "state_used", "context_used"):
        arguments = {"action": {}, "state_used": {}, "context_used": {}, field: mapping}
        with pytest.raises(TypeError):
            DecisionRecord("band", "v1", **arguments)

    scalars = {"s": "text", "i": 1, "f": 0.5, "b": True, "n": None}
    assert DecisionRecord("band", "v1", scalars, {}, {}).to_dict()["action"] == scalars


def test_learner_state_and_context_are_immutable():
    mastery = {CONCEPT: 0.55}
    state = LearnerState(mastery=mastery, initial_mastery=0.3)
    context = DecisionContext(concept=CONCEPT, candidates=[CONCEPT], edges=[])

    with pytest.raises(TypeError):
        state.mastery[CONCEPT] = 0.9
    with pytest.raises(FrozenInstanceError):
        state.initial_mastery = 0.9
    with pytest.raises(FrozenInstanceError):
        context.concept = OTHER_CONCEPT
    mastery[CONCEPT] = 0.9
    assert state.mastery == {CONCEPT: 0.55}
    assert (context.candidates, context.edges) == ((CONCEPT,), ())
    assert pickle.loads(pickle.dumps(state)) == state
    assert hash(state) == hash(LearnerState(mastery={CONCEPT: 0.55}, initial_mastery=0.3))
    assert repr(state.mastery) == "{'Civil War': 0.55}"
    assert len(state.mastery) == 1


# ---------------------------------------------------------------------------
# The envelope: the service adds the time, the payload carries the record
# ---------------------------------------------------------------------------


def test_service_response_carries_the_record_and_the_clock_time(service):
    profile = _profile(0.75)
    service.save_profile(profile)
    record = profile.decide_difficulty(CONCEPT)

    response = service.get_target_difficulty(CONCEPT, LEARNER)

    assert response.decision == DecisionRecordPayload.from_record(record, DECIDED_AT)
    assert response.decision.model_dump() == {
        "record_id": record.record_id(),
        "policy_id": "band",
        "policy_version": "v1",
        "action": {"kind": "difficulty", "difficulty": "hard"},
        "state_used": {"mastery": 0.75, "mastery_source": "tracked"},
        "context_used": {"concept": CONCEPT},
        "edges_used": [],
        "decided_at": DECIDED_AT,
    }
    assert response.target_difficulty == response.decision.action["difficulty"] == "hard"
    assert response.mastery_level == 0.75


def test_service_response_for_an_unseen_concept(service, monkeypatch):
    monkeypatch.setattr(settings, "student_initial_mastery", 0.5)

    response = service.get_target_difficulty("Unseen Concept", "new_learner")

    assert response.target_difficulty == "medium"
    assert response.decision.state_used == {"mastery": 0.5, "mastery_source": "initial"}
    assert response.decision.context_used == {"concept": "Unseen Concept"}


@pytest.mark.parametrize(("mastery", "band"), BOUNDARIES)
def test_service_decides_at_the_boundaries(service, mastery, band):
    """The stored value reaches the policy unrounded, through SQLite and back."""
    profile = _profile(mastery)
    service.save_profile(profile)

    response = service.get_target_difficulty(CONCEPT, LEARNER)

    assert response.concept == CONCEPT
    assert response.mastery_level == round(mastery, 3)
    assert response.target_difficulty == band
    assert response.decision == DecisionRecordPayload.from_record(
        _band_record(band, mastery, "tracked", CONCEPT), DECIDED_AT
    )
    assert response.decision.record_id == profile.decide_difficulty(CONCEPT).record_id()
    assert service.get_all_target_difficulties(LEARNER) == {CONCEPT: band, OTHER_CONCEPT: "medium"}


def test_decided_at_is_outside_the_record(tmp_path):
    """The same decision at two times: one record id, two values of decided_at."""
    later = DECIDED_AT + timedelta(hours=1)
    times = iter([DECIDED_AT, later])
    service = StudentService(storage_path=tmp_path / "profiles.sqlite3", clock=lambda: next(times))
    service.save_profile(_profile(0.55))

    first = service.get_target_difficulty(CONCEPT, LEARNER).decision
    second = service.get_target_difficulty(CONCEPT, LEARNER).decision

    assert (first.decided_at, second.decided_at) == (DECIDED_AT, later)
    assert first.record_id == second.record_id
    assert first.record_id == _profile(0.55).decide_difficulty(CONCEPT).record_id()
    assert first.model_dump(exclude={"decided_at"}) == second.model_dump(exclude={"decided_at"})


def test_service_reads_the_clock_once_per_decision(tmp_path):
    """One reading per record returned, and none on the paths that return no record."""
    readings: list[datetime] = []

    def clock() -> datetime:
        readings.append(DECIDED_AT + timedelta(seconds=len(readings)))
        return readings[-1]

    service = StudentService(storage_path=tmp_path / "profiles.sqlite3", clock=clock)
    service.save_profile(_profile(0.55))

    first = service.get_target_difficulty(CONCEPT, LEARNER).decision
    second = service.get_target_difficulty(CONCEPT, LEARNER).decision
    service.get_all_target_difficulties(LEARNER)
    service.update_mastery(CONCEPT, True, LEARNER)

    assert [first.decided_at, second.decided_at] == readings
    assert len(readings) == 2
    assert first.record_id == second.record_id


def test_default_clock_is_the_current_utc_time(tmp_path, monkeypatch):
    """Without a clock argument the service stamps ``datetime.now(UTC)``.

    The module's ``datetime`` is replaced by one with a fixed ``now``, so the test does not
    compare against the wall clock.
    """
    zones: list[Any] = []

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            zones.append(tz)
            return DECIDED_AT.astimezone(tz) if tz is not None else DECIDED_AT.replace(tzinfo=None)

    service = StudentService(storage_path=tmp_path / "profiles.sqlite3")
    monkeypatch.setattr("backend.app.student.student_service.datetime", FixedDatetime)

    decided_at = service.get_target_difficulty(CONCEPT, LEARNER).decision.decided_at

    assert [zone for zone in zones if zone is not None] == [UTC]
    assert decided_at == DECIDED_AT
    assert decided_at.utcoffset() == timedelta(0)


def test_payload_refuses_a_time_without_a_utc_offset(tmp_path):
    """``decided_at`` is an aware time; a clock that returns a naive one fails loudly."""
    record = _profile(0.55).decide_difficulty(CONCEPT)
    naive = datetime(2026, 11, 11, 12, 0)
    service = StudentService(storage_path=tmp_path / "profiles.sqlite3", clock=lambda: naive)

    with pytest.raises(ValidationError, match="timezone"):
        DecisionRecordPayload.from_record(record, naive)
    with pytest.raises(ValidationError, match="timezone"):
        service.get_target_difficulty(CONCEPT, LEARNER)
    # The paths that return no record do not read the clock.
    assert service.update_mastery(CONCEPT, True, LEARNER).total_attempts == 1
    assert set(service.get_all_target_difficulties(LEARNER)) == {CONCEPT}

    # Another offset is accepted and kept; it is the same instant.
    plus_two = DECIDED_AT.astimezone(timezone(timedelta(hours=2)))
    payload = DecisionRecordPayload.from_record(record, plus_two)
    assert payload.decided_at == DECIDED_AT
    assert payload.model_dump(mode="json")["decided_at"] == "2026-11-11T14:00:00+02:00"
    assert payload.record_id == record.record_id()


def test_payload_is_the_record_plus_its_id_and_the_time():
    edge = EdgeUse(source=OTHER_CONCEPT, target=CONCEPT, relation="PREREQ", provenance="test")
    record = DecisionRecord(
        policy_id="next",
        policy_version="v0",
        action={"kind": "next_concept", "concept": CONCEPT},
        state_used={"mastery": 0.75, "ready": True, "attempts": 3, "note": None},
        context_used={"step": 4},
        edges_used=(edge,),
    )

    payload = DecisionRecordPayload.from_record(record, DECIDED_AT)

    assert payload.model_dump(mode="json") == {
        **record.to_dict(),
        "record_id": record.record_id(),
        "decided_at": "2026-11-11T12:00:00Z",
    }
    assert payload.model_dump()["edges_used"] == [
        {"source": OTHER_CONCEPT, "target": CONCEPT, "relation": "PREREQ", "provenance": "test"}
    ]
    # Booleans, integers and floats keep their types.
    assert [type(value) for value in payload.state_used.values()] == [float, bool, int, type(None)]
