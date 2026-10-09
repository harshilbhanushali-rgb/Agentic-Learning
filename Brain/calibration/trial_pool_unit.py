#!/usr/bin/env python3
"""Does clustering whole CLIENT turns beat clustering sentence fragments? (free)

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

THE PROBLEM. Layer A clusters CLAUSES while Layer B matches TURNS. The clause split
severs a stance sentence from the subject it arrived with -- one turn "Yeah. That makes
sense. So for the ATS integration, do we need a pixel?" becomes TWO pool items, one
carrying no subject at all. 59.1% of the clause pool (43,566 of 73,771) is content-free
as a result, and that is the raw material every posture scenario is built from.

Zero Gemma calls, zero DB writes, zero Pinecone. Embeddings are local and cached.
Imports production code (build_client_pool, fit_topic_model, cluster_evidence) rather
than reimplementing it -- this codebase has been burned by a dry run that reimplemented
Layer B and disagreed with production by 99.7% vs 14%.

WHAT THIS CAN AND CANNOT MEASURE -- read before trusting a number.

  The 21/68 baseline in the spec is a SCENARIO-level figure: post-Gemma-adjudication,
  post-merge, with pairs assigned by Layer B. A free harness cannot reach that -- naming
  and coachability are Gemma's call. This measures CLUSTER level, pre-Gemma.

  So the operative comparison is CLAUSE ARM vs TURN ARM INSIDE THIS HARNESS, which is
  symmetric by construction. The spec's ">= 50%" bar was anchored to the scenario-level
  31% and is NOT directly comparable here; it is re-anchored to the clause arm's own
  value in this same run. Reported as such, not silently substituted.

SYMMETRY. Each arm is scored on its own NATIVE members against a null drawn from that
SAME unit population, so lift-over-null is unit-normalised. Scoring turn-arm clusters
with clause vectors (or vice versa) would count the unit change twice -- the asymmetric
comparison bug this codebase has hit four times.

THE FOUR GATE CHECKS.
  1. share of clusters clearing a size-matched random null by >= 0.05
  2. does a backchannel SINK still form? (Layer D's rejection depends on it)
  3. sampled clusters read as situations -- seeded and stratified, NEVER the first N
  4. stance distinguishability -- do negated turns concentrate, or spread evenly?
     Check 1 CANNOT catch stance collapse; it rewards it, because a pure-topic cluster
     is maximally homogeneous. Same defect class as the skills sweep's
     cross_scenario_coverage, which could only ever say yes.

Usage (from Brain/, venv active):
    python calibration/trial_pool_unit.py --smoke        # ~30 transcripts, path test
    python calibration/trial_pool_unit.py                # full 416-call corpus
    python calibration/trial_pool_unit.py --load PATH    # re-report, free
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

NULL_DRAWS = 20            # random draws per size when building the size-matched null
NULL_LIFT_BAR = 0.05       # a cluster "clears" if coherence exceeds its null by this
SHUFFLES = 200             # permutations for the stance-concentration null
SAMPLES_TO_READ = 10
SEED = 42


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--smoke", action="store_true",
                   help="30 transcripts, exercises every code path cheaply. "
                        "ALWAYS run this before the full run -- py_compile does not "
                        "catch a bad slice or a missing import inside a branch")
    p.add_argument("--arms", default="clause,turn")
    p.add_argument("--merge-sweep", default="",
                   help="comma-separated merge thresholds to evaluate against ONE clustering "
                        "pass. DESCRIPTIVE sensitivity only -- the adopted value is 0.92, "
                        "derived by reading merge groups before any trial ran at it. Do NOT "
                        "pick the best row here; that is the tuned-result failure mode")
    p.add_argument("--merge-threshold", type=float, default=0.0,
                   help="override merge_cosine_threshold. REQUIRED for the turn arm: the "
                        "shipped 0.85 was derived by reading CLAUSE-level merge groups, and "
                        "turn-level cosines sit in a higher, tighter band. Turn's independently "
                        "derived equivalent is 0.92 (see logs/merge_detail_turn.log). Each arm "
                        "must run at ITS OWN derived value or the comparison measures the "
                        "threshold instead of the unit")
    p.add_argument("--min-cluster-size", type=int, default=0,
                   help="override HDBSCAN min_cluster_size. REQUIRED when comparing pools "
                        "of different item counts: the production formula is a hardcoded 50 "
                        "for any corpus >= 500 items, so 50 is 0.068%% of the clause pool but "
                        "0.209%% of the turn pool -- a 3x stiffer relative bar that would "
                        "measure the bar instead of the pools")
    p.add_argument("--load", default="",
                   help="re-report persisted artifact(s), free. Accepts a comma-separated "
                        "list and merges their arms, so the two arms can be run in "
                        "SEPARATE processes -- each releases its memory on exit, which "
                        "matters because one process holding two 768-dim pools plus two "
                        "UMAP fits is what makes this machine's spaCy/torch allocation fail")
    p.add_argument("--out", default="")
    return p.parse_args()


def coherence(vectors: np.ndarray) -> float:
    """Mean cosine of each member to the centroid. Same definition as
    calibration/scenario_coherence.py, deliberately -- the numbers must be comparable.
    """
    if len(vectors) < 2:
        return float("nan")
    v = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    c = v.mean(axis=0)
    c /= np.linalg.norm(c) + 1e-10
    return float((v @ c).mean())


def size_matched_null(pool: np.ndarray, n: int, rng: random.Random,
                      draws: int = NULL_DRAWS) -> float:
    """Mean coherence of `draws` random subsets of size n drawn from the whole pool.

    Size-matched because random-subset coherence falls as n rises -- comparing a
    4,000-member cluster against a null built at n=50 would manufacture a lift.
    """
    vals = []
    for _ in range(draws):
        idx = rng.sample(range(len(pool)), min(n, len(pool)))
        vals.append(coherence(pool[idx]))
    return float(np.mean(vals))


def _load_turns(recordings: str, limit: int, config):
    from preprocessing.transcript_parser import parse_transcript, load_roster

    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt transcripts in {recordings}/")
    if limit:
        files = files[:limit]
    turns = []
    for f in files:
        turns.extend(parse_transcript(str(f), config.joveo_speakers_lower,
                                      config.naren_name_lower, load_roster(str(f))))
    return turns, len(files)


def _negation_flags(texts: list[str]) -> list[bool]:
    """True if the item contains syntactic negation, via spaCy's `neg` dependency.

    A PARSER OUTPUT, not a hand-written marker list -- a curated list would be the
    "a threshold must never be a curated list" anti-pattern. Verified on real phrasing:
    "No, we don't have budget" -> True (n't); "Tell me more about the budget" -> False.

    STATED LIMIT: this is syntactic negation, a SUBSET of pushback. "We already have an
    ATS in place." is a refusal in substance and carries no `neg`. Acceptable because
    check 4 is distributional -- it asks whether ANY stance signal survives clustering,
    not whether every instance is caught -- and because this is a measurement
    instrument, never a shipped knob.
    """
    import spacy
    nlp = spacy.load("en_core_web_lg", disable=["ner", "lemmatizer", "attribute_ruler"])
    out = []
    for doc in nlp.pipe(texts, batch_size=64):
        out.append(any(t.dep_ == "neg" for t in doc))
    return out


def run_arm(arm: str, all_turns, total_calls: int, ta, min_cluster_size: int = 0,
            merge_threshold: float = 0.0, sweep: tuple = ()) -> dict:
    """Cluster one arm through the PRODUCTION path and score all four gate checks."""
    from shared import cluster_evidence
    from preprocessing import embedder
    from v2.layer_a import build_client_pool, fit_topic_model

    rng = random.Random(SEED)
    unit = "turn" if arm.startswith("turn") else "clause"
    min_words = ta.min_content_words if arm.endswith("prefilter") else 0

    texts, call_ids = build_client_pool(all_turns, unit=unit, min_content_words=min_words)
    print(f"\n[{arm}] pool: {len(texts)} item(s) [unit={unit}"
          f"{', prefiltered' if min_words else ''}]. Embedding...", flush=True)
    vecs = embedder.embed_query_matrix(texts)

    # --- content-free supply: the posture raw material -------------------------------
    thin = sum(1 for t in texts if not cluster_evidence.is_substantive(t, 5))
    print(f"[{arm}] content-free items: {thin}/{len(texts)} ({thin/len(texts)*100:.1f}%)",
          flush=True)

    mcs = min_cluster_size or max(3, min(len(texts) // 10, 50))
    print(f"[{arm}] clustering (UMAP + HDBSCAN), min_cluster_size={mcs} "
          f"({mcs/len(texts)*100:.3f}% of pool)...", flush=True)
    topic_model, topics = fit_topic_model(texts, vecs,
                                          min_cluster_size=min_cluster_size or None)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    n_outliers = sum(1 for t in topics if t == -1)
    if not raw_ids:
        raise SystemExit(f"[{arm}] BERTopic produced no clusters.")
    print(f"[{arm}] {len(raw_ids)} raw cluster(s), {n_outliers} outlier(s) "
          f"({n_outliers/len(texts)*100:.1f}%)", flush=True)

    centroids = np.stack([
        cluster_evidence.support_stats([call_ids[i] for i in members[t]],
                                       vecs[members[t]], total_calls).centroid
        for t in raw_ids
    ])

    # --- merge + triage, production helpers -----------------------------------------
    merge = merge_threshold or ta.merge_cosine_threshold
    groups = cluster_evidence.merge_by_similarity(centroids, merge)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    print(f"[{arm}] merge at >= {merge}: "
          f"{len(raw_ids)} -> {len(groups)} cluster(s); "
          f"support floor {min_support} distinct calls", flush=True)

    # --- stance flags, once over the whole pool -------------------------------------
    print(f"[{arm}] tagging negation over {len(texts)} item(s)...", flush=True)
    neg = _negation_flags(texts)
    print(f"[{arm}] negated items: {sum(neg)}/{len(texts)} ({sum(neg)/len(texts)*100:.1f}%)",
          flush=True)

    sweep_rows = []
    if sweep:
        print(f"[{arm}] merge sensitivity sweep (one clustering pass):", flush=True)
        sweep_rows = merge_sweep(arm, texts, vecs, call_ids, members, raw_ids, centroids,
                                 neg, total_calls, ta, sweep)

    clusters = []
    for group in groups:
        tids = [raw_ids[g] for g in group]
        idxs = [i for t in tids for i in members[t]]
        ctexts = [texts[i] for i in idxs]
        stats = cluster_evidence.support_stats(
            [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=ctexts)
        verdict = cluster_evidence.triage(stats, min_support, ta.ubiquity_ceiling)
        if verdict == cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        coh = coherence(vecs[idxs])
        null = size_matched_null(vecs, len(idxs), rng)
        n_thin = sum(1 for t in ctexts if not cluster_evidence.is_substantive(t, 5))
        n_neg = sum(1 for i in idxs if neg[i])
        clusters.append({
            "keywords": ", ".join(w for w, _ in topic_model.get_topic(tids[0])[:6]),
            "n_items": len(idxs),
            "distinct_calls": stats.distinct_calls,
            "call_coverage": stats.call_coverage,
            "verdict": verdict,
            "coherence": coh,
            "null": null,
            "lift": coh - null,
            "thin_fraction": n_thin / len(idxs),
            "neg_rate": n_neg / len(idxs),
            "samples": [" ".join(t.split()) for t in rng.sample(ctexts, min(6, len(ctexts)))],
        })
    clusters.sort(key=lambda c: -c["n_items"])

    # --- check 1: share clearing the size-matched null -------------------------------
    cleared = [c for c in clusters if c["lift"] >= NULL_LIFT_BAR]
    share = len(cleared) / len(clusters) if clusters else 0.0

    # --- check 2: does a backchannel sink still form? --------------------------------
    # Gemma decides coachability, which is not free. The measurable proxy is whether a
    # cluster exists that is PREDOMINANTLY content-free -- that is what Gemma sinks.
    sinkish = [c for c in clusters if c["thin_fraction"] >= 0.70]

    # --- check 4: stance distinguishability -----------------------------------------
    # Size-weighted variance of per-cluster negation rate, against a shuffled baseline.
    # High variance => some clusters are stance-heavy => stance survived clustering.
    # Low/at-null => stance was ignored and we collapsed to pure topic.
    sizes = np.array([c["n_items"] for c in clusters], dtype=float)
    rates = np.array([c["neg_rate"] for c in clusters], dtype=float)
    w = sizes / sizes.sum()
    observed = float(np.sum(w * (rates - np.sum(w * rates)) ** 2))
    flat = np.array(neg, dtype=float)
    shuffle_rng = np.random.default_rng(SEED)
    null_vars = []
    for _ in range(SHUFFLES):
        perm = shuffle_rng.permutation(flat)
        cursor, rs = 0, []
        for n in sizes.astype(int):
            rs.append(perm[cursor:cursor + n].mean() if n else 0.0)
            cursor += n
        rs = np.array(rs)
        null_vars.append(float(np.sum(w * (rs - np.sum(w * rs)) ** 2)))
    stance_null = float(np.mean(null_vars))
    stance_ratio = observed / stance_null if stance_null > 0 else float("inf")

    return {
        "arm": arm, "unit": unit, "min_content_words": min_words,
        "min_cluster_size": mcs,
        "merge_threshold": merge,
        "merge_sweep": sweep_rows,
        "pool_items": len(texts), "content_free_items": thin,
        "raw_clusters": len(raw_ids), "outliers": n_outliers,
        "merged_clusters": len(groups), "surviving_clusters": len(clusters),
        "negated_items": int(sum(neg)),
        "check1_share_clearing_null": share,
        "check1_cleared": len(cleared),
        "check2_sinkish_clusters": len(sinkish),
        "check2_largest_sinkish_items": max((c["n_items"] for c in sinkish), default=0),
        "check4_stance_variance": observed,
        "check4_stance_null": stance_null,
        "check4_ratio": stance_ratio,
        "clusters": clusters,
    }



def merge_sweep(arm, texts, vecs, call_ids, members, raw_ids, centroids, neg,
                total_calls, ta, thresholds):
    """Evaluate MANY merge thresholds against ONE clustering pass.

    Clustering (UMAP+HDBSCAN) and negation tagging are the expensive steps and are
    independent of the merge threshold, so a sensitivity curve costs almost nothing
    once they are done. Deliberately skips the size-matched null: check 1 was RETIRED
    (it correlates +0.53 with content-free fraction, i.e. it rewards the junk), so
    paying 20 draws per cluster per threshold would buy a number we do not use.

    This is DESCRIPTIVE, not a selection procedure. The adopted value is 0.92, derived
    independently by reading merge groups before any trial ran at it. Picking whichever
    threshold maximises the headline here would be exactly the tuned-result failure the
    pre-registration in the spec exists to prevent.
    """
    from shared import cluster_evidence

    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    rows = []
    for t in thresholds:
        groups = cluster_evidence.merge_by_similarity(centroids, t)
        surviving = []
        for group in groups:
            tids = [raw_ids[g] for g in group]
            idxs = [i for tt in tids for i in members[tt]]
            ctexts = [texts[i] for i in idxs]
            stats = cluster_evidence.support_stats(
                [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=ctexts)
            if cluster_evidence.triage(stats, min_support, ta.ubiquity_ceiling) ==                     cluster_evidence.INSUFFICIENT_EVIDENCE:
                continue
            thin = sum(1 for x in ctexts if not cluster_evidence.is_substantive(x, 5))
            surviving.append({
                "n": len(idxs), "thin": thin / len(idxs),
                "neg": sum(1 for i in idxs if neg[i]) / len(idxs),
                "n_raw": len(tids),
            })
        n = len(surviving) or 1
        subj = [c for c in surviving if c["thin"] < 0.30]
        junk = [c for c in surviving if c["thin"] >= 0.70]
        rows.append({
            "threshold": t, "groups": len(groups), "surviving": len(surviving),
            "subject_bearing": len(subj), "subject_share": len(subj) / n,
            "junk": len(junk), "junk_share": len(junk) / n,
            "largest_n_raw": max((c["n_raw"] for c in surviving), default=0),
            "largest_items": max((c["n"] for c in surviving), default=0),
            "subj_mean_neg": (sum(c["neg"] for c in subj) / len(subj)) if subj else 0.0,
        })
        r = rows[-1]
        print(f"  [{arm}] merge {t:.2f}: {r['surviving']:>4} surviving | "
              f"subject-bearing {r['subject_bearing']:>3} ({r['subject_share']*100:>5.1f}%) | "
              f"junk {r['junk']:>3} ({r['junk_share']*100:>5.1f}%) | "
              f"largest {r['largest_n_raw']:>2} raw / {r['largest_items']:>4} items", flush=True)
    return rows


def _stratified_sample(clusters: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Seeded and stratified over the coherence range -- NEVER the first N.

    An alphabetical prefix once returned nothing but subject-matter scenarios, because
    every posture key begins `client_`, silently testing a fix on the half that already
    worked. The same trap applies to "the biggest N clusters".
    """
    if len(clusters) <= k:
        return list(clusters)
    ordered = sorted(clusters, key=lambda c: c["lift"])
    edges = np.linspace(0, len(ordered), k + 1).astype(int)
    return [rng.choice(ordered[a:b]) for a, b in zip(edges[:-1], edges[1:]) if b > a]


def report(payload: dict) -> None:
    arms = payload["arms"]
    print("\n" + "=" * 78)
    print("POOL UNIT TRIAL -- clause (control) vs turn (treatment)")
    print("=" * 78)
    print(f"corpus: {payload['total_calls']} transcripts\n")

    print(f"{'arm':<18} {'pool':>8} {'content-free':>13} {'raw':>6} {'outlier%':>9} "
          f"{'survive':>8}")
    for a in arms:
        print(f"{a['arm']:<18} {a['pool_items']:>8} "
              f"{a['content_free_items']/a['pool_items']*100:>12.1f}% "
              f"{a['raw_clusters']:>6} {a['outliers']/a['pool_items']*100:>8.1f}% "
              f"{a['surviving_clusters']:>8}")

    print("\nCHECK 1 -- share of surviving clusters beating a size-matched random null")
    for a in arms:
        print(f"  {a['arm']:<18} {a['check1_cleared']:>4}/{a['surviving_clusters']:<4} "
              f"= {a['check1_share_clearing_null']*100:>5.1f}%")

    print("\nCHECK 2 -- does a backchannel sink still form? (>= 70% content-free members)")
    for a in arms:
        verdict = "YES" if a["check2_sinkish_clusters"] else "NO -- Layer D rejection at risk"
        print(f"  {a['arm']:<18} {a['check2_sinkish_clusters']:>3} cluster(s), "
              f"largest {a['check2_largest_sinkish_items']:>6} items   {verdict}")

    print("\nCHECK 4 -- stance distinguishability (size-weighted variance of negation rate)")
    print("           ratio ~1.0 = stance IGNORED (collapsed to pure topic); >1 = captured")
    for a in arms:
        print(f"  {a['arm']:<18} observed {a['check4_stance_variance']:.5f}  "
              f"null {a['check4_stance_null']:.5f}  ratio {a['check4_ratio']:>6.2f}")

    rng = random.Random(SEED)
    for a in arms:
        print(f"\n{'-'*78}\nCHECK 3 -- {SAMPLES_TO_READ} stratified clusters from "
              f"{a['arm']} (read these)\n{'-'*78}")
        for c in _stratified_sample(a["clusters"], SAMPLES_TO_READ, rng):
            print(f"\n  lift {c['lift']:+.3f} (coh {c['coherence']:.3f} vs null "
                  f"{c['null']:.3f})  {c['n_items']} items / {c['distinct_calls']} calls"
                  f"  thin {c['thin_fraction']:.0%}  neg {c['neg_rate']:.0%}")
            print(f"    keywords: {c['keywords']}")
            for s in c["samples"][:4]:
                print(f"      - {s[:110]}")

    if len(arms) >= 2:
        control = next((a for a in arms if a["unit"] == "clause"), arms[0])
        treat = next((a for a in arms if a["unit"] == "turn"), arms[-1])
        d = treat["check1_share_clearing_null"] - control["check1_share_clearing_null"]
        print("\n" + "=" * 78)
        print("VERDICT (arm vs arm -- the spec's 50% bar was a SCENARIO-level figure and "
              "\nis re-anchored here to the control arm's own value)")
        print("=" * 78)
        print(f"  check 1  {control['arm']} {control['check1_share_clearing_null']*100:.1f}% "
              f"-> {treat['arm']} {treat['check1_share_clearing_null']*100:.1f}%  "
              f"({d*100:+.1f} points)")
        print(f"  check 2  sink forms in treatment: "
              f"{'YES' if treat['check2_sinkish_clusters'] else 'NO'}")
        print(f"  check 4  stance ratio {control['check4_ratio']:.2f} -> "
              f"{treat['check4_ratio']:.2f}")
        print("  check 3  requires a human to read the samples above -- not automatable")


def main() -> None:
    args = _args()
    if args.load:
        paths = [p.strip() for p in args.load.split(",") if p.strip()]
        payloads = [json.loads(Path(p).read_text(encoding="utf-8-sig")) for p in paths]
        merged = dict(payloads[0])
        merged["arms"] = [a for p in payloads for a in p["arms"]]
        # Ordered control-first so the verdict block reads clause -> turn regardless of
        # the order the two runs happened to finish in.
        merged["arms"].sort(key=lambda a: 0 if a["unit"] == "clause" else 1)
        if len({p["total_calls"] for p in payloads}) > 1:
            raise SystemExit("Refusing to merge arms measured on different corpora -- "
                             f"total_calls differ: {[p['total_calls'] for p in payloads]}")
        report(merged)
        return

    from config import load_config
    from shared.tuning import load_tuning

    ta = load_tuning().layer_a
    config = load_config()
    limit = 30 if args.smoke else 0
    all_turns, total_calls = _load_turns(args.recordings, limit, config)
    print(f"Parsed {total_calls} transcript(s), {len(all_turns)} turns.")
    if args.smoke:
        print("SMOKE MODE -- path test only. Numbers are NOT interpretable: 30 "
              "transcripts cannot support the thresholds these gates were derived from.")

    payload = {"total_calls": total_calls, "smoke": bool(args.smoke),
               "merge_cosine_threshold": ta.merge_cosine_threshold,
               "null_draws": NULL_DRAWS, "null_lift_bar": NULL_LIFT_BAR,
               "min_cluster_size_override": args.min_cluster_size,
               "merge_threshold_override": args.merge_threshold,
               "merge_sweep_thresholds": args.merge_sweep,
               "arms": [run_arm(a.strip(), all_turns, total_calls, ta, args.min_cluster_size,
                                args.merge_threshold,
                                tuple(float(x) for x in args.merge_sweep.split(",") if x.strip()))
                        for a in args.arms.split(",") if a.strip()]}
    report(payload)

    out = Path(args.out) if args.out else ARTIFACTS_DIR / (
        "pool_unit_trial_smoke.json" if args.smoke else "pool_unit_trial.json")
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
