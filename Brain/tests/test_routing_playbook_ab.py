"""Tests for calibration/routing_playbook_ab.py (three-arm routing A/B).

Spec: docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md (frozen).

The synthesis/snap/PB0/selection machinery is imported from the two validated harnesses
and is already covered by test_scenario_playbook_trial.py / test_playbook_snap_trial.py;
r1's routing internals are covered by test_layer_b_routers.py. What is NEW and pinned
here is everything this design adds on top:

  * the base-membership projection and its content-hash PIN (T-R0)
  * the scenario_vector_mode install and its read-back, plus the fallback detector that
    stops a keyphrases/concat MIXTURE from passing as the treatment
  * G-D, the pre-spend divergence gate
  * the counterbalancing rule across BOTH dimensions (rank position and comparison)
  * packet composition
  * the head-to-head scorer: G-V, G-P-as-VOID, and G-W at its exact bar
  * the cross-arm budget ledger
"""
import json
import sys

import pytest

from calibration import routing_playbook_ab as rt


# --------------------------------------------------------------------------------------
# T-R0 — the base-membership projection and its pin
# --------------------------------------------------------------------------------------

def test_project_base_clusters_reads_idxs_base_only():
    art = {"clusters": [
        {"cluster_id": "c0", "idxs_base": [3, 1], "idxs_rescued": [3, 1, 9]},
        {"cluster_id": "c1", "idxs_base": [7], "idxs_rescued": [7, 8]},
    ]}
    out = rt.project_base_clusters(art)
    assert out == [{"cluster_id": "c0", "idxs": [3, 1]},
                   {"cluster_id": "c1", "idxs": [7]}]


def test_project_base_clusters_rejects_duplicate_cluster_id():
    """The cluster_id is the join key between memberships and adjudication rows. A
    duplicate would make the pin meaningless and let dict order pick memberships."""
    art = {"clusters": [{"cluster_id": "c0", "idxs_base": [1]},
                        {"cluster_id": "c0", "idxs_base": [2]}]}
    with pytest.raises(ValueError, match="duplicate cluster_id"):
        rt.project_base_clusters(art)


def test_project_base_clusters_rejects_empty_membership():
    with pytest.raises(ValueError, match="empty idxs_base"):
        rt.project_base_clusters({"clusters": [{"cluster_id": "c0", "idxs_base": []}]})


def test_membership_pin_accepts_the_matching_hash():
    from calibration.adjudication_ab import members_sha

    clusters = [{"cluster_id": "c0", "idxs": [2, 1]}, {"cluster_id": "c1", "idxs": [3]}]
    got = rt.assert_membership_pin(clusters, {"members_sha": members_sha(clusters)})
    assert got == members_sha(clusters)


def test_membership_pin_rejects_a_mismatch():
    clusters = [{"cluster_id": "c0", "idxs": [1]}]
    with pytest.raises(SystemExit, match="T-R0 MEMBERSHIP MISMATCH"):
        rt.assert_membership_pin(clusters, {"members_sha": "deadbeefdeadbeef"})


def test_membership_pin_refuses_an_unpinnable_taxonomy():
    with pytest.raises(SystemExit, match="no members_sha"):
        rt.assert_membership_pin([{"cluster_id": "c", "idxs": [1]}], {})


def test_membership_pin_is_order_insensitive_within_a_cluster():
    """members_sha sorts each cluster's indices, so a membership list that differs only
    in order must still pin — otherwise the projection would have to preserve an ordering
    the artifact never promised."""
    from calibration.adjudication_ab import members_sha

    a = [{"cluster_id": "c0", "idxs": [1, 2, 3]}]
    b = [{"cluster_id": "c0", "idxs": [3, 1, 2]}]
    assert members_sha(a) == members_sha(b)


# --------------------------------------------------------------------------------------
# the arm switch — installed, proven, and never a silent mixture
# --------------------------------------------------------------------------------------

@pytest.fixture
def restore_tuning():
    from shared import tuning as tuning_mod
    before = tuning_mod._cached
    yield
    tuning_mod._cached = before


def test_install_scenario_vector_mode_changes_what_scenario_text_returns(restore_tuning):
    from shared.scenario_vectors import scenario_text

    info = {"business_description": "PROSE", "keyphrases": ["kp1", "kp2"]}
    assert rt.install_scenario_vector_mode("concat") == "concat"
    assert scenario_text(info) == "PROSE kp1 kp2"
    assert rt.install_scenario_vector_mode("keyphrases") == "keyphrases"
    assert scenario_text(info) == "kp1 kp2"


def test_install_scenario_vector_mode_rejects_an_unknown_register(restore_tuning):
    with pytest.raises(SystemExit, match="scenario_vector_mode"):
        rt.install_scenario_vector_mode("embeddings_but_vibes")


def test_install_is_visible_through_get_tuning(restore_tuning):
    """production `assign_scenarios` -> build_scenario_vecs -> _resolve_mode reads the
    SINGLETON, so that is the object the install has to move."""
    from shared import tuning as tuning_mod

    rt.install_scenario_vector_mode("keyphrases")
    assert tuning_mod.get_tuning().layer_a.scenario_vector_mode == "keyphrases"


