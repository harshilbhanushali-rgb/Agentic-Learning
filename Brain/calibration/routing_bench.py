#!/usr/bin/env python3
"""Benchmark every turn->scenario routing method on ONE scale. Free, read-only, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md
Arms: calibration/routing_arms.py

This is the promotion of three throwaway scratchpad scripts -- round-trip, held-out-by-call
routing, and coherence-vs-null over a pluggable population -- into one harness. They are
UNIFIED rather than promoted as three files for one reason: all three need the same 400-call
pool, the same cached embeddings and the same BERTopic re-clustering, and running them in
three processes would compare arms against three separately-fitted clusterings. That is
survivable on this backend (gemini embeddings are deterministic and the clustering reproduced
exactly across four launches) but it is survivable by luck, and the join assert below is the
only thing that would catch it. One process makes it structural.

The three measurements, and what each is for:

  ROUTING ACCURACY   does a turn land on the scenario whose cluster it belongs to.
                     Ground truth IS cluster membership, and most arms are BUILT from cluster
                     membership, so this metric favours them by construction. Reported, never
                     the gate. Full-corpus it is the round trip; out-of-fold it is
                     generalisation -- the same measurement at two leakage levels.

  COHERENCE VS NULL  *** THE GATE. *** Share of scenarios whose population beats a
                     length-matched random null by at least the lift a size-matched
                     positive-control group achieves. Never references membership, which is
                     exactly why it can adjudicate between arms that are built from it.
                     Machinery is imported wholesale from null_test_taxonomy.py -- same
                     coherence, same three nulls, same size-conditional reference -- so a
                     number here is directly comparable with the published 29 / 47 / 53.

  REJECT RATE        share of turns whose best match is a SINK. A falsifier, not a
                     diagnostic: an arm that wins accuracy by accepting everything has
                     abolished the only junk filter the pipeline has (spec F4).

*** PRIMARY MODE IS OUT-OF-FOLD. *** Calls are split into K folds; every turn is routed by a
model fitted on the other folds, so every turn is scored exactly once, blind to its own call,
and the evaluation population is the WHOLE pool. Full-corpus is reported beside it and is
INFLATED for `knn_max` / `knn_topk_mean` / `medoid` / `probe`: scored over the turns they were
fitted on, a member is its own nearest neighbour at cosine 1.0 and the arm reproduces cluster
membership while having learned nothing. Those cells are marked `*` rather than being silently
comparable. With one shared control and one shared reference, the two modes differ in exactly
one respect -- whether the router saw the turn's call.

A SINGLE 75/25 HOLDOUT WAS TRIED FIRST AND WAS UNDER-POWERED, by this script's own
pre-registered F6: only 14 scenarios stayed rankable under every arm against a floor of 20,
because a quarter-size population runs into MIN_MEMBERS=8. At n=14 one scenario is 7 points
and the arm ordering inverted against the full-corpus ordering. CV changes the DENOMINATOR
and nothing else -- no arm, metric, null or failure condition moved.

Folds are over CALLS, never turns. Turns from one call share a speaker, an account, and often
one sentence split in two, so a turn-level fold leaks a turn's own neighbours into fitting and
every membership-based arm scores near ceiling for a reason unrelated to routing.

FREE SELF-CHECK ON THE FOLD MACHINERY: `description` does no fitting, so its out-of-fold and
full-corpus assignments must be IDENTICAL, turn for turn. The run asserts it. Any bug that
mixed folds, misaligned an index or dropped a turn would break that equality.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/routing_bench.py
    ..\\.venv\\Scripts\\python.exe calibration/routing_bench.py --arms description,centroid
    ..\\.venv\\Scripts\\python.exe calibration/routing_bench.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration import null_test_taxonomy as nt
from calibration import routing_arms as ra

OUT = ARTIFACTS_DIR / "routing_bench.json"
ADJ = ARTIFACTS_DIR / "adjudicate_gemini_min16.json"
SEED = 42
K_FOLDS = 4                    # out-of-fold CV over calls; every turn scored once
MIN_CLUSTER_SIZE = 16          # must match the adjudication artifact being joined against
MERGE = 0.97                   # ditto -- asserted below, never assumed
MIN_RANKABLE_ARMS = 20         # spec F6: below this an arm is unrankable, not comparable
MARGIN_PCTS = (10, 25, 50, 75, 90)
# Cross-encoder rerank (spec section 10). ms-marco is a query/passage relevance ranker and
# SATURATES on prose descriptions (probed spread 0.57, everything at its "irrelevant" floor);
# it separates on turn-vs-turn (spread 4.61). That is why the arm pairs a turn with real
# member TURNS and never with the description.
XENC_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
XENC_K = 5                     # candidates proposed by centroid_pooled
XENC_MEMBERS = 3               # representative member turns per candidate


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--arms", default="", help="comma-separated subset; default = all free arms")
    p.add_argument("--folds", type=int, default=K_FOLDS,
                   help="cross-validation folds over CALLS (primary, out-of-fold mode)")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--embed-variants", action="store_true",
                   help="ALSO run the description-register arms; fetches a few hundred "
                        "SHORT texts (capped), never the turn pool")
    p.add_argument("--cross-encoder", action="store_true",
                   help="ALSO run the cross-encoder rerank arm + its random placebo (local "
                        "model, GPU, no network after first load)")
    p.add_argument("--xenc-model", default=XENC_MODEL)
    p.add_argument("--xenc-k", type=int, default=XENC_K)
    p.add_argument("--xenc-members", type=int, default=XENC_MEMBERS)
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    p.add_argument("--force", action="store_true",
                   help="allow overwriting an artifact built from MORE turns than this run")
    return p.parse_args()


def embed_cache_only(texts: list[str]) -> np.ndarray:
    """Cached vectors only -- a miss ABORTS rather than silently spending.

    Every arm here is free by design. An accidental cache miss on a 24k-turn pool is 24k
    gateway requests, so this refuses instead of discovering the bill afterwards.
    """
    from calibration.trial_pool_unit_gemini import _cache_open, _key

    conn = _cache_open()
    keys = [_key(t) for t in texts]
    have: dict[str, np.ndarray] = {}
    for i in range(0, len(keys), 900):                     # SQLite parameter limit
        chunk = keys[i:i + 900]
        q = ",".join("?" * len(chunk))
        for k, blob in conn.execute(f"SELECT k, v FROM vec WHERE k IN ({q})", chunk):
            have[k] = np.frombuffer(blob, dtype=np.float32)
    conn.close()
    miss = sum(1 for k in keys if k not in have)
    if miss:
        raise SystemExit(f"ABORT: {miss}/{len(texts)} texts uncached -- this run would have "
                         f"SPENT. Warm the cache deliberately, never as a side effect.")
    return np.stack([have[k] for k in keys])


def build_pool(recordings: str):
    """Production entry point, production arguments. A scratchpad re-implementation of this
    disagreed with production by ~20% twice -- spaCy loaded with different components moves
    sentence boundaries, and `parse_transcript` without the Avoma roster misclassifies
    speakers. Import production code; never paraphrase it."""
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool

    cfg = load_config()
    turns = []
    for f in sorted(Path(recordings).glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    return texts, call_ids


def cluster_pool(texts, vecs, call_ids, adj_rows):
    """Re-run production's Layer A clustering and join it to the adjudication artifact."""
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model

    ta = load_tuning().layer_a
    total_calls = len(set(call_ids))
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, MERGE)
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
    if len(clusters) != len(adj_rows):
        raise SystemExit(f"JOIN FAILED: re-clustering produced {len(clusters)} clusters, the "
                         f"adjudication artifact holds {len(adj_rows)}. The run is void.")
    return clusters


