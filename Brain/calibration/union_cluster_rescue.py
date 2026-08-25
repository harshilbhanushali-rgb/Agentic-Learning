#!/usr/bin/env python3
"""UNION TAXONOMY REBUILD — Stage B: cluster + rescue_centroid. FREE, one UMAP fit.

Spec: docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md §3 (frozen):
UMAP seed 42 + HDBSCAN turn mode, MIN_CLUSTER_SIZE=16, near-duplicate merge at 0.97, the
same evidence triage as `clean2_base`'s construction, then the frozen `rescue_centroid`
rule (a noise turn is admitted into its nearest surviving cluster iff its cosine to that
centroid clears the cluster's OWN member p25). Cluster count and identity unchanged by
the rescue; memberships grow.

WHAT THIS PERSISTS AND WHY. BOTH membership sets — `rescued` (the set Stage C
adjudicates) and `base` (the fallback arm, NOT adjudicated under this spec) — plus the
c-TF-IDF keywords, stable cluster_id and triage verdict per cluster. Stage C loads these
via `adjudication_ab --clusters-from` instead of re-fitting, so the adjudicated clusters
are PROVABLY the ones fitted here rather than a second launch's UMAP output. The fit
happens exactly once, in this process.

The clustering code path is `adjudication_ab.derive_clusters` — the same function the
clean2 arms ran through — and the rescue is `adjudication_ab.compute_rescue`, which
imports the one frozen rule from `clustering_bench.rescue_centroid_additions`. Nothing
here re-implements either (the stale-sidecar lesson: recompute in-process, import the
rule).

T1 (descriptive, non-gating, spec §3): cluster count, noise rate before/after rescue,
rescued-turn count, size distribution — printed and recorded in the artifact.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/union_cluster_rescue.py
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "union_clusters.json"
SEED = 42                      # inside v2.layer_a.fit_topic_model (UMAP random_state=42)
MIN_CLUSTER_SIZE = 16
MERGE = 0.97
# The adjudication budget's hard stop is 500 calls at ~1 call/cluster. If this fit
# yields more clusters than that, Stage C must not start without the operator.
ADJUDICATION_HARD_STOP = 500


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_union_cluster_rescue.py)
# ---------------------------------------------------------------------------------------

def size_distribution(sizes: list[int]) -> dict:
    if not sizes:
        return {"n": 0}
    a = np.asarray(sizes)
    return {"n": len(sizes), "p10": int(np.percentile(a, 10)),
            "p50": int(np.percentile(a, 50)), "p90": int(np.percentile(a, 90)),
            "max": int(a.max()), "mean": float(a.mean()), "total": int(a.sum())}


def assert_rescue_only_adds(base: list[list[int]], rescued: list[list[int]]) -> int:
    """The rescue's contract: same cluster count, every base membership a subset of its
    rescued twin, no turn admitted into two clusters. Returns the number of added turns.
    Asserted rather than trusted — a violated contract here would poison Stage C's
    'membership is the single variable' design."""
    if len(base) != len(rescued):
        raise ValueError(f"cluster count moved under rescue: {len(base)} -> {len(rescued)}")
    added_all: list[int] = []
    n_added = 0
    for bi, (b, r) in enumerate(zip(base, rescued)):
        bs, rs = set(b), set(r)
        if not bs.issubset(rs):
            raise ValueError(f"cluster {bi} LOST members under rescue")
        added = rs - bs
        n_added += len(added)
        added_all.extend(added)
    if len(added_all) != len(set(added_all)):
        raise ValueError("a rescued turn was admitted into more than one cluster")
    return n_added


def t1_summary(n_turns: int, base: list[list[int]], rescued: list[list[int]]) -> dict:
    """Spec §3's T1 readout, computed from the two membership sets alone."""
    n_added = assert_rescue_only_adds(base, rescued)
    covered_base = sum(len(c) for c in base)
    covered_resc = sum(len(c) for c in rescued)
    return {
        "n_turns": n_turns,
        "n_clusters": len(base),
        "noise_before": 1.0 - covered_base / n_turns if n_turns else float("nan"),
        "noise_after": 1.0 - covered_resc / n_turns if n_turns else float("nan"),
        "rescued_turns": n_added,
        "sizes_base": size_distribution([len(c) for c in base]),
        "sizes_rescued": size_distribution([len(c) for c in rescued]),
    }


