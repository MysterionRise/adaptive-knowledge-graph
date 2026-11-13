"""
Property tests for the Bayesian Knowledge Tracing update and the mastery bookkeeping (#210).

``StudentService._update_mastery_bkt`` (``backend/app/student/student_service.py``) is BKT
with a learning step:

    posterior = P(known | answer)                         Bayes' rule with slip and guess
    p_known   = posterior + (1 - posterior) * transit     the learning step
    p_known   = min(0.99, max(0.01, p_known))             the clamp

The defaults are transit 0.1, slip 0.1 and guess 0.25.

"A correct answer never lowers p_known, an incorrect one never raises it" does not hold for
this update. Two regions break it, and both are how BKT with a learning step and a clamp
behaves, not defects:

- Below the wrong-answer fixed point (3/26, about 0.1154, with the defaults) the learning step
  outweighs the evidence, so a wrong answer raises p_known: 0.10 becomes 0.1131 and 0.01
  becomes 0.1012. That is 116 of the 1001 priors k/1000.
- A stored value above the clamp is lowered by a correct answer: 1.0 becomes 0.99.

The properties that do hold, and that this module tests:

(a) A wrong answer never raises the posterior (the value before the learning step).
(b) After the learning step a wrong answer never leaves p_known above
    max(prior, fixed point).
(c) A correct answer never lowers p_known for priors in [0.01, 0.99].
(d) The result always lies in [0.01, 0.99].
(e) After a BKT update through the service, mastery_level is max(0.1, p_known).
(f) overall_ability is the mean of the tracked mastery levels.
(g) The default parameters are plausible: guess < 0.5, slip < 0.5 and 1 - slip > guess.
(h) The fixed point with the defaults is 3/26.

(a) to (d) are checked on a grid of priors for the defaults and for every plausible parameter
triple in ``PLAUSIBLE``. (a) and (c) need 1 - slip >= guess: outside that constraint the
evidence is inverted (see ``test_implausible_parameters_invert_the_evidence``). (a) is
observed with transit 0, where the function returns the posterior clamped to [0.01, 0.99],
so the check is p_known <= max(prior, 0.01).

One convention is pinned as well. When the observed answer has probability 0 (prior 0 and
guess 0 with a correct answer, prior 1 and slip 0 with a wrong one), Bayes' rule gives no
posterior and the function keeps the prior before the learning step.

Everything here works on in-memory models: no database, no LLM. The only randomness is the
``random()`` method of ``random.Random(210)``. (e) on the public path, an answer posted to
``/student/mastery`` with a stored profile, is in ``test_student_counterfactual.py``, which
has a learner store on ``tmp_path``.
"""

import itertools
import random
from fractions import Fraction
from functools import cache
from statistics import fmean

import pytest

from backend.app.core.settings import Settings, settings
from backend.app.student.models import ConceptMastery, StudentProfile
from backend.app.student.student_service import StudentService

pytestmark = pytest.mark.unit

SEED = 210
FIXED_POINT = 3 / 26  # wrong-answer fixed point with the default parameters
TOLERANCE = 1e-12  # for comparisons at a fixed point, where rounding decides the last bit

_rng = random.Random(SEED)

# Priors k/1000: the grid the two regions are counted on.
FINE_GRID = tuple(k / 1000 for k in range(1001))
# Priors for the parameter grid: k/200 plus 50 seeded draws, 0.0 and 1.0 included.
PRIORS = tuple(k / 200 for k in range(201)) + tuple(_rng.random() for _ in range(50))
# (transit, slip, guess) with slip < 0.5, guess < 0.5 and 1 - slip > guess: a lattice that
# includes the defaults, plus 20 seeded draws.
PLAUSIBLE = tuple(
    itertools.product((0.0, 0.05, 0.1, 0.3), (0.0, 0.05, 0.1, 0.3, 0.49), (0.0, 0.1, 0.25, 0.49))
) + tuple((_rng.random() / 2, _rng.random() / 2, _rng.random() / 2) for _ in range(20))


def _in_clamp(prior: float) -> bool:
    return 0.01 <= prior <= 0.99


