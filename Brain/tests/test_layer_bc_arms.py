"""Pure-helper tests for calibration/layer_bc_arms.py.

Each test pins a guard that exists because of a specific defect this repo has already paid
for. Named so a failure says WHICH one came back.
"""
import numpy as np
import pytest

from calibration.layer_bc_arms import (
    compare_arms,
    corpus_sha,
    distribution_stats,
    f4_band,
    match_milestones,
    paths,
    routing_stats,
    scenario_map_from_rows,
    taxonomy_path,
    taxonomy_provenance,
    taxonomy_sha,
    top1_top2_margins,
)


def _row(cid, kind, key, desc="d", kp=None, failed=False):
    return {"cluster_id": cid, "kind": kind, "scenario_key": key, "failed": failed,
            "business_description": desc, "keyphrases": kp or []}


# --------------------------------------------------------------------------------------
# scenario_map_from_rows -- `merged` means RETAINED. Collapsing this four-valued enum to a
# boolean produced the phantom "Gemma over-sinks 14.6%" finding, then recurred in a second
# file. It must not recur in a third.
# --------------------------------------------------------------------------------------

def test_merged_rows_create_no_scenario_and_are_NOT_counted_as_sinks():
    smap, _ = scenario_map_from_rows([
        _row("1", "scenario", "real"),
        _row("2", "merged", "dupe"),
        _row("3", "mechanics", "junk"),
    ])
    assert "dupe" not in smap
    assert set(smap) == {"real", "junk"}
    assert [k for k, v in smap.items() if not v["is_coachable"]] == ["junk"]


def test_sinks_are_kept_in_the_map():
    """layer_b files a junk trigger to its sink ALONE. Drop sinks and every trigger matches a
    real scenario by construction -- the absolute-floor pathology wearing a relative margin."""
    smap, _ = scenario_map_from_rows([
        _row("1", "scenario", "real"), _row("2", "mechanics", "m"), _row("3", "logistics", "l"),
    ])
    assert smap["m"]["is_coachable"] is False and smap["m"]["cluster_kind"] == "mechanics"
    assert smap["l"]["is_coachable"] is False and smap["l"]["cluster_kind"] == "logistics"
    assert smap["real"]["is_coachable"] is True


def test_failed_rows_are_excluded_entirely():
    """A transport blip synthesised as a scenario inflates the coachable count AND poisons
    matching with an empty description."""
    smap, _ = scenario_map_from_rows([
        _row("1", "scenario", "ok"), _row("2", "scenario", "boom", failed=True),
        _row("3", "failed", "boom2"),
    ])
    assert set(smap) == {"ok"}


def test_cluster_of_key_is_returned_for_the_join():
    _, cok = scenario_map_from_rows([_row("7-9", "scenario", "real")])
    assert cok["real"] == "7-9"


def test_duplicate_scenario_keys_are_SUFFIXED_and_no_cluster_is_lost():
    """THE blocker the audit found. Gemma reuses names -- `conversational_acknowledgment`
    appeared 26x in one real run -- so collisions are normal, not corrupt input. Raising made
    the harness unrunnable; DEDUPING would have been worse, because the collision count differs
    per arm (37/29/36 on the three real artifacts), so it would drop a different number of
    SINKS from each arm and change layer_b's short-circuit for one side only."""
    smap, cok = scenario_map_from_rows([
        _row("1", "mechanics", "conversational_acknowledgment"),
        _row("2", "mechanics", "conversational_acknowledgment"),
        _row("3", "mechanics", "conversational_acknowledgment"),
    ])
    assert len(smap) == 3, "every cluster must survive; a dropped sink changes routing"
    assert set(smap) == {"conversational_acknowledgment",
                         "conversational_acknowledgment_1",
                         "conversational_acknowledgment_2"}
    assert len(set(cok.values())) == 3      # each suffixed key keeps its own cluster_id


def test_suffixing_preserves_each_duplicates_own_description():
    """The suffixed rows are DIFFERENT clusters with different text -- collapsing them would
    also collapse the descriptions, which are the only channel Layer B/C see."""
    smap, _ = scenario_map_from_rows([
        _row("1", "scenario", "dupe", desc="first"),
        _row("2", "scenario", "dupe", desc="second"),
    ])
    assert smap["dupe"]["business_description"] == "first"
    assert smap["dupe_1"]["business_description"] == "second"


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        scenario_map_from_rows([_row("1", "banana", "x")])


