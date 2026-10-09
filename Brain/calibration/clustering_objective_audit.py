#!/usr/bin/env python3
"""IS `rescue_centroid`'s WIN JUST THE GATE'S OWN OBJECTIVE FUNCTION? Free, read-only.

Spec: docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md.
Sibling of `calibration/routing_objective_audit.py`, which established the method and the
trap; read that module's docstring before changing anything here.

THE CHARGE, and why it is sharper for this arm than for any other in the bench.
`clustering_bench.py` grades a population P by `coherence(P)` = mean cosine of P to its OWN
centroid, lifted over a length-matched null. Nine of its ten arms produce populations by
CLUSTERING, which is not that statistic. `rescue_centroid` is the exception: it admits a noise
turn t into cluster c iff

    cos(t, centroid_c) >= p25({cos(m, centroid_c) : m in c})

i.e. it selects new members BY the very quantity the gate then measures. The bench's own
numbers carry the signature: the gate and the arm-neutral lexical column track each other
across every arm (53/61, 53/53, 50/50, 45/47, 42/50, 39/45, 24/34, 13/29, 8/21, 0/0) and
diverge for exactly one -- rescue_centroid at 74 gate / 47 lexical.

*** THE OBVIOUS NEUTRAL MEASURE IS FAKE. *** `coherence(P) == sqrt(mean pairwise cosine
including the diagonal)`, verified to 1e-6 in the routing audit. Mean pairwise cosine is the
SAME STATISTIC RENAMED and cannot audit its own source. It is not offered here.

THE THIRD OBJECTIVE ADDED HERE:
  description   mean cosine of P's members to that key's DESCRIPTION vector (the adjudicated
                scenario's prose + keyphrases, embedded). No clustering arm and no rescue rule
                optimises it, and it lives in a different register (analyst prose) from the
                turns being scored.
                *** STATED BIAS, not hidden: Gemma WROTE each description while looking at
                samples of the INCUMBENT's cluster, so this objective is anchored to the
                incumbent's original content. That biases it TOWARD the incumbent and AGAINST
                any arm that changes membership. It is therefore evidence only in one
                direction -- if a rescue arm WINS here despite the anchoring that is strong;
                if it loses, the anchoring is a sufficient explanation and the result is
                weak. Read it with that asymmetry, never as a symmetric referee. ***

Scores whatever arms have stored memberships (`clustering_bench_members.json`) plus the
incumbent (from `clustering_bench.json`). Re-scoring only -- no clustering is re-fitted, so
this costs no UMAP fit and no embedding request.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/clustering_objective_audit.py
    ..\\.venv\\Scripts\\python.exe calibration/clustering_objective_audit.py --load
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
from calibration import null_test_taxonomy as nt
from calibration import routing_arms as ra
from calibration import routing_bench as rb
from calibration.clustering_bench import (
    ADJ_NAME, MEMBERS_OUT, OUT as BENCH_OUT, SEED, plurality_transfer, populations, sign_test,
)
from calibration.routing_objective_audit import coherence_sparse, draw_length_matched

OUT = ARTIFACTS_DIR / "clustering_objective_audit.json"


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--load", action="store_true")
    return p.parse_args()


def score_desc(pops: dict[str, list[int]], keys: list[str], vecs, desc_vecs, desc_have,
               order_by_wc, rank_of, rng) -> list[dict]:
    """Mean cosine to the key's description vector, lifted over the SAME length-matched null."""
    pos = {k: i for i, k in enumerate(keys)}
    rows = []
    for k in keys:
        idx = pops.get(k, [])
        j = pos[k]
        row = {"key": k, "n": len(idx), "rankable": len(idx) >= nt.MIN_MEMBERS,
               "lift_desc": float("nan")}
        if len(idx) >= 2 and desc_have[j]:
            d = desc_vecs[j]
            obs = float((vecs[idx] @ d).mean())
            drawn = draw_length_matched(idx, order_by_wc, rank_of, rng)
            null = float(np.mean([float((vecs[dr] @ d).mean()) for dr in drawn])) if drawn \
                else float("nan")
            row["lift_desc"] = obs - null
        rows.append(row)
    return rows


