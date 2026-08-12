"""Loader for tuning.yaml -- every pipeline threshold in one editable file.

Unknown or missing keys raise at load time. A silent default would mean a typo
in tuning.yaml quietly reverts a threshold the user believed they had changed,
which is the exact failure mode this file exists to prevent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent / "tuning.yaml"


@dataclass(frozen=True)
class LayerATuning:
    min_call_support_fraction: float
    min_call_support_floor: int
    ubiquity_ceiling: float
    merge_cosine_threshold: float
    min_content_words: int
    grouping_method: str
    primary_topic_merge_threshold: float
    response_taxonomy_purity_gate: float
    response_taxonomy_auto_pass_enabled: bool
    response_taxonomy_consensus_runs: int
    response_taxonomy_candidate_match_overlap: float


@dataclass(frozen=True)
class LayerBTuning:
    relative_margin: float
    max_scenarios_per_pair: int
    matching_strategy: str
    primary_topic_relative_margin: float
    max_primary_topics_per_pair: int
    two_stage_fallback_floor: float
    sink_rescue_strategy: str
    sink_rescue_relative_margin: float
    sink_rescue_response_min_similarity: float
    sink_rescue_trigger_weak_floor: float
    sink_rescue_blend_alpha: float
    sink_rescue_density_threshold: float
    sink_rescue_density_borderline_floor: float
    sink_rescue_density_min_words: int


@dataclass(frozen=True)
class LayerCTuning:
    milestone_relevance_percentile: float
    min_milestone_call_fraction: float
    min_milestone_calls_floor: int
    milestone_hard_cap: int
    min_cluster_size_fraction: float
    min_cluster_size_floor: int
    min_cluster_size_ceiling: int
    umap_n_components: int
    milestone_sink_similarity_percentile: float
    describe_mode: str


@dataclass(frozen=True)
class EmbeddingTuning:
    cache_enabled: bool
    cache_path: str


@dataclass(frozen=True)
class LayerDTuning:
    """Ego Trap / gap analysis. Replaces ego_trap/settings.py's os.environ reads.

    signal_detection_mode and turn_match_mode are strategy selectors (precedent:
    layer_b.matching_strategy); gap_events_enabled is a feature flag (precedent:
    layer_a.response_taxonomy_auto_pass_enabled). Everything else is a fraction or a
    cosine margin, i.e. a property of the data, per this file's own rule.

    Deliberately absent: the Gemma batch size and the benchmark-example count. Both
    are request/prompt packing rather than data properties, and the precedent for
    those is a module constant (v2/layer_c._DESCRIBE_BATCH_SIZE,
    _MAX_RUBRIC_RESPONSES), not a tuning key.
    """
    signal_detection_mode: str
    similarity_relative_margin: float
    max_scenarios_per_signal: int
    gemma_scenario_shortlist_k: int
    turn_match_mode: str
    turn_match_min_ratio: float
    gap_events_enabled: bool
    skip_uncoachable_milestones: bool
    require_validated_milestones: bool
    score_soft_skills: bool
    gap_severity_critical_miss_rate: float
    gap_severity_high_miss_rate: float
    gap_severity_moderate_miss_rate: float


@dataclass(frozen=True)
class Tuning:
    layer_a: LayerATuning
    layer_b: LayerBTuning
    layer_c: LayerCTuning
    layer_d: LayerDTuning
    embedding: EmbeddingTuning


_SECTIONS = {
    "layer_a": LayerATuning,
    "layer_b": LayerBTuning,
    "layer_c": LayerCTuning,
    "layer_d": LayerDTuning,
    "embedding": EmbeddingTuning,
}


def _build_section(name: str, cls, raw: dict):
    if not isinstance(raw, dict):
        raise ValueError(
            f"tuning.yaml: section {name} must be a mapping, got {type(raw).__name__}"
        )
    expected = {f.name for f in fields(cls)}
    got = set(raw)
    unknown = got - expected
    if unknown:
        raise ValueError(f"tuning.yaml: unknown key(s) in {name}: {sorted(unknown)}")
    missing = expected - got
    if missing:
        raise ValueError(f"tuning.yaml: missing key(s) in {name}: {sorted(missing)}")
    return cls(**raw)


def load_tuning(path: str | Path | None = None) -> Tuning:
    """Read and validate tuning.yaml. Override the path via BRAIN_TUNING_PATH."""
    resolved = Path(path or os.environ.get("BRAIN_TUNING_PATH") or _DEFAULT_PATH)
    if not resolved.exists():
        raise FileNotFoundError(f"tuning.yaml not found at {resolved}")

    raw = yaml.safe_load(resolved.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"tuning.yaml: top level must be a mapping, got {type(raw).__name__}"
        )

    unknown = set(raw) - set(_SECTIONS)
    if unknown:
        raise ValueError(f"tuning.yaml: unknown top-level section(s): {sorted(unknown)}")
    missing = set(_SECTIONS) - set(raw)
    if missing:
        raise ValueError(f"tuning.yaml: missing top-level section(s): {sorted(missing)}")

    return Tuning(
        **{name: _build_section(name, cls, raw[name]) for name, cls in _SECTIONS.items()}
    )


_cached: Tuning | None = None


def get_tuning() -> Tuning:
    """Process-wide singleton. Use this from pipeline code; load_tuning in tests."""
    global _cached
    if _cached is None:
        _cached = load_tuning()
    return _cached