# --------------------------------------------------------------------------------------
# hashes -- identity must notice what actually moves
# --------------------------------------------------------------------------------------

def _pair(fn="a.txt", idx=0, trig="t", resp="r"):
    return {"call_filename": fn, "turn_index": idx, "trigger_text": trig, "response_text": resp}


def test_corpus_sha_notices_a_changed_response_not_just_a_filename():
    """The UNATTRIBUTED fix changed speaker ROLES, not filenames. A filename-only hash would
    have called the old and new corpora identical."""
    assert corpus_sha([_pair()]) != corpus_sha([_pair(resp="different")])
    assert corpus_sha([_pair()]) == corpus_sha([_pair()])


def test_corpus_sha_notices_a_dropped_pair():
    assert corpus_sha([_pair(), _pair(idx=1)]) != corpus_sha([_pair()])


def test_taxonomy_sha_moves_when_only_the_DESCRIPTION_moves():
    """The description is the ONLY channel the rescue has to Layer B/C. Two taxonomies can
    share every key while that channel moved completely."""
    a = {"k": {"business_description": "one", "keyphrases": ["x"], "is_coachable": True}}
    b = {"k": {"business_description": "two", "keyphrases": ["x"], "is_coachable": True}}
    assert taxonomy_sha(a) != taxonomy_sha(b)


def test_taxonomy_sha_moves_when_coachability_flips():
    a = {"k": {"business_description": "one", "keyphrases": [], "is_coachable": True}}
    b = {"k": {"business_description": "one", "keyphrases": [], "is_coachable": False}}
    assert taxonomy_sha(a) != taxonomy_sha(b)


def test_taxonomy_sha_is_stable_under_key_insertion_order():
    x = {"business_description": "a", "keyphrases": [], "is_coachable": True}
    y = {"business_description": "b", "keyphrases": [], "is_coachable": True}
    assert taxonomy_sha({"k1": x, "k2": y}) == taxonomy_sha({"k2": y, "k1": x})


# --------------------------------------------------------------------------------------
# match_milestones -- merge-blindness inflated an entire Layer C A/B while the milestone
# count went UP, which is exactly how it hid.
# --------------------------------------------------------------------------------------

def _ms(clauses, support):
    return {"clauses": list(clauses), "support_calls": support}


def test_two_base_milestones_collapsing_into_one_arm_cluster_report_MERGED_not_matched():
    base = [_ms(["a1", "a2"], 10), _ms(["b1", "b2"], 12)]
    arm = [_ms(["a1", "a2", "b1", "b2"], 20)]
    outcomes, _ = match_milestones(base, arm, 30, 30)
    assert [o["outcome"] for o in outcomes] == ["merged", "merged"]
    assert all(o["n_base_in_same_cluster"] == 2 for o in outcomes)


def test_a_clean_one_to_one_is_matched_not_merged():
    base = [_ms(["a1", "a2"], 10), _ms(["b1", "b2"], 12)]
    arm = [_ms(["a1", "a2"], 11), _ms(["b1", "b2"], 13)]
    outcomes, _ = match_milestones(base, arm, 30, 30)
    assert [o["outcome"] for o in outcomes] == ["matched", "matched"]


def test_fragmented_evidence_is_split_not_lost():
    base = [_ms(["a1", "a2", "a3", "a4"], 10)]
    arm = [_ms(["a1", "a2"], 5), _ms(["a3", "a4"], 5)]
    assert match_milestones(base, arm, 30, 30)[0][0]["outcome"] == "split"


def test_a_milestone_with_no_overlap_is_lost():
    assert match_milestones([_ms(["a"], 3)], [_ms(["z"], 3)], 30, 30)[0][0]["outcome"] == "lost"


