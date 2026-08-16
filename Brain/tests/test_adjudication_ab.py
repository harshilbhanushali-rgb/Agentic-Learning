"""Pure-helper tests for calibration/adjudication_ab.py.

Each test pins a guard that exists because a specific defect was found in the harness this
file replaces. Named so a failure says WHICH defect came back.
"""
import numpy as np
import pytest

from calibration.adjudication_ab import (
    cluster_id,
    compare_kinds,
    kind_by_cluster,
    members_sha,
    pick_representatives,
    retention_stats,
    paths,
)


# --------------------------------------------------------------------------------------
# members_sha -- the checkpoint key. Keying on COUNT let a rescued arm reuse its base's
# verdicts, because the rescue holds cluster count fixed by construction.
# --------------------------------------------------------------------------------------

def test_sha_changes_when_membership_grows_at_constant_cluster_count():
    """THE defect this replaces: same count, different members, old guard saw no difference."""
    base = [{"idxs": [1, 2, 3]}, {"idxs": [4, 5]}]
    grown = [{"idxs": [1, 2, 3, 99]}, {"idxs": [4, 5]}]
    assert len(base) == len(grown)
    assert members_sha(base) != members_sha(grown)


def test_sha_is_stable_across_member_order():
    assert members_sha([{"idxs": [3, 1, 2]}]) == members_sha([{"idxs": [1, 2, 3]}])


def test_sha_distinguishes_cluster_boundaries():
    """[[1,2],[3]] and [[1],[2,3]] hold the same members but are different partitions."""
    assert members_sha([{"idxs": [1, 2]}, {"idxs": [3]}]) != \
           members_sha([{"idxs": [1]}, {"idxs": [2, 3]}])


# --------------------------------------------------------------------------------------
# cluster_id -- the join key. The loop index is a RANK and the rescue reorders it.
# --------------------------------------------------------------------------------------

def test_cluster_id_is_order_independent():
    assert cluster_id([7, 2, 5]) == cluster_id([2, 5, 7])


def test_cluster_id_distinguishes_different_topic_sets():
    assert cluster_id([1, 2]) != cluster_id([1, 3])


# --------------------------------------------------------------------------------------
# pick_representatives -- position-based selection made the judge blind to the treatment.
# --------------------------------------------------------------------------------------

def _toy():
    # 4 unit vectors; index 3 is closest to the centroid direction e0, index 0 is furthest
    v = np.array([[0.0, 1.0], [0.6, 0.8], [0.8, 0.6], [1.0, 0.0]], dtype=np.float32)
    texts = ["far", "midfar", "midnear", "near"]
    return v, texts, np.array([1.0, 0.0], dtype=np.float32)


def test_representatives_are_the_most_central_not_the_first():
    v, texts, cen = _toy()
    assert pick_representatives(v, [0, 1, 2, 3], texts, cen, k=2) == ["near", "midnear"]


def test_an_appended_central_member_DISPLACES_a_peripheral_one():
    """The whole point: a rescued turn must be able to reach the judge. Under the old
    `texts[:k]` rule an appended member could never appear, so the arms' prompts were
    identical and the comparison was a guaranteed null."""
    v, texts, cen = _toy()
    without = pick_representatives(v, [0, 1], texts, cen, k=2)
    with_appended = pick_representatives(v, [0, 1, 3], texts, cen, k=2)
    assert without == ["midfar", "far"]
    assert with_appended[0] == "near"
    assert without != with_appended


def test_representatives_are_deterministic():
    v, texts, cen = _toy()
    a = pick_representatives(v, [0, 1, 2, 3], texts, cen, k=3)
    b = pick_representatives(v, [0, 1, 2, 3], texts, cen, k=3)
    assert a == b


def test_representatives_handle_fewer_members_than_k_and_empty():
    v, texts, cen = _toy()
    assert pick_representatives(v, [2], texts, cen, k=6) == ["midnear"]
    assert pick_representatives(v, [], texts, cen, k=6) == []


# --------------------------------------------------------------------------------------
# retention_stats -- `merged` means RETAINED. Collapsing the enum produced a phantom finding.
# --------------------------------------------------------------------------------------

