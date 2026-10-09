"""Unit tests for calibration/playbook_snap_trial.py — the frozen snap rules,
counterbalancing, and the resized PB1. Hand-built inputs throughout."""
from __future__ import annotations

import pytest

from calibration.playbook_snap_trial import (
    SNAP_MIN_SCORE, best_span, counterbalanced_side, pb1_doc_resized, snap_citation,
    snap_doc,
)
from calibration.scenario_playbook_trial import norm_quote, pb0_doc

RESP = ("Let me walk you through the cost drivers — sponsored slots doubled and the "
        "market moved. That definitely was part of our publisher mix. But obviously "
        "the way we have seen this in the past, the cost point is way cheaper.")
EV = [{"call": "call_a", "account": "acme.com",
       "trigger_text": "Why are costs so high this month?",
       "response_text": RESP}]
CANDS = [norm_quote(RESP), norm_quote(EV[0]["trigger_text"])]


def _cit(quote, call="call_a", account="acme.com"):
    return {"quote": quote, "call": call, "account": account}


# ------------------------------------------------------------------------ snap_citation

def test_verbatim_quote_is_kept_unchanged():
    outcome, e, score = snap_citation(_cit("the cost drivers — sponsored slots"), CANDS)
    assert outcome == "kept" and score == 1.0
    assert e["quote"] == "the cost drivers — sponsored slots"   # untouched, not normalized


def test_near_miss_is_snapped_to_exact_substring():
    # the predecessor's real failure mode: "That" -> "This"
    outcome, e, score = snap_citation(
        _cit("This definitely was part of our publisher mix."), CANDS)
    assert outcome == "snapped" and score >= SNAP_MIN_SCORE
    assert norm_quote(e["quote"]) in CANDS[0]          # PB0-passing by construction
    assert "That definitely was part of our publisher mix" in e["quote"]


def test_snapped_call_and_account_never_change():
    _, e, _ = snap_citation(_cit("This definitely was part of our publisher mix."), CANDS)
    assert e["call"] == "call_a" and e["account"] == "acme.com"


def test_fabricated_quote_is_dropped():
    outcome, e, score = snap_citation(
        _cit("we guarantee a fifty percent discount forever"), CANDS)
    assert outcome == "dropped" and e is None and score < SNAP_MIN_SCORE


def test_empty_quote_and_unknown_call_drop():
    assert snap_citation(_cit("   "), CANDS)[0] == "dropped"
    assert snap_citation(_cit("anything", call="zz"), [])[0] == "dropped"


def test_snap_deterministic():
    c = _cit("This definitely was part of our publisher mix.")
    assert snap_citation(c, CANDS) == snap_citation(c, CANDS)


def test_snap_threshold_boundary_is_inclusive(monkeypatch):
    # spec §3 step 4: score >= 0.80 snaps; strictly below drops
    import calibration.playbook_snap_trial as m
    monkeypatch.setattr(m, "best_span", lambda q, t: (0.80, "real span"))
    assert m.snap_citation(_cit("no exact match here zz"), CANDS)[0] == "snapped"
    monkeypatch.setattr(m, "best_span", lambda q, t: (0.7999, "real span"))
    assert m.snap_citation(_cit("no exact match here zz"), CANDS)[0] == "dropped"


def test_best_span_no_common_text():
    score, span = best_span("xyz", "abc abc abc")
    assert score == 0.0 or score < 0.5


# ----------------------------------------------------------------------------- snap_doc

def _doc(move_quotes: list[list[str]]) -> dict:
    return {"situation_signature": "sig",
            "arc": [f"m{i}" for i in range(len(move_quotes))],
            "key_moves": [{"name": f"m{i}", "criterion": "c",
                           "evidence": [_cit(q) for q in quotes]}
                          for i, quotes in enumerate(move_quotes)],
            "signature_language": [dict(_cit("the cost drivers"), phrase="p")],
            "pitfalls_and_variants": [{"text": "pit",
                                       "evidence": [_cit("totally invented text qqq")]}],
            "layer_d_checks": ["a", "b", "c"]}


GOOD = "the cost drivers — sponsored slots doubled"
NEAR = "This definitely was part of our publisher mix."
BAD = "purely fabricated nonsense about llamas"


def test_snap_doc_repairs_and_passes_pb0():
    doc = _doc([[GOOD, NEAR], [GOOD, GOOD], [GOOD, NEAR, GOOD]])
    snapped, log = snap_doc(doc, EV)
    assert not log["schema_collapsed"]
    assert log["snapped"] == 2 and log["dropped"] == 1      # the pitfall's fake quote
    assert len(snapped["key_moves"]) == 3
    assert snapped["pitfalls_and_variants"] == []           # pitfall lost its evidence
    assert pb0_doc(snapped, EV)["pass"]                     # the whole point


def test_move_below_two_citations_is_dropped_and_arc_follows():
    doc = _doc([[GOOD, BAD], [GOOD, GOOD], [GOOD, GOOD], [GOOD, GOOD]])
    snapped, log = snap_doc(doc, EV)
    assert log["dropped_moves"] == ["m0"]
    assert len(snapped["key_moves"]) == 3
    assert "m0" not in snapped["arc"]
    assert not log["schema_collapsed"]


def test_document_collapses_below_three_moves():
    doc = _doc([[BAD, BAD], [GOOD, GOOD], [GOOD, GOOD]])
    _, log = snap_doc(doc, EV)
    assert log["dropped_moves"] == ["m0"] and log["schema_collapsed"]


# -------------------------------------------------------------- counterbalance + PB1

def test_counterbalanced_sides_alternate():
    assert [counterbalanced_side(i) for i in range(5)] == ["A", "B", "A", "B", "A"]


def _ev_accounts(accounts):
    return [{"call": f"c{i}", "account": a, "trigger_text": "", "response_text": ""}
            for i, a in enumerate(accounts)]


def test_pb1_resized_denominator_is_quote_budget():
    # 10 accounts available but only 6 citations -> denominator 6, span 4/6 passes
    ev = _ev_accounts(list("abcdefghij"))
    doc = {"key_moves": [
        {"name": "m1", "evidence": [_cit("q", f"c{i}", a) for i, a in
                                    enumerate(["a", "b", "c"])]},
        {"name": "m2", "evidence": [_cit("q", "c0", "a"), _cit("q", "c1", "b"),
                                    _cit("q", "c3", "d")]}]}
    res = pb1_doc_resized(doc, ev)
    assert res["span_denominator"] == 6
    assert res["span"] == pytest.approx(4 / 6)
    assert res["pass"]


def test_pb1_resized_still_fails_narrow_docs():
    ev = _ev_accounts(list("abcdefghij"))
    doc = {"key_moves": [
        {"name": "m1", "evidence": [_cit("q", "c0", "a"), _cit("q", "c0", "a"),
                                    _cit("q", "c0", "a")]}]}
    res = pb1_doc_resized(doc, ev)
    assert not res["pass"] and not res["pass_moves"] and not res["pass_span"]