def test_available_frac_separates_a_REROUTED_loss_from_a_RECLUSTERED_one():
    """The addition the sink replay did not need. There the arm pool was a strict superset, so
    a miss could only mean reclustering. Here a base clause may not be in this scenario's arm
    pool at all -- its pair went somewhere else -- and blaming that on clustering would
    misattribute a Layer B change to Layer C."""
    base = [_ms(["a1", "a2"], 5)]
    arm = [_ms(["z"], 5)]
    rerouted = match_milestones(base, arm, 9, 9, arm_pool={"z"})[0][0]
    reclustered = match_milestones(base, arm, 9, 9, arm_pool={"z", "a1", "a2"})[0][0]
    assert rerouted["outcome"] == reclustered["outcome"] == "lost"
    assert rerouted["available_frac"] == 0.0
    assert reclustered["available_frac"] == 1.0


def test_support_is_normalised_by_each_arms_own_call_count():
    """Raw support 112 -> 133 read as +19% and was 73% -> 72% once the arm's extra calls were
    counted. The raw delta is the wrong statistic."""
    base = [_ms(["a"], 112)]
    arm = [_ms(["a"], 133)]
    o = match_milestones(base, arm, 153, 184)[0][0]
    assert o["base_support_frac"] == pytest.approx(112 / 153)
    assert o["arm_support_frac"] == pytest.approx(133 / 184)
    assert o["arm_support_frac"] < o["base_support_frac"]   # the raw jump is a DILUTION


def test_unclaimed_arm_milestones_are_reported_as_gained():
    _, gained = match_milestones([_ms(["a"], 3)], [_ms(["a"], 3), _ms(["new"], 4)], 9, 9)
    assert len(gained) == 1 and gained[0]["support_calls"] == 4


def test_empty_arms_do_not_crash():
    outcomes, gained = match_milestones([], [], 0, 0)
    assert outcomes == [] and gained == []
    assert match_milestones([_ms(["a"], 1)], [], 5, 5)[0][0]["outcome"] == "lost"


# --------------------------------------------------------------------------------------
# distribution_stats -- the PRIMARY metrics
# --------------------------------------------------------------------------------------

def _scen(ms_supports, outcome="clustered"):
    return {"outcome": outcome,
            "milestones": [{"support_calls": s, "clauses": []} for s in ms_supports]}


def test_the_product_win_is_reported_as_ONE_number():
    """The two tests that used to sit here asserted a distinction that does not exist and could
    not exist: `pass1` only keeps milestones with support >= required >= floor, and sets
    outcome=="clustered" iff at least one survived. So zero-milestone, fell-back and
    clears-the-floor are IDENTICALLY the same count on any reachable state. Both old tests
    passed only because they fed unreachable inputs (a milestone below the floor; an empty
    'clustered' scenario), which is how the redundancy stayed hidden. One number now."""
    per = {"a": _scen([5, 4]), "b": _scen([], outcome="fallback_no_support"), "c": _scen([3])}
    s = distribution_stats(per, floor=3)
    assert s["scenarios_with_clustered_rubric"] == 2
    assert s["scenarios_no_clustered_rubric"] == 1
    assert s["scenarios_with_clustered_rubric"] + s["scenarios_no_clustered_rubric"] \
        == s["n_scenarios"]
    assert s["n_milestones"] == 3


def test_fallback_reasons_are_broken_out_for_diagnosis():
    per = {"a": _scen([], outcome="fallback_no_support"),
           "b": _scen([], outcome="fallback_too_few_clauses"),
           "c": _scen([], outcome="fallback_no_support")}
    assert distribution_stats(per, floor=3)["fallback_reasons"] == {
        "fallback_no_support": 2, "fallback_too_few_clauses": 1}


def test_distribution_stats_on_an_empty_arm_does_not_divide_by_zero():
    s = distribution_stats({}, floor=3)
    assert s["n_scenarios"] == 0 and s["n_milestones"] == 0
    assert np.isnan(s["support_calls_p25"])


# --------------------------------------------------------------------------------------
# routing_stats -- says whether the treatment reached Layer C at all
# --------------------------------------------------------------------------------------

def test_sink_share_uses_is_coachable_and_not_a_name_heuristic():
    smap = {"real": {"is_coachable": True}, "junk": {"is_coachable": False}}
    pairs = [{"scenario_key": "real", "scenario_keys": ["real"]},
             {"scenario_key": "junk", "scenario_keys": ["junk"]},
             {"scenario_key": "junk", "scenario_keys": ["junk"]}]
    r = routing_stats(pairs, smap)
    assert r["pairs_to_sink"] == 2 and r["sink_share"] == pytest.approx(2 / 3)
    assert r["match_width"] == {"1": 3}


