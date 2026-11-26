"""
Tests for the attempt record schema (#307; persisted by #308).

``backend/app/student/attempts.py`` defines one answered item as a frozen record with an
allowlist of fields: the row of the attempt log in ``docs/adaptivity/README.md``. The tests
hold the schema to that list, to "no free text" (every string is a short one-line id) and to
the two sources, "real" and "sim". Nothing is stored here: the records are used in memory.
"""

import ast
import copy
import json
import pickle
import sys
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.app.student import attempts
from backend.app.student.attempts import (
    ATTEMPT_FIELDS,
    ATTEMPT_SOURCES,
    MAX_ID_CHARS,
    SIM_EPOCH,
    Attempt,
    sim_timestamp,
)

pytestmark = pytest.mark.unit

# The row of the design note's attempt log: opaque learner id, item id, concept ids, chosen
# option id, correctness, latency, the assisted flag, decision-record id, model versions,
# source and timestamp.
DESIGN_NOTE_FIELDS = (
    "learner_id",
    "item_id",
    "concept_ids",
    "chosen_option_id",
    "correct",
    "latency_ms",
    "assisted",
    "decision_record_id",
    "model_versions",
    "source",
    "timestamp",
)

WHEN = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)


def _attempt(**changes: Any) -> Attempt:
    values: dict[str, Any] = {
        "learner_id": "4f1c9a",
        "item_id": "item-17",
        "concept_ids": ("The New Deal",),
        "chosen_option_id": "b",
        "correct": True,
        "latency_ms": 8400,
        "assisted": False,
        "decision_record_id": "76dfd3041ebb5cea",
        "model_versions": {"policy": "band-v1", "estimator": "bkt-fixed-v1"},
        "source": "real",
        "timestamp": WHEN,
    }
    values.update(changes)
    return Attempt(**values)


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_fields_are_exactly_the_allowlist_of_the_design_note():
    assert ATTEMPT_FIELDS == DESIGN_NOTE_FIELDS
    assert tuple(field.name for field in fields(Attempt)) == ATTEMPT_FIELDS


def test_row_has_the_allowlisted_keys_in_order_and_is_json():
    attempt = _attempt()
    row = attempt.to_row()

    assert tuple(row) == ATTEMPT_FIELDS
    assert json.loads(json.dumps(row)) == {
        "learner_id": "4f1c9a",
        "item_id": "item-17",
        "concept_ids": ["The New Deal"],
        "chosen_option_id": "b",
        "correct": True,
        "latency_ms": 8400,
        "assisted": False,
        "decision_record_id": "76dfd3041ebb5cea",
        "model_versions": {"estimator": "bkt-fixed-v1", "policy": "band-v1"},
        "source": "real",
        "timestamp": "2026-11-11T09:30:00+00:00",
    }


def test_row_of_a_simulated_attempt_without_options_latency_or_decision():
    attempt = _attempt(
        chosen_option_id=None,
        latency_ms=None,
        decision_record_id=None,
        model_versions={},
        source="sim",
        timestamp=sim_timestamp(90),
    )

    row = json.loads(json.dumps(attempt.to_row()))

    assert row["chosen_option_id"] is None
    assert row["latency_ms"] is None
    assert row["decision_record_id"] is None
    assert row["model_versions"] == {}
    assert row["source"] == "sim"
    assert row["timestamp"] == "2000-01-01T01:30:00+00:00"


def test_timestamp_keeps_its_utc_offset_in_the_row():
    plus_two = timezone(timedelta(hours=2))

    row = _attempt(timestamp=datetime(2026, 11, 11, 11, 30, tzinfo=plus_two)).to_row()

    assert row["timestamp"] == "2026-11-11T11:30:00+02:00"


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


def test_sources_are_real_and_sim():
    assert ATTEMPT_SOURCES == ("real", "sim")
    for source in ATTEMPT_SOURCES:
        assert _attempt(source=source).source == source


@pytest.mark.parametrize("source", ["", "simulated", "REAL", "Sim", None, 1])
def test_other_sources_are_rejected(source):
    with pytest.raises(ValueError, match="source must be one of"):
        _attempt(source=source)


