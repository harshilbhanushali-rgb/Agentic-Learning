"""Tests for shared/rubric_validation.py -- Layer C's objective function.

Design: docs/superpowers/specs/2026-08-11-layer-c-objective-function-design.md

Everything here is pure. The Gemma calls, the DB and the sampling live in
calibration/validate_rubrics.py, which reuses score_naren_ceiling's already-tested
holdout logic; what a silent bug would corrupt is the VERDICT ASSIGNMENT, the
staleness check and the JSONB merge, so those are what this file pins.

Imports no torch, for the same [WinError 1455] reason as test_naren_ceiling.py.
"""
from __future__ import annotations

import pytest

from shared import rubric_validation as rv


def _c(attempts=8, hits=0, partial=0):
    return {"attempts": attempts, "hits": hits, "partial": partial}


# --- the pre-registered thresholds ------------------------------------------------------

def test_thresholds_are_the_values_pre_registered_in_the_design_spec():
    """Inherited from the ceiling spec's own gate and main threshold, deliberately, so
    this instrument is calibrated against an existing measurement rather than fresh
    guesses. A change here must be an argued edit, not drift."""
    assert rv.T_DISCRIMINATION == 0.5
    assert rv.T_SATISFIABLE == 0.20
    assert rv.T_CONTINGENT == 0.50
    assert rv.MIN_APPLICABLE == 6


# --- verdict assignment: not_discriminating ---------------------------------------------

def test_the_unrelated_rubric_scoring_half_as_well_condemns_the_milestone():
    # W(A3) = 4/8 = 0.5, W(B) = 2/8 = 0.25 == 0.5 * 0.5 -> the gate fires.
    v = rv.classify(a3=_c(hits=4), b=_c(hits=2), applicable=_c(attempts=8, hits=4))
    assert v["verdict"] == rv.NOT_DISCRIMINATING


def test_the_discrimination_gate_is_inclusive_at_exactly_half(
):
    """`W(B) >= 0.5 x W(A3)` -- equality is a FAILURE, matching the ceiling harness's
    own gate, which reported INSTRUMENT INVALID at exactly the boundary."""
    v = rv.classify(a3=_c(hits=4), b=_c(hits=2), applicable=_c(attempts=8, hits=4))
    assert v["verdict"] == rv.NOT_DISCRIMINATING
    # One partial less on the control and it survives.
    ok = rv.classify(a3=_c(hits=4), b=_c(hits=1), applicable=_c(attempts=8, hits=4))
    assert ok["verdict"] != rv.NOT_DISCRIMINATING


def test_a_milestone_nobody_ever_hits_is_not_blamed_on_discrimination():
    """The load-bearing precedence rule.

    With W(A3) = 0 the raw inequality `W(B) >= 0.5 x W(A3)` reads 0 >= 0 and fires, which
    would label every dead milestone `not_discriminating` -- and the 65 zero-hit
    milestones are exactly the population this whole run exists to split between
    `not_satisfiable` and `contingent`. Classifying them here would make the design's own
    §3.6 self-validation unreproducible. Same guard as score_naren_ceiling's
    `invalid = w_a3 > 0 and ...`.
    """
    v = rv.classify(a3=_c(), b=_c(), applicable=_c(attempts=8))
    assert v["verdict"] == rv.NOT_SATISFIABLE


# --- verdict assignment: insufficient_evidence ------------------------------------------

def test_fewer_than_six_applicable_instances_is_insufficient_evidence_not_a_failure():
    v = rv.classify(a3=_c(hits=4), b=_c(), applicable=_c(attempts=5, hits=4))
    assert v["verdict"] == rv.INSUFFICIENT_EVIDENCE


def test_exactly_six_applicable_instances_is_enough_to_judge():
    v = rv.classify(a3=_c(hits=4), b=_c(), applicable=_c(attempts=6, hits=4))
    assert v["verdict"] != rv.INSUFFICIENT_EVIDENCE


def test_insufficient_evidence_still_reports_applicable_rate():
    """At 8 attempts per arm a genuinely contingent milestone (applies ~25% of the time)
    lands ~2 applicable instances and is reported `insufficient_evidence`, never
    `contingent`. That is the pre-registered ordering, and it is exactly why the rate has
    to survive onto the record -- §7's unreachable-vs-conditional question is answered by
    reading applicable_rate, not by counting verdicts."""
    v = rv.classify(a3=_c(), b=_c(), applicable=_c(attempts=2))
    assert v["verdict"] == rv.INSUFFICIENT_EVIDENCE
    assert v["applicable_rate"] == pytest.approx(2 / 8)


