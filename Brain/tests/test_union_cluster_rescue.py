"""Pure-helper tests for calibration/union_cluster_rescue.py (Stage B of the rebuild).

The rescue contract (adds only, count fixed, no double admission) is what makes Stage C's
"membership is the single variable" design true; each violation is pinned separately.
"""
import pytest

from calibration.union_cluster_rescue import (
    assert_rescue_only_adds,
    size_distribution,
    t1_summary,
)


# --------------------------------------------------------------------------------------
# assert_rescue_only_adds — the rescue contract
# --------------------------------------------------------------------------------------

def test_counts_added_turns_across_clusters():
    assert assert_rescue_only_adds([[1, 2], [3]], [[1, 2, 9], [3, 4, 5]]) == 3


def test_identical_membership_is_a_valid_zero_rescue():
    assert assert_rescue_only_adds([[1], [2]], [[1], [2]]) == 0


def test_a_cluster_losing_a_member_is_refused():
    with pytest.raises(ValueError, match="LOST"):
        assert_rescue_only_adds([[1, 2]], [[1, 9]])


def test_a_changed_cluster_count_is_refused():
    with pytest.raises(ValueError, match="count"):
        assert_rescue_only_adds([[1], [2]], [[1, 2]])


def test_double_admission_of_one_turn_is_refused():
    """The frozen rule admits a noise turn to its single NEAREST cluster; the same turn
    appearing in two clusters means the rule was not what ran."""
    with pytest.raises(ValueError, match="more than one"):
        assert_rescue_only_adds([[1], [2]], [[1, 9], [2, 9]])


def test_membership_order_is_irrelevant_to_the_contract():
    assert assert_rescue_only_adds([[2, 1]], [[9, 1, 2]]) == 1


# --------------------------------------------------------------------------------------
# t1_summary — the T1 readout is derived from memberships alone
# --------------------------------------------------------------------------------------

def test_t1_noise_rates_before_and_after():
    t1 = t1_summary(10, [[0, 1], [2]], [[0, 1, 5], [2, 6, 7]])
    assert t1["n_clusters"] == 2
    assert t1["noise_before"] == pytest.approx(0.7)
    assert t1["noise_after"] == pytest.approx(0.4)
    assert t1["rescued_turns"] == 3


def test_t1_size_distributions_reflect_both_sets():
    t1 = t1_summary(10, [[0], [1]], [[0, 2], [1, 3]])
    assert t1["sizes_base"]["total"] == 2
    assert t1["sizes_rescued"]["total"] == 4


def test_t1_propagates_a_contract_violation():
    with pytest.raises(ValueError):
        t1_summary(10, [[0, 1]], [[0]])


# --------------------------------------------------------------------------------------
# size_distribution
# --------------------------------------------------------------------------------------

def test_size_distribution_basic_and_empty():
    d = size_distribution([1, 2, 3, 4])
    assert d["n"] == 4 and d["total"] == 10 and d["max"] == 4
    assert size_distribution([]) == {"n": 0}
