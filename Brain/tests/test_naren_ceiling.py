"""Tests for calibration/score_naren_ceiling.py's sampling and holdout logic.

score_milestones_batch is called unchanged and is not retested here. What IS tested is
everything a silent bug would render an overnight Gemma run meaningless: which responses
enter which arm, what the benchmark holdout removes, and that arm B's pairings are really
unrelated.

Deliberately imports no torch. score_naren_ceiling keeps preprocessing.embedder,
shared.scenario_vectors and ego_trap.rubric_lookup as lazy in-function imports precisely so
this file can exercise the pure helpers on a 16GB box where a torch import can fail with
[WinError 1455].
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from calibration import score_naren_ceiling as snc


def _row(pair_id, call_id, filename=None, text=None):
    return {"pair_id": pair_id, "call_id": call_id,
            "call_filename": filename or f"call{call_id}.txt",
            "response_text": text or f"response {pair_id}"}


# --- weighted score -------------------------------------------------------------------

def test_weighted_matches_the_pipeline_definition():
    assert snc.weighted(2, 4, 8) == pytest.approx((2 + 0.5 * 4) / 8)


def test_weighted_of_zero_attempts_is_zero_not_a_crash():
    # A milestone nobody attempted has no score; dividing would kill a whole report.
    assert snc.weighted(0, 0, 0) == 0.0


# --- arm A3: the call-level derivation holdout ----------------------------------------

def test_a3_excludes_a_secondary_row_whose_sibling_holds_the_scalar_label():
    """The case the design was measured on and the reason A3 exists.

    Pair 2 carries the scenario only as a secondary label, so a response-level holdout
    would admit it -- but pair 1 from the SAME call holds the scalar label and therefore
    fed the scenario's Layer C clause pool. The call is contaminated, so pair 2 is out.
    """
    secondary = [_row(2, call_id=10), _row(3, call_id=11)]
    primary_calls = {10}
    kept = snc.a3_eligible(secondary, primary_calls)
    assert [r["pair_id"] for r in kept] == [3]


def test_a3_keeps_everything_when_no_call_contributed_a_primary_pair():
    secondary = [_row(2, 10), _row(3, 11)]
    assert len(snc.a3_eligible(secondary, set())) == 2


def test_a3_can_legitimately_empty_a_scenario():
    # Measured: client_value_expectation_discovery has zero A3-eligible pairs. An empty
    # stratum must be a normal return, not an exception.
    assert snc.a3_eligible([_row(2, 10)], {10}) == []


# --- benchmark holdout (leak 1) --------------------------------------------------------

def test_hold_out_removes_every_row_from_the_call_not_just_the_row_under_test():
    pool = [_row(1, 10), _row(2, 10), _row(3, 11)]
    kept = snc.hold_out(pool, "call10.txt")
    assert [r["pair_id"] for r in kept] == [3]


def test_pick_benchmark_cannot_return_the_response_under_test():
    under_test = _row(1, 10, text="THE ANSWER KEY")
    pool = [under_test, _row(2, 11), _row(3, 12)]
    picked = snc.pick_benchmark(pool, under_test["call_filename"])
    assert "THE ANSWER KEY" not in [r["response_text"] for r in picked]


def test_pick_benchmark_takes_the_top_two_in_ranked_order():
    pool = [_row(i, i) for i in (1, 2, 3, 4)]  # already ranked by caller
    picked = snc.pick_benchmark(pool, "call99.txt", limit=2)
    assert [r["pair_id"] for r in picked] == [1, 2]


@pytest.mark.parametrize("size", [0, 1, 2])
def test_pick_benchmark_survives_a_degenerate_pool(size):
    """Pins the dry_run_ego_trap harness bug: a tiny pool must not be read for
    scenario_similarity, which rank_benchmark_responses omits on its short-circuit."""
    pool = [_row(i, i) for i in range(size)]
    picked = snc.pick_benchmark(pool, "absent.txt")
    assert len(picked) == min(size, snc._BENCHMARK_EXAMPLES)
    assert all("scenario_similarity" not in r for r in picked)


# --- sampling --------------------------------------------------------------------------

def test_take_sample_returns_the_whole_pool_when_smaller_than_n():
    pool = [_row(i, i) for i in range(3)]
    assert len(snc.take_sample(pool, 8, random.Random(1))) == 3


def test_take_sample_never_repeats_a_row():
    pool = [_row(i, i) for i in range(20)]
    got = snc.take_sample(pool, 8, random.Random(1))
    assert len({r["pair_id"] for r in got}) == 8


def test_take_sample_is_reproducible_from_the_seed():
    pool = [_row(i, i) for i in range(20)]
    a = snc.take_sample(pool, 8, random.Random(snc._DEFAULT_SEED))
    b = snc.take_sample(pool, 8, random.Random(snc._DEFAULT_SEED))
    assert [r["pair_id"] for r in a] == [r["pair_id"] for r in b]


# --- arm B pairings --------------------------------------------------------------------

def _sim(n, pairs=()):
    """Identity diagonal, 0.1 elsewhere, with named pairs forced high."""
    m = np.full((n, n), 0.1)
    np.fill_diagonal(m, 1.0)
    for i, j, v in pairs:
        m[i][j] = m[j][i] = v
    return m


def test_derange_never_pairs_a_scenario_with_itself():
    keys = list("abcd")
    mapping, method = snc.derange(keys, _sim(4), 0.85, random.Random(7))
    assert method == "derangement"
    assert all(mapping[k] != k for k in keys)


def test_derange_is_a_permutation_so_each_rubric_gets_equal_attempts():
    keys = list("abcde")
    mapping, _ = snc.derange(keys, _sim(5), 0.85, random.Random(7))
    assert sorted(mapping.values()) == sorted(keys)


def test_derange_rejects_a_pairing_above_the_cosine_threshold():
    # a and b are near-duplicate scenarios; pairing them would not be a control at all.
    keys = list("abcd")
    sim = _sim(4, pairs=[(0, 1, 0.93)])
    mapping, _ = snc.derange(keys, sim, 0.85, random.Random(3))
    assert mapping["a"] != "b" and mapping["b"] != "a"


def test_derange_reports_when_no_valid_partner_exists_instead_of_pairing_anyway():
    keys = list("ab")
    sim = _sim(2, pairs=[(0, 1, 0.99)])
    mapping, method = snc.derange(keys, sim, 0.85, random.Random(3), max_tries=20)
    assert mapping is None
    assert method.startswith("no_valid_partner")


def test_derange_is_reproducible_from_the_seed():
    keys = list("abcdef")
    a, _ = snc.derange(keys, _sim(6), 0.85, random.Random(snc._DEFAULT_SEED))
    b, _ = snc.derange(keys, _sim(6), 0.85, random.Random(snc._DEFAULT_SEED))
    assert a == b


# --- aggregation ----------------------------------------------------------------------

def _rec(rubric_id, mid, verdict, skey="s"):
    return {"rubric_id": rubric_id, "milestone_id": mid, "verdict": verdict,
            "scenario_key": skey}


def test_aggregate_counts_hits_partials_and_attempts_per_milestone():
    recs = [_rec(1, "M1", "full_hit"), _rec(1, "M1", "partial_hit"),
            _rec(1, "M1", "miss"), _rec(1, "M2", "miss")]
    got = snc.aggregate(recs)
    assert got[(1, "M1")] == {"attempts": 3, "hits": 1, "partial": 1, "scenario_key": "s"}
    assert got[(1, "M2")]["attempts"] == 1


def test_aggregate_keeps_the_same_milestone_id_separate_across_rubrics():
    # milestone_id is a positional array index, so "M1" means different criteria in
    # different rubrics. Collapsing them is the bug milestone_ids' docstring warns about.
    got = snc.aggregate([_rec(1, "M1", "full_hit"), _rec(2, "M1", "miss")])
    assert len(got) == 2


def test_arm_totals_weighted_matches_the_counters():
    recs = [_rec(1, "M1", "full_hit"), _rec(1, "M2", "partial_hit"),
            _rec(1, "M3", "miss"), _rec(1, "M4", "miss")]
    t = snc.arm_totals(recs)
    assert (t["attempts"], t["hits"], t["partial"]) == (4, 1, 1)
    assert t["W"] == pytest.approx((1 + 0.5) / 4)


# --- the indictment list --------------------------------------------------------------

def test_unhittable_requires_zero_partials_not_just_zero_full_hits():
    """A milestone scoring partials is being APPROACHED, so 'nobody can satisfy this' is
    not available for it -- the condition is semantic, not a noise-floor concession."""
    counters = {
        ("a", "M1"): {"attempts": 8, "hits": 0, "partial": 0, "scenario_key": "a"},
        ("b", "M1"): {"attempts": 8, "hits": 0, "partial": 3, "scenario_key": "b"},
    }
    assert snc.unhittable(counters) == [("a", "M1")]


def test_unhittable_ignores_milestones_with_too_few_attempts():
    counters = {("a", "M1"): {"attempts": 2, "hits": 0, "partial": 0, "scenario_key": "a"}}
    assert snc.unhittable(counters, min_attempts=6) == []


def test_unhittable_orders_by_attempts_so_the_best_evidenced_indictment_comes_first():
    counters = {
        ("a", "M1"): {"attempts": 7, "hits": 0, "partial": 0, "scenario_key": "a"},
        ("b", "M1"): {"attempts": 9, "hits": 0, "partial": 0, "scenario_key": "b"},
    }
    assert snc.unhittable(counters)[0] == ("b", "M1")


# --- pre-registered thresholds --------------------------------------------------------

def test_thresholds_are_the_values_pre_registered_in_the_design_spec():
    """These are load-bearing: the spec fixes them before data is seen so they cannot be
    moved afterwards. A change here should be a deliberate, argued edit -- not drift."""
    assert (snc._T_WORKS, snc._T_BROKEN, snc._T_INSTRUMENT) == (0.50, 0.20, 0.5)
    assert snc._MIN_ATTEMPTS_TO_INDICT == 6