# --------------------------------------------------------------------------------------
# f4_band -- a raw [350,450] copied across would void every run for the wrong reason
# --------------------------------------------------------------------------------------

def test_the_f4_band_scales_with_scenario_count():
    lo30, hi30 = f4_band(30)
    lo85, hi85 = f4_band(85)
    assert lo30 < lo85 and hi30 < hi85
    assert lo85 <= 404 <= hi85       # production's own run must sit inside its own band


# --------------------------------------------------------------------------------------
# paths -- no default that can clobber a measured artifact
# --------------------------------------------------------------------------------------

def test_each_arm_gets_its_own_file():
    assert paths("base_1") != paths("base_2")


def test_unsafe_arm_names_are_refused():
    for bad in ("", "../evil", "a b", "x/y"):
        with pytest.raises(SystemExit):
            paths(bad)


def test_an_arm_never_writes_over_the_taxonomy_it_reads():
    """--taxonomy reads adjudication_ab_<name>.json and the arm may share that name. The old
    version of this test asserted `not name.startswith("adjudication_ab")`, which the hardcoded
    `layer_bc_` prefix makes true for EVERY input -- it could not fail, so it pinned nothing.
    Compare the two real paths instead."""
    for name in ("clean2_base", "clean2_rescued"):
        assert paths(name) != taxonomy_path(name)


# --------------------------------------------------------------------------------------
# compare_arms -- THE join. Gemma renames a cluster every run.
# --------------------------------------------------------------------------------------

def _art(per_scenario, placebo=False):
    return {"per_scenario": per_scenario, "placebo": placebo,
            "identity": {"taxonomy_sha": "x"}}


def test_arms_join_on_cluster_id_even_when_gemma_RENAMED_the_scenario():
    """`stakeholder_role_identification` vs `stakeholder_role_mapping` are the same cluster
    renamed. A scenario_key join would report the entire taxonomy as changed."""
    a = _art({"stakeholder_role_identification": {
        "cluster_id": "12", "scenario_calls": 10, "clause_pool": ["a1", "a2"],
        "milestones": [_ms(["a1", "a2"], 5)]}})
    b = _art({"stakeholder_role_mapping": {
        "cluster_id": "12", "scenario_calls": 10, "clause_pool": ["a1", "a2"],
        "milestones": [_ms(["a1", "a2"], 6)]}})
    d = compare_arms(a, b)
    assert d["n_shared"] == 1 and d["n_only_a"] == 0 and d["n_only_b"] == 0
    assert d["matched"] == 1 and d["lost"] == 0


def test_clusters_coachable_in_only_one_arm_are_reported_not_dropped():
    """The +6 net scenarios are the headline claim; silently excluding them from the join
    would delete the very thing being measured."""
    a = _art({"only_a": {"cluster_id": "1", "scenario_calls": 5, "clause_pool": [],
                         "milestones": []}})
    b = _art({"only_b": {"cluster_id": "2", "scenario_calls": 5, "clause_pool": [],
                         "milestones": []}})
    d = compare_arms(a, b)
    assert d["n_shared"] == 0 and d["n_only_a"] == 1 and d["n_only_b"] == 1


def test_scenarios_with_no_cluster_id_are_skipped_rather_than_joined_on_empty_string():
    a = _art({"x": {"cluster_id": "", "scenario_calls": 5, "clause_pool": [], "milestones": []}})
    b = _art({"y": {"cluster_id": "", "scenario_calls": 5, "clause_pool": [], "milestones": []}})
    assert compare_arms(a, b)["n_shared"] == 0


