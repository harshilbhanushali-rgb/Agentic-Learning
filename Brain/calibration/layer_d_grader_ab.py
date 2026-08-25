"""C2: the Layer D grader head-to-head -- can the instrument tell matched from unrelated?

Pre-registration: docs/findings/layer-d-redesign.md (§C2, gates frozen 2026-08-20;
sharpened 2026-08-24 after the C3 pre/post settled that the per-moment absolute unit,
not check wording, suppresses rates -- so the checks arm runs WITH its partial tier and
the pairwise arm is the a-priori favourite).

NOT PRODUCTION. Nothing in v1/, v2/, shared/, preprocessing/ or layer_d/ imports this.
Zero DB writes (read-only session); ZERO writes to move_events -- results land in
artifacts/layer_d_grader_ab.json only.

THE CONSTRUCTION (ground truth by design, symmetric across arms):
  Population: CSM moments detected by the PRODUCTION path (arm-e segmentation,
  sink-relative admit) whose scenario is one of the 5 pbq gradability playbooks,
  response_outcome='csm', non-empty reply. Stratified up to --per-scenario per key.

  CHECKS arm  : each moment graded against its MATCHED playbook and against a
                SIZE-MATCHED UNRELATED playbook (same move count where possible --
                the call-level trial's v1/v2 retraction was an arm-size confound;
                never again). Score = weighted (hit=1, partial=0.5) over scored
                moves. Win = matched score > unrelated score.
  PAIRWISE arm: each moment's client trigger answered by TWO Naren replies -- the
                top-cosine pair from the MATCHED scenario vs the top-cosine pair
                from the UNRELATED scenario -- judged on the matched playbook's
                moves, both orders, position-consistent verdicts only. Ground
                truth: the matched exemplar should win. Win = majority of scored
                moves prefer matched.

  Both arms: k runs per judgment (--k, default 3); a moment's outcome is the
  majority across runs; run disagreement -> tie, excluded from the win count but
  REPORTED (it is the noise floor).

GATES (frozen; any failure -> stop and bring the operator options):
  G-C2a  win share >= 0.70 over decided (non-tie) moments, binomial p < 0.05
         against 0.5, per arm. Decision: highest win-share arm passing G-C2a+b
         ships layer_d.grader_arm; tie -> checks (cheaper, names the behavior).
  G-C2b  checks arm only: >= 95% of credited quotes verify (the fabrication gate).
  G-C2c  report-only: per-arm tie/disagreement rate (noise floor), pairwise
         swap-inconsistency rate, unscored rates.

Spend at the defaults (60 moments, k=3): checks ~2*ceil(60/6)*3 = 60 requests;
pairwise ~60*2*3 = 360 requests; total ~420 plus resamples. Embeddings are C0
cache hits except the exemplar-trigger vectors (paid once, cached).

Usage (from Brain/, VPN up):
    python calibration/layer_d_grader_ab.py                 # the bill, zero spend
    python calibration/layer_d_grader_ab.py --spend         # run both arms
    python calibration/layer_d_grader_ab.py --load artifacts/layer_d_grader_ab.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from config import load_config  # noqa: E402
from ego_trap import csm_registry  # noqa: E402
from ego_trap.transcript_parser import parse_transcript  # noqa: E402
from layer_d import graders, signals  # noqa: E402
from layer_d.pipeline import gateway_chat, live_playbooks_flat, playbook_move_specs  # noqa: E402
from shared import relative_match, storage  # noqa: E402
from shared.tuning import get_tuning  # noqa: E402

BRAIN = Path(__file__).resolve().parent.parent
RECORDINGS = BRAIN / "csm_recordings"
ARTIFACT = ARTIFACTS_DIR / "layer_d_grader_ab.json"

PBQ_KEYS = (
    "application_volume_and_prioritization",
    "ats_integration_and_api_mapping",
    "downstream_activation_and_cost_metrics",
    "landing_page_and_conversion_setup",
    "niche_talent_scarcity_and_budget_reallocation",
)


# ------------------------------------------------------------------ pure helpers

def size_matched_partner(key: str, playbooks: dict[str, dict]) -> str:
    """The unrelated playbook for `key`: same move count where possible, else the
    closest count; ties broken alphabetically. Deterministic, no randomness."""
    n = len(playbooks[key]["key_moves"])
    others = sorted(k for k in playbooks if k != key)
    return min(others, key=lambda k: (abs(len(playbooks[k]["key_moves"]) - n), k))


def weighted_score(verdicts: list[graders.MoveVerdict]) -> float | None:
    """(hit + 0.5*partial) / scored, or None when nothing scored."""
    scored = [v for v in verdicts if v.verdict != "unscored"]
    if not scored:
        return None
    w = sum(1.0 if v.verdict == "hit" else 0.5 if v.verdict == "partial" else 0.0
            for v in scored)
    return w / len(scored)


def majority_outcome(outcomes: list[str]) -> str:
    """'win' / 'loss' / 'tie' by strict majority across k runs; no majority -> 'tie'."""
    counts = Counter(o for o in outcomes if o in ("win", "loss"))
    if not counts:
        return "tie"
    top, n = counts.most_common(1)[0]
    return top if n * 2 > sum(counts.values()) else "tie"


def binom_p_at_least(k: int, n: int) -> float:
    """One-sided P[X >= k] for X~Binom(n, 0.5). Exact, stdlib only."""
    if n == 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)


def gate_report(decided: int, wins: int) -> dict:
    share = wins / decided if decided else float("nan")
    p = binom_p_at_least(wins, decided)
    return {"decided": decided, "wins": wins, "win_share": round(share, 4),
            "binomial_p": round(p, 6),
            "G_C2a_pass": bool(decided and share >= 0.70 and p < 0.05)}


# ------------------------------------------------------------------ collection

def collect_moments(cfg, playbooks: dict[str, dict], per_scenario: int,
                    roster: frozenset[str]) -> list[dict]:
    """CSM moments on the 5 pbq scenarios via the PRODUCTION detection path,
    INCLUDING production's fail-closed speaker gate (audit finding 3: without it,
    colleague chatter becomes 'client' moments, and the contamination is
    arm-asymmetric -- junk deflates the checks arm's decided-N while pairwise,
    which never reads the CSM reply, sails through). Deterministic: stems in
    filename order, first-N per scenario."""
    d = get_tuning().layer_d
    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = on")
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    conn.close()

    scorer = signals.SignalScorer(scenario_map, margin=d.similarity_relative_margin,
                                  cap=d.max_scenarios_per_signal)
    mapping = csm_registry.load_mapping(RECORDINGS / "mapping.csv")
    out: dict[str, list[dict]] = {k: [] for k in playbooks}
    excluded = 0
    for stem in sorted(p.stem for p in RECORDINGS.glob("*.txt")):
        if stem not in mapping:
            continue
        if all(len(v) >= per_scenario for v in out.values()):
            break
        _, csm_name = mapping[stem]
        turns = parse_transcript(str(RECORDINGS / f"{stem}.txt"),
                                 csm_name.strip().lower(), cfg.joveo_speakers_lower)
        if signals.unverified_speakers(turns, roster):
            excluded += 1
            continue
        for m in signals.detect_moments(turns, stem, scorer, arm=d.segmentation_arm):
            if (m.scenario_key in playbooks and m.response_outcome == "csm"
                    and m.response_text and len(out[m.scenario_key]) < per_scenario):
                out[m.scenario_key].append({
                    "moment_id": m.moment_id, "scenario_key": m.scenario_key,
                    "trigger_text": m.trigger_text, "response_text": m.response_text,
                })
    print(f"[speaker gate] {excluded} transcript(s) excluded (unverified client speakers)")
    return [m for k in sorted(out) for m in out[k]]


def exemplar_index(conn, keys: tuple[str, ...]):
    """scenario_key -> (pairs, trigger_matrix) for top-cosine exemplar lookup."""
    from preprocessing import embedder
    index = {}
    for key in keys:
        pairs = [p for p in storage.get_pairs_for_scenario_multilabel(conn, key)
                 if p["response_text"].strip()]
        pairs = sorted(pairs, key=lambda p: (not p["is_primary"], p["pair_id"]))[:120]
        mat = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
        index[key] = (pairs, np.asarray(mat))
    return index


def top_exemplar(index, key: str, trigger_vec: np.ndarray) -> dict:
    pairs, mat = index[key]
    sims = relative_match.cosine_sims(trigger_vec.reshape(1, -1), mat)[0]
    best = pairs[int(np.argmax(sims))]
    return {"trigger_text": best["trigger_text"], "response_text": best["response_text"]}


# ------------------------------------------------------------------------ main

def flush(results: dict) -> None:
    """Audit finding 2: every paid verdict is persisted as soon as it exists.
    no_cache=True means a lost result is a re-paid result; the artifact IS the cache."""
    ARTIFACT.write_text(json.dumps(results, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true")
    ap.add_argument("--load", default="")
    ap.add_argument("--per-scenario", type=int, default=12)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="continue from the existing artifact: moments with both "
                         "arm outcomes recorded are skipped, partial ones redo")
    ap.add_argument("--allow-unverified-speakers", action="store_true")
    args = ap.parse_args()

    if args.load:
        report(json.loads(Path(args.load).read_text(encoding="utf-8")))
        return

    cfg = load_config()
    d = get_tuning().layer_d

    roster_path = RECORDINGS / "client_speakers.txt"
    if roster_path.exists():
        from layer_d.pipeline import load_client_roster
        roster = load_client_roster(roster_path)
    elif args.allow_unverified_speakers:
        roster = None
        print("!! running WITHOUT the speaker gate (fail-open classification) -- "
              "population may contain colleague chatter as 'client' moments")
    else:
        raise SystemExit(f"{roster_path} not found. Provide it or pass "
                         f"--allow-unverified-speakers (biases the arms; see docstring).")

    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = on")
    playbooks = {p["scenario_key"]: p for p in live_playbooks_flat(conn)
                 if p["scenario_key"] in PBQ_KEYS}
    assert len(playbooks) == 5, sorted(playbooks)

    moments = collect_moments(cfg, playbooks, args.per_scenario,
                              roster if roster is not None else frozenset())
    if roster is None:
        print("  (speaker gate SKIPPED by --allow-unverified-speakers)")
    n = len(moments)
    by_scen: dict[str, list[dict]] = {}
    for m in moments:
        by_scen.setdefault(m["scenario_key"], []).append(m)
    # Audit finding 1: checks batches per (scenario, side, run) exactly like
    # production's grade_moment_set, so the bill and the measured instrument both
    # match what would ship.
    n_checks = 2 * args.k * sum(-(-len(v) // graders.CHECKS_BATCH_SIZE)
                                for v in by_scen.values())
    n_pair = 2 * args.k * n
    print(f"[population] {n} moments over {len(by_scen)} scenarios "
          f"(target {args.per_scenario}/scenario)")
    print(f"[bill] checks ~{n_checks} requests, pairwise ~{n_pair} requests, "
          f"k={args.k}; plus resamples")
    if not args.spend:
        conn.close()
        print("Zero spend. Re-run with --spend to run both arms.")
        return

    chat = gateway_chat()
    partner = {k: size_matched_partner(k, playbooks) for k in playbooks}
    print(f"[partners] {partner}")
    ex_index = exemplar_index(conn, tuple(playbooks))
    from preprocessing import embedder
    conn.close()

    results = {"identity": {
        "model": d.grader_model, "effort": d.grader_reasoning_effort, "k": args.k,
        "per_scenario": args.per_scenario, "n_moments": n,
        "partners": partner, "contract": "checks_v2_partial_tier",
    }, "moments": []}
    done: dict[str, dict] = {}
    if args.resume and ARTIFACT.exists():
        prior = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        for rec in prior.get("moments", []):
            if rec.get("checks", {}).get("outcome") and rec.get("pairwise", {}).get("outcome"):
                done[rec["moment_id"]] = rec
        print(f"[resume] {len(done)} completed moment(s) carried over")
    recs: dict[str, dict] = {}
    for m in moments:
        if m["moment_id"] in done:
            recs[m["moment_id"]] = done[m["moment_id"]]
        else:
            recs[m["moment_id"]] = {
                "moment_id": m["moment_id"], "scenario_key": m["scenario_key"],
                "unrelated": partner[m["scenario_key"]],
                "checks": {"runs": []}, "pairwise": {"runs": []},
            }
    results["moments"] = [recs[m["moment_id"]] for m in moments]

    # ---- checks arm: batched per (scenario, side, run), production-shaped
    for key in sorted(by_scen):
        todo = [m for m in by_scen[key] if not recs[m["moment_id"]]["checks"].get("outcome")]
        if not todo:
            continue
        pb, un_pb = playbooks[key], playbooks[partner[key]]
        per_run: list[dict[str, dict[str, dict]]] = []   # run -> moment_id -> side -> outcome
        for _ in range(args.k):
            run_scores: dict[str, dict[str, dict]] = {m["moment_id"]: {} for m in todo}
            for label, book in (("matched", pb), ("unrelated", un_pb)):
                graded = graders.grade_checks_batch(
                    chat, book["scenario_key"], book.get("situation_signature", ""),
                    playbook_move_specs(book), todo, d.quote_verify_min_overlap)
                for g in graded:
                    run_scores[g.moment_id][label] = {
                        "score": weighted_score(g.verdicts),
                        "verdicts": [(v.move_id, v.verdict, v.reason) for v in g.verdicts],
                    }
            per_run.append(run_scores)
        for m in todo:
            rec = recs[m["moment_id"]]
            for run_scores in per_run:
                out = run_scores[m["moment_id"]]
                ms, us = out["matched"]["score"], out["unrelated"]["score"]
                out["result"] = ("tie" if ms is None or us is None or ms == us
                                 else "win" if ms > us else "loss")
                rec["checks"]["runs"].append(out)
            rec["checks"]["outcome"] = majority_outcome(
                [r["result"] for r in rec["checks"]["runs"]])
        flush(results)
        print(f"  [checks] {key}: "
              f"{Counter(recs[m['moment_id']]['checks']['outcome'] for m in by_scen[key])}")

    # ---- pairwise arm: matched vs unrelated exemplar on matched moves, k runs
    trig_vecs = np.asarray(embedder.embed_query_matrix(
        [m["trigger_text"] for m in moments]))
    for i, m in enumerate(moments):
        rec = recs[m["moment_id"]]
        if rec["pairwise"].get("outcome"):
            continue
        key = m["scenario_key"]
        pb = playbooks[key]
        matched_ex = top_exemplar(ex_index, key, trig_vecs[i])
        unrelated_ex = top_exemplar(ex_index, partner[key], trig_vecs[i])
        for _ in range(args.k):
            g = graders.grade_pairwise(
                chat, key, pb.get("situation_signature", ""),
                playbook_move_specs(pb),
                {"moment_id": m["moment_id"], "trigger_text": m["trigger_text"],
                 "response_text": matched_ex["response_text"]},
                {"trigger_text": m["trigger_text"],
                 "response_text": unrelated_ex["response_text"]})
            scored = [v for v in g.verdicts if v.verdict != "unscored"]
            # 'hit' = the moment-arg (the MATCHED exemplar) won in BOTH orders
            wins = sum(1 for v in scored if v.verdict == "hit")
            losses = sum(1 for v in scored if v.verdict == "miss")
            rec["pairwise"]["runs"].append({
                "verdicts": [(v.move_id, v.verdict, v.reason) for v in g.verdicts],
                "result": ("tie" if not scored or wins == losses
                           else "win" if wins > losses else "loss"),
            })
        rec["pairwise"]["outcome"] = majority_outcome(
            [r["result"] for r in rec["pairwise"]["runs"]])
        flush(results)
        print(f"  [pairwise {i + 1}/{n}] {m['moment_id']}: "
              f"{rec['pairwise']['outcome']} (checks={rec['checks'].get('outcome')})")

    flush(results)
    print(f"[artifact] {ARTIFACT}")
    report(results)


def report(results: dict) -> None:
    print(f"\n=== C2 GRADER HEAD-TO-HEAD ({results['identity']}) ===")
    for arm in ("checks", "pairwise"):
        outcomes = Counter(m[arm]["outcome"] for m in results["moments"])
        wins, losses, ties = outcomes["win"], outcomes["loss"], outcomes["tie"]
        g = gate_report(wins + losses, wins)
        print(f"\n[{arm}] win {wins} / loss {losses} / tie {ties}")
        print(f"  G-C2a: win_share={g['win_share']} over {g['decided']} decided, "
              f"p={g['binomial_p']} -> {'PASS' if g['G_C2a_pass'] else 'FAIL'}")
        flips = sum(1 for m in results["moments"]
                    if len({r["result"] for r in m[arm]["runs"]}) > 1)
        print(f"  G-C2c noise: {flips}/{len(results['moments'])} moments flipped "
              f"across k runs")
    # G-C2b: quote verification among checks credits (refusals are 'quote_unverified')
    credits = refused = 0
    for m in results["moments"]:
        for r in m["checks"]["runs"]:
            for side in ("matched", "unrelated"):
                for _mv, verdict, reason in r[side]["verdicts"]:
                    if verdict in ("hit", "partial"):
                        credits += 1
                    elif reason == "quote_unverified":
                        refused += 1
    total_claims = credits + refused
    rate = credits / total_claims if total_claims else float("nan")
    print(f"\n[checks] G-C2b quote verification: {credits}/{total_claims} claims "
          f"verified ({rate:.1%}) -> {'PASS' if total_claims and rate >= 0.95 else 'FAIL'}")
    print("\nDecision rule (pre-registered): highest win-share arm passing "
          "G-C2a (+G-C2b for checks) ships layer_d.grader_arm; tie -> checks.")
    print("[NO production file modified; NO move_events row written.]")


if __name__ == "__main__":
    main()
