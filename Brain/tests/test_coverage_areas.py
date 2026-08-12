"""Tests for shared/coverage_areas.py -- option 4 of the profile-rebuild design.

Coverage areas replace ~5 independently-written gradable criteria per scenario with 3-4
things strong handling COVERS. The parsing is where a silent bug would invalidate the
whole arm, so it is what these tests pin.

The failure this module exists to make visible: collapsing 5 moves into 3 areas can
quietly fuse genuinely distinct coaching moves. That is the merge-blindness which
inflated an entire Layer C A/B while the milestone COUNT went UP -- invisible in every
summary statistic it produced. Every area therefore declares which moves it covers, and
the coverage is checked rather than trusted.
"""
from __future__ import annotations

import pytest

from shared import coverage_areas as ca


def _area(cid, covers, label="Area", exemplars=("a quote",)):
    return {"id": cid, "label": label, "description": f"{label} description",
            "precondition": "any turn in this situation",
            "covers_clusters": list(covers), "exemplars": list(exemplars)}


# --- parsing ----------------------------------------------------------------------------

def test_a_well_formed_reply_parses_into_areas():
    raw = [_area("C1", ["m1", "m2"]), _area("C2", ["m3"])]
    areas, report = ca.parse_areas(raw, ["m1", "m2", "m3"])

    assert [a["id"] for a in areas] == ["C1", "C2"]
    assert areas[0]["covers_clusters"] == ["m1", "m2"]
    assert report["unknown_clusters"] == [] and report["uncovered_clusters"] == []


def test_a_reply_wrapped_in_an_object_is_read_the_same_as_a_bare_array():
    """Gemma returns a bare array or {"results": [...]} unpredictably -- the guard
    CLAUDE.md requires on every parse in this codebase."""
    raw = {"results": [_area("C1", ["m1"])]}
    areas, _ = ca.parse_areas(raw, ["m1"])
    assert len(areas) == 1


def test_an_invented_cluster_id_is_dropped_and_reported():
    """An id that was never offered means the model is not tracking the id space, which
    implies misattribution rather than mere omission."""
    areas, report = ca.parse_areas([_area("C1", ["m1", "m99"])], ["m1"])

    assert areas[0]["covers_clusters"] == ["m1"]
    assert report["unknown_clusters"] == ["m99"]


def test_a_move_no_area_claims_is_reported_not_silently_lost():
    """An uncovered move is a real move with real support that the playbook forgot. It
    must surface -- silence here is how evidence disappears."""
    _, report = ca.parse_areas([_area("C1", ["m1"])], ["m1", "m2"])

    assert report["uncovered_clusters"] == ["m2"]


def test_a_move_claimed_twice_is_reported():
    """Double-claiming means the areas overlap, so support counts would be
    double-counted when they are rolled up from the moves."""
    _, report = ca.parse_areas([_area("C1", ["m1"]), _area("C2", ["m1"])], ["m1"])

    assert report["double_claimed_clusters"] == ["m1"]


def test_an_area_covering_nothing_is_dropped():
    """An area with no moves behind it has no evidence at all -- exactly the
    unfalsifiable prose the covers_clusters requirement exists to prevent."""
    areas, report = ca.parse_areas([_area("C1", ["m1"]), _area("C2", [])], ["m1"])

    assert [a["id"] for a in areas] == ["C1"]
    assert report["empty_areas"] == ["C2"]


def test_areas_get_positional_ids_regardless_of_what_the_model_returned():
    """Same rule as milestone_id: identity is the array POSITION. A model-chosen id
    would let a re-run silently repoint a person's history at a different area."""
    areas, _ = ca.parse_areas([_area("banana", ["m1"]), _area("C7", ["m2"])], ["m1", "m2"])

    assert [a["id"] for a in areas] == ["C1", "C2"]


def test_an_area_missing_its_description_is_dropped_rather_than_stored_blank():
    raw = [{"id": "C1", "covers_clusters": ["m1"]}, _area("C2", ["m2"])]
    areas, report = ca.parse_areas(raw, ["m1", "m2"])

    assert [a["id"] for a in areas] == ["C1"]      # renumbered from the survivor
    assert report["malformed_areas"] == 1


def test_an_empty_reply_produces_no_areas_and_reports_every_move_uncovered():
    areas, report = ca.parse_areas([], ["m1", "m2"])

    assert areas == []
    assert report["uncovered_clusters"] == ["m1", "m2"]


# --- rolling evidence up from the moves ---------------------------------------------------

def _cluster(cid, calls, clauses):
    return {"cluster_id": cid, "support_calls": calls,
            "clauses": ["c"] * clauses, "relevance_mean": 0.6}


