"""Unit tests for the 2026-08-17 Layer C trial's pure functions (lcfr_common).

Fixtures are SKEWED on purpose -- lesson #8 of the Layer B trial: a null test whose fixture
is symmetric can be passed by a wrong implementation identically. Each test states the
wrong implementation it would catch.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from calibration.lcfr_common import (
    permute_destinations, keep_rank, keep_margin, keep_demean, keep_csls,
    r_neighbourhood, rule_mask, rescue_assign, placebo_assign, unit_rows)


# ---------------------------------------------------------------------------------------
# permutation
# ---------------------------------------------------------------------------------------

def test_permutation_preserves_multiset_on_skewed_keys():
    # skewed: one key holds 80% of the pairs, like the real absorption profile
    keys = ["big"] * 80 + ["mid"] * 15 + ["tiny"] * 5
    perm = permute_destinations(list(keys), random.Random(7))
    assert sorted(perm) == sorted(keys)
    assert perm != keys  # astronomically unlikely to be identity at n=100


def test_permutation_is_seed_deterministic():
    keys = [f"k{i}" for i in range(50)]
    a = permute_destinations(list(keys), random.Random(42))
    b = permute_destinations(list(keys), random.Random(42))
    assert a == b


# ---------------------------------------------------------------------------------------
# filter rules -- 3 clauses x 4 scenarios, hand-built, own = column 0
# ---------------------------------------------------------------------------------------

SIMS = np.array([
    [0.70, 0.50, 0.40, 0.30],   # clause 0: own is clear top-1
    [0.55, 0.60, 0.35, 0.20],   # clause 1: own is rank 2
    [0.45, 0.60, 0.55, 0.50],   # clause 2: own is rank 4 (last)
], dtype=np.float32)


def test_keep_rank_counts_strict_betters():
    # wrong impl using >= (own beats itself) would shift every rank by one
    assert keep_rank(SIMS, 0, 1).tolist() == [True, False, False]
    assert keep_rank(SIMS, 0, 2).tolist() == [True, True, False]
    assert keep_rank(SIMS, 0, 4).tolist() == [True, True, True]


def test_keep_rank_tie_resolves_toward_keeping():
    sims = np.array([[0.5, 0.5, 0.3]], dtype=np.float32)
    assert keep_rank(sims, 0, 1).tolist() == [True]  # tie is not "strictly better"


def test_keep_margin_excludes_own_from_max():
    # wrong impl taking max over ALL columns would compare own to itself and keep everything
    assert keep_margin(SIMS, 0, 1.00).tolist() == [True, False, False]
    assert keep_margin(SIMS, 0, 0.90).tolist() == [True, True, False]
    # clause 2: own 0.45 vs max_other 0.60 -> 0.75 ratio; kept only at very loose margins
    assert keep_margin(SIMS, 0, 0.70).tolist() == [True, True, True]


def test_keep_demean_uses_mean_of_others():
    # clause 0: 0.70 - mean(0.50,0.40,0.30)=0.40 -> +0.30
    # clause 1: 0.55 - mean(0.60,0.35,0.20)=0.3833 -> +0.1667
    # clause 2: 0.45 - 0.55 -> -0.10
    assert keep_demean(SIMS, 0, 0.00).tolist() == [True, True, False]
    assert keep_demean(SIMS, 0, 0.20).tolist() == [True, False, False]


def test_r_neighbourhood_top_k_mean_and_clamp():
    sims = np.array([[0.1, 0.9, 0.5, 0.7]], dtype=np.float32)
    assert r_neighbourhood(sims, 2)[0] == pytest.approx(0.8)      # mean of 0.9, 0.7
    assert r_neighbourhood(sims, 99)[0] == pytest.approx(0.55)    # clamped to row width


def test_csls_demotes_a_hub_scenario():
    """Scenario 1 is a HUB: every clause scores ~0.9 against it, so raw rank-1 always
    prefers it. CSLS subtracts the scenario-side offset ry and the own scenario wins.
    A wrong implementation that drops the ry term reproduces the raw ranking and fails."""
    sims = np.array([
        [0.70, 0.90, 0.30],
        [0.65, 0.88, 0.25],
    ], dtype=np.float32)
    rx = r_neighbourhood(sims, 2)
    ry = np.array([0.40, 0.89, 0.20], dtype=np.float32)  # hub's neighbourhood is dense
    assert keep_rank(sims, 0, 1).tolist() == [False, False]          # raw: hub wins
    assert keep_csls(sims, 0, 1, rx, ry).tolist() == [True, True]    # corrected: own wins
    # without the correction the same call must NOT keep them -- pins that ry is live
    assert keep_csls(sims, 0, 1, rx, np.zeros(3, np.float32)).tolist() == [False, False]


def test_rule_mask_dispatch_matches_direct_calls():
    assert (rule_mask("rank", 2, SIMS, 0) == keep_rank(SIMS, 0, 2)).all()
    assert (rule_mask("margin", 0.9, SIMS, 0) == keep_margin(SIMS, 0, 0.9)).all()
    assert (rule_mask("demean", 0.0, SIMS, 0) == keep_demean(SIMS, 0, 0.0)).all()
    with pytest.raises(ValueError):
        rule_mask("nope", 1, SIMS, 0)


# ---------------------------------------------------------------------------------------
# rescue -- skewed geometry: one tight cluster, one loose, noise at known angles
# ---------------------------------------------------------------------------------------

def _vec(angle_deg: float) -> np.ndarray:
    a = np.deg2rad(angle_deg)
    return np.array([np.cos(a), np.sin(a)], dtype=np.float32)


def test_rescue_admits_by_p25_of_member_band_not_mean():
    # cluster A members at 0/4/8/40 degrees: the 40-degree straggler drags p25 DOWN far
    # less than it drags the mean; a wrong impl thresholding on the MEAN member cosine
    # would reject the 20-degree noise clause that p25 admits.
    members = {0: np.stack([_vec(0), _vec(4), _vec(8), _vec(40)])}
    cent = unit_rows(members[0]).mean(axis=0)
    cent = cent / np.linalg.norm(cent)
    mem_cos = unit_rows(members[0]) @ cent
    p25, mean = np.percentile(mem_cos, 25), mem_cos.mean()
    probe = _vec(30)  # ~17 deg from the ~13-deg centroid: between p25 and the mean
    cos_probe = float((unit_rows(probe[None]) @ cent)[0])
    assert p25 < cos_probe < mean  # geometry precondition: the two rules disagree here
    admitted, thr = rescue_assign(probe[None, :], members)
    assert admitted[0] == [0]
    assert thr[0] == pytest.approx(float(p25), abs=1e-6)


def test_rescue_rejects_far_noise_and_routes_to_nearest():
    members = {0: np.stack([_vec(0), _vec(5), _vec(10)]),
               1: np.stack([_vec(90), _vec(95), _vec(100)])}
    noise = np.stack([_vec(7), _vec(93), _vec(200)])
    admitted, _ = rescue_assign(noise, members)
    assert admitted[0] == [0]      # near cluster 0
    assert admitted[1] == [1]      # near cluster 1
    # _vec(200) is far from both centroids -> admitted nowhere
    assert 2 not in admitted[0] and 2 not in admitted[1]


def test_rescue_empty_noise_or_clusters():
    admitted, thr = rescue_assign(np.empty((0, 2), np.float32),
                                  {0: np.stack([_vec(0), _vec(5)])})
    assert admitted == {0: []} and thr == {}
    admitted, thr = rescue_assign(np.stack([_vec(0)]), {})
    assert admitted == {} and thr == {}


def test_placebo_counts_match_and_draw_without_replacement():
    counts = {0: 3, 1: 2}          # skewed: cluster 0 takes more
    out = placebo_assign(counts, 10, random.Random(3))
    assert {l: len(v) for l, v in out.items()} == counts
    drawn = out[0] + out[1]
    assert len(set(drawn)) == len(drawn)          # no index reused across clusters
    assert all(0 <= i < 10 for i in drawn)


def test_placebo_refuses_overdraw():
    with pytest.raises(AssertionError):
        placebo_assign({0: 5, 1: 6}, 10, random.Random(0))
