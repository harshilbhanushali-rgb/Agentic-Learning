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


@dataclass(frozen=True)
class LayerBTuning:
    relative_margin: float
    max_scenarios_per_pair: int


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


@dataclass(frozen=True)
class EmbeddingTuning:
    cache_enabled: bool
    cache_path: str


@dataclass(frozen=True)
class Tuning:
    layer_a: LayerATuning
    layer_b: LayerBTuning
    layer_c: LayerCTuning
    embedding: EmbeddingTuning


_SECTIONS = {
    "layer_a": LayerATuning,
    "layer_b": LayerBTuning,
    "layer_c": LayerCTuning,
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
