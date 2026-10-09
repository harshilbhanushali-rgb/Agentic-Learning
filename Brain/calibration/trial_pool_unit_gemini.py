#!/usr/bin/env python3
"""Does the turn-mode pool still produce a good taxonomy on the GEMINI embedder? (no chat calls)

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

WHAT THIS ANSWERS. Turn mode beat clause mode decisively on the LOCAL bge embedder --
subject-bearing clusters 4.7% -> 37.2%, and the two arms' bands never overlapped across
six merge thresholds. All of that is bge. This measures whether the turn-mode taxonomy
still holds up when the vectors come from `gemini-embedding-2` via the Joveo gateway.

WHAT IT DELIBERATELY DOES NOT DO. It does not re-run the clause arm on Gemini (that would
cost another ~74k requests). The UNIT question is settled under bge and its mechanism is
structural -- clause splitting severs a stance sentence from its subject, which is a fact
about `preprocessing/segmenter.py`, not about any embedding. What is genuinely unknown is
whether Gemini's tighter cosine space (spread 0.082 vs bge's 0.141, p50 0.686 vs 0.558)
still lets HDBSCAN separate subject-bearing content from filler. That is what is measured.

Two reasons to expect it works, one to worry:
  + `sink_real_margin` measured 0.561 (bge) -> 0.686 (Gemini), and that signal's documented
    failure was "real and sink centroids sit too close together" -- exactly the separation
    turn mode's benefit rests on.
  + Gemini embeddings are deterministic (cos 1.000000 on repeat), removing one of the two
    sources of this pipeline's run-to-run cluster variance.
  - The space is tighter, and HDBSCAN is density-based. UMAP works on relative distances so
    uniform compression should wash out, but that is reasoning, not measurement.

EMBEDDING SAFETY. One text per request, always. `calibration/trial_gateway.py` measured the
gateway's /embeddings endpoint SILENTLY returning fewer vectors than inputs, intermittently
-- the same request batches or collapses depending on when it is sent, and it hits SHORT
text hardest, which is 29% of this corpus. Batching is not "risky but faster" here, it is
wrong for this population. Throughput comes from concurrency (`--workers`), which cannot
reintroduce the collapse because each request still carries exactly one text.

THRESHOLDS. `merge_cosine_threshold: 0.92` was derived by READING merge groups in bge's
band and is meaningless here. This script measures Gemini's own band and sweeps thresholds,
printing member keywords so the value can be chosen by reading. `min_cluster_size` is a
count of items, not a cosine, so 16 stays scale-matched regardless of embedder.

Vectors are cached to SQLite keyed on (model, dims, text), so the ~24k paid requests are
spent once and every re-run is free -- and a crash at 15k resumes rather than restarting.
Persisting the PAID artifact rather than only the derived scores is the lesson from
`compare_embedders.py`, where changing one criterion cost another 461 requests.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/trial_pool_unit_gemini.py --smoke
    ..\\.venv\\Scripts\\python.exe calibration/trial_pool_unit_gemini.py --workers 20
    ..\\.venv\\Scripts\\python.exe calibration/trial_pool_unit_gemini.py --load
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

EMBED_MODEL = "gemini-embedding-2"
# FETCH AND CACHE AT NATIVE 3072, ALWAYS. Then truncate locally to whatever width is being
# analysed (--width). compare_embedders.py measured gemini_768 slightly BEATING gemini_3072
# on sink_real_margin (0.686 vs 0.672), so 768 may well be the better analysis width -- but
# requesting 768 from the API would lock 24k paid requests to one width, and trial_gateway.py
# measured cos(api_at_768, first_768_of_3072) = 1.000000, i.e. Matryoshka truncation is EXACT.
# So one wide call yields every narrower width for free and a width comparison costs nothing.
#
# THE CACHE KEY USES THIS NATIVE WIDTH AND NEVER THE ANALYSIS WIDTH. Keying on the analysis
# width is the trap: --width 768 would compute a different key, miss every row, and re-pay all
# 24k requests -- which is exactly the "persist the PAID artifact, not the derived scores"
# lesson from compare_embedders.py, reintroduced through the back door.
EMBED_DIMS = 3072
WIDTHS = [3072, 1536, 768, 256]     # any of these is free once 3072 is cached
MIN_CLUSTER_SIZE = 16          # scale-matched to clause's 50/73,771 -- a count, not a cosine
# Extended UPWARD after the smoke test: Gemini centroids sit far closer to each other than
# bge's (centroid-vs-centroid p10=0.802 p50=0.871 p90=0.925), so bge's 0.92 fuses almost
# everything -- 3 surviving clusters on the smoke corpus -- and the subject-bearing share was
# still climbing at 0.96. A sweep that stopped where bge's did would have measured only the
# over-merged end of this backend's range.
SWEEP = [0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98]
CACHE = Path(__file__).resolve().parent.parent / "gemini_embed_cache.db"


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--smoke", action="store_true",
                   help="30 transcripts. ALWAYS run this first -- it exercises the gateway, "
                        "the cache, the concurrency and the artifact write for a few hundred "
                        "requests instead of 24k. Numbers are NOT interpretable (subset).")
    p.add_argument("--width", type=int, default=3072, choices=WIDTHS,
                   help="analysis width, truncated+renormalised from the cached 3072 vectors. "
                        "Changing it costs NOTHING -- the cache is keyed on the native width. "
                        "Run once per width in a SEPARATE process rather than looping widths in "
                        "one: two UMAP fits over a 24k x 3072 matrix in a single process is the "
                        "allocation pattern this machine's spaCy/torch failures come from.")
    p.add_argument("--show", type=int, default=6, help="merge groups printed per threshold")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    return p.parse_args()


# -- cache -----------------------------------------------------------------------------

def _cache_open() -> sqlite3.Connection:
    conn = sqlite3.connect(CACHE)
    conn.execute("CREATE TABLE IF NOT EXISTS vec ("
                 "k TEXT PRIMARY KEY, dims INTEGER NOT NULL, v BLOB NOT NULL)")
    conn.commit()
    return conn


def _key(text: str) -> str:
    return hashlib.sha256(f"{EMBED_MODEL}|{EMBED_DIMS}|{text}".encode("utf-8")).hexdigest()


def embed_cached(texts: list[str], workers: int) -> np.ndarray:
    """Return an (n, EMBED_DIMS) float32 matrix, embedding only what is not cached."""
    from calibration.trial_gateway import GatewayClient

    conn = _cache_open()
    keys = [_key(t) for t in texts]
    have: dict[str, np.ndarray] = {}
    for i in range(0, len(keys), 900):                     # SQLite parameter limit
        chunk = keys[i:i + 900]
        q = ",".join("?" * len(chunk))
        for k, blob in conn.execute(f"SELECT k, v FROM vec WHERE k IN ({q})", chunk):
            have[k] = np.frombuffer(blob, dtype=np.float32)

    todo = [i for i, k in enumerate(keys) if k not in have]
    print(f"[embed] {len(texts)} texts: {len(have)} cached, {len(todo)} to fetch", flush=True)

    if todo:
        t0 = time.time()
        with GatewayClient() as gw:
            CHUNK = 400                                    # commit often so a crash resumes
            for start in range(0, len(todo), CHUNK):
                batch_idx = todo[start:start + CHUNK]
                vecs = gw.embed([texts[i] for i in batch_idx],
                                model=EMBED_MODEL, dimensions=EMBED_DIMS,
                                workers=workers, progress_every=0)
                rows = []
                for i, v in zip(batch_idx, vecs):
                    a = np.asarray(v, dtype=np.float32)
                    have[keys[i]] = a
                    rows.append((keys[i], EMBED_DIMS, a.tobytes()))
                conn.executemany("INSERT OR REPLACE INTO vec VALUES (?,?,?)", rows)
                conn.commit()
                done = start + len(batch_idx)
                el = time.time() - t0
                rate = done / max(el, 1e-6)
                eta = (len(todo) - done) / max(rate, 1e-6)
                print(f"[embed] {done}/{len(todo)}  {rate:>6.1f} req/s  "
                      f"elapsed {el/60:>5.1f}m  eta {eta/60:>5.1f}m", flush=True)
    conn.close()
    return np.stack([have[k] for k in keys])


# -- the trial -------------------------------------------------------------------------

def coherence_free(v: np.ndarray) -> float:
    if len(v) < 2:
        return float("nan")
    c = v.mean(axis=0); c /= np.linalg.norm(c) + 1e-10
    return float((v @ c).mean())


def main() -> None:
    a = _args()
    tag = "smoke" if a.smoke else "full"
    out = ARTIFACTS_DIR / f"pool_unit_gemini_{tag}_{a.width}d.json"
    if a.load:
        print(json.dumps(json.loads(out.read_text(encoding="utf-8-sig")), indent=1)[:4000])
        return

    from config import load_config
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool, fit_topic_model

    ta = load_tuning().layer_a
    cfg = load_config()
    files = sorted(Path(a.recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"no transcripts in {a.recordings}/")
    if a.smoke:
        files = files[:30]
        print("SMOKE MODE -- 30 transcripts. Path test only; numbers are NOT interpretable.\n")

    turns = []
    for f in files:
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    total_calls = len(set(call_ids))
    print(f"{len(files)} transcripts -> {len(texts)} CLIENT turns over {total_calls} calls\n")

    vecs = embed_cached(texts, a.workers)
    n0 = np.linalg.norm(vecs, axis=1)
    print(f"\n[embed] native matrix {vecs.shape}  ||v|| mean {n0.mean():.6f} "
          f"(min {n0.min():.6f} max {n0.max():.6f})")

    # Matryoshka truncation, then RENORMALISE. The renormalise is not optional: cutting a
    # unit vector's tail leaves ||v|| < 1, and trial_gateway measured the API's own 768 as
    # cosine-identical to the truncation, i.e. the API returns the renormalised form. Skip
    # this and every downstream dot product silently stops being a cosine.
    if a.width != EMBED_DIMS:
        vecs = vecs[:, :a.width]
        print(f"[embed] truncated to {a.width}d (Matryoshka, exact) -> {vecs.shape}")
    n = np.linalg.norm(vecs, axis=1)
    vecs = (vecs / (n[:, None] + 1e-10)).astype(np.float32)
    print(f"[embed] analysis width {a.width}d, renormalised ||v|| mean "
          f"{np.linalg.norm(vecs, axis=1).mean():.6f}")

    thin = np.array([not cluster_evidence.is_substantive(t, 5) for t in texts])
    print(f"[pool] content-free items: {thin.sum()}/{len(texts)} ({thin.mean()*100:.1f}%)"
          f"   <- text-only, must match bge's 32.8%")

    # --- Gemini's own cosine band, never measured on this corpus -----------------------
    rng = np.random.default_rng(42)
    s = rng.choice(len(vecs), size=min(4000, len(vecs)), replace=False)
    sub = vecs[s]
    sims = sub @ sub.T
    iu = np.triu_indices(len(sub), k=1)
    band = sims[iu]
    print(f"\n[band] turn-vs-turn cosine over {len(sub)} sampled turns:")
    print("       " + "  ".join(f"p{q}={np.percentile(band,q):.3f}" for q in (10,25,50,75,90)))
    print(f"       spread p10-p90 = {np.percentile(band,90)-np.percentile(band,10):.3f}"
          f"   (bge turn-level reference: spread ~0.141, p50 ~0.558)")

    print(f"\n[cluster] UMAP + HDBSCAN, min_cluster_size={MIN_CLUSTER_SIZE} "
          f"({MIN_CLUSTER_SIZE/len(texts)*100:.3f}% of pool)...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    if not raw_ids:
        raise SystemExit("no clusters -- min_cluster_size too high for this pool")
    print(f"[cluster] {len(raw_ids)} raw clusters, {(topics==-1).sum()} noise "
          f"({(topics==-1).mean()*100:.1f}%)   <- bge turn arm: 246 raw, 48.9% noise")

    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    cc = cent @ cent.T
    ciu = np.triu_indices(len(cent), k=1)
    print(f"[band] centroid-vs-centroid cosine: "
          + "  ".join(f"p{q}={np.percentile(cc[ciu],q):.3f}" for q in (10,50,90)))

    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)

    rows = []
    print(f"\n[sweep] merge thresholds (support floor {min_support} distinct calls)")
    print(f"{'merge':>7}{'groups':>8}{'survive':>9}{'subject-bearing':>18}{'junk':>15}"
          f"{'largest':>16}")
    per_thresh_groups = {}
    for t in SWEEP:
        groups = cluster_evidence.merge_by_similarity(cent, t)
        surv = []
        for g in groups:
            tids = [raw_ids[x] for x in g]
            idxs = [i for tt in tids for i in members[tt]]
            st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                               total_calls, texts=[texts[i] for i in idxs])
            if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                    cluster_evidence.INSUFFICIENT_EVIDENCE:
                continue
            surv.append({"n": len(idxs), "n_raw": len(tids), "thin": thin[idxs].mean(),
                         "calls": st.distinct_calls, "cov": st.call_coverage,
                         "kw": ", ".join(w for w, _ in tm.get_topic(
                             max(tids, key=lambda z: len(members[z])))[:6]),
                         "coh": coherence_free(vecs[idxs]),
                         "sample": [" ".join(texts[i].split())[:100]
                                    for i in idxs[:3]]})
        d = len(surv) or 1
        sb = [c for c in surv if c["thin"] < 0.30]
        jk = [c for c in surv if c["thin"] >= 0.70]
        rows.append({"threshold": t, "groups": len(groups), "surviving": len(surv),
                     "subject_bearing": len(sb), "subject_share": len(sb)/d,
                     "junk": len(jk), "junk_share": len(jk)/d,
                     "largest_items": max((c["n"] for c in surv), default=0),
                     "largest_n_raw": max((c["n_raw"] for c in surv), default=0)})
        r = rows[-1]
        print(f"{t:>7.2f}{r['groups']:>8}{r['surviving']:>9}"
              f"{r['subject_bearing']:>10} ({r['subject_share']*100:>4.1f}%)"
              f"{r['junk']:>8} ({r['junk_share']*100:>4.1f}%)"
              f"{r['largest_n_raw']:>6} raw /{r['largest_items']:>6}", flush=True)
        per_thresh_groups[t] = surv

    # --- READ the groups: the rule is that a merge threshold is judged by reading -----
    for t in SWEEP:
        surv = sorted(per_thresh_groups[t], key=lambda c: -c["n"])[:a.show]
        print(f"\n{'='*78}\nMERGE {t:.2f} -- {a.show} largest surviving clusters (READ THESE)\n{'='*78}")
        for c in surv:
            print(f"  [{c['n']:>5} items /{c['calls']:>4} calls | {c['cov']:>4.0%} cov | "
                  f"thin {c['thin']:>3.0%} | {c['n_raw']:>2} raw] {c['kw'][:52]}")
            for sm in c["sample"][:2]:
                print(f"       - {sm}")

    payload = {"embed_model": EMBED_MODEL, "native_dims": EMBED_DIMS,
               "analysis_width": a.width, "smoke": bool(a.smoke),
               "transcripts": len(files), "turns": len(texts), "calls": total_calls,
               "content_free_share": float(thin.mean()),
               "min_cluster_size": MIN_CLUSTER_SIZE,
               "raw_clusters": len(raw_ids), "noise_share": float((topics==-1).mean()),
               "turn_band": {f"p{q}": float(np.percentile(band, q)) for q in (10,25,50,75,90)},
               "centroid_band": {f"p{q}": float(np.percentile(cc[ciu], q)) for q in (10,50,90)},
               "sweep": rows,
               "clusters_at": {str(t): per_thresh_groups[t] for t in SWEEP}}
    out.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {out}")
    print("\nNEXT: choose the merge threshold by READING the groups above (not by counting "
          "-- \n  count-matching picked 0.90 on bge and reading proved it fused six business "
          "topics).\n  Then, and only then, spend the ~200 adjudication calls.")


if __name__ == "__main__":
    main()
