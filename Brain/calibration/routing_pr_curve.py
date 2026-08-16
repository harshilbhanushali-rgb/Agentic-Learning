#!/usr/bin/env python3
"""PRECISION-RECALL CURVES for the accept/reject decision. Free, read-only, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md section 11.

WHY THIS EXISTS. `description` and `centroid_pooled` were compared at ONE operating point each
-- description 79.5% precision / 87.1% recall, centroid 65.5% / 91.1%. Comparing two points is
not comparing two methods: precision and recall trade off along a CURVE, and centroid's recall
advantage may be nothing more than a looser operating point that description can also reach.

THE KNOB, which is the same one in both arms and was never swept:

    accept  iff  max(score over COACHABLE keys) - max(score over SINK keys)  >=  delta

At delta = 0 this is exactly the shipped rule ("accept iff the argmax is coachable"), so both
arms pass through their published point and the curve is an extension of the measurement
rather than a different one. Negative delta accepts more (recall up, precision down).

THE ESTIMATOR. Ground truth is 80 turns judged BLIND for substance (arm-free question, no
router information shown -- see read_routed_samples_v2.py). Those 80 are a STRATIFIED sample:
the four strata are defined by the two arms' delta=0 decisions, with wildly different
sizes (8,851 / 10,275 / 3,749 / 1,074). A raw average over the 80 would therefore be badly
biased, so every quantity is reweighted by N_stratum / n_sampled. Stratification by the
delta=0 decision stays valid at every other delta because the strata partition a FIXED
population; only which turns are accepted moves.

WHAT IT CANNOT DO. 80 judgments across 4 strata (8 / 32 / 20 / 20) is thin, and the
description-only stratum has n=8. Bootstrap CIs are reported so the thinness is visible
rather than implied. One reader, who designed the arms.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/routing_pr_curve.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration import routing_arms as ra
from calibration import routing_bench as rb

OUT = ARTIFACTS_DIR / "routing_pr_curve.json"
YES_B = {"B01", "B04", "B06", "B07", "B08", "B10", "B14", "B18", "B22", "B23", "B24",
         "B25", "B28", "B31", "B37", "B38"}
YES_C = {"C02", "C03", "C04", "C05", "C06", "C07", "C09", "C10", "C11", "C12", "C13",
         "C14", "C15", "C16", "C17", "C19"}
BOOT = 2000
SEED = 11


def coach_sink_margin(scores: np.ndarray, coach: np.ndarray) -> np.ndarray:
    """max over coachable keys minus max over sink keys. delta=0 reproduces the shipped rule."""
    c = np.where(coach[None, :], scores, -np.inf).max(axis=1)
    s = np.where(~coach[None, :], scores, -np.inf).max(axis=1)
    return (c - s).astype(np.float64)


def main() -> None:
    adj = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))["rows"]
    texts, call_ids = rb.build_pool("recordings")
    v = rb.embed_cache_only(texts)
    v = (v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    clusters = rb.cluster_pool(texts, v, call_ids, adj)
    ck, cc, _ = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(ck, cc)

    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dv = rb.embed_cache_only([t["text"] for t in tax])
    dv = (dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    D = np.zeros((len(keys), v.shape[1]), np.float32)
    H = np.zeros(len(keys), bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, x in zip(tax, dv):
        if (j := pos.get(t["key"])) is not None:
            D[j], H[j] = x, True

    ctx = ra.ArmContext(vecs=v, eval_idx=np.arange(len(texts)),
                        fit_mask=np.ones(len(texts), bool),
                        cluster_members=[c["idxs"] for c in clusters], cluster_keys=ck,
                        cluster_coach=cc, desc_vecs=D, desc_have=H, keys=keys, coach=coach,
                        owner=owner, seed=42, texts=texts)

    desc_scores = np.full((len(texts), len(keys)), -np.inf, np.float32)
    have = np.flatnonzero(H)
    desc_scores[:, have] = v @ D[have].T
    cent_scores, _ = ra.pooled_centroid_scores(ctx)
    M = {"description": coach_sink_margin(desc_scores, coach),
         "centroid_pooled": coach_sink_margin(cent_scores, coach)}

    # --- the judged sample, with its strata ------------------------------------------------
    k2 = json.loads((ARTIFACTS_DIR / "routed_samples_v2_key.json").read_text(encoding="utf-8-sig"))
    st = json.loads((ARTIFACTS_DIR / "strata_key.json").read_text(encoding="utf-8-sig"))
    a0 = M["description"] >= 0
    b0 = M["centroid_pooled"] >= 0
    N = {"both_accept": int((a0 & b0).sum()), "both_reject": int((~a0 & ~b0).sum()),
         "desc_only": int((a0 & ~b0).sum()), "cent_only": int((~a0 & b0).sum())}

    sample = []                                   # (turn_index, stratum, label)
    for it in k2["reject"]:
        s = "desc_only" if it["description"] else "cent_only"
        sample.append((it["turn"], s, it["id"] in YES_B))
    for n, i in enumerate(st["C"], 1):
        sample.append((i, "both_accept", f"C{n:02d}" in YES_C))
    for n, i in enumerate(st["D"], 1):
        sample.append((i, "both_reject", False))
    n_s = {s: sum(1 for _, x, _ in sample if x == s) for s in N}
    print(f"strata sizes {N}\nsampled       {n_s}")
    for s in N:
        if not n_s[s]:
            raise SystemExit(f"stratum {s} has no judged turns; the estimate would be undefined")

    idx = np.array([t for t, _, _ in sample])
    lab = np.array([l for _, _, l in sample])
    w = np.array([N[s] / n_s[s] for _, s, _ in sample])          # stratum weight per sample
    total_sub = float((w * lab).sum())

    def pr(arm, delta, weights):
        acc = M[arm][idx] >= delta
        tp = float((weights * acc * lab).sum())
        n_acc = float((weights * acc).sum())
        sub = float((weights * lab).sum())
        return (tp / n_acc if n_acc else float("nan"),
                tp / sub if sub else float("nan"), n_acc)

    rng = np.random.default_rng(SEED)
    by_s = {s: np.flatnonzero(np.array([x for _, x, _ in sample]) == s) for s in N}

    def boot_pr(arm, delta):
        out = []
        for _ in range(BOOT):
            wb = np.zeros(len(sample))
            for s, ii in by_s.items():
                pick = rng.choice(ii, size=len(ii), replace=True)
                for j in pick:
                    wb[j] += N[s] / n_s[s]
            out.append(pr(arm, delta, wb)[:2])
        a = np.array(out)
        return np.nanpercentile(a[:, 0], [2.5, 97.5]), np.nanpercentile(a[:, 1], [2.5, 97.5])

    print(f"\nestimated substantive turns in the pool: {total_sub:,.0f} "
          f"({total_sub/len(texts)*100:.0f}%)")
    print("\n  delta=0 (the shipped operating point)")
    base = {}
    for arm in M:
        p, r, n = pr(arm, 0.0, w)
        pc, rc = boot_pr(arm, 0.0)
        base[arm] = (p, r)
        print(f"    {arm:<17} precision {p*100:>5.1f}% [{pc[0]*100:.0f}-{pc[1]*100:.0f}]"
              f"   recall {r*100:>5.1f}% [{rc[0]*100:.0f}-{rc[1]*100:.0f}]   accepts {n:,.0f}")

    # --- THE COMPARISON THAT MATTERS: match centroid's recall, read description's precision --
    target = base["centroid_pooled"][1]
    grid = np.quantile(M["description"], np.linspace(0.01, 0.99, 400))
    best = None
    for d in sorted(grid):
        p, r, n = pr("description", d, w)
        if r >= target and (best is None or d > best[0]):
            best = (d, p, r, n)
    print(f"\n  MATCHED RECALL -- description moved along its OWN curve to centroid's "
          f"recall ({target*100:.1f}%)")
    if best:
        d, p, r, n = best
        pc, rc = boot_pr("description", d)
        print(f"    description @ delta={d:+.4f}  precision {p*100:>5.1f}% "
              f"[{pc[0]*100:.0f}-{pc[1]*100:.0f}]   recall {r*100:>5.1f}%   accepts {n:,.0f}")
        print(f"    centroid_pooled @ delta=0    precision "
              f"{base['centroid_pooled'][0]*100:>5.1f}%   recall {target*100:>5.1f}%")
        verdict = ("description DOMINATES -- higher precision at the same recall"
                   if p > base["centroid_pooled"][0] else
                   "centroid_pooled wins in this recall region")
        print(f"    -> {verdict}")
    else:
        print("    description cannot reach that recall at any delta on this grid")

    print("\n  full curve (delta swept over description's own score quantiles)")
    print(f"    {'delta':>9}" + "".join(f"{a[:12]:>26}" for a in M))
    for q in (0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80):
        d = float(np.quantile(np.concatenate([M[a] for a in M]), q))
        cells = ""
        for arm in M:
            p, r, _ = pr(arm, d, w)
            cells += f"   P {p*100:>5.1f}%  R {r*100:>5.1f}%"
        print(f"    {d:>+9.4f}{cells}")

    OUT.write_text(json.dumps({"strata": N, "sampled": n_s, "total_substantive": total_sub,
                               "base": {a: {"precision": base[a][0], "recall": base[a][1]}
                                        for a in base},
                               "matched": ({"delta": best[0], "precision": best[1],
                                            "recall": best[2]} if best else None),
                               "bootstrap": BOOT, "seed": SEED}, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}\nZero chat calls, zero embedding requests, zero Postgres writes.")


if __name__ == "__main__":
    main()