def main() -> None:
    a = _args()
    if a.load:
        print(json.dumps(json.loads(OUT.read_text(encoding="utf-8-sig"))["table"], indent=1))
        return

    bench = json.loads(BENCH_OUT.read_text(encoding="utf-8-sig"))
    members = json.loads(MEMBERS_OUT.read_text(encoding="utf-8-sig"))
    adj = json.loads((ARTIFACTS_DIR / ADJ_NAME).read_text(encoding="utf-8-sig"))["rows"]

    texts, call_ids = rb.build_pool(a.recordings)
    vecs = rb.embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    cl_keys, cl_coach, _ = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)
    coach_of_key = {k: bool(c) for k, c in zip(keys, coach)}
    coach_keys = [k for k, c in zip(keys, coach) if c]
    word_count = np.array([len(t.split()) for t in texts])
    order_by_wc = [int(i) for i in np.argsort(word_count, kind="stable")]
    rank_of = {t: i for i, t in enumerate(order_by_wc)}

    inc = bench["incumbent_clusters"]
    truth_key = {}
    for c, ki in zip(inc, owner):
        for i in c["idxs"]:
            truth_key[i] = keys[ki]

    # --- description vectors, cache-only ---------------------------------------------------
    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dv = rb.embed_cache_only([t["text"] for t in tax])
    dv = (dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    desc_vecs = np.zeros((len(keys), vecs.shape[1]), dtype=np.float32)
    desc_have = np.zeros(len(keys), dtype=bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, v in zip(tax, dv):
        j = pos.get(t["key"])
        if j is not None:
            desc_vecs[j], desc_have[j] = v, True
    print(f"description vectors: {int(desc_have.sum())}/{len(keys)} keys covered")

    arms: dict[str, tuple[list[list[int]], list]] = {
        "incumbent": ([list(map(int, c["idxs"])) for c in inc], [])}
    for name, v in members.get("arms", {}).items():
        arms[name] = ([list(map(int, c)) for c in v["clusters"]], list(v["mapped"]))

    ctl_desc = None
    table = {}
    for name in ["incumbent"] + [n for n in arms if n != "incumbent"]:
        clusters, _ = arms[name]
        mapped = plurality_transfer(clusters, truth_key)
        pops = populations(clusters, mapped, coach_of_key)
        rows = score_desc(pops, coach_keys, vecs, desc_vecs, desc_have,
                          order_by_wc, rank_of, random.Random(SEED))
        rk = [r for r in rows if r["rankable"] and r["lift_desc"] == r["lift_desc"]]
        ref = ctl_desc if ctl_desc is not None else rk
        for r in rk:
            r["ref"] = nt.size_matched_reference(r["n"], ref, field="lift_desc")
            r["reaches"] = bool(r["lift_desc"] >= r["ref"])
        if ctl_desc is None:
            ctl_desc = rk
        ctl_keys_set = {r["key"] for r in ctl_desc}
        won = {r["key"] for r in rk if r.get("reaches")}
        table[name] = {"n_clear": len(won & ctl_keys_set), "n_fixed": len(ctl_keys_set),
                       "share": len(won & ctl_keys_set) / max(1, len(ctl_keys_set)),
                       "reaches_by_key": {r["key"]: bool(r.get("reaches")) for r in rk}}
        print(f"  [{name}] description-objective share "
              f"{table[name]['n_clear']}/{table[name]['n_fixed']} "
              f"= {table[name]['share'] * 100:.0f}%", flush=True)

    # --- the three objectives side by side --------------------------------------------------
    print("\n" + "=" * 88)
    print("  THREE OBJECTIVES, SAME POPULATIONS  (centroid = the bench gate)")
    print("=" * 88)
    print(f"  {'arm':<20}{'centroid':>10}{'description':>13}{'lexical':>9}{'desc sign p':>13}")
    inc_reach = table["incumbent"]["reaches_by_key"]
    ck = sorted(table["incumbent"]["reaches_by_key"])
    for name in sorted(table, key=lambda n: -bench["arms"].get(n, {}).get("share_fixed", 0)):
        b = bench["arms"].get(name, {})
        rb_ = table[name]["reaches_by_key"]
        bb = sum(1 for k in ck if rb_.get(k, False) and not inc_reach.get(k, False))
        cc = sum(1 for k in ck if not rb_.get(k, False) and inc_reach.get(k, False))
        p = sign_test(bb, cc) if name != "incumbent" else float("nan")
        table[name].update({"sign_b": bb, "sign_c": cc, "sign_p": p})
        print(f"  {name:<20}{(b.get('share_fixed') or 0) * 100:>9.0f}%"
              f"{table[name]['share'] * 100:>12.0f}%"
              f"{(b.get('share_lex') or 0) * 100:>8.0f}%"
              + (f"{p:>13.3f}  (+{bb}/-{cc})" if p == p else f"{'--':>13}"))

    OUT.write_text(json.dumps({"table": table, "n_keys": len(coach_keys)},
                              indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
