"""Pure-helper tests for calibration/clustering_bench.py.

Only the functions that decide something on their own are covered here: label transfer,
the two placebo constructions, the sign test and scale matching. The heavy paths (UMAP,
HDBSCAN, Leiden) are validated at run time by the harness's own asserts -- F2's identity
transfer and the seed-42 mirror check -- because a unit test with hand-built vectors would
only re-test the library, not the harness's use of it.

Same reasoning as tests/test_layer_b_assignment.py: build the inputs by hand so the RULE is
what gets tested, never the embedding model.
"""
import random

import pytest

from calibration.clustering_bench import (
    plurality_transfer,
    populations,
    scale_match,
    shuffle_partition,
    sign_test,
    volume_matched_rescue,
)


# --------------------------------------------------------------------------------------
# plurality_transfer
# --------------------------------------------------------------------------------------

def test_plurality_wins_not_first_seen():
    """The MAJORITY label wins, not whichever label a low index happens to carry."""
    truth = {0: "zeta", 1: "alpha", 2: "alpha", 3: "alpha"}
    assert plurality_transfer([[0, 1, 2, 3]], truth) == ["alpha"]


def test_unlabeled_members_are_ignored_not_counted():
    """Incumbent-noise turns carry no label; they must not dilute the plurality."""
    truth = {5: "alpha"}
    assert plurality_transfer([[5, 900, 901, 902]], truth) == ["alpha"]


def test_tie_breaks_to_lexicographically_smallest():
    """Determinism: a 2-2 tie must resolve the same way on every machine and every run."""
    truth = {0: "beta", 1: "beta", 2: "alpha", 3: "alpha"}
    assert plurality_transfer([[0, 1, 2, 3]], truth) == ["alpha"]
    # and the answer must not depend on member order
    assert plurality_transfer([[3, 2, 1, 0]], truth) == ["alpha"]


def test_cluster_with_zero_labeled_members_is_unmapped():
    assert plurality_transfer([[900, 901]], {0: "alpha"}) == [None]


def test_transfer_of_a_partition_into_itself_is_the_identity():
    """The F2 invariant in miniature: unanimous clusters map to their own key."""
    truth = {0: "a", 1: "a", 2: "b", 3: "b", 4: "b"}
    assert plurality_transfer([[0, 1], [2, 3, 4]], truth) == ["a", "b"]


# --------------------------------------------------------------------------------------
# populations
# --------------------------------------------------------------------------------------

def test_populations_union_clusters_sharing_a_key_and_drop_sinks():
    arm = [[0, 1], [2], [3, 4]]
    mapped = ["a", "a", "sink"]
    pops = populations(arm, mapped, {"a": True, "sink": False})
    assert pops == {"a": [0, 1, 2]}


def test_populations_skip_unmapped_clusters():
    pops = populations([[0], [1]], ["a", None], {"a": True})
    assert pops == {"a": [0]}


# --------------------------------------------------------------------------------------
# shuffle_partition (F1 placebo)
# --------------------------------------------------------------------------------------

def test_shuffle_preserves_sizes_and_the_exact_member_multiset():
    pool = list(range(20))
    sizes = [3, 7, 10]
    out = shuffle_partition(sizes, pool, random.Random(42))
    assert [len(g) for g in out] == sizes
    assert sorted(i for g in out for i in g) == pool


def test_shuffle_actually_permutes():
    """A placebo that returned the input unchanged would silently pass as the incumbent."""
    pool = list(range(200))
    out = shuffle_partition([100, 100], pool, random.Random(42))
    assert out[0] != pool[:100]


def test_shuffle_rejects_a_size_mismatch():
    with pytest.raises(ValueError):
        shuffle_partition([3, 3], list(range(5)), random.Random(0))


# --------------------------------------------------------------------------------------
# volume_matched_rescue (the mandatory rescue placebo)
# --------------------------------------------------------------------------------------

def test_volume_matched_draws_exactly_the_treatment_counts():
    counts = [4, 0, 9]
    out = volume_matched_rescue(counts, list(range(500)), random.Random(7))
    assert [len(g) for g in out] == counts


def test_volume_matched_draws_without_replacement():
    counts = [50, 50]
    out = volume_matched_rescue(counts, list(range(120)), random.Random(7))
    drawn = [i for g in out for i in g]
    assert len(drawn) == len(set(drawn)) == 100


def test_volume_matched_draws_only_from_the_noise_pool():
    noise = list(range(1000, 1050))
    out = volume_matched_rescue([10, 10], noise, random.Random(1))
    assert all(i in set(noise) for g in out for i in g)


def test_volume_matched_refuses_to_overdraw():
    with pytest.raises(ValueError):
        volume_matched_rescue([30], list(range(10)), random.Random(0))


# --------------------------------------------------------------------------------------
# sign_test
# --------------------------------------------------------------------------------------

def test_sign_test_no_discordant_pairs_is_p_one():
    assert sign_test(0, 0) == 1.0


def test_sign_test_is_symmetric_in_its_arguments():
    assert sign_test(12, 1) == pytest.approx(sign_test(1, 12))


def test_sign_test_known_binomials():
    # two-sided exact binomial, p=0.5
    assert sign_test(5, 5) == pytest.approx(1.0)
    assert sign_test(1, 0) == pytest.approx(1.0)
    assert sign_test(2, 0) == pytest.approx(0.5)
    assert sign_test(10, 0) == pytest.approx(2 * 0.5 ** 10)


def test_the_spec_claim_that_n38_needs_about_12_1_for_p_below_0p01():
    """The design says ~12-1 discordant is needed at n=38. If that stops being true the
    trial's own power statement is wrong, so pin it."""
    assert sign_test(12, 1) < 0.01
    assert sign_test(10, 1) > 0.01


def test_a_narrow_split_is_not_significant():
    assert sign_test(6, 3) >= 0.05


# --------------------------------------------------------------------------------------
# scale_match
# --------------------------------------------------------------------------------------

def test_scale_match_picks_the_closest_count():
    assert scale_match({0.1: 100, 0.2: 240, 0.3: 400}, 245) == 0.2


def test_scale_match_ties_go_to_the_smaller_parameter():
    """Determinism again: two params equidistant from the target must resolve stably."""
    assert scale_match({0.1: 240, 0.9: 250}, 245) == 0.1


def test_scale_match_handles_a_single_candidate():
    assert scale_match({0.5: 3}, 245) == 0.5
