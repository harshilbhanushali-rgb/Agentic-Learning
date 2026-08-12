"""Tests for calibration/trial_skills.py -- the pure helpers of the skills-vocabulary test.

Pre-registration: docs/superpowers/specs/2026-08-13-layer-c-skills-vocabulary-design.md

Hand-built orthogonal unit vectors throughout, never the embedding model -- the
test_layer_b_assignment precedent. These assert the RULE, so they keep meaning at any
embedding version.

The helpers under test are the ones that decide the verdict, so they are the ones that must
not be wrong: the power bounds (derived, never chosen), the window between the two curves,
the judge's blinded null, and the order-permutation check. The Gemma and embedding paths are
exercised by the pilot run, not here.
"""
from __future__ import annotations

import numpy as np
import pytest

from calibration import trial_skills as ts


def _unit(*components) -> np.ndarray:
    v = np.asarray(components, dtype=np.float32)
    return v / np.linalg.norm(v)


_A, _B, _C = _unit(1, 0, 0), _unit(0, 1, 0), _unit(0, 0, 1)
_A_NEAR = _unit(0.98, 0.2, 0)


# --- reading the population -------------------------------------------------------------

def _payload(*milestones) -> dict:
    return {"arms": {"arm0_baseline": {"rubrics": {
        "scenario_one": {"milestones": list(milestones)}}}}}


def test_descriptions_are_read_with_their_scenario_attached():
    """scenario_key is what scenario_span is computed from later. Losing it here would
    make every group look like it spans one scenario -- the exact failure the test is
    trying to detect."""
    got = ts.extract_descriptions(_payload({"description": "Ask an open question."}),
                                  "arm0_baseline")

    assert len(got) == 1
    assert got[0]["scenario_key"] == "scenario_one"
    assert got[0]["description"] == "Ask an open question."


def test_milestones_without_a_description_are_dropped_not_blanked():
    """A blank string embeds to a real vector and would join some group on noise."""
    got = ts.extract_descriptions(
        _payload({"description": "Real."}, {"description": ""}, {"label": "no desc"}),
        "arm0_baseline")

    assert [d["description"] for d in got] == ["Real."]


def test_mechanics_milestones_are_flagged_for_the_positive_control():
    """The abstraction prompt has an explicit "call mechanics" escape hatch, so these
    SHOULD collapse into one group. If they do not, the pass is not abstracting."""
    got = ts.extract_descriptions(
        _payload({"description": "Hand over the turn.", "not_coachable_category": "mechanics"},
                 {"description": "Explain the API."}),
        "arm0_baseline")

    assert [d["is_mechanics"] for d in got] == [True, False]


def test_reading_an_absent_arm_is_empty_rather_than_a_crash():
    assert ts.extract_descriptions(_payload({"description": "x"}), "nope") == []


# --- the power bounds, derived rather than chosen ----------------------------------------

def test_every_standard_derives_its_member_floor_from_measured_attempts():
    """No target count anywhere. The floor follows from 889 attempts over 405 milestones
    and the noise floor measured on this exact metric; it is not a chosen number."""
    floors = {s["key"]: ts.min_members(s) for s in ts.POWER_STANDARDS}

    assert floors == {"noise_band": 38, "half_change": 23,
                      "full_change": 12, "rank_d05": 24}


def test_the_standards_agree_with_their_own_k_bounds():
    """Both framings must describe the same requirement: min_members * max_k should land
    near the 405-item corpus. A drift here means one table was edited and the other was
    not."""
    for s in ts.POWER_STANDARDS:
        assert 0.75 <= ts.min_members(s) * s["max_k"] / 405 <= 1.35, s["key"]


def test_a_threshold_fails_a_standard_when_the_median_skill_is_too_thin():
    """K is an optimistic bound; the median skill is the operative test. A run can hit the
    skill count while the median skill still pools nothing."""
    row = {"threshold": 0.8, "n_skills": 10, "median_size": 3.0}
    standard = {"key": "noise_band", "min_obs": 83, "max_k": 11}

    assert not ts.meets_standard(row, standard)


def test_a_threshold_passes_only_when_both_the_count_and_the_median_hold():
    standard = {"key": "full_change", "min_obs": 25, "max_k": 35}

    assert ts.meets_standard({"threshold": 0.8, "n_skills": 30, "median_size": 12.0}, standard)
    assert not ts.meets_standard({"threshold": 0.8, "n_skills": 40, "median_size": 12.0}, standard)


# --- choosing where to spend judge calls --------------------------------------------------

def test_each_bound_is_judged_at_the_finest_threshold_that_still_meets_it():
    """Finer clustering means higher validity, so the largest threshold satisfying a bound
    is that bound's best shot. Judging a coarser one would understate it."""
    rows = [{"threshold": 0.60, "n_skills": 5, "median_size": 40.0},
            {"threshold": 0.70, "n_skills": 11, "median_size": 38.0},
            {"threshold": 0.80, "n_skills": 40, "median_size": 10.0}]

    picked = ts.select_judge_thresholds(rows)

    assert 0.70 in picked


def test_the_finest_threshold_is_always_judged_as_a_positive_control():
    """Validity should be near 1.0 where almost nothing merged. If it is not, the judge is
    broken and no other point on the curve can be believed."""
    rows = [{"threshold": 0.60, "n_skills": 5, "median_size": 40.0},
            {"threshold": 0.95, "n_skills": 300, "median_size": 1.0}]

    assert 0.95 in ts.select_judge_thresholds(rows)


def test_an_unreachable_bound_contributes_no_threshold_rather_than_a_wrong_one():
    rows = [{"threshold": 0.95, "n_skills": 300, "median_size": 1.0}]

    picked = ts.select_judge_thresholds(rows)

    assert picked == [0.95]