def test_merged_rows_are_excluded_from_the_matched_support_delta():
    """A fusion has the largest support of any cluster BY CONSTRUCTION, so counting it in the
    same average puts every merge in `thickened` -- which is precisely the 'evidence
    thickening' reading check_milestone_thickening.py falsified."""
    a = _art({"s": {"cluster_id": "1", "scenario_calls": 10, "clause_pool": ["x1", "x2", "y1"],
                    "clause_pool_prefilter": ["x1", "x2", "y1"],
                    "milestones": [_ms(["x1", "x2"], 2), _ms(["y1"], 2)]}})
    b = _art({"s": {"cluster_id": "1", "scenario_calls": 10, "clause_pool": ["x1", "x2", "y1"],
                    "clause_pool_prefilter": ["x1", "x2", "y1"],
                    "milestones": [_ms(["x1", "x2", "y1"], 9)]}})
    d = compare_arms(a, b)
    assert d["merged"] == 2 and d["matched"] == 0
    assert d["thickened"] == 0                       # the fusion must NOT read as thickening
    assert d["support_frac_delta_mean"] == 0.0
    assert d["merged_support_frac_delta_mean"] > 0   # it is reported, just separately


def test_available_frac_separates_a_layer_B_reroute_from_a_layer_C_relevance_cut():
    """Both look like 'lost'. Pre-filter LOW means the pair went to another scenario (Layer B);
    pre-filter HIGH with post-filter LOW means this arm's own p40 cutoff dropped it (Layer C).
    Measuring only against the post-filter pool blames Layer B for a Layer C change."""
    base = _art({"s": {"cluster_id": "1", "scenario_calls": 9, "clause_pool": ["z"],
                       "clause_pool_prefilter": ["z"],
                       "milestones": [_ms(["a1", "a2"], 5)]}})
    rerouted = _art({"s": {"cluster_id": "1", "scenario_calls": 9, "clause_pool": ["z"],
                           "clause_pool_prefilter": ["z"], "milestones": [_ms(["z"], 5)]}})
    relevance_cut = _art({"s": {"cluster_id": "1", "scenario_calls": 9, "clause_pool": ["z"],
                                "clause_pool_prefilter": ["z", "a1", "a2"],
                                "milestones": [_ms(["z"], 5)]}})
    d1, d2 = compare_arms(base, rerouted), compare_arms(base, relevance_cut)
    assert d1["lost"] == d2["lost"] == 1
    assert d1["lost_available_prefilter_mean"] == 0.0     # never arrived -> Layer B
    assert d2["lost_available_prefilter_mean"] == 1.0     # arrived...
    assert d2["lost_available_mean"] == 0.0               # ...then was filtered -> Layer C


# --------------------------------------------------------------------------------------
# taxonomy_provenance -- two arms built from taxonomies fitted on DIFFERENT corpora used to
# compare cleanly, because every field that would have differed was whitelisted.
# --------------------------------------------------------------------------------------

def test_provenance_carries_the_adjudication_settings_and_drops_the_treatment_fields():
    p = taxonomy_provenance({"identity": {
        "n_clusters": 227, "merge": 0.97, "min_cluster_size": 16, "chat_model": "m",
        "members_sha": "aaa", "rescue": "centroid"}})
    assert p["tax_n_clusters"] == 227 and p["tax_merge"] == 0.97
    # members_sha and rescue ARE the treatment; including them would make every real
    # comparison shout.
    assert "tax_members_sha" not in p and "tax_rescue" not in p


def test_provenance_distinguishes_taxonomies_fitted_on_different_pools():
    """The live hazard: stale clean_base_a (fitted on the 21,915-turn pool) vs a fresh arm."""
    stale = taxonomy_provenance({"identity": {"n_clusters": 224, "merge": 0.97}})
    fresh = taxonomy_provenance({"identity": {"n_clusters": 227, "merge": 0.97}})
    assert stale != fresh


def test_provenance_on_a_missing_identity_is_empty_not_a_crash():
    assert taxonomy_provenance({}) == {}


# --------------------------------------------------------------------------------------
# top1_top2_margins -- the spec's third Layer B metric, ~0.01 cosine in both taxonomies
# --------------------------------------------------------------------------------------