# --- verdict assignment: not_satisfiable ------------------------------------------------

def test_a_criterion_the_author_cannot_meet_when_it_applies_is_not_satisfiable():
    # 6 applicable, 1 partial -> W = 0.5/6 = 0.083 < 0.20
    v = rv.classify(a3=_c(partial=1), b=_c(), applicable=_c(attempts=6, partial=1))
    assert v["verdict"] == rv.NOT_SATISFIABLE


def test_the_satisfiability_threshold_is_exclusive_at_exactly_point_two():
    """`W(A3|applicable) < 0.20` -- exactly 0.20 PASSES. 8 applicable, 1 hit and 1 partial
    is 1.5/8 = 0.1875 (fails); 2 hits of 10 is exactly 0.20 (passes)."""
    fails = rv.classify(a3=_c(hits=1, partial=1), b=_c(),
                        applicable=_c(attempts=8, hits=1, partial=1))
    assert fails["verdict"] == rv.NOT_SATISFIABLE
    passes = rv.classify(a3=_c(attempts=10, hits=2), b=_c(attempts=10),
                         applicable=_c(attempts=10, hits=2))
    assert passes["verdict"] != rv.NOT_SATISFIABLE


def test_satisfiability_is_measured_on_applicable_instances_only():
    """The whole point of the applicability pre-check: 2 hits out of 3 applicable is a
    milestone the author reliably performs when the moment calls for it, even though it
    is 2 of 8 unconditionally. Judged unconditionally it would read 0.25 and judged on
    applicable instances 0.67 -- and only the second is 'can it be satisfied'."""
    v = rv.classify(a3=_c(hits=2), b=_c(), applicable=_c(attempts=6, hits=4))
    assert v["a3_w"] == pytest.approx(2 / 8)
    assert v["a3_w_applicable"] == pytest.approx(4 / 6)


# --- verdict assignment: contingent -----------------------------------------------------

def test_a_move_called_for_less_than_half_the_time_is_contingent_not_failed():
    """The finding this design exists to act on: contingent moves emitted as mandatory.
    6 of 16 applicable = 0.375, and it is satisfied 4 of those 6."""
    v = rv.classify(a3=_c(attempts=16, hits=4), b=_c(attempts=16),
                    applicable=_c(attempts=6, hits=4))
    assert v["verdict"] == rv.CONTINGENT
    assert v["applicable_rate"] == pytest.approx(6 / 16)


def test_the_contingency_threshold_is_exclusive_at_exactly_half():
    """`applicable_rate < 0.50` -- exactly half applicable is NOT contingent."""
    v = rv.classify(a3=_c(attempts=12, hits=4), b=_c(attempts=12),
                    applicable=_c(attempts=6, hits=4))
    assert v["applicable_rate"] == pytest.approx(0.5)
    assert v["verdict"] == rv.VALIDATED


# --- verdict assignment: validated ------------------------------------------------------

def test_a_milestone_that_discriminates_and_is_satisfiable_and_applies_is_validated():
    v = rv.classify(a3=_c(hits=4), b=_c(), applicable=_c(attempts=8, hits=4))
    assert v["verdict"] == rv.VALIDATED
    assert v["discrimination"] == pytest.approx(0.5)


def test_zero_attempts_anywhere_never_divides_by_zero():
    v = rv.classify(a3=_c(attempts=0), b=_c(attempts=0), applicable=_c(attempts=0))
    assert v["a3_w"] == 0.0 and v["b_w"] == 0.0 and v["applicable_rate"] == 0.0
    assert v["verdict"] == rv.INSUFFICIENT_EVIDENCE


def test_the_record_carries_every_count_needed_to_re_derive_the_verdict():
    """A stored verdict a reader cannot audit is a number to be trusted rather than
    checked -- the failure mode this whole line of work exists to end."""
    v = rv.classify(a3=_c(hits=4), b=_c(hits=1), applicable=_c(attempts=6, hits=3))
    for field in ("verdict", "a3_w", "a3_w_applicable", "b_w", "discrimination",
                  "applicable_rate", "a3_attempts", "a3_applicable", "b_attempts"):
        assert field in v, field
    assert (v["a3_attempts"], v["a3_applicable"], v["b_attempts"]) == (8, 6, 8)


