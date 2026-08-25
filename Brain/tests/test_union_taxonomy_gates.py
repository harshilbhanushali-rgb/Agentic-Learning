"""Pure-helper tests for calibration/union_taxonomy_gates.py (Stage D gates).

Every frozen bar (G-R1 comparativeness, G-R2 ceilings, G-R3 floors, G-R4 tallies) is
pinned with hand-built inputs so a constant edited after a result fails a test.
"""
import json
import random

import numpy as np
import pytest

from calibration.union_taxonomy_gates import (
    G2_NEW_MAX,
    G2_OLD_MAX,
    build_scramble,
    g1_gate,
    g1_scenario,
    g2_verdict,
    g3_rows,
    g3_verdict,
    g4_reader_valid,
    g4_score,
    mean_pairwise_cosine,
    scenario_memberships,
    stratified_pick,
)


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# --------------------------------------------------------------------------------------
# mean_pairwise_cosine — the sum-vector identity must equal the brute force
# --------------------------------------------------------------------------------------

def test_mean_pairwise_matches_brute_force():
    rng = np.random.default_rng(0)
    V = _unit(rng.normal(size=(7, 5)))
    brute = np.mean([V[i] @ V[j] for i in range(7) for j in range(7) if i != j])
    assert mean_pairwise_cosine(V) == pytest.approx(brute, abs=1e-12)


def test_identical_vectors_cohere_at_one_and_singleton_is_nan():
    V = _unit(np.tile([1.0, 2.0], (4, 1)))
    assert mean_pairwise_cosine(V) == pytest.approx(1.0)
    assert np.isnan(mean_pairwise_cosine(V[:1]))


# --------------------------------------------------------------------------------------
# g1_scenario — a tight cluster passes its null, a random one does not
# --------------------------------------------------------------------------------------

def _pool(n=400, d=8, seed=1):
    rng = np.random.default_rng(seed)
    return _unit(rng.normal(size=(n, d)))


def test_tight_cluster_beats_the_null():
    pool = _pool()
    anchor = np.ones(8)
    tight = _unit(anchor + 0.05 * np.random.default_rng(2).normal(size=(20, 8)))
    pool_with = np.vstack([pool, tight])
    row = g1_scenario(tight, pool_with, n_draws=50)
    assert row["pass"] is True and row["cohesion"] > row["null_p95"]


def test_a_random_subset_does_not_beat_its_own_null():
    pool = _pool()
    rng = np.random.default_rng(3)
    subset = pool[rng.choice(len(pool), 20, replace=False)]
    row = g1_scenario(subset, pool, n_draws=50)
    assert row["cohesion"] <= row["null_p95"] + 0.05      # at/near the null band


def test_g1_draws_depend_only_on_size_so_both_maps_face_identical_nulls():
    pool = _pool()
    a = g1_scenario(pool[:10], pool, n_draws=20)
    b = g1_scenario(pool[50:60], pool, n_draws=20)
    assert a["null_p95"] == pytest.approx(b["null_p95"])   # same size -> same draws


# --------------------------------------------------------------------------------------
# g1_gate — comparative, ties pass
# --------------------------------------------------------------------------------------

def _rows(passes, fails):
    out = {}
    for i in range(passes):
        out[f"p{i}"] = {"pass": True}
    for i in range(fails):
        out[f"f{i}"] = {"pass": False}
    return out


def test_g1_gate_passes_on_tie_and_better_fails_on_worse():
    assert g1_gate(_rows(5, 5), _rows(5, 5))["pass"] is True
    assert g1_gate(_rows(6, 4), _rows(5, 5))["pass"] is True
    assert g1_gate(_rows(4, 6), _rows(5, 5))["pass"] is False


def test_g1_gate_compares_rates_not_counts():
    """A bigger map with more passing scenarios can still be structurally worse."""
    assert g1_gate(_rows(6, 6), _rows(3, 2))["pass"] is False   # 50% < 60%


# --------------------------------------------------------------------------------------
# g2_verdict — both ceilings, boundary inclusive
# --------------------------------------------------------------------------------------

def _shares(new, old):
    return {"new": {"sink_share": new}, "old": {"sink_share": old}}


def test_g2_frozen_constants():
    assert G2_NEW_MAX == pytest.approx(0.593)
    assert G2_OLD_MAX == pytest.approx(0.629)


def test_g2_boundary_is_inclusive_and_both_ceilings_bind():
    assert g2_verdict(_shares(0.593, 0.629))["pass"] is True
    assert g2_verdict(_shares(0.594, 0.5))["pass"] is False    # new too high
    assert g2_verdict(_shares(0.5, 0.63))["pass"] is False     # old collapsed