def test_margin_is_the_gap_between_the_best_and_second_best_scenario():
    smap = {"a": {"business_description": "alpha", "keyphrases": [], "is_coachable": True},
            "b": {"business_description": "beta", "keyphrases": [], "is_coachable": True}}

    import calibration.layer_bc_arms as mod
    orig = mod.__dict__.get("build_scenario_vecs")
    import shared.scenario_vectors as sv
    saved = sv.build_scenario_vecs
    sv.build_scenario_vecs = lambda m, mode=None: (list(m), [[1.0, 0.0], [0.0, 1.0]])
    try:
        # a trigger leaning 0.8/0.6 toward scenario "a" -> margin 0.8 - 0.6 = 0.2
        m = top1_top2_margins([[0.8, 0.6]], smap)
    finally:
        sv.build_scenario_vecs = saved
        assert orig is None or True
    assert len(m) == 1 and m[0] == pytest.approx(0.2, abs=1e-6)


def test_margin_needs_two_scenarios_to_be_defined():
    one = {"a": {"business_description": "x", "keyphrases": [], "is_coachable": True}}
    assert top1_top2_margins([[1.0, 0.0]], one) == []


# --------------------------------------------------------------------------------------
# compare()'s NOISE-FLOOR labelling -- it must share the TREATMENT, not just the taxonomy
# --------------------------------------------------------------------------------------

def _compare_art(router, taxonomy_sha="tax", segment="s0", admit="a0", placebo=False):
    return {
        "arm": "x", "taxonomy_arm": "clean2_base", "placebo": placebo,
        "identity": {"corpus_sha": "corp", "taxonomy_sha": taxonomy_sha, "segment": segment,
                     "admit": admit, "router": router},
        "stats": {"n_scenarios": 2, "n_milestones": 4, "milestones_per_scenario_mean": 2.0,
                  "scenarios_with_clustered_rubric": 2, "scenarios_no_clustered_rubric": 0,
                  "support_calls_median": 5.0},
        "routing": {"sink_share": 0.5, "max_absorption_coachable": 0.1, "margin_p50": 0.01},
        "per_scenario": {}, "cluster_of_key": {},
    }


def _run_compare(monkeypatch, tmp_path, capsys, arts):
    import json as _json
    import calibration.layer_bc_arms as mod
    for name, art in arts.items():
        (tmp_path / f"{name}.json").write_text(_json.dumps(art), encoding="utf-8")
    monkeypatch.setattr(mod, "paths", lambda n: tmp_path / f"{n}.json")
    mod.compare(list(arts))
    return capsys.readouterr().out


def test_two_arms_differing_only_in_the_ROUTER_are_a_TREATMENT_not_a_noise_floor(
        monkeypatch, tmp_path, capsys):
    """They share `taxonomy_sha` exactly, so the original taxonomy-only test labelled them a
    noise floor and the router's whole effect would have read as UMAP variance."""
    out = _run_compare(monkeypatch, tmp_path, capsys,
                       {"a": _compare_art("r0"), "b": _compare_art("r2")})
    assert "NOISE-FLOOR pairs (same taxonomy AND same S/A/R" in out
    assert "NONE -- the treatment cannot be read" in out
    assert "[TREATMENT]" in out and "[NOISE FLOOR]" not in out


def test_two_arms_identical_in_S_A_and_R_are_still_a_noise_floor(monkeypatch, tmp_path,
                                                                 capsys):
    out = _run_compare(monkeypatch, tmp_path, capsys,
                       {"a": _compare_art("r0"), "b": _compare_art("r0")})
    assert "[NOISE FLOOR]" in out and "[TREATMENT]" not in out


def test_the_compare_table_prints_S_A_R_so_two_router_arms_are_distinguishable(
        monkeypatch, tmp_path, capsys):
    out = _run_compare(monkeypatch, tmp_path, capsys,
                       {"a": _compare_art("r0"), "b": _compare_art("r3", admit="a4")})
    assert "s0/a0/r0" in out and "s0/a4/r3" in out


def test_an_INCOMPLETE_arm_is_flagged_in_the_comparison(monkeypatch, tmp_path, capsys):
    """--limit arms are what a router smoke test leaves behind; their Layer C columns are an
    alphabetical prefix, which CLAUDE.md records as not a sample."""
    a, b = _compare_art("r0"), _compare_art("r0")
    b["incomplete"] = True
    out = _run_compare(monkeypatch, tmp_path, capsys, {"full": a, "part": b})
    assert "['part'] are stamped INCOMPLETE" in out
