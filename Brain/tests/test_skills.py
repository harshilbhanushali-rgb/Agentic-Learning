"""Tests for shared/skills.py -- option 1 of the profile-rebuild design.

Hand-built orthogonal unit vectors throughout, never the embedding model. That is the
test_layer_b_assignment precedent: testing the RULE rather than bge's behaviour is what
makes these assertions mean something at any embedding version.

The number that decides whether skills exist at all is scenario_span. A group living
inside one scenario pools nothing, so it cannot fix the eight-observations-per-axis
problem this module exists for -- and measured on the real 405 descriptions, 290 of 338
clusters were exactly that.
"""
from __future__ import annotations

import numpy as np
import pytest

from shared import skills


def _unit(*components) -> np.ndarray:
    v = np.asarray(components, dtype=np.float32)
    return v / np.linalg.norm(v)


# Three mutually orthogonal directions -- "behaviours" that share nothing.
_A, _B, _C = _unit(1, 0, 0), _unit(0, 1, 0), _unit(0, 0, 1)
_A_NEAR = _unit(0.98, 0.2, 0)      # same behaviour, different wording


# --- clustering ---------------------------------------------------------------------------

def test_identical_behaviours_land_in_one_group():
    labels = skills.cluster_behaviours(np.stack([_A, _A, _A]), threshold=0.8)
    assert len(set(labels)) == 1


def test_orthogonal_behaviours_never_merge():
    labels = skills.cluster_behaviours(np.stack([_A, _B, _C]), threshold=0.8)
    assert len(set(labels)) == 3


def test_a_near_duplicate_joins_its_group():
    labels = skills.cluster_behaviours(np.stack([_A, _A_NEAR, _B]), threshold=0.8)
    assert labels[0] == labels[1] != labels[2]


def test_a_higher_threshold_splits_what_a_lower_one_merged():
    """The tension the sweep exists to expose: coarser pools more observations, finer
    keeps skills sharper. Neither is right a priori, which is why it is measured."""
    vecs = np.stack([_A, _A_NEAR])
    assert len(set(skills.cluster_behaviours(vecs, 0.8))) == 1
    assert len(set(skills.cluster_behaviours(vecs, 0.999))) == 2


def test_clustering_is_deterministic_for_the_same_input_order():
    """UMAP+HDBSCAN is documented non-reproducible across process launches, and a skill
    vocabulary that reshuffles between runs cannot carry a profile. This must not."""
    vecs = np.stack([_A, _B, _A_NEAR, _C])
    assert skills.cluster_behaviours(vecs, 0.8) == skills.cluster_behaviours(vecs, 0.8)


def test_an_empty_input_produces_no_labels():
    assert skills.cluster_behaviours(np.empty((0, 3)), 0.8) == []


def test_a_growing_group_keeps_a_unit_centroid():
    """If a centroid stops being unit-length the threshold silently means something
    different as the group grows -- a knob that drifts while looking fixed.

    The spread matters. Near-identical vectors average to a near-unit mean, so they pass
    whether or not the centroid is renormalised -- an earlier version of this test used
    them and did NOT catch the bug, proven by deleting the renormalisation and watching
    it still pass. These vectors are far enough apart that the un-normalised mean shrinks
    below the threshold while the true cosine stays above it.
    """
    spread = np.stack([
        _unit(1, 0, 0), _unit(1, 0.45, 0), _unit(1, 0, 0.45),
        _unit(1, 0.45, 0.45), _unit(1, 0.30, 0.30),
    ])
    assert len(set(skills.cluster_behaviours(spread, 0.88))) == 1


# --- span, the number that decides everything ---------------------------------------------

def test_a_group_confined_to_one_scenario_reports_span_one():
    """This is the failure case. Such a group is a coverage area again: it pools nothing
    and cannot fix the observations-per-axis problem."""
    labels = skills.cluster_behaviours(np.stack([_A, _A]), 0.8)
    groups = skills.summarise_groups(labels, ["alpha", "alpha"])

    assert groups[0]["scenario_span"] == 1


def test_a_behaviour_recurring_across_scenarios_reports_a_real_span():
    labels = skills.cluster_behaviours(np.stack([_A, _A_NEAR, _A]), 0.8)
    groups = skills.summarise_groups(labels, ["alpha", "beta", "gamma"])

    assert groups[0]["scenario_span"] == 3 and groups[0]["size"] == 3