# --- scenario-level classification (the resolution that actually held) --------------------

def test_scenario_thresholds_are_the_ceiling_runs_own_bands():
    """Reproduced from naren_ceiling.json 2026-08-12: at these values the ceiling run's
    published table comes back exactly -- 40 qualifying scenarios, 16 discriminating,
    7 zero-control, 7 inverted. Moving either number silently redefines what "ships"."""
    assert rv.SCENARIO_MIN_ATTEMPTS == 15
    assert rv.SCENARIO_BAND == 0.05


def test_a_scenario_whose_control_finds_nothing_ships():
    v = rv.classify_scenario(a3=_c(attempts=48, hits=13), b=_c(attempts=48))
    assert v["verdict"] == rv.SCENARIO_SHIP
    assert v["control_is_zero"] is True


def test_a_scenario_clearing_the_band_ships():
    # A3 W 0.261 vs B W 0.011 -- budget_and_spend_disclosure's real shape.
    v = rv.classify_scenario(a3=_c(attempts=88, hits=23), b=_c(attempts=88, hits=1))
    assert v["verdict"] == rv.SCENARIO_SHIP
    assert v["control_is_zero"] is False


def test_a_scenario_where_the_wrong_rubric_wins_is_disabled():
    """client_reacts_to_anomaly's real shape: the unrelated rubric scores 2.4x higher.
    No wording change helps -- the scenario label carries no information its criteria
    could use."""
    v = rv.classify_scenario(a3=_c(attempts=24, hits=4), b=_c(attempts=24, hits=9, partial=1))
    assert v["verdict"] == rv.SCENARIO_DISABLE


def test_a_scenario_inside_the_band_is_held_not_shipped():
    """No measurable separation either way. Held is a real third state: shipping it would
    claim an instrument that was never demonstrated, disabling it would discard a rubric
    never shown to be broken."""
    v = rv.classify_scenario(a3=_c(attempts=48, hits=3), b=_c(attempts=48, hits=2))
    assert v["verdict"] == rv.SCENARIO_HOLD


def test_the_ship_band_is_exclusive_at_exactly_the_threshold():
    # gap of exactly +0.05 is NOT > 0.05, so it holds.
    v = rv.classify_scenario(a3=_c(attempts=20, hits=2), b=_c(attempts=20, hits=1))
    assert v["gap"] == pytest.approx(0.05)
    assert v["verdict"] == rv.SCENARIO_HOLD


def test_the_disable_band_is_exclusive_at_exactly_the_threshold():
    v = rv.classify_scenario(a3=_c(attempts=20, hits=1), b=_c(attempts=20, hits=2))
    assert v["gap"] == pytest.approx(-0.05)
    assert v["verdict"] == rv.SCENARIO_HOLD


def test_a_thin_scenario_is_reported_unmeasured_rather_than_judged():
    """33 of 82 rubrics have never been exercised at all. Unmeasured must be its own
    state -- calling them broken would condemn rubrics on no evidence, and calling them
    fine would ship them on none."""
    v = rv.classify_scenario(a3=_c(attempts=8, hits=4), b=_c(attempts=8))
    assert v["verdict"] == rv.SCENARIO_INSUFFICIENT


def test_a_thin_control_arm_also_blocks_a_verdict():
    """Both arms must clear the floor. A scenario with plenty of A3 attempts but a tiny
    control has no null worth comparing against."""
    v = rv.classify_scenario(a3=_c(attempts=48, hits=13), b=_c(attempts=6))
    assert v["verdict"] == rv.SCENARIO_INSUFFICIENT


def test_a_zero_control_does_not_ship_a_scenario_that_also_scores_zero():
    """0.000 vs 0.000 is not an instrument, it is silence on both sides."""
    v = rv.classify_scenario(a3=_c(attempts=48), b=_c(attempts=48))
    assert v["verdict"] != rv.SCENARIO_SHIP


def test_the_scenario_record_carries_the_counts_behind_its_verdict():
    v = rv.classify_scenario(a3=_c(attempts=48, hits=13), b=_c(attempts=40, hits=1))
    for field in ("verdict", "a3_w", "b_w", "gap", "a3_attempts", "b_attempts",
                  "control_is_zero"):
        assert field in v, field
    assert (v["a3_attempts"], v["b_attempts"]) == (48, 40)


