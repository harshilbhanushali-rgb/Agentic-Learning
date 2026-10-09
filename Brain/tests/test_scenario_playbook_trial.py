"""Unit tests for calibration/scenario_playbook_trial.py — the pure parts only.

Hand-built inputs throughout (the test_layer_b_assignment discipline): these test the
frozen RULES — pick rule, donor assignment, PB0 normalization/matching, PB1 arithmetic,
selection determinism + account floor, reader validity, and the PB2/PB3 scoring — not
the embedding model, the gateway, or the substrate."""
from __future__ import annotations

import random

import numpy as np
import pytest

from calibration.scenario_playbook_trial import (
    assign_donors, build_neg, doc_jobs, iter_cited, norm_quote, pb0_doc, pb1_doc,
    pick_pilot, reader_valid, score_read, select_evidence, sign_test_two_sided,
    validate_map, validate_playbook,
)


# ---------------------------------------------------------------------------- pick rule

def _counts(n: int) -> dict[str, int]:
    return {f"s{i:02d}": 1000 - i for i in range(n)}


def test_pick_pilot_ranks():
    counts = _counts(26)
    assert pick_pilot(counts) == ["s00", "s04", "s09", "s14", "s19"]


def test_pick_pilot_tie_breaks_ascending_key():
    counts = {"b": 10, "a": 10, "c": 5, "d": 4, "e": 3}
    assert pick_pilot(counts, ranks=(1, 2)) == ["a", "b"]


def test_pick_pilot_too_few_scenarios():
    with pytest.raises(SystemExit):
        pick_pilot(_counts(19))


# ------------------------------------------------------------------------------- donors

def test_assign_donors_closest_without_replacement():
    counts = {"p1": 100, "p2": 50, "d_a": 99, "d_b": 98, "d_c": 51}
    donors = assign_donors(["p1", "p2"], counts)
    assert donors == {"p1": "d_a", "p2": "d_c"}


def test_assign_donors_tie_ascending_key():
    counts = {"p1": 100, "x": 90, "y": 110}   # both 10 away
    assert assign_donors(["p1"], counts) == {"p1": "x"}


def test_assign_donors_never_reuses():
    counts = {"p1": 10, "p2": 10, "d": 10, "e": 999}
    donors = assign_donors(["p1", "p2"], counts)
    assert donors["p1"] == "d" and donors["p2"] == "e"


# -------------------------------------------------------------------------- PB0 matcher

def test_norm_quote_whitespace_and_curly():
    assert norm_quote("  “It’s   a\n test”  ") == '"It\'s a test"'
    assert norm_quote("a – b — c − d") == "a - b - c - d"


def test_norm_quote_case_sensitive():
    assert norm_quote("Hello") != norm_quote("hello")


EV = [
    {"call": "call_a", "account": "acme.com",
     "trigger_text": "Why are costs so high this month?",
     "response_text": "Let me walk you through the cost drivers — sponsored slots "
                      "doubled and the market moved."},
    {"call": "call_b", "account": "globex.com",
     "trigger_text": "We might pause the campaign.",
     "response_text": "Before pausing, look at the benchmark: your cost per hire is "
                      "still 30% under market."},
]


def _doc(quote: str, call: str = "call_a", account: str = "acme.com") -> dict:
    return {"key_moves": [{"name": "m", "criterion": "c",
                           "evidence": [{"quote": quote, "call": call,
                                         "account": account}]}]}


def test_pb0_verbatim_pass_with_messy_whitespace():
    res = pb0_doc(_doc("the  cost\ndrivers — sponsored slots"), EV)
    assert res["pass"], res["failures"]


def test_pb0_fabricated_quote_fails():
    res = pb0_doc(_doc("we guarantee a 50% discount"), EV)
    assert not res["pass"]
    assert res["failures"][0]["reason"] == "not verbatim in cited call"


def test_pb0_altered_quote_fails():
    res = pb0_doc(_doc("your cost per hire is still 35% under market", "call_b",
                       "globex.com"), EV)
    assert not res["pass"]


def test_pb0_misattributed_quote_flagged_as_such():
    res = pb0_doc(_doc("your cost per hire is still 30% under market",
                       "call_a", "acme.com"), EV)
    assert not res["pass"]
    assert res["failures"][0]["reason"] == "misattributed"