def test_every_item_appears_in_exactly_one_group():
    labels = skills.cluster_behaviours(np.stack([_A, _B, _A_NEAR, _C]), 0.8)
    groups = skills.summarise_groups(labels, ["a", "b", "c", "d"])

    assert sorted(i for g in groups for i in g["members"]) == [0, 1, 2, 3]


# --- the sweep ------------------------------------------------------------------------------

def test_the_sweep_measures_every_threshold_in_one_pass():
    vecs = np.stack([_A, _A_NEAR, _B, _C])
    rows = skills.sweep(vecs, ["a", "b", "c", "d"], [0.5, 0.8, 0.999])

    assert [r["threshold"] for r in rows] == [0.5, 0.8, 0.999]


def test_the_sweep_reports_the_skill_count_rather_than_targeting_it():
    """No target count anywhere: MAX_CLUSTERS=150 is the cautionary tale, because a count
    halts at N whether duplication remains or not."""
    vecs = np.stack([_A, _B, _C])
    assert skills.sweep(vecs, ["a", "b", "c"], [0.999])[0]["n_skills"] == 3


def test_cross_scenario_coverage_is_zero_when_nothing_generalises():
    """The honest-failure signal. If this stays near zero at every threshold, behavioural
    skills do not exist in this corpus and the approach fails rather than being tuned
    into existence."""
    rows = skills.sweep(np.stack([_A, _B, _C]), ["a", "b", "c"], [0.999])

    assert rows[0]["cross_scenario_coverage"] == 0.0
    assert rows[0]["n_multi_scenario"] == 0


def test_cross_scenario_coverage_counts_items_in_multi_scenario_groups():
    vecs = np.stack([_A, _A_NEAR, _B])
    rows = skills.sweep(vecs, ["alpha", "beta", "gamma"], [0.8])

    assert rows[0]["cross_scenario_coverage"] == pytest.approx(2 / 3)


# --- assigning into a fixed vocabulary ------------------------------------------------------

def test_a_matching_area_is_assigned_to_its_skill():
    got = skills.assign_to_vocabulary(
        np.stack([_A_NEAR]), np.stack([_A, _B]), ["S1", "S2"], threshold=0.8)
    assert got == ["S1"]


def test_novel_behaviour_lands_in_unassigned_rather_than_the_nearest_skill():
    """The bucket IS the signal that the vocabulary needs re-deriving. Forcing novel
    behaviour into the nearest skill is how a taxonomy stops describing its data without
    anyone noticing."""
    got = skills.assign_to_vocabulary(
        np.stack([_C]), np.stack([_A, _B]), ["S1", "S2"], threshold=0.8)
    assert got == [skills.UNASSIGNED]


def test_an_empty_vocabulary_assigns_nothing_rather_than_crashing():
    got = skills.assign_to_vocabulary(
        np.stack([_A]), np.empty((0, 3)), [], threshold=0.8)
    assert got == [skills.UNASSIGNED]


def test_assignment_survives_a_reshuffled_cluster_set():
    """The whole point of a fixed vocabulary: the clusters underneath may churn between
    Layer C runs, but the same behaviour must still land on the same skill."""
    vocab, ids = np.stack([_A, _B]), ["S1", "S2"]
    first = skills.assign_to_vocabulary(np.stack([_A_NEAR, _B]), vocab, ids, 0.8)
    reshuffled = skills.assign_to_vocabulary(np.stack([_B, _A_NEAR]), vocab, ids, 0.8)

    assert first == ["S1", "S2"] and reshuffled == ["S2", "S1"]


# --- the grid --------------------------------------------------------------------------------

def test_the_grid_reports_cells_and_both_margins():
    g = skills.grid(["S1", "S1", "S2"], ["integration", "budget", "integration"])

    assert g["cells"]["S1"] == {"integration": 1, "budget": 1}
    assert g["row_totals"]["S1"] == 2
    assert g["col_totals"]["integration"] == 2


def test_the_margins_pool_more_than_any_single_cell():
    """Why the grid exists: a row and a column each pool many observations and are the
    trustworthy part; a cell is thin by construction."""
    g = skills.grid(["S1"] * 4, ["a", "b", "c", "d"])

    assert g["row_totals"]["S1"] == 4
    assert max(g["cells"]["S1"].values()) == 1


def test_an_empty_grid_is_empty_not_a_crash():
    assert skills.grid([], []) == {"cells": {}, "row_totals": {}, "col_totals": {}, "n": 0}
