"""Tests for calibration/validate_rubrics.py's aggregation.

The verdict rules themselves live in shared/rubric_validation.py and are tested in
test_rubric_validation.py. What is tested HERE is the step between the scored records and
those rules -- turning per-response verdicts plus per-exchange applicability answers into
the four counter sets classify() consumes.

That step is worth its own tests for a specific, already-paid-for reason: the merge-blind
_match_milestones in replay_layer_c_admitted.py silently inflated a whole Layer C A/B by
mis-aggregating, and the bug was invisible in every summary statistic it produced. A
harness that cannot detect its own broken precondition is the failure mode, not the
exception.

Imports no torch: validate_rubrics keeps preprocessing.embedder and friends behind
score_naren_ceiling's lazy in-function imports.
"""
from __future__ import annotations

import pytest

from calibration import validate_rubrics as vr
from shared import rubric_validation as rv


def _rec(pair_id, scenario_key, rubric_id, milestone_id, verdict):
    return {"pair_id": pair_id, "scenario_key": scenario_key, "rubric_id": rubric_id,
            "milestone_id": milestone_id, "verdict": verdict,
            "milestone_description": f"criterion {milestone_id}"}


# --- counters ---------------------------------------------------------------------------

def test_tally_counts_full_and_partial_hits_separately():
    c = vr.counter_zero()
    for verdict in ("full_hit", "partial_hit", "miss"):
        vr.tally(c, verdict)
    assert c == {"attempts": 3, "hits": 1, "partial": 1}


# --- applicability aggregation ------------------------------------------------------------

def test_a_milestone_the_moment_called_for_counts_in_both_sets():
    records = [_rec(1, "s", 10, "M1", "full_hit")]
    appl, judged = vr.applicability_counters(records, {(1, "s"): {"M1"}})
    assert appl[(10, "M1")]["attempts"] == 1
    assert judged[(10, "M1")]["attempts"] == 1


def test_a_milestone_the_moment_did_not_call_for_counts_only_as_judged():
    """The correction this whole design exists to make. The response is still evidence
    that the judge LOOKED -- it just is not evidence about satisfiability."""
    records = [_rec(1, "s", 10, "M1", "miss")]
    appl, judged = vr.applicability_counters(records, {(1, "s"): {"M2"}})
    assert (10, "M1") not in appl
    assert judged[(10, "M1")]["attempts"] == 1


def test_an_unanswered_exchange_counts_in_neither_set():
    """None means the judge was silent. Counting it as 'not applicable' manufactures
    contingency out of a dropped batch; counting it as applicable manufactures
    unsatisfiability. Both are findings invented by a failure."""
    records = [_rec(1, "s", 10, "M1", "miss")]
    appl, judged = vr.applicability_counters(records, {(1, "s"): None})
    assert appl == {} and judged == {}


def test_an_exchange_missing_from_the_answers_entirely_is_also_unanswered():
    """A batch that raised GemmaError never reaches the answer dict at all, which must
    behave identically to an explicit None rather than defaulting to applicable."""
    records = [_rec(1, "s", 10, "M1", "miss")]
    appl, judged = vr.applicability_counters(records, {})
    assert appl == {} and judged == {}


def test_applicability_is_keyed_per_response_not_per_scenario():
    """Two responses in the same scenario legitimately call for different milestones --
    that IS contingency. Collapsing them to a scenario-level answer would erase exactly
    the quantity being measured."""
    records = [_rec(1, "s", 10, "M1", "full_hit"), _rec(2, "s", 10, "M1", "miss")]
    appl, judged = vr.applicability_counters(
        records, {(1, "s"): {"M1"}, (2, "s"): set()})
    assert appl[(10, "M1")] == {"attempts": 1, "hits": 1, "partial": 0}
    assert judged[(10, "M1")]["attempts"] == 2


def test_the_same_milestone_id_stays_separate_across_rubrics():
    """milestone_id is a positional array index, so "M1" is a different criterion in
    every rubric. Merging them is the bug milestone_ids' docstring warns about."""
    records = [_rec(1, "a", 10, "M1", "full_hit"), _rec(2, "b", 11, "M1", "full_hit")]
    appl, _ = vr.applicability_counters(
        records, {(1, "a"): {"M1"}, (2, "b"): {"M1"}})
    assert len(appl) == 2


# --- build_verdicts ------------------------------------------------------------------------

def test_a_milestone_scoring_well_on_its_own_rubric_and_zero_on_the_null_is_validated():
    a3 = [_rec(i, "s", 10, "M1", "full_hit") for i in range(1, 9)]
    b = [_rec(i, "other", 10, "M1", "miss") for i in range(20, 28)]
    applicable = {(i, "s"): {"M1"} for i in range(1, 9)}
    got = vr.build_verdicts(a3, b, applicable)
    assert got["10::M1"]["verdict"] == rv.VALIDATED
    assert got["10::M1"]["discrimination"] == pytest.approx(1.0)