@cache
def _bkt(
    prior: float, correct: bool, transit: float = 0.1, slip: float = 0.1, guess: float = 0.25
) -> float:
    """One update of the shipped function from ``prior``."""
    record = ConceptMastery(
        concept_name="c",
        mastery_level=prior,
        bkt_p_known=prior,
        bkt_p_transit=transit,
        bkt_p_slip=slip,
        bkt_p_guess=guess,
    )
    return StudentService._update_mastery_bkt(record, correct)


def _textbook_bkt(prior: float, correct: bool, transit: float, slip: float, guess: float) -> float:
    """The three lines of the module docstring in exact rational arithmetic.

    Written from the definitions: P(answer | known) and P(answer | not known) give the
    probability of the answer, Bayes' rule gives the posterior. An answer with probability 0
    leaves the prior as the posterior.
    """
    p, t, s, g = (Fraction(value) for value in (prior, transit, slip, guess))
    if_known, if_not_known = (1 - s, g) if correct else (s, 1 - g)
    p_answer = p * if_known + (1 - p) * if_not_known
    posterior = p * if_known / p_answer if p_answer else p
    learned = posterior + (1 - posterior) * t
    return float(min(Fraction(99, 100), max(Fraction(1, 100), learned)))


def _wrong_answer_fixed_point(transit: float, slip: float, guess: float) -> float:
    """Where repeated wrong answers converge, inside the clamp.

    Setting p equal to the wrong-answer update of p gives a quadratic with the roots 1 and
    transit * (1 - guess) / (1 - guess - slip).
    """
    return max(0.01, min(0.99, transit * (1 - guess) / (1 - guess - slip)))


def _service_without_storage() -> StudentService:
    """A service object that never opens SQLite.

    ``_apply_answer`` changes the profile it is given and reads only class constants, so the
    constructor, which creates the database file, is skipped.
    """
    return StudentService.__new__(StudentService)


def _answers(rng: random.Random, concepts: tuple[str, ...], count: int) -> list[tuple[str, bool]]:
    """A seeded sequence of (concept, correct) answers; uses ``rng.random()`` only."""
    return [(concepts[int(rng.random() * len(concepts))], rng.random() < 0.5) for _ in range(count)]


# ---------------------------------------------------------------------------
# (g), (h) and the update itself: default parameters, fixed point, worked examples
# ---------------------------------------------------------------------------


def test_default_parameters_are_plausible():
    """(g) guess < 0.5, slip < 0.5, and knowing the concept makes a correct answer more likely."""
    record = ConceptMastery(concept_name="c")
    transit, slip, guess = record.bkt_p_transit, record.bkt_p_slip, record.bkt_p_guess

    assert guess < 0.5
    assert slip < 0.5
    assert 1 - slip > guess  # P(correct | known) > P(correct | not known)
    assert 0 < transit < 1


def test_default_parameters_are_transit_0_1_slip_0_1_guess_0_25():
    """The values behind 3/26, the 116 raised priors and the worked examples."""
    record = ConceptMastery(concept_name="c")

    assert (record.bkt_p_transit, record.bkt_p_slip, record.bkt_p_guess) == (0.1, 0.1, 0.25)


def test_parameter_grid_is_plausible_and_includes_the_defaults():
    assert (0.1, 0.1, 0.25) in PLAUSIBLE
    assert len(set(PLAUSIBLE)) == len(PLAUSIBLE) == 100
    for transit, slip, guess in PLAUSIBLE:
        assert 0 <= transit < 1
        assert 0 <= slip < 0.5
        assert 0 <= guess < 0.5
        assert 1 - slip > guess


def test_wrong_answer_fixed_point_with_the_defaults_is_3_over_26():
    """(h) 3/26 maps to itself, and wrong answers converge to it from both sides."""
    assert _wrong_answer_fixed_point(0.1, 0.1, 0.25) == pytest.approx(FIXED_POINT, abs=TOLERANCE)
    assert _bkt(FIXED_POINT, False) == pytest.approx(FIXED_POINT, abs=TOLERANCE)

    for start in (0.01, 0.3, 0.99):
        p_known = start
        for _ in range(60):
            previous, p_known = p_known, _bkt(p_known, False)
            if start < FIXED_POINT:
                assert previous - TOLERANCE <= p_known <= FIXED_POINT + TOLERANCE
            else:
                assert FIXED_POINT - TOLERANCE <= p_known <= previous + TOLERANCE
        assert p_known == pytest.approx(FIXED_POINT, abs=TOLERANCE)


