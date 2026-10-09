#!/usr/bin/env python3
"""EXTENSION E1: widened, higher-powered re-test of `r1` vs control on the playbook yardstick.

Spec: docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md §14 (FROZEN
2026-08-19, pre-registered before this file existed and AFTER the original 5-topic result
was known — see §14.0, which states that ordering and its risk openly).

    11 topics = the original 5 + 6 new     |     2 arms: concat (control) vs r1
    2 packets x 3 FRESH readers            |     PRIMARY = pooled 33-vote sign test
    (3 readers = the ORIGINAL instrument; only the topic count moves)

*** THIS MODULE IMPORTS THE ORIGINAL HARNESS AND OVERWRITES NOTHING OF ITS OUTPUT. ***
`routing_playbook_ab.py` produced the primary pre-registered result; it is not edited, and
its `rt_*` artifacts are read-only here. Everything E1 writes is `rte_*`. Document
production is carried over UNCHANGED (same map, corpus, routing, 50-pair selection rule,
prompts verbatim, model pin, snap, fidelity gate) so the only deliberate differences from
the original read are the TOPIC COUNT and the primary statistic. The reader count
stays at 3 so exactly one thing about the sample changes.

WHY THE PRIMARY STATISTIC CHANGED (§14.1): the original collapsed each topic to a binary
before aggregating, which threw away most of its information — at 5 topics and 3 readers a
5/5 bar has ~17% power even if r1 truly wins 70% of topics. E1 pools all 33 votes and runs a
two-sided sign test, CORRELATION-ADJUSTED (readers are not independent). It is better; it is still not a high-powered test, and §14.1 fixes that
in advance rather than discovering it afterwards.

Usage (from Brain/, one arm/stage per process):
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ext.py -ScriptArgs '--select --arm concat'
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ext.py -ScriptArgs '--select --arm r1'
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ext.py -ScriptArgs '--synthesize --arm concat'
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ext.py -ScriptArgs '--synthesize --arm r1'
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ext.py --snap --arm concat
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ext.py --pb0 --arm concat
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ext.py --build-read --packet 1
    # (3 blinded readers per packet write artifacts/rte_p<N>_judgments_r*.json, ONE AT A TIME)
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ext.py --score
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration import routing_playbook_ab as rt  # noqa: E402
from calibration.scenario_playbook_trial import _cit_ok  # noqa: E402
from calibration.scenario_playbook_trial import (  # noqa: E402
    ACCT_FLOOR, ATTEMPTS_PER_CALL, BATCH_MAX, CHAT_TEMPERATURE, N_EVIDENCE_MAX, N_NEG,
    SEED, build_neg, build_pool, map_prompt, pb0_doc, reader_valid, reduce_prompt,
    render_doc, scenario_header_text, sign_test_two_sided, validate_map, validate_playbook,
)
from calibration.playbook_snap_trial import pb1_doc_resized, snap_doc  # noqa: E402

# --------------------------------------------------------------------------------------
# FROZEN (spec §14.1). None of this may move after any E1 result is seen.
# --------------------------------------------------------------------------------------
EXT_ARMS = ("concat", "r1")          # keyphrases is DISQUALIFIED (§13); it takes no part
CONTROL = rt.CONTROL

# The 6 new topics: eligible ranks 1, 4, 7, 10, 13, 16 where eligible = not already in the
# pilot AND >= 56 routed pairs in BOTH arms, ranked by the CONTROL's routed count. Ranked on
# the control so the choice cannot favour the challenger; the 56 floor is the measured
# pool/routed ratio (0.958-0.986) rounded up so a 50-pair pool is guaranteed and no topic can
# be lost to a volume-shortfall disqualification. Frozen as literals, and `verify_pick_rule`
# re-derives them from the artifacts so a silent drift fails loudly.
EXT_SCENARIOS = (
    "campaign_level_performance_tracking",
    "programmatic_advertising_scope_and_capability",
    "xml_feed_setup_and_ingestion",
    "testing_and_implementation_timeline",
    "craigslist_and_classifieds_strategy",
    "job_role_taxonomy_and_scoping",
)
EXT_ELIGIBLE_RANKS = (1, 4, 7, 10, 13, 16)
EXT_ROUTED_FLOOR = 56

# *** 3 READERS, NOT 5 — THE INSTRUMENT IS IDENTICAL TO THE ORIGINAL READ. ***
# An earlier draft of this extension used 5, on the assumption that more readers meant more
# power. Two measured facts killed it (operator caught the first):
#   1. Readers are correlated draws from ONE model — measured ICC ~= 0.47 from the original
#      judgments — so design effect 1+(m-1)*ICC takes 33 raw votes at m=3 to ~17 effective
#      and 55 raw votes at m=5 to ~19. Going 3 -> 5 buys ~12% effective information. The
#      independent unit is the TOPIC, not the reader; 5 -> 11 topics is what actually helps.
#   2. It made G-P HARDER: a real-on-B calibration pair needs 3/5 instead of 2/3, dropping
#      from ~0.104 to ~0.058 against a side-biased pool — so raising readers raised the
#      chance of buying two unreadable packets.
# Keeping 3 also means E1 moves EXACTLY ONE variable from the original (the topic count),
# which is this repo's standing discipline, and it means the original read already
# demonstrates this pool clears G-P at 3 readers (3/4, including a real-on-B pair at 3/3).
EXT_READERS = 3
EXT_TOPIC_MAJORITY = 2               # of 3 readers -> that topic prefers that arm
EXT_ALPHA = 0.05                     # two-sided sign test on the POOLED votes (PRIMARY)
EXT_BUDGET = 100                     # TOTAL chat attempts incl. the original 32.
# BUDGET AMENDMENT (operator, 2026-08-19): raised 85 -> 100 as insurance after a SECOND
# document hit three schema rejects. Without headroom a stubborn document could halt
# mid-arm and strand E1 with an incomplete r1 arm, wasting the 63 attempts already
# spent. Expected landing remains ~78; the extra 15 is protection, not a plan to spend.
N_PACKETS = 2

EXT_REPORT = ARTIFACTS_DIR / "rte_report.json"


def ext_evidence_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rte_evidence_{arm}.json"


def ext_route_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rte_route_{arm}.json"


def ext_playbooks_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rte_playbooks_{arm}.json"


def ext_snapped_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rte_snapped_{arm}.json"


def ext_pb0_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rte_pb0_{arm}.json"


def ext_packet_art(i: int) -> Path:
    return ARTIFACTS_DIR / f"rte_p{i}_read_packet.txt"


def ext_key_art(i: int) -> Path:
    return ARTIFACTS_DIR / f"rte_p{i}_read_KEY.json"


def ext_judgments_glob(i: int, round_: int | None = None) -> str:
    if round_ is None:
        return f"rte_p{i}_judgments_*.json"
    if round_ < 2:
        raise SystemExit("--round is for a RE-dispatch after a VOID; round 1 is the "
                         "unscoped default")
    return f"rte_p{i}_round{round_}_judgments_*.json"


def _check_arm(arm: str) -> str:
    if arm not in EXT_ARMS:
        raise SystemExit(f"--arm must be one of {EXT_ARMS} (keyphrases is disqualified "
                         f"per §13 and takes no part in E1), got {arm!r}")
    return arm


# ======================================================================================
# pure functions (unit-tested in tests/test_routing_playbook_ext.py)
# ======================================================================================

def verify_pick_rule(ranking_control: dict, ranking_r1: dict, pilot: list[str]) -> list[str]:
    """Re-derive EXT_SCENARIOS from the artifacts and assert the frozen literals match.

    The topics are hardcoded so they are readable in the spec, but a hardcoded list is a
    claim about data, and this repo's habit is to verify such claims rather than trust them.

    *** SCOPE, STATED HONESTLY (audit finding 6): this compares the frozen literals against
    the rule applied to the ORIGINAL trial's persisted rankings. It is a check against a
    constant, NOT a drift detector — an earlier docstring claimed otherwise and was wrong.
    Drift is caught separately, by `stage_select` asserting that THIS run's freshly computed
    routed counts reproduce those persisted rankings exactly. ***
    """
    eligible = [k for k in sorted(ranking_control,
                                 key=lambda k: (-ranking_control[k], k))
                if k not in pilot
                and ranking_control[k] >= EXT_ROUTED_FLOOR
                and ranking_r1.get(k, 0) >= EXT_ROUTED_FLOOR]
    if len(eligible) < max(EXT_ELIGIBLE_RANKS):
        raise SystemExit(f"only {len(eligible)} eligible topics; the frozen rule needs "
                         f"rank {max(EXT_ELIGIBLE_RANKS)}")
    derived = [eligible[r - 1] for r in EXT_ELIGIBLE_RANKS]
    if tuple(derived) != EXT_SCENARIOS:
        raise SystemExit(
            f"PICK-RULE DRIFT: the frozen rule now selects\n  {derived}\nbut the frozen "
            f"literals are\n  {list(EXT_SCENARIOS)}\nSomething upstream moved; refusing to "
            f"run on a topic set that is not the pre-registered one.")
    return derived


def ext_topics(pilot: list[str]) -> list[str]:
    """The 11 topics in frozen order: the original pilot in its rank order, then the 6 new
    ones in eligible-rank order."""
    return list(pilot) + list(EXT_SCENARIOS)


def packet_of(index: int) -> int:
    """Frozen packet assignment: alternating by topic index, so each packet carries a MIX of
    original and new topics. 11 topics -> packet 1 gets 6 (even indices), packet 2 gets 5.

    Alternating rather than splitting 0-5 / 6-10 on purpose: a block split would put every
    original topic in one packet and every new topic in the other, so a packet-level reader
    effect would be perfectly confounded with old-vs-new topics.
    """
    return 1 if index % 2 == 0 else 2


def topics_for_packet(topics: list[str], packet: int) -> list[str]:
    return [t for i, t in enumerate(topics) if packet_of(i) == packet]


def ext_packet_rng(packet: int):
    """One deterministic shuffle stream per E1 packet, in its own numeric range so it can
    never collide with the original trial's streams."""
    import random
    if packet not in range(1, N_PACKETS + 1):
        raise SystemExit(f"packet must be 1..{N_PACKETS}, got {packet!r}")
    return random.Random(SEED + 1000 * (10 + packet))