def test_judge_thresholds_are_deduplicated():
    """Several bounds usually resolve to one threshold. Paying for the same judgement four
    times is the kind of silent waste --limit-style shortcuts were meant to avoid."""
    rows = [{"threshold": 0.70, "n_skills": 10, "median_size": 40.0}]

    assert ts.select_judge_thresholds(rows) == [0.70]


# --- the window ----------------------------------------------------------------------------

def test_the_window_opens_only_when_a_threshold_clears_both_curves():
    rows = [{"threshold": 0.70, "n_skills": 11, "median_size": 38.0}]
    validity = {0.70: 0.9}

    result = ts.evaluate_window(rows, validity, v_min=0.8)

    assert result["noise_band"]["passed"] is True


def test_a_valid_but_too_fine_threshold_does_not_open_the_window():
    """The lower bound doing its job: groups may be perfectly coherent and still pool too
    few observations to carry an axis."""
    rows = [{"threshold": 0.95, "n_skills": 300, "median_size": 1.0}]
    validity = {0.95: 1.0}

    result = ts.evaluate_window(rows, validity, v_min=0.8)

    assert all(not r["passed"] for r in result.values())


def test_a_coarse_enough_threshold_that_fused_moves_does_not_open_the_window():
    """The upper bound doing its job -- the counterweight the sweep alone does not have.
    Without it, coarsening always produces a pass."""
    rows = [{"threshold": 0.50, "n_skills": 4, "median_size": 100.0}]
    validity = {0.50: 0.3}

    result = ts.evaluate_window(rows, validity, v_min=0.8)

    assert all(not r["passed"] for r in result.values())


def test_an_unjudged_threshold_never_counts_as_a_pass():
    """Absent validity means unmeasured, never assumed good."""
    rows = [{"threshold": 0.70, "n_skills": 11, "median_size": 38.0}]

    result = ts.evaluate_window(rows, {}, v_min=0.8)

    assert all(not r["passed"] for r in result.values())


# --- the judge's blinded null ---------------------------------------------------------------

def test_null_pairs_are_drawn_from_the_least_similar_behaviours():
    """A judge calling maximally dissimilar behaviours the same move is broken. Anything
    less extreme would be genuinely ambiguous and could not falsify anything."""
    vectors = np.stack([_A, _A_NEAR, _B, _C])

    pairs = ts.null_pairs(vectors, n=1, seed=1)

    i, j = pairs[0]
    assert float(vectors[i] @ vectors[j]) < 0.5


def test_null_pairs_never_pair_an_item_with_itself():
    pairs = ts.null_pairs(np.stack([_A, _B, _C]), n=3, seed=1)

    assert all(i != j for i, j in pairs)


def test_null_pairs_are_reproducible_for_a_seed():
    vectors = np.stack([_A, _A_NEAR, _B, _C])

    assert ts.null_pairs(vectors, n=2, seed=7) == ts.null_pairs(vectors, n=2, seed=7)


def test_too_few_items_yields_no_null_rather_than_a_degenerate_pair():
    assert ts.null_pairs(np.stack([_A]), n=3, seed=1) == []


def test_null_groups_match_the_sizes_they_are_given():
    """Blinding: if every null were a 2-item pair while real groups carried up to 8, the
    judge could identify the nulls by size alone and the null would measure nothing."""
    vectors = np.stack([_A, _A_NEAR, _B, _C])

    got = ts.null_groups(vectors, [2, 3], seed=1)

    assert [len(g) for g in got] == [2, 3]


def test_null_groups_hold_mutually_dissimilar_behaviours():
    vectors = np.stack([_A, _A_NEAR, _B, _C])

    members = ts.null_groups(vectors, [3], seed=1)[0]

    for a in members:
        for b in members:
            if a != b:
                assert float(vectors[a] @ vectors[b]) < 0.5


def test_null_groups_are_reproducible_and_never_exceed_the_population():
    vectors = np.stack([_A, _B])

    assert ts.null_groups(vectors, [5], seed=2) == ts.null_groups(vectors, [5], seed=2)
    assert len(ts.null_groups(vectors, [5], seed=2)[0]) == 2


def test_the_null_verdict_requires_rejecting_most_disguised_pairs():
    """Pre-registered at 0.80. Below it the counterweight is void and the run reports that
    instead of a granularity -- two judges have already failed their own nulls here."""
    assert ts.null_passed({"n0": "fused", "n1": "fused", "n2": "fused",
                           "n3": "fused", "n4": "same_move"}, min_reject=0.8)
    assert not ts.null_passed({"n0": "same_move", "n1": "fused"}, min_reject=0.8)


def test_an_empty_null_fails_rather_than_passing_vacuously():
    """An all() over nothing is True. That would silently certify a judge that was never
    tested."""
    assert not ts.null_passed({}, min_reject=0.8)


# --- order permutation ------------------------------------------------------------------------

def test_a_stable_vocabulary_reports_the_same_count_under_reshuffling():
    """cluster_behaviours is greedy and order-dependent by its own docstring. A vocabulary
    that reshuffles cannot carry a profile however well it groups once."""
    vectors = np.stack([_A, _A_NEAR, _B, _C])

    counts = ts.permutation_counts(vectors, threshold=0.8, n_shuffles=5, seed=3)

    assert len(counts) == 5
    assert len(set(counts)) == 1


def test_permutation_drift_is_reported_as_a_fraction_of_the_count():
    assert ts.permutation_drift([10, 10, 10], baseline=10) == 0.0
    assert ts.permutation_drift([12, 8, 10], baseline=10) == pytest.approx(0.2)


def test_permutation_drift_of_an_empty_run_is_zero_not_a_division_error():
    assert ts.permutation_drift([], baseline=0) == 0.0
