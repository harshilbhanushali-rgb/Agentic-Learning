"""Tests for calibration/null_test_taxonomy.py's length-matched null.

Pins audit F12. The size-matched null drew from the WHOLE pool, which is maximally dispersed
in turn SHAPE, while a scenario's members are turns selected for having a coachable best match
and run far longer than the pool at large (69.1 / 80.9 words vs 45.7). So a group that is
homogeneous in LENGTH ALONE -- carrying no shared subject whatsoever -- beat that null. Not
hypothetical: `client_direct_denial`, 98% content-free at a mean of 3.7 words, cleared it at
rank 2 of 82.

The synthetic pool below makes embedding direction a function of word count and nothing else,
so a length-homogeneous group is coherent BY CONSTRUCTION and carries zero real signal. Any
null worth having must reject it. The second group carries a genuine shared topic across a
spread of lengths and must SURVIVE -- a null that rejects everything is as useless as one that
accepts everything, which is the whole reason the script also runs the rigged positive control.

No network, no DB, no embedder: hand-built vectors only, the same discipline as
test_layer_b_assignment.py.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from calibration import null_test_taxonomy as nt
from calibration.trial_pool_unit import coherence

DIM = 16
N_BG = 600
SEED = 7


def _pool():
    """Background pool whose direction is driven ONLY by word count.

    Word counts sweep 2..200; the vector rotates smoothly with length in the (e0, e1) plane
    plus isotropic noise. Two turns of similar length are therefore similar, and two turns of
    very different length are not -- with no notion of subject anywhere in the construction.
    """
    rng = np.random.default_rng(SEED)
    words = np.linspace(2, 200, N_BG).round().astype(int)
    vecs = np.zeros((N_BG, DIM), dtype=np.float32)
    for i, w in enumerate(words):
        angle = (w / 200.0) * (np.pi / 2)
        v = np.zeros(DIM)
        v[0], v[1] = np.cos(angle), np.sin(angle)
        v += rng.normal(0, 0.35, DIM)
        vecs[i] = v / np.linalg.norm(v)
    return words, vecs


def _rank_structs(words):
    order = [int(i) for i in np.argsort(words, kind="stable")]
    return order, {t: i for i, t in enumerate(order)}


def _length_homogeneous_group(words):
    """Turns of near-identical length. Coherent purely because they are the same length."""
    return [int(i) for i in np.where((words >= 150) & (words <= 165))[0]]


def _real_topic_group(words, vecs, rng_seed=3):
    """A genuine shared direction, deliberately SPREAD across the whole length range."""
    rng = np.random.default_rng(rng_seed)
    idx = [int(i) for i in np.linspace(0, N_BG - 1, 40).round().astype(int)]
    topic = np.zeros(DIM)
    topic[7] = 1.0
    for i in idx:
        v = vecs[i] + 1.6 * topic + rng.normal(0, 0.10, DIM)
        vecs[i] = v / np.linalg.norm(v)
    return idx


# -- the defect ---------------------------------------------------------------------------

def test_length_only_group_beats_the_whole_pool_null_but_not_the_length_matched_one():
    words, vecs = _pool()
    order, rank_of = _rank_structs(words)
    grp = _length_homogeneous_group(words)
    assert len(grp) >= nt.MIN_MEMBERS

    from calibration.trial_pool_unit import size_matched_null

    coh = coherence(vecs[grp])
    lift_whole = coh - size_matched_null(vecs, len(grp), random.Random(SEED))
    lift_length = coh - nt.length_matched_null(vecs, grp, order, rank_of,
                                               random.Random(SEED))

    assert lift_whole >= nt.LIFT_BAR, (
        "the pre-fix null must be beaten by a length-only group -- if it is not, this "
        f"fixture no longer reproduces F12 (lift_whole={lift_whole:.3f})")
    assert lift_length < nt.LIFT_BAR, (
        "a group with no shared subject, coherent only because its turns are the same "
        f"length, must NOT clear the length-matched null (lift_length={lift_length:.3f})")


def test_length_matched_null_draws_replacements_of_comparable_length():
    """The mechanism, not just the outcome: what it draws must match the target's profile."""
    words, vecs = _pool()
    order, rank_of = _rank_structs(words)
    grp = _length_homogeneous_group(words)

    # Record every candidate the null considers. Rejected duplicates are recorded too, but
    # they come from the same length window, so they cannot flatter the assertion below.
    picks: list[int] = []

    class RecordingRandom(random.Random):
        def randrange(self, lo, hi=None):          # type: ignore[override]
            v = super().randrange(lo, hi)
            picks.append(order[v])
            return v

    nt.length_matched_null(vecs, grp, order, rank_of, RecordingRandom(SEED), draws=3)

    drawn = words[np.array(picks)]
    target = words[np.array(grp)]
    assert abs(drawn.mean() - target.mean()) < 15, (
        f"drawn mean {drawn.mean():.1f} vs target {target.mean():.1f} -- the draw is not "
        "length-matched")
    assert abs(drawn.mean() - words.mean()) > 40, (
        "the draw is indistinguishable from a uniform whole-pool draw, so nothing was matched")