def ext_treatment_side(position: int, packet: int) -> str:
    """Counterbalancing: r1 takes A iff (position within packet + packet index) is even.
    Alternates within a packet AND flips between packets, so no arm sits on one side."""
    return rt.treatment_side(position, packet - 1)


def design_effect(mean_agreement: float, m: int = EXT_READERS) -> tuple[float, float]:
    """(design_effect, ICC) from the observed pairwise reader agreement.

    `ICC ~= (a - 0.5) / 0.5`, i.e. chance agreement is taken as 0.5 and perfect agreement as
    1.0; clamped to [0, 1]. deff = 1 + (m - 1) * ICC.

    *** DELIBERATELY CONSERVATIVE, AND NOT A DEFENSIBLE ICC ESTIMATE IN GENERAL. *** Taking
    chance agreement as 0.5 conflates MARGINAL SKEW with reader correlation: this pool
    answered "A" on 12 of 15 routing items, so chance agreement under independence is
    0.8^2 + 0.2^2 = 0.68 and the exchangeable-binary correlation is
    rho = 1 - (1 - a) / (2 p (1 - p)) ~= 0.167, not the 0.467 this estimator returns.
    Over-stating rho over-states deff, which only ever makes the adjusted p LARGER — the safe
    direction for a gate, which is why it is kept here. It must NOT be used to reason about
    how much power a design has: re-audit finding, and the reader-count amendment in §14.1
    was argued from the wrong figure. Power is reported from simulation, not from deff.
    """
    icc = max(0.0, min(1.0, (mean_agreement - 0.5) / 0.5))
    return 1.0 + (m - 1) * icc, icc


def pooled_sign_verdict(votes_treatment: int, votes_base: int,
                        mean_agreement: float | None = None,
                        voided: bool = False) -> dict:
    """THE PRIMARY STATISTIC (§14.1): a two-sided sign test on every judgment cast, with a
    correlation-adjusted companion, and no winner unless BOTH clear alpha.

    *** THE RAW SIGN TEST OVER THESE VOTES IS ANTI-CONSERVATIVE. *** 33 votes are 11 topics
    x 3 readers, and readers within a topic are not independent — `agreement_matrix` exists
    because they are not. Declaring a winner on the uncorrected p would run a nominal 5% test
    at a true error rate closer to 16%, which is precisely the "second bite at an easier bar"
    that an extension designed after seeing a null must not take. So the adjusted p must also
    clear alpha, and a tie in direction can never be a win regardless of either p.

    `voided` suppresses the winner outright: with a packet VOID the surviving votes are not
    the pre-registered sample, and the split is not neutral — the alternating assignment puts
    r1's two unanimous original-topic losses in one packet and its two wins in the other, so
    whichever half survives flatters one arm.
    """
    n = votes_treatment + votes_base
    p_raw = sign_test_two_sided(votes_treatment, votes_base)
    share = (votes_treatment / n) if n else 0.0
    out = {"votes_treatment": votes_treatment, "votes_base": votes_base, "n_votes": n,
           "sign_p_two_sided": p_raw, "alpha": EXT_ALPHA, "share_treatment": share}
    p_adj, deff, icc = p_raw, 1.0, 0.0
    if mean_agreement is not None and n:
        deff, icc = design_effect(mean_agreement)
        n_eff = max(1, int(round(n / deff)))
        # ROUND TOWARD THE NULL, never away from it (re-audit finding). int(round(...))
        # shifted the adjusted win threshold DOWN by one vote across the whole agreement
        # range — e.g. at agreement 0.733, t=25 of 33 rounded UP to 13/17 (p_adj 0.049,
        # "r1 WINS") where flooring gives 12/17 (p_adj 0.144, no winner). A permissive
        # rounding choice in an extension designed after seeing a null is exactly what must
        # not be left to chance.
        import math
        k_eff = (int(share * n_eff) if share > 0.5
                 else math.ceil(share * n_eff) if share < 0.5
                 else int(round(share * n_eff)))
        p_adj = sign_test_two_sided(k_eff, n_eff - k_eff)
        out.update({"mean_reader_agreement": mean_agreement, "icc_approx": icc,
                    "design_effect_approx": deff, "n_votes_effective": n_eff,
                    "sign_p_correlation_adjusted": p_adj,
                    "adjustment_note": "APPROXIMATE (see design_effect); the adjusted p is "
                                       "what the verdict uses, never the raw one alone"})
    winner = None
    if (not voided and votes_treatment != votes_base
            and p_raw < EXT_ALPHA and p_adj < EXT_ALPHA):
        winner = "r1" if votes_treatment > votes_base else CONTROL
    out["winner"] = winner
    if voided:
        out["winner_suppressed"] = ("a packet VOIDed; the surviving votes are not the "
                                    "pre-registered sample and the packet split is not "
                                    "neutral between the arms")
    return out


