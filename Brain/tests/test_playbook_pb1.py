"""PB1 coherence: the gate must grade what the prompt makes achievable.

Measured 2026-08-20: PB1 demanded 3 distinct accounts per move while the prompt permitted
2 quotes per move, and 89% of moves took the minimum. 0/11 documents passed -- for arithmetic,
before quality was ever assessed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration.scenario_playbook_trial import (  # noqa: E402
    MAX_EVIDENCE_PER_MOVE,
    MIN_EVIDENCE_PER_MOVE,
    PB1_MOVE_ACCTS,
    REDUCE_RULES,
    pb1_doc,
)

_EV = [{"quote": f"q{i}", "call": f"c{i}", "account": f"a{i}.com"} for i in range(10)]


def _move(accounts):
    return {"name": "m", "criterion": "c",
            "evidence": [{"quote": "q", "call": "c", "account": a} for a in accounts]}


def test_the_prompt_floor_makes_the_account_bar_reachable():
    """The whole defect in one assertion: you cannot cite N accounts with fewer than N
    quotes, so the prompt's minimum must be at least PB1's account requirement."""
    assert MIN_EVIDENCE_PER_MOVE >= PB1_MOVE_ACCTS
    assert MAX_EVIDENCE_PER_MOVE >= MIN_EVIDENCE_PER_MOVE


def test_the_prompt_text_matches_the_constants():
    """REDUCE_RULES is a plain string (it contains JSON braces, so it cannot be an
    f-string). That makes drift between the text and the constants possible -- this is what
    catches it."""
    assert f'"evidence" with {MIN_EVIDENCE_PER_MOVE}-{MAX_EVIDENCE_PER_MOVE} entries' \
        in REDUCE_RULES
    assert f"at least {PB1_MOVE_ACCTS} DISTINCT accounts" in REDUCE_RULES


def test_a_narrow_move_still_fails():
    """The cap must not forgive genuine narrowness: 3 quotes all from one account is
    exactly the 'one client's quirk' case PB1 exists to catch."""
    doc = {"key_moves": [_move(["a1.com", "a1.com", "a1.com"])]}
    r = pb1_doc(doc, _EV)
    assert r["per_move"][0]["accounts"] == 1
    assert not r["per_move"][0]["ok"]


def test_a_diverse_move_passes():
    doc = {"key_moves": [_move(["a1.com", "a2.com", "a3.com"])]}
    assert pb1_doc(doc, _EV)["per_move"][0]["ok"]


def test_a_two_quote_move_still_fails_and_that_is_intended():
    """Capping `need` by the move's own quote count was TRIED on 2026-08-20 and reverted:
    it makes a 2-quote move pass by lowering the bar to meet it, forgiving exactly the
    documents that should be flagged. Under the new 3-entry prompt floor a 2-quote move is
    a schema violation, and PB1 failing it is the correct signal."""
    doc = {"key_moves": [_move(["a1.com", "a2.com"])]}
    m = pb1_doc(doc, _EV)["per_move"][0]
    assert m["need"] == 3 and not m["ok"]
    assert m["quotes"] == 2, "the quote count is reported so the failure is diagnosable"


def test_need_is_capped_by_accounts_available_too():
    """A scenario drawing on only 2 accounts cannot be asked for 3."""
    doc = {"key_moves": [_move(["a1.com", "a2.com", "a2.com"])]}
    two = [{"quote": "q", "call": "c", "account": a} for a in ("a1.com", "a2.com")]
    assert pb1_doc(doc, two)["per_move"][0]["ok"]


def test_the_gate_reports_quotes_so_a_failure_is_diagnosable():
    doc = {"key_moves": [_move(["a1.com", "a2.com"])]}
    m = pb1_doc(doc, _EV)["per_move"][0]
    assert m["quotes"] == 2 and "need" in m