# --- staleness: a Layer C re-run silently destroys every verdict -------------------------

def _validated(milestone: dict, verdict: str = rv.VALIDATED) -> dict:
    """A milestone carrying a fresh verdict for its own current text."""
    out = dict(milestone)
    out["validation"] = {"verdict": verdict,
                         "milestone_fingerprint": rv.milestone_fingerprint(milestone),
                         "validated_at_run": "run-abc"}
    return out


def test_a_milestone_with_no_validation_has_no_verdict():
    assert rv.validation_of({"description": "d"}) is None


def test_a_fresh_verdict_is_returned():
    m = _validated({"description": "d", "detection_hint": "h"})
    assert rv.validation_of(m)["verdict"] == rv.VALIDATED


def test_a_reworded_criterion_invalidates_its_own_verdict():
    """The load-bearing gotcha. upsert_rubric's ON CONFLICT (scenario_id) replaces
    `milestones` in place, so any Layer C run overwrites the text a verdict describes
    while leaving the verdict object sitting on it. Same failure family as gap_events
    copying evidence rather than joining to it."""
    m = _validated({"description": "original criterion", "detection_hint": "h"})
    m["description"] = "reworded by a later Layer C run"
    assert rv.is_stale(m) is True
    assert rv.validation_of(m) is None


def test_a_changed_detection_hint_also_invalidates_the_verdict():
    """score_milestones_batch sends DETECTION HINT to the grader alongside the
    description, so a milestone whose hint changed is not the criterion that was
    measured, even if the description is byte-identical."""
    m = _validated({"description": "d", "detection_hint": "original hint"})
    m["detection_hint"] = "different hint"
    assert rv.validation_of(m) is None


def test_a_verdict_written_without_a_fingerprint_is_never_trusted():
    """Fail closed. A validation object from an older writer cannot be shown to describe
    the current text, and "probably still fine" is how a stale verdict gets used."""
    m = {"description": "d", "validation": {"verdict": rv.VALIDATED}}
    assert rv.is_stale(m) is True
    assert rv.validation_of(m) is None


def test_a_milestone_with_no_validation_at_all_is_not_reported_stale():
    """Absent and stale are different states: absent means "never measured", which the
    report must distinguish from "measured, then invalidated"."""
    assert rv.is_stale({"description": "d"}) is False


def test_the_fingerprint_is_stable_across_calls():
    m = {"description": "d", "detection_hint": "h"}
    assert rv.milestone_fingerprint(m) == rv.milestone_fingerprint(dict(m))


# --- Layer D's gate ----------------------------------------------------------------------

def test_nothing_is_skipped_while_the_flag_is_off():
    """require_validated_milestones ships false, exactly like
    response_taxonomy_auto_pass_enabled, so an unvalidated corpus behaves as it does
    today."""
    m = _validated({"description": "d"}, rv.NOT_DISCRIMINATING)
    assert rv.should_score(m, require_validated=False) is True


def test_a_validated_milestone_is_scored():
    m = _validated({"description": "d"}, rv.VALIDATED)
    assert rv.should_score(m, require_validated=True) is True


def test_a_contingent_milestone_is_scored_where_the_moment_called_for_it():
    """CONTINGENT is not a failure -- it is the fix for the dominant proximate cause.
    Layer D runs the applicability check for it and scores it only where it applies."""
    m = _validated({"description": "d"}, rv.CONTINGENT)
    assert rv.should_score(m, require_validated=True,
                           milestone_id="M2", applicable_ids={"M2"}) is True


def test_a_contingent_milestone_is_not_scored_where_the_moment_did_not_call_for_it():
    """The whole point: grading every response against every milestone regardless of
    whether the moment called for it is the scoring-model bug, and it is why rewording
    the criteria twice did not help."""
    m = _validated({"description": "d"}, rv.CONTINGENT)
    assert rv.should_score(m, require_validated=True,
                           milestone_id="M2", applicable_ids={"M1"}) is False


def test_a_contingent_milestone_is_not_scored_when_applicability_is_unknown():
    """Fails closed. Scoring a contingent milestone with no applicability information
    reinstates the exact defect, and each resulting miss emits a Milestone_Omission gap
    -- written coaching advice telling a CSM they failed to do something the moment never
    called for. That is the same harm skip_uncoachable_milestones exists to stop, so
    silence beats a fabricated finding."""
    m = _validated({"description": "d"}, rv.CONTINGENT)
    assert rv.should_score(m, require_validated=True) is False