def test_mode_fallback_counter_catches_a_half_concat_arm(restore_tuning):
    """A scenario with no keyphrases falls back to concat with a WARNING and nothing else
    would stop it — the arm would silently be a mixture."""
    from shared.scenario_vectors import scenario_text

    rt.install_scenario_vector_mode("keyphrases")
    counter = rt.ModeFallbackCounter().install()
    try:
        scenario_text({"business_description": "PROSE", "keyphrases": []})
        assert len(counter.records) == 1
        with pytest.raises(SystemExit, match="MIXTURE"):
            counter.assert_clean("keyphrases")
    finally:
        import logging
        logging.getLogger("shared.scenario_vectors").removeHandler(counter)


def test_mode_fallback_counter_is_quiet_on_a_clean_arm(restore_tuning):
    from shared.scenario_vectors import scenario_text

    rt.install_scenario_vector_mode("keyphrases")
    counter = rt.ModeFallbackCounter().install()
    try:
        scenario_text({"business_description": "PROSE", "keyphrases": ["kp"]})
        assert counter.records == []
        counter.assert_clean("keyphrases")          # must not raise
    finally:
        import logging
        logging.getLogger("shared.scenario_vectors").removeHandler(counter)


def test_taxonomy_identity_sha_is_mode_invariant(restore_tuning):
    """The cross-arm identity check MUST NOT be register-dependent, or it rejects the
    keyphrases arm for being the keyphrases arm — which is exactly what happened with
    `layer_bc_arms.taxonomy_sha`, whose hash runs through `scenario_text`."""
    from calibration.layer_bc_arms import taxonomy_sha

    sm = {"a": {"is_coachable": True, "business_description": "PROSE A",
                "keyphrases": ["k1", "k2"]},
          "b": {"is_coachable": False, "business_description": "PROSE B",
                "keyphrases": ["k3"]}}
    rt.install_scenario_vector_mode("concat")
    inv_concat, dep_concat = rt.taxonomy_identity_sha(sm), taxonomy_sha(sm)
    rt.install_scenario_vector_mode("keyphrases")
    inv_kp, dep_kp = rt.taxonomy_identity_sha(sm), taxonomy_sha(sm)

    assert inv_concat == inv_kp, "the invariant hash moved with the register"
    assert dep_concat != dep_kp, (
        "the register-dependent hash did NOT move — it would be useless as a positive "
        "check that the treatment applied")


def test_taxonomy_identity_sha_still_notices_a_real_taxonomy_change():
    base = {"a": {"is_coachable": True, "business_description": "P",
                  "keyphrases": ["k1"]}}
    for field, changed in (("business_description", "DIFFERENT"),
                           ("keyphrases", ["k1", "k2"]),
                           ("is_coachable", False)):
        other = {"a": {**base["a"], field: changed}}
        assert rt.taxonomy_identity_sha(other) != rt.taxonomy_identity_sha(base), field
    assert rt.taxonomy_identity_sha({"z": base["a"]}) != rt.taxonomy_identity_sha(base)


def test_every_arm_maps_to_a_register_and_a_router():
    assert set(rt.ARMS) == set(rt.ARM_MODE) == set(rt.ARM_ROUTER)
    assert rt.ARM_MODE["r1"] == "concat", "r1's description FALLBACK is the control register"
    assert rt.ARM_ROUTER["concat"] == rt.ARM_ROUTER["keyphrases"] == "r0"


# --------------------------------------------------------------------------------------
# G-D — the pre-spend divergence gate
# --------------------------------------------------------------------------------------

def _ps(scenario: str, ids: list[str], routed: list[str] | None = None) -> dict:
    return {scenario: {"selected": [{"call": i.split(":")[0],
                                     "turn_index": int(i.split(":")[1])} for i in ids],
                       **({"routed_pair_ids": routed} if routed is not None else {})}}


def test_selected_ids_is_the_pair_id_form():
    assert rt.selected_ids(_ps("s", ["callA:3", "callB:7"]), "s") == {"callA:3", "callB:7"}


def test_divergence_row_counts_only_what_the_arm_added():
    ctrl = _ps("s", ["a:1", "a:2", "a:3", "a:4"])
    arm = _ps("s", ["a:3", "a:4", "b:5", "b:6"])
    r = rt.divergence_row(ctrl, arm, "s")
    assert r["changed"] == 2 and r["shared"] == 2
    assert r["jaccard_selected"] == pytest.approx(2 / 6)


def test_divergence_row_identical_selection_is_zero_divergence():
    ctrl = arm = _ps("s", ["a:1", "a:2"])
    r = rt.divergence_row(ctrl, arm, "s")
    assert r["changed"] == 0 and r["jaccard_selected"] == 1.0


def _row(scenario: str, changed: int, n: int = 50, n_control: int | None = None) -> dict:
    return {"scenario": scenario, "changed": changed, "n_arm": n,
            "n_control": n if n_control is None else n_control}


def test_gd_passes_at_exactly_the_bar():
    rows = [_row(f"s{i}", rt.GD_CHANGED_MIN) for i in range(3)]
    rows += [_row("s3", 0), _row("s4", 9)]
    v = rt.gd_verdict(rows)
    assert v["pass"] is True and v["n_qualifying"] == 3


def test_gd_fails_one_scenario_short():
    rows = [_row(f"s{i}", rt.GD_CHANGED_MIN) for i in range(2)]
    rows += [_row(f"s{i}", rt.GD_CHANGED_MIN - 1) for i in range(2, 5)]
    v = rt.gd_verdict(rows)
    assert v["pass"] is False and v["n_qualifying"] == 2


