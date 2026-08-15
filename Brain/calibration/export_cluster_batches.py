#!/usr/bin/env python3
"""Export cluster batches for BLIND independent quality judging by subagents.

WHY BLIND. The adjudication run already recorded Gemma's verdict per cluster
(scenario / mechanics / logistics / merged) plus its scenario_key, description and
reason. If a judge sees any of those it is grading the label, not the cluster, and the
agreement number becomes meaningless. So each batch carries ONLY what a fresh reader
needs -- keywords, sample utterances, size, call coverage -- and the verdict is joined
back afterwards by cluster id.

This is the same discipline the head-to-head trial used (blinded position-swapped
judging) and the same reason the skills trial disguised its pairs.

WHY BATCHED. One judge per cluster would be ~370 agent invocations for a question that
needs a paragraph of context each. Batching lets a judge read 40 clusters in one pass and
also see them RELATIVE to each other, which is what "is this one coherent situation"
actually depends on -- a cluster looks different next to its siblings than alone.

Usage (from Brain/):
    python calibration/export_cluster_batches.py --min-cluster-size 16 --batch 40
    python calibration/export_cluster_batches.py --min-cluster-size 50 --batch 40
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

BATCH_DIR = ARTIFACTS_DIR / "cluster_batches"
SAMPLES_PER_CLUSTER = 12       # enough to judge coherence; 6 is what the adjudicator saw


def _recluster_samples(min_cluster_size: int, merge: float) -> list[dict]:
    """Repeat the clustering to recover member utterances. Zero chat calls, vectors cached.

    Returns clusters in the SAME order the adjudicator used (largest first, after the
    insufficient-evidence drop), so the caller can join by position and verify.
    """
    import numpy as np
    from config import load_config
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool, fit_topic_model
    from calibration.trial_pool_unit_gemini import embed_cached
    from collections import defaultdict

    ta = load_tuning().layer_a
    cfg = load_config()
    turns = []
    for f in sorted(Path("recordings").glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    total_calls = len(set(call_ids))
    vecs = embed_cached(texts, workers=20)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype("float32")

    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=min_cluster_size)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, merge)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)

    out = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        ctexts = [texts[i] for i in idxs]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=ctexts)
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        # Spread the samples across the cluster rather than taking the head: the first N
        # members are whatever order HDBSCAN emitted, which can be one call's worth.
        step = max(1, len(ctexts) // SAMPLES_PER_CLUSTER)
        picked = [" ".join(ctexts[i].split())[:260]
                  for i in range(0, len(ctexts), step)][:SAMPLES_PER_CLUSTER]
        out.append({"n_items": st.n_items, "samples": picked})
    out.sort(key=lambda c: c["n_items"], reverse=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--min-cluster-size", type=int, required=True)
    p.add_argument("--batch", type=int, default=40)
    a = p.parse_args()

    src = ARTIFACTS_DIR / f"adjudicate_gemini_min{a.min_cluster_size}.json"
    meta = json.loads(src.read_text(encoding="utf-8-sig"))
    rows = meta["rows"]
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # The adjudication artifact stores keywords but NOT the member utterances, so they are
    # re-derived here by repeating the clustering. That is free (no chat calls, vectors
    # cached) but it rests on the clustering reproducing exactly.
    #
    # UMAP is documented as non-reproducible across process launches for the LOCAL bge
    # embedder (241 -> 231 -> 226 raw clusters for one corpus). It HAS reproduced exactly on
    # this Gemini backend -- 292 raw -> 245 merged in three separate processes -- which is
    # consistent with deterministic embeddings removing one of the two variance sources.
    # But "has reproduced" is not "will reproduce", so the join is VERIFIED rather than
    # trusted: every cluster's turn count must match the artifact position for position, or
    # this aborts. A silent mismatch would attach one cluster's utterances to another
    # cluster's verdict, which is the merge-blind _match_milestones failure all over again.
    samples = _recluster_samples(a.min_cluster_size, meta["merge"])
    if len(samples) != len(rows):
        raise SystemExit(f"ABORT: re-clustering gave {len(samples)} clusters, artifact has "
                         f"{len(rows)}. The clustering did not reproduce; cannot join safely.")
    for i, (r, s) in enumerate(zip(rows, samples)):
        if r["n_items"] != s["n_items"]:
            raise SystemExit(f"ABORT: cluster {i} has {s['n_items']} turns on re-cluster but "
                             f"{r['n_items']} in the artifact. Ordering diverged; join unsafe.")
        r["samples"] = s["samples"]
    print(f"join VERIFIED: {len(rows)} clusters matched position-for-position on turn count")

    # The blind payload. Deliberately EXCLUDES: kind, decision, scenario_key,
    # business_description, keyphrases, soft_skills, reason, merge_into_key.
    blind = [{
        "cluster_id": r["i"],
        "keywords": r["keywords"],
        "n_turns": r["n_items"],
        "distinct_calls": r["calls"],
        "corpus_coverage_pct": round(r["coverage"] * 100, 1),
        "sample_client_turns": r.get("samples") or [],
    } for r in rows]

    n = 0
    for start in range(0, len(blind), a.batch):
        chunk = blind[start:start + a.batch]
        out = BATCH_DIR / f"min{a.min_cluster_size}_batch{start // a.batch:02d}.json"
        out.write_text(json.dumps({
            "granularity": f"min_cluster_size={a.min_cluster_size}",
            "batch_index": start // a.batch,
            "n_clusters": len(chunk),
            "clusters": chunk,
        }, indent=1), encoding="utf-8")
        n += 1
    print(f"{len(blind)} clusters -> {n} batch file(s) of <= {a.batch} in {BATCH_DIR}")
    print("Blind: no verdict, key, description or reason is included.")


if __name__ == "__main__":
    main()