def test_applicability_does_not_gate_a_fully_validated_milestone():
    """`validated` means the move applies at least half the time and is satisfiable when
    it does. Filtering it per response as well would apply the contingency correction
    twice."""
    m = _validated({"description": "d"}, rv.VALIDATED)
    assert rv.should_score(m, require_validated=True,
                           milestone_id="M2", applicable_ids=set()) is True


@pytest.mark.parametrize("verdict", [rv.NOT_DISCRIMINATING, rv.NOT_SATISFIABLE,
                                     rv.INSUFFICIENT_EVIDENCE])
def test_a_failed_milestone_is_not_scored(verdict):
    m = _validated({"description": "d"}, verdict)
    assert rv.should_score(m, require_validated=True) is False


def test_an_unvalidated_milestone_is_not_scored_once_the_flag_is_on():
    """Turning the flag on against a rubric that was never validated empties it. That is
    an honest outcome rather than a bug -- §5 names it as the reason the flag must ship
    false and the first run must be read before flipping it."""
    assert rv.should_score({"description": "d"}, require_validated=True) is False


def test_a_stale_verdict_cannot_keep_a_milestone_alive():
    m = _validated({"description": "original"}, rv.VALIDATED)
    m["description"] = "reworded"
    assert rv.should_score(m, require_validated=True) is False


# --- parsing the applicability judge's reply --------------------------------------------

def test_a_returned_subset_becomes_the_applicable_set_for_that_exchange():
    got, report = rv.parse_applicability(
        [{"id": "S0", "applicable": ["M1", "M3"]}], {0: ["M1", "M2", "M3"]})
    assert got == [{"M1", "M3"}]
    assert report["unanswered"] == 0


def test_an_exchange_the_judge_never_answered_is_unknown_not_applicable():
    """The one default that must not exist. Marking an unanswered exchange APPLICABLE
    inflates the satisfiability denominator and makes a contingent milestone read
    unsatisfiable; marking it NOT applicable shrinks it and manufactures contingency.
    Neither is a measurement, so the honest third state is None and the harness drops
    the response -- the same discipline as score_milestones_batch reporting a missing id
    rather than absorbing it as a miss."""
    got, report = rv.parse_applicability([], {0: ["M1", "M2"]})
    assert got == [None]
    assert report["unanswered"] == 1


def test_a_milestone_id_that_is_not_in_this_rubric_is_dropped_and_reported():
    """An invented id means the judge is not tracking the id space, which implies
    misattribution, not merely omission."""
    got, report = rv.parse_applicability(
        [{"id": "S0", "applicable": ["M1", "M99"]}], {0: ["M1", "M2"]})
    assert got == [{"M1"}]
    assert report["unknown_ids"] == ["S0:M99"]


def test_an_empty_applicable_list_means_nothing_applied_which_is_a_real_answer():
    """Distinct from unanswered: the judge looked and said the moment called for none of
    these. That is exactly the observation a fully contingent milestone produces."""
    got, report = rv.parse_applicability(
        [{"id": "S0", "applicable": []}], {0: ["M1"]})
    assert got == [set()]
    assert report["unanswered"] == 0


def test_a_reply_wrapped_in_an_object_is_read_the_same_as_a_bare_array():
    """Gemma returns a bare array or {"results": [...]} unpredictably -- the guard
    CLAUDE.md requires on every parse in this codebase."""
    got, _ = rv.parse_applicability(
        {"results": [{"id": "S0", "applicable": ["M1"]}]}, {0: ["M1"]})
    assert got == [{"M1"}]


def test_a_reply_object_missing_its_id_cannot_silently_claim_an_exchange():
    got, report = rv.parse_applicability(
        [{"applicable": ["M1"]}], {0: ["M1"]})
    assert got == [None]
    assert report["unanswered"] == 1


def test_exchanges_keep_their_positions_when_only_some_are_answered():
    got, report = rv.parse_applicability(
        [{"id": "S2", "applicable": ["M1"]}], {0: ["M1"], 1: ["M1"], 2: ["M1"]})
    assert got == [None, None, {"M1"}]
    assert report["unanswered"] == 2


# --- the applicability denominator ------------------------------------------------------