def side_share(judgments: list[dict], key_items: list[dict]) -> dict:
    """How often readers answered "A" on the PAIR items, per reader and pooled.

    *** THIS IS THE CHANNEL THAT TURNED OUT TO EXPLAIN THE ORIGINAL RESULT, AND IT WAS NOT
    MEASURED. *** On the original read the pool answered A on 12 of 15 routing votes (80%)
    and 20 of 27 pair items (74%), while r1 held A on 2 topics and B on 3 — so pure position
    answering predicts r1 6 votes to control 9, against the 7-8 observed. A pooled result
    from a side-biased pool carries far less content information than its p-value suggests,
    and an operator cannot see that unless it is reported.
    """
    pairs = [str(r["item"]) for r in key_items if r["kind"] in ("ROUTE", "CAL")]
    route = [str(r["item"]) for r in key_items if r["kind"] == "ROUTE"]
    per_reader, tot_a, tot_n, r_a, r_n = {}, 0, 0, 0, 0
    for jd in judgments:
        a = sum(1 for k in pairs
                if str((jd["items"].get(k) or {}).get("choice", "")).upper() == "A")
        ra = sum(1 for k in route
                 if str((jd["items"].get(k) or {}).get("choice", "")).upper() == "A")
        per_reader[jd["reader"]] = {"a_of_pairs": a, "n_pairs": len(pairs),
                                   "a_share_pairs": (a / len(pairs)) if pairs else 0.0,
                                   "a_of_route": ra, "n_route": len(route)}
        tot_a += a
        tot_n += len(pairs)
        r_a += ra
        r_n += len(route)
    return {"per_reader": per_reader,
            "pooled_a_share_pairs": (tot_a / tot_n) if tot_n else 0.0,
            "pooled_a_share_route": (r_a / r_n) if r_n else 0.0,
            "note": "a pooled share far from 0.5 means position, not content, may be "
                    "driving the votes (see side_share docstring)"}


def agreement_matrix(judgments: list[dict], key_items: list[dict]) -> dict:
    """Pairwise reader agreement on the ROUTE items.

    Sonnet readers are draws from ONE model, not independent judges — G-R4 produced two
    byte-identical readers last night. Correlated votes make the pooled sign test worth less
    than its nominal N, so the correlation is REPORTED next to the p-value AND gates the
    verdict, rather than the p-value being presented as if independence held (§14.1).
    """
    route = [str(r["item"]) for r in key_items if r["kind"] == "ROUTE"]
    names = [jd["reader"] for jd in judgments]
    out, ident = {}, []
    for i in range(len(judgments)):
        for j in range(i + 1, len(judgments)):
            a = [str((judgments[i]["items"].get(k) or {}).get("choice", "")).upper()
                 for k in route]
            b = [str((judgments[j]["items"].get(k) or {}).get("choice", "")).upper()
                 for k in route]
            same = sum(1 for x, y in zip(a, b) if x == y)
            out[f"{names[i]}|{names[j]}"] = {"agree": same, "of": len(route),
                                             "rate": (same / len(route)) if route else 0.0}
            if route and same == len(route):
                ident.append(f"{names[i]}|{names[j]}")
    rates = [v["rate"] for v in out.values()]
    return {"pairwise": out, "mean_rate": (sum(rates) / len(rates)) if rates else 0.0,
            "identical_pairs": ident}


def score_ext(keys: list[dict], judgments_by_packet: list[list[dict]]) -> dict:
    """G-V and G-P per packet, then the POOLED primary across both packets.

    Reuses `reader_valid` verbatim (every item answered, >= 4/5 negatives rejected) and
    `rt.CAL_PASS_MIN` for G-P; only the reader count and the aggregation are E1's own.
    """
    packets, valid_by_packet = [], []
    for pi, (key, jds) in enumerate(zip(keys, judgments_by_packet), start=1):
        names = [jd["reader"] for jd in jds]
        if len(set(names)) != len(names):
            raise ValueError(f"packet {pi}: duplicate reader identity {names}")
        payloads = [json.dumps(jd["items"], sort_keys=True) for jd in jds]
        if len(set(payloads)) != len(payloads):
            raise ValueError(f"packet {pi}: two judgment files are byte-identical — a "
                             f"duplicated dispatch, not two readers")
        validity, valid = {}, []
        for jd in jds:
            ok, why = reader_valid(jd["items"], key["items"])
            validity[jd["reader"]] = {"valid": ok, "why": why}
            if ok and len(valid) < EXT_READERS:
                valid.append(jd)
        rec = {"packet": pi, "validity": validity,
               "n_valid": len(valid), "readers_required": EXT_READERS,
               "agreement": agreement_matrix(valid, key["items"]) if valid else None,
               "side_share": side_share(valid, key["items"]) if valid else None,
               # ON A G-V VOID `valid` IS EMPTY, and that is exactly the packet where the
               # operator needs to know whether the discarded readers were answering by
               # position before re-dispatching (re-audit finding). So both diagnostics are
               # also computed over EVERY submitted reader, tagged with their scope.
               "agreement_all_submitted": agreement_matrix(jds, key["items"]),
               "side_share_all_submitted": {**side_share(jds, key["items"]),
                                           "scope": "all_submitted"},
               "calibration_channels": rt.cal_channels(key)}
        if len(valid) < EXT_READERS:
            rec.update({"verdict": "VOID",
                        "reason": f"G-V: only {len(valid)} valid reader(s) of "
                                  f"{EXT_READERS} required"})
            packets.append(rec)
            valid_by_packet.append([])
            continue
        cal = {}
        for row in key["items"]:
            if row["kind"] != "CAL":
                continue
            v = sum(1 for jd in valid
                    if str((jd["items"].get(str(row["item"])) or {}).get(
                        "choice", "")).upper() == row["real_side"])
            cal[row["scenario"]] = {"votes_real": v,
                                    "real_preferred": v >= EXT_TOPIC_MAJORITY}
        n_cal = sum(1 for r in cal.values() if r["real_preferred"])
        rec["g_p"] = {"calibration_pairs": cal, "n_real_preferred": n_cal,
                      "min_required": rt.CAL_PASS_MIN,
                      "pass": n_cal >= rt.CAL_PASS_MIN}
        rec["verdict"] = "OK" if rec["g_p"]["pass"] else "VOID"
        if not rec["g_p"]["pass"]:
            rec["reason"] = (f"G-P: real preferred on only {n_cal}/{len(cal)} calibration "
                             f"pairs (< {rt.CAL_PASS_MIN}); this packet has not been shown "
                             f"to discriminate, so neither a win nor a null is readable")
        packets.append(rec)
        valid_by_packet.append(valid if rec["g_p"]["pass"] else [])

    per_topic, t_tot, b_tot = {}, 0, 0
    for key, valid in zip(keys, valid_by_packet):
        for row in key["items"]:
            if row["kind"] != "ROUTE" or not valid:
                continue
            side = row["treat_side"]
            v = sum(1 for jd in valid
                    if str((jd["items"].get(str(row["item"])) or {}).get(
                        "choice", "")).upper() == side)
            t_tot += v
            b_tot += len(valid) - v
            # The packets PARTITION the topics, so a scenario must appear in exactly one.
            # Without this guard a duplicated topic would silently overwrite its own
            # per-topic row (the pooled count would still be right, so the loss would show
            # up only as a quietly shrunken secondary denominator).
            if row["scenario"] in per_topic:
                raise ValueError(
                    f"topic {row['scenario']!r} appears in more than one packet; the packet "
                    f"split must partition the topics or the per-topic tally silently "
                    f"loses one of them")
            n_moves = row.get("n_moves_treat", 0)
            applies = [[str(x).upper() == "APPLY"
                        for x in ((jd["items"].get(str(row["item"])) or {}).get(
                            f"apply_{side}") or [])] for jd in valid]
            move_ok = [sum(1 for a in applies if mi < len(a) and a[mi])
                       >= EXT_TOPIC_MAJORITY for mi in range(n_moves)]
            per_topic[row["scenario"]] = {
                "votes_r1": v, "n_valid": len(valid),
                "r1_preferred": v >= EXT_TOPIC_MAJORITY,
                "is_new_topic": row["scenario"] in EXT_SCENARIOS,
                # the move-count channel is live on ROUTE items too, not only calibration
                # ones (audit finding 7): report both sides' counts next to the vote
                "n_moves_treat": n_moves, "n_moves_base": row.get("n_moves_base"),
                "apply_share_r1": (sum(move_ok) / n_moves) if n_moves else 0.0}

    voided = [p["packet"] for p in packets if p["verdict"] == "VOID"]
    rates = [p["agreement"]["mean_rate"] for p in packets
             if p.get("agreement") and p["verdict"] != "VOID"]
    mean_agree = (sum(rates) / len(rates)) if rates else None
    out = {"packets": packets, "voided_packets": voided, "per_topic": per_topic,
           "primary_pooled": pooled_sign_verdict(t_tot, b_tot, mean_agree,
                                                voided=bool(voided))}
    n_pref = sum(1 for r in per_topic.values() if r["r1_preferred"])
    out["secondary_topic_count"] = {
        "topics_r1_preferred": n_pref, "n_topics": len(per_topic),
        "binomial_p_two_sided": sign_test_two_sided(n_pref, len(per_topic) - n_pref),
        "note": "SECONDARY, never decisive (spec §14.1)"}
    if voided:
        out["verdict"] = (f"PARTIAL — packet(s) {voided} VOID; the pooled statistic covers "
                          f"only the surviving packet(s) and is NOT the pre-registered "
                          f"{11 * EXT_READERS}-vote test")
    else:
        w = out["primary_pooled"]["winner"]
        out["verdict"] = (f"{w} WINS (pooled sign test p="
                          f"{out['primary_pooled']['sign_p_two_sided']:.4f})" if w else
                          "NO WINNER — pooled votes do not separate the arms")
    return out


