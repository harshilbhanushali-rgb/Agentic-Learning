"""Pure-helper tests for calibration/union_pool_fetch.py (Stage A of the union rebuild).

The frozen constant and the exact-equality T0 rule are pinned here so an edit to either
fails a test rather than silently re-deriving the reference pool.
"""
import pytest

from calibration.union_pool_fetch import (
    T0_EXPECTED_OLD_TURNS,
    count_by_origin,
    t0_verdict,
)


# --------------------------------------------------------------------------------------
# the frozen constant itself
# --------------------------------------------------------------------------------------

def test_t0_expected_is_the_audited_clean2_figure():
    """Spec §2: the old corpus must be exactly the pool clean2_base was built on."""
    assert T0_EXPECTED_OLD_TURNS == 20_788


# --------------------------------------------------------------------------------------
# count_by_origin
# --------------------------------------------------------------------------------------

def test_counts_split_on_old_stem_membership():
    old, new = count_by_origin(["a", "b", "a", "c", "d"], {"a", "b"})
    assert (old, new) == (3, 2)


def test_all_old_and_all_new_edges():
    assert count_by_origin(["a", "a"], {"a"}) == (2, 0)
    assert count_by_origin(["x", "y"], {"a"}) == (0, 2)
    assert count_by_origin([], {"a"}) == (0, 0)


# --------------------------------------------------------------------------------------
# t0_verdict — exact equality, both directions
# --------------------------------------------------------------------------------------

def test_t0_passes_only_on_exact_equality():
    assert t0_verdict(20_788)["pass"] is True


@pytest.mark.parametrize("n", [20_787, 20_789, 0, 21_915, 23_949])
def test_t0_fails_on_any_other_count_in_either_direction(n):
    """A pool that GAINED turns is as disqualifying as one that lost them — either way
    the parse no longer matches what clean2_base was adjudicated on."""
    assert t0_verdict(n)["pass"] is False


def test_t0_verdict_records_both_numbers_for_the_artifact():
    v = t0_verdict(5, expected=7)
    assert v == {"expected_old_turns": 7, "old_turns": 5, "pass": False}