def test_gd_fails_when_an_arm_barely_moves_anything():
    v = rt.gd_verdict([_row(f"s{i}", 1) for i in range(5)])
    assert v["pass"] is False, "a near-identical arm must be a null BY CONSTRUCTION"


def test_gd_refuses_to_qualify_a_scenario_whose_volume_collapsed():
    """`changed` is an absolute count, so a thinner selection clears the bar MORE easily —
    while introducing a volume confound the read would credit to routing."""
    rows = [_row(f"s{i}", 12, n=12, n_control=50) for i in range(5)]
    v = rt.gd_verdict(rows)
    assert v["pass"] is False and v["n_qualifying"] == 0
    assert len(v["volume_mismatched"]) == 5


def test_divergence_row_reports_routed_jaccard_when_the_sets_are_persisted():
    ctrl = _ps("s", ["a:1", "a:2"], routed=["a:1", "a:2", "a:3", "a:4"])
    arm = _ps("s", ["a:1", "b:9"], routed=["a:1", "a:2", "b:9"])
    r = rt.divergence_row(ctrl, arm, "s")
    assert r["n_routed_control"] == 4 and r["n_routed_arm"] == 3
    assert r["jaccard_routed"] == pytest.approx(2 / 5)


def test_divergence_row_reports_none_rather_than_faking_routed_identity():
    """An older artifact without the routed sets must read as 'unknown', never as
    'identical' — the latter would look like proof that routing is inert."""
    r = rt.divergence_row(_ps("s", ["a:1"]), _ps("s", ["a:2"]), "s")
    assert r["jaccard_routed"] is None


def test_gd_bars_are_the_frozen_ones():
    assert (rt.GD_CHANGED_MIN, rt.GD_SCENARIOS_MIN) == (10, 3)


# --------------------------------------------------------------------------------------
# counterbalancing — both dimensions
# --------------------------------------------------------------------------------------

def test_treatment_side_alternates_across_pilot_positions():
    sides = [rt.treatment_side(i, 0) for i in range(5)]
    assert sides == ["A", "B", "A", "B", "A"]


def test_the_control_does_not_sit_on_one_side_across_the_two_comparisons():
    """A reader in comparison 2 must not find the control where comparison 1 put it —
    and neither packet may be all-one-side for the treatment."""
    for i in range(5):
        assert rt.treatment_side(i, 0) != rt.treatment_side(i, 1)
    for ci in (0, 1):
        sides = {rt.treatment_side(i, ci) for i in range(5)}
        assert sides == {"A", "B"}


def test_treatment_side_is_deterministic():
    assert all(rt.treatment_side(i, c) == rt.treatment_side(i, c)
               for i in range(5) for c in (0, 1))


def test_every_comparison_has_a_counterbalancing_offset():
    assert set(rt.COMPARISONS) == set(rt.COMPARISON_INDEX)


# --------------------------------------------------------------------------------------
# packet composition
# --------------------------------------------------------------------------------------

PILOT = ["s1", "s2", "s3", "s4", "s5"]


def test_packet_has_the_frozen_composition():
    items = rt.build_packet_items(PILOT, "keyphrases", rt.packet_rng("keyphrases"))
    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    assert kinds == {"ROUTE": 5, "CAL": 4, "NEG": rt.N_NEG}
    assert len(items) == 14


def test_packet_order_is_seeded_and_reproducible():
    a = rt.build_packet_items(PILOT, "keyphrases", rt.packet_rng("keyphrases"))
    b = rt.build_packet_items(PILOT, "keyphrases", rt.packet_rng("keyphrases"))
    assert a == b


def test_a_side_biased_reader_CANNOT_pass_g_p():
    """THE REGRESSION TEST FOR THE AUDIT'S FATAL FINDING, stated as the property that
    matters rather than as a side pattern.

    G-P is the gate that makes a null believable. If a reader that answers by POSITION
    alone can clear it, the gate certifies nothing. The first fix (3 pairs at A/B/A) still
    handed such a reader 2 of 3 — exactly the bar — which an earlier version of this test
    missed because it contained an escape clause. Four pairs at A/B/A/B hand it 2 of 4,
    below a bar of 3, so no side pattern can pass.
    """
    for comparison in rt.COMPARISONS:
        items = rt.build_packet_items(PILOT, comparison, rt.packet_rng(comparison))
        cal = [it["real_side"] for it in items if it["kind"] == "CAL"]
        assert len(cal) == len(rt.CAL_SCENARIOS)
        for bias in ("A", "B"):
            hits = sum(1 for s in cal if s == bias)
            assert hits < rt.CAL_PASS_MIN, (
                f"{comparison}: an always-{bias} reader scores G-P {hits}/{len(cal)} "
                f"against a bar of {rt.CAL_PASS_MIN} — G-P is position-satisfiable")


def test_calibration_sides_are_alternating_and_deterministic():
    for comparison in rt.COMPARISONS:
        items = rt.build_packet_items(PILOT, comparison, rt.packet_rng(comparison))
        by_scen = {it["scenario"]: it["real_side"]
                   for it in items if it["kind"] == "CAL"}
        assert [by_scen[s] for s in rt.CAL_SCENARIOS] == ["A", "B", "A", "B"]


