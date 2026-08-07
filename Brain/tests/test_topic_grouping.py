"""Unit tests for primary-topic grouping. Pure functions, hand-built synthetic
centroids -- not the real embedding model -- mirroring test_cluster_evidence.py's
style, since group_post_hoc/group_nested are themselves thin wrappers around
cluster_evidence.merge_by_similarity."""
import math

import numpy as np
import pytest

from shared import topic_grouping as tg


def _angle_vec(degrees: float) -> np.ndarray:
    rad = math.radians(degrees)
    return np.array([math.cos(rad), math.sin(rad)], dtype=np.float32)


class TestGroupPostHoc:
    def test_empty_input_returns_no_groups(self):
        assert tg.group_post_hoc([], threshold=0.85) == []

    def test_single_record_is_its_own_group(self):
        records = [{"scenario_key": "solo", "centroid": _angle_vec(0)}]
        assert tg.group_post_hoc(records, threshold=0.85) == [["solo"]]

    def test_identical_centroids_all_merge(self):
        records = [
            {"scenario_key": f"s{i}", "centroid": _angle_vec(0)} for i in range(3)
        ]
        groups = tg.group_post_hoc(records, threshold=0.88)
        assert len(groups) == 1
        assert sorted(groups[0]) == ["s0", "s1", "s2"]

    def test_orthogonal_centroids_stay_separate(self):
        records = [
            {"scenario_key": "a", "centroid": _angle_vec(0)},
            {"scenario_key": "b", "centroid": _angle_vec(90)},
        ]
        groups = tg.group_post_hoc(records, threshold=0.88)
        assert sorted(map(sorted, groups)) == [["a"], ["b"]]

    def test_no_valid_grouping_above_threshold_leaves_everything_singleton(self):
        # Two moderately-related subtopics (30 degrees apart, cosine ~0.87) do
        # not clear an unreasonably strict threshold.
        records = [
            {"scenario_key": "a", "centroid": _angle_vec(0)},
            {"scenario_key": "b", "centroid": _angle_vec(30)},
        ]
        groups = tg.group_post_hoc(records, threshold=0.999)
        assert sorted(map(sorted, groups)) == [["a"], ["b"]]

    def test_groups_are_ordered_largest_first(self):
        records = [
            {"scenario_key": "big1", "centroid": _angle_vec(0)},
            {"scenario_key": "big2", "centroid": _angle_vec(1)},
            {"scenario_key": "big3", "centroid": _angle_vec(2)},
            {"scenario_key": "small", "centroid": _angle_vec(90)},
        ]
        groups = tg.group_post_hoc(records, threshold=0.88)
        assert len(groups) == 2
        assert sorted(groups[0]) == ["big1", "big2", "big3"]
        assert groups[1] == ["small"]

    def test_every_scenario_key_appears_exactly_once(self):
        rng = np.random.default_rng(0)
        records = [
            {"scenario_key": f"s{i}", "centroid": rng.normal(size=4).astype(np.float32)}
            for i in range(10)
        ]
        groups = tg.group_post_hoc(records, threshold=0.88)
        flat = [k for g in groups for k in g]
        assert sorted(flat) == sorted(r["scenario_key"] for r in records)


