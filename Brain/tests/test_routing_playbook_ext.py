"""Tests for calibration/routing_playbook_ext.py (extension E1).

Spec: docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md §14 (frozen).

Document production, snap, PB0 and the reader-validity bar are imported unchanged from the
original harness and are covered by test_routing_playbook_ab.py. What is NEW and pinned
here: the frozen pick rule and its drift check, the packet split, counterbalancing across
two packets, the pooled sign test as PRIMARY, the reader-correlation report, and the
protection of the original result.
"""
import json

import pytest

from calibration import routing_playbook_ab as rt
from calibration import routing_playbook_ext as ext

PILOT = ["p0", "p1", "p2", "p3", "p4"]


# --------------------------------------------------------------------------------------
# the frozen pick rule
# --------------------------------------------------------------------------------------

def test_pick_rule_reproduces_the_frozen_topics_on_the_real_artifacts():
    """The 6 topics are hardcoded so the spec can name them, but a hardcoded list is a CLAIM
    about data. Re-derive it from the actual routing artifacts."""
    c = json.loads(rt.evidence_art("concat").read_text(encoding="utf-8-sig"))
    r = json.loads(rt.evidence_art("r1").read_text(encoding="utf-8-sig"))
    got = ext.verify_pick_rule(c["ranking"], r["ranking"], c["pilot"])
    assert tuple(got) == ext.EXT_SCENARIOS
    assert len(set(got)) == 6
    assert not (set(got) & set(c["pilot"])), "a new topic duplicates an original one"


def test_pick_rule_raises_on_drift():
    ranking_c = {f"s{i}": 1000 - i for i in range(40)}
    ranking_r = dict(ranking_c)
    with pytest.raises(SystemExit, match="PICK-RULE DRIFT"):
        ext.verify_pick_rule(ranking_c, ranking_r, [])


def test_pick_rule_r1_floor_actually_excludes(monkeypatch):
    """THE r1 HALF OF THE FLOOR IS THE ONE CLAUSE THAT COULD TILT SELECTION, so it is tested
    through `verify_pick_rule` itself. An earlier version of this test re-implemented the
    filter inline and asserted on its own reimplementation — deleting the r1 clause from the
    module left it green."""
    # 20 topics, all fat under control; the topic at eligible rank 1 is thin under r1 only.
    ranking_c = {f"s{i:02d}": 1000 - i for i in range(20)}
    ranking_r = {k: 500 for k in ranking_c}
    ranking_r["s00"] = ext.EXT_ROUTED_FLOOR - 1
    # With the r1 floor honoured, rank 1 is s01; without it, s00.
    monkeypatch.setattr(ext, "EXT_ELIGIBLE_RANKS", (1,))
    monkeypatch.setattr(ext, "EXT_SCENARIOS", ("s01",))
    assert ext.verify_pick_rule(ranking_c, ranking_r, []) == ["s01"]
    monkeypatch.setattr(ext, "EXT_SCENARIOS", ("s00",))
    with pytest.raises(SystemExit, match="PICK-RULE DRIFT"):
        ext.verify_pick_rule(ranking_c, ranking_r, [])


def test_pick_rule_excludes_pilot_topics():
    ranking_c = {f"s{i:02d}": 1000 - i for i in range(20)}
    ranking_r = {k: 500 for k in ranking_c}
    got = [k for k in sorted(ranking_c, key=lambda k: (-ranking_c[k], k))
           if k not in ("s00", "s01")][:1]
    assert got == ["s02"], "sanity: the pilot exclusion is by key"


def test_the_floor_guarantees_a_full_selection():
    """56 is not arbitrary. The measured MINIMUM pool/routed ratio across both arms is
    0.9423 (concat / niche_talent, 98 of 104) — an earlier version of this test cited 0.958,
    which is the r1 arm's range only and was false as a global claim."""
    worst = 0.9423
    assert ext.EXT_ROUTED_FLOOR * worst >= 50, "the floor cannot guarantee a 50-pair pool"


def test_the_floor_claim_matches_the_real_artifacts():
    """Re-derive the worst observed ratio rather than trusting the constant above."""
    ratios = []
    for arm in ext.EXT_ARMS:
        ev = json.loads(rt.evidence_art(arm).read_text(encoding="utf-8-sig"))
        for ps in ev["per_scenario"].values():
            if ps["routed_pairs"] and ps["pool_accounted"]:
                ratios.append(ps["pool_accounted"] / ps["routed_pairs"])
    assert ratios
    assert ext.EXT_ROUTED_FLOOR * min(ratios) >= 50, (
        f"worst observed ratio {min(ratios):.4f} breaks the floor's guarantee")