# -- the fix must not simply reject everything --------------------------------------------

def test_a_real_shared_topic_still_clears_the_length_matched_null():
    words, vecs = _pool()
    order, rank_of = _rank_structs(words)
    grp = _real_topic_group(words, vecs)

    coh = coherence(vecs[grp])
    lift = coh - nt.length_matched_null(vecs, grp, order, rank_of, random.Random(SEED))
    assert lift >= nt.LIFT_BAR, (
        "a group sharing a genuine direction across a SPREAD of lengths must survive the "
        f"length-matched null, or the null is merely too hard (lift={lift:.3f})")


def test_gate_and_null_names_stay_in_sync():
    assert nt.GATE_NULL in nt.NULLS
    assert nt.NULLS[0] == "whole", "the pre-fix null must stay first and stay reported"


# -- the control arm's population ----------------------------------------------------------

def test_merged_clusters_are_folded_in_not_discarded():
    """`merged` means RETAINED. Dropping it makes the control purer than what it stands for.

    In the live artifact that filter excluded 69 clusters / 2,434 turns against the 2,725 it
    kept -- and the reference derived from the control is what both headline shares are
    measured against, so the error propagates to every arm.
    """
    clusters = [{"idxs": [0, 1, 2]}, {"idxs": [3, 4]}, {"idxs": [5]}, {"idxs": [6, 7]}]
    adj = [{"kind": "scenario", "scenario_key": "alpha"},
           {"kind": "merged", "scenario_key": "dup", "merge_into_key": "alpha"},
           {"kind": "mechanics", "scenario_key": "sink"},
           {"kind": "scenario", "scenario_key": "beta"}]

    cl_idx, folded, orphaned = nt.fold_merged_clusters(clusters, adj)
    assert set(cl_idx) == {"alpha", "beta"}, "sinks must not become control entries"
    assert sorted(cl_idx["alpha"]) == [0, 1, 2, 3, 4], "the merged cluster's turns must be kept"
    assert cl_idx["beta"] == [6, 7]
    assert (folded, orphaned) == (1, 0)


def test_a_merge_target_that_is_not_a_kept_scenario_is_counted_not_dropped():
    clusters = [{"idxs": [0]}, {"idxs": [1, 2]}]
    adj = [{"kind": "scenario", "scenario_key": "alpha"},
           {"kind": "merged", "scenario_key": "dup", "merge_into_key": "vanished"}]
    cl_idx, folded, orphaned = nt.fold_merged_clusters(clusters, adj)
    assert cl_idx == {"alpha": [0]}
    assert (folded, orphaned) == (0, 1), "an unresolvable merge must be reported, not silent"


# -- the size-matched reference --------------------------------------------------------------

def test_the_reference_is_conditional_on_size():
    """A flat reference grades big groups against a bar set by small ones.

    Inside the live control, corr(lift, n) = -0.510, and its entries are ~4x smaller than
    the arms it judges -- which understated both arms by 16-17 points.
    """
    ctl = [{"n": 10, "lift_length": 0.09, "rankable": True},
           {"n": 12, "lift_length": 0.08, "rankable": True},
           {"n": 15, "lift_length": 0.085, "rankable": True},
           {"n": 800, "lift_length": 0.02, "rankable": True},
           {"n": 900, "lift_length": 0.021, "rankable": True},
           {"n": 1000, "lift_length": 0.019, "rankable": True}]

    small = nt.size_matched_reference(11, ctl, k=3)
    large = nt.size_matched_reference(880, ctl, k=3)
    assert small > large, (
        f"a small entry must face a stiffer reference than a large one ({small} vs {large})")
    assert abs(small - 0.085) < 1e-9 and abs(large - 0.020) < 1e-9, (
        "the reference must be the median of the NEAREST-in-log-size control entries")

    flat = float(np.median([r["lift_length"] for r in ctl]))
    entry_lift = 0.03                      # a big entry, decent for its size
    assert entry_lift < flat, "fixture must reproduce the flat bar being too high..."
    assert entry_lift >= large, "...while the size-matched reference passes it"


def test_reference_ignores_unrankable_and_nan_control_rows():
    ctl = [{"n": 10, "lift_length": 0.09, "rankable": True},
           {"n": 11, "lift_length": float("nan"), "rankable": True},
           {"n": 12, "lift_length": 0.5, "rankable": False}]
    assert nt.size_matched_reference(10, ctl, k=3) == 0.09