def test_calibration_scenarios_never_overlap_the_routing_scenarios():
    """The DIRECTIONAL half of the FATAL finding: a calibration pair that reuses a pilot
    scenario shows the reader a genuine CONTROL-derived document for that scenario, and
    familiarity then anchors the routing item toward the control — a gate that
    manufactures nulls."""
    ev = json.loads(rt.PBV_EVIDENCE.read_text(encoding="utf-8-sig"))
    assert not (set(rt.CAL_SCENARIOS) & set(ev["pilot"]))
    # and not merely a different key for the same subject
    assert not any("ats" in s for s in rt.CAL_SCENARIOS), (
        "the pilot contains an ATS scenario; a same-subject calibration pair anchors it")


def test_calibration_pairs_come_from_a_published_validated_source():
    """A powered-ness control is only meaningful if the difference it tests is KNOWN. The
    snap trial measured these pairs at PB2 5/5, pooled 14-1."""
    assert rt.PBS_SNAPPED.name == "pbs_playbooks.json"
    docs = json.loads(rt.PBS_SNAPPED.read_text(encoding="utf-8-sig"))["documents"]
    for s in rt.CAL_SCENARIOS:
        assert f"{s}::real" in docs and f"{s}::placebo" in docs
        assert not docs[f"{s}::real"]["snap_log"]["schema_collapsed"]
        assert not docs[f"{s}::placebo"]["snap_log"]["schema_collapsed"]


def test_each_comparison_gets_its_own_shuffle_stream():
    """One shared Random(SEED) gave all three packets an identical layout, putting the G-P
    items at the freshest positions and the decisive ROUTE items at the most fatigued ones
    in every packet."""
    layouts = {c: [it["kind"] for it in rt.build_packet_items(PILOT, c, rt.packet_rng(c))]
               for c in rt.COMPARISONS}
    assert len(set(map(tuple, layouts.values()))) == len(layouts)


def test_neg_headers_never_name_a_pilot_scenario():
    """A negative is built from moves lifted verbatim out of the displayed documents, so a
    negative headed by its own source scenario can honestly read as YES — which would
    invalidate the CAREFUL readers and retain the careless ones."""
    ranking = {s: 100 - i for i, s in enumerate(PILOT)}
    ranking.update({f"other{i}": 50 - i for i in range(6)})
    got = rt.neg_headers(ranking, PILOT)
    assert len(got) == rt.N_NEG
    assert not (set(got) & set(PILOT))
    assert got == ["other0", "other1", "other2", "other3", "other4"]


def test_neg_headers_refuse_to_run_short():
    ranking = {s: 1 for s in PILOT}
    ranking.update({"other0": 1, "other1": 1})
    with pytest.raises(SystemExit, match="non-pilot"):
        rt.neg_headers(ranking, PILOT)


def test_every_route_item_carries_both_arms_and_a_side():
    import random
    items = rt.build_packet_items(PILOT, "r1", random.Random(rt.SEED))
    route = [it for it in items if it["kind"] == "ROUTE"]
    assert {it["treat_arm"] for it in route} == {"r1"}
    assert {it["base_arm"] for it in route} == {rt.CONTROL}
    assert all(it["treat_side"] in ("A", "B") for it in route)


# --------------------------------------------------------------------------------------
# the head-to-head scorer
# --------------------------------------------------------------------------------------

N_CAL = len(rt.CAL_SCENARIOS)


def _key(treat_pref: int, cal_pref: int = N_CAL, n_moves: int = 2) -> dict:
    """A 14-item key: 5 ROUTE, 4 CAL, 5 NEG, with the treatment on A throughout for
    readability of the fixtures (the real packet counterbalances). CAL scenarios are named
    `c<i>` so a fixture can never accidentally reuse a ROUTE scenario — the very overlap
    the FATAL finding was about."""
    items = []
    for i in range(5):
        items.append({"item": i + 1, "kind": "ROUTE", "scenario": f"s{i}",
                      "treat_arm": "r1", "base_arm": "concat", "treat_side": "A",
                      "n_moves_treat": n_moves, "n_moves_base": n_moves})
    for i in range(N_CAL):
        items.append({"item": 6 + i, "kind": "CAL", "scenario": f"c{i}",
                      "real_side": "A", "n_moves_real": n_moves})
    for i in range(rt.N_NEG):
        items.append({"item": 6 + N_CAL + i, "kind": "NEG", "header_scenario": "n0"})
    return {"items": items, "_treat_pref": treat_pref, "_cal_pref": cal_pref}


def _judgment(name: str, key: dict, treat_pref: int, cal_pref: int,
              applies: str = "APPLY", neg_reject: int = 5, salt: int = 0) -> dict:
    """A synthetic reader. `salt` pads `apply_B` on the ROUTE items ONLY.

    The scorer reads `apply_<treat_side>` — side A in every fixture here — and CAL items
    are scored on `choice` alone, so padding apply_B cannot move any tally, any validity
    verdict, or any apply share. It exists solely to make two readers who VOTE the same
    way carry distinct payloads, because the duplicate-payload guard fires before scoring
    and would otherwise mask the behaviour under test.
    """
    items = {}
    for row in key["items"]:
        i = str(row["item"])
        if row["kind"] == "ROUTE":
            idx = int(row["scenario"][1:])
            pick = "A" if idx < treat_pref else "B"
            items[i] = {"choice": pick,
                        "apply_A": [applies] * row["n_moves_treat"],
                        "apply_B": ["VAGUE"] * (row["n_moves_base"] + salt)}
        elif row["kind"] == "CAL":
            idx = int(row["scenario"][1:])
            items[i] = {"choice": "A" if idx < cal_pref else "B",
                        "apply_A": [applies] * row["n_moves_real"],
                        "apply_B": ["VAGUE"] * row["n_moves_real"]}
        else:
            n = int(i) - (6 + N_CAL)
            items[i] = {"answer": "NO" if n < neg_reject else "YES"}
    return {"reader": name, "items": items}