# --------------------------------------------------------------------------------------
# topics, packet split, counterbalancing
# --------------------------------------------------------------------------------------

def test_eleven_topics_original_first():
    t = ext.ext_topics(PILOT)
    assert len(t) == 11
    assert t[:5] == PILOT
    assert t[5:] == list(ext.EXT_SCENARIOS)


def test_packets_mix_original_and_new_topics():
    """A block split (0-5 / 6-10) would put every original topic in one packet and every new
    one in the other, perfectly confounding a packet-level reader effect with old-vs-new."""
    t = ext.ext_topics(PILOT)
    p1 = ext.topics_for_packet(t, 1)
    p2 = ext.topics_for_packet(t, 2)
    assert len(p1) == 6 and len(p2) == 5
    assert set(p1) | set(p2) == set(t) and not (set(p1) & set(p2))
    for p in (p1, p2):
        assert any(x in PILOT for x in p), "packet has no original topic"
        assert any(x in ext.EXT_SCENARIOS for x in p), "packet has no new topic"


def test_counterbalancing_alternates_within_and_flips_between_packets():
    for packet in (1, 2):
        sides = {ext.ext_treatment_side(i, packet) for i in range(5)}
        assert sides == {"A", "B"}, f"packet {packet} is all one side"
    for i in range(5):
        assert ext.ext_treatment_side(i, 1) != ext.ext_treatment_side(i, 2)


# --------------------------------------------------------------------------------------
# the PRIMARY statistic
# --------------------------------------------------------------------------------------

def test_pooled_sign_test_declares_no_winner_on_a_dead_heat():
    v = ext.pooled_sign_verdict(27, 28)
    assert v["winner"] is None and v["sign_p_two_sided"] > ext.EXT_ALPHA


def test_pooled_sign_test_declares_a_winner_only_below_alpha():
    lo = ext.pooled_sign_verdict(33, 22)      # 60% of 55, not significant
    assert lo["winner"] is None, lo["sign_p_two_sided"]
    hi = ext.pooled_sign_verdict(38, 17)      # 69% of 55
    assert hi["sign_p_two_sided"] < ext.EXT_ALPHA and hi["winner"] == "r1"


def test_pooled_sign_test_is_symmetric_for_the_control():
    v = ext.pooled_sign_verdict(17, 38)
    assert v["winner"] == ext.CONTROL and v["sign_p_two_sided"] < ext.EXT_ALPHA


def test_an_exact_tie_can_never_be_a_win(monkeypatch):
    """A tie gives p=1.0, so the direction guard is unreachable by the p-value alone; force
    alpha above 1 so ONLY the direction guard can reject, which is what this pins."""
    v = ext.pooled_sign_verdict(20, 20)
    assert v["winner"] is None
    monkeypatch.setattr(ext, "EXT_ALPHA", 2.0)
    assert ext.pooled_sign_verdict(20, 20)["winner"] is None, "a tie became a win"
    assert ext.pooled_sign_verdict(21, 20)["winner"] == "r1", "guard rejects a real lead"


def test_the_primary_is_the_pooled_vote_not_the_topic_count():
    """§14.1 makes the pooled vote primary because collapsing each topic to a binary is where
    the original design lost its power."""
    assert ext.EXT_ALPHA == 0.05
    # 3 readers = the ORIGINAL instrument, so E1 moves exactly one variable (topic count).
    # 5 readers was rejected: correlated readers make it ~12% more effective information
    # while making G-P materially harder to clear.
    assert ext.EXT_READERS == 3 and ext.EXT_TOPIC_MAJORITY == 2
    # The ceiling is a TOTAL across the original trial and E1, and it was amended upward by
    # the operator twice (70 -> 85 -> 100). Pinned as a floor plus the cross-trial property,
    # so a further authorised raise does not fail the suite while a silent RESET still does.
    assert ext.EXT_BUDGET >= 85, "the ceiling was lowered without an operator amendment"
    assert ext.EXT_BUDGET == 100


# --------------------------------------------------------------------------------------
# reader correlation
# --------------------------------------------------------------------------------------

