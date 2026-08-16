#!/usr/bin/env python3
"""Is the 47% HDBSCAN noise a parameter artifact or genuine structure? Free, read-only.

Follows the routing-method search (spec 2026-08-16-layer-a-routing-method-design.md), which
closed with "the clusters are the ceiling". Before any clustering arm is pre-registered, this
answers the brief's ordered question: are the ~11.7k noise turns (47% of the 23,949-turn pool)
genuinely unclusterable content, or an artifact of UMAP/HDBSCAN parameters?

WHAT THIS IS AND IS NOT. This is a DIAGNOSTIC: it reports structure (noise rates, geometry,
soft-membership mass, what parameter probes do to the noise fraction and its composition).
It deliberately does NOT compute the coherence-vs-null gate for any probe -- choosing arms by
their gate score before pre-registration is how a result gets tuned into existence. Arms are
chosen from this diagnostic's STRUCTURAL findings; the gate is run once, later, on
pre-registered arms (see the clustering-arms spec).

Production fidelity: the pool comes from routing_bench.build_pool (production entry point,
Avoma roster), vectors from its cache-only embedder (a miss ABORTS), and the clustering from
v2.layer_a.fit_topic_model at the adjudicated min_cluster_size=16 / merge=0.97, joined
position-for-position against adjudicate_gemini_min16.json via null_test_taxonomy.verify_join.
The HDBSCAN parameter probes run on the FITTED BERTopic model's own UMAP space
(tm.umap_model.embedding_), so they vary exactly one stage; the baseline probe must reproduce
the production partition bit-for-bit or the run aborts.

Stages (separate processes -- one process holding two UMAP fits fails on this machine, see
trial_pool_unit.py's --load note):
    --stage main             census, geometry, soft membership, HDBSCAN probes  (~15 min)
    --stage noise-recluster  re-cluster the noise subset alone, scale-matched   (~5 min)
    --load                   re-report the artifact, free

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/diagnose_layer_a_noise.py --stage main
    ..\\.venv\\Scripts\\python.exe calibration/diagnose_layer_a_noise.py --stage noise-recluster
    ..\\.venv\\Scripts\\python.exe calibration/diagnose_layer_a_noise.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "layer_a_noise_diagnostic.json"
SEED = 42
MIN_CLUSTER_SIZE = 16          # must match the adjudication artifact being joined against
MERGE = 0.97                   # ditto
WC_BANDS = ((0, 9), (10, 24), (25, 49), (50, 99), (100, 199), (200, 10 ** 9))
SAMPLES = 12


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", default="main", choices=("main", "noise-recluster"))
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--load", action="store_true")
    return p.parse_args()


def content_free_flags(texts: list[str]) -> list[bool]:
    """True = content-free, via the SAME predicate as cluster_evidence.is_substantive(t, 5).

    Batched through the module's own nlp object for speed (24k one-at-a-time calls cost
    minutes), then VERIFIED against the production function on a 300-item sample -- if the
    batched path ever disagrees, the run aborts rather than shipping a drifted proxy.
    """
    from shared import cluster_evidence

    cluster_evidence.is_substantive("warm the model", 5)   # loads _nlp as production does
    nlp = cluster_evidence._nlp
    flags = []
    for doc in nlp.pipe(texts, batch_size=256):
        flags.append(sum(1 for t in doc if t.is_alpha and not t.is_stop) < 5)
    rng = random.Random(SEED)
    for i in rng.sample(range(len(texts)), min(300, len(texts))):
        if flags[i] != (not cluster_evidence.is_substantive(texts[i], 5)):
            raise SystemExit(f"PROXY DRIFT at item {i}: batched flag disagrees with "
                             f"cluster_evidence.is_substantive. Diagnostic void.")
    return flags


def wc_band(w: int) -> str:
    for lo, hi in WC_BANDS:
        if lo <= w <= hi:
            return f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+"
    return "?"


def partition_equal(a: np.ndarray, b: np.ndarray) -> bool:
    """Same partition up to label renaming, INCLUDING the same noise set (-1 stays -1)."""
    if (a == -1).sum() != (b == -1).sum() or not np.array_equal(a == -1, b == -1):
        return False
    m = a != -1
    fwd, bwd = {}, {}
    for x, y in zip(a[m].tolist(), b[m].tolist()):
        if fwd.setdefault(x, y) != y or bwd.setdefault(y, x) != x:
            return False
    return True


def stage_main(a) -> None:
    from calibration import routing_bench as rb
    from calibration import null_test_taxonomy as nt
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model
    import hdbscan as hdb

    t0 = time.time()
    adj_payload = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))
    adj = adj_payload["rows"]

    texts, call_ids = rb.build_pool(a.recordings)
    print(f"{len(texts)} CLIENT turns / {len(set(call_ids))} calls", flush=True)

    # spaCy FIRST (contiguous 392MiB vector table), before UMAP fragments the address space.
    print("content-free flags (spaCy, batched, verified against production) ...", flush=True)
    cfree = content_free_flags(texts)
    word_count = np.array([len(t.split()) for t in texts])

    vecs = rb.embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)

    print("production clustering (fit_topic_model, min_cluster_size=16) ...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)

    # Reproduce the merge exactly as null_test_taxonomy.main does, then verify the join --
    # keywords included -- so every downstream number is provably about the adjudicated
    # clustering and not a lookalike.
    ta = load_tuning().layer_a
    total_calls = len(set(call_ids))
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
        clusters.append({"idxs": idxs, "n": st.n_items, "calls": st.distinct_calls,
                         "keywords": ", ".join(w for w, _ in tm.get_topic(tids[0])[:10])})
    clusters.sort(key=lambda c: c["n"], reverse=True)
    nt.verify_join(clusters, adj)

    clustered = np.zeros(len(texts), dtype=bool)
    own_of = np.full(len(texts), -1, dtype=np.int32)
    for ci, c in enumerate(clusters):
        for i in c["idxs"]:
            clustered[i] = True
            own_of[i] = ci
    noise_idx = np.flatnonzero(~clustered)
    print(f"clustered {int(clustered.sum())} / noise {len(noise_idx)} "
          f"({len(noise_idx) / len(texts) * 100:.1f}%)", flush=True)

    # --- 1. census: noise rate by length band, content-free split ------------------------
    census = {}
    for band in [f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+" for lo, hi in WC_BANDS]:
        census[band] = {"n": 0, "noise": 0, "cfree": 0, "noise_cfree": 0}
    for i in range(len(texts)):
        b = census[wc_band(int(word_count[i]))]
        b["n"] += 1
        b["cfree"] += cfree[i]
        if not clustered[i]:
            b["noise"] += 1
            b["noise_cfree"] += cfree[i]
    n_cf_noise = sum(1 for i in noise_idx if cfree[i])
    n_cf_clustered = sum(1 for i in range(len(texts)) if clustered[i] and cfree[i])

    # --- 2. geometry in the FULL 3072 space ----------------------------------------------
    cents = np.stack([np.asarray(
        cluster_evidence.support_stats([call_ids[i] for i in c["idxs"]], vecs[c["idxs"]],
                                       total_calls).centroid) for c in clusters])
    cents = (cents / (np.linalg.norm(cents, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    sims = np.empty((len(texts), len(cents)), dtype=np.float32)
    for s in range(0, len(texts), 4096):
        sims[s:s + 4096] = vecs[s:s + 4096] @ cents.T
    member_own = np.array([sims[i, own_of[i]] for i in range(len(texts)) if clustered[i]])
    noise_best = sims[noise_idx].max(axis=1)
    member_p = {f"p{q}": float(np.percentile(member_own, q)) for q in (10, 25, 50, 75, 90)}
    noise_p = {f"p{q}": float(np.percentile(noise_best, q)) for q in (10, 25, 50, 75, 90)}
    # the rescuable population: substantive noise whose best centroid cosine is inside the
    # member band (>= member p25)
    subst_noise = np.array([not cfree[i] for i in noise_idx])
    near = noise_best >= member_p["p25"]
    rescuable = int((subst_noise & near).sum())

    # --- 3. HDBSCAN's own soft membership for noise points -------------------------------
    print("soft membership (all_points_membership_vectors) ...", flush=True)
    try:
        mv = hdb.all_points_membership_vectors(tm.hdbscan_model)
        noise_soft = mv[noise_idx].max(axis=1)
        soft_p = {f"p{q}": float(np.percentile(noise_soft, q)) for q in (10, 25, 50, 75, 90)}
        soft_ge_05 = int((noise_soft >= 0.5).sum())
        soft_ge_02 = int((noise_soft >= 0.2).sum())
    except Exception as exc:                                   # noqa: BLE001
        print(f"  soft membership unavailable: {type(exc).__name__}: {exc}", flush=True)
        soft_p, soft_ge_05, soft_ge_02 = {}, -1, -1

    # --- 4. HDBSCAN parameter probes on the FITTED UMAP space ----------------------------
    # Varying exactly one stage: same 5-d embedding HDBSCAN actually saw. STRUCTURE ONLY --
    # noise rate and composition; no coherence gate here, by design (see module docstring).
    X5 = np.asarray(tm.umap_model.embedding_, dtype=np.float64)
    if X5.shape != (len(texts), 5):
        raise SystemExit(f"UMAP embedding shape {X5.shape} != ({len(texts)}, 5)")

    def probe(ms, method, eps):
        h = hdb.HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, min_samples=ms, metric="euclidean",
                        cluster_selection_method=method, cluster_selection_epsilon=eps)
        lab = h.fit_predict(X5)
        ncl = len(set(lab.tolist())) - (1 if -1 in lab else 0)
        noise = float((lab == -1).mean())
        # composition of the CLUSTERED half, cluster-level content-free mix (raw clusters)
        cf_by = defaultdict(lambda: [0, 0])
        for i, l in enumerate(lab):
            if l != -1:
                cf_by[int(l)][0] += 1
                cf_by[int(l)][1] += cfree[i]
        subj = sum(1 for n_, c_ in cf_by.values() if c_ / n_ < 0.30)
        junk = sum(1 for n_, c_ in cf_by.values() if c_ / n_ >= 0.70)
        clustered_i = [i for i, l in enumerate(lab) if l != -1]
        cf_share = float(np.mean([cfree[i] for i in clustered_i])) if clustered_i else float("nan")
        return lab, {"min_samples": ms, "method": method, "epsilon": round(eps, 4),
                     "noise": noise, "raw_clusters": ncl, "subject_bearing": subj,
                     "junk_70": junk, "clustered_cfree_share": cf_share}

    # baseline must reproduce production bit-for-bit (up to label renaming) or the probe
    # space is not the production space and nothing downstream may be read.
    base_lab, base_row = probe(max(2, MIN_CLUSTER_SIZE // 3), "eom", 0.0)
    if not partition_equal(base_lab, topics):
        raise SystemExit("BASELINE PROBE MISMATCH: HDBSCAN re-run on the fitted UMAP space "
                         "does not reproduce production topics. Probes are void.")
    print("baseline probe reproduces the production partition exactly", flush=True)
    base_row["note"] = "PRODUCTION BASELINE (reproduced exactly)"

    # data-derived epsilon candidates: percentiles of the pool's own core-distance proxy
    # (k-th neighbour distance in the reduced space, k = production min_samples)
    from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=max(2, MIN_CLUSTER_SIZE // 3) + 1).fit(X5)
    dk = nn.kneighbors(X5)[0][:, -1]
    eps_cands = {f"core_p{q}": float(np.percentile(dk, q)) for q in (25, 50, 75)}

    probes = [base_row]
    for ms in (2, 3, 8, 16):
        if ms == max(2, MIN_CLUSTER_SIZE // 3):
            continue
        probes.append(probe(ms, "eom", 0.0)[1])
    probes.append(probe(max(2, MIN_CLUSTER_SIZE // 3), "leaf", 0.0)[1])
    probes.append(probe(2, "leaf", 0.0)[1])
    for name, e in eps_cands.items():
        r = probe(max(2, MIN_CLUSTER_SIZE // 3), "eom", e)[1]
        r["epsilon_source"] = name
        probes.append(r)
    for r in probes:
        print(f"  probe ms={r['min_samples']:>2} {r['method']:<4} eps={r['epsilon']:<7} "
              f"noise={r['noise'] * 100:5.1f}%  raw={r['raw_clusters']:>3}  "
              f"subj={r['subject_bearing']:>3}  junk={r['junk_70']:>3}", flush=True)

    # --- 5. read samples: the two poles of the noise pool --------------------------------
    rng = random.Random(SEED)
    subst_near = [int(i) for i, s, nb in zip(noise_idx, subst_noise, near) if s and nb]
    subst_far = [int(i) for i, s, nb in zip(noise_idx, subst_noise, near) if s and not nb]
    sample_near = [{"i": i, "wc": int(word_count[i]), "best_sim": float(sims[i].max()),
                    "nearest": clusters[int(sims[i].argmax())]["keywords"][:60],
                    "text": texts[i][:220]}
                   for i in rng.sample(subst_near, min(SAMPLES, len(subst_near)))]
    sample_far = [{"i": i, "wc": int(word_count[i]), "best_sim": float(sims[i].max()),
                   "text": texts[i][:220]}
                  for i in rng.sample(subst_far, min(SAMPLES, len(subst_far)))]

    payload = {
        "stage_main": {
            "n_turns": len(texts), "n_calls": total_calls,
            "min_cluster_size": MIN_CLUSTER_SIZE, "merge": MERGE, "seed": SEED,
            "n_raw_topics": len(raw_ids), "n_surviving_clusters": len(clusters),
            "n_clustered": int(clustered.sum()), "n_noise": int(len(noise_idx)),
            "noise_rate": float(len(noise_idx) / len(texts)),
            "census_by_band": census,
            "noise_cfree": n_cf_noise, "clustered_cfree": n_cf_clustered,
            "member_own_centroid_cos": member_p, "noise_best_centroid_cos": noise_p,
            "noise_substantive": int(subst_noise.sum()),
            "noise_substantive_near_member_p25": rescuable,
            "soft_membership_noise_max": soft_p,
            "soft_ge_0.5": soft_ge_05, "soft_ge_0.2": soft_ge_02,
            "eps_candidates": eps_cands, "probes": probes,
            "samples_substantive_near": sample_near,
            "samples_substantive_far": sample_far,
            "noise_idx": [int(i) for i in noise_idx],
            "seconds": round(time.time() - t0, 1),
        }
    }
    if OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8-sig"))
        old.update(payload)
        payload = old
    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}\nZero chat calls, zero embedding requests, zero Postgres writes.")


def stage_noise(a) -> None:
    """Re-cluster the noise subset ALONE, scale-matched, in its own process."""
    from calibration import routing_bench as rb
    from v2.layer_a import fit_topic_model

    t0 = time.time()
    payload = json.loads(OUT.read_text(encoding="utf-8-sig"))
    sm = payload.get("stage_main")
    if not sm:
        raise SystemExit("run --stage main first")
    texts, call_ids = rb.build_pool(a.recordings)
    if len(texts) != sm["n_turns"]:
        raise SystemExit(f"pool changed: {len(texts)} vs artifact {sm['n_turns']}")
    noise_idx = sm["noise_idx"]
    ntexts = [texts[i] for i in noise_idx]
    ncalls = [call_ids[i] for i in noise_idx]

    print("content-free flags for the noise subset ...", flush=True)
    cfree = content_free_flags(ntexts)

    vecs = rb.embed_cache_only(ntexts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)

    # scale-matched min_cluster_size: the production 16 is 0.0668% of the 23,949 pool; the
    # same FRACTION of the noise pool. A fixed 16 would be a ~2x stiffer relative bar --
    # the exact pool-size trap fit_topic_model's own docstring documents.
    mcs = max(3, round(MIN_CLUSTER_SIZE * len(ntexts) / sm["n_turns"]))
    print(f"re-clustering {len(ntexts)} noise turns alone, min_cluster_size={mcs} "
          f"(scale-matched) ...", flush=True)
    tm, topics = fit_topic_model(ntexts, vecs, min_cluster_size=mcs)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    n_cl = int((topics != -1).sum())
    rows = []
    for t in sorted(members, key=lambda t: -len(members[t])):
        idxs = members[t]
        cf = sum(cfree[i] for i in idxs) / len(idxs)
        rows.append({"topic": int(t), "n": len(idxs),
                     "calls": len({ncalls[i] for i in idxs}), "cfree": round(cf, 3),
                     "keywords": ", ".join(w for w, _ in tm.get_topic(t)[:8]),
                     "samples": [ntexts[i][:150] for i in random.Random(SEED).sample(
                         idxs, min(3, len(idxs)))]})
    payload["stage_noise"] = {
        "n_noise": len(ntexts), "min_cluster_size": mcs,
        "n_reclustered": n_cl, "reclustered_share": n_cl / len(ntexts),
        "n_clusters": len(rows),
        "subject_bearing": sum(1 for r in rows if r["cfree"] < 0.30),
        "junk_70": sum(1 for r in rows if r["cfree"] >= 0.70),
        "clusters": rows, "seconds": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}\nZero chat calls, zero embedding requests, zero Postgres writes.")


def report(p: dict) -> None:
    sm = p.get("stage_main")
    if sm:
        print("\n" + "=" * 92)
        print("NOISE DIAGNOSTIC -- is 47% noise a parameter artifact or genuine?")
        print("=" * 92)
        print(f"  pool {sm['n_turns']} turns / {sm['n_calls']} calls   "
              f"raw topics {sm['n_raw_topics']} -> surviving clusters "
              f"{sm['n_surviving_clusters']}")
        print(f"  noise {sm['n_noise']} ({sm['noise_rate'] * 100:.1f}%)   "
              f"content-free: {sm['noise_cfree']}/{sm['n_noise']} of noise "
              f"({sm['noise_cfree'] / sm['n_noise'] * 100:.0f}%) vs "
              f"{sm['clustered_cfree']}/{sm['n_clustered']} of clustered "
              f"({sm['clustered_cfree'] / sm['n_clustered'] * 100:.0f}%)")
        print(f"\n  {'band':>8}{'n':>7}{'noise%':>8}{'cfree%':>8}{'noise cfree%':>13}")
        for band, b in sm["census_by_band"].items():
            if not b["n"]:
                continue
            print(f"  {band:>8}{b['n']:>7}{b['noise'] / b['n'] * 100:>7.1f}%"
                  f"{b['cfree'] / b['n'] * 100:>7.1f}%"
                  + (f"{b['noise_cfree'] / b['noise'] * 100:>12.1f}%" if b["noise"] else ""))
        print(f"\n  geometry (3072-space): member cos to OWN centroid "
              f"p25={sm['member_own_centroid_cos']['p25']:.3f} "
              f"p50={sm['member_own_centroid_cos']['p50']:.3f}")
        print(f"  noise best cos to ANY centroid "
              f"p25={sm['noise_best_centroid_cos']['p25']:.3f} "
              f"p50={sm['noise_best_centroid_cos']['p50']:.3f} "
              f"p90={sm['noise_best_centroid_cos']['p90']:.3f}")
        print(f"  substantive noise turns: {sm['noise_substantive']} "
              f"({sm['noise_substantive'] / sm['n_noise'] * 100:.0f}% of noise); of those, "
              f"{sm['noise_substantive_near_member_p25']} sit inside the member band "
              f"(best cos >= member p25) -- the rescuable population")
        if sm.get("soft_membership_noise_max"):
            print(f"  HDBSCAN soft membership, noise max-prob: "
                  f"p50={sm['soft_membership_noise_max'].get('p50', float('nan')):.3f} "
                  f"p90={sm['soft_membership_noise_max'].get('p90', float('nan')):.3f}; "
                  f">=0.5: {sm['soft_ge_0.5']}, >=0.2: {sm['soft_ge_0.2']}")
        print(f"\n  HDBSCAN probes on the fitted UMAP space (structure only, NOT the gate):")
        print(f"  {'min_samples':>12}{'method':>7}{'eps':>9}{'noise%':>8}{'raw':>6}"
              f"{'subj':>6}{'junk':>6}{'cfree%':>8}")
        for r in sm["probes"]:
            print(f"  {r['min_samples']:>12}{r['method']:>7}{r['epsilon']:>9}"
                  f"{r['noise'] * 100:>7.1f}%{r['raw_clusters']:>6}{r['subject_bearing']:>6}"
                  f"{r['junk_70']:>6}{r['clustered_cfree_share'] * 100:>7.1f}%"
                  + ("  " + r.get("note", "") if r.get("note") else "")
                  + ("  " + r.get("epsilon_source", "") if r.get("epsilon_source") else ""))
        print("\n  -- substantive noise NEAR a cluster (rescue candidates) --")
        for s in sm["samples_substantive_near"]:
            print(f"   [{s['best_sim']:.3f} vs {s['nearest'][:40]}] {s['text'][:150]}")
        print("\n  -- substantive noise FAR from every cluster --")
        for s in sm["samples_substantive_far"]:
            print(f"   [{s['best_sim']:.3f}] {s['text'][:150]}")
    sn = p.get("stage_noise")
    if sn:
        print("\n" + "=" * 92)
        print("NOISE-ONLY RECLUSTERING -- does structure hide inside the noise?")
        print("=" * 92)
        print(f"  {sn['n_noise']} noise turns, min_cluster_size={sn['min_cluster_size']} "
              f"(scale-matched)")
        print(f"  reclustered: {sn['n_reclustered']} ({sn['reclustered_share'] * 100:.1f}%) "
              f"into {sn['n_clusters']} clusters; subject-bearing {sn['subject_bearing']}, "
              f"junk(>=70% cfree) {sn['junk_70']}")
        for r in sn["clusters"][:15]:
            print(f"\n  n={r['n']:>4} calls={r['calls']:>3} cfree={r['cfree']:.2f}  "
                  f"{r['keywords'][:70]}")
            for s in r["samples"]:
                print(f"     | {s}")


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return
    if a.stage == "main":
        stage_main(a)
    else:
        stage_noise(a)


if __name__ == "__main__":
    main()