def test_pb0_unknown_call_fails():
    res = pb0_doc(_doc("anything", "call_zz", "acme.com"), EV)
    assert not res["pass"]
    assert res["failures"][0]["reason"] == "cited call not in evidence set"


def test_pb0_account_mismatch_fails():
    res = pb0_doc(_doc("the cost drivers", "call_a", "globex.com"), EV)
    assert not res["pass"]
    assert res["failures"][0]["reason"] == "account mismatch"


def test_pb0_empty_quote_fails_and_short_quote_warns():
    assert not pb0_doc(_doc("   "), EV)["pass"]
    res = pb0_doc(_doc("cost drivers"), EV)      # 12 chars: matches but warns
    assert res["pass"] and res["n_short_quotes_warn"] == 1


def test_pb0_quote_from_trigger_side_passes():
    res = pb0_doc(_doc("Why are costs so high this month?"), EV)
    assert res["pass"]


def test_iter_cited_walks_all_sections():
    doc = {"key_moves": [{"evidence": [{"quote": "a"}]}],
           "signature_language": [{"quote": "b"}],
           "pitfalls_and_variants": [{"evidence": [{"quote": "c"}, {"quote": "d"}]}]}
    assert len(list(iter_cited(doc))) == 4


# ---------------------------------------------------------------------------------- PB1

def _ev_accounts(accounts: list[str]) -> list[dict]:
    return [{"call": f"c{i}", "account": a, "trigger_text": "", "response_text": ""}
            for i, a in enumerate(accounts)]


def _move(accounts: list[str]) -> dict:
    return {"name": "m", "evidence": [{"quote": "q", "call": "c", "account": a}
                                      for a in accounts]}


def test_pb1_pass():
    ev = _ev_accounts(["a", "b", "c", "d"])
    doc = {"key_moves": [_move(["a", "b", "c"]), _move(["b", "c", "d"])]}
    res = pb1_doc(doc, ev)
    assert res["pass"] and res["span"] == 1.0


def test_pb1_move_below_floor_fails():
    ev = _ev_accounts(["a", "b", "c", "d"])
    doc = {"key_moves": [_move(["a", "b"]), _move(["b", "c", "d"])]}
    res = pb1_doc(doc, ev)
    assert not res["pass"] and not res["pass_moves"]


def test_pb1_span_below_60pct_fails():
    ev = _ev_accounts(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])
    doc = {"key_moves": [_move(["a", "b", "c"]), _move(["a", "b", "c"])]}
    res = pb1_doc(doc, ev)
    assert res["pass_moves"] and not res["pass_span"] and not res["pass"]


def test_pb1_small_pool_lowers_the_move_floor():
    ev = _ev_accounts(["a", "b"])          # only 2 accounts available -> need = 2
    doc = {"key_moves": [_move(["a", "b"])]}
    assert pb1_doc(doc, ev)["pass_moves"]


# ---------------------------------------------------------------------------- selection

def _pool(accounts: list[str]) -> list[dict]:
    return [{"account": a} for a in accounts]


def test_select_account_floor_covers_accounts_first():
    # 6 pairs, 3 accounts; floor 3 -> first three picks cover all three accounts
    pool = _pool(["a", "a", "a", "b", "b", "c"])
    mat = np.eye(6, dtype=np.float32)      # orthogonal: every pair equally far
    idx = select_evidence(pool, mat, n_max=4, floor=3)
    assert len(idx) == 4
    assert {pool[i]["account"] for i in idx[:3]} == {"a", "b", "c"}


def test_select_deterministic():
    pool = _pool(["a", "b", "a", "c", "b", "c", "a"])
    rng = np.random.default_rng(0)
    mat = rng.normal(size=(7, 5)).astype(np.float32)
    assert select_evidence(pool, mat, 5, 3) == select_evidence(pool, mat, 5, 3)


def test_select_maxmin_prefers_far_point():
    # three near-identical vectors plus one distant one; after the floor pick the
    # diversity fill must grab the distant vector before a duplicate
    pool = _pool(["a", "a", "a", "a"])
    mat = np.array([[1, 0], [0.999, 0.04], [0.998, 0.06], [0, 1]], dtype=np.float32)
    idx = select_evidence(pool, mat, n_max=2, floor=1)
    assert idx[1] == 3