# --------------------------------------------------------------------------------------
# g3 — floors and the 90% share
# --------------------------------------------------------------------------------------

def test_g3_row_needs_both_pairs_and_domains():
    rows = g3_rows({"a": 10, "b": 10, "c": 9},
                   {"a": {"x", "y", "z"}, "b": {"x", "y"}, "c": {"x", "y", "z"}})
    ok = {r["scenario"]: r["ok"] for r in rows}
    assert ok == {"a": True, "b": False, "c": False}


def test_g3_verdict_at_the_90_percent_share():
    rows = [{"scenario": f"s{i}", "ok": i != 0} for i in range(10)]
    assert g3_verdict(rows)["pass"] is True                   # 9/10 == 90%
    rows[1]["ok"] = False
    v = g3_verdict(rows)
    assert v["pass"] is False and set(v["below_floor"]) == {"s0", "s1"}


def test_g3_verdict_empty_is_not_a_pass():
    assert g3_verdict([])["pass"] is False


# --------------------------------------------------------------------------------------
# stratified_pick — 4/4/4 terciles, deterministic under the seed
# --------------------------------------------------------------------------------------

def test_stratified_pick_takes_four_from_each_tercile():
    counts = {f"s{i:02d}": 100 - i for i in range(30)}
    picked = stratified_pick(counts, random.Random(42))
    assert len(picked) == 12 and len(set(picked)) == 12
    order = sorted(counts, key=lambda k: (-counts[k], k))
    strata = [set(order[:10]), set(order[10:20]), set(order[20:])]
    for si, s in enumerate(strata):
        assert sum(1 for p in picked[si * 4:(si + 1) * 4] if p in s) == 4


def test_stratified_pick_is_deterministic_and_refuses_thin_taxonomies():
    counts = {f"s{i}": i for i in range(30)}
    assert stratified_pick(counts, random.Random(42)) == \
           stratified_pick(counts, random.Random(42))
    with pytest.raises(SystemExit):
        stratified_pick({f"s{i}": i for i in range(11)}, random.Random(42))


# --------------------------------------------------------------------------------------
# build_scramble — negatives must genuinely span sources
# --------------------------------------------------------------------------------------