class TestGroupNested:
    def test_empty_input_returns_no_groups(self):
        assert tg.group_nested(np.empty((0, 2)), loose_threshold=0.80, tight_threshold=0.95) == []

    def test_single_raw_centroid_is_one_macro_group_one_subgroup(self):
        centroids = np.stack([_angle_vec(0)])
        nested = tg.group_nested(centroids, loose_threshold=0.80, tight_threshold=0.95)
        assert nested == [[[0]]]

    def test_two_tight_families_within_one_loose_macro_group(self):
        # Subtopic A: two near-identical raw topics at 0 and 2 degrees.
        # Subtopic B: two near-identical raw topics at 30 and 32 degrees.
        # A and B are ~30 degrees apart (cosine ~0.866): a loose threshold of
        # 0.80 unifies them into one macro group, but a tight threshold of 0.95
        # is strict enough that only same-subtopic pairs merge within it.
        centroids = np.stack([
            _angle_vec(0), _angle_vec(2), _angle_vec(30), _angle_vec(32),
        ])
        nested = tg.group_nested(centroids, loose_threshold=0.80, tight_threshold=0.95)

        assert len(nested) == 1  # one macro group
        subgroups = {frozenset(g) for g in nested[0]}
        assert subgroups == {frozenset({0, 1}), frozenset({2, 3})}

    def test_families_too_far_apart_stay_separate_macro_groups(self):
        # Same two families as above, but the loose threshold is now stricter
        # than the ~30-degree gap between them, so they cannot share a macro
        # group at all -- each becomes its own macro group of one tight subgroup.
        centroids = np.stack([
            _angle_vec(0), _angle_vec(2), _angle_vec(30), _angle_vec(32),
        ])
        nested = tg.group_nested(centroids, loose_threshold=0.95, tight_threshold=0.95)

        assert len(nested) == 2
        flat_subgroups = {frozenset(g) for macro in nested for g in macro}
        assert flat_subgroups == {frozenset({0, 1}), frozenset({2, 3})}

    def test_macro_groups_are_ordered_largest_first(self):
        # Macro X: 3 raw topics within 10 degrees of each other (loose-similar),
        # but more than tight_threshold's angular budget apart pairwise, so each
        # stays its own subgroup. Macro Y: 2 raw topics, same shape, far from X.
        centroids = np.stack([
            _angle_vec(0), _angle_vec(5), _angle_vec(10),   # macro X (3 raw topics)
            _angle_vec(90), _angle_vec(95),                  # macro Y (2 raw topics)
        ])
        nested = tg.group_nested(centroids, loose_threshold=0.90, tight_threshold=0.999)

        assert len(nested) == 2
        sizes = [sum(len(g) for g in macro) for macro in nested]
        assert sizes == [3, 2]
        assert {i for g in nested[0] for i in g} == {0, 1, 2}
        assert {i for g in nested[1] for i in g} == {3, 4}

    def test_flattening_covers_every_raw_index_exactly_once(self):
        rng = np.random.default_rng(1)
        centroids = rng.normal(size=(12, 5)).astype(np.float32)
        nested = tg.group_nested(centroids, loose_threshold=0.80, tight_threshold=0.95)
        flat = [i for macro in nested for g in macro for i in g]
        assert sorted(flat) == list(range(12))

    def test_loose_tight_threshold_never_produces_more_macro_groups_than_subgroups(self):
        # A tight_threshold LOOSER than loose_threshold merges everything that
        # cleared the macro-group stage right back into one subgroup per macro
        # group -- a subgroup is only ever computed from its own macro group's
        # members, so it can never span two macro groups.
        centroids = np.stack([
            _angle_vec(0), _angle_vec(2), _angle_vec(30), _angle_vec(32),
        ])
        nested = tg.group_nested(centroids, loose_threshold=0.80, tight_threshold=0.10)
        assert len(nested) == 1
        assert len(nested[0]) == 1
        assert set(nested[0][0]) == {0, 1, 2, 3}


def _member(key: str, coachable: bool) -> dict:
    return {"scenario_key": key, "is_coachable": coachable}


class TestSplitByCoachability:
    def test_all_coachable_group_is_unchanged(self):
        group = [_member("a", True), _member("b", True)]
        assert tg.split_by_coachability([group]) == [group]

    def test_all_sink_group_is_unchanged(self):
        group = [_member("a", False), _member("b", False)]
        assert tg.split_by_coachability([group]) == [group]

    def test_mixed_group_splits_into_two_homogeneous_groups(self):
        group = [_member("a", True), _member("b", False), _member("c", True)]
        result = tg.split_by_coachability([group])
        assert len(result) == 2
        by_status = {frozenset(m["scenario_key"] for m in g): all(m["is_coachable"] for m in g) for g in result}
        assert frozenset({"a", "c"}) in by_status and by_status[frozenset({"a", "c"})] is True
        assert frozenset({"b"}) in by_status and by_status[frozenset({"b"})] is False

    def test_multiple_mixed_groups_all_split_and_stay_largest_first(self):
        group1 = [_member("a", True), _member("b", False)]
        group2 = [_member("c", True), _member("d", True), _member("e", False)]
        result = tg.split_by_coachability([group1, group2])
        sizes = [len(g) for g in result]
        assert sizes == sorted(sizes, reverse=True)
        keysets = [frozenset(m["scenario_key"] for m in g) for g in result]
        assert frozenset({"c", "d"}) in keysets
        assert frozenset({"a"}) in keysets
        assert frozenset({"b"}) in keysets
        assert frozenset({"e"}) in keysets

    def test_no_group_is_ever_mixed_after_split(self):
        groups = [
            [_member("a", True), _member("b", False), _member("c", False)],
            [_member("d", True)],
        ]
        for g in tg.split_by_coachability(groups):
            assert len({m["is_coachable"] for m in g}) == 1

    def test_empty_input_returns_no_groups(self):
        assert tg.split_by_coachability([]) == []


def _member_c(key: str, coachable: bool, centroid: np.ndarray) -> dict:
    return {"scenario_key": key, "is_coachable": coachable, "centroid": centroid}