# ---------------------------------------------------------------------------
# No free text: every string is a short one-line id
# ---------------------------------------------------------------------------

ID_FIELDS = ("learner_id", "item_id", "chosen_option_id", "decision_record_id")


@pytest.mark.parametrize("name", ID_FIELDS)
@pytest.mark.parametrize(
    "value",
    ["", "two\nlines", "tab\tseparated", "x" * (MAX_ID_CHARS + 1), "bell\x07"],
    ids=["empty", "newline", "tab", "too-long", "control"],
)
def test_ids_must_be_one_short_printable_line(name, value):
    with pytest.raises(ValueError, match="one printable line"):
        _attempt(**{name: value})


@pytest.mark.parametrize("name", ID_FIELDS)
def test_ids_must_be_strings(name):
    with pytest.raises(TypeError, match="must be a string"):
        _attempt(**{name: 17})


def test_an_id_may_be_as_long_as_the_limit_and_hold_spaces():
    attempt = _attempt(learner_id="x" * MAX_ID_CHARS, concept_ids=("Great Depression, The",))

    assert len(attempt.learner_id) == MAX_ID_CHARS == 200
    assert attempt.concept_ids == ("Great Depression, The",)


@pytest.mark.parametrize(
    "field",
    [
        "item_id",
        "learner_id",
        "source",
        "correct",
        "latency_ms",
        "timestamp",
        "concept_ids",
        "model_versions",
    ],
)
def test_error_messages_do_not_echo_the_rejected_value(field):
    secret = "my essay about\nwhat I did"

    with pytest.raises((TypeError, ValueError)) as error:
        _attempt(**{field: secret})

    assert "essay" not in str(error.value)
    assert field in str(error.value)


@pytest.mark.parametrize("concept_ids", [(), []])
def test_at_least_one_concept(concept_ids):
    with pytest.raises(ValueError, match="at least one concept"):
        _attempt(concept_ids=concept_ids)


def test_concept_ids_is_not_one_string():
    with pytest.raises(TypeError, match="not one string"):
        _attempt(concept_ids="The New Deal")


@pytest.mark.parametrize("concept_ids", [None, 5, 2.5], ids=["none", "int", "float"])
def test_concept_ids_must_be_a_sequence(concept_ids):
    with pytest.raises(TypeError, match="concept_ids must be a sequence of ids"):
        _attempt(concept_ids=concept_ids)


def test_every_concept_id_is_checked():
    with pytest.raises(ValueError, match="one printable line"):
        _attempt(concept_ids=("fine", "not\nfine"))
    with pytest.raises(TypeError, match="must be a string"):
        _attempt(concept_ids=("fine", 3))


@pytest.mark.parametrize(
    "versions",
    [{"policy": "line\nbreak"}, {"": "band-v1"}, {"policy": ""}, {"policy": "v" * 201}],
    ids=["value-newline", "empty-key", "empty-value", "long-value"],
)
def test_model_versions_hold_ids_only(versions):
    with pytest.raises(ValueError, match="one printable line"):
        _attempt(model_versions=versions)


def test_model_versions_values_must_be_strings():
    with pytest.raises(TypeError, match="must be a string"):
        _attempt(model_versions={"policy": 1})


@pytest.mark.parametrize(
    "versions",
    [None, [("policy", "band-v1")], "band-v1", 3],
    ids=["none", "list-of-pairs", "string", "int"],
)
def test_model_versions_must_be_a_mapping(versions):
    with pytest.raises(TypeError, match="model_versions must be a mapping of ids"):
        _attempt(model_versions=versions)


@pytest.mark.parametrize(
    "versions",
    [{1: "band-v1"}, {"policy": "band-v1", 2: "bkt-fixed-v1"}, {None: "band-v1"}],
    ids=["int-key", "mixed-keys", "none-key"],
)
def test_model_versions_keys_must_be_strings(versions):
    """Checked before the keys are sorted: keys of mixed types have no order."""
    with pytest.raises(TypeError, match="model_versions key must be a string"):
        _attempt(model_versions=versions)


