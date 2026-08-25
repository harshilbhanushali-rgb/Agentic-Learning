"""Tests for calibration/expanded_pool_stage1.py's pure helpers.

Hand-built inputs only — no corpus, no embedder, no artifacts. The rule being tested is the
harness's own logic (F0 comparison, origin split, gain classification, failing-cluster fate),
not production Layer B/C, which the harness imports rather than paraphrases.
"""
import pytest

from calibration.expanded_pool_stage1 import (
    assert_no_stem_collision, restrict_to_old, f0_union_check, origin_of,
    sink_share_by_origin, classify_gained, join_gained_to_milestones,
    merge_account_maps, failing_candidates, failing_fate,
)


# --- stem collision ----------------------------------------------------------------------

def test_stem_collision_raises():
    with pytest.raises(SystemExit):
        assert_no_stem_collision({"a", "b"}, {"b", "c"})


def test_disjoint_stems_pass():
    assert_no_stem_collision({"a"}, {"b"})  # no raise


# --- F0-union ----------------------------------------------------------------------------

def test_f0_identical_passes():
    r = f0_union_check(["x", "y"], ["x", "y"])
    assert r["ok"] and r["n"] == 2


def test_f0_order_matters():
    r = f0_union_check(["y", "x"], ["x", "y"])
    assert not r["ok"] and r["first_divergence_index"] == 0


def test_f0_length_mismatch_reports_divergence_at_end():
    r = f0_union_check(["x", "y", "z"], ["x", "y"])
    assert not r["ok"] and r["first_divergence_index"] == 2


def test_restrict_to_old_preserves_order():
    resp = [{"call_filename": "a.txt", "i": 0}, {"call_filename": "n.txt", "i": 1},
            {"call_filename": "b.txt", "i": 2}]
    got = restrict_to_old(resp, {"a.txt", "b.txt"})
    assert [r["i"] for r in got] == [0, 2]


# --- origin split ------------------------------------------------------------------------

def test_sink_share_by_origin_symmetric_predicate():
    smap = {"real": {"is_coachable": True}, "sink": {"is_coachable": False}}
    pairs = [{"call_filename": "o.txt", "scenario_key": "real"},
             {"call_filename": "o.txt", "scenario_key": "sink"},
             {"call_filename": "n.txt", "scenario_key": "sink"},
             {"call_filename": "n.txt", "scenario_key": "sink"}]
    r = sink_share_by_origin(pairs, smap, {"n.txt"})
    assert r["old"]["n_pairs"] == 2 and r["old"]["to_sink"] == 1
    assert r["new"]["n_pairs"] == 2 and r["new"]["sink_share"] == 1.0
    assert origin_of("n.txt", {"n.txt"}) == "new"
    assert origin_of("o.txt", {"n.txt"}) == "old"


# --- gain classification -----------------------------------------------------------------

def test_classify_gained_new_data_necessary():
    m = {"support_call_files": ["old1.txt", "new1.txt", "new2.txt"]}
    g = classify_gained(m, required_support=3, old_calls={"old1.txt"},
                        old_domains={"acme.com"},
                        accounts={"new1": "fresh.com", "new2": "acme.com"})
    # 1 old call < required 3 -> the milestone could not exist without new data
    assert g["new_data_necessary"] is True
    # fresh.com never appeared in the old corpus -> honest gain
    assert g["new_account_backed"] is True and g["new_accounts"] == ["fresh.com"]


def test_classify_gained_repeat_account_padding():
    m = {"support_call_files": ["old1.txt", "old2.txt", "old3.txt", "new1.txt"]}
    g = classify_gained(m, required_support=3, old_calls={"old1.txt", "old2.txt", "old3.txt"},
                        old_domains={"acme.com"}, accounts={"new1": "acme.com"})
    assert g["new_data_necessary"] is False       # old support 3 >= required 3
    assert g["new_account_backed"] is False       # only a repeat account arrived


def test_classify_gained_unaccounted_new_call_contributes_nothing():
    m = {"support_call_files": ["new1.txt"]}
    g = classify_gained(m, required_support=1, old_calls=set(),
                        old_domains=set(), accounts={})
    assert g["new_account_backed"] is False       # no resolvable account, never a win


# --- gained join -------------------------------------------------------------------------

def test_join_gained_round_trip():
    ms = [{"support_calls": 3, "clauses": ["a", "b", "c", "d"], "support_call_files": ["x"]},
          {"support_calls": 5, "clauses": ["e", "f"], "support_call_files": ["y"]}]
    gained = [{"support_calls": 5, "clauses": ["e", "f"]}]
    got = join_gained_to_milestones(gained, ms)
    assert got[0]["support_call_files"] == ["y"]


def test_join_gained_ambiguous_raises():
    ms = [{"support_calls": 3, "clauses": ["a"], "support_call_files": ["x"]},
          {"support_calls": 3, "clauses": ["a"], "support_call_files": ["y"]}]
    with pytest.raises(ValueError):
        join_gained_to_milestones([{"support_calls": 3, "clauses": ["a"]}], ms)


# --- account maps ------------------------------------------------------------------------

def test_merge_account_maps_disjoint():
    got = merge_account_maps([{"a": "x.com"}, {"b": "y.com"}])
    assert got == {"a": "x.com", "b": "y.com"}


def test_merge_account_maps_conflict_raises():
    with pytest.raises(ValueError):
        merge_account_maps([{"a": "x.com"}, {"a": "y.com"}])


# --- failing clusters --------------------------------------------------------------------

def _cand(support, files):
    return {"support_calls": support, "support_call_files": files,
            "support_clauses": support, "cluster_id": 0, "support_frac": 0.1,
            "median_position": 1.0, "relevance_mean": 0.5}


def test_failing_candidates_filters_below_required():
    ps = {"s1": {"required_support": 3,
                 "candidates_pregate": [_cand(2, ["a"]), _cand(3, ["a", "b", "c"])]},
          "s2": {"required_support": None, "candidates_pregate": [_cand(1, ["z"])]}}
    got = failing_candidates(ps)
    assert len(got) == 1 and got[0]["scenario_key"] == "s1" and got[0]["support_calls"] == 2


def test_failing_fate_matched_and_clears():
    ctrl = [{"scenario_key": "s1", "required": 3, **_cand(2, ["a.txt", "b.txt"])}]
    union = {"s1": {"required_support": 4,
                    "candidates_pregate": [_cand(5, ["a.txt", "b.txt", "n1.txt", "n2.txt",
                                                     "n3.txt"])]}}
    got = failing_fate(ctrl, union, old_calls={"a.txt", "b.txt"})
    assert got[0]["matched"] and got[0]["now_clears"] and got[0]["overlap"] == 1.0


def test_failing_fate_new_call_overlap_does_not_count():
    # A union candidate whose overlap comes only from NEW calls must not match: identity is
    # asserted through the OLD corpus, which both arms share.
    ctrl = [{"scenario_key": "s1", "required": 3, **_cand(2, ["a.txt", "b.txt"])}]
    union = {"s1": {"required_support": 3,
                    "candidates_pregate": [_cand(4, ["n1.txt", "n2.txt", "n3.txt",
                                                     "n4.txt"])]}}
    got = failing_fate(ctrl, union, old_calls={"a.txt", "b.txt"})
    assert not got[0]["matched"] and not got[0]["now_clears"]