class TestTightenCoachableGroups:
    def test_all_sink_group_is_unchanged_regardless_of_spread(self):
        # Sinks tolerate coarse grouping fine -- only coachable groups get
        # re-clustered at the tight threshold.
        group = [
            _member_c("a", False, _angle_vec(0)),
            _member_c("b", False, _angle_vec(90)),
        ]
        assert tg.tighten_coachable_groups([group], tight_threshold=0.95) == [group]

    def test_cohesive_coachable_group_stays_together(self):
        group = [
            _member_c("a", True, _angle_vec(0)),
            _member_c("b", True, _angle_vec(1)),
        ]
        result = tg.tighten_coachable_groups([group], tight_threshold=0.95)
        assert len(result) == 1
        assert sorted(m["scenario_key"] for m in result[0]) == ["a", "b"]

    def test_loosely_related_coachable_group_splits_apart(self):
        # ~30 degrees apart (cosine ~0.87): clears the loose 0.75 threshold
        # that grouped them together in the first place, but not a tight 0.95
        # threshold -- exactly the "Client Discovery and Requirements" blob
        # confirmed in production, reproduced at unit-test scale.
        group = [
            _member_c("a", True, _angle_vec(0)),
            _member_c("b", True, _angle_vec(30)),
        ]
        result = tg.tighten_coachable_groups([group], tight_threshold=0.95)
        assert len(result) == 2
        keysets = [frozenset(m["scenario_key"] for m in g) for g in result]
        assert frozenset({"a"}) in keysets
        assert frozenset({"b"}) in keysets

    def test_singleton_group_is_unchanged(self):
        group = [_member_c("a", True, _angle_vec(0))]
        assert tg.tighten_coachable_groups([group], tight_threshold=0.95) == [group]

    def test_only_the_coachable_group_is_retightened_when_mixed_input_given(self):
        cohesive_sink = [_member_c("s1", False, _angle_vec(0)), _member_c("s2", False, _angle_vec(90))]
        splits_apart = [_member_c("a", True, _angle_vec(0)), _member_c("b", True, _angle_vec(30))]
        result = tg.tighten_coachable_groups([cohesive_sink, splits_apart], tight_threshold=0.95)
        assert cohesive_sink in result
        keysets = [frozenset(m["scenario_key"] for m in g) for g in result]
        assert frozenset({"a"}) in keysets
        assert frozenset({"b"}) in keysets

    def test_empty_input_returns_no_groups(self):
        assert tg.tighten_coachable_groups([], tight_threshold=0.95) == []


class TestMatchExistingPrimaryTopic:
    def test_no_candidates_returns_none(self):
        assert tg.match_existing_primary_topic(_angle_vec(0), [], np.empty((0, 2)), 0.85) is None

    def test_close_match_returns_its_key(self):
        keys = ["a", "b"]
        vecs = np.stack([_angle_vec(0), _angle_vec(90)])
        assert tg.match_existing_primary_topic(_angle_vec(1), keys, vecs, 0.85) == "a"

    def test_no_candidate_clears_threshold_returns_none(self):
        keys = ["a", "b"]
        vecs = np.stack([_angle_vec(0), _angle_vec(90)])
        # 45 degrees from both -- cosine ~0.707, below a strict 0.85 threshold.
        assert tg.match_existing_primary_topic(_angle_vec(45), keys, vecs, 0.85) is None

    def test_picks_the_single_best_match_when_multiple_clear_threshold(self):
        keys = ["far_but_ok", "closest"]
        vecs = np.stack([_angle_vec(20), _angle_vec(2)])
        assert tg.match_existing_primary_topic(_angle_vec(0), keys, vecs, 0.80) == "closest"


class TestTightenCoachableGroupsResplitOrdering:
    def test_resplitting_reorders_by_final_group_size(self):
        # Group A: two cohesive members (0, 2 deg) plus an outlier (60 deg)
        # that splits off. Group B: two cohesive members, presented second.
        # After A's outlier splits off, the largest surviving group (size 2)
        # may come from either A or B -- the result must stay size-sorted.
        group_a = [
            _member_c("a1", True, _angle_vec(0)),
            _member_c("a2", True, _angle_vec(2)),
            _member_c("outlier", True, _angle_vec(60)),
        ]
        group_b = [
            _member_c("b1", True, _angle_vec(120)),
            _member_c("b2", True, _angle_vec(122)),
        ]
        result = tg.tighten_coachable_groups([group_a, group_b], tight_threshold=0.95)
        sizes = [len(g) for g in result]
        assert sizes == sorted(sizes, reverse=True)
        assert sizes[0] == 2