def test_select_caps_at_pool_size():
    pool = _pool(["a", "b"])
    mat = np.eye(2, dtype=np.float32)
    assert sorted(select_evidence(pool, mat, 50, 8)) == [0, 1]


# --------------------------------------------------------------------------- read score

def _key(n_pair: int = 5, n_neg: int = 5) -> dict:
    items = []
    for i in range(1, n_pair + 1):
        items.append({"item": i, "kind": "PAIR", "scenario": f"s{i}",
                      "real_side": "A" if i % 2 else "B", "n_moves_real": 3})
    for i in range(n_pair + 1, n_pair + n_neg + 1):
        items.append({"item": i, "kind": "NEG", "header_scenario": "x"})
    return {"items": items}


def _reader(name: str, choices: dict[int, str], negs_no: int = 5,
            apply_all: bool = True) -> dict:
    key = _key()
    items = {}
    neg_seen = 0
    for row in key["items"]:
        i = row["item"]
        if row["kind"] == "PAIR":
            side = choices.get(i, row["real_side"])
            rating = ["APPLY" if apply_all else "VAGUE"] * 3
            items[str(i)] = {"choice": side, "apply_A": rating, "apply_B": rating}
        else:
            neg_seen += 1
            items[str(i)] = {"answer": "NO" if neg_seen <= negs_no else "YES"}
    return {"reader": name, "items": items}


def test_reader_validity_bar():
    key = _key()
    ok, _ = reader_valid(_reader("r", {})["items"], key["items"])
    assert ok
    ok, why = reader_valid(_reader("r", {}, negs_no=3)["items"], key["items"])
    assert not ok and "3/5" in why
    bad = _reader("r", {})
    del bad["items"]["1"]
    ok, why = reader_valid(bad["items"], key["items"])
    assert not ok and "unanswered" in why or "choice" in why


def test_score_rejects_duplicate_reader_identity_and_payload():
    key = _key()
    moves = {f"s{i}": 3 for i in range(1, 6)}
    dup_name = [_reader("r1", {}), _reader("r1", {1: "B"}), _reader("r3", {})]
    with pytest.raises(ValueError, match="duplicate reader identity"):
        score_read(key, dup_name, moves)
    same_payload = [_reader("r1", {}), _reader("r2", {}), _reader("r3", {2: "A"})]
    same_payload[1]["items"] = same_payload[0]["items"]
    with pytest.raises(ValueError, match="byte-identical"):
        score_read(key, same_payload, moves)


def test_score_void_below_three_valid_readers():
    res = score_read(_key(), [_reader("r1", {}), _reader("r2", {}, negs_no=1)],
                     {f"s{i}": 3 for i in range(1, 6)})
    assert res["verdict"] == "VOID"


def _wrong(row_real: str) -> str:
    return "B" if row_real == "A" else "A"


def test_score_pb2_won_at_4_of_5():
    key = _key()
    real_of = {r["item"]: r["real_side"] for r in key["items"] if r["kind"] == "PAIR"}
    # r1 picks real everywhere; r2 and r3 both flip item 1 -> majority wrong there ->
    # 4/5, still WON (r3 rates VAGUE so its payload differs from r2's)
    r1 = _reader("r1", {})
    r2 = _reader("r2", {1: _wrong(real_of[1])})
    r3 = _reader("r3", {1: _wrong(real_of[1])}, apply_all=False)
    res = score_read(key, [r1, r2, r3], {f"s{i}": 3 for i in range(1, 6)})
    assert res["pb2"]["scenarios_real_preferred"] == 4 and res["pb2"]["won"]


def test_score_pb2_not_won_at_3_of_5():
    key = _key()
    real_of = {r["item"]: r["real_side"] for r in key["items"] if r["kind"] == "PAIR"}
    flips = {1: _wrong(real_of[1]), 2: _wrong(real_of[2])}
    readers = [_reader("r1", flips), _reader("r2", flips, apply_all=False),
               _reader("r3", {})]
    res = score_read(key, readers, {f"s{i}": 3 for i in range(1, 6)})
    assert res["pb2"]["scenarios_real_preferred"] == 3 and not res["pb2"]["won"]


