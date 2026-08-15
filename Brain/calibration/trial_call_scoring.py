#!/usr/bin/env python3
"""The pre-registered gate for call-level scoring. ZERO Postgres writes.

Spec: docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md

Runs three of the gate's four checks; check 4 (read the flips) is a human read of the samples
this prints and persists.

*** CHECK 1 -- DISCRIMINATION, AND THE ONE CONSTRUCTION THAT MATTERS ***
The moment-level trial swapped the RUBRIC between arms. Here the scenario's identity is what
drives `did_occur`, so swapping the whole scenario would conflate two questions: the unrelated
arm would answer "this never happened" and score nothing, and the comparison would degenerate
into a did_occur test wearing a discrimination test's clothes.

So the arms hold the scenario IDENTITY fixed -- same key, same description, same trigger turns,
so `did_occur` is true on both sides -- and swap ONLY the criteria, to a deranged partner's.
Exactly one thing differs, and it is the thing under test.

*** THE SAMPLING UNIT CHANGED, AND SKIPPING THAT WOULD MAKE THIS QUIETLY WRONG ***
trial_grader_inputs.py samples leakage-clean RESPONSES. A whole-call scorer needs whole CALLS,
so both the sample and the holdout move up a level: a call is clean for a scenario when it
contributed NO primary pair to it, meaning none of its content entered that scenario's Layer C
clause pool. The spec names this explicitly because reusing the response-level sampler would
score a whole call while claiming a per-response holdout.

CHECK 2 -- quote verification. Free, mechanical, no model and no human: does the cited quote
appear at or near the cited turn? This is the specific risk a large context window introduces
and the reason `turn` is mandatory rather than decorative.

CHECK 3 -- the did_occur null. Ask about a scenario with NO pairs at all in that call. It must
say no. This is a coarser relative of a question that failed twice here, so it is gated rather
than assumed.

PRE-REGISTERED BARS (spec, before anything was built):
  check 1   >= 70% of decided scenarios favour the matched criteria, p < 0.05
  check 2   >= 95% of cited quotes verifiable
  check 3   >= 90% of absent scenarios correctly declined

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
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "call_scoring_trial.json"
CKPT = ARTIFACTS_DIR / "call_scoring_trial_ckpt.json"
PIN_MODEL = "gemini-3.1-flash-lite"
BAR_SIGN, BAR_QUOTE, BAR_NULL = 0.70, 0.95, 0.90


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
    print(f"  wins {st['wins']}  losses {st['losses']}  ties {st['ties']}   "
          f"win share {st['win_share']:.1%}  p={st['p_value']:.2g}")
    print(f"  bar >= {BAR_SIGN:.0%} and p<0.05  ->  {'PASS' if ok1 else 'FAIL'}")
    if st["ties"] >= st["decided"]:
        print("  ! TIES >= DECIDED -- most pairs score identically on both sides, so this\n"
              "    check is uninformative however the rest fall.")

    q = P["check2"]
    ok2 = q["rate"] >= BAR_QUOTE if q["checked"] else False
    print(f"\nCHECK 2  quote verification (free, mechanical)")
    print(f"  {q['verified']}/{q['checked']} cited quotes found at/near their turn "
          f"= {q['rate']:.1%}" if q["checked"] else "  no quotes cited")
    print(f"  bar >= {BAR_QUOTE:.0%}  ->  {'PASS' if ok2 else 'FAIL'}")
    fab = [f for f in q["failures"] if not f["found_elsewhere"]]
    if fab:
        print(f"  of {len(q['failures'])} failures, {len(fab)} appear NOWHERE in the "
              f"transcript (fabricated, not misattributed):")
        for f in fab[:5]:
            print(f"    [{f['scenario_key']} {f['milestone_id']} turn {f['turn']}] "
                  f"{f['quote'][:90]}")

    n = P["check3"]
    ok3 = n["declined"] / n["asked"] >= BAR_NULL if n["asked"] else False
    print(f"\nCHECK 3  did_occur null (scenarios with no pairs in that call)")
    print(f"  correctly declined {n['declined']}/{n['asked']} = "
          f"{n['declined']/max(n['asked'],1):.1%}")
    print(f"  bar >= {BAR_NULL:.0%}  ->  {'PASS' if ok3 else 'FAIL'}")
    for s in n["accepted_samples"][:4]:
        print(f"    accepted (should not have): {s['scenario_key']} -- {s['reason'][:90]}")

    print(f"\n{'=' * 86}\nGATE: {'PASS' if (ok1 and ok2 and ok3) else 'FAIL'} "
          f"(check1 {'ok' if ok1 else 'no'}, check2 {'ok' if ok2 else 'no'}, "
          f"check3 {'ok' if ok3 else 'no'})")
    print("=" * 86)

    print("\nCHECK 4 -- READ THESE. Criteria credited under whole-call scoring, with the")
    print("turn the evidence came from. A wider window is only a gain if these are earned.")
    for s in P["samples"][:10]:
        print(f"\n  [{s['scenario_key']}] {s['verdict']} @ turn {s['turn']}")
        print(f"    criterion: {s['description'][:110]}")
        print(f"    quote:     {s['quote'][:130]}")


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
    from calibration.score_naren_ceiling import derange
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
    partner, method = derange(keys, v @ v.T,
                              load_tuning().layer_a.merge_cosine_threshold,
                              random.Random(a.seed))
    if partner is None:
        raise SystemExit(f"no partner mapping: {method}")

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
        present = by_call[fn][:a.per_call]
        absent = [k for k in rng.sample(keys, 8)
                  if (fn, k) not in secondary and fn not in primary_calls.get(k, set())][:1]

        def block(key, rubric_key, trig):
            return ScenarioBlock(
                scenario_key=key, description=scen[key]["business_description"],
                rubric={"milestones": scen[rubric_key]["milestones"]},
                trigger_turns=[(ti or 0, t) for ti, t in trig[:4]],
                benchmark_response="\n\n".join(bench.get(rubric_key, [])[:2]))

        # matched / unrelated share the scenario IDENTITY; only the criteria differ.
        m_blocks = [block(k, k, tr) for k, tr in present]
        u_blocks = [block(k, partner[k], tr) for k, tr in present]
        n_blocks = [block(k, k, []) for k in absent]

        res = {}
        for arm, blocks in (("matched", m_blocks), ("unrelated", u_blocks),
                            ("null", n_blocks)):
            if not blocks:
                continue
            out, warns = call_scoring.score_call(
                turns, blocks, cfg, scenarios_per_request=3,
                model=a.model, fallback_models=())
            res[arm] = out
            if warns:
                res.setdefault("warnings", []).extend(warns)
        res["quote_check"] = call_scoring.verify_quotes(res.get("matched", []), turns)
        done[fn] = res
        CKPT.write_text(json.dumps({"picked": picked, "done": done}, default=str),
                        encoding="utf-8")
        print(f"  [{idx}/{len(picked)}] {fn[:20]} scored", flush=True)

    pairs, samples = [], []
    qc = {"checked": 0, "verified": 0, "failures": []}
    null = {"asked": 0, "declined": 0, "accepted_samples": []}
    for fn, res in done.items():
        m = {r["scenario_key"]: r for r in res.get("matched", [])}
        u = {r["scenario_key"]: r for r in res.get("unrelated", [])}
        for k in m:
            if k in u and m[k]["did_occur"] and u[k]["did_occur"]:
                pairs.append((weighted(m[k]["milestones"]), weighted(u[k]["milestones"])))
            for ms in m[k]["milestones"]:
                if ms["verdict"] != "miss" and ms.get("quote"):
                    samples.append({"scenario_key": k, "verdict": ms["verdict"],
                                    "turn": ms.get("turn"), "quote": ms["quote"],
                                    "description": ms["milestone_description"]})
        c = res.get("quote_check", {})
        qc["checked"] += c.get("checked", 0)
        qc["verified"] += c.get("verified", 0)
        qc["failures"].extend(c.get("failures", []))
        for r in res.get("null", []):
            null["asked"] += 1
            if not r["did_occur"]:
                null["declined"] += 1
            else:
                null["accepted_samples"].append(
                    {"scenario_key": r["scenario_key"], "reason": r["occurrence_reason"]})
    qc["rate"] = qc["verified"] / qc["checked"] if qc["checked"] else float("nan")

    P = {"n_calls": len(done), "n_pairs": len(pairs), "model": a.model, "seed": a.seed,
         "smoke": bool(a.smoke), "partner_method": method,
         "check1": sign_test(pairs), "check2": qc, "check3": null,
         "samples": samples, "raw": done}
    OUT.write_text(json.dumps(P, indent=1, default=float), encoding="utf-8")
    report(P)
    print(f"\nwrote {OUT}\nNOTHING was written to Postgres.")


if __name__ == "__main__":
    main()
