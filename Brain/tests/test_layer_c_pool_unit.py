"""Unit tests for calibration/layer_c_pool_unit.py — the pure helpers only.

The pipeline pieces (segmenter, filter, clusterer) are production imports proven by
V0/F0 checks at run time; these tests pin the NEW logic: the frozen window rule, unit
construction (positions, text join, call attribution), canonical clause resolution,
and the support gate on units.
"""
from __future__ import annotations

import numpy as np
import pytest

from calibration.layer_c_pool_unit import (window_spans, units_from_response,
                                           build_units, resolved_milestones,
                                           noise_rate, WINDOW)


# ---------------------------------------------------------------------------------------
# window_spans — the frozen rule
# ---------------------------------------------------------------------------------------

def test_window_spans_exact_multiples():
    assert window_spans(3) == [(0, 3)]
    assert window_spans(6) == [(0, 3), (3, 6)]
    assert window_spans(9) == [(0, 3), (3, 6), (6, 9)]


def test_window_spans_remainder_two_stays():
    assert window_spans(5) == [(0, 3), (3, 5)]
    assert window_spans(8) == [(0, 3), (3, 6), (6, 8)]


def test_window_spans_remainder_one_merges_into_previous():
    assert window_spans(4) == [(0, 4)]
    assert window_spans(7) == [(0, 3), (3, 7)]
    assert window_spans(10) == [(0, 3), (3, 6), (6, 10)]


def test_window_spans_short_response_is_one_window():
    assert window_spans(1) == [(0, 1)]
    assert window_spans(2) == [(0, 2)]


def test_window_spans_zero_and_coverage():
    assert window_spans(0) == []
    for n in range(1, 40):
        spans = window_spans(n)
        # exact cover, no overlap, order preserved
        assert spans[0][0] == 0 and spans[-1][1] == n
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            assert b1 == a2
        # no window of size 1 unless the whole response is 1 clause
        if n > 1:
            assert all(b - a >= 2 for a, b in spans)


# ---------------------------------------------------------------------------------------
# units_from_response — positions, text, call attribution
# ---------------------------------------------------------------------------------------

def test_turn_unit_is_whole_response():
    cl = ["a b c.", "d e f.", "g h i.", "j k l."]
    us = units_from_response(cl, "call1.txt", "u_turn")
    assert len(us) == 1
    assert us[0]["clauses"] == cl
    assert us[0]["text"] == "a b c. d e f. g h i. j k l."
    assert us[0]["call"] == "call1.txt"
    # median of positions 0, 1/3, 2/3, 1
    assert us[0]["position"] == pytest.approx(0.5)


def test_window_units_positions_mirror_production_normalisation():
    cl = [f"clause {i}." for i in range(6)]     # positions i/5
    us = units_from_response(cl, "c.txt", "u_win")
    assert len(us) == 2
    assert us[0]["clauses"] == cl[:3] and us[1]["clauses"] == cl[3:]
    assert us[0]["position"] == pytest.approx(1 / 5)   # median(0, .2, .4)
    assert us[1]["position"] == pytest.approx(4 / 5)   # median(.6, .8, 1)


def test_single_clause_response_position_is_zero():
    us = units_from_response(["only clause."], "c.txt", "u_turn")
    assert us[0]["position"] == 0.0
    us = units_from_response(["only clause."], "c.txt", "u_win")
    assert len(us) == 1 and us[0]["position"] == 0.0


def test_empty_response_yields_no_units():
    assert units_from_response([], "c.txt", "u_turn") == []
    assert units_from_response([], "c.txt", "u_win") == []


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        units_from_response(["x y z."], "c.txt", "clause")


def test_build_units_preserves_response_order_and_calls():
    responses = [
        {"response_text": "R1", "call_filename": "a.txt"},
        {"response_text": "R2", "call_filename": "b.txt"},
    ]
    fake_segments = {"R1": ["r1 c1.", "r1 c2.", "r1 c3.", "r1 c4."],
                     "R2": ["r2 c1.", "r2 c2."]}
    us = build_units(responses, "u_win", lambda t: fake_segments[t])
    # R1 (4 clauses, remainder-1 merge) -> one window of 4; R2 (2) -> one window of 2
    assert [u["call"] for u in us] == ["a.txt", "b.txt"]
    assert us[0]["clauses"] == fake_segments["R1"]
    assert us[1]["clauses"] == fake_segments["R2"]


# ---------------------------------------------------------------------------------------
# resolved_milestones — support gate on distinct calls + canonical resolution
# ---------------------------------------------------------------------------------------

def _mk_units(spec):
    """spec: list of (call, clauses) tuples."""
    return [{"text": f"t{i}", "clauses": list(cl), "call": call,
             "position": i / max(len(spec) - 1, 1)}
            for i, (call, cl) in enumerate(spec)]


def test_support_counts_distinct_calls_not_units():
    units = _mk_units([("a.txt", ["c1."]), ("a.txt", ["c2."]),
                       ("a.txt", ["c3."]), ("b.txt", ["c4."])])
    rel = {u["text"]: 0.5 for u in units}
    # cluster 0 = three units of the SAME call -> support 1, fails required=2
    labels = [0, 0, 0, 1]
    ms, n_cands = resolved_milestones(labels, units, rel, scenario_calls=2, required=2)
    assert n_cands == 2
    assert ms == []


def test_resolution_concatenates_member_clauses_in_pool_order():
    units = _mk_units([("a.txt", ["c1.", "c2."]), ("b.txt", ["c3."]),
                       ("c.txt", ["c4.", "c5."])])
    rel = {u["text"]: 0.9 for u in units}
    labels = [0, 0, 0]
    ms, _ = resolved_milestones(labels, units, rel, scenario_calls=3, required=2)
    assert len(ms) == 1
    m = ms[0]
    assert m["clauses"] == ["c1.", "c2.", "c3.", "c4.", "c5."]
    assert m["n_units"] == 3
    assert m["support_clauses"] == 5
    assert m["support_calls"] == 3
    assert m["support_call_files"] == ["a.txt", "b.txt", "c.txt"]
    assert m["support_frac"] == pytest.approx(1.0)
    assert m["relevance_mean"] == pytest.approx(0.9)


def test_noise_label_excluded_and_milestones_sorted_by_position():
    units = _mk_units([("a.txt", ["x."]), ("b.txt", ["y."]),
                       ("c.txt", ["z."]), ("d.txt", ["w."]), ("e.txt", ["v."])])
    rel = {u["text"]: 0.1 for u in units}
    # cluster 1 sits LATER in the pool (higher positions) than cluster 0
    labels = [-1, 1, 1, 0, 0]
    ms, n_cands = resolved_milestones(labels, units, rel, scenario_calls=5, required=2)
    assert n_cands == 2
    assert [m["cluster_id"] for m in ms] == [1, 0] or ms[0]["median_position"] <= ms[1]["median_position"]
    assert all(m["median_position"] == pytest.approx(m["median_position"]) for m in ms)
    assert ms[0]["median_position"] <= ms[1]["median_position"]


def test_noise_rate():
    assert noise_rate([-1, -1, 0, 1]) == pytest.approx(0.5)
    assert np.isnan(noise_rate([]))


def test_window_constant_is_three():
    # the spec froze windows at 3 clauses; a silent constant change must fail a test
    assert WINDOW == 3
