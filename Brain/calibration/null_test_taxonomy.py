#!/usr/bin/env python3
"""Do the turn-mode coachable scenarios beat a size-matched random null? (free, read-only)

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

THE QUESTION. The finding that started this whole effort is that two thirds of the LIVE
taxonomy is statistically indistinguishable from a random pile of client turns -- 21 of 68
rankable scenarios beat their own size-matched null, and just 1 of 24 posture scenarios did.
The new turn-mode taxonomy has never faced that bar. Everything measured about it so far
(content-free share, blind judges, coherence, account concentration, the Layer D comparison)
is upstream of it.

*** THE SYMMETRY RULE, AND WHY THE OBVIOUS VERSION OF THIS SCRIPT IS WRONG. ***
The obvious run -- score each new scenario on its own HDBSCAN cluster members -- is rigged.
Cluster membership is CHOSEN to be coherent, so it would beat any null by construction, while
production's scenarios are populated by MATCHING (layer_b assigns a turn to its best scenario).
Comparing the two would measure "clustering vs matching", not "taxonomy vs taxonomy" -- the
asymmetric-comparison bug this codebase has hit five times and grown a separate defence for
each time.

The spec pre-registered against this: it retires the 21/68 = 31% figure as a CROSS-UNIT
ARTIFACT and forbids treating it as the bar to beat, because it scored clause-formed
scenarios using turn vectors.

So both arms here are built identically and only the taxonomy differs:
  same turn pool          the 23,949 Naren CLIENT turns (production entry point, Avoma roster)
  same embedder           gemini-embedding-2 @ 3072, cached -- neither side gets its native one
  same assignment         top-1 cosine against `business_description + keyphrases`, which is
                          what layer_b's primary scenario_key and Layer D's rubric lookup both
                          resolve to
  same null               size_matched_null() from trial_pool_unit, drawn from that same pool
  same bar                lift >= 0.05, and rankable means >= 8 assigned turns

ARM 3 IS REPORTED AND IS NOT THE ANSWER. The rigged cluster-membership version is computed
too, explicitly labelled an upper bound, so the gap between "HDBSCAN's own clusters" and
"what matching actually gathers" is visible rather than hidden. Printing it is the honest
move; quoting it as the result would not be.

WHAT THIS CANNOT ANSWER. Beating a random null means a scenario is more than a random pile of
turns. It does not mean the scenario produces a usable rubric, and nothing downstream of Layer
A is exercised here.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/null_test_taxonomy.py
    ..\\.venv\\Scripts\\python.exe calibration/null_test_taxonomy.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "null_test_taxonomy.json"
MIN_MEMBERS = 8          # scenario_coherence.py's MIN_TRIGGERS -- below this no stable centroid
LIFT_BAR = 0.05          # trial_pool_unit.NULL_LIFT_BAR
SEED = 42


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    return p.parse_args()


def score_population(vecs: np.ndarray, pool: np.ndarray, label: str, keys: list[str],
                     member_idx: dict[str, list[int]]):
    """Coherence vs size-matched null for every entry, using the SHARED implementations."""
    from calibration.trial_pool_unit import coherence, size_matched_null

    rng = random.Random(SEED)
    rows = []
    for k in keys:
        idx = member_idx.get(k, [])
        if len(idx) < 2:
            rows.append({"key": k, "n": len(idx), "coh": float("nan"),
                         "null": float("nan"), "lift": float("nan"), "rankable": False})
            continue
        coh = coherence(vecs[idx])
        nul = size_matched_null(pool, len(idx), rng)
        rows.append({"key": k, "n": len(idx), "coh": coh, "null": nul,
                     "lift": coh - nul, "rankable": len(idx) >= MIN_MEMBERS})
    rankable = [r for r in rows if r["rankable"]]
    clears = [r for r in rankable if r["lift"] >= LIFT_BAR]
    print(f"\n  {label}: {len(rows)} coachable entries, {len(rankable)} rankable "
          f"(>= {MIN_MEMBERS} turns)")
    if rankable:
        print(f"    coherence  mean {np.mean([r['coh'] for r in rankable]):.3f}"
              f"   null mean {np.mean([r['null'] for r in rankable]):.3f}"
              f"   lift {np.mean([r['lift'] for r in rankable]):+.3f}")
        print(f"    BEAT THEIR OWN NULL by >= {LIFT_BAR}: "
              f"{len(clears)}/{len(rankable)} = {len(clears)/len(rankable)*100:.0f}%")
    return {"rows": rows, "n_rankable": len(rankable), "n_clear": len(clears),
            "share": len(clears) / len(rankable) if rankable else float("nan")}


def report(p: dict) -> None:
    print("\n" + "=" * 88)
    print("SIZE-MATCHED RANDOM NULL -- BOTH TAXONOMIES, SAME POOL / EMBEDDER / RULE / NULL")
    print("=" * 88)
    print(f"  pool: {p['n_turns']} Naren CLIENT turns   embedder: {p['embedder']}")
    for name in ("old_matched", "new_matched"):
        a = p[name]
        print(f"\n  {name:<14} rankable {a['n_rankable']:>3}   clear the null "
              f"{a['n_clear']:>3}  = {a['share']*100:>4.0f}%")
    ub = p["new_cluster_upper_bound"]
    print(f"\n  {'new_cluster':<14} rankable {ub['n_rankable']:>3}   clear the null "
          f"{ub['n_clear']:>3}  = {ub['share']*100:>4.0f}%   <- RIGGED UPPER BOUND, not the answer")

    print("\n--- turn-mode coachable scenarios, by matched lift ---")
    rows = sorted([r for r in p["new_matched"]["rows"] if r["rankable"]],
                  key=lambda r: -r["lift"])
    for r in rows:
        mark = "PASS" if r["lift"] >= LIFT_BAR else "    "
        print(f"  {mark} {r['lift']:+.3f}  coh {r['coh']:.3f} vs null {r['null']:.3f}"
              f"  n={r['n']:<5} {r['key'][:50]}")
    thin = [r for r in p["new_matched"]["rows"] if not r["rankable"]]
    if thin:
        print(f"\n  too thin to rank ({len(thin)}): "
              + ", ".join(f"{r['key'][:34]}(n={r['n']})" for r in thin))


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return

    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool
    from calibration.trial_pool_unit_gemini import embed_cached
    from calibration.validate_taxonomy_vs_layerd import load_old, load_new, match
    import psycopg

    cfg = load_config()

    # DB FIRST, CLOSED BEFORE ANY EMBEDDING. Holding a Neon connection across slow work is
    # the documented way this fails; validate_taxonomy_vs_layerd.py carries the same rule.
    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        old = load_old(conn)
    new = load_new()
    print(f"OLD taxonomy: {len(old)} entries ({sum(t['coachable'] for t in old)} coachable)")
    print(f"NEW taxonomy: {len(new)} entries ({sum(t['coachable'] for t in new)} coachable)")

    turns = []
    for f in sorted(Path(a.recordings).glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    print(f"{len(texts)} CLIENT turns over {len(set(call_ids))} calls")

    vecs = embed_cached(texts, workers=20)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    emb = lambda t: embed_cached(t, workers=20)

    payload = {"n_turns": len(texts), "embedder": "gemini-embedding-2@3072",
               "min_members": MIN_MEMBERS, "lift_bar": LIFT_BAR, "seed": SEED}

    for name, tax in (("old_matched", old), ("new_matched", new)):
        m = match(vecs, tax, emb)
        coach_keys = [t["key"] for t in tax if t["coachable"]]
        member_idx: dict[str, list[int]] = {}
        for i, b in enumerate(m["best"]):
            if m["accepted"][i]:
                member_idx.setdefault(m["keys"][b], []).append(i)
        assigned = sum(len(v) for v in member_idx.values())
        print(f"\n[{name}] {assigned}/{len(texts)} turns ({assigned/len(texts)*100:.1f}%) "
              f"matched a COACHABLE entry")
        payload[name] = score_population(vecs, vecs, name, coach_keys, member_idx)

    # --- the rigged arm, computed on purpose so the inflation is visible ------------------
    from collections import defaultdict
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model
    adj = json.loads((ARTIFACTS_DIR / "adjudicate_gemini_min16.json")
                     .read_text(encoding="utf-8-sig"))["rows"]
    ta = load_tuning().layer_a
    total_calls = len(set(call_ids))
    print("\n[new_cluster] re-clustering for the rigged upper bound ...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=16)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, 0.97)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=[texts[i] for i in idxs])
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        clusters.append({"idxs": idxs, "n": st.n_items})
    clusters.sort(key=lambda c: c["n"], reverse=True)
    if len(clusters) != len(adj):
        raise SystemExit(f"JOIN FAILED: {len(clusters)} vs {len(adj)}")
    cl_idx = {r["scenario_key"]: c["idxs"] for c, r in zip(clusters, adj)
              if r["kind"] == "scenario"}
    payload["new_cluster_upper_bound"] = score_population(
        vecs, vecs, "new_cluster", list(cl_idx), cl_idx)

    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}")
    print("Zero chat calls, zero embedding requests, zero Postgres writes.")


if __name__ == "__main__":
    main()