def _three(key: dict, **kw) -> list[dict]:
    """Three readers voting identically but with distinct payloads (see `salt`)."""
    return [_judgment(f"r{n}", key, salt=n, **kw) for n in range(3)]


def test_win_at_exactly_four_of_five():
    key = _key(4)
    res = rt.score_headtohead(key, _three(key, treat_pref=4, cal_pref=3))
    assert res["g_p"]["pass"] is True
    assert res["g_w"]["scenarios_treatment_preferred"] == 4
    assert res["won"] is True and res["verdict"] == "TREATMENT WINS"


def test_no_win_at_three_of_five():
    key = _key(3)
    res = rt.score_headtohead(key, _three(key, treat_pref=3, cal_pref=3))
    assert res["g_w"]["scenarios_treatment_preferred"] == 3
    assert res["won"] is False and "NO WIN" in res["verdict"]


def test_per_scenario_preference_needs_two_of_three_readers():
    key = _key(5)
    jds = [_judgment("r0", key, treat_pref=5, cal_pref=3, salt=0),
           _judgment("r1", key, treat_pref=0, cal_pref=3, salt=1),
           _judgment("r2", key, treat_pref=0, cal_pref=3, salt=2)]
    res = rt.score_headtohead(key, jds)
    assert res["g_w"]["scenarios_treatment_preferred"] == 0, (
        "one enthusiastic reader out of three must never carry a scenario")
    assert res["g_w"]["pooled_votes"]["treatment"] == 5
    assert res["g_w"]["pooled_votes"]["base"] == 10


def test_g_p_failure_VOIDS_the_read_rather_than_reporting_a_null():
    """The guard that makes a null believable: a pool that cannot prefer the real
    document over its placebo has not been shown to discriminate at all."""
    key = _key(0)
    res = rt.score_headtohead(key, _three(key, treat_pref=0, cal_pref=0))
    assert res["verdict"] == "VOID" and res["won"] is False
    assert "G-P" in res["reason"]
    assert res["g_p"]["n_real_preferred"] == 0


def test_g_p_failure_voids_even_when_the_treatment_would_have_won():
    """The dangerous direction: a blind pool that happened to favour the treatment must
    not be allowed to declare a WIN either."""
    key = _key(5)
    res = rt.score_headtohead(key, _three(key, treat_pref=5, cal_pref=0))
    assert res["g_w"]["scenarios_treatment_preferred"] == 5
    assert res["verdict"] == "VOID" and res["won"] is False


def test_g_p_passes_at_exactly_the_bar():
    key = _key(5)
    res = rt.score_headtohead(key, _three(key, treat_pref=5, cal_pref=rt.CAL_PASS_MIN))
    assert res["g_p"]["n_real_preferred"] == rt.CAL_PASS_MIN
    assert res["g_p"]["pass"] is True
    assert res["verdict"] == "TREATMENT WINS"


def test_g_p_fails_one_calibration_pair_short():
    key = _key(5)
    res = rt.score_headtohead(key, _three(key, treat_pref=5,
                                          cal_pref=rt.CAL_PASS_MIN - 1))
    assert res["g_p"]["pass"] is False
    assert res["verdict"] == "VOID" and res["won"] is False


def test_g_v_voids_when_a_reader_fails_the_negatives():
    key = _key(5)
    res = rt.score_headtohead(key, _three(key, treat_pref=5, cal_pref=3, neg_reject=1))
    assert res["verdict"] == "VOID" and "G-V" in res["reason"]


def test_g_v_voids_on_an_unanswered_item():
    key = _key(5)
    jds = _three(key, treat_pref=5, cal_pref=3)
    for jd in jds:
        jd["items"].pop("1")
    res = rt.score_headtohead(key, jds)
    assert res["verdict"] == "VOID" and "G-V" in res["reason"]


def test_duplicate_reader_identity_raises():
    key = _key(5)
    jds = [_judgment("same", key, 5, 3, salt=0), _judgment("same", key, 5, 3, salt=1),
           _judgment("other", key, 5, 3, salt=2)]
    with pytest.raises(ValueError, match="duplicate reader identity"):
        rt.score_headtohead(key, jds)


def test_duplicate_payload_raises_even_under_distinct_names():
    key = _key(5)
    jds = [_judgment(f"r{n}", key, 5, 3) for n in range(3)]     # no salt -> identical
    with pytest.raises(ValueError, match="byte-identical answers"):
        rt.score_headtohead(key, jds)


def test_apply_share_counts_a_move_only_at_two_of_three_readers():
    key = _key(5, n_moves=2)
    jds = [_judgment("r0", key, 5, 3, applies="APPLY", salt=0),
           _judgment("r1", key, 5, 3, applies="APPLY", salt=1),
           _judgment("r2", key, 5, 3, applies="VAGUE", salt=2)]
    assert rt.score_headtohead(key, jds)["apply_share"]["median"] == 1.0
    jds2 = [_judgment("r0", key, 5, 3, applies="APPLY", salt=0),
            _judgment("r1", key, 5, 3, applies="VAGUE", salt=1),
            _judgment("r2", key, 5, 3, applies="VAGUE", salt=2)]
    assert rt.score_headtohead(key, jds2)["apply_share"]["median"] == 0.0