def ext_spend_so_far(exclude: str | None = None) -> int:
    """Chat attempts across BOTH the original trial and E1. The ceiling is a total (§14.1),
    so a new module must not be able to reset it."""
    total = rt.spend_so_far()
    for arm in EXT_ARMS:
        if arm == exclude:
            continue
        p = ext_playbooks_art(arm)
        if p.exists():
            total += int(json.loads(p.read_text(encoding="utf-8-sig")).get(
                "calls_used", 0))
    return total


# ======================================================================================
# stages
# ======================================================================================

def _load_pilot() -> list[str]:
    ev = json.loads(rt.PBV_EVIDENCE.read_text(encoding="utf-8-sig"))
    return list(ev["pilot"])


def stage_select(arm: str) -> None:
    """Route (again, free) and select 50 pairs for the 6 NEW topics only."""
    from calibration import layer_b_arms as lb
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map
    from calibration.layer_bc_arms import (_load_cached, build_pairs, corpus_sha,
                                           install_embedder_shim, prewarm, taxonomy_sha)
    from calibration.scenario_playbook_trial import select_evidence
    from preprocessing import segmenter
    from shared.scenario_vectors import scenario_text

    rt._no_clobber(ext_evidence_art(arm))
    rt._no_clobber(ext_route_art(arm))

    tax_art, scenario_map = rt._load_taxonomy()
    man, texts, parsed_old, parsed_new = rt._anchors()
    pairs = (build_pairs("recordings", "s0", "a0", parsed=parsed_old)
             + build_pairs("recordings_pull_keep", "s0", "a0", parsed=parsed_new))

    fallbacks = rt.ModeFallbackCounter().install()
    mode = rt.install_scenario_vector_mode(rt.ARM_MODE[arm])
    print(f"[E1 arm {arm}] scenario_vector_mode={mode}, router={rt.ARM_ROUTER[arm]}",
          flush=True)
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    shim = install_embedder_shim(rt.WIDTH)
    diag = rt._route(arm, pairs, scenario_map, tax_art["rows"],
                     tax_art.get("identity", {}), texts, parsed_old + parsed_new)
    fallbacks.assert_clean(mode)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)
    counts = {k: len(by_key.get(k, []))
              for k, v in scenario_map.items() if v["is_coachable"]}

    # THE FROZEN PICK RULE, RE-DERIVED (never trusted from the literals alone).
    pilot = _load_pilot()
    ctrl_ranking = json.loads(rt.evidence_art(CONTROL).read_text(
        encoding="utf-8-sig"))["ranking"]
    r1_ranking = json.loads(rt.evidence_art("r1").read_text(
        encoding="utf-8-sig"))["ranking"]
    verify_pick_rule(ctrl_ranking, r1_ranking, pilot)
    # THE ACTUAL DRIFT CHECK (audit finding 6): this run re-routed the corpus from scratch, so
    # its counts must reproduce the original trial's persisted ranking for this arm exactly.
    # If routing were non-reproducible, E1's documents would be built on a different
    # substrate from the original's while the packets mixed both.
    persisted = ctrl_ranking if arm == CONTROL else r1_ranking
    drift = {k: (persisted.get(k), counts.get(k)) for k in set(persisted) | set(counts)
             if persisted.get(k) != counts.get(k)}
    if drift:
        raise SystemExit(
            f"ROUTING DRIFT on arm {arm!r}: {len(drift)} scenario(s) routed differently than "
            f"the original trial recorded, e.g. {dict(list(drift.items())[:3])}. E1's "
            f"documents would rest on a different substrate from the originals they are "
            f"packeted against. Halt.")
    print(f"[E1] pick rule verified; routed counts reproduce the original trial exactly; "
          f"6 new topics = {list(EXT_SCENARIOS)}", flush=True)

    acct_old, _ = account_map("recordings")
    acct_new, _ = account_map("recordings_pull_keep")
    if not acct_old or not acct_new:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    pools, empty = {}, []
    for key in EXT_SCENARIOS:
        pool, no_acct, no_clause = build_pool(by_key.get(key, []), acct,
                                              segmenter.segment_into_clauses)
        if not pool:
            empty.append(key)
        pools[key] = (pool, no_acct, no_clause)
    if empty:
        print(f"\n!! EMPTY EVIDENCE POOL under arm {arm!r} for {empty} — DISQUALIFIED\n",
              flush=True)

    all_texts = sorted({p["unit_text"] for pool, _, _ in pools.values() for p in pool})
    _, missing = _load_cached(all_texts, rt.WIDTH)
    n_fetched = 0
    if missing:
        from calibration.trial_pool_unit_gemini import embed_cached
        n_fetched = len(missing)
        if n_fetched > rt.TOPUP_CEILING:
            raise SystemExit(f"TOP-UP CEILING: {n_fetched} uncached selection vectors "
                             f"(> {rt.TOPUP_CEILING}) — HALT; ask the operator.")
        print(f"[top-up] {n_fetched} uncached selection vector(s), fetching...", flush=True)
        embed_cached(sorted(missing), 20)
        _, still = _load_cached(all_texts, rt.WIDTH)
        if still:
            raise SystemExit(f"ABORT: {len(still)} unit text(s) STILL uncached")

    per_scenario = {}
    for key in EXT_SCENARIOS:
        pool, no_acct, no_clause = pools[key]
        if not pool:
            per_scenario[key] = {"routed_pairs": counts.get(key, 0), "pool_accounted": 0,
                                 "excluded_no_account": no_acct,
                                 "excluded_no_clause": no_clause,
                                 "accounts_in_pool": 0, "accounts_selected": 0,
                                 "selected": []}
            continue
        mat, _ = _load_cached([p["unit_text"] for p in pool], rt.WIDTH)
        if mat is None:
            raise SystemExit(f"ABORT: cache miss after top-up for {key!r}")
        idx = select_evidence(pool, mat, N_EVIDENCE_MAX,
                             min(ACCT_FLOOR, len({p["account"] for p in pool})))
        sel = [dict(pool[i]) for i in idx]
        per_scenario[key] = {
            "routed_pairs": counts.get(key, 0), "pool_accounted": len(pool),
            "excluded_no_account": no_acct, "excluded_no_clause": no_clause,
            "accounts_in_pool": len({p["account"] for p in pool}),
            "accounts_selected": len({s["account"] for s in sel}),
            "routed_pair_ids": sorted(p["pair_id"] for p in by_key.get(key, [])),
            "selected": sel}
        print(f"  [{key[:44]:<44}] pool {len(pool):>4} -> {len(sel)} selected, "
              f"{per_scenario[key]['accounts_selected']} accounts", flush=True)

    short = {k: len(per_scenario[k]["selected"]) for k in EXT_SCENARIOS
             if len(per_scenario[k]["selected"]) < N_EVIDENCE_MAX}
    if short:
        print(f"\n!! VOLUME SHORTFALL under arm {arm!r}: {short} (each must be "
              f"{N_EVIDENCE_MAX}). This arm CANNOT synthesize. HALT and ask.\n", flush=True)

    ident = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "pid": os.getpid(), "seed": SEED, "arm": arm, "taxonomy": rt.TAXONOMY,
             "scenario_vector_mode": mode, "router": rt.ARM_ROUTER[arm],
             "pool_sha": man["pool_sha"], "corpus_sha": corpus_sha(pairs),
             "taxonomy_sha": taxonomy_sha(scenario_map),
             "taxonomy_sha_invariant": rt.taxonomy_identity_sha(scenario_map),
             "spec": "2026-08-19-routing-playbook-ab-design.md §14", "extension": "E1"}
    ext_route_art(arm).write_text(json.dumps(
        {"identity": ident, "n_pairs": len(pairs), "routing_diag": diag,
         "embedder_texts_served": shim.get("texts"), "routed_counts": counts},
        indent=1, ensure_ascii=False), encoding="utf-8")
    ext_evidence_art(arm).write_text(json.dumps(
        {"identity": {**ident, "topup_fetched": n_fetched}, "ranking": counts,
         "ext_scenarios": list(EXT_SCENARIOS), "volume_shortfall": short,
         "empty_pools": empty, "per_scenario": per_scenario},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] {ext_evidence_art(arm).name} written. ZERO chat calls, "
          f"{n_fetched} embedding top-ups, ZERO Postgres writes.")
    print(f"E1 SELECT COMPLETE ({arm})", flush=True)