def test_fixed_point_formula_matches_the_update():
    """The closed form used in (b) is a fixed point of the shipped update for every triple."""
    for transit, slip, guess in PLAUSIBLE:
        fixed_point = _wrong_answer_fixed_point(transit, slip, guess)
        p_known = _bkt(fixed_point, False, transit, slip, guess)

        assert p_known == pytest.approx(fixed_point, abs=TOLERANCE), (transit, slip, guess)


@pytest.mark.parametrize(
    ("prior", "correct", "expected"),
    [
        (0.3, True, 115 / 178),  # posterior 54/89, about 0.6461 after the learning step
        (0.3, False, 11 / 74),  # posterior 2/37, about 0.1486 after the learning step
        (0.10, False, 31 / 274),  # about 0.1131: raised, 0.10 is below the fixed point
        (0.01, False, 301 / 2974),  # about 0.1012: raised
        (0.0, False, 0.1),  # posterior 0, then the learning step alone
        (0.0, True, 0.1),  # a correct answer does not move a prior of 0 either
        (0.99, True, 0.99),  # the clamp holds a value at its upper end
        (1.0, True, 0.99),  # the clamp lowers a stored 1.0
        (1.0, False, 0.99),  # a prior of 1 is not moved by evidence; the clamp returns 0.99
    ],
)
def test_worked_examples_with_the_defaults(prior, correct, expected):
    assert _bkt(prior, correct) == pytest.approx(expected, abs=TOLERANCE)


def test_impossible_evidence_keeps_the_prior_before_the_learning_step():
    """An answer with probability 0 leaves the posterior at the prior.

    Prior 0 and guess 0 make a correct answer impossible; prior 1 and slip 0 make a wrong one
    impossible. Bayes' rule divides by 0 there, and the function keeps the prior, then
    applies the learning step and the clamp.
    """
    assert _bkt(0.0, True, 0.1, 0.1, 0.0) == pytest.approx(0.1, abs=TOLERANCE)
    assert _bkt(0.0, True, 0.3, 0.1, 0.0) == pytest.approx(0.3, abs=TOLERANCE)
    assert _bkt(0.0, True, 0.0, 0.1, 0.0) == 0.01  # posterior 0, no learning, the clamp
    assert _bkt(1.0, False, 0.1, 0.0, 0.25) == 0.99  # posterior 1, the clamp
    assert _bkt(1.0, False, 0.0, 0.0, 0.25) == 0.99


def test_update_is_textbook_bkt_with_a_learning_step_and_a_clamp():
    """The shipped function against the definition, computed in exact rational arithmetic."""
    cases = [(prior, 0.1, 0.1, 0.25) for prior in FINE_GRID[::10]]
    cases += [
        (prior, *triple) for triple in PLAUSIBLE for prior in (0.0, 0.01, 0.2, 0.5, 0.8, 0.99, 1.0)
    ]

    for prior, transit, slip, guess in cases:
        for correct in (True, False):
            expected = _textbook_bkt(prior, correct, transit, slip, guess)

            assert _bkt(prior, correct, transit, slip, guess) == pytest.approx(
                expected, abs=TOLERANCE
            ), (prior, correct, transit, slip, guess)


# ---------------------------------------------------------------------------
# The two regions where the property in the issue body fails (documented behaviour)
# ---------------------------------------------------------------------------


def test_wrong_answer_raises_p_known_only_below_the_fixed_point():
    """Documented behaviour: with the defaults, 116 of 1001 priors rise on a wrong answer."""
    raised = [prior for prior in FINE_GRID if _bkt(prior, False) > prior]
    lowered = [prior for prior in FINE_GRID if _bkt(prior, False) < prior]

    assert raised == [prior for prior in FINE_GRID if prior < FIXED_POINT]
    assert len(raised) == 116
    # 3/26 is not on the grid: every other prior is strictly lowered.
    assert lowered == [prior for prior in FINE_GRID if prior > FIXED_POINT]
    assert len(lowered) == 885
    assert _bkt(0.10, False) == pytest.approx(0.1131, abs=5e-5)
    assert _bkt(0.01, False) == pytest.approx(0.1012, abs=5e-5)