def score_arm(name, routing, ctx, mode, truth_key, truth_coach, ctl_rows,
              coach_keys, vecs, order_by_wc, rank_of, word_count):
    """The three metrics for one arm in one mode, plus the margin distribution."""
    ev = ctx.eval_idx
    # --- 1. routing accuracy, over eval turns that belong to a COACHABLE cluster -----------
    gt = [(j, truth_key[i]) for j, i in enumerate(ev) if i in truth_key and truth_coach[i]]
    hit = sum(1 for j, k in gt if routing.keys[j] == k)
    acc = hit / len(gt) if gt else float("nan")

    # --- 3. reject rate, over ALL eval turns ----------------------------------------------
    reject = float(1.0 - routing.accepted.mean())

    # --- 2. coherence vs null -- THE GATE -------------------------------------------------
    member_idx: dict[str, list[int]] = defaultdict(list)
    for j, i in enumerate(ev):
        if routing.accepted[j]:
            member_idx[routing.keys[j]].append(int(i))
    scored = nt.score_population(vecs, f"{name}[{mode}]", coach_keys, dict(member_idx),
                                 order_by_wc, rank_of, word_count)
    rk = [r for r in scored["rows"] if r["rankable"]]
    for r in rk:
        r["ref_lift"] = nt.size_matched_reference(r["n"], ctl_rows) if ctl_rows else float("nan")
        r["reaches_ref"] = bool(r[f"lift_{nt.GATE_NULL}"] >= r["ref_lift"])
    scored["n_clear_ctrl"] = sum(r["reaches_ref"] for r in rk)
    scored["share_ctrl"] = scored["n_clear_ctrl"] / len(rk) if rk else float("nan")

    fin = routing.margin[np.isfinite(routing.margin)]
    scored.update({
        "arm": name, "mode": mode, "note": routing.note, "n_points": routing.n_points,
        "routing_accuracy": acc, "routing_hits": hit, "routing_evaluable": len(gt),
        "reject_rate": reject, "accepted_turns": int(routing.accepted.sum()),
        "eval_turns": int(len(ev)),
        "self_inflating": bool(name in ra.SELF_INFLATING and mode == "full"),
        "needs_membership": bool(name in ra.NEEDS_MEMBERSHIP),
        "comparable": bool(len(rk) >= MIN_RANKABLE_ARMS),
        "margin_pct": {str(p): float(np.percentile(fin, p)) for p in MARGIN_PCTS}
        if len(fin) else {},
        "best_sim_p50": float(np.median(routing.best_sim)) if len(routing.best_sim) else float("nan"),
    })
    return scored


