"""Tests for calibration/diagnose_rubric_level.py's union denominator.

Pins F6: the union rate is "what share of the RUBRIC'S criteria does somebody ever hit",
so its denominator is the rubric's criteria count -- not the number of criteria that
happen to carry a milestone_performance row. Layer D never attempts every criterion (17 of
395 in the shipped artifact), and excluding the unattempted ones inflates the union, which
pushes the diagnosis toward "denominator inflation" and away from "dead criteria".

No DB, no network -- union_rows is pure.
"""
from __future__ import annotations

import pytest

from calibration import diagnose_rubric_level as drl


def _row(rubric_id, milestone_id, n_criteria_in_rubric, attempts=10, hits=0, partial=0):
    return {
        "rubric_id": rubric_id,
        "scenario_key": f"scenario_{rubric_id}",
        "milestone_id": milestone_id,
        "label": "",
        "description": "",
        "n_criteria_in_rubric": n_criteria_in_rubric,
        "attempts": attempts,
        "hits": hits,
        "partial": partial,
        "w": (hits + 0.5 * partial) / attempts if attempts else 0.0,
        "ever_hit": (hits + partial) > 0,
    }


def test_union_denominator_is_the_rubrics_criteria_not_the_attempted_ones():
    """The F6 case: a 3-criterion rubric where Layer D only ever attempted 2 of them.

    One of the two attempted criteria was hit, so the union is 1/3, NOT 1/2. The
    never-attempted criterion was never hit by anybody either -- that is exactly what the
    union is asking about, so it belongs in the denominator.
    """
    rows = [
        _row(1, "M1", n_criteria_in_rubric=3, hits=2),   # ever hit
        _row(1, "M2", n_criteria_in_rubric=3, hits=0),   # attempted, never hit
        # M3 exists in the rubric but has no milestone_performance row at all.
    ]
    (u,) = drl.union_rows(rows)
    assert u["n"] == 3, "denominator must be the rubric's criteria count"
    assert u["alive"] == 1
    assert u["union"] == pytest.approx(1 / 3)


def test_union_is_one_only_when_every_criterion_in_the_rubric_is_reachable():
    """A rubric whose attempted criteria were all hit is NOT complete if some were skipped."""
    partly_attempted = [
        _row(7, "M1", n_criteria_in_rubric=2, hits=1),   # the only attempted one, and hit
    ]
    fully_attempted = [
        _row(8, "M1", n_criteria_in_rubric=2, hits=1),
        _row(8, "M2", n_criteria_in_rubric=2, partial=1),
    ]
    (a,) = drl.union_rows(partly_attempted)
    (b,) = drl.union_rows(fully_attempted)
    assert a["union"] == pytest.approx(0.5)
    assert b["union"] == pytest.approx(1.0)


def test_n_attempted_is_still_reported_so_the_gap_is_visible():
    """The attempted count is the silent-drop counter -- it must not be thrown away."""
    rows = [_row(3, "M1", n_criteria_in_rubric=5, hits=1)]
    (u,) = drl.union_rows(rows)
    assert u["n_attempted"] == 1
    assert u["n"] == 5


def test_a_partial_hit_counts_as_alive():
    """ever_hit is (hits + partial) > 0 -- a partial credit means the criterion is reachable."""
    rows = [
        _row(4, "M1", n_criteria_in_rubric=2, hits=0, partial=3),
        _row(4, "M2", n_criteria_in_rubric=2, hits=0, partial=0),
    ]
    (u,) = drl.union_rows(rows)
    assert u["alive"] == 1
    assert u["union"] == pytest.approx(0.5)


def test_w_is_unchanged_by_the_denominator_fix():
    """W is attempts-weighted and must keep using only rows that were actually attempted."""
    rows = [
        _row(5, "M1", n_criteria_in_rubric=9, attempts=10, hits=1),
        _row(5, "M2", n_criteria_in_rubric=9, attempts=10, hits=0, partial=2),
    ]
    (u,) = drl.union_rows(rows)
    assert u["w"] == pytest.approx((1 + 0.5 * 2) / 20)