def test_length_band_scales_with_the_pool_and_never_starves_the_group():
    """Directly pins the knob the module comment claims is scale-free."""
    assert nt.length_band(10, 23949) == round(nt.LENGTH_BAND_FRACTION * 23949)
    assert nt.length_band(10, 600) == 12, "small pools must get a proportionally small band"
    assert nt.length_band(400, 600) == 400, "the band must never be narrower than the group"
    for n_pool in (50, 600, 23949):
        for n_members in (2, 50, 400):
            assert nt.length_band(n_members, n_pool) >= n_members


# -- why the gate is NOT z -----------------------------------------------------------------

def test_the_nulls_spread_collapses_as_the_group_grows():
    """The mechanism that disqualifies z as a gate, pinned so it cannot be re-introduced.

    The null is a mean over a random pile, so its draw-to-draw spread falls roughly as
    1/sqrt(n). z = lift/sd therefore inflates with SIZE: on real data, sd ran 0.0072 at
    n=10 down to 0.0008 at n=870 and a trivial +0.012 excess scored z~15.
    """
    words, vecs = _pool()
    order, rank_of = _rank_structs(words)
    small = [int(i) for i in np.linspace(0, N_BG - 1, 10).round().astype(int)]
    large = [int(i) for i in np.linspace(0, N_BG - 1, 300).round().astype(int)]

    s_small: dict = {}
    s_large: dict = {}
    nt.length_matched_null(vecs, small, order, rank_of, random.Random(SEED), stats=s_small)
    nt.length_matched_null(vecs, large, order, rank_of, random.Random(SEED), stats=s_large)

    assert s_small["sd"] > 2 * s_large["sd"], (
        f"the null's spread must shrink materially with n (small {s_small['sd']:.5f} vs "
        f"large {s_large['sd']:.5f}) -- this is why z is not a valid gate here")


def test_the_reported_gate_is_lift_not_z():
    """A large group with a WEAK shared direction: significant (big z), trivial (low lift).

    That is the shape of the real arms -- excesses of +0.012 scoring z~15 -- and it must
    NOT be counted as clearing. This is the exact confusion that nearly shipped as the
    "principled" re-derived bar. The topic strength is set low on purpose so the effect is
    small; nothing about the assertion depends on its exact value.
    """
    words, vecs = _pool()
    order, rank_of = _rank_structs(words)
    rng = np.random.default_rng(11)
    grp = [int(i) for i in np.linspace(0, N_BG - 1, 300).round().astype(int)]
    topic = np.zeros(DIM)
    topic[9] = 1.0
    for i in grp:                                   # weak, unlike _real_topic_group's 1.6
        v = vecs[i] + 0.22 * topic
        vecs[i] = v / np.linalg.norm(v)

    out = nt.score_population(vecs, "arm", ["k"], {"k": grp}, order, rank_of, words)
    row = out["rows"][0]
    assert out["n_clear"] == out[f"n_clear_{nt.GATE_NULL}"], "the headline must be the lift count"
    assert row[f"lift_{nt.GATE_NULL}"] < nt.LIFT_BAR, (
        f"fixture must produce a SMALL effect, got {row[f'lift_{nt.GATE_NULL}']:.4f}")
    assert row["z_length"] >= nt.Z_BAR, (
        f"...that is nonetheless statistically significant, got z={row['z_length']:.2f}")
    assert out["n_clear"] == 0 and out["n_clear_z"] == 1, (
        "the reported headline must follow the effect size, not the significance test")


# -- the gate itself ----------------------------------------------------------------------

def test_a_zero_variance_null_does_not_become_an_automatic_pass():
    """z = (coh - mean) / sd divides by zero when every null draw scores identically.

    Unguarded that yields +inf, which sails past any z bar -- so the degenerate case would
    be reported as the STRONGEST possible result instead of an unmeasurable one. The gate
    must treat it as unmeasured (NaN) and the clear-count must exclude it.
    """
    words = np.array([10] * 40)
    order, rank_of = _rank_structs(words)
    vecs = np.tile(np.eye(1, DIM, 0).astype(np.float32), (40, 1))   # every vector identical
    grp = list(range(12))

    st: dict = {}
    nt.length_matched_null(vecs, grp, order, rank_of, random.Random(SEED), stats=st)
    assert st["sd"] == 0 or np.isnan(st["sd"]), f"fixture must give a flat null, got {st['sd']}"

    rows = nt.score_population(vecs, "degenerate", ["k"], {"k": grp},
                               order, rank_of, words)
    z = rows["rows"][0]["z_length"]
    assert np.isnan(z), f"a zero-spread null must yield an unmeasurable z, not {z}"
    assert rows["n_clear_z"] == 0, "an unmeasurable entry must not be counted as clearing"
