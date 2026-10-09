"""Tests for calibration/layer_c_cluster_bench.py's pure pieces — hand-built inputs only."""
import numpy as np
import pytest

from calibration.layer_c_cluster_bench import (
    noise_rate, milestones_from_labels, pick_gamma, rescue_labels,
)


# --- noise_rate ----------------------------------------------------------------------------

def test_noise_rate():
    assert noise_rate(np.array([0, -1, 1, -1])) == 0.5
    assert noise_rate(np.array([0, 0])) == 0.0


def test_noise_rate_empty_is_nan():
    assert noise_rate(np.array([])) != noise_rate(np.array([]))  # NaN


# --- milestones_from_labels ------------------------------------------------------------------

def _pool():
    clauses = ["a", "b", "c", "d", "e"]
    calls = ["c1.txt", "c2.txt", "c1.txt", "c3.txt", "c3.txt"]
    positions = [1, 2, 3, 4, 5]
    relevance = {c: 0.5 for c in clauses}
    return clauses, calls, positions, relevance


def test_support_gate_is_distinct_calls():
    clauses, calls, positions, relevance = _pool()
    # cluster 0 = rows 0,2 (both c1.txt -> support 1); cluster 1 = rows 1,3,4 (c2,c3 -> 2)
    labels = np.array([0, 1, 0, 1, 1])
    ms, cands = milestones_from_labels(labels, clauses, calls, positions, relevance,
                                       scenario_calls=10, required=2)
    assert len(cands) == 2
    assert len(ms) == 1 and ms[0]["support_calls"] == 2
    assert ms[0]["support_call_files"] == ["c2.txt", "c3.txt"]
    assert ms[0]["support_frac"] == 0.2


def test_noise_rows_excluded_and_order_by_position():
    clauses, calls, positions, relevance = _pool()
    labels = np.array([1, 1, -1, 0, 0])
    ms, _ = milestones_from_labels(labels, clauses, calls, positions, relevance,
                                   scenario_calls=5, required=1)
    # cluster 1 (positions 1,2) must sort before cluster 0 (positions 4,5)
    assert [m["cluster_id"] for m in ms] == [1, 0]
    assert all("c" not in m["clauses"] for m in ms)  # the -1 row never appears


# --- pick_gamma ------------------------------------------------------------------------------

def test_pick_gamma_smallest_reaching_target():
    g, endpoint = pick_gamma({0.001: 2, 0.01: 5, 0.1: 9}, target=5)
    assert g == 0.01 and not endpoint


def test_pick_gamma_endpoint_flagged_low():
    g, endpoint = pick_gamma({0.001: 7, 0.01: 9}, target=5)
    assert g == 0.001 and endpoint  # landed on the grid's low edge -> warned


def test_pick_gamma_endpoint_flagged_high_when_unreachable():
    g, endpoint = pick_gamma({0.001: 1, 0.01: 2}, target=99)
    assert g == 0.01 and endpoint


# --- rescue_labels ---------------------------------------------------------------------------

def test_rescue_labels_translates_noise_indices():
    base = np.array([0, -1, 1, -1, -1])
    noise_idx = [1, 3, 4]
    out = rescue_labels(base, {0: [0], 1: [2]}, noise_idx)
    assert out.tolist() == [0, 0, 1, -1, 1]
    assert base.tolist() == [0, -1, 1, -1, -1]  # input never mutated


def test_rescue_labels_refuses_clustered_target():
    base = np.array([0, 1])
    with pytest.raises(AssertionError):
        rescue_labels(base, {0: [0]}, noise_idx=[0])  # noise_idx points at a clustered row