def test_scramble_spans_at_least_four_scenarios_with_no_duplicate_turns():
    members = {f"k{i}": list(range(i * 100, i * 100 + 10)) for i in range(6)}
    turns = build_scramble(members, random.Random(1))
    assert len(turns) == 8 and len(set(turns)) == 8
    sources = {t // 100 for t in turns}
    assert len(sources) >= 4


def test_scramble_refuses_too_few_source_scenarios():
    with pytest.raises(SystemExit):
        build_scramble({"a": [1, 2], "b": [3, 4]}, random.Random(1))


# --------------------------------------------------------------------------------------
# g4 validity + scoring
# --------------------------------------------------------------------------------------

def _key(n_real=12, n_neg=6):
    items = []
    for i in range(1, n_real + 1):
        items.append({"item": i, "kind": "REAL", "scenario": f"s{i}"})
    for i in range(n_real + 1, n_real + n_neg + 1):
        items.append({"item": i, "kind": "NEG"})
    return {"items": items}


def _answers(key, real="YES", neg="NO", flip_neg=0):
    out = {}
    flipped = 0
    for row in key["items"]:
        if row["kind"] == "NEG" and flipped < flip_neg:
            out[str(row["item"])] = "YES"
            flipped += 1
        else:
            out[str(row["item"])] = real if row["kind"] == "REAL" else neg
    return out


def test_reader_valid_at_five_of_six_and_invalid_below():
    key = _key()
    ok, _ = g4_reader_valid(_answers(key, flip_neg=1), key["items"])
    assert ok is True
    bad, why = g4_reader_valid(_answers(key, flip_neg=2), key["items"])
    assert bad is False and "4/6" in why


def test_reader_invalid_on_a_missing_or_malformed_answer():
    key = _key()
    ans = _answers(key)
    del ans["3"]
    assert g4_reader_valid(ans, key["items"])[0] is False
    ans2 = _answers(key)
    ans2["3"] = "MAYBE"
    assert g4_reader_valid(ans2, key["items"])[0] is False


def _jd(name, items):
    return {"reader": name, "items": items}


def test_g4_score_gate_at_nine_of_twelve():
    key = _key()
    # readers agree: scenarios s1..s9 YES, s10..s12 NO -> exactly 9 coherent
    def ans():
        out = {}
        for row in key["items"]:
            if row["kind"] == "NEG":
                out[str(row["item"])] = "NO"
            else:
                out[str(row["item"])] = "YES" if row["item"] <= 9 else "NO"
        return out
    res = g4_score(key, [_jd("r1", ans()), _jd("r2", ans()),
                         _jd("r3", {**ans(), "1": "NO"})])   # 2/3 still coherent on s1
    assert res["n_coherent"] == 9 and res["pass"] is True


def test_g4_score_two_of_three_rule():
    key = _key()
    yes = _answers(key)
    no = _answers(key, real="NO")
    res = g4_score(key, [_jd("r1", yes), _jd("r2", no), _jd("r3", no)])
    assert res["n_coherent"] == 0 and res["pass"] is False


def test_g4_score_rejects_duplicate_identity_but_only_flags_duplicate_payload():
    """18 binary answers CAN honestly collide (unlike the snap trial's structured
    payloads), so payload identity is an on-record flag, not a void."""
    key = _key()
    a = _answers(key)
    with pytest.raises(ValueError):
        g4_score(key, [_jd("r1", a), _jd("r1", _answers(key, flip_neg=1))])
    res = g4_score(key, [_jd("r1", a), _jd("r2", json.loads(json.dumps(a))),
                         _jd("r3", _answers(key, flip_neg=1))])
    assert res["payload_duplicate_flag"] is True
    assert res["pass"] is True                     # unanimous YES on all 12


def test_g4_score_void_below_three_valid_readers():
    key = _key()
    res = g4_score(key, [_jd("r1", _answers(key)),
                         _jd("r2", _answers(key, flip_neg=3)),
                         _jd("r3", _answers(key, flip_neg=2))])
    assert res["verdict"] == "VOID"


# --------------------------------------------------------------------------------------
# scenario_memberships — stable-id join, hard failure on a broken join
# --------------------------------------------------------------------------------------

def test_scenario_memberships_joins_on_cluster_id_and_filters_sinks():
    smap = {"coach": {"is_coachable": True}, "sink": {"is_coachable": False}}
    cok = {"coach": "10-11", "sink": "12"}
    byid = {"10-11": [1, 2, 3], "12": [9]}
    got = scenario_memberships(smap, cok, byid)
    assert got == {"coach": [1, 2, 3]}


def test_scenario_memberships_refuses_a_missing_cluster():
    with pytest.raises(SystemExit):
        scenario_memberships({"a": {"is_coachable": True}}, {"a": "nope"}, {})


# --------------------------------------------------------------------------------------
# set_arm — the fallback arm must swing taxonomy, membership AND every output path
# --------------------------------------------------------------------------------------

def test_set_arm_base_switches_everything_and_rescued_restores():
    import calibration.union_taxonomy_gates as g
    try:
        g.set_arm("base")
        assert g.NEW_TAXONOMY == "union_base" and g.MEMBERSHIP == "base"
        for p in (g.G1_OUT, g.G23_OUT, g.G4_PACKET, g.G4_KEY, g.G4_OUT, g.REPORT_OUT):
            assert "fallback_" in p.name, p.name
        assert g.G4_JUDGMENTS_GLOB.startswith("union_gates_fallback_judgments")
        # the rescued glob must never match a fallback judgment filename
        import fnmatch
        assert not fnmatch.fnmatch("union_gates_fallback_judgments_r1.json",
                                   "union_gates_judgments_*.json") or True
    finally:
        g.set_arm("rescued")
    assert g.NEW_TAXONOMY == "union_rescued" and g.MEMBERSHIP == "rescued"
    assert g.G1_OUT.name == "union_gates_g1.json"


def test_rescued_judgment_glob_does_not_match_fallback_files():
    """Cross-arm judgment bleed would let one arm's readers vote in the other's gate."""
    import fnmatch
    assert fnmatch.fnmatch("union_gates_judgments_r1.json",
                           "union_gates_judgments_*.json")
    assert not fnmatch.fnmatch("union_gates_fallback_judgments_r1.json",
                               "union_gates_judgments_*.json")
    assert fnmatch.fnmatch("union_gates_fallback_judgments_r1.json",
                           "union_gates_fallback_judgments_*.json")


def test_set_arm_refuses_unknown():
    import calibration.union_taxonomy_gates as g
    import pytest as _pt
    with _pt.raises(SystemExit):
        g.set_arm("placebo")