def test_support_rolls_up_from_the_moves_an_area_covers():
    """An area's evidence is its moves' evidence. Without this an area is prose with no
    audit trail, and 'does this recur?' becomes unanswerable."""
    areas = [_area("C1", ["m1", "m2"])]
    clusters = {"m1": _cluster("m1", calls=8, clauses=20),
                "m2": _cluster("m2", calls=5, clauses=12)}
    rolled = ca.attach_evidence(areas, clusters)

    assert rolled[0]["support_clauses"] == 32
    assert rolled[0]["covers_n_moves"] == 2


def test_support_calls_is_a_max_not_a_sum_because_calls_overlap():
    """Two moves can recur in the SAME calls, so adding their call counts would claim
    more distinct calls than exist. Max is the honest lower bound available without
    per-move call sets."""
    areas = [_area("C1", ["m1", "m2"])]
    clusters = {"m1": _cluster("m1", calls=8, clauses=20),
                "m2": _cluster("m2", calls=5, clauses=12)}

    assert ca.attach_evidence(areas, clusters)[0]["support_calls"] == 8


def test_a_merge_of_many_moves_into_one_area_is_flagged():
    """THE FAILURE MODE THIS MODULE EXISTS FOR. Fusing many distinct moves into one area
    is how a playbook loses coaching moves while looking tidier. Flagged, not blocked --
    sometimes it is correct, and a human reads the flag."""
    clusters = {f"m{i}": _cluster(f"m{i}", 5, 10) for i in range(1, 6)}
    rolled = ca.attach_evidence([_area("C1", list(clusters))], clusters)

    assert rolled[0]["wide_merge"] is True


def test_a_two_move_area_is_not_flagged_as_a_merge():
    clusters = {"m1": _cluster("m1", 5, 10), "m2": _cluster("m2", 5, 10)}
    rolled = ca.attach_evidence([_area("C1", ["m1", "m2"])], clusters)

    assert rolled[0]["wide_merge"] is False


def test_evidence_for_an_unknown_move_is_skipped_rather_than_crashing():
    rolled = ca.attach_evidence([_area("C1", ["m1", "ghost"])],
                                {"m1": _cluster("m1", 4, 9)})

    assert rolled[0]["covers_n_moves"] == 1
    assert rolled[0]["support_clauses"] == 9


def test_the_merge_threshold_is_the_documented_value():
    assert ca.WIDE_MERGE_MOVES == 4


# --- the fourth verdict -------------------------------------------------------------------

def test_the_four_verdicts_are_the_designed_vocabulary():
    assert ca.VALID_VERDICTS == {"covered", "partly_covered", "not_covered",
                                 "not_called_for"}


def test_an_unparseable_verdict_defaults_to_not_covered_never_not_called_for():
    """Defaulting to not_called_for would shrink the denominator and flatter every score
    -- the one failure direction nothing downstream can detect."""
    assert ca.normalize_verdict({"verdict": "banana"}) == ca.NOT_COVERED
    assert ca.normalize_verdict({}) == ca.NOT_COVERED


def test_score_reports_both_denominators():
    """An arm using the fourth verdict computes over a different population than one that
    does not, so the unconditional figure must exist on both sides or the arms are not
    comparable."""
    s = ca.score(["covered", "partly_covered", "not_covered", "not_called_for"])

    assert s["attempts"] == 4 and s["applicable"] == 3
    assert s["w_unconditional"] == pytest.approx(1.5 / 4)
    assert s["w_conditional"] == pytest.approx(1.5 / 3)


def test_not_called_for_leaves_the_conditional_score_alone():
    """The contingency correction: being graded on a move the moment never required must
    not count against anyone."""
    base = ca.score(["covered", "not_covered"])
    padded = ca.score(["covered", "not_covered", "not_called_for", "not_called_for"])

    assert padded["w_conditional"] == pytest.approx(base["w_conditional"])
    assert padded["w_unconditional"] < base["w_unconditional"]


def test_an_all_not_called_for_moment_scores_zero_rather_than_dividing_by_zero():
    s = ca.score(["not_called_for", "not_called_for"])

    assert s["applicable"] == 0
    assert s["w_conditional"] == 0.0
    assert s["not_called_for_rate"] == 1.0


def test_no_verdicts_at_all_is_zero_not_a_crash():
    s = ca.score([])
    assert s["attempts"] == 0 and s["w_unconditional"] == 0.0


def test_an_unknown_verdict_is_counted_as_not_covered_in_the_totals():
    s = ca.score(["covered", "nonsense"])
    assert s["counts"]["not_covered"] == 1 and s["attempts"] == 2