def _key(n_route=3, n_cal=None, n_neg=2, treat_side="A", tag="t"):
    """n_cal defaults to the real calibration-set size: G-P needs >= rt.CAL_PASS_MIN of
    them, so a fixture with fewer voids every packet on G-P rather than testing what it
    means to test. `tag` namespaces the topics, because the packets PARTITION the topic set
    and score_ext now refuses a topic that appears twice."""
    if n_cal is None:
        n_cal = len(rt.CAL_SCENARIOS)
    items, i = [], 1
    for k in range(n_route):
        items.append({"item": i, "kind": "ROUTE", "scenario": f"{tag}{k}",
                      "treat_side": treat_side, "n_moves_treat": 2, "n_moves_base": 2})
        i += 1
    for k in range(n_cal):
        items.append({"item": i, "kind": "CAL", "scenario": f"c{k}", "real_side": "A",
                      "n_moves_real": 2, "n_moves_placebo": 2})
        i += 1
    for k in range(n_neg):
        items.append({"item": i, "kind": "NEG", "header_scenario": "n"})
        i += 1
    return {"items": items}


def test_identical_readers_are_reported_not_hidden():
    """G-R4 produced two byte-identical readers last night. Correlated votes make the sign
    test weaker than its nominal N, so the correlation must be visible."""
    key = _key()
    jd = lambda name, picks: {                                    # noqa: E731
        "reader": name,
        "items": {**{str(i + 1): {"choice": p} for i, p in enumerate(picks)},
                  "4": {"choice": "A"}, "5": {"choice": "A"},
                  "6": {"answer": "NO"}, "7": {"answer": "NO"}}}
    ag = ext.agreement_matrix([jd("a", ["A", "A", "B"]), jd("b", ["A", "A", "B"]),
                               jd("c", ["B", "A", "A"])], key["items"])
    assert ag["pairwise"]["a|b"]["rate"] == 1.0
    assert "a|b" in ag["identical_pairs"]
    assert "a|c" not in ag["identical_pairs"]


# --------------------------------------------------------------------------------------
# scoring end to end
# --------------------------------------------------------------------------------------

def _judgments(key, name, route_picks, cal_right=True, neg_reject=True, salt=0):
    items = {}
    ri = 0
    for row in key["items"]:
        i = str(row["item"])
        if row["kind"] == "ROUTE":
            items[i] = {"choice": route_picks[ri],
                        "apply_A": ["APPLY"] * 2,
                        "apply_B": ["VAGUE"] * (2 + salt)}
            ri += 1
        elif row["kind"] == "CAL":
            items[i] = {"choice": row["real_side"] if cal_right else
                        ("B" if row["real_side"] == "A" else "A")}
        else:
            items[i] = {"answer": "NO" if neg_reject else "YES"}
    return {"reader": name, "items": items}


def test_score_ext_pools_across_both_packets():
    k1, k2 = _key(n_route=3, n_neg=5), _key(n_route=2, n_neg=5, tag="u")
    j1 = [_judgments(k1, f"a{n}", ["A", "A", "A"], salt=n)
          for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A", "A"], salt=n)
          for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k1, k2], [j1, j2])
    assert res["voided_packets"] == []
    # 5 topics x EXT_READERS readers, treatment on A and every reader picked A
    assert res["primary_pooled"]["votes_treatment"] == 5 * ext.EXT_READERS
    assert res["primary_pooled"]["votes_base"] == 0
    assert res["secondary_topic_count"]["topics_r1_preferred"] == 5
    # AND the winner is correctly WITHHELD: these readers agree perfectly, so 15 raw votes
    # are only ~5 effective ones (5 topics), which a sign test cannot call at p<0.05. This is
    # audit finding 3 working — a clean sweep of 5 topics is not yet evidence.
    assert res["primary_pooled"]["winner"] is None
    assert res["primary_pooled"]["sign_p_two_sided"] < ext.EXT_ALPHA, "raw p looks big"
    assert res["primary_pooled"]["sign_p_correlation_adjusted"] > ext.EXT_ALPHA


def test_a_g_p_failure_voids_that_packet_and_excludes_its_votes():
    k1, k2 = _key(n_route=3, n_neg=5), _key(n_route=2, n_neg=5, tag="u")
    j1 = [_judgments(k1, f"a{n}", ["A", "A", "A"], cal_right=False, salt=n)
          for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A", "A"], salt=n)
          for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k1, k2], [j1, j2])
    assert res["voided_packets"] == [1]
    assert res["primary_pooled"]["votes_treatment"] == 2 * ext.EXT_READERS, (
        "the voided packet still contributed votes")
    assert "PARTIAL" in res["verdict"]


