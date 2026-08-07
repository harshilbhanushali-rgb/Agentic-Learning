"""Evidence-based triage of clusters, shared by Layer A and Layer C.

The pipeline discovers structure by clustering surface-text embeddings, which
finds whatever is frequent -- including backchannel. Rather than trying to
filter ~40,000 utterances before clustering (impossible to do exhaustively),
this module judges the ~150 resulting clusters, which is cheap enough to afford
real evidence.

Call coverage is the main signal, but it is a signal about *what to scrutinise*,
not a verdict. A cluster spanning most of the corpus is either conversational
mechanics (backchannel, greetings) or a core business topic that genuinely comes
up in every call -- and coverage alone cannot tell those apart. The calibration
sweep proved the point: at every operating point roughly half of all clusters
sat above the ceiling, which is not a plausible mechanics rate. So high coverage
routes a cluster to LLM adjudication with its stats attached, and the LLM makes
the call.

The one verdict decided here without an LLM is insufficient_evidence: a cluster
too thin to support any claim of recurrence is dropped before it costs a Gemma
call.

All functions here are pure. Thresholds come from tuning.yaml via the caller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# triage() verdicts.
SCENARIO_CANDIDATE = "scenario_candidate"
NEEDS_REVIEW = "needs_review"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"

# cluster_kind values written to scenarios.cluster_kind. Only the LLM assigns
# MECHANICS or LOGISTICS -- triage() never does.
KIND_SCENARIO = "scenario"
KIND_MECHANICS = "mechanics"
KIND_LOGISTICS = "logistics"

_nlp = None


@dataclass(frozen=True)
class ClusterStats:
    n_items: int
    distinct_calls: int
    call_coverage: float
    mean_len: float
    cohesion: float
    centroid: np.ndarray


def _unit(vec: np.ndarray) -> np.ndarray:
    return vec / (np.linalg.norm(vec) + 1e-10)


def support_stats(
    call_ids: list[str],
    vecs: np.ndarray,
    total_calls: int,
    texts: list[str] | None = None,
) -> ClusterStats:
    """Summarise one cluster. call_ids and vecs are parallel, one entry per member."""
    if len(call_ids) != len(vecs):
        raise ValueError(
            f"call_ids and vecs must be parallel, got {len(call_ids)} and {len(vecs)}"
        )
    if total_calls <= 0:
        raise ValueError(f"total_calls must be positive, got {total_calls}")

    arr = np.asarray(vecs, dtype=np.float32)
    centroid = _unit(arr.mean(axis=0))
    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    distinct = len(set(call_ids))
    mean_len = float(np.mean([len(t.split()) for t in texts])) if texts else 0.0

    return ClusterStats(
        n_items=len(call_ids),
        distinct_calls=distinct,
        call_coverage=distinct / total_calls,
        mean_len=mean_len,
        cohesion=float(np.mean(normed @ centroid)),
        centroid=centroid,
    )


def merge_by_similarity(centroids: np.ndarray, threshold: float) -> list[list[int]]:
    """Group centroid indices whose average-linkage cosine similarity clears threshold.

    Replaces a count-based cap. A count cannot express "no duplicates" -- it
    halts at N whether duplication remains or not, and merges the rarest
    clusters first, which is the opposite end of the distribution from the
    backchannel families that actually duplicate.
    """
    from sklearn.cluster import AgglomerativeClustering

    arr = np.asarray(centroids, dtype=np.float32)
    if len(arr) == 0:
        return []
    if len(arr) == 1:
        return [[0]]

    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    model = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=1.0 - threshold,
    )
    labels = model.fit_predict(normed)

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        groups.setdefault(int(label), []).append(idx)
    return [sorted(g) for g in groups.values()]


def required_call_support(total_calls: int, fraction: float, floor: int) -> int:
    """Distinct calls a cluster must span to count as evidence, scaled to corpus size.

    An absolute count does not scale. At 416 calls a floor of 4 is inert, because
    BERTopic min_cluster_size is already 50 clauses at that corpus size, so every
    surviving cluster trivially spans more than 4 calls.
    """
    return max(floor, math.ceil(fraction * max(total_calls, 0)))


def triage(stats: ClusterStats, min_call_support: int, ubiquity_ceiling: float) -> str:
    """Route a cluster from its evidence alone. No text inspection, no LLM.

    Only INSUFFICIENT_EVIDENCE is terminal. NEEDS_REVIEW means "broad enough that
    it might be mechanics" -- it is handed to the LLM with its coverage stats, not
    discarded. Treating high coverage as an automatic mechanics verdict
    misclassified core business topics that legitimately recur in most calls.
    """
    if stats.distinct_calls < min_call_support:
        return INSUFFICIENT_EVIDENCE
    if stats.call_coverage > ubiquity_ceiling:
        return NEEDS_REVIEW
    return SCENARIO_CANDIDATE


def milestone_cluster_centroid(vecs: np.ndarray) -> np.ndarray:
    """Unit-normalized centroid of a milestone candidate cluster's member embeddings.

    Same construction as support_stats' centroid, but standalone: Layer C needs
    this before the call-support gate runs, not bundled with call-coverage stats.
    """
    return _unit(np.asarray(vecs, dtype=np.float32).mean(axis=0))


def nearest_sink_index(centroid: np.ndarray, sink_centroids: np.ndarray) -> tuple[int, float]:
    """Index and cosine similarity of the sink-scenario centroid nearest a milestone
    cluster's own centroid. Both must already be unit-normalized and share the same
    embedding space (bge document embeddings of scenario descriptions vs. of
    response clauses).

    This is a soft review-flag signal, not a rejection filter: the measured
    similarity band between real milestones and backchannel has no clean
    separation cliff, so the caller only flags for LLM review at the upper tail.
    """
    if len(sink_centroids) == 0:
        raise ValueError("sink_centroids must not be empty -- there is nothing to compare against")
    sims = np.asarray(sink_centroids, dtype=np.float32) @ np.asarray(centroid, dtype=np.float32)
    best = int(np.argmax(sims))
    return best, float(sims[best])


def review_flag_threshold(similarities: list[float], percentile: float) -> float:
    """Self-scaling review-flag cutoff: the given percentile of a run's WHOLE
    candidate-cluster sink-similarity population, computed live rather than
    hardcoded -- consistent with every other threshold in this file.
    """
    if not similarities:
        raise ValueError("similarities must not be empty -- there is no population to derive a percentile from")
    return float(np.percentile(np.asarray(similarities, dtype=np.float32), percentile))


def required_milestone_support(
    scenario_call_count: int, fraction: float, floor: int
) -> int:
    """Distinct calls a milestone must appear in to count as recurring.

    Scales with the scenario, so a 200-call scenario cannot accumulate
    milestones merely by being large -- which is the pairs=212 to
    milestones=95 pathology.
    """
    return max(floor, math.ceil(fraction * max(scenario_call_count, 0)))


def milestone_min_cluster_size(
    pool_size: int, fraction: float, floor: int, ceiling: int
) -> int:
    """HDBSCAN min_cluster_size scaled to the clause pool, clamped to sane bounds."""
    return int(max(floor, min(ceiling, round(fraction * pool_size))))


def is_substantive(text: str, min_content_words: int) -> bool:
    """Cheap pre-filter: enough non-stopword alphabetic tokens to carry content.

    Deliberately weak. It removes bare "Perfect." and "Yeah." and nothing more.
    Garbled mid-thought fragments clear this bar easily, which is why cluster
    triage above -- not this function -- is the real defence.
    """
    global _nlp
    if _nlp is None:
        import spacy

        _nlp = spacy.load("en_core_web_lg", disable=["parser", "ner"])
    doc = _nlp(text)
    return sum(1 for t in doc if t.is_alpha and not t.is_stop) >= min_content_words


def passes_reconciliation_gate(nearest_coachable_sim: float, merge_cosine_threshold: float) -> bool:
    """True iff a candidate homeless-topic cluster is genuinely distinct from its
    nearest existing coachable scenario, using the SAME threshold this codebase
    already uses to decide "duplicate or genuinely distinct" for subtopic dedup
    (merge_cosine_threshold). No new threshold -- the existing one already draws
    the right line here.

    A cluster that fails this must be SKIPPED by its caller, never force-routed
    into the near-neighbor scenario -- that is the exact failure mode the
    sink-pool diagnostic's by_cluster variant was rejected for (destructive
    milestone merges from routing content into a near-but-wrong scenario).
    """
    return nearest_coachable_sim < merge_cosine_threshold