def test_correct_answer_lowers_p_known_only_above_the_clamp():
    """Documented behaviour: a stored value above 0.99 comes back as 0.99."""
    lowered = [prior for prior in FINE_GRID if _bkt(prior, True) < prior]
    raised = [prior for prior in FINE_GRID if _bkt(prior, True) > prior]

    assert lowered == [prior for prior in FINE_GRID if prior > 0.99]
    assert all(_bkt(prior, True) == 0.99 for prior in lowered)
    assert _bkt(1.0, True) == 0.99
    # Below the clamp a correct answer strictly raises p_known; at 0.99 it stays.
    assert raised == [prior for prior in FINE_GRID if prior < 0.99]
    assert _bkt(0.99, True) == 0.99


def test_from_the_default_prior_a_wrong_answer_never_raises_p_known():
    """Neither region is reachable from the shipped initial mastery with the defaults.

    Starting at 0.3, p_known stays at or above the fixed point and at or below 0.99, so along
    these sequences a wrong answer never raises it and a correct answer never lowers it.
    """
    initial = Settings.model_fields["student_initial_mastery"].default
    assert initial == 0.3
    rng = random.Random(SEED)

    for _ in range(300):
        p_known = initial
        for _, correct in _answers(rng, ("c",), 40):
            previous, p_known = p_known, _bkt(p_known, correct)
            assert FIXED_POINT - TOLERANCE <= p_known <= 0.99
            if correct:
                assert p_known >= previous
            else:
                assert p_known <= previous + TOLERANCE


# ---------------------------------------------------------------------------
# (a) to (d): the update, for the defaults and every plausible parameter triple
# ---------------------------------------------------------------------------


def test_wrong_answer_never_raises_the_posterior():
    """(a) With transit 0 the function returns the posterior, clamped to [0.01, 0.99].

    The bound is max(prior, 0.01) because the clamp lifts a posterior below 0.01 to 0.01.
    """
    for prior in FINE_GRID:
        assert _bkt(prior, False, transit=0.0) <= max(prior, 0.01)

    for _, slip, guess in PLAUSIBLE:
        for prior in PRIORS:
            assert _bkt(prior, False, 0.0, slip, guess) <= max(prior, 0.01), (prior, slip, guess)


def test_wrong_answer_gains_no_more_than_the_learning_step():
    """(a) seen after the learning step: p_known <= prior + (1 - prior) * transit.

    For every prior; the lower clamp again accounts for the 0.01 in the bound.
    """
    for transit, slip, guess in PLAUSIBLE:
        for prior in PRIORS:
            p_known = _bkt(prior, False, transit, slip, guess)
            bound = max(0.01, prior + (1 - prior) * transit)

            assert p_known <= bound, (prior, transit, slip, guess)


def test_wrong_answer_never_leaves_p_known_above_the_prior_and_the_fixed_point():
    """(b) p_known after a wrong answer is at most max(prior, fixed point), for every prior."""
    for prior in FINE_GRID:
        assert _bkt(prior, False) <= max(prior, FIXED_POINT) + TOLERANCE

    for transit, slip, guess in PLAUSIBLE:
        fixed_point = _wrong_answer_fixed_point(transit, slip, guess)
        for prior in PRIORS:
            p_known = _bkt(prior, False, transit, slip, guess)

            assert p_known <= max(prior, fixed_point) + TOLERANCE, (prior, transit, slip, guess)


def test_correct_answer_never_lowers_p_known_inside_the_clamp():
    """(c) For priors in [0.01, 0.99]."""
    for prior in filter(_in_clamp, FINE_GRID):
        assert _bkt(prior, True) >= prior

    for transit, slip, guess in PLAUSIBLE:
        for prior in filter(_in_clamp, PRIORS):
            assert _bkt(prior, True, transit, slip, guess) >= prior, (prior, transit, slip, guess)


