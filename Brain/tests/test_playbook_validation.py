"""Tests for calibration/playbook_validation.py (Stage E — PV on the new map).

The pipeline's pure machinery is already covered by test_scenario_playbook_trial.py and
test_playbook_snap_trial.py (this harness imports it rather than re-implementing). What
is NEW and pinned here: the one frozen prompt hardening, and that the PV artifacts can
never collide with the pilot's frozen pb_*/pbs_* paths.
"""
import pytest

from calibration.playbook_validation import (
    _PREFER,
    _REQUIRE,
    pv_reduce_prompt,
    pv_reduce_rules,
)
from calibration.scenario_playbook_trial import REDUCE_RULES, reduce_prompt


# --------------------------------------------------------------------------------------
# the frozen hardening — exactly one sentence changes, everything else byte-identical
# --------------------------------------------------------------------------------------

def test_hardening_replaces_exactly_the_preference_sentence():
    rules = pv_reduce_rules()
    assert _PREFER not in rules
    assert _REQUIRE in rules
    assert "REQUIREMENT" in rules
    # everything else is byte-identical: undo the one replacement and compare
    assert rules.replace(_REQUIRE, _PREFER) == REDUCE_RULES


def test_source_rules_still_carry_the_sentence_the_hardening_targets():
    """If scenario_playbook_trial's REDUCE_RULES is ever edited, the hardening must
    fail loudly rather than silently shipping an unhardened prompt."""
    assert REDUCE_RULES.count(_PREFER) == 1


def test_pv_reduce_prompt_embeds_the_hardened_rules():
    header = "scenario_key: k\ndescription: d\nkeyphrases: a, b"
    maps = [{"moves": []}]
    triggers = ["t1"]
    base = reduce_prompt(header, maps, triggers)
    pv = pv_reduce_prompt(header, maps, triggers)
    assert _REQUIRE in pv and _PREFER not in pv
    # identical outside the rules block
    assert pv.replace(pv_reduce_rules(), "") == base.replace(REDUCE_RULES, "")


def test_all_pv_artifacts_use_the_pbv_prefix_never_the_frozen_ones():
    import calibration.playbook_validation as pv
    for p in (pv.EVIDENCE, pv.PLAYBOOKS, pv.SNAPPED, pv.PB0_REPORT, pv.PACKET,
              pv.KEY, pv.REPORT):
        assert p.name.startswith("pbv_"), p.name
    assert pv.JUDGMENTS_GLOB.startswith("pbv_")


def test_pv_budget_and_bars_are_the_pilot_eras():
    """Spec §6: bars carried unchanged; budget is the pilot-era 50-attempt cap."""
    from calibration.playbook_validation import CALL_BUDGET_HARD, N_EVIDENCE_MAX
    assert CALL_BUDGET_HARD == 50
    assert N_EVIDENCE_MAX == 50