def _rows(scenario=0, merged=0, mechanics=0, logistics=0, failed=0):
    out = []
    for kind, n in (("scenario", scenario), ("merged", merged), ("mechanics", mechanics),
                    ("logistics", logistics)):
        out += [{"kind": kind, "cluster_id": f"{kind}{i}", "failed": False} for i in range(n)]
    out += [{"kind": "failed", "cluster_id": f"f{i}", "failed": True} for i in range(failed)]
    return out


def test_rebased_share_excludes_merged_from_the_denominator():
    s = retention_stats(_rows(scenario=38, merged=69, mechanics=129, logistics=9))
    assert s["n"] == 245
    assert s["share_raw"] == pytest.approx(38 / 245)
    assert s["share_rebased"] == pytest.approx(38 / 176)
    assert s["retained"] == 107


def test_growing_the_merge_count_moves_raw_and_rebased_shares_in_OPPOSITE_directions():
    """Exactly why the raw share must never be the headline in a paired comparison: the
    treatment moves the denominator, so the ratio can move the wrong way on its own."""
    a = retention_stats(_rows(scenario=38, merged=69, mechanics=138))
    b = retention_stats(_rows(scenario=38, merged=79, mechanics=128))
    assert a["n"] == b["n"] and a["scenario"] == b["scenario"]
    assert a["share_raw"] == b["share_raw"]           # raw cannot see the change at all
    assert b["share_rebased"] > a["share_rebased"]    # rebased does


def test_failed_rows_are_counted_and_are_not_scenarios():
    s = retention_stats(_rows(scenario=3, failed=2))
    assert s["failed"] == 2 and s["scenario"] == 3


def test_retention_stats_on_empty_rows_does_not_divide_by_zero():
    s = retention_stats([])
    assert s["n"] == 0 and s["share_raw"] == 0.0


# --------------------------------------------------------------------------------------
# compare_kinds -- joins on cluster_id
# --------------------------------------------------------------------------------------

def test_flips_are_detected_and_transitions_counted():
    a = [{"cluster_id": "1", "kind": "scenario"}, {"cluster_id": "2", "kind": "mechanics"}]
    b = [{"cluster_id": "1", "kind": "mechanics"}, {"cluster_id": "2", "kind": "mechanics"}]
    d = compare_kinds(a, b)
    assert d["n_shared"] == 2 and d["n_flipped"] == 1
    assert d["transitions"] == {"scenario->mechanics": 1}
    assert d["flip_rate"] == pytest.approx(0.5)


def test_join_is_by_cluster_id_and_survives_reordering():
    """The rescue reorders the largest-first sort, so a positional join would report
    spurious flips. Same ids in a different order must show ZERO flips."""
    a = [{"cluster_id": "x", "kind": "scenario"}, {"cluster_id": "y", "kind": "mechanics"}]
    b = [{"cluster_id": "y", "kind": "mechanics"}, {"cluster_id": "x", "kind": "scenario"}]
    assert compare_kinds(a, b)["n_flipped"] == 0


def test_non_overlapping_clusters_are_reported_not_silently_dropped():
    a = [{"cluster_id": "x", "kind": "scenario"}]
    b = [{"cluster_id": "z", "kind": "scenario"}]
    d = compare_kinds(a, b)
    assert d["n_shared"] == 0 and d["n_only_a"] == 1 and d["n_only_b"] == 1


def test_kind_by_cluster_skips_rows_with_no_id():
    assert kind_by_cluster([{"kind": "scenario"}]) == {}


# --------------------------------------------------------------------------------------
# paths -- no default that can collide with a published baseline
# --------------------------------------------------------------------------------------

def test_each_arm_gets_its_own_pair_of_files():
    ca, oa = paths("base_a")
    cb, ob = paths("base_b")
    assert ca != cb and oa != ob
    assert "base_a" in oa.name and "base_b" in ob.name


def test_an_empty_or_unsafe_arm_name_is_refused():
    for bad in ("", "../evil", "a b", "x/y"):
        with pytest.raises(SystemExit):
            paths(bad)


def test_arm_paths_never_collide_with_the_old_harness_artifacts():
    """The replaced harness wrote to adjudicate_gemini_min16.json, which IS a baseline."""
    for arm in ("base_a", "rescued", "min16"):
        _, out = paths(arm)
        assert not out.name.startswith("adjudicate_gemini")