def test_result_always_lies_in_the_clamp():
    """(d) For every prior in [0, 1], stored values outside the clamp included."""
    for prior in FINE_GRID:
        for correct in (True, False):
            assert 0.01 <= _bkt(prior, correct) <= 0.99

    for transit, slip, guess in PLAUSIBLE:
        for prior in PRIORS:
            for correct in (True, False):
                p_known = _bkt(prior, correct, transit, slip, guess)

                assert 0.01 <= p_known <= 0.99, (prior, correct, transit, slip, guess)


def test_wrong_answer_is_never_better_than_a_correct_one():
    for transit, slip, guess in PLAUSIBLE:
        for prior in PRIORS:
            wrong = _bkt(prior, False, transit, slip, guess)
            correct = _bkt(prior, True, transit, slip, guess)

            assert wrong <= correct, (prior, transit, slip, guess)


def test_slip_and_guess_are_not_interchangeable():
    """With guess 0 a correct answer is proof; with slip 0 a wrong answer is disproof."""
    for prior in filter(_in_clamp, PRIORS):
        # Nobody guesses: a correct answer means the concept is known.
        assert _bkt(prior, True, 0.1, 0.1, 0.0) == 0.99
        assert _bkt(prior, False, 0.1, 0.1, 0.0) < 0.99
        # Nobody slips: a wrong answer means it is not known; only the learning step remains.
        assert _bkt(prior, False, 0.1, 0.0, 0.25) == pytest.approx(0.1, abs=TOLERANCE)
        assert _bkt(prior, True, 0.1, 0.0, 0.25) > 0.1


def test_implausible_parameters_invert_the_evidence():
    """Why (g) matters: the models do not validate the parameters, and (a) and (c) need them.

    With slip 0.6 and guess 0.6 a learner who knows the concept is right less often (0.4)
    than one who does not (0.6), so a correct answer lowers p_known and a wrong one raises it.
    """
    assert _bkt(0.5, True, 0.1, 0.6, 0.6) == pytest.approx(0.46, abs=TOLERANCE)
    assert _bkt(0.5, False, 0.1, 0.6, 0.6) == pytest.approx(0.64, abs=TOLERANCE)


def test_update_starts_from_mastery_level_when_p_known_is_unset():
    for prior in PRIORS:
        for correct in (True, False):
            record = ConceptMastery(concept_name="c", mastery_level=prior, bkt_p_known=None)

            assert StudentService._update_mastery_bkt(record, correct) == _bkt(prior, correct)


# ---------------------------------------------------------------------------
# (e), (f): what the service stores after an answer
# ---------------------------------------------------------------------------

CONCEPTS = ("Fresh", "Stored", "No learning")


def _seeded_profile(rng: random.Random) -> StudentProfile:
    """A learner with two stored concepts; "Fresh" gets its record on the first answer.

    "Stored" has a mastery level anywhere in [0, 1] and no p_known yet. "No learning" has
    transit 0: an update returns at least its transit, so only a stored transit below 0.1 lets
    p_known fall under the 0.1 mastery floor.
    """
    return StudentProfile(
        student_id="seeded",
        mastery_map={
            "Stored": ConceptMastery(concept_name="Stored", mastery_level=rng.random()),
            "No learning": ConceptMastery(concept_name="No learning", bkt_p_transit=0.0),
        },
    )


def test_mastery_level_is_p_known_with_a_floor_of_0_1(monkeypatch):
    """(e) Checked after every answer of seeded sequences, with BKT on."""
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = _service_without_storage()
    rng = random.Random(SEED)
    floor_applied = floor_not_applied = 0

    for _ in range(100):
        profile = _seeded_profile(rng)
        for concept, correct in _answers(rng, CONCEPTS, 40):
            service._apply_answer(profile, concept, correct)
            record = profile.mastery_map[concept]

            assert record.bkt_p_known is not None
            assert 0.01 <= record.bkt_p_known <= 0.99
            assert record.mastery_level == max(0.1, record.bkt_p_known)
            floor_applied += record.bkt_p_known < 0.1
            floor_not_applied += record.bkt_p_known >= 0.1

    # Both sides of the floor were exercised.
    assert floor_applied > 100
    assert floor_not_applied > 100


