#!/usr/bin/env python3
"""G-S1/2/3: can the SAY arm tell matched from unrelated? (pre-registered gates)

Pre-registration: docs/findings/layer-d-say-arm.md §5, frozen 2026-08-28 BEFORE this
harness existed. Mirrors calibration/layer_d_grader_ab.py's C2 construction exactly,
so the say arm's number is comparable to pairwise's 77.1% and checks' 53.9%.

NOT PRODUCTION. Zero DB writes, zero move_events rows; results land in
artifacts/layer_d_say_ab.json only. No read-only session GUC (the Neon pooler leak,
docs/GOTCHAS.md 2026-08-26) -- this script simply never writes.

THE CONSTRUCTION (ground truth by design):
  Population: the SAME population rule as C2 -- CSM moments detected by the
  PRODUCTION path (arm-e segmentation, sink-relative admit, fail-closed speaker
  gate) on the 5 pbq scenarios, response_outcome='csm', non-empty reply,
  stratified up to --per-scenario per key.

  SAY arm: each moment graded against its MATCHED playbook's SAY-routed moves and
  against a SAY-SIZE-MATCHED UNRELATED playbook's SAY-routed moves (same say-move
  count where possible -- the arm-size confound rule, kept). Score = weighted
  (specific=1, generic=0.5, no=0) over scored moves. Win = matched > unrelated.
  k runs, majority outcome; run disagreement -> tie (reported: the noise floor).

GATES (frozen):
  G-S1  win share >= 0.70 over decided (non-tie) moments, binomial p < 0.05.
  G-S2  >= 95% of specific/generic claims carry a programmatically verified quote.
  G-S3  tier spread on MATCHED-side scored verdicts: no single tier > 90%, and
        'specific' fires at least once -- else the gradient did not materialize
        and the arm is binary-with-extra-steps.

Spend at defaults (12/scenario, k=3): 2 sides x 3 runs x ceil(12/6)=2 batches x
5 scenarios = ~60 requests, plus resamples.

Usage (from Brain/, VPN up):
    python calibration/layer_d_say_ab.py                # the bill, zero spend
    python calibration/layer_d_say_ab.py --spend        # run the arm
    python calibration/layer_d_say_ab.py --spend --resume
    python calibration/layer_d_say_ab.py --load artifacts/layer_d_say_ab.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.layer_d_grader_ab import (  # noqa: E402  -- the C2 rules, reused
    PBQ_KEYS, binom_p_at_least, collect_moments, majority_outcome, weighted_score,
)
from config import load_config  # noqa: E402
from layer_d import graders, move_classes  # noqa: E402
from layer_d.pipeline import gateway_chat, live_playbooks_flat  # noqa: E402
from shared import storage  # noqa: E402
from shared.tuning import get_tuning  # noqa: E402

BRAIN = Path(__file__).resolve().parent.parent
RECORDINGS = BRAIN / "csm_recordings"
ARTIFACT = ARTIFACTS_DIR / "layer_d_say_ab.json"


def say_size_matched_partner(key: str, say_specs: dict[str, list[dict]]) -> str:
    """The unrelated playbook for `key`, matched on SAY-move count (the C2
    size-confound rule, applied to the move set this arm actually grades)."""
    n = len(say_specs[key])
    others = sorted(k for k in say_specs if k != key and say_specs[k])
    if not others:
        raise SystemExit(f"no partner with SAY moves available for {key}")
    return min(others, key=lambda k: (abs(len(say_specs[k]) - n), k))


def flush(results: dict) -> None:
    ARTIFACT.write_text(json.dumps(results, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true")
    ap.add_argument("--load", default="")
    ap.add_argument("--per-scenario", type=int, default=12)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--allow-unverified-speakers", action="store_true")
    args = ap.parse_args()

    if args.load:
        report(json.loads(Path(args.load).read_text(encoding="utf-8")))
        return

    cfg = load_config()
    # Neon DNS workaround (same as layer_d_act_type_packet.py): literal pooler IP
    # as hostaddr, host kept in the URL for TLS SNI + SCRAM. Config is frozen.
    if "hostaddr=" not in cfg.database_url:
        import dataclasses
        cfg = dataclasses.replace(
            cfg, database_url=cfg.database_url
            + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39")
    d = get_tuning().layer_d

    roster_path = RECORDINGS / "client_speakers.txt"
    if roster_path.exists():
        from layer_d.pipeline import load_client_roster
        roster = load_client_roster(roster_path)
    elif args.allow_unverified_speakers:
        roster = None
        print("!! running WITHOUT the speaker gate (fail-open classification)")
    else:
        raise SystemExit(f"{roster_path} not found. Provide it or pass "
                         f"--allow-unverified-speakers.")

    classes = move_classes.load_move_classes()

    conn = storage.get_connection(cfg.database_url)
    playbooks = {p["scenario_key"]: p for p in live_playbooks_flat(conn)
                 if p["scenario_key"] in PBQ_KEYS}
    conn.close()
    assert len(playbooks) == 5, sorted(playbooks)

    say_specs = {k: move_classes.say_moves(pb, classes)
                 for k, pb in playbooks.items()}
    for k in sorted(say_specs):
        print(f"[say moves] {k}: {len(say_specs[k])} of "
              f"{len(playbooks[k]['key_moves'])}")
    graded_keys = {k: v for k, v in say_specs.items() if v}
    if len(graded_keys) < 2:
        raise SystemExit("fewer than 2 pbq playbooks have SAY moves -- the "
                         "matched-vs-unrelated construction needs a partner pool")

    moments = collect_moments(cfg, {k: playbooks[k] for k in graded_keys},
                              args.per_scenario,
                              roster if roster is not None else frozenset())
    n = len(moments)
    by_scen: dict[str, list[dict]] = {}
    for m in moments:
        by_scen.setdefault(m["scenario_key"], []).append(m)
    n_req = 2 * args.k * sum(-(-len(v) // graders.CHECKS_BATCH_SIZE)
                             for v in by_scen.values())
    print(f"[population] {n} moments over {len(by_scen)} scenarios "
          f"(target {args.per_scenario}/scenario)")
    print(f"[bill] say ~{n_req} requests, k={args.k}; plus resamples")
    if not args.spend:
        print("Zero spend. Re-run with --spend to run the arm.")
        return

    chat = gateway_chat()
    partner = {k: say_size_matched_partner(k, say_specs) for k in graded_keys}
    print(f"[partners] {partner}")

    results = {"identity": {
        "model": d.grader_model, "effort": d.grader_reasoning_effort, "k": args.k,
        "per_scenario": args.per_scenario, "n_moments": n, "partners": partner,
        "classes_fp": move_classes.classes_fingerprint(classes),
        # v2 (design doc §5b): the generic tier credits a concrete ELEMENT of a
        # bundled criterion -- the checks partial-tier lesson, applied.
        "contract": "say_v2_element_credit",
    }, "moments": []}
    done: dict[str, dict] = {}
    if args.resume and ARTIFACT.exists():
        prior = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        for rec in prior.get("moments", []):
            if rec.get("say", {}).get("outcome"):
                done[rec["moment_id"]] = rec
        print(f"[resume] {len(done)} completed moment(s) carried over")
    recs: dict[str, dict] = {}
    for m in moments:
        recs[m["moment_id"]] = done.get(m["moment_id"]) or {
            "moment_id": m["moment_id"], "scenario_key": m["scenario_key"],
            "unrelated": partner[m["scenario_key"]], "say": {"runs": []},
        }
    results["moments"] = [recs[m["moment_id"]] for m in moments]

    # Batched per (scenario, side, run), production-shaped -- the C2 audit rule:
    # the bill and the measured instrument must both match what would ship.
    for key in sorted(by_scen):
        todo = [m for m in by_scen[key] if not recs[m["moment_id"]]["say"].get("outcome")]
        if not todo:
            continue
        sides = (("matched", playbooks[key], say_specs[key]),
                 ("unrelated", playbooks[partner[key]], say_specs[partner[key]]))
        per_run: list[dict[str, dict[str, dict]]] = []
        for _ in range(args.k):
            run_scores: dict[str, dict[str, dict]] = {m["moment_id"]: {} for m in todo}
            for label, book, specs in sides:
                graded = graders.grade_say_batch(
                    chat, book["scenario_key"], book.get("situation_signature", ""),
                    specs, todo, d.quote_verify_min_overlap)
                for g in graded:
                    run_scores[g.moment_id][label] = {
                        "score": weighted_score(g.verdicts),
                        "verdicts": [(v.move_id, v.verdict, v.reason)
                                     for v in g.verdicts],
                    }
            per_run.append(run_scores)
        for m in todo:
            rec = recs[m["moment_id"]]
            for run_scores in per_run:
                out = run_scores[m["moment_id"]]
                ms, us = out["matched"]["score"], out["unrelated"]["score"]
                out["result"] = ("tie" if ms is None or us is None or ms == us
                                 else "win" if ms > us else "loss")
                rec["say"]["runs"].append(out)
            rec["say"]["outcome"] = majority_outcome(
                [r["result"] for r in rec["say"]["runs"]])
        flush(results)
        print(f"  [say] {key}: "
              f"{Counter(recs[m['moment_id']]['say']['outcome'] for m in by_scen[key])}")

    flush(results)
    print(f"[artifact] {ARTIFACT}")
    report(results)


_RANK = {"hit": 3, "partial": 2, "miss": 1}


def call_level_outcomes(results: dict) -> Counter:
    """G-S1b (design doc §5b): the SAME graded runs re-aggregated at the arm's
    shipping unit. Per (scenario, call), per run index, per side: best verdict per
    move across the call's moments (production's rollup), weighted over moves;
    win = matched > unrelated; call outcome = majority across runs."""
    by_call: dict[tuple[str, str], list[dict]] = {}
    for m in results["moments"]:
        call = m["moment_id"].rsplit(":", 1)[0]
        by_call.setdefault((m["scenario_key"], call), []).append(m)

    outcomes: Counter = Counter()
    for (_scen, _call), moments in sorted(by_call.items()):
        k = max(len(m["say"]["runs"]) for m in moments)
        results_per_run: list[str] = []
        for i in range(k):
            side_score: dict[str, float | None] = {}
            for side in ("matched", "unrelated"):
                best: dict[str, int] = {}
                for m in moments:
                    if i >= len(m["say"]["runs"]):
                        continue
                    for mv, verdict, _reason in m["say"]["runs"][i][side]["verdicts"]:
                        r = _RANK.get(verdict)
                        if r is not None:
                            best[mv] = max(best.get(mv, 0), r)
                if best:
                    side_score[side] = sum(
                        {3: 1.0, 2: 0.5, 1: 0.0}[r] for r in best.values()) / len(best)
                else:
                    side_score[side] = None
            ms, us = side_score["matched"], side_score["unrelated"]
            results_per_run.append("tie" if ms is None or us is None or ms == us
                                   else "win" if ms > us else "loss")
        outcomes[majority_outcome(results_per_run)] += 1
    return outcomes


def report(results: dict) -> None:
    print(f"\n=== SAY-ARM MATCHED-VS-UNRELATED ({results['identity']}) ===")
    outcomes = Counter(m["say"]["outcome"] for m in results["moments"])
    wins, losses, ties = outcomes["win"], outcomes["loss"], outcomes["tie"]
    decided = wins + losses
    share = wins / decided if decided else float("nan")
    p = binom_p_at_least(wins, decided)
    print(f"\n[say, per MOMENT] win {wins} / loss {losses} / tie {ties}")
    print(f"  G-S1: win_share={share:.4f} over {decided} decided, p={p:.6f} -> "
          f"{'PASS' if decided and share >= 0.70 and p < 0.05 else 'FAIL'}"
          f"  (diagnostic once §5b applies: an absolute arm at a 0-5% per-moment"
          f" base rate ties 0-0 regardless of its real discrimination)")
    flips = sum(1 for m in results["moments"]
                if len({r["result"] for r in m["say"]["runs"]}) > 1)
    print(f"  noise: {flips}/{len(results['moments'])} moments flipped across k runs")

    co = call_level_outcomes(results)
    cw, cl, ct = co["win"], co["loss"], co["tie"]
    cd = cw + cl
    cshare = cw / cd if cd else float("nan")
    cp = binom_p_at_least(cw, cd)
    print(f"\n[say, per CALL -- the shipping unit] win {cw} / loss {cl} / tie {ct}")
    print(f"  G-S1b (LICENSING GATE, §5b): win_share={cshare:.4f} over {cd} decided "
          f"calls, p={cp:.6f} -> "
          f"{'PASS' if cd and cshare >= 0.70 and cp < 0.05 else 'FAIL'}")

    # G-S2: quote verification among specific/generic claims (refusals carry
    # reason='quote_unverified'; verified credits landed as hit/partial).
    credits = refused = 0
    tier = Counter()
    for m in results["moments"]:
        for r in m["say"]["runs"]:
            for side in ("matched", "unrelated"):
                for _mv, verdict, reason in r[side]["verdicts"]:
                    if verdict in ("hit", "partial"):
                        credits += 1
                    elif reason == "quote_unverified":
                        refused += 1
                    if side == "matched" and verdict != "unscored":
                        tier[verdict] += 1
    total_claims = credits + refused
    rate = credits / total_claims if total_claims else float("nan")
    print(f"\n  G-S2 quote verification: {credits}/{total_claims} claims verified "
          f"({rate:.1%}) -> {'PASS' if total_claims and rate >= 0.95 else 'FAIL'}")

    scored = sum(tier.values())
    print(f"\n  G-S3 tier spread (matched side, scored verdicts): "
          + "  ".join(f"{k}={v} ({v / scored:.0%})" for k, v in sorted(tier.items()))
          if scored else "\n  G-S3: NOTHING SCORED")
    if scored:
        top_share = max(tier.values()) / scored
        specific_fires = tier.get("hit", 0) >= 1
        print(f"  max tier share {top_share:.0%} (bar: <= 90%), specific fired: "
              f"{specific_fires} -> "
              f"{'PASS' if top_share <= 0.90 and specific_fires else 'FAIL'}")
    print("\n[NO production file modified; NO move_events row written.]")


if __name__ == "__main__":
    main()