def test_model_versions_may_be_empty():
    assert dict(_attempt(model_versions={}).model_versions) == {}


# ---------------------------------------------------------------------------
# Typed fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["correct", "assisted"])
@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_flags_must_be_bools(name, value):
    with pytest.raises(TypeError, match=f"{name} must be a bool"):
        _attempt(**{name: value})


@pytest.mark.parametrize("latency", [1.5, "8400", True])
def test_latency_must_be_an_int(latency):
    with pytest.raises(TypeError, match="latency_ms must be an int or None"):
        _attempt(latency_ms=latency)


def test_latency_must_not_be_negative():
    with pytest.raises(ValueError, match="must not be negative"):
        _attempt(latency_ms=-1)
    assert _attempt(latency_ms=0).latency_ms == 0


def test_timestamp_needs_a_utc_offset():
    with pytest.raises(ValueError, match="UTC offset"):
        _attempt(timestamp=datetime(2026, 11, 11, 9, 30))


def test_timestamp_must_be_a_datetime():
    with pytest.raises(TypeError, match="timestamp must be a datetime"):
        _attempt(timestamp="2026-11-11T09:30:00+00:00")


# ---------------------------------------------------------------------------
# Frozen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ATTEMPT_FIELDS)
def test_fields_cannot_be_assigned(name):
    attempt = _attempt()

    with pytest.raises(FrozenInstanceError):
        setattr(attempt, name, getattr(attempt, name))


def test_no_field_can_be_added():
    with pytest.raises((AttributeError, TypeError)):
        _attempt().note = "free text"


def test_containers_are_read_only_copies():
    concepts = ["The New Deal"]
    versions = {"policy": "band-v1"}
    attempt = _attempt(concept_ids=concepts, model_versions=versions)

    concepts.append("Dust Bowl")
    versions["policy"] = "changed"

    assert attempt.concept_ids == ("The New Deal",)
    assert dict(attempt.model_versions) == {"policy": "band-v1"}
    with pytest.raises(TypeError):
        attempt.model_versions["policy"] = "changed"


def test_equal_attempts_are_equal_and_hash_alike():
    first = _attempt(model_versions={"policy": "band-v1", "estimator": "bkt-fixed-v1"})
    second = _attempt(model_versions={"estimator": "bkt-fixed-v1", "policy": "band-v1"})

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second, replace(first, correct=False)}) == 2


def test_attempt_survives_pickling_and_copying():
    attempt = _attempt()

    for clone in (pickle.loads(pickle.dumps(attempt)), copy.deepcopy(attempt), copy.copy(attempt)):
        assert clone == attempt
        assert clone.to_row() == attempt.to_row()
        with pytest.raises(TypeError):
            clone.model_versions["policy"] = "changed"


def test_row_is_a_fresh_copy():
    attempt = _attempt()

    attempt.to_row()["concept_ids"].append("Dust Bowl")
    attempt.to_row()["model_versions"]["policy"] = "changed"

    assert attempt.to_row()["concept_ids"] == ["The New Deal"]
    assert attempt.to_row()["model_versions"]["policy"] == "band-v1"


# ---------------------------------------------------------------------------
# Simulated time
# ---------------------------------------------------------------------------


def test_simulated_time_starts_at_a_fixed_epoch_with_an_offset():
    assert SIM_EPOCH == datetime(2000, 1, 1, tzinfo=UTC)
    assert SIM_EPOCH.utcoffset() == timedelta(0)


def test_sim_timestamp_is_the_epoch_plus_simulated_minutes():
    assert sim_timestamp(0) == SIM_EPOCH
    assert sim_timestamp(1.5) == SIM_EPOCH + timedelta(seconds=90)
    assert sim_timestamp(120) == datetime(2000, 1, 1, 2, 0, tzinfo=UTC)


def test_module_imports_the_standard_library_only_and_reads_no_clock():
    source = Path(attempts.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imported.add(node.module)
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert imported
    assert all(name.split(".")[0] in sys.stdlib_module_names for name in imported)
    assert "time" not in imported
    assert not {"now", "utcnow", "today"} & attributes