def test_missing_apply_list_reads_as_vague_not_as_a_crash():
    key = _key(5, n_moves=3)
    jds = _three(key, treat_pref=5, cal_pref=3)
    for jd in jds:
        jd["items"]["1"]["apply_A"] = ["APPLY"]          # short list, 1 of 3 moves rated
    res = rt.score_headtohead(key, jds)
    assert res["apply_share"]["per_scenario"]["s0"] == pytest.approx(1 / 3)


# --------------------------------------------------------------------------------------
# jobs and the cross-arm budget ledger
# --------------------------------------------------------------------------------------

def test_doc_jobs_are_five_real_documents_in_pilot_order():
    ev = {"pilot": PILOT,
          "per_scenario": {s: {"selected": [{"call": "c", "turn_index": 1}]}
                           for s in PILOT}}
    jobs = rt.rt_doc_jobs(ev)
    assert [j["doc_id"] for j in jobs] == [f"{s}::real" for s in PILOT]
    assert all("placebo" not in j["doc_id"] for j in jobs)


def test_spend_is_summed_across_arms_so_a_new_process_cannot_reset_it(monkeypatch,
                                                                     tmp_path):
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "rt_playbooks_concat.json").write_text(
        json.dumps({"calls_used": 17, "documents": {}}), encoding="utf-8")
    (tmp_path / "rt_playbooks_keyphrases.json").write_text(
        json.dumps({"calls_used": 20, "documents": {}}), encoding="utf-8")
    assert rt.spend_so_far() == 37
    assert rt.spend_so_far(exclude_arm="keyphrases") == 17
    assert rt.spend_so_far(exclude_arm="r1") == 37


def test_budget_ceiling_is_the_frozen_total():
    assert rt.RT_BUDGET == 70


# --------------------------------------------------------------------------------------
# gate ENFORCEMENT — the guards must refuse, not merely print
# --------------------------------------------------------------------------------------

def _stage_fixture(monkeypatch, tmp_path, cleared: list[str]) -> None:
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(rt, "DIVERGENCE", tmp_path / "rt_divergence.json")
    (tmp_path / "rt_divergence.json").write_text(
        json.dumps({"arms_cleared_to_spend": cleared}), encoding="utf-8")
    for arm in rt.ARMS:
        (tmp_path / f"rt_evidence_{arm}.json").write_text(
            json.dumps({"pilot": PILOT, "identity": {},
                        "per_scenario": {s: {"selected": []} for s in PILOT}}),
            encoding="utf-8")


def test_no_arm_cleared_g_d_cancels_the_CONTROL_spend_too(monkeypatch, tmp_path):
    """Spec §5 cancels the ENTIRE spend at ZERO chat cost when both treatments fail G-D.
    The control's documents would have nothing to be compared against."""
    _stage_fixture(monkeypatch, tmp_path, cleared=[])
    with pytest.raises(SystemExit, match="ENTIRE chat spend is cancelled"):
        rt.stage_synthesize(rt.CONTROL)


def test_an_arm_that_failed_g_d_cannot_spend(monkeypatch, tmp_path):
    _stage_fixture(monkeypatch, tmp_path, cleared=["keyphrases"])
    with pytest.raises(SystemExit, match="did NOT clear G-D"):
        rt.stage_synthesize("r1")


def test_synthesis_refuses_without_a_divergence_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(rt, "DIVERGENCE", tmp_path / "rt_divergence.json")
    (tmp_path / "rt_evidence_concat.json").write_text(
        json.dumps({"pilot": PILOT, "identity": {}, "per_scenario": {}}),
        encoding="utf-8")
    with pytest.raises(SystemExit, match="run --divergence first"):
        rt.stage_synthesize(rt.CONTROL)


def test_clobber_guard_refuses_an_existing_artifact(monkeypatch, tmp_path):
    p = tmp_path / "rt_thing.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to clobber"):
        rt._no_clobber(p)
    rt._no_clobber(tmp_path / "rt_absent.json")          # must not raise


def test_one_stage_per_process_is_enforced(monkeypatch):
    """The keyphrases arm mutates a process-wide singleton, so two stages in one process
    could route one arm with another's register."""
    monkeypatch.setattr(sys, "argv", ["x", "--select", "--arm", "concat", "--snap"])
    with pytest.raises(SystemExit, match="exactly one stage per process"):
        rt.main()


def test_unknown_arm_and_comparison_are_refused(monkeypatch):
    with pytest.raises(SystemExit, match="--arm must be one of"):
        rt._check_arm("centroid_pooled")
    with pytest.raises(SystemExit, match="--comparison must be one of"):
        rt._check_comparison("r2_vs_r3")


def test_model_pin_is_the_frozen_configuration():
    """`high` is unreachable through the gateway (LiteLLM's 120s cap); `low` is the
    measured-working effort and must not drift."""
    assert rt.RT_CHAT_MODEL == "gemini-3.5-flash"
    assert rt.RT_REASONING == "low"
    assert rt.RT_MAX_TOKENS == 65536


def test_win_bars_are_the_frozen_ones():
    assert (rt.WIN_SCENARIOS, rt.PHASE2_WIN) == (4, 3)
    # G-P: 3 of 4, the bar a purely position-answering reader (2 of 4) cannot reach.
    assert (rt.CAL_PASS_MIN, len(rt.CAL_SCENARIOS)) == (3, 4)
    assert rt.CAL_PASS_MIN > len(rt.CAL_SCENARIOS) // 2, (
        "the G-P bar must exceed what alternating sides hand a side-biased reader")


