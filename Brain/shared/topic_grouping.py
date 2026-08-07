"""Grouping subtopic clusters into primary-topic macro-groups.

scenarios.primary_topic today is not a real grouping: it is a free-text string
independently invented by Gemma once per subtopic cluster, with no dedup or
shared identity across clusters. This module builds the actual parent grouping,
via two independently calibratable mechanisms that both reduce to the same
primitive Layer A already uses for subtopic dedup -- merge_by_similarity, at a
looser threshold than subtopic dedup's own.

Both functions here are pure: no I/O, no Gemma calls, thresholds passed in by
the caller from tuning.yaml. Labelling a group (turning it into a `label`/
`description`/`keyphrases` primary_topics row) is a separate, Gemma-backed step
that lives in v2/layer_a.py -- this module only decides which subtopics belong
together.
"""
from __future__ import annotations

import numpy as np

from shared import cluster_evidence


def group_post_hoc(subtopic_records: list[dict], threshold: float) -> list[list[str]]:
    """Group subtopic scenario_keys into primary_topic groups by centroid similarity.

    Runs AFTER today's per-subtopic adjudication loop finishes -- dedup via
    merge_into, coachable/mechanics/logistics triage, all unchanged. Reuses
    merge_by_similarity a second time, at a looser threshold than the 0.85 used
    for subtopic dedup, over the resulting subtopic centroids (each record must
    carry "scenario_key" and "centroid").

    Returns groups of scenario_key, largest-first, matching _merged_clusters'
    existing ordering convention.
    """
    if not subtopic_records:
        return []
    centroids = np.stack([r["centroid"] for r in subtopic_records])
    groups = cluster_evidence.merge_by_similarity(centroids, threshold)
    groups.sort(key=len, reverse=True)
    return [[subtopic_records[i]["scenario_key"] for i in group] for group in groups]


def group_nested(
    raw_centroids: np.ndarray, loose_threshold: float, tight_threshold: float,
) -> list[list[list[int]]]:
    """Two-level clustering over RAW (pre-subtopic-merge) BERTopic centroids.

    A loose merge finds macro-groups first; within each macro-group, a second
    merge at subtopic dedup's own (tight) threshold finds the subtopic clusters
    nested inside it. This is the alternative to group_post_hoc: instead of
    merging already-adjudicated subtopics into macro-groups after the fact, it
    decides the hierarchy before any subtopic exists, so a raw topic can never
    end up paired with a subtopic sibling from the wrong macro-group.

    Returns macro-groups, each a list of subtopic-level raw-index groups:
    [[[raw_idx, ...], [raw_idx, ...]], ...]. Flattening one level reproduces
    exactly what a single flat tight-threshold merge over ALL raw centroids
    would find restricted to each macro-group's members -- nested grouping can
    only partition raw topics differently across macro-group boundaries, never
    invent or lose one relative to the flat path.
    """
    if len(raw_centroids) == 0:
        return []
    macro_groups = cluster_evidence.merge_by_similarity(raw_centroids, loose_threshold)
    macro_groups.sort(key=len, reverse=True)

    nested: list[list[list[int]]] = []
    for macro in macro_groups:
        macro_centroids = np.asarray(raw_centroids)[macro]
        sub_groups = cluster_evidence.merge_by_similarity(macro_centroids, tight_threshold)
        # sub_groups holds indices into macro_centroids -- translate back to
        # indices into the original raw_centroids array.
        nested.append([[macro[i] for i in sub] for sub in sub_groups])
    return nested


def split_by_coachability(groups: list[list[dict]]) -> list[list[dict]]:
    """Split any primary-topic group whose members are not all the same
    is_coachable status into homogeneous coachable-only / non-coachable-only
    groups.

    Centroid-similarity grouping decides membership from geometry alone and
    can fuse a coachable subtopic with a sink subtopic when their centroids
    converge toward a generic "conversation" direction under averaging --
    confirmed on real data (a 22-member primary_topic mixing 6 coachable
    scenarios with 16 mechanics sinks). is_coachable is already known by the
    time this runs (grouping is a separate pass after adjudication finishes),
    so this is a free, zero-Gemma correction: it can only ever split a group,
    never merge one, so it cannot introduce a new failure mode beyond what
    grouping already decided.

    Returns groups re-sorted largest-first, matching the existing convention.
    """
    result: list[list[dict]] = []
    for group in groups:
        coachable = [m for m in group if m["is_coachable"]]
        not_coachable = [m for m in group if not m["is_coachable"]]
        if coachable:
            result.append(coachable)
        if not_coachable:
            result.append(not_coachable)
    result.sort(key=len, reverse=True)
    return result


def match_existing_primary_topic(
    centroid: np.ndarray, candidate_keys: list[str], candidate_vecs, threshold: float,
) -> str | None:
    """Nearest-neighbor match of a single new embedding against an existing primary_topics
    population, for assigning a graduated scenario's primary_topic_key.

    Reuses the one-vs-population cosine-argmax-plus-threshold shape this module and
    cluster_evidence.py already use elsewhere (cluster_evidence.nearest_sink_index is the
    closest existing analogue) rather than reaching for merge_by_similarity, which groups a
    whole population pairwise -- overkill for matching one new item against an
    already-fixed set of candidates.

    Returns None when there are no candidates, or when the best match does not clear
    threshold -- both cases mean the caller should create a new primary_topics row instead
    of reusing one.
    """
    if len(candidate_keys) == 0:
        return None
    c = np.asarray(centroid, dtype=np.float32)
    c = c / (np.linalg.norm(c) + 1e-10)
    arr = np.asarray(candidate_vecs, dtype=np.float32)
    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    sims = normed @ c
    best = int(np.argmax(sims))
    if float(sims[best]) < threshold:
        return None
    return candidate_keys[best]


def tighten_coachable_groups(groups: list[list[dict]], tight_threshold: float) -> list[list[dict]]:
    """Re-cluster every all-coachable group at the tight (subtopic-dedup) threshold.

    Loose primary-topic grouping can fuse business scenarios that only share a
    generic "conversation" direction under centroid averaging -- confirmed on
    real production data (a 21-member "Client Discovery and Requirements" group
    spanning budget disclosure, ATS integration, job-board ecosystem, and URL
    redirection config, none of which share real content). Sink-only groups
    tolerate coarse grouping fine -- mixing two junk families together under one
    umbrella is harmless, since no rubric is ever generated from them -- so only
    all-coachable groups are re-clustered here.

    Deliberately not gated on group size: a member-count ceiling is the exact
    anti-pattern the old MAX_CLUSTERS=150 cap already proved wrong (it halts at
    N whether duplication remains or not). Coachability is the data property
    that decides eligibility; a small cohesive group simply survives the
    re-cluster unchanged.

    Each member dict must carry "centroid" and "is_coachable". Runs after
    split_by_coachability, so every input group is already homogeneous -- like
    that function, this can only ever split a group further, never merge
    across groups or touch a sink group, so it cannot introduce a new failure
    mode beyond what the loose grouping already decided.
    """
    result: list[list[dict]] = []
    for group in groups:
        if len(group) <= 1 or not all(m["is_coachable"] for m in group):
            result.append(group)
            continue
        centroids = np.stack([m["centroid"] for m in group])
        sub_idx_groups = cluster_evidence.merge_by_similarity(centroids, tight_threshold)
        result.extend([group[i] for i in idxs] for idxs in sub_idx_groups)
    result.sort(key=len, reverse=True)
    return result