def stage_synthesize(arm: str) -> None:
    from calibration.adjudication_ab import save_checkpoint
    from calibration.trial_gateway import GatewayClient

    ep = ext_evidence_art(arm)
    if not ep.exists():
        raise SystemExit(f"run --select --arm {arm} first")
    ev = json.loads(ep.read_text(encoding="utf-8-sig"))
    if ev.get("empty_pools"):
        raise SystemExit(f"arm {arm!r} routes ZERO pairs to {ev['empty_pools']} — "
                         f"DISQUALIFIED; refusing to spend.")
    if ev.get("volume_shortfall"):
        raise SystemExit(f"arm {arm!r} VOLUME SHORTFALL {ev['volume_shortfall']} — a thinner "
                         f"document would put volume in the read alongside routing. "
                         f"Refusing to spend; ask the operator.")
    _, scenario_map = rt._load_taxonomy()

    state = (json.loads(ext_playbooks_art(arm).read_text(encoding="utf-8-sig"))
             if ext_playbooks_art(arm).exists() else
             {"identity": {**ev["identity"],
                           "started_at": datetime.datetime.now().isoformat(
                               timespec="seconds"),
                           "pid": os.getpid(), "model": rt.RT_CHAT_MODEL,
                           "reasoning_effort": rt.RT_REASONING,
                           "max_tokens": rt.RT_MAX_TOKENS,
                           "temperature": CHAT_TEMPERATURE, "no_cache": True,
                           "prompts": "pilot_verbatim_identical_to_the_original_trial"},
              "calls_used": 0, "documents": {}})

    def save() -> None:
        save_checkpoint(ext_playbooks_art(arm), state)

    other = ext_spend_so_far(exclude=arm)
    print(f"[budget] {other} attempt(s) spent elsewhere (original trial + other E1 arm); "
          f"this arm has {state['calls_used']}; TOTAL ceiling {EXT_BUDGET}", flush=True)

    gw = GatewayClient(max_retries=1, timeout=rt.RT_TIMEOUT)

    def call(prompt: str, label: str) -> dict:
        last: Exception | None = None
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            if other + state["calls_used"] >= EXT_BUDGET:
                save()
                raise SystemExit(f"HARD STOP: {other + state['calls_used']} chat attempts "
                                 f"total (ceiling {EXT_BUDGET}). Ask the operator.")
            state["calls_used"] += 1
            save()
            t0 = time.time()
            try:
                parsed, usage = gw.chat_json(prompt, model=rt.RT_CHAT_MODEL,
                                             temperature=CHAT_TEMPERATURE,
                                             max_tokens=rt.RT_MAX_TOKENS, no_cache=True,
                                             reasoning_effort=rt.RT_REASONING)
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": True,
                     "model": rt.RT_CHAT_MODEL, "reasoning": rt.RT_REASONING,
                     "seconds": round(time.time() - t0, 1), "usage": usage})
                save()
                return parsed
            except Exception as e:      # noqa: BLE001
                last = e
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": False,
                     "seconds": round(time.time() - t0, 1), "error": str(e)[:300]})
                save()
                print(f"  [{label}] attempt {attempt} failed: {str(e)[:160]}", flush=True)
                time.sleep(4)
        raise SystemExit(f"{label}: {ATTEMPTS_PER_CALL} attempts failed; last: {last}")

    for scen in EXT_SCENARIOS:
        doc_id = f"{scen}::real"
        if doc_id in state["documents"]:
            print(f"[skip] {doc_id} already synthesized", flush=True)
            continue
        evidence = ev["per_scenario"][scen]["selected"]
        header = scenario_header_text(scenario_map[scen])
        batches = [evidence[i:i + BATCH_MAX] for i in range(0, len(evidence), BATCH_MAX)]
        print(f"[synth {arm}] {doc_id}: {len(evidence)} pairs, {len(batches)} map + 1 "
              f"reduce (arm calls: {state['calls_used']})", flush=True)
        maps = []
        for bi, batch in enumerate(batches):
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                out = call(map_prompt(header, batch), f"{doc_id}/map{bi}.{attempt}")
                try:
                    validate_map(out)
                    break
                except ValueError as e:
                    print(f"  [{doc_id}/map{bi}] schema reject: {e}", flush=True)
                    if attempt == ATTEMPTS_PER_CALL:
                        raise SystemExit(f"{doc_id}/map{bi}: never met the schema")
            maps.append(out)
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            doc = call(reduce_prompt(header, maps, [e["trigger_text"] for e in evidence]),
                       f"{doc_id}/reduce{attempt}")
            try:
                validate_playbook(doc)
                break
            except ValueError as e:
                print(f"  [{doc_id}] schema reject: {e}", flush=True)
                # DIAGNOSTIC ONLY, no behaviour change (rt has this; it was trimmed here and
                # the first real failure was consequently unreadable). `validate_playbook`
                # names the offending move but not WHICH of its five conditions failed, and
                # three identical rejects on one move are undebuggable from the message
                # alone. The rejected document is also persisted so it can be inspected
                # after the run instead of being lost with the process.
                for m in (doc.get("key_moves") or []):
                    mev = m.get("evidence")
                    n_ev = len(mev) if isinstance(mev, list) else "MISSING"
                    bad_cit = ([i for i, c in enumerate(mev) if not _cit_ok(c)]
                               if isinstance(mev, list) else "-")
                    print(f"    move {str(m.get('name', ''))[:42]!r}: "
                          f"name={bool(str(m.get('name', '')).strip())} "
                          f"crit={bool(str(m.get('criterion', '')).strip())} "
                          f"n_ev={n_ev} bad_citations={bad_cit}", flush=True)
                print(f"    doc-level: n_moves={len(doc.get('key_moves') or [])} "
                      f"arc={len(doc.get('arc') or [])} "
                      f"checks={len(doc.get('layer_d_checks') or [])} "
                      f"sig={bool(str(doc.get('situation_signature', '')).strip())}",
                      flush=True)
                state.setdefault("rejected", []).append(
                    {"doc_id": doc_id, "attempt": attempt, "error": str(e)[:200],
                     "playbook": doc})
                save()
                if attempt == ATTEMPTS_PER_CALL:
                    raise SystemExit(f"{doc_id}: reduce never met the schema")
        state["documents"][doc_id] = {"scenario": scen, "arm": arm,
                                      "n_evidence": len(evidence), "playbook": doc}
        save()
        print(f"  -> ok ({len(doc['key_moves'])} moves)", flush=True)

    print(f"\nE1 SYNTHESIS COMPLETE ({arm}): {len(state['documents'])} documents, "
          f"{state['calls_used']} attempts this arm, "
          f"{other + state['calls_used']}/{EXT_BUDGET} total.", flush=True)


