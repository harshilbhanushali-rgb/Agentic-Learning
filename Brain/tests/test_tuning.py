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
layer_b:
  relative_margin: 0.85
  max_scenarios_per_pair: 3
layer_c:
  milestone_relevance_percentile: 60
  min_milestone_call_fraction: 0.15
  min_milestone_calls_floor: 3
  milestone_hard_cap: 10
  min_cluster_size_fraction: 0.02
  min_cluster_size_floor: 3
  min_cluster_size_ceiling: 25
embedding:
  cache_enabled: true
  cache_path: embed_cache.db
"""


def _write(tmp_path, text):
    path = tmp_path / "tuning.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_file(tmp_path):
    t = load_tuning(_write(tmp_path, _GOOD))
    assert t.layer_a.min_call_support_floor == 4
    assert t.layer_c.milestone_hard_cap == 10
    assert t.embedding.cache_enabled is True


def test_shipped_tuning_yaml_is_valid():
    # The real file must always load -- this catches an edit that breaks the run.
    t = load_tuning()
    assert 0.0 < t.layer_a.ubiquity_ceiling <= 1.0
    assert 0.0 < t.layer_a.merge_cosine_threshold <= 1.0
    assert t.layer_c.min_milestone_calls_floor >= 1


def test_typo_in_key_raises_rather_than_defaulting(tmp_path):
    bad = _GOOD.replace("min_call_support_floor", "min_call_suport_floor")
    with pytest.raises(ValueError, match="unknown key"):
        load_tuning(_write(tmp_path, bad))


def test_missing_key_raises(tmp_path):
    bad = _GOOD.replace("  min_content_words: 5\n", "")
    with pytest.raises(ValueError, match="missing key"):
        load_tuning(_write(tmp_path, bad))


def test_unknown_section_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown top-level section"):
        load_tuning(_write(tmp_path, _GOOD + "\nlayer_z:\n  foo: 1\n"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tuning(tmp_path / "nope.yaml")