def test_unanswered_responses_are_excluded_from_the_contingency_rate():
    """If the judge answered only 8 of 16 A3 instances, the rate is over those 8. Using
    all 16 would report 6/16 = 0.375 and call a mandatory milestone contingent purely
    because the judge dropped half the batch."""
    v = rv.classify(a3=_c(attempts=16, hits=8), b=_c(attempts=16),
                    applicable=_c(attempts=6, hits=4),
                    applicability_scored=_c(attempts=8, hits=4))
    assert v["applicable_rate"] == pytest.approx(6 / 8)
    assert v["a3_applicability_scored"] == 8


def test_the_rate_defaults_to_the_whole_a3_arm_when_every_response_was_judged():
    v = rv.classify(a3=_c(attempts=16, hits=8), b=_c(attempts=16),
                    applicable=_c(attempts=8, hits=4))
    assert v["applicable_rate"] == pytest.approx(8 / 16)
    assert v["a3_applicability_scored"] == 16


def test_discrimination_still_uses_the_whole_arm_when_applicability_is_partial():
    """Discrimination must stay unconditional on BOTH arms -- filtering it by
    applicability shrinks the denominator and inflates the null."""
    v = rv.classify(a3=_c(attempts=16, hits=8), b=_c(attempts=16, hits=1),
                    applicable=_c(attempts=6, hits=4),
                    applicability_scored=_c(attempts=8, hits=4))
    assert v["a3_w"] == pytest.approx(8 / 16)
    assert v["b_w"] == pytest.approx(1 / 16)


# --- the write path ----------------------------------------------------------------------

def _real_milestone():
    """The JSONB shape v2/layer_c._finish_rubric actually stores, plus the two flags
    later passes added in place. Round-tripping this is the point."""
    return {
        "order": 2,
        "description": "Quantify the expected outcome using the client's own figures.",
        "detection_hint": "mentions a number the client supplied",
        "support_calls": 22, "support_clauses": 45, "relevance_mean": 0.61,
        "position_variance": 0.098, "sequencing_type": "fixed", "source_v": "v2",
        "criteria_rewritten": True, "not_coachable_flag": False,
    }


def test_writing_a_verdict_preserves_every_existing_milestone_field():
    """upsert_rubric replaces `milestones` wholesale, so anything this merge drops is
    permanently destroyed -- including the support evidence gap_events copies and the
    two flags earlier repair passes wrote."""
    before = _real_milestone()
    record = rv.classify(a3=_c(hits=4), b=_c(), applicable=_c(attempts=8, hits=4))
    after = rv.with_validation(before, record, run_id="run-abc")
    for field, value in before.items():
        assert after[field] == value, field


def test_writing_a_verdict_does_not_mutate_the_milestone_it_was_given():
    before = _real_milestone()
    rv.with_validation(before, rv.classify(_c(), _c(), _c()), run_id="r")
    assert "validation" not in before


def test_a_written_verdict_is_immediately_readable_and_fresh():
    record = rv.classify(a3=_c(hits=4), b=_c(), applicable=_c(attempts=8, hits=4))
    after = rv.with_validation(_real_milestone(), record, run_id="run-abc")
    assert rv.is_stale(after) is False
    assert rv.validation_of(after)["verdict"] == rv.VALIDATED
    assert rv.validation_of(after)["validated_at_run"] == "run-abc"


def test_a_written_verdict_carries_the_counts_and_the_scoring_model():
    record = rv.classify(a3=_c(hits=4), b=_c(hits=1), applicable=_c(attempts=6, hits=3))
    after = rv.with_validation(_real_milestone(), record, run_id="r",
                               scored_by="gemini-3.1-flash-lite")
    v = after["validation"]
    assert v["a3_attempts"] == 8 and v["b_attempts"] == 8 and v["a3_applicable"] == 6
    assert v["scored_by"] == "gemini-3.1-flash-lite"


def test_rewriting_a_verdict_replaces_the_old_one_rather_than_nesting_it():
    first = rv.with_validation(_real_milestone(),
                               rv.classify(_c(), _c(), _c()), run_id="r1")
    second = rv.with_validation(first,
                                rv.classify(_c(hits=4), _c(), _c(attempts=8, hits=4)),
                                run_id="r2")
    assert second["validation"]["verdict"] == rv.VALIDATED
    assert second["validation"]["validated_at_run"] == "r2"
    assert "validation" not in second["validation"]