def _load_ext(arm: str) -> tuple[dict, dict]:
    ep, pp = ext_evidence_art(arm), ext_playbooks_art(arm)
    if not (ep.exists() and pp.exists()):
        raise SystemExit(f"need {ep.name} and {pp.name}")
    ev = json.loads(ep.read_text(encoding="utf-8-sig"))
    pb = json.loads(pp.read_text(encoding="utf-8-sig"))
    if len(pb.get("documents", {})) != len(EXT_SCENARIOS):
        raise SystemExit(f"{pp.name} holds {len(pb.get('documents', {}))} documents, "
                         f"expected {len(EXT_SCENARIOS)} — resume --synthesize first")
    return ev, pb


def new_topic_divergence() -> dict:
    """G-D over the 6 NEW topics, using the ORIGINAL harness's own functions.

    §14.1 carried over selection, prompts, model, snap and G-F but not the divergence gate,
    and E1 implemented none (audit finding 8). A new topic whose two arms select nearly the
    same 50 pairs cannot be resolved by any read, so buying and reading it adds coin-flip
    votes to the pooled primary. Reported here — free — rather than left invisible. It is a
    DIAGNOSTIC in E1, not a spend gate: the frozen §14.1 topic set may not be narrowed after
    the fact, so what it earns is honest interpretation, not a smaller bill.
    """
    evs = {a: json.loads(ext_evidence_art(a).read_text(encoding="utf-8-sig"))
           for a in EXT_ARMS}
    rows = [rt.divergence_row(evs[CONTROL]["per_scenario"], evs["r1"]["per_scenario"], s)
            for s in EXT_SCENARIOS]
    v = rt.gd_verdict(rows)
    below = [r["scenario"] for r in rows if r["changed"] < rt.GD_CHANGED_MIN]
    return {"per_scenario": rows, "n_qualifying": v["n_qualifying"],
            "changed_min": rt.GD_CHANGED_MIN, "below_bar": below,
            "note": "DIAGNOSTIC, not a gate, in E1 (see new_topic_divergence); a topic below "
                    "the bar contributes votes no read can resolve"}


def stage_snap(arm: str) -> None:
    rt._no_clobber(ext_snapped_art(arm))
    ev, pb = _load_ext(arm)
    from calibration.playbook_snap_trial import SNAP_MIN_SCORE
    out = {"identity": {"generated_at": datetime.datetime.now().isoformat(
                            timespec="seconds"), "seed": SEED, "arm": arm,
                        "snap_min_score": SNAP_MIN_SCORE,
                        "source": ext_playbooks_art(arm).name,
                        "source_calls_used": pb.get("calls_used")},
           "documents": {}}
    for doc_id, rec in sorted(pb["documents"].items()):
        snapped, log = snap_doc(rec["playbook"],
                               ev["per_scenario"][rec["scenario"]]["selected"])
        out["documents"][doc_id] = {**{k: v for k, v in rec.items() if k != "playbook"},
                                    "playbook": snapped, "snap_log": log}
        print(f"  [{doc_id[:52]:<52}] kept {log['kept']:>2} snapped {log['snapped']} "
              f"dropped {log['dropped']} moves_dropped {len(log['dropped_moves'])}"
              f"{'  ** SCHEMA COLLAPSED **' if log['schema_collapsed'] else ''}",
              flush=True)
    ext_snapped_art(arm).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
    print(f"E1 SNAP COMPLETE ({arm})", flush=True)


