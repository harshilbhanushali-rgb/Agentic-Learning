"""Unit tests for evidence-based cluster triage. Pure functions, no I/O."""
import numpy as np
import pytest

from shared import cluster_evidence as ce


def _vec(*components):
    return np.array(components, dtype=np.float32)


class TestSupportStats:
    def test_counts_distinct_calls_not_items(self):
        # Five clauses but only two calls -- support is 2, not 5.
        stats = ce.support_stats(
            ["a", "a", "a", "b", "b"],
            np.tile(_vec(1.0, 0.0), (5, 1)),
            total_calls=10,
        )
        assert stats.n_items == 5
        assert stats.distinct_calls == 2
        assert stats.call_coverage == pytest.approx(0.2)

    def test_centroid_is_unit_length(self):
        stats = ce.support_stats(["a", "b"], np.array([[3.0, 0.0], [0.0, 4.0]]), total_calls=2)
        assert np.linalg.norm(stats.centroid) == pytest.approx(1.0, abs=1e-5)

    def test_cohesion_is_one_for_identical_vectors(self):
        stats = ce.support_stats(["a", "b"], np.tile(_vec(1.0, 1.0), (2, 1)), total_calls=2)
        assert stats.cohesion == pytest.approx(1.0, abs=1e-5)

    def test_mean_len_only_when_texts_given(self):
        vecs = np.tile(_vec(1.0, 0.0), (2, 1))
        assert ce.support_stats(["a", "b"], vecs, 2).mean_len == 0.0
        with_texts = ce.support_stats(["a", "b"], vecs, 2, texts=["one two", "three four five six"])
        assert with_texts.mean_len == pytest.approx(3.0)

    def test_rejects_mismatched_parallel_lists(self):
        with pytest.raises(ValueError, match="parallel"):
            ce.support_stats(["a"], np.tile(_vec(1.0, 0.0), (2, 1)), total_calls=2)

    def test_rejects_nonpositive_total_calls(self):
        with pytest.raises(ValueError, match="positive"):
            ce.support_stats(["a"], _vec(1.0, 0.0).reshape(1, 2), total_calls=0)


class TestMergeBySimilarity:
    def test_identical_centroids_merge(self):
        centroids = np.tile(_vec(1.0, 0.0), (3, 1))
        groups = ce.merge_by_similarity(centroids, threshold=0.88)
        assert groups == [[0, 1, 2]]

    def test_orthogonal_centroids_stay_separate(self):
        centroids = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        groups = ce.merge_by_similarity(centroids, threshold=0.88)
        assert sorted(groups) == [[0], [1]]

    def test_threshold_controls_aggressiveness(self):
        # Two centroids about 0.95 cosine apart.
        centroids = np.array([[1.0, 0.0], [0.95, 0.31]], dtype=np.float32)
        assert len(ce.merge_by_similarity(centroids, threshold=0.90)) == 1
        assert len(ce.merge_by_similarity(centroids, threshold=0.99)) == 2

    def test_handles_degenerate_inputs(self):
        assert ce.merge_by_similarity(np.empty((0, 2)), 0.88) == []
        assert ce.merge_by_similarity(_vec(1.0, 0.0).reshape(1, 2), 0.88) == [[0]]

    def test_every_index_appears_exactly_once(self):
        rng = np.random.default_rng(0)
        centroids = rng.normal(size=(12, 8)).astype(np.float32)
        flat = [i for g in ce.merge_by_similarity(centroids, 0.88) for i in g]
        assert sorted(flat) == list(range(12))


class TestTriage:
    def _stats(self, distinct_calls, total_calls):
        return ce.support_stats(
            [str(i) for i in range(distinct_calls)],
            np.tile(_vec(1.0, 0.0), (distinct_calls, 1)),
            total_calls=total_calls,
        )

    def test_thin_evidence_is_dropped(self):
        assert ce.triage(self._stats(2, 100), min_call_support=4, ubiquity_ceiling=0.4) == ce.INSUFFICIENT_EVIDENCE

    def test_ubiquitous_cluster_is_flagged_for_review_not_condemned(self):
        # Present in 90 of 100 calls. That is suspicious enough to audit, but it
        # could equally be a core business topic, so the LLM decides -- triage
        # must not return a terminal mechanics verdict on coverage alone.
        assert ce.triage(self._stats(90, 100), min_call_support=4, ubiquity_ceiling=0.4) == ce.NEEDS_REVIEW

    def test_well_evidenced_specific_cluster_survives(self):
        assert ce.triage(self._stats(15, 100), min_call_support=4, ubiquity_ceiling=0.4) == ce.SCENARIO_CANDIDATE

    def test_thin_evidence_wins_over_ubiquity(self):
        # 3 of 4 calls is 75 percent coverage, but 3 calls is still too thin.
        assert ce.triage(self._stats(3, 4), min_call_support=4, ubiquity_ceiling=0.4) == ce.INSUFFICIENT_EVIDENCE


class TestMilestoneSupport:
    def test_scales_with_scenario_size(self):
        # This is what stops a 200-call scenario accruing milestones by volume.
        assert ce.required_milestone_support(200, fraction=0.15, floor=3) == 30
        assert ce.required_milestone_support(6, fraction=0.15, floor=3) == 3

    def test_floor_applies_to_small_scenarios(self):
        assert ce.required_milestone_support(1, fraction=0.15, floor=3) == 3
        assert ce.required_milestone_support(0, fraction=0.15, floor=3) == 3

    def test_rounds_up_not_down(self):
        assert ce.required_milestone_support(41, fraction=0.15, floor=1) == 7

    def test_min_cluster_size_is_clamped(self):
        assert ce.milestone_min_cluster_size(10, 0.02, floor=3, ceiling=25) == 3
        assert ce.milestone_min_cluster_size(10_000, 0.02, floor=3, ceiling=25) == 25
        assert ce.milestone_min_cluster_size(500, 0.02, floor=3, ceiling=25) == 10