def round_trip_detail(routing, ctx, truth_key, truth_coach, top=6):
    """Per-scenario recall / precision / dilution -- the original round-trip harness.

    `recall` of a cluster's own eval turns, how many return to its own scenario. `precision`
    of the turns the arm gathered under that scenario, how many were in its cluster.
    `dilution` gathered / own: a scenario can hold 27x its cluster and still look fine on
    recall alone, which is what the first version of this measurement missed.
    """
    ev = ctx.eval_idx
    own = defaultdict(list)
    for j, i in enumerate(ev):
        if i in truth_key and truth_coach[i]:
            own[truth_key[i]].append(j)
    got = defaultdict(list)
    for j in range(len(ev)):
        if routing.accepted[j]:
            got[routing.keys[j]].append(j)
    rows = []
    for k, mine in own.items():
        back = sum(1 for j in mine if routing.keys[j] == k)
        g = got.get(k, [])
        inter = len(set(mine) & set(g))
        rows.append({"key": k, "n_cluster": len(mine), "n_matched": len(g),
                     "recall": back / len(mine),
                     "precision": inter / len(g) if g else float("nan"),
                     "dilution": len(g) / len(mine)})
    rows.sort(key=lambda r: r["recall"])
    return rows


MAX_VARIANT_TEXTS = 1200       # hard cap on what --embed-variants may fetch