def test_score_pb3_median_and_missing_ratings_read_vague():
    key = _key()
    real_of = {r["item"]: r["real_side"] for r in key["items"] if r["kind"] == "PAIR"}
    readers = [_reader("r1", {}), _reader("r2", {2: _wrong(real_of[2])}),
               _reader("r3", {})]
    for jd in readers[:2]:            # two readers rate VAGUE everywhere
        for it in jd["items"].values():
            if "apply_A" in it:
                it["apply_A"] = ["VAGUE"] * 3
                it["apply_B"] = ["VAGUE"] * 3
    res = score_read(key, readers, {f"s{i}": 3 for i in range(1, 6)})
    assert res["pb3"]["median_apply_share"] == 0.0 and not res["pb3"]["pass"]
    # all APPLY -> pass (readers differ on a choice / a NEG so payloads stay distinct)
    res2 = score_read(key, [_reader("r1", {}), _reader("r2", {2: _wrong(real_of[2])}),
                            _reader("r3", {}, negs_no=4)],
                      {f"s{i}": 3 for i in range(1, 6)})
    assert res2["pb3"]["median_apply_share"] == 1.0 and res2["pb3"]["pass"]


def test_sign_test():
    assert sign_test_two_sided(0, 0) == 1.0
    assert abs(sign_test_two_sided(15, 0) - 2 / 2 ** 15) < 1e-12
    assert sign_test_two_sided(8, 7) > 0.5


# ------------------------------------------------------------------- neg + schema + jobs

def _playbook(tag: str) -> dict:
    ev = [{"quote": f"q{tag}{i}", "call": f"c{tag}", "account": f"a{tag}.com"}
          for i in range(2)]
    return {"situation_signature": f"sig {tag}",
            "arc": [f"move {tag}"],
            "key_moves": [{"name": f"move {tag}{j}", "criterion": "crit",
                           "evidence": ev} for j in range(3)],
            "signature_language": [{"phrase": f"p{tag}", **ev[0]}],
            "pitfalls_and_variants": [{"text": f"pit {tag}", "evidence": ev[:1]}],
            "layer_d_checks": [f"chk {tag} {j}" for j in range(3)]}


def test_build_neg_mixes_three_sources():
    docs = [_playbook(t) for t in "abcdef"]
    neg = build_neg(docs, random.Random(1))
    move_tags = {m["name"][5] for m in neg["key_moves"]}
    assert len(neg["key_moves"]) == 3 and len(move_tags) == 3


def test_validate_playbook_accepts_good_and_rejects_bad():
    validate_playbook(_playbook("x"))
    bad = _playbook("x")
    bad["key_moves"] = bad["key_moves"][:2]          # only 2 moves
    with pytest.raises(ValueError):
        validate_playbook(bad)
    bad2 = _playbook("x")
    bad2["key_moves"][0]["evidence"] = bad2["key_moves"][0]["evidence"][:1]  # 1 quote
    with pytest.raises(ValueError):
        validate_playbook(bad2)
    bad3 = _playbook("x")
    bad3["pitfalls_and_variants"][0]["evidence"] = []
    with pytest.raises(ValueError):
        validate_playbook(bad3)


def test_validate_map():
    validate_map({"moves": [{"name": "m", "criterion": "c",
                             "evidence": [{"quote": "q", "call": "c", "account": "a"}]}]})
    with pytest.raises(ValueError):
        validate_map({"moves": []})
    with pytest.raises(ValueError):
        validate_map({"moves": [{"name": "m", "evidence": []}]})


def test_doc_jobs_order_and_placebo_volume_cap():
    ev = {"pilot": ["p1", "p2"], "donors": {"p1": "d1", "p2": "d2"},
          "per_scenario": {
              "p1": {"selected": [{"i": n} for n in range(4)]},
              "d1": {"selected": [{"i": n} for n in range(10)]},
              "p2": {"selected": [{"i": n} for n in range(6)]},
              "d2": {"selected": [{"i": n} for n in range(3)]}}}
    jobs = doc_jobs(ev)
    assert [j["doc_id"] for j in jobs] == ["p1::real", "p1::placebo",
                                           "p2::real", "p2::placebo"]
    assert len(jobs[1]["evidence"]) == 4      # donor capped to real N
    assert len(jobs[3]["evidence"]) == 3      # donor pool smaller: recorded elsewhere