# --------------------------------------------------------------------------------------
# artifact isolation — no published artifact may be written
# --------------------------------------------------------------------------------------

def test_every_written_artifact_carries_the_rt_prefix():
    written = [rt.route_art("concat"), rt.evidence_art("concat"),
               rt.playbooks_art("r1"), rt.snapped_art("r1"), rt.pb0_art("keyphrases"),
               rt.packet_art("keyphrases"), rt.key_art("r1"), rt.report_art("r1"),
               rt.DIVERGENCE]
    for p in written:
        assert p.name.startswith("rt_"), p.name


def test_published_inputs_are_the_frozen_read_only_ones():
    assert rt.PBV_EVIDENCE.name == "pbv_evidence.json"
    assert rt.PBS_SNAPPED.name == "pbs_playbooks.json"
    assert rt.UNION_CLUSTERS.name == "union_clusters.json"


def test_a_redispatched_round_is_a_disjoint_namespace():
    """A VOID packet is re-dispatched to fresh readers (spec §7.4). Without a round scope
    the scorer keeps the first 3 valid files in FILENAME order, so round 2's readers are
    never reached and the run records a second VOID that the replacement pool never cast —
    or, if the fresh files sort earlier, a verdict mixed from two dispatches."""
    import fnmatch
    r1 = "rt_keyphrases_judgments_r1.json"
    r2 = "rt_keyphrases_round2_judgments_r4.json"
    assert fnmatch.fnmatch(r1, rt.judgments_glob("keyphrases"))
    assert not fnmatch.fnmatch(r2, rt.judgments_glob("keyphrases"))
    assert fnmatch.fnmatch(r2, rt.judgments_glob("keyphrases", 2))
    assert not fnmatch.fnmatch(r1, rt.judgments_glob("keyphrases", 2))


def test_round_one_must_not_be_scoped():
    with pytest.raises(SystemExit, match="round 1 is the unscoped default"):
        rt.judgments_glob("r1", 1)


def test_score_refuses_a_mixed_namespace(monkeypatch, tmp_path):
    """More judgment files than a round holds means two dispatches are mixed; truncating to
    the first three silently re-scores a discarded round."""
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    key = _key(5)
    (tmp_path / "rt_r1_read_KEY.json").write_text(json.dumps(key), encoding="utf-8")
    for n in range(1, 7):
        (tmp_path / f"rt_r1_judgments_r{n}.json").write_text(
            json.dumps(_judgment(f"r{n}", key, 5, 4, salt=n)), encoding="utf-8")
    with pytest.raises(SystemExit, match="mixed in one namespace"):
        rt.stage_score("r1")


def test_calibration_channels_surface_the_move_count_route_to_a_g_p_pass():
    """G-P is bias-proof against SIDE patterns but the frozen pairs carry a key-move-count
    channel: a reader preferring the longer document, without reading it, can reach the
    bar. It cannot be engineered away without readmitting the excluded ATS pair, so it must
    be visible in the report."""
    key = {"items": [
        {"kind": "CAL", "scenario": "c0", "real_side": "A",
         "n_moves_real": 4, "n_moves_placebo": 3},
        {"kind": "CAL", "scenario": "c1", "real_side": "B",
         "n_moves_real": 4, "n_moves_placebo": 4},
        {"kind": "ROUTE", "scenario": "s0", "treat_side": "A", "n_moves_treat": 3},
    ]}
    ch = rt.cal_channels(key)
    assert [p["move_count_favours_real"] for p in ch["per_pair"]] == [True, False]
    assert len(ch["per_pair"]) == 2, "ROUTE items are not calibration pairs"


def test_the_real_calibration_pairs_move_counts_are_recorded_as_measured():
    """Pins the actual on-disk numbers the residual is stated against, so a future edit to
    CAL_SCENARIOS cannot silently change how exploitable G-P is."""
    docs = json.loads(rt.PBS_SNAPPED.read_text(encoding="utf-8-sig"))["documents"]
    separable = sum(1 for s in rt.CAL_SCENARIOS
                    if len(docs[f"{s}::real"]["playbook"]["key_moves"])
                    != len(docs[f"{s}::placebo"]["playbook"]["key_moves"]))
    assert separable == 2, (
        f"{separable} of {len(rt.CAL_SCENARIOS)} calibration pairs are separable by move "
        f"count; spec §11's stated residual assumes 2 — re-derive it before running")


def test_empty_pool_disqualifies_its_arm_without_blocking_the_trial(monkeypatch, tmp_path):
    """MEASURED on the keyphrases arm: it routes ZERO pairs to the map's largest scenario.
    Aborting at select time left its artifacts unwritten, so `--divergence` (which needs all
    three arms) could never run and the r1 comparison was blocked by an unrelated arm's
    collapse. The arm must be disqualified, not the trial."""
    _stage_fixture(monkeypatch, tmp_path, cleared=["r1"])
    p = tmp_path / "rt_evidence_keyphrases.json"
    ev = json.loads(p.read_text(encoding="utf-8-sig"))
    ev["empty_pools"] = ["application_volume_and_prioritization"]
    p.write_text(json.dumps(ev), encoding="utf-8")
    with pytest.raises(SystemExit, match="routes ZERO pairs"):
        rt.stage_synthesize("keyphrases")
    assert not (tmp_path / "rt_playbooks_keyphrases.json").exists()