def test_mastery_floor_applies_when_p_known_falls_below_it(monkeypatch):
    """(e) With transit 0, two wrong answers take p_known from 0.3 to the 0.01 clamp."""
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    service = _service_without_storage()
    record = ConceptMastery(concept_name="c", mastery_level=0.3, bkt_p_transit=0.0)
    profile = StudentProfile(mastery_map={"c": record})

    service._apply_answer(profile, "c", correct=False)
    assert record.bkt_p_known == pytest.approx(2 / 37, abs=TOLERANCE)
    assert record.mastery_level == 0.1

    service._apply_answer(profile, "c", correct=False)
    assert record.bkt_p_known == 0.01
    assert record.mastery_level == 0.1


def test_default_transit_keeps_p_known_at_or_above_the_mastery_floor():
    """With transit 0.1 every update returns at least 0.1, so the floor changes nothing."""
    assert min(_bkt(prior, correct) for prior in FINE_GRID for correct in (True, False)) == 0.1


@pytest.mark.parametrize("bkt_enabled", [True, False], ids=["bkt", "linear"])
def test_mastery_floor_and_cap_hold_in_both_update_modes(monkeypatch, bkt_enabled):
    monkeypatch.setattr(settings, "student_bkt_enabled", bkt_enabled)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = _service_without_storage()
    rng = random.Random(SEED)
    at_floor = at_cap = 0

    for _ in range(100):
        profile = _seeded_profile(rng)
        for concept, correct in _answers(rng, CONCEPTS, 40):
            service._apply_answer(profile, concept, correct)
            level = profile.mastery_map[concept].mastery_level

            assert 0.1 <= level <= 1.0
            at_floor += level == 0.1
            at_cap += level == (0.99 if bkt_enabled else 1.0)

    assert at_floor > 0
    assert at_cap > 0


def test_linear_update_stops_at_the_floor_and_the_cap(monkeypatch):
    monkeypatch.setattr(settings, "student_bkt_enabled", False)
    service = _service_without_storage()
    profile = StudentProfile(
        mastery_map={
            "low": ConceptMastery(concept_name="low", mastery_level=0.15),
            "high": ConceptMastery(concept_name="high", mastery_level=0.95),
        }
    )

    service._apply_answer(profile, "low", correct=False)  # 0.15 - 0.10 is below the floor
    service._apply_answer(profile, "high", correct=True)  # 0.95 + 0.15 is above the cap

    assert profile.mastery_map["low"].mastery_level == 0.1
    assert profile.mastery_map["high"].mastery_level == 1.0


@pytest.mark.parametrize("bkt_enabled", [True, False], ids=["bkt", "linear"])
def test_overall_ability_is_the_mean_of_the_tracked_mastery_levels(monkeypatch, bkt_enabled):
    """(f) Checked after every answer of seeded sequences, in both update modes."""
    monkeypatch.setattr(settings, "student_bkt_enabled", bkt_enabled)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = _service_without_storage()
    rng = random.Random(SEED)
    below_the_maximum = 0

    for _ in range(100):
        profile = _seeded_profile(rng)
        for concept, correct in _answers(rng, CONCEPTS, 40):
            service._apply_answer(profile, concept, correct)
            levels = [record.mastery_level for record in profile.mastery_map.values()]

            assert profile.overall_ability == pytest.approx(fmean(levels), abs=TOLERANCE)
            below_the_maximum += profile.overall_ability < max(levels) - 0.01

    assert below_the_maximum > 100  # the mean was not the maximum by coincidence


def test_overall_ability_counts_tracked_concepts_only(monkeypatch):
    """(f) After a first answer on a third concept the mean is over the three tracked levels."""
    monkeypatch.setattr(settings, "student_bkt_enabled", True)
    monkeypatch.setattr(settings, "student_initial_mastery", 0.3)
    service = _service_without_storage()
    profile = StudentProfile(
        mastery_map={
            "a": ConceptMastery(concept_name="a", mastery_level=0.9),
            "b": ConceptMastery(concept_name="b", mastery_level=0.2),
        }
    )

    service._apply_answer(profile, "c", correct=True)

    assert profile.mastery_map["c"].mastery_level == pytest.approx(115 / 178, abs=TOLERANCE)
    assert profile.overall_ability == pytest.approx((0.9 + 0.2 + 115 / 178) / 3, abs=TOLERANCE)
