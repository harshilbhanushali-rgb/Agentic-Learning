"""Unit tests for the F1/F2 follow-up pure helpers. Skewed fixtures, per the standing rule."""
from __future__ import annotations

import numpy as np

from calibration.lcfr_followups import failing_members, flips, paired_flip_counts


def _cands():
    # skewed: one huge passing cluster, two small failing ones -- like the real 171-vs-33
    return [
        {"cluster_id": 0, "support_calls": 40, "support_call_files": [f"c{i}" for i in range(40)],
         "_idx": [0, 1], "clauses": ["a", "b"]},
        {"cluster_id": 1, "support_calls": 2, "support_call_files": ["c1", "c2"],
         "_idx": [2], "clauses": ["c"]},
        {"cluster_id": 2, "support_calls": 3, "support_call_files": ["c3", "c4", "c5"],
         "_idx": [3], "clauses": ["d"]},
    ]


def test_failing_members_excludes_passing_clusters():
    vecs = np.eye(5, dtype=np.float32)
    m = failing_members(_cands(), required=4, vecs=vecs)
    # cluster 0 (support 40) must NOT be a destination; that is the entire re-aim
    assert set(m) == {1, 2}
    assert m[1].shape == (1, 5)


def test_flips_counts_only_new_distinct_calls():
    cands = _cands()
    calls = ["c1", "c1", "c1", "c3", "cX", "cY", "c2", "c2"]
    noise_rows = [4, 5, 6, 7]
    # cluster 1 (support 2, needs 4): adds noise idx 0,1 -> calls cX, cY -> support 4: flip
    # cluster 2 (support 3, needs 4): adds noise idx 2,3 -> calls c2, c2 -> c2 is NEW to
    #   cluster 2 -> support 4: flip. A wrong impl counting CLAUSES not distinct calls
    #   would give cluster 2 support 5.
    adds = {1: [0, 1], 2: [2, 3]}
    got = flips(cands, 4, calls, adds, noise_rows)
    assert got == {1, 2}
    # same-call adds only: cluster 1 adds two clauses both from c1 (already a member call)
    got = flips(cands, 4, calls, {1: [], 2: []}, noise_rows)
    assert got == set()


def test_flips_ignores_passing_clusters_and_same_call_padding():
    cands = _cands()
    calls = ["c1"] * 8
    noise_rows = [4, 5, 6, 7]
    # every add comes from c1, already in both failing clusters' unions or adding 1 call:
    # cluster 2 union {c3,c4,c5} + c1 -> 4 -> flips; cluster 1 union {c1,c2} + c1 -> 2, no
    got = flips(cands, 4, calls, {1: [0, 1], 2: [2]}, noise_rows)
    assert got == {2}


def test_flips_dedups_adds_against_existing_member_calls():
    # required=5, existing {c1,c2}; adds bring cX and c1. Correct union = {c1,c2,cX} = 3,
    # no flip. An impl computing support_calls + len(set(add_calls)) gets 2+2=4... still
    # no flip at 5 -- so pin the flip side too: adds bring cX, cY, c1 -> correct 4 (no
    # flip at 5), no-cross-dedup impl gets 2+3=5 (flip). This fixture fails that impl.
    cands = [{"cluster_id": 9, "support_calls": 2, "support_call_files": ["c1", "c2"],
              "_idx": [0], "clauses": ["m"]}]
    calls = ["c1", "cX", "cY", "c1"]
    noise_rows = [1, 2, 3]
    got = flips(cands, 5, calls, {9: [0, 1, 2]}, noise_rows)  # adds cX, cY, c1
    assert got == set()


def test_paired_flip_counts_directions():
    failing = [("s", 1), ("s", 2), ("t", 3), ("t", 4)]
    up, down, tie = paired_flip_counts(
        failing, rule_flips={("s", 1), ("t", 3)}, placebo_flips={("s", 1), ("t", 4)})
    assert (up, down, tie) == (1, 1, 2)