def stage_pb0(arm: str) -> None:
    rt._no_clobber(ext_pb0_art(arm))
    ev, _ = _load_ext(arm)
    sn = json.loads(ext_snapped_art(arm).read_text(encoding="utf-8-sig"))
    report, n_pass = {}, 0
    for doc_id, rec in sorted(sn["documents"].items()):
        evidence = ev["per_scenario"][rec["scenario"]]["selected"]
        res = pb0_doc(rec["playbook"], evidence)
        if rec["snap_log"]["schema_collapsed"]:
            res = {**res, "pass": False,
                   "failures": res["failures"] + [{"reason": "schema_collapsed",
                                                   "path": "key_moves"}]}
        report[doc_id] = res
        n_pass += bool(res["pass"])
        print(f"  [{doc_id[:52]:<52}] {'PASS' if res['pass'] else 'FAIL':<5} "
              f"{res['n_quotes']:>3}q {len(res['failures'])}bad", flush=True)
    verdict = "PASS" if n_pass == len(sn["documents"]) else "FAIL"
    print(f"\nG-F ({arm}, E1): {n_pass}/{len(sn['documents'])} -> {verdict}")
    ext_pb0_art(arm).write_text(json.dumps(
        {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "arm": arm, "verdict": verdict, "n_pass": n_pass,
         "n_docs": len(sn["documents"]),
         "pb1_resized": {d: pb1_doc_resized(
             r["playbook"], ev["per_scenario"][r["scenario"]]["selected"])
             for d, r in sorted(sn["documents"].items())},
         "per_document": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"E1 PB0/G-F COMPLETE ({arm})", flush=True)


def _all_docs(arm: str) -> dict:
    """Snapped documents for all 11 topics: the original 5 from the primary trial's
    artifacts (read-only) plus E1's 6. Keyed by scenario."""
    out = {}
    for path in (rt.snapped_art(arm), ext_snapped_art(arm)):
        if not path.exists():
            raise SystemExit(f"{path.name} missing")
        for rec in json.loads(path.read_text(encoding="utf-8-sig"))["documents"].values():
            out[rec["scenario"]] = rec["playbook"]
    return out


def stage_build_read(packet: int) -> None:
    if packet not in range(1, N_PACKETS + 1):
        raise SystemExit(f"--packet must be 1..{N_PACKETS}")
    rt._no_clobber(ext_packet_art(packet))
    rt._no_clobber(ext_key_art(packet))
    for arm in EXT_ARMS:
        for p in (rt.pb0_art(arm), ext_pb0_art(arm)):
            if not p.exists():
                raise SystemExit(f"{p.name} missing — G-F gates readability")
            if json.loads(p.read_text(encoding="utf-8-sig"))["verdict"] != "PASS":
                raise SystemExit(f"{p.name} did not PASS G-F; refusing to build a read")

    docs = {arm: _all_docs(arm) for arm in EXT_ARMS}
    topics = ext_topics(_load_pilot())
    # THE ANCHORING GUARD FROM §12.1.1, RESTORED (re-audit finding). A calibration pair that
    # is also a routing topic shows the reader an endorsed control-derived document for that
    # topic and biases the routing item toward the control — the directional half of the
    # original FATAL. Inert on today's data (all four CAL keys exist only in clean2_base),
    # but the topic set is wider now and the guard must not be absent.
    clash = set(rt.CAL_SCENARIOS) & set(topics)
    if clash:
        raise SystemExit(f"calibration scenario(s) {sorted(clash)} are also routing topics — "
                         f"familiarity with an endorsed control-derived document would anchor "
                         f"the routing item toward the control. Refusing to build a read.")
    if not rt.PBS_SNAPPED.exists():
        raise SystemExit(f"{rt.PBS_SNAPPED.name} missing — it holds the calibration pairs")
    mine = topics_for_packet(topics, packet)
    _, scenario_map = rt._load_taxonomy()
    cal_map = rt._cal_scenario_map()
    cal_docs = json.loads(rt.PBS_SNAPPED.read_text(encoding="utf-8-sig"))["documents"]
    ctrl_ranking = json.loads(rt.evidence_art(CONTROL).read_text(
        encoding="utf-8-sig"))["ranking"]
    negs = rt.neg_headers(ctrl_ranking, topics)

    # E1's OWN shuffle stream. `rt.packet_rng` resolves its label against
    # `rt.COMPARISONS` and would raise ValueError on an E1 label — a crash that would have
    # fired only at this stage, i.e. AFTER the entire chat spend (audit finding 1).
    rng = ext_packet_rng(packet)
    items = [{"kind": "ROUTE", "scenario": s, "position": i,
              "treat_side": ext_treatment_side(i, packet)} for i, s in enumerate(mine)]
    items += [{"kind": "CAL", "scenario": s, "real_side": rt.counterbalanced_side(j)}
              for j, s in enumerate(rt.CAL_SCENARIOS)]
    items += [{"kind": "NEG", "neg_index": n} for n in range(N_NEG)]
    rng.shuffle(items)

    neg_pool = [d for arm in EXT_ARMS for d in docs[arm].values() if d.get("key_moves")]
    lines, key_rows = list(rt.ROUTE_PACKET_HEADER), []
    for i, it in enumerate(items, 1):
        if it["kind"] == "NEG":
            head_scen = negs[it["neg_index"]]
            lines += [f"--- ITEM {i} (SINGLE) ---",
                      f"SCENARIO: {head_scen}\n  "
                      f"{scenario_map[head_scen].get('business_description', '')}",
                      "DOCUMENT:"]
            lines += render_doc(build_neg(neg_pool, rng))
            key_rows.append({"item": i, "kind": "NEG", "header_scenario": head_scen})
            lines.append("")
            continue
        scen = it["scenario"]
        info = (cal_map if it["kind"] == "CAL" else scenario_map)[scen]
        head = f"SCENARIO: {scen}\n  {info.get('business_description', '')}"
        if it["kind"] == "ROUTE":
            t, b = docs["r1"][scen], docs[CONTROL][scen]
            side = it["treat_side"]
            a_doc, b_doc = (t, b) if side == "A" else (b, t)
            key_rows.append({"item": i, "kind": "ROUTE", "scenario": scen,
                             "treat_arm": "r1", "base_arm": CONTROL, "treat_side": side,
                             "is_new_topic": scen in EXT_SCENARIOS,
                             "n_moves_treat": len(t["key_moves"]),
                             "n_moves_base": len(b["key_moves"])})
        else:
            real = cal_docs[f"{scen}::real"]["playbook"]
            plc = cal_docs[f"{scen}::placebo"]["playbook"]
            side = it["real_side"]
            a_doc, b_doc = (real, plc) if side == "A" else (plc, real)
            key_rows.append({"item": i, "kind": "CAL", "scenario": scen,
                             "real_side": side, "source": rt.PBS_SNAPPED.name,
                             "n_moves_real": len(real["key_moves"]),
                             "n_moves_placebo": len(plc["key_moves"])})
        lines += [f"--- ITEM {i} (PAIR) ---", head, "DOCUMENT A:"]
        lines += render_doc(a_doc)
        lines.append("DOCUMENT B:")
        lines += render_doc(b_doc)
        lines.append("")
    lines += ["=" * 96,
              "REQUIRED ANSWER FORMAT — one JSON object, nothing else:",
              '{"1": {"choice": "A", "apply_A": ["APPLY", ...], "apply_B": ["VAGUE", ...]},',
              ' "2": {"answer": "NO"}, ...}',
              "PAIR items take choice/apply_A/apply_B (one rating per KEY MOVE, display",
              "order); SINGLE items take answer. Every item number must appear."]
    ext_packet_art(packet).write_text("\n".join(lines), encoding="utf-8")
    ext_key_art(packet).write_text(json.dumps(
        {"seed": SEED, "extension": "E1", "packet": packet,
         "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "readers_required": EXT_READERS, "counterbalanced": True,
         "composition": dict(Counter(r["kind"] for r in key_rows)),
         "items": key_rows}, indent=1), encoding="utf-8")
    print(f"wrote {ext_packet_art(packet).name} ({len(items)} items, "
          f"{len(mine)} routing pairs) and {ext_key_art(packet).name}")
    print(f"topics in packet {packet}: {mine}")
    print(f"E1 PACKET {packet} READY", flush=True)


def stage_score(round_: int | None = None) -> None:
    # A VOID packet is re-dispatched to a SCOPED round (§12.2.1/§14.1). Without threading the
    # round through, `--score` re-globs the unscoped namespace and silently re-scores the
    # DISCARDED readers, recording a second VOID the replacement pool never cast (audit
    # finding 5 — the same defect the sibling harness was fixed for).
    out_path = (EXT_REPORT if round_ is None
                else ARTIFACTS_DIR / f"rte_round{round_}_report.json")
    rt._no_clobber(out_path)
    keys, jds, rounds_used = [], [], {}
    for i in range(1, N_PACKETS + 1):
        if not ext_key_art(i).exists():
            raise SystemExit(f"run --build-read --packet {i} first")
        keys.append(json.loads(ext_key_art(i).read_text(encoding="utf-8-sig")))
        # RESOLVE THE ROUND PER PACKET (re-audit finding): only the VOIDed packet is
        # re-dispatched, so demanding round-N files for BOTH packets makes a partial
        # re-dispatch unscoreable and pushes the operator toward re-reading a packet whose
        # round-1 pool was perfectly valid.
        files = sorted(ARTIFACTS_DIR.glob(ext_judgments_glob(i, round_))) if round_ else []
        used_round = round_ if files else None
        if not files:
            files = sorted(ARTIFACTS_DIR.glob(ext_judgments_glob(i)))
        rounds_used[i] = used_round or 1
        if len(files) > EXT_READERS:
            raise SystemExit(
                f"packet {i}: {len(files)} files match "
                f"{ext_judgments_glob(i, round_)!r} but a round holds {EXT_READERS}. Two "
                f"dispatches are mixed in one namespace; scoring the first {EXT_READERS} in "
                f"filename order would silently re-score a discarded round. Re-dispatch as "
                f"rte_p{i}_round2_judgments_r*.json and pass --round 2.")
        if not files:
            raise SystemExit(f"packet {i}: no judgment files matching "
                             f"{ext_judgments_glob(i, round_)!r}")
        print(f"[score] packet {i}, round {rounds_used[i]}: {len(files)} file(s): "
              + ", ".join(f.name for f in files))
        jds.append([json.loads(f.read_text(encoding="utf-8-sig")) for f in files])

    res = score_ext(keys, jds)
    pp = res["primary_pooled"]
    print("=" * 88)
    for p in res["packets"]:
        gp = p.get("g_p") or {}
        ag = p.get("agreement") or {}
        ss = p.get("side_share") or {}
        print(f"packet {p['packet']}: {p['verdict']} | valid {p['n_valid']}/"
              f"{EXT_READERS} | G-P {gp.get('n_real_preferred', '-')}/"
              f"{len(gp.get('calibration_pairs', {}) or {})} | reader agreement "
              f"{ag.get('mean_rate', float('nan')):.2f} | A-share(route) "
              f"{ss.get('pooled_a_share_route', float('nan')):.2f}"
              f"{'  ** IDENTICAL READERS: ' + str(ag.get('identical_pairs')) if ag.get('identical_pairs') else ''}")
    print(f"PRIMARY (pooled): r1 {pp['votes_treatment']} – {pp['votes_base']} control "
          f"of {pp['n_votes']} votes | raw sign p={pp['sign_p_two_sided']:.4f} | "
          f"correlation-adjusted p="
          f"{pp.get('sign_p_correlation_adjusted', float('nan')):.4f} "
          f"(deff~{pp.get('design_effect_approx', 1.0):.2f}, "
          f"n_eff~{pp.get('n_votes_effective', pp['n_votes'])}) | alpha {EXT_ALPHA}")
    if pp.get("winner_suppressed"):
        print(f"  winner SUPPRESSED: {pp['winner_suppressed']}")
    st = res["secondary_topic_count"]
    print(f"SECONDARY (topics, never decisive): r1 preferred in "
          f"{st['topics_r1_preferred']}/{st['n_topics']}, p={st['binomial_p_two_sided']:.4f}")
    print(f"E1 VERDICT: {res['verdict']}")
    print("The ORIGINAL 5-topic result (3/5, pooled 7–8) stands as the primary "
          "pre-registered outcome; E1 is a labelled post-hoc-motivated re-test (§14.2).")
    print("=" * 88)
    out_path.write_text(json.dumps(
        {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "extension": "E1", "spec": "§14", "taxonomy": rt.TAXONOMY,
         "read_round_requested": round_ or 1, "read_round_per_packet": rounds_used,
         "topics": ext_topics(_load_pilot()), "new_topics": list(EXT_SCENARIOS),
         "original_result_untouched": {"topics_r1_preferred": 3, "n_topics": 5,
                                       "pooled": [7, 8], "verdict": "NO WIN",
                                       "source": rt.report_art("r1").name},
         "new_topic_divergence": (new_topic_divergence()
                                  if all(ext_evidence_art(a).exists() for a in EXT_ARMS)
                                  else None),
         **res}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path.name}")
    print("E1 SCORED", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default=None)
    p.add_argument("--packet", type=int, default=None)
    p.add_argument("--round", type=int, default=None, dest="round_",
                   help="re-dispatch round for --score after a VOID packet (>= 2); readers "
                        "write rte_p<N>_round<R>_judgments_r*.json")
    p.add_argument("--select", action="store_true")
    p.add_argument("--synthesize", action="store_true")
    p.add_argument("--snap", action="store_true")
    p.add_argument("--pb0", action="store_true")
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()
    per_arm = (a.select, a.synthesize, a.snap, a.pb0)
    if any(per_arm) and not a.arm:
        raise SystemExit("--arm is required for --select/--synthesize/--snap/--pb0")
    if a.build_read and a.packet is None:
        raise SystemExit("--packet is required for --build-read")
    if sum(map(bool, [*per_arm, a.build_read, a.score])) > 1:
        raise SystemExit("run exactly one stage per process (the keyphrases-style register "
                         "install mutates a process-wide singleton)")
    if a.select:
        stage_select(_check_arm(a.arm))
    elif a.synthesize:
        stage_synthesize(_check_arm(a.arm))
    elif a.snap:
        stage_snap(_check_arm(a.arm))
    elif a.pb0:
        stage_pb0(_check_arm(a.arm))
    elif a.build_read:
        stage_build_read(a.packet)
    elif a.score:
        stage_score(a.round_)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
