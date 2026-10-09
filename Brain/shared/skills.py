"""Skills: the axes a CSM profile can actually be built on.

Design: docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md section 5.

THE PROBLEM THIS SOLVES. The profile today has 405 axes -- one per milestone -- and
20-50 calls per person yields roughly 8 observations each. That is far too thin to say
anything about anyone, and no improvement in criterion quality fixes it; it is
arithmetic. Every other failure measured on 2026-08-12 traces back to it: the +/-0.05
decision band sitting at a third the size of its own noise, per-scenario verdicts
agreeing only 41-47% across runs, per-milestone gates tripping on a single stray partial
hit.

Grouping coverage areas into a smaller set of recurring BEHAVIOURS pools their
observations. A skill appearing in 30 scenarios pools all 30 scenarios' evidence.

WHY THE TOPIC MUST BE STRIPPED FIRST. Measured 2026-08-12 on the real 405 descriptions:
clustering them as written groups them by SUBJECT, not behaviour -- 290 of 338 clusters
held a single scenario, and "ask open questions about budget" separated from "ask open
questions about screening" purely on the topical object. bge embeddings are dominated by
topic. Stripping the object is what makes behavioural similarity visible at all.

NO TARGET COUNT. The number of skills is an OUTPUT, never a parameter. A threshold in
this codebase is never a count of outputs -- MAX_CLUSTERS=150 is the cautionary tale,
because a count halts at N whether duplication remains or not. The granularity is chosen
by sweeping a cosine threshold and measuring what each one produces.

Pure -- no Gemma, no DB. The abstraction prompt lives in shared/prompts.py; the sweep and
the Gemma call live in the calibration harness.
"""
from __future__ import annotations

import numpy as np

UNASSIGNED = "unassigned"


def cluster_behaviours(vectors: np.ndarray, threshold: float) -> list[int]:
    """Greedy nearest-centroid grouping of topic-stripped behaviour vectors.

    Returns a group index per input. Deliberately NOT UMAP+HDBSCAN: that pipeline is
    documented non-reproducible across process launches (385/398/403/404 milestones for
    byte-identical input), and a skill vocabulary that reshuffles between runs cannot
    carry a profile. This is deterministic given the same input order.

    Greedy assignment means the result depends on input order, so callers must feed a
    stable order -- the same reason group_describe_items_by_scenario preserves insertion
    order.
    """
    if len(vectors) == 0:
        return []
    normed = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    centroids: list[np.ndarray] = []
    counts: list[int] = []
    labels: list[int] = []
    for vec in normed:
        if centroids:
            sims = np.asarray(centroids) @ vec
            best = int(np.argmax(sims))
            if sims[best] >= threshold:
                labels.append(best)
                # Running mean, renormalised: a centroid must stay a unit vector or the
                # threshold silently means something different as the group grows.
                merged = (np.asarray(centroids[best]) * counts[best] + vec) / (counts[best] + 1)
                centroids[best] = merged / (np.linalg.norm(merged) + 1e-10)
                counts[best] += 1
                continue
        centroids.append(vec)
        counts.append(1)
        labels.append(len(centroids) - 1)
    return labels


def summarise_groups(labels: list[int], scenario_keys: list[str]) -> list[dict]:
    """Per-group size and scenario span, in group-index order.

    scenario_span is the number that decides whether skills exist at all. A group living
    inside ONE scenario is just a coverage area again -- it pools nothing, so it cannot
    fix the eight-observations-per-axis problem this module exists for.
    """
    groups: dict[int, list[int]] = {}
    for i, label in enumerate(labels):
        groups.setdefault(label, []).append(i)
    return [
        {
            "group": label,
            "members": members,
            "size": len(members),
            "scenario_span": len({scenario_keys[i] for i in members}),
        }
        for label, members in sorted(groups.items())
    ]


def sweep(vectors: np.ndarray, scenario_keys: list[str],
          thresholds: list[float]) -> list[dict]:
    """One pass measuring every candidate granularity, like Layer C's own grid sweep.

    Reports, per threshold: how many groups, how far they span, and what fraction of
    items land in a group spanning multiple scenarios. Selecting a row afterwards needs
    no re-run.

    n_skills is reported, never targeted. cross_scenario_coverage is the load-bearing
    figure -- if it stays near zero at every threshold, behavioural skills do not exist
    in this corpus at a usable granularity and the whole approach fails honestly rather
    than being tuned into existence.
    """
    out = []
    for threshold in thresholds:
        labels = cluster_behaviours(vectors, threshold)
        groups = summarise_groups(labels, scenario_keys)
        multi = [g for g in groups if g["scenario_span"] > 1]
        wide = [g for g in groups if g["scenario_span"] >= 5]
        covered = sum(g["size"] for g in multi)
        out.append({
            "threshold": threshold,
            "n_skills": len(groups),
            "n_multi_scenario": len(multi),
            "n_spanning_5plus": len(wide),
            "max_span": max((g["scenario_span"] for g in groups), default=0),
            "median_size": float(np.median([g["size"] for g in groups])) if groups else 0.0,
            "cross_scenario_coverage": covered / len(labels) if labels else 0.0,
        })
    return out


def assign_to_vocabulary(vectors: np.ndarray, vocab_centroids: np.ndarray,
                         vocab_ids: list[str], threshold: float) -> list[str]:
    """Place new coverage areas into an EXISTING skill vocabulary.

    This is what lets a profile survive a Layer C re-run. Cluster identity is not stable
    across runs, so a skill defined by its membership would be reshuffled and every
    profile built on it orphaned. Defining skills by their text and assigning into them
    keeps the vocabulary fixed while the clusters underneath churn freely.

    Direct precedent: shared/topic_grouping.py::match_existing_primary_topic, which
    exists because graduate_sink_topics.py was writing primary_topic_key = None and
    permanently orphaning rows.

    Anything below threshold lands in UNASSIGNED rather than being forced into the
    nearest skill. That bucket is the signal the vocabulary needs re-deriving -- silently
    absorbing novel behaviour is how a taxonomy stops describing its data without anyone
    noticing.
    """
    if len(vectors) == 0:
        return []
    if len(vocab_centroids) == 0:
        return [UNASSIGNED] * len(vectors)
    normed = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    centroids = vocab_centroids / (
        np.linalg.norm(vocab_centroids, axis=1, keepdims=True) + 1e-10)
    sims = normed @ centroids.T
    best = np.argmax(sims, axis=1)
    return [vocab_ids[int(j)] if sims[i][int(j)] >= threshold else UNASSIGNED
            for i, j in enumerate(best)]


def grid(assignments: list[str], topics: list[str]) -> dict:
    """The skill x topic grid: counts per cell, plus both margins.

    Read three ways. A ROW (a skill across all topics) and a COLUMN (a topic across all
    skills) each pool many observations and are the trustworthy part. A CELL is thin by
    construction and is the interesting detail -- shown only where its row and column
    both have support.
    """
    cells: dict[str, dict[str, int]] = {}
    row_totals: dict[str, int] = {}
    col_totals: dict[str, int] = {}
    for skill, topic in zip(assignments, topics):
        cells.setdefault(skill, {}).setdefault(topic, 0)
        cells[skill][topic] += 1
        row_totals[skill] = row_totals.get(skill, 0) + 1
        col_totals[topic] = col_totals.get(topic, 0) + 1
    return {"cells": cells, "row_totals": row_totals, "col_totals": col_totals,
            "n": len(assignments)}