def test_a_milestone_with_no_arm_b_attempts_is_still_classified():
    """A rubric can legitimately receive fewer B attempts than A3 -- the partner's A3 pool
    is a different size. An absent B counter must read as a zero null, not a KeyError that
    kills the whole run after the calls are paid for."""
    a3 = [_rec(i, "s", 10, "M1", "miss") for i in range(1, 9)]
    got = vr.build_verdicts(a3, [], {(i, "s"): {"M1"} for i in range(1, 9)})
    assert got["10::M1"]["b_attempts"] == 0
    assert got["10::M1"]["verdict"] == rv.NOT_SATISFIABLE


def test_a_contingent_milestone_is_separated_from_an_unsatisfiable_one():
    """THE RESULT THIS RUN EXISTS TO PRODUCE. Both milestones score zero unconditionally;
    only the applicability answers tell them apart. M1 was called for every time and never
    satisfied -- unreachable. M2 was called for twice in eight and satisfied both times --
    a real move with an unstated precondition, which Layer C emits as mandatory."""
    a3 = ([_rec(i, "s", 10, "M1", "miss") for i in range(1, 9)]
          + [_rec(i, "s", 10, "M2", "full_hit" if i <= 2 else "miss")
             for i in range(1, 9)])
    applicable = {(i, "s"): ({"M1", "M2"} if i <= 2 else {"M1"}) for i in range(1, 9)}
    got = vr.build_verdicts(a3, [], applicable)
    assert got["10::M1"]["verdict"] == rv.NOT_SATISFIABLE
    assert got["10::M2"]["verdict"] == rv.INSUFFICIENT_EVIDENCE
    assert got["10::M2"]["applicable_rate"] == pytest.approx(2 / 8)


def test_the_contingency_denominator_excludes_unjudged_responses():
    """Half the batch unanswered must not read as 'applied half the time'."""
    a3 = [_rec(i, "s", 10, "M1", "full_hit") for i in range(1, 9)]
    applicable = {(i, "s"): ({"M1"} if i <= 4 else None) for i in range(1, 9)}
    got = vr.build_verdicts(a3, [], applicable)
    assert got["10::M1"]["a3_applicability_scored"] == 4
    assert got["10::M1"]["applicable_rate"] == pytest.approx(1.0)
    assert got["10::M1"]["a3_attempts"] == 8


def test_discrimination_stays_unconditional_when_applicability_is_partial():
    """Filtering arm B, or arm A3's discrimination numerator, by applicability shrinks a
    denominator and inflates the null -- the one way this instrument could flatter
    itself."""
    a3 = [_rec(i, "s", 10, "M1", "full_hit") for i in range(1, 9)]
    b = [_rec(i, "other", 10, "M1", "full_hit") for i in range(20, 28)]
    applicable = {(i, "s"): ({"M1"} if i <= 2 else set()) for i in range(1, 9)}
    got = vr.build_verdicts(a3, b, applicable)
    assert got["10::M1"]["a3_w"] == pytest.approx(1.0)
    assert got["10::M1"]["b_w"] == pytest.approx(1.0)
    assert got["10::M1"]["verdict"] == rv.NOT_DISCRIMINATING


def test_each_verdict_carries_the_identifiers_needed_to_write_it_back():
    a3 = [_rec(1, "budget_and_spend_disclosure", 10, "M1", "miss")]
    got = vr.build_verdicts(a3, [], {(1, "budget_and_spend_disclosure"): set()})
    record = got["10::M1"]
    assert record["rubric_id"] == 10
    assert record["milestone_id"] == "M1"
    assert record["scenario_key"] == "budget_and_spend_disclosure"


def test_a_milestone_only_arm_b_ever_saw_produces_no_verdict():
    """Verdicts are keyed off A3. A milestone with no A3 attempts has no matched-arm
    measurement, so classifying it would report a discrimination gap computed from one
    arm."""
    b = [_rec(1, "other", 10, "M1", "full_hit")]
    assert vr.build_verdicts([], b, {}) == {}


# --- the rollup ----------------------------------------------------------------------------

def test_scenario_rollup_counts_verdicts_per_scenario():
    a3 = ([_rec(i, "s", 10, "M1", "full_hit") for i in range(1, 9)]
          + [_rec(i, "s", 10, "M2", "miss") for i in range(1, 9)])
    applicable = {(i, "s"): {"M1", "M2"} for i in range(1, 9)}
    rollup = vr.scenario_rollup(vr.build_verdicts(a3, [], applicable))
    assert rollup["s"][rv.VALIDATED] == 1
    assert rollup["s"][rv.NOT_SATISFIABLE] == 1


def test_applicable_rate_overall_ignores_unanswered_exchanges():
    got = vr.applicable_rate_overall({("a",): {"M1", "M2"}, ("b",): None,
                                      ("c",): set()})
    assert got == (2, 2)