def test_divergence_record_never_clears_a_disqualified_arm(monkeypatch, tmp_path):
    """MEASURED: keyphrases passes G-D 3/5 on its surviving scenarios while being unusable.
    stage_synthesize refuses it either way, but `arms_cleared_to_spend` is the RECORD and must
    not name a disqualified arm — a later reader would conclude the arm was viable."""
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(rt, "DIVERGENCE", tmp_path / "rt_divergence.json")

    def ev(extra=None, changed_from=0):
        per = {}
        for i, s in enumerate(PILOT):
            # give every scenario a fully disjoint 50-pair selection so G-D passes 5/5
            ids = [{"call": f"c{i}_{j + changed_from}", "turn_index": j} for j in range(50)]
            per[s] = {"selected": ids, "routed_pair_ids": []}
        return {"pilot": PILOT, "ranking": {s: 100 for s in PILOT}, "per_scenario": per,
                "identity": {"corpus_sha": "x", "taxonomy_sha": "t",
                             "taxonomy_sha_invariant": "inv",
                             "scenario_vector_mode": "concat"},
                **(extra or {})}

    (tmp_path / "rt_evidence_concat.json").write_text(json.dumps(ev()), encoding="utf-8")
    (tmp_path / "rt_evidence_r1.json").write_text(
        json.dumps(ev(changed_from=500)), encoding="utf-8")
    (tmp_path / "rt_evidence_keyphrases.json").write_text(
        json.dumps(ev({"empty_pools": ["s1"],
                       "volume_shortfall": {"s1": 0}}, changed_from=900)),
        encoding="utf-8")

    rt.stage_divergence()
    out = json.loads((tmp_path / "rt_divergence.json").read_text(encoding="utf-8"))
    assert out["arms"]["keyphrases"]["pass"] is True, "G-D itself should still report PASS"
    assert "keyphrases" not in out["arms_cleared_to_spend"], "a disqualified arm was cleared"
    assert "r1" in out["arms_cleared_to_spend"]
    assert out["disqualified_arms"]["keyphrases"]["empty_pools"] == ["s1"]


def test_an_empty_pool_scenario_can_never_qualify_under_g_d():
    """n_arm=0 vs n_control=50 is a volume mismatch, so the existing second net disqualifies
    it — a scenario with no evidence must not be able to clear the divergence bar on the
    strength of having changed 'everything'."""
    rows = [_row("s0", 0, n=0, n_control=50)]
    rows += [_row(f"s{i}", rt.GD_CHANGED_MIN) for i in range(1, 5)]
    v = rt.gd_verdict(rows)
    assert "s0" not in v["qualifying"]
    assert "s0" in v["volume_mismatched"]


def test_volume_shortfall_blocks_only_its_own_arm(monkeypatch, tmp_path):
    """Raising at select time left the arm's artifacts unwritten, so --divergence could
    never run and an unrelated comparison was blocked by this arm's collapse."""
    _stage_fixture(monkeypatch, tmp_path, cleared=["r1", "keyphrases"])
    p = tmp_path / "rt_evidence_r1.json"
    ev = json.loads(p.read_text(encoding="utf-8-sig"))
    ev["volume_shortfall"] = {"niche_talent": 44}
    p.write_text(json.dumps(ev), encoding="utf-8")
    with pytest.raises(SystemExit, match="VOLUME SHORTFALL"):
        rt.stage_synthesize("r1")
    # The unaffected arm is NOT blocked by r1's shortfall. It still fails — the fixture's
    # scenarios are synthetic, so it cannot build a real prompt — but reaching the synthesis
    # loop at all proves it passed both the G-D and volume gates, which is the property under
    # test. No chat call can have been made: the failure precedes the first `call()`.
    with pytest.raises(Exception) as exc:
        rt.stage_synthesize("keyphrases")
    assert "VOLUME SHORTFALL" not in str(exc.value)
    # Nothing was persisted, and the count is persisted BEFORE any POST — so no chat
    # attempt was made on either arm.
    assert not (tmp_path / "rt_playbooks_keyphrases.json").exists()
    assert not (tmp_path / "rt_playbooks_r1.json").exists()


def test_judgment_globs_do_not_collide_across_comparisons():
    globs = {rt.judgments_glob(c) for c in rt.COMPARISONS}
    assert len(globs) == len(rt.COMPARISONS)
    # and none of them can pick up a previous trial's judgments
    for g in globs:
        assert g.startswith("rt_") and not g.startswith("rt_judgments")


def test_route_packet_header_keeps_the_frozen_answer_format():
    """The framing had to change (both routing documents are genuine), but the answer
    format and the SINGLE-item wording are what `reader_valid` and the judgment schema
    depend on, so those stay byte-identical to the pilot's."""
    from calibration.scenario_playbook_trial import PACKET_HEADER

    ours = "\n".join(rt.ROUTE_PACKET_HEADER)
    theirs = "\n".join(PACKET_HEADER)
    for frozen in ('"apply_A" / "apply_B": one rating per KEY MOVE, in display order',
                   'SINGLE items show one document and name a scenario. Answer:',
                   '"answer": "YES" if it is one coherent, usable coaching document'):
        assert frozen in ours and frozen in theirs
    assert "genuine playbook synthesized from" not in ours, (
        "on a routing item BOTH documents are genuine; telling the reader to hunt for a "
        "fake would answer a different question")
