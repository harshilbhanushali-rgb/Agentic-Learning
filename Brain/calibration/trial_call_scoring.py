#!/usr/bin/env python3
"""The pre-registered gate for call-level scoring. ZERO Postgres writes.

Spec: docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md

*** REVISION 2. v1 of this gate FAILED all three checks on 2026-08-15, and the audit found
that two of the three failures were partly self-inflicted. What changed:

  did_occur is GONE, and with it check 3. It declined only 20% of scenarios that never
    happened, having already failed at two finer grains. Over-including candidate scenarios
    is therefore unsafe and selection falls back to matching alone -- the fallback the design
    pre-registered for exactly this outcome.
  CHECK 2 NOW VERIFIES EVERY CREDIT IN BOTH ARMS. v1 checked 26 of 239 -- only the matched
    arm's partial hits -- because the scorer blanked the quote on a full hit. The reported
    "80.8% verified" was measured on the biased 11%.
  EVIDENCE MAY BE DISTRIBUTED. v1 demanded a verbatim single-turn quote for every credit; a
    milestone satisfied by the shape of a conversation has no such quote, so the prompt was
    inviting the fabrication it was then measured for. "across_turns" evidence is now legal
    and is verified differently: >= 2 cited turns must exist and be CSM turns.

*** CHECK 1 -- DISCRIMINATION, AND THE ONE CONSTRUCTION THAT MATTERS ***
The arms hold the scenario IDENTITY fixed -- same key, same description, same trigger turns --
and swap ONLY the criteria, to a deranged partner's. Exactly one thing differs, and it is the
thing under test. Swapping the whole scenario would instead measure whether the model notices
a topic mismatch, which is a different (and now abandoned) question.

*** THE SAMPLING UNIT CHANGED, AND SKIPPING THAT WOULD MAKE THIS QUIETLY WRONG ***
trial_grader_inputs.py samples leakage-clean RESPONSES. A whole-call scorer needs whole CALLS,
so both the sample and the holdout move up a level: a call is clean for a scenario when it
contributed NO primary pair to it, meaning none of its content entered that scenario's Layer C
clause pool. The spec names this explicitly because reusing the response-level sampler would
score a whole call while claiming a per-response holdout.

CHECK 2 -- evidence verification. Free, mechanical, no model and no human. Every full_hit and
partial_hit must be locatable: an "at_turn" credit's quote must appear at or near the turn it
claims, and an "across_turns" credit must name >= 2 real CSM turns. A credit with no usable
evidence FAILS -- the prompt says such a credit should have been a miss, and this is what
makes that claim enforceable. It is also the anti-inflation mechanism: what cannot be located
cannot be credited.

PRE-REGISTERED BARS (unchanged from the design; the check-3 bar is retired with the check):
  check 1   >= 70% of decided scenarios favour the matched criteria, p < 0.05
  check 2   >= 95% of ALL credits, in BOTH arms, locatable in the transcript

CREDIT LEVEL is reported but deliberately NOT gated. v1 scored W 0.56 against moment mode's
0.078 and that inflation is what destroyed separation -- but high credit with VERIFIED
evidence would be a good outcome (reps doing more than a 3-turn window can see), and high
credit with unverifiable evidence is precisely what check 2 catches. Gating on the level
itself would presume the answer.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/trial_call_scoring.py --smoke
    ..\\.venv\\Scripts\\python.exe calibration/trial_call_scoring.py --calls 20
    ..\\.venv\\Scripts\\python.exe calibration/trial_call_scoring.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "call_scoring_trial.json"
CKPT = ARTIFACTS_DIR / "call_scoring_trial_ckpt.json"
PIN_MODEL = "gemini-3.1-flash-lite"
BAR_SIGN, BAR_QUOTE = 0.70, 0.95


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--calls", type=int, default=20)
    p.add_argument("--per-call", type=int, default=2, help="scenarios asked about per call")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--model", default=PIN_MODEL)
    p.add_argument("--smoke", action="store_true", help="3 calls. Path test; NOT interpretable.")
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--load", action="store_true")
    return p.parse_args()


def weighted(ms: list[dict]) -> float:
    if not ms:
        return 0.0
    h = sum(1 for m in ms if m["verdict"] == "full_hit")
    p = sum(1 for m in ms if m["verdict"] == "partial_hit")
    return (h + 0.5 * p) / len(ms)


def size_matched_partner(keys: list[str], sizes: dict[str, int], sim, threshold: float,
                         rng: random.Random) -> tuple[dict[str, str], str]:
    """Pair each scenario with an unrelated one carrying the SAME NUMBER OF CRITERIA.

    *** WHY THIS REPLACED score_naren_ceiling.derange HERE, measured 2026-08-15. ***
    A plain derangement gave the matched arm 5.08 criteria per pair and the unrelated arm
    3.64, because this trial samples calls that are leakage-clean for a scenario -- which
    requires the scenario to have secondary-label pairs, i.e. the big prominent ones with
    more milestones -- while their partners are drawn from all 82. And fewer criteria scores
    HIGHER (corr(n criteria, W) = -0.146), so the comparison was biased against the matched
    arm. That is what produced a 35% win share, and restricting to the 10 accidentally
    equal-sized pairs reversed the direction (0.538 vs 0.454). The v1 and v2 discrimination
    numbers are both confounded by this and neither may be cited.

    Exact size matching makes both arms' denominators identical, so W is directly comparable
    and the confound is removed by construction rather than adjusted for afterwards. A
    scenario with no exact-size, content-dissimilar partner gets NO partner and is dropped
    from the trial -- a near-match would reintroduce a smaller version of the same bias.

    Content dissimilarity is still required: cosine < layer_a.merge_cosine_threshold, an
    already-calibrated knob, so this adds no tuning key.
    """
    idx = {k: i for i, k in enumerate(keys)}
    out: dict[str, str] = {}
    for k in keys:
        cands = [j for j in keys
                 if j != k and sizes[j] == sizes[k] and sim[idx[k]][idx[j]] < threshold]
        if cands:
            out[k] = rng.choice(cands)
    return out, "exact_size_matched"


def sign_test(pairs: list[tuple[float, float]]) -> dict:
    wins = sum(1 for m, u in pairs if m > u)
    losses = sum(1 for m, u in pairs if m < u)
    ties = sum(1 for m, u in pairs if m == u)
    decided = wins + losses
    p = float("nan")
    if decided:
        from math import comb
        tail = sum(comb(decided, i) for i in range(min(wins, losses) + 1)) / 2 ** decided
        p = min(1.0, 2 * tail)
    return {"wins": wins, "losses": losses, "ties": ties, "decided": decided,
            "win_share": wins / decided if decided else float("nan"), "p_value": p}


def report(P: dict) -> None:
    print("\n" + "=" * 86)
    print("CALL-LEVEL SCORING -- PRE-REGISTERED GATE")
    print("=" * 86)
    print(f"  {P['n_calls']} calls, {P['n_pairs']} (call, scenario) pairs, "
          f"model {P['model']}")

    st = P["check1"]
    ok1 = st["win_share"] >= BAR_SIGN and st["p_value"] < 0.05
    print(f"\nCHECK 1  discrimination (same scenario, criteria swapped)")
    # THE CONFOUND GUARD. v1 and v2 both ran with a plain derangement and the arms carried
    # 5.08 vs 3.64 criteria, which alone biased the result. If these are not equal, check 1
    # is not readable and says so instead of printing a number someone will quote.
    cs = P.get("criteria_per_arm", {})
    if cs and abs(cs.get("matched", 0) - cs.get("unrelated", 0)) > 1e-9:
        print(f"  ! ARMS ARE NOT SIZE-MATCHED ({cs['matched']:.2f} vs {cs['unrelated']:.2f} "
              f"criteria/pair). This check is CONFOUNDED and must not be cited.")
    else:
        print(f"  arms size-matched at {cs.get('matched', float('nan')):.2f} criteria/pair "
              f"-- the v1/v2 denominator confound is removed by construction")
    print(f"  wins {st['wins']}  losses {st['losses']}  ties {st['ties']}   "
          f"win share {st['win_share']:.1%}  p={st['p_value']:.2g}")
    print(f"  bar >= {BAR_SIGN:.0%} and p<0.05  ->  {'PASS' if ok1 else 'FAIL'}")
    if st["ties"] >= st["decided"]:
        print("  ! TIES >= DECIDED -- most pairs score identically on both sides, so this\n"
              "    check is uninformative however the rest fall.")

    q = P["check2"]
    ok2 = q["rate"] >= BAR_QUOTE if q["checked"] else False
    print(f"\nCHECK 2  evidence verification -- EVERY credit, both arms (free, mechanical)")
    print(f"  {q['verified']}/{q['checked']} credits locatable in the transcript "
          f"= {q['rate']:.1%}   forms: {q['kinds']}")
    print(f"  bar >= {BAR_QUOTE:.0%}  ->  {'PASS' if ok2 else 'FAIL'}")
    fab = [f for f in q["failures"] if f.get("kind") != "across_turns"
           and not f["found_elsewhere"] and f.get("quote")]
    if fab:
        print(f"  of {len(q['failures'])} failures, {len(fab)} quote words that appear "
              f"NOWHERE in the transcript (fabricated, not misattributed):")
        for f in fab[:5]:
            print(f"    [{f['scenario_key']} {f['milestone_id']} turn {f['turn']}] "
                  f"{f['quote'][:90]}")
    unev = [f for f in q["failures"] if f.get("why") == "no quote or no turn"]
    if unev:
        print(f"  {len(unev)} credits carried NO usable evidence at all -- the prompt says "
              f"those should have been misses.")

    # Reported, NOT gated. High credit with VERIFIED evidence would be a good outcome (reps
    # doing more than the 3-turn window could see); high credit with unverifiable evidence is
    # what check 2 exists to catch. So inflation is context for reading check 1, not a bar.
    print(f"\nCONTEXT  credit levels (moment mode's W is 0.078 -- NOT comparable, the unit "
          f"differs)")
    for arm in ("matched", "unrelated"):
        v = P["verdicts"].get(arm, {})
        print(f"  {arm:<10} W {P['W'].get(arm, float('nan')):.3f}   {v}")

    print(f"\n{'=' * 86}\nGATE: {'PASS' if (ok1 and ok2) else 'FAIL'} "
          f"(check1 {'ok' if ok1 else 'no'}, check2 {'ok' if ok2 else 'no'})")
    print("=" * 86)

    print("\nCHECK 4 -- READ THESE. Credits under whole-call scoring and the evidence given.")
    print("A wider window is only a gain if these are earned, not found by looking hard enough.")
    for s in P["samples"][:12]:
        where = (f"turns {s.get('turns')}" if s.get("kind") == "across_turns"
                 else f"turn {s.get('turn')}")
        print(f"\n  [{s['scenario_key']}] {s['verdict']} ({s.get('kind') or '?'}) @ {where}")
        print(f"    criterion: {s['description'][:110]}")
        if s.get("quote"):
            print(f"    quote:     {s['quote'][:130]}")
        if s.get("pattern"):
            print(f"    pattern:   {s['pattern'][:130]}")


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return

    from config import load_config
    from ego_trap import call_scoring
    from ego_trap.call_scoring import ScenarioBlock
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from preprocessing import embedder
    import psycopg

    cfg = load_config()
    n_calls = 3 if a.smoke else a.calls
    if a.smoke:
        print("SMOKE -- 3 calls. Path test only, numbers NOT interpretable.\n")

    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.scenario_key, s.business_description, s.keyphrases, r.milestones "
                "FROM public.scenarios s JOIN public.rubrics r ON r.scenario_id=s.scenario_id "
                "WHERE s.is_coachable AND jsonb_array_length(r.milestones)>0")
            scen = {k: {"business_description": bd or "", "keyphrases": kp or [],
                        "milestones": ms} for k, bd, kp, ms in cur.fetchall()}
            cur.execute(
                "SELECT p.scenario_key, p.scenario_keys, p.trigger_text, p.response_text, "
                "       c.filename, p.turn_index "
                "FROM public.kb_pairs p JOIN public.calls c ON c.call_id=p.call_id "
                "WHERE length(trim(p.trigger_text))>20")
            primary_calls = defaultdict(set)
            secondary = defaultdict(list)      # (file, key) -> trigger turns
            bench = defaultdict(list)
            for pk, sks, trg, rsp, fn, ti in cur.fetchall():
                if pk in scen:
                    primary_calls[pk].add(fn)
                    bench[pk].append(rsp)
                for k in (sks or []):
                    if k in scen and k != pk:
                        secondary[(fn, k)].append((ti, trg))

    # A call is CLEAN for a scenario when it contributed no primary pair to it -- none of its
    # content entered that scenario's Layer C clause pool, so the rubric cannot describe it.
    clean = [(fn, k, turns) for (fn, k), turns in secondary.items()
             if fn not in primary_calls.get(k, set())]
    by_call = defaultdict(list)
    for fn, k, turns in clean:
        by_call[fn].append((k, turns))
    eligible = sorted(fn for fn, v in by_call.items() if len(v) >= a.per_call)
    print(f"{len(scen)} scenarios with rubrics; {len(eligible)} calls are leakage-clean for "
          f">= {a.per_call} scenarios")

    rng = random.Random(a.seed)
    picked = rng.sample(eligible, min(n_calls, len(eligible)))

    keys = sorted(scen)
    v = embedder.embed_document_matrix([scenario_text(scen[k]) for k in keys])
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-10)
    partner, method = size_matched_partner(
        keys, {k: len(scen[k]["milestones"]) for k in keys}, v @ v.T,
        load_tuning().layer_a.merge_cosine_threshold, random.Random(a.seed))
    matchable = sum(1 for k in keys if partner.get(k))
    print(f"partner mapping: {method}; {matchable}/{len(keys)} scenarios have an "
          f"EXACT size-matched partner")

    done = {}
    if CKPT.exists() and not a.fresh:
        ck = json.loads(CKPT.read_text(encoding="utf-8-sig"))
        if ck.get("picked") == picked:
            done = ck["done"]
            print(f"[resume] {len(done)} calls already scored\n")

    for idx, fn in enumerate(picked, 1):
        if fn in done:
            continue
        path = Path("recordings") / f"{fn}.txt"
        if not path.exists():
            path = Path("recordings") / fn
        if not path.exists():
            print(f"  ! transcript missing for {fn}, skipped")
            continue
        turns_objs = parse_transcript(str(path), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(path)))
        # ROLE, not speaker_raw. The grader must not see who is speaking by name -- a real
        # name is a leak (it can recognise the expert) and the role is what the verdict is
        # actually about. Turn numbering below is 1-based over THIS list, which is the
        # address space every `turn` in a verdict is checked against.
        turns = [(t.role.name, t.text) for t in turns_objs]
        # Only scenarios with an exact size-matched partner can be compared without
        # reintroducing the denominator bias, so the rest are skipped rather than paired
        # approximately.
        present = [(k, tr) for k, tr in by_call[fn] if partner.get(k)][:a.per_call]
        if not present:
            print(f"  [{idx}/{len(picked)}] {fn[:20]} skipped: no size-matched partner")
            done[fn] = {"matched": [], "unrelated": [], "evidence_check": {}}
            continue

        def block(key, rubric_key, trig):
            return ScenarioBlock(
                scenario_key=key, description=scen[key]["business_description"],
                rubric={"milestones": scen[rubric_key]["milestones"]},
                trigger_turns=[(ti or 0, t) for ti, t in trig[:4]],
                benchmark_response="\n\n".join(bench.get(rubric_key, [])[:2]))

        # matched / unrelated share the scenario IDENTITY; only the criteria differ.
        m_blocks = [block(k, k, tr) for k, tr in present]
        u_blocks = [block(k, partner[k], tr) for k, tr in present]

        res = {}
        for arm, blocks in (("matched", m_blocks), ("unrelated", u_blocks)):
            if not blocks:
                continue
            out, warns = call_scoring.score_call(
                turns, blocks, cfg, scenarios_per_request=3,
                model=a.model, fallback_models=())
            res[arm] = out
            if warns:
                res.setdefault("warnings", []).extend(warns)
        # Verify BOTH arms, and every credit in them. v1 verified only the matched arm's
        # partial hits -- 26 of 239 credits, the biased 11%.
        roles = tuple({r for r, _ in turns} & {"NAREN", "CSM", "OTHER_JOVEO"}) or ("NAREN",)
        res["evidence_check"] = {
            arm: call_scoring.verify_evidence(res.get(arm, []), turns, csm_roles=roles)
            for arm in ("matched", "unrelated")}
        done[fn] = res
        CKPT.write_text(json.dumps({"picked": picked, "done": done}, default=str),
                        encoding="utf-8")
        print(f"  [{idx}/{len(picked)}] {fn[:20]} scored", flush=True)

    pairs, samples = [], []
    qc = {"checked": 0, "verified": 0, "failures": [], "kinds": {}}
    verdicts = {"matched": Counter(), "unrelated": Counter()}
    for fn, res in done.items():
        m = {r["scenario_key"]: r for r in res.get("matched", [])}
        u = {r["scenario_key"]: r for r in res.get("unrelated", [])}
        for arm, d in (("matched", m), ("unrelated", u)):
            for r in d.values():
                for ms in r["milestones"]:
                    verdicts[arm][ms["verdict"]] += 1
        for k in m:
            if k in u and m[k]["milestones"] and u[k]["milestones"]:
                pairs.append((weighted(m[k]["milestones"]), weighted(u[k]["milestones"])))
            for ms in m[k]["milestones"]:
                if ms["verdict"] != "miss":
                    samples.append({"scenario_key": k, "verdict": ms["verdict"],
                                    "kind": ms.get("evidence_kind"), "turn": ms.get("turn"),
                                    "turns": ms.get("turns"), "quote": ms.get("quote", ""),
                                    "pattern": ms.get("pattern", ""),
                                    "description": ms["milestone_description"]})
        for arm in ("matched", "unrelated"):
            c = res.get("evidence_check", {}).get(arm, {})
            qc["checked"] += c.get("checked", 0)
            qc["verified"] += c.get("verified", 0)
            qc["failures"].extend(c.get("failures", []))
            for kk, vv in (c.get("kinds") or {}).items():
                qc["kinds"][kk] = qc["kinds"].get(kk, 0) + vv
    qc["rate"] = qc["verified"] / qc["checked"] if qc["checked"] else float("nan")

    def _w(c):
        n = sum(c.values())
        return (c["full_hit"] + 0.5 * c["partial_hit"]) / n if n else float("nan")

    n_m = [len(m[k]["milestones"]) for fn, res in done.items()
           for m in [{r["scenario_key"]: r for r in res.get("matched", [])}] for k in m
           if m[k]["milestones"]]
    n_u = [len(u[k]["milestones"]) for fn, res in done.items()
           for u in [{r["scenario_key"]: r for r in res.get("unrelated", [])}] for k in u
           if u[k]["milestones"]]

    P = {"n_calls": len(done), "n_pairs": len(pairs), "model": a.model, "seed": a.seed,
         "smoke": bool(a.smoke), "partner_method": method,
         "criteria_per_arm": {"matched": float(np.mean(n_m)) if n_m else float("nan"),
                              "unrelated": float(np.mean(n_u)) if n_u else float("nan")},
         "check1": sign_test(pairs), "check2": qc,
         "verdicts": {k: dict(v) for k, v in verdicts.items()},
         "W": {k: _w(v) for k, v in verdicts.items()},
         "samples": samples, "raw": done}
    OUT.write_text(json.dumps(P, indent=1, default=float), encoding="utf-8")
    report(P)
    print(f"\nwrote {OUT}\nNOTHING was written to Postgres.")


if __name__ == "__main__":
    main()