def test_too_few_valid_readers_voids_the_packet():
    k1, k2 = _key(n_route=3, n_neg=5), _key(n_route=2, n_neg=5, tag="u")
    j1 = [_judgments(k1, f"a{n}", ["A", "A", "A"], neg_reject=False, salt=n)
          for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A", "A"], salt=n)
          for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k1, k2], [j1, j2])
    assert 1 in res["voided_packets"]
    assert "G-V" in res["packets"][0]["reason"]


def test_duplicate_payload_is_refused_per_packet():
    k1, k2 = _key(n_route=3, n_neg=5), _key(n_route=2, n_neg=5, tag="u")
    j1 = [_judgments(k1, f"a{n}", ["A", "A", "A"])
          for n in range(ext.EXT_READERS)]   # no salt
    j2 = [_judgments(k2, f"b{n}", ["A", "A"], salt=n)
          for n in range(ext.EXT_READERS)]
    with pytest.raises(ValueError, match="byte-identical"):
        ext.score_ext([k1, k2], [j1, j2])


def test_new_topics_are_flagged_so_old_and_new_can_be_compared():
    k1 = _key(n_route=1, n_neg=5)
    k1["items"][0]["scenario"] = ext.EXT_SCENARIOS[0]
    k2 = _key(n_route=1, n_neg=5, tag="u")
    k2["items"][0]["scenario"] = "an_original_topic"
    j1 = [_judgments(k1, f"a{n}", ["A"], salt=n) for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A"], salt=n) for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k1, k2], [j1, j2])
    assert res["per_topic"][ext.EXT_SCENARIOS[0]]["is_new_topic"] is True
    assert res["per_topic"]["an_original_topic"]["is_new_topic"] is False


# --------------------------------------------------------------------------------------
# isolation from the primary result
# --------------------------------------------------------------------------------------

def test_packet_rng_does_not_crash_after_the_spend():
    """AUDIT FINDING 1: `--build-read` used rt.packet_rng("ext_p1"), which resolves its label
    against rt.COMPARISONS and raises ValueError. It would have fired only at this stage —
    i.e. after every chat call had been paid for — and no test covered the stage."""
    for packet in (1, 2):
        a = ext.ext_packet_rng(packet)
        b = ext.ext_packet_rng(packet)
        assert [a.random() for _ in range(3)] == [b.random() for _ in range(3)]
    assert (ext.ext_packet_rng(1).random() != ext.ext_packet_rng(2).random())
    with pytest.raises(SystemExit):
        ext.ext_packet_rng(99)
    with pytest.raises(ValueError):
        rt.packet_rng("ext_p1")          # the original bug, pinned so it cannot come back


def test_void_packet_cannot_name_a_winner():
    """AUDIT FINDING 2: the surviving half of the split is not neutral — it holds r1's two
    unanimous original-topic losses or its two wins, depending which packet dies."""
    v = ext.pooled_sign_verdict(25, 0, mean_agreement=0.6, voided=True)
    assert v["winner"] is None and "winner_suppressed" in v
    ok = ext.pooled_sign_verdict(25, 0, mean_agreement=0.6, voided=False)
    assert ok["winner"] == "r1", "the suppression must depend on VOID, not break the test"


def test_correlated_votes_cannot_pass_on_the_raw_p_alone():
    """AUDIT FINDING 3: 33 votes are 11 topics x 3 correlated readers. At the measured
    agreement the naive test's true type-I error is ~3x its nominal alpha, so the
    correlation-adjusted p must ALSO clear alpha before a winner is named."""
    # perfectly agreeing readers -> ICC 1 -> deff = EXT_READERS -> n_eff = 11
    v = ext.pooled_sign_verdict(23, 10, mean_agreement=1.0)
    assert v["sign_p_two_sided"] < ext.EXT_ALPHA, "raw p should look significant"
    assert v["sign_p_correlation_adjusted"] > ext.EXT_ALPHA
    assert v["winner"] is None, "a winner was named on the uncorrected p"
    assert v["design_effect_approx"] == pytest.approx(float(ext.EXT_READERS))


def test_design_effect_spans_chance_to_perfect_agreement():
    d0, i0 = ext.design_effect(0.5)
    d1, i1 = ext.design_effect(1.0)
    assert (d0, i0) == (1.0, 0.0)
    assert i1 == 1.0 and d1 == float(ext.EXT_READERS)
    assert ext.design_effect(0.2)[0] == 1.0, "below-chance agreement must not shrink deff"


def test_side_share_reports_the_channel_that_explained_the_original_result():
    """AUDIT FINDING 4: readers answered A on 80% of the original routing items, and pure
    position answering predicts r1 6-9 against the 7-8 observed."""
    key = _key(n_route=2, n_neg=2)
    jd = [{"reader": "a", "items": {"1": {"choice": "A"}, "2": {"choice": "A"},
                                    "3": {"choice": "A"}, "4": {"choice": "A"},
                                    "5": {"choice": "A"}, "6": {"choice": "A"},
                                    "7": {"answer": "NO"}, "8": {"answer": "NO"}}}]
    ss = ext.side_share(jd, key["items"])
    assert ss["pooled_a_share_route"] == 1.0
    assert ss["pooled_a_share_pairs"] == 1.0
    assert ss["per_reader"]["a"]["a_of_route"] == 2


def test_round_scoping_namespaces_are_disjoint_both_ways():
    """AUDIT FINDING 5: the §12.2.1 defect had come back — ext_judgments_glob accepted a
    round and nothing ever passed one."""
    import fnmatch
    r1f = "rte_p1_judgments_r1.json"
    r2f = "rte_p1_round2_judgments_r4.json"
    assert fnmatch.fnmatch(r1f, ext.ext_judgments_glob(1))
    assert not fnmatch.fnmatch(r2f, ext.ext_judgments_glob(1))
    assert fnmatch.fnmatch(r2f, ext.ext_judgments_glob(1, 2))
    assert not fnmatch.fnmatch(r1f, ext.ext_judgments_glob(1, 2))
    # and a packet-2 file must never match a packet-1 glob
    assert not fnmatch.fnmatch("rte_p2_judgments_r1.json", ext.ext_judgments_glob(1))


def test_score_refuses_a_mixed_namespace(monkeypatch, tmp_path):
    monkeypatch.setattr(ext, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(ext, "EXT_REPORT", tmp_path / "rte_report.json")
    for i in (1, 2):
        (tmp_path / f"rte_p{i}_read_KEY.json").write_text(
            json.dumps(_key(n_route=1, n_neg=5)), encoding="utf-8")
    for n in range(1, ext.EXT_READERS + 3):
        (tmp_path / f"rte_p1_judgments_r{n}.json").write_text(
            json.dumps({"reader": f"r{n}", "items": {}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="mixed in one namespace"):
        ext.stage_score()


def test_duplicate_topic_across_packets_is_refused():
    k1 = _key(n_route=1, n_neg=5)
    k2 = _key(n_route=1, n_neg=5)          # same tag -> same topic name in both packets
    j1 = [_judgments(k1, f"a{n}", ["A"], salt=n) for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A"], salt=n) for n in range(ext.EXT_READERS)]
    with pytest.raises(ValueError, match="more than one packet"):
        ext.score_ext([k1, k2], [j1, j2])


def test_e1_writes_only_rte_artifacts():
    paths = [ext.ext_evidence_art("r1"), ext.ext_route_art("r1"),
             ext.ext_playbooks_art("concat"), ext.ext_snapped_art("concat"),
             ext.ext_pb0_art("r1"), ext.ext_packet_art(1), ext.ext_key_art(2),
             ext.EXT_REPORT]
    for p in paths:
        assert p.name.startswith("rte_"), p.name


def test_e1_never_targets_the_primary_trials_artifacts():
    primary = {rt.route_art("concat").name, rt.evidence_art("concat").name,
               rt.playbooks_art("r1").name, rt.snapped_art("r1").name,
               rt.report_art("r1").name, rt.DIVERGENCE.name}
    mine = {ext.ext_evidence_art(a).name for a in ext.EXT_ARMS}
    mine |= {ext.ext_playbooks_art(a).name for a in ext.EXT_ARMS}
    mine |= {ext.ext_snapped_art(a).name for a in ext.EXT_ARMS}
    mine |= {ext.EXT_REPORT.name}
    assert not (primary & mine)


def test_keyphrases_cannot_take_part_in_e1():
    assert "keyphrases" not in ext.EXT_ARMS
    with pytest.raises(SystemExit, match="disqualified"):
        ext._check_arm("keyphrases")


def test_budget_is_a_total_across_the_original_trial_and_e1(monkeypatch, tmp_path):
    """A new module must not be able to reset the ceiling."""
    monkeypatch.setattr(rt, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(ext, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "rt_playbooks_concat.json").write_text(
        json.dumps({"calls_used": 15, "documents": {}}), encoding="utf-8")
    (tmp_path / "rt_playbooks_r1.json").write_text(
        json.dumps({"calls_used": 17, "documents": {}}), encoding="utf-8")
    (tmp_path / "rte_playbooks_concat.json").write_text(
        json.dumps({"calls_used": 18, "documents": {}}), encoding="utf-8")
    assert ext.ext_spend_so_far() == 50
    assert ext.ext_spend_so_far(exclude="concat") == 32


def test_model_pin_is_inherited_not_redefined():
    """Both arms in both trials must be model-identical, or the read compares models."""
    import calibration.routing_playbook_ext as m
    src = (m.__file__ or "")
    assert src.endswith("routing_playbook_ext.py")
    # the module must reference the original's constants rather than its own literals
    text = open(m.__file__, encoding="utf-8").read()
    assert "rt.RT_CHAT_MODEL" in text and "rt.RT_REASONING" in text
    assert 'RT_CHAT_MODEL = "' not in text, "E1 redefined the model pin"


# --------------------------------------------------------------------------------------
# re-audit repairs
# --------------------------------------------------------------------------------------

def test_adjusted_threshold_rounds_toward_the_null():
    """RE-AUDIT: int(round(share*n_eff)) shifted the adjusted win threshold DOWN one vote
    across the whole agreement range — at agreement 0.733, t=25 of 33 rounded UP to 13/17
    (p_adj 0.049, a WIN) where flooring gives 12/17 (0.144, no winner). A permissive rounding
    choice in an extension designed after seeing a null must not be left to chance."""
    v = ext.pooled_sign_verdict(25, 8, mean_agreement=0.7333)
    assert v["n_votes_effective"] == 17
    assert v["sign_p_correlation_adjusted"] > ext.EXT_ALPHA
    assert v["winner"] is None, "the one-vote permissive rounding came back"


def test_rounding_is_symmetric_for_the_control():
    lo = ext.pooled_sign_verdict(8, 25, mean_agreement=0.7333)
    hi = ext.pooled_sign_verdict(25, 8, mean_agreement=0.7333)
    assert lo["sign_p_correlation_adjusted"] == hi["sign_p_correlation_adjusted"]


def test_adjusted_p_is_never_smaller_than_raw_in_a_way_that_creates_a_win():
    """The conjunction (raw < alpha AND adjusted < alpha) makes an anti-conservative adjusted
    p harmless, but pin it: no (t, agreement) combination may win on the adjusted p alone."""
    for t in range(0, 34):
        for a in (0.5, 0.6, 0.7333, 0.85, 1.0):
            v = ext.pooled_sign_verdict(t, 33 - t, mean_agreement=a)
            if v["winner"] is not None:
                assert v["sign_p_two_sided"] < ext.EXT_ALPHA
                assert v["sign_p_correlation_adjusted"] < ext.EXT_ALPHA


def test_void_packet_still_reports_the_bias_diagnostics():
    """RE-AUDIT: on a G-V VOID, `valid` is empty and side_share/agreement were written as
    null — precisely the packet where the operator must know whether the discarded readers
    answered by position."""
    k = _key(n_route=2, n_neg=5)
    jds = [_judgments(k, f"a{n}", ["A", "A"], neg_reject=False, salt=n)
           for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k], [jds])
    p = res["packets"][0]
    assert p["verdict"] == "VOID" and p["n_valid"] == 0
    assert p["side_share"] is None
    assert p["side_share_all_submitted"]["scope"] == "all_submitted"
    assert p["side_share_all_submitted"]["pooled_a_share_route"] == 1.0
    assert p["agreement_all_submitted"]["mean_rate"] == 1.0


def test_round_one_is_refused_with_the_right_message():
    with pytest.raises(SystemExit, match="round 1 is the unscoped default"):
        ext.ext_judgments_glob(1, 1)


def test_void_verdict_text_names_the_real_vote_count():
    """RE-AUDIT: the VOID verdict string said '55-vote', the 5-reader design's number, and
    that string goes into the artifact."""
    k1 = _key(n_route=2, n_neg=5)
    k2 = _key(n_route=1, n_neg=5, tag="u")
    j1 = [_judgments(k1, f"a{n}", ["A", "A"], cal_right=False, salt=n)
          for n in range(ext.EXT_READERS)]
    j2 = [_judgments(k2, f"b{n}", ["A"], salt=n) for n in range(ext.EXT_READERS)]
    res = ext.score_ext([k1, k2], [j1, j2])
    assert "PARTIAL" in res["verdict"]
    assert "55-vote" not in res["verdict"]
    assert f"{11 * ext.EXT_READERS}-vote" in res["verdict"]