def build_variant_arms(keys: list[str]) -> tuple[dict, int]:
    """Split the shipped description vector into its two REGISTERS and score them separately.

    `load_new()` concatenates `business_description` (analyst prose, written ABOUT clients)
    with `keyphrases` (verbatim client language, e.g. 'launching this RFP', 'cost per
    activation') and embeds the result as ONE vector. Averaging two registers is precisely the
    query-document register gap the asymmetric-retrieval literature names, and it is testable
    here for a few hundred embedding requests rather than any LLM generation:

      desc_prose        analyst prose alone
      desc_keyphrases   the keyphrases alone, joined
      desc_maxpool      prose and keyphrases as TWO points, max-pooled -- a turn scores
                        against whichever register it is closer to, instead of their average
      desc_kp_each      EVERY keyphrase its own point. This is the free version of the
                        HyDE/HyPE mirror: retrieval points that are already real client
                        utterances, so no generation is needed to close the register gap.

    Only these few hundred SHORT texts may be fetched -- never the 24k turn pool, which is
    what `embed_cache_only` exists to protect.
    """
    from calibration.trial_pool_unit_gemini import embed_cached

    rows = [r for r in json.loads(ADJ.read_text(encoding="utf-8-sig"))["rows"]
            if r["kind"] != "merged"]
    prose = {r["scenario_key"]: (r["business_description"] or "").strip() for r in rows}
    kps = {r["scenario_key"]: [p for p in (r["keyphrases"] or []) if p.strip()] for r in rows}
    prose = {k: v for k, v in prose.items() if v and k in set(keys)}
    kps = {k: v for k, v in kps.items() if v and k in set(keys)}

    texts = sorted({*prose.values(), *(" ".join(v) for v in kps.values()),
                    *(p for v in kps.values() for p in v)})
    if len(texts) > MAX_VARIANT_TEXTS:
        raise SystemExit(f"REFUSING: {len(texts)} variant texts exceeds the "
                         f"{MAX_VARIANT_TEXTS} cap. This path may embed short description "
                         f"variants, never a turn pool.")
    print(f"[variants] embedding {len(texts)} short texts (cap {MAX_VARIANT_TEXTS}) ...",
          flush=True)
    mat = embed_cached(texts, workers=20)
    mat = (mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    vec = {t: v for t, v in zip(texts, mat)}

    arms = {
        "desc_prose": ra.make_text_arm({k: vec[v][None, :] for k, v in prose.items()},
                                       "business_description prose alone"),
        "desc_keyphrases": ra.make_text_arm(
            {k: vec[" ".join(v)][None, :] for k, v in kps.items()},
            "keyphrases alone (verbatim client language)"),
        "desc_maxpool": ra.make_text_arm(
            {k: np.stack([vec[prose[k]], vec[" ".join(kps[k])]])
             for k in prose if k in kps}, "prose and keyphrases as 2 points, max-pooled"),
        "desc_kp_each": ra.make_text_arm(
            {k: np.stack([vec[p] for p in v]) for k, v in kps.items()},
            "each keyphrase its own point (free HyPE analogue)"),
    }
    return arms, len(texts)


def build_rerank_arms(model_name: str, k: int, n_members: int) -> dict:
    """The cross-encoder arm and its placebo. Local model, GPU, no network after first load.

    THE PLACEBO IS NOT OPTIONAL (spec F7). Restricting to the top-5 is itself an intervention
    -- it discards every far-fetched key the argmax could otherwise reach -- so `rerank_random`
    picks uniformly among the SAME shortlist. If the cross-encoder does not clearly beat it,
    any gain came from the shortlist rather than from reading the pair, and the honest
    conclusion is that the re-ranker is inert.
    """
    from sentence_transformers import CrossEncoder

    print(f"[xenc] loading {model_name} ...", flush=True)
    model = CrossEncoder(model_name, max_length=256)
    print(f"[xenc] on {model.model.device}", flush=True)
    seen = {"pairs": 0}

    def score(pairs):
        seen["pairs"] += len(pairs)
        return model.predict(pairs, batch_size=256, show_progress_bar=False)

    short = model_name.split("/")[-1]
    return {
        "xenc_member": ra.make_rerank_arm(score, k=k, n_members=n_members,
                                          note=f"cross-encoder {short} vs member turns"),
        "rerank_random": ra.make_random_rerank_arm(k=k),
    }


def run_out_of_fold(fn, ctx_full, fold_of_turn: np.ndarray, k: int, name: str):
    """Score every turn with a router that never saw that turn's CALL.

    The result covers the whole pool, so its coherence populations are the same size as the
    full-corpus ones and the two modes differ in exactly one respect. Folds are over CALLS,
    never turns: turns from one call share a speaker, an account, and often one sentence split
    in two, so a turn-level fold leaks a turn's own neighbours into fitting and every
    membership-based arm scores near ceiling for a reason that has nothing to do with routing.
    """
    from dataclasses import replace

    n = len(ctx_full.vecs)
    keys: list[str] = [""] * n
    acc = np.zeros(n, dtype=bool)
    marg = np.full(n, np.nan, dtype=np.float32)
    bsim = np.full(n, np.nan, dtype=np.float32)
    pts, note = [], ""
    for f in range(k):
        ev = np.flatnonzero(fold_of_turn == f)
        if not len(ev):
            continue
        r = fn(replace(ctx_full, eval_idx=ev, fit_mask=fold_of_turn != f))
        for j, i in enumerate(ev):
            keys[i] = r.keys[j]
        acc[ev], marg[ev], bsim[ev] = r.accepted, r.margin, r.best_sim
        pts.append(r.n_points)
        note = r.note
        print(f"    fold {f}: {len(ev)} turns, {r.n_points} points", flush=True)
    if any(x == "" for x in keys):
        raise ValueError(f"{name}: some turns were never scored out-of-fold")
    return ra.Routing(keys=keys, accepted=acc, margin=marg, best_sim=bsim,
                      n_points=int(np.mean(pts)) if pts else 0,
                      note=f"{note} [out-of-fold, mean {int(np.mean(pts)) if pts else 0} pts]")


def report(p: dict) -> None:
    print("\n" + "=" * 108)
    print("ROUTING BENCH -- every arm, same pool / embedder / clustering / split / null")
    print("=" * 108)
    print(f"  pool {p['n_turns']} turns / {p['n_calls']} calls   embedder {p['embedder']}   "
          f"seed {p['seed']}   {p['folds']}-fold CV over calls")
    print(f"  clustering min_cluster_size={p['min_cluster_size']} merge={p['merge']}   "
          f"{p['n_clusters']} clusters -> {p['n_keys']} keys "
          f"({p['n_coachable_keys']} coachable)")
    print(f"  cluster labels: {p['label_stats']}")
    print(f"  every turn scored exactly once by a router blind to its own call; "
          f"fold turn counts {p['fold_sizes']}")

    for mode in ("oof", "full"):
        arms = [a for a in p["arms"] if a["mode"] == mode]
        if not arms:
            continue
        head = ("*** PRIMARY: OUT-OF-FOLD (every turn routed by a model blind to its call)"
                if mode == "oof" else
                "FULL CORPUS -- continuity with the published 29 / 47 / 53. `*` = self-inflating")
        print("\n" + "-" * 108)
        print(f"  {head}")
        print("-" * 108)
        print(f"  {'arm':<22}{'route acc':>11}{'FIXED':>12}{'common':>11}{'own set':>11}"
              f"{'reject':>9}{'miss':>6}{'points':>8}  note")
        base = {a["arm"]: a for a in arms}
        key = lambda x: -(x.get("share_fixed") if x.get("share_fixed") == x.get("share_fixed")
                          else -9)
        for a in sorted(arms, key=key):
            star = "*" if a["self_inflating"] else " "
            fx = (f"{a['n_clear_fixed']}/{a['n_fixed']}="
                  f"{a['share_fixed'] * 100:.0f}%") if a.get("n_fixed") else "--"
            com = (f"{a['share_common'] * 100:.0f}%") if a.get("n_common") else "--"
            own = (f"{a['n_clear_ctrl']}/{a['n_rankable']}") if a["n_rankable"] else "--"
            print(f"  {a['arm']:<21}{star}{a['routing_accuracy'] * 100:>10.1f}%{fx:>12}"
                  f"{com:>11}{own:>11}{a['reject_rate'] * 100:>8.1f}%"
                  f"{a.get('n_unrankable_vs_ctl', 0):>6}{a['n_points']:>8}  {a['note'][:24]}")
        n_com = next((x.get("n_common", 0) for x in arms if not x.get("failed")), 0)
        n_fx = next((x.get("n_fixed", 0) for x in arms if not x.get("failed")), 0)
        print(f"    FIXED = cleared, out of the {n_fx} scenarios the CONTROL can rank -- the "
              f"headline. Its denominator does not move\n    with the arm list. `miss` = how "
              f"many of those the arm could not even rank (<8 turns): a failure, not an\n"
              f"    excuse. `common` = the {n_com}-scenario all-arm intersection, which "
              f"SHRINKS if any one arm starves scenarios.")
        for k in ("description", "centroid", "placebo_centroid"):
            if k in base:
                print(f"    {k:<20} margin p10/p50/p90 = "
                      + " / ".join(f"{base[k]['margin_pct'].get(str(q), float('nan')):.4f}"
                                   for q in (10, 50, 90)))

    v = p.get("verdicts", {})
    if v:
        print("\n" + "=" * 108)
        print("  PRE-REGISTERED FAILURE CONDITIONS")
        print("=" * 108)
        for k in sorted(v):
            print(f"  {k}: {v[k]}")

    rt = p.get("round_trip", {})
    for arm, rows in rt.items():
        print(f"\n--- round trip [{arm}, out-of-fold]: worst and best by recall ---")
        print(f"  {'recall':>8}{'prec':>8}{'clust':>7}{'match':>7}{'dilut':>7}  key")
        for r in rows[:5] + rows[-3:]:
            print(f"  {r['recall'] * 100:>7.1f}%{r['precision'] * 100:>7.1f}%"
                  f"{r['n_cluster']:>7}{r['n_matched']:>7}{r['dilution']:>6.1f}x  "
                  f"{r['key'][:46]}")


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return

    t0 = time.time()
    adj_payload = json.loads(ADJ.read_text(encoding="utf-8-sig"))
    adj = adj_payload["rows"]
    for k, v in (("min_cluster_size", MIN_CLUSTER_SIZE), ("merge", MERGE)):
        if adj_payload.get(k) is not None and adj_payload[k] != v:
            raise SystemExit(f"CONFIG MISMATCH: {ADJ.name} was built with {k}="
                             f"{adj_payload[k]}, this run uses {v}.")

    texts, call_ids = build_pool(a.recordings)
    vecs = embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    print(f"{len(texts)} CLIENT turns over {len(set(call_ids))} calls", flush=True)

    print("re-clustering (production path) ...", flush=True)
    clusters = cluster_pool(texts, vecs, call_ids, adj)
    cl_keys, cl_coach, label_stats = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)
    coach_keys = [k for k, c in zip(keys, coach) if c]
    print(f"{len(clusters)} clusters -> {len(keys)} keys ({len(coach_keys)} coachable); "
          f"{label_stats}")

    # Cross-check the labelling against null_test_taxonomy's own fold, which the published
    # control was built with. Two implementations of "merged means retained" that disagree
    # would make this bench and that artifact incomparable without saying so.
    folded_ref, n_folded, n_orph = nt.fold_merged_clusters(clusters, adj)
    if set(folded_ref) != set(coach_keys):
        raise SystemExit(f"LABEL MISMATCH vs null_test_taxonomy.fold_merged_clusters: "
                         f"{len(folded_ref)} vs {len(coach_keys)} coachable keys")
    if n_folded != label_stats["merged_folded"] or n_orph != label_stats["merged_orphaned"]:
        raise SystemExit(f"FOLD MISMATCH: {n_folded}/{n_orph} vs {label_stats}")

    truth_key: dict[int, str] = {}
    truth_coach: dict[int, bool] = {}
    for c, ki, co in zip(clusters, owner, cl_coach):
        for i in c["idxs"]:
            truth_key[i] = keys[ki]
            truth_coach[i] = bool(co)

    # --- the description side, aligned onto the CLUSTER key universe ----------------------
    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dvec = embed_cache_only([t["text"] for t in tax])
    dvec = (dvec / (np.linalg.norm(dvec, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    desc_vecs = np.zeros((len(keys), vecs.shape[1]), dtype=np.float32)
    desc_have = np.zeros(len(keys), dtype=bool)
    pos = {k: i for i, k in enumerate(keys)}
    unknown = 0
    for t, v in zip(tax, dvec):
        j = pos.get(t["key"])
        if j is None:
            unknown += 1
            continue
        desc_vecs[j], desc_have[j] = v, True
    print(f"descriptions: {int(desc_have.sum())}/{len(keys)} keys have one "
          f"({unknown} taxonomy entries had no cluster-side key), "
          f"{int((desc_have & coach).sum())}/{len(coach_keys)} coachable")

    # --- K-FOLD BY CALL, not one holdout ---------------------------------------------------
    # A single 75/25 split was tried first and was UNDER-POWERED, by this script's own
    # pre-registered F6: only 14 scenarios stayed rankable under every arm (floor: 20),
    # because held-out populations are a quarter the size and MIN_MEMBERS=8 then bites. At
    # n=14 one scenario is 7 points and the arm ordering inverted against the full-corpus
    # ordering -- i.e. noise. Cross-validation fixes the DENOMINATOR without touching any
    # arm, metric, null or failure condition: every turn is scored exactly once by a router
    # that never saw its call, so the out-of-fold population is the whole 23,949 turns.
    #
    # That also makes the two modes differ in EXACTLY ONE THING -- whether the router saw
    # the turn's call while fitting. Same eval turns, same control, same reference. The
    # single-split numbers are kept in logs/routing_bench_split.log as the record.
    calls = sorted(set(call_ids))
    rng = random.Random(a.seed)
    rng.shuffle(calls)
    fold_of_call = {c: i % a.folds for i, c in enumerate(calls)}
    fold_of_turn = np.array([fold_of_call[c] for c in call_ids])
    sizes = [int((fold_of_turn == f).sum()) for f in range(a.folds)]
    print(f"{a.folds}-fold split BY CALL: {len(calls)} calls -> fold turn counts {sizes}")

    word_count = np.array([len(t.split()) for t in texts])
    order_by_wc = [int(i) for i in np.argsort(word_count, kind="stable")]
    rank_of = {t: i for i, t in enumerate(order_by_wc)}

    cluster_members = [c["idxs"] for c in clusters]
    all_idx = np.arange(len(texts))
    ctx_full = ra.ArmContext(vecs=vecs, eval_idx=all_idx,
                             fit_mask=np.ones(len(texts), bool),
                             cluster_members=cluster_members, cluster_keys=cl_keys,
                             cluster_coach=cl_coach, desc_vecs=desc_vecs,
                             desc_have=desc_have, keys=keys, coach=coach, owner=owner,
                             seed=a.seed, texts=texts)

    registry = dict(ra.FREE_ARMS)
    n_variant_texts = 0
    if a.cross_encoder:
        registry.update(build_rerank_arms(a.xenc_model, a.xenc_k, a.xenc_members))
    if a.embed_variants:
        variants, n_variant_texts = build_variant_arms(keys)
        registry.update(variants)
    chosen = [s.strip() for s in a.arms.split(",") if s.strip()] or list(registry)
    bad = [c for c in chosen if c not in registry]
    if bad:
        raise SystemExit(f"unknown arms {bad}; available: {sorted(registry)}")

    results, round_trip, routings = [], {}, {}

    # THE POSITIVE CONTROL, COMPUTED ONCE. Both modes now evaluate every turn, so one control
    # supplies the size-matched reference for every arm in both of them. Two controls would
    # have meant two references, and an arm's mode-to-mode difference would then have mixed
    # "did fitting on its own eval turns help it" with "was it graded against a different bar".
    ctl_member = defaultdict(list)
    for i in range(len(texts)):
        if i in truth_key and truth_coach[i]:
            ctl_member[truth_key[i]].append(int(i))
    ctl = nt.score_population(vecs, "cluster_membership", coach_keys, dict(ctl_member),
                              order_by_wc, rank_of, word_count)
    ctl_rows = [r for r in ctl["rows"] if r["rankable"]]
    for r in ctl_rows:
        r["ref_lift"] = nt.size_matched_reference(r["n"], ctl_rows)
        r["reaches_ref"] = bool(r[f"lift_{nt.GATE_NULL}"] >= r["ref_lift"])
    ctl.update({"arm": "cluster_membership",
                "note": "POSITIVE CONTROL -- HDBSCAN's own membership",
                "n_clear_ctrl": sum(r["reaches_ref"] for r in ctl_rows),
                "share_ctrl": (sum(r["reaches_ref"] for r in ctl_rows) / len(ctl_rows)
                               if ctl_rows else float("nan")),
                "routing_accuracy": 1.0, "routing_hits": 0, "routing_evaluable": 0,
                "reject_rate": float("nan"), "n_points": 0, "self_inflating": False,
                "needs_membership": True, "margin_pct": {},
                "comparable": len(ctl_rows) >= MIN_RANKABLE_ARMS,
                "accepted_turns": sum(len(v) for v in ctl_member.values()),
                "eval_turns": len(texts), "best_sim_p50": float("nan")})

    for mode in ("oof", "full"):
        ctx = ctx_full
        results.append({**ctl, "mode": mode})

        for name in chosen:
            print(f"\n[{mode}] arm {name} ...", flush=True)
            t1 = time.time()
            # A failed arm is RECORDED as failed, never silently missing from the table. An
            # arm that vanishes reads as "not tried"; one that is absent from the artifact
            # cannot be distinguished later from one that was never in the list.
            try:
                routing = (run_out_of_fold(registry[name], ctx_full, fold_of_turn,
                                           a.folds, name)
                           if mode == "oof" else registry[name](ctx))
            except Exception as exc:                       # noqa: BLE001 -- harness resilience
                print(f"    ARM FAILED: {type(exc).__name__}: {exc}", flush=True)
                results.append({"arm": name, "mode": mode, "failed": f"{type(exc).__name__}: {exc}",
                                "rows": [], "n_rankable": 0, "share_ctrl": float("nan"),
                                "median_lift": float("nan"), "routing_accuracy": float("nan"),
                                "reject_rate": float("nan"), "n_points": 0, "note": "FAILED",
                                "self_inflating": False, "comparable": False, "margin_pct": {}})
                continue
            res = score_arm(name, routing, ctx, mode, truth_key, truth_coach, ctl_rows,
                            coach_keys, vecs, order_by_wc, rank_of, word_count)
            res["seconds"] = round(time.time() - t1, 1)
            results.append(res)
            routings[(name, mode)] = routing
            if mode == "oof" and name in ("description", "centroid"):
                round_trip[name] = round_trip_detail(routing, ctx, truth_key, truth_coach)

        # *** SYMMETRY: compare arms on the SAME scenarios. ***
        # `share_ctrl` is a share over each arm's OWN rankable set, and those differ -- an arm
        # that concentrates turns leaves more scenarios above the 8-member floor than one that
        # scatters them. Two shares over two denominators is precisely the asymmetric
        # comparison this codebase has grown four separate defences against. The intersection
        # of every arm's rankable set is the population all arms can be graded on at once;
        # it is REPORTED ALONGSIDE, not instead of, so the denominator drift stays visible.
        here = [r for r in results if r["mode"] == mode and not r.get("failed")]
        common = set.intersection(*[{r["key"] for r in x["rows"] if r["rankable"]}
                                    for x in here]) if here else set()
        # *** THE HEADLINE IS `share_fixed`, over the CONTROL's rankable set. ***
        # `share_common` has a defect that only shows once arm sets vary: the intersection
        # SHRINKS when any single arm starves scenarios below the 8-member floor, so adding
        # one bad arm degrades the resolution of every other comparison in the run (`probe`
        # alone drags it from 35 to 21) and two runs with different arm lists are not
        # comparable. Worse, it EXCUSES the starving arm -- the scenarios it failed to
        # populate are removed from its own denominator too.
        # The control's rankable set is a fixed population of scenarios known to be
        # rankable at all, independent of the arm mix. An arm that cannot gather 8 turns for
        # one of them has FAILED on it, which is a result, not a missing observation.
        ctl_rank = {r["key"] for r in ctl["rows"] if r["rankable"]}
        for x in here:
            sub = [r for r in x["rows"] if r["key"] in common and r["rankable"]]
            x["n_common"] = len(sub)
            x["n_clear_common"] = sum(r.get("reaches_ref", False) for r in sub)
            x["share_common"] = x["n_clear_common"] / len(sub) if sub else float("nan")
            won = {r["key"] for r in x["rows"] if r["rankable"] and r.get("reaches_ref")}
            x["n_fixed"] = len(ctl_rank)
            x["n_clear_fixed"] = len(won & ctl_rank)
            x["share_fixed"] = x["n_clear_fixed"] / len(ctl_rank) if ctl_rank else float("nan")
            x["n_unrankable_vs_ctl"] = len(ctl_rank - {r["key"] for r in x["rows"]
                                                       if r["rankable"]})
        print(f"\n[{mode}] fixed denominator (control rankable): {len(ctl_rank)}; "
              f"all-arm common subset: {len(common)}")

    # --- the pre-registered verdicts, evaluated in code rather than by eye -----------------
    def cell(arm, mode="oof"):
        for r in results:
            if r["arm"] == arm and r["mode"] == mode:
                return r
        return None

    # FOLD-MACHINERY SELF-CHECK. `description` never looks at `fit_mask`, so its out-of-fold
    # assignment must equal its full-corpus assignment turn for turn. Any index misalignment,
    # dropped turn or fold mix-up breaks this, and it costs nothing to assert.
    if ("description", "oof") in routings and ("description", "full") in routings:
        o, f = routings[("description", "oof")], routings[("description", "full")]
        if o.keys != f.keys:
            bad = sum(1 for x, y in zip(o.keys, f.keys) if x != y)
            raise SystemExit(f"FOLD MACHINERY BROKEN: the fitting-free `description` arm "
                             f"disagrees with itself on {bad} turns between out-of-fold and "
                             f"full-corpus. The run is void.")
        print("\nfold self-check: description[oof] == description[full] on all "
              f"{len(o.keys)} turns")

    # Every verdict reads `share_common`, the symmetric column -- an arm must not clear a
    # failure condition by being graded on an easier subset of scenarios than its rivals.
    verdicts = {}
    S = lambda r: r.get("share_fixed", float("nan"))
    pl, cen, desc, ctlh = (cell("placebo_centroid"), cell("centroid"),
                           cell("description"), cell("cluster_membership"))
    if pl and cen:
        verdicts["F1 metric void (placebo >= centroid)"] = (
            f"{'FIRED' if S(pl) >= S(cen) else 'clear'} -- placebo "
            f"{S(pl) * 100:.0f}% vs centroid {S(cen) * 100:.0f}% (fixed denominator)")
    if ctlh:
        best = max((S(r) for r in results
                    if r["mode"] == "oof" and r["arm"] != "cluster_membership"
                    and S(r) == S(r)), default=float("nan"))
        verdicts["F2 instrument too hard (control not above every arm)"] = (
            f"{'FIRED' if S(ctlh) <= best else 'clear'} -- control "
            f"{S(ctlh) * 100:.0f}% vs best arm {best * 100:.0f}% (fixed denominator)")
    if cen:
        better = [f"{r['arm']}({S(r) * 100:.0f}%)" for r in results
                  if r["mode"] == "oof" and r["arm"] not in
                  ("cluster_membership", "placebo_centroid") and S(r) > S(cen)]
        verdicts["F3 H1 fails (nothing beats centroid)"] = (
            f"{'FIRED -- centroid is the best available' if not better else 'clear'} -- "
            f"beating centroid ({S(cen) * 100:.0f}%): {better or 'none'}")
    if desc:
        killed = [r["arm"] for r in results if r["mode"] == "oof"
                  and r["reject_rate"] == r["reject_rate"]
                  and r["reject_rate"] < 0.5 * desc["reject_rate"]]
        verdicts["F4 rejection destroyed (< half the description arm's)"] = (
            f"{'FIRED for ' + ', '.join(killed) if killed else 'clear'} -- description "
            f"rejects {desc['reject_rate'] * 100:.1f}%")
    thin = [f"{r['arm']}[{r['mode']}]" for r in results if not r["comparable"]]
    verdicts["F6 thin strata (< 20 rankable)"] = f"{thin or 'clear'}"

    # NULL_DRAWS lives in another module and determines every null's spread, so it is
    # recorded: without it the lift column is uninterpretable from the artifact alone.
    from calibration.trial_pool_unit import NULL_DRAWS
    from sklearn import __version__ as skv
    payload = {
        "n_turns": len(texts), "n_calls": len(calls), "embedder": "gemini-embedding-2@3072",
        "seed": a.seed, "folds": a.folds, "fold_sizes": sizes, "recordings": a.recordings,
        "min_cluster_size": MIN_CLUSTER_SIZE, "merge": MERGE,
        "n_clusters": len(clusters), "n_keys": len(keys),
        "n_coachable_keys": len(coach_keys), "label_stats": label_stats,

        "control_source": ADJ.name, "control_neighbours": nt.CONTROL_NEIGHBOURS,
        "gate_null": nt.GATE_NULL, "nulls": list(nt.NULLS), "min_members": nt.MIN_MEMBERS,
        "null_draws": NULL_DRAWS,
        "knn_k": ra.KNN_K, "submeans_per": ra.SUBMEANS_PER, "submeans_max": ra.SUBMEANS_MAX,
        "min_train_members": ra.MIN_TRAIN_MEMBERS, "blend_alphas": list(ra.BLEND_ALPHAS),
        "sklearn": skv, "arms_run": chosen,
        "cross_encoder": (a.xenc_model if a.cross_encoder else None),
        "xenc_k": a.xenc_k, "xenc_members": a.xenc_members, "seconds": round(time.time() - t0, 1),
        "arms": results, "round_trip": round_trip, "verdicts": verdicts,
        "spend": {"chat_calls": 0, "embedding_texts_offered": n_variant_texts,
                  "postgres_writes": 0},
    }

    if OUT.exists() and not a.force:
        prev = json.loads(OUT.read_text(encoding="utf-8-sig"))
        if prev.get("n_turns", 0) > len(texts):
            raise SystemExit(
                f"REFUSING TO OVERWRITE: {OUT.name} holds a {prev['n_turns']}-turn run "
                f"(recordings={prev.get('recordings', '?')}); this run has only "
                f"{len(texts)}. Re-run with --force if that is genuinely intended.")
    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}")
    print("Zero chat calls, zero embedding requests, zero Postgres writes.")


if __name__ == "__main__":
    main()