# ---------------------------------------------------------------------------------------
# the one fit
# ---------------------------------------------------------------------------------------

def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter
                            ).parse_args()
    if OUT.exists():
        raise SystemExit(f"{OUT.name} already exists — refusing to clobber the persisted "
                         f"clustering Stage C adjudicates. Delete it only if Stage C has "
                         f"not spent anything against it.")

    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model
    from calibration.routing_bench import embed_cache_only
    from calibration.union_pool_fetch import load_t0, build_union_pool
    from calibration.adjudication_ab import (compute_rescue, derive_clusters, pool_sha)

    man = load_t0()                              # T0 must exist and PASS
    texts, call_ids, old_stems, *_ = build_union_pool()
    sha = pool_sha(texts)
    if sha != man["pool_sha"]:
        raise SystemExit(f"POOL DRIFT: sha {sha} vs T0's {man['pool_sha']} — re-run "
                         f"union_pool_fetch.py --t0 deliberately if intended.")
    total_calls = len(set(call_ids))

    vecs = embed_cache_only(texts)               # a miss aborts; the fetch already ran
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    print(f"[embed] {vecs.shape} cache-only", flush=True)

    ta = load_tuning().layer_a
    print(f"[fit] UMAP(seed {SEED}) + HDBSCAN(mcs {MIN_CLUSTER_SIZE}), turn mode, "
          f"ONE fit in this process...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)
    clusters = derive_clusters(texts, call_ids, vecs, total_calls, tm, topics, ta)
    if not clusters:
        raise SystemExit("zero surviving clusters — nothing to persist")

    base_members = [list(c["idxs"]) for c in clusters]

    # compute_rescue applies the frozen p25 rule in-process and grows c["idxs"] in place.
    n_added = compute_rescue(clusters, vecs, len(texts))
    rescued_members = [list(c["idxs"]) for c in clusters]

    t1 = t1_summary(len(texts), base_members, rescued_members)
    assert t1["rescued_turns"] == n_added, "rescue accounting mismatch"

    payload = {
        "identity": {
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(), "seed": SEED,
            "min_cluster_size": MIN_CLUSTER_SIZE, "merge": MERGE,
            "embedder": "gemini-embedding-2@3072",
            "pool_sha": sha, "t0_artifact": "union_pool_t0.json",
            "n_turns": len(texts), "n_calls": total_calls,
            "rescue_rule": "centroid_p25_in_process",
        },
        "t1": t1,
        "clusters": [
            {"cluster_id": c["cluster_id"], "keywords": c["keywords"],
             "n_merged": c["n_merged"], "triage_verdict": c["verdict"],
             "idxs_base": sorted(map(int, b)), "idxs_rescued": sorted(map(int, r))}
            for c, b, r in zip(clusters, base_members, rescued_members)
        ],
    }
    # tmp + atomic replace (audit 9.2 finding 1): a kill mid-write must not leave a
    # truncated artifact behind the clobber refusal after a tens-of-minutes fit.
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    os.replace(tmp, OUT)

    print("\n" + "=" * 78)
    print(f"T1 READOUT (descriptive, non-gating)")
    print("=" * 78)
    print(f"  clusters             : {t1['n_clusters']}")
    print(f"  noise before rescue  : {t1['noise_before']*100:.1f}%")
    print(f"  noise after rescue   : {t1['noise_after']*100:.1f}%")
    print(f"  rescued turns        : {t1['rescued_turns']}")
    print(f"  sizes base           : {t1['sizes_base']}")
    print(f"  sizes rescued        : {t1['sizes_rescued']}")
    if t1["n_clusters"] > ADJUDICATION_HARD_STOP:
        print(f"\n!! {t1['n_clusters']} clusters exceeds the spec's original ~300-450 "
              f"planning band / 500 line. NOTE: the operator REMOVED the 500 hard stop "
              f"on 2026-08-18 when approving the full 58k-turn pool — Stage C may "
              f"proceed; the count is on the record here.")
    print(f"\nwrote {OUT.name}")
    print("UNION CLUSTER COMPLETE", flush=True)


if __name__ == "__main__":
    main()
