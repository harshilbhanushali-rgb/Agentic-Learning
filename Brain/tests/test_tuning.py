"""Tests for tuning.yaml loading. A typo must fail loudly, never silently default."""
import pytest

from shared.tuning import load_tuning

_GOOD = """
layer_a:
  min_call_support_fraction: 0.02
  min_call_support_floor: 4
  ubiquity_ceiling: 0.4
  merge_cosine_threshold: 0.88
  min_content_words: 5
  pool_unit: clause
  grouping_method: post_hoc
  primary_topic_merge_threshold: 0.70
  response_taxonomy_purity_gate: 0.90
  response_taxonomy_auto_pass_enabled: false
  response_taxonomy_consensus_runs: 3
  response_taxonomy_candidate_match_overlap: 0.5
layer_b:
  relative_margin: 0.85
  max_scenarios_per_pair: 3
  matching_strategy: flat
  primary_topic_relative_margin: 0.95
  max_primary_topics_per_pair: 2
  two_stage_fallback_floor: 0.50
  sink_rescue_strategy: none
  sink_rescue_relative_margin: 0.95
  sink_rescue_response_min_similarity: 0.50
  sink_rescue_trigger_weak_floor: 0.50
  sink_rescue_blend_alpha: 0.6
  sink_rescue_density_threshold: 0.5
  sink_rescue_density_borderline_floor: 0.2
  sink_rescue_density_min_words: 3
layer_c:
  milestone_relevance_percentile: 60
  min_milestone_call_fraction: 0.15
  min_milestone_calls_floor: 3
  milestone_hard_cap: 10
  min_cluster_size_fraction: 0.02
  min_cluster_size_floor: 3
  min_cluster_size_ceiling: 25
  umap_n_components: 5
  milestone_sink_similarity_percentile: 95
  describe_mode: legacy
layer_d:
  signal_detection_mode: gemma
  scoring_unit: moment
  scenarios_per_request: 3
  similarity_relative_margin: 0.95
  max_scenarios_per_signal: 1
  gemma_scenario_shortlist_k: 0
  turn_match_mode: normalized
  turn_match_min_ratio: 0.85
  gap_events_enabled: true
  skip_uncoachable_milestones: true
  require_validated_milestones: false
  score_soft_skills: true
  gap_severity_critical_miss_rate: 0.60
  gap_severity_high_miss_rate: 0.35
  gap_severity_moderate_miss_rate: 0.15
embedding:
  cache_enabled: true
  cache_path: embed_cache.db
  backend: local
  gemini_model: gemini-embedding-2
  gemini_dimensions: 3072
  gemini_batch_size: 100
"""


def _write(tmp_path, text):
    path = tmp_path / "tuning.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_file(tmp_path):
    t = load_tuning(_write(tmp_path, _GOOD))
    assert t.layer_a.min_call_support_floor == 4
    assert t.layer_a.grouping_method == "post_hoc"
    assert t.layer_c.milestone_hard_cap == 10
    assert t.layer_d.signal_detection_mode == "gemma"
    assert t.layer_d.gemma_scenario_shortlist_k == 0
    assert t.embedding.cache_enabled is True


def test_shipped_tuning_yaml_is_valid():
    # The real file must always load -- this catches an edit that breaks the run.
    t = load_tuning()
    assert 0.0 < t.layer_a.ubiquity_ceiling <= 1.0
    assert 0.0 < t.layer_a.merge_cosine_threshold <= 1.0
    assert t.layer_a.grouping_method in ("post_hoc", "nested")
    assert 0.0 < t.layer_a.primary_topic_merge_threshold <= 1.0
    assert 0.0 < t.layer_a.response_taxonomy_purity_gate <= 1.0
    assert t.layer_a.response_taxonomy_auto_pass_enabled in (True, False)
    assert t.layer_a.response_taxonomy_consensus_runs >= 1
    assert 0.0 < t.layer_a.response_taxonomy_candidate_match_overlap <= 1.0
    assert t.layer_c.min_milestone_calls_floor >= 1
    assert t.layer_b.matching_strategy in ("flat", "strict", "soft", "fallback")
    assert t.layer_b.sink_rescue_strategy in (
        "none", "response_only", "or_rule", "blended", "content_gate_narrow",
    )
    assert 0.0 < t.layer_b.sink_rescue_relative_margin <= 1.0
    assert 0.0 < t.layer_b.sink_rescue_response_min_similarity <= 1.0
    assert 0.0 < t.layer_b.sink_rescue_trigger_weak_floor <= 1.0
    assert 0.0 < t.layer_b.sink_rescue_blend_alpha < 1.0
    assert 0.0 <= t.layer_b.sink_rescue_density_borderline_floor < t.layer_b.sink_rescue_density_threshold
    assert t.layer_b.sink_rescue_density_min_words >= 0
    assert t.layer_c.describe_mode in ("legacy", "situated")
    assert t.layer_d.signal_detection_mode in ("gemma", "similarity")
    assert t.layer_d.turn_match_mode in ("exact", "normalized", "ratio")
    assert 0.0 < t.layer_d.similarity_relative_margin <= 1.0
    assert 0.0 < t.layer_d.turn_match_min_ratio <= 1.0
    assert t.layer_d.max_scenarios_per_signal >= 1
    assert t.layer_d.gemma_scenario_shortlist_k >= 0
    assert t.layer_d.gap_events_enabled in (True, False)
    assert t.layer_d.score_soft_skills in (True, False)
    assert t.layer_d.skip_uncoachable_milestones in (True, False)
    # Severity buckets must be strictly descending, or compute_severity's first-match
    # loop silently makes the lower ones unreachable.
    assert (
        t.layer_d.gap_severity_critical_miss_rate
        > t.layer_d.gap_severity_high_miss_rate
        > t.layer_d.gap_severity_moderate_miss_rate
        > 0.0
    )


def test_typo_in_key_raises_rather_than_defaulting(tmp_path):
    bad = _GOOD.replace("min_call_support_floor", "min_call_suport_floor")
    with pytest.raises(ValueError, match="unknown key"):
        load_tuning(_write(tmp_path, bad))


def test_missing_key_raises(tmp_path):
    bad = _GOOD.replace("  min_content_words: 5\n", "")
    with pytest.raises(ValueError, match="missing key"):
        load_tuning(_write(tmp_path, bad))


def test_pool_unit_is_present_and_ships_clause():
    """The live file must keep the legacy unit until the turn arm passes its gate.

    Pinned because flipping it silently changes what the whole taxonomy is built
    from AND invalidates merge_cosine_threshold (different cosine band), so it
    must never move as a side effect of editing something near it.
    """
    t = load_tuning()
    assert t.layer_a.pool_unit == "clause"


def test_pool_unit_only_accepts_the_two_known_units(tmp_path):
    """load_tuning validates keys, not values, so the guard lives in
    build_client_pool -- this pins that a typo cannot reach the clustering.
    """
    from v2.layer_a import build_client_pool

    with pytest.raises(ValueError, match="pool_unit"):
        build_client_pool([], unit="sentences")


def test_unknown_section_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown top-level section"):
        load_tuning(_write(tmp_path, _GOOD + "\nlayer_z:\n  foo: 1\n"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tuning(tmp_path / "nope.yaml")
