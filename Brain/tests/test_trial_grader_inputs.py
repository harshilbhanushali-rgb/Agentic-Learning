"""Tests for calibration/trial_grader_inputs.py's uncertainty on D.

Pins F11: the point estimate D is pooled -- W = (full + 0.5*partial)/attempts over every
milestone in the arm -- while its bootstrap CI averaged per-item W values UNWEIGHTED. Two
different estimators reported as one number. On the shipped artifacts they disagree by -0.02
to +1.9, and in `confirmB` the interval [2.116, 3.645] excluded its own point estimate of
2.114.

No network, no DB: bootstrap_d is pure given a seeded Generator.
"""
from __future__ import annotations

import numpy as np
import pytest

from calibration import trial_grader_inputs as tg


def _rec(verdict):
    return {"verdict": verdict}


def test_item_counts_returns_the_terms_w_is_built_from():
    recs = [_rec("full_hit"), _rec("partial_hit"), _rec("partial_hit"), _rec("miss")]
    assert tg.item_counts(recs) == (1, 2, 4)
    assert tg.weighted(*tg.item_counts(recs)) == pytest.approx((1 + 0.5 * 2) / 4)


def test_the_ci_brackets_the_pooled_d_and_not_the_per_item_mean():
    """The decisive case: big low-scoring items vs small high-scoring ones.

    matched   2 items x 10 milestones, no credit | 6 items x 1 milestone, a full hit
      pooled     = 6 / 26                = 0.2308   <- what D reports
      per-item   = (0+0+1*6) / 8         = 0.7500   <- what the old CI averaged
    unrelated is deliberately uniform (every item 1 of 2), so its two estimators agree at
    0.5 and the divergence is isolated to the matched arm.
      D pooled   = 0.4615      D per-item = 1.5000

    The interval must bracket 0.4615 and must NOT reach the per-item answer. A CI built the
    old way sits around 1.5 and excludes the very number it claims to quantify -- which is
    what `confirmB` shipped: [2.116, 3.645] around a point estimate of 2.114.
    """
    cm = {f"big{i}": (0, 0, 10) for i in range(2)}
    cm.update({f"small{i}": (1, 0, 1) for i in range(6)})
    cu = {k: (1, 0, 2) for k in cm}

    d_pooled = tg.weighted(6, 0, 26) / tg.weighted(8, 0, 16)
    d_per_item = (6 / 8) / 0.5
    assert d_pooled == pytest.approx(0.4615, abs=1e-4)
    assert d_per_item == pytest.approx(1.5)

    lo, hi = tg.bootstrap_d(cm, cu, np.random.default_rng(0))
    assert lo <= d_pooled <= hi, "the interval must contain its own point estimate"
    # `lo` is what discriminates. Resampling 8 items of which 2 are big is high-variance, so
    # the UPPER end legitimately reaches ~2.0 under the correct estimator too and asserting
    # on it would fail a right answer. The pre-fix bootstrap puts `lo` near 0.75, above the
    # 0.4615 it claims to bracket; the pooled one puts it near 0.11.
    assert lo < d_pooled, "the lower bound must sit below the point estimate, not above it"


def test_a_single_item_repeated_gives_a_degenerate_but_finite_interval():
    cm = {"A": (1, 0, 2)}
    cu = {"A": (1, 0, 4)}
    lo, hi = tg.bootstrap_d(cm, cu, np.random.default_rng(1))
    assert lo == pytest.approx(2.0) and hi == pytest.approx(2.0)


def test_bootstrap_needs_counts_not_pre_divided_w():
    """The division must happen AFTER the resampled counts are summed. Handing bootstrap_d
    per-item W floats is the pre-fix shape and must not silently work."""
    with pytest.raises((TypeError, ValueError, IndexError)):
        tg.bootstrap_d({"A": 0.5, "B": 0.25}, {"A": 0.5, "B": 0.25},
                       np.random.default_rng(0))


def test_no_overlapping_items_yields_nan_not_a_fabricated_interval():
    lo, hi = tg.bootstrap_d({"A": (1, 0, 2)}, {"B": (1, 0, 2)}, np.random.default_rng(0))
    assert lo != lo and hi != hi


def test_every_condition_records_which_estimator_made_its_interval():
    """An artifact whose CI came from the pre-2026-08-15 per-item mean is not comparable to
    one from the pooled bootstrap, and nothing in the file used to say which it was."""
    assert tg.CI_ESTIMATOR == "pooled_w_over_resampled_items"


def test_weighted_counts_a_partial_as_half():
    assert tg.weighted(1, 1, 4) == pytest.approx(0.375)
    assert tg.weighted(0, 0, 0) == 0.0
