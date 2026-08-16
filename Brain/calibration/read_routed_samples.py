#!/usr/bin/env python3
"""READ REAL ROUTED TURNS. Blinded. Free, read-only, no writes to Postgres.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md

Every conclusion in `routing_bench.py` is aggregate, and this repo's record is that the
aggregate misled it and reading samples is what exposed it -- coherence-lift turned out to
reward junk, and a 72.7% "orphan rate" turned out to be the fix working. Nothing in the routing
comparison has been read. This is that check.

*** IT WRITES TWO FILES AND THE SEPARATION IS THE POINT. ***
    routed_samples_blind.txt   turns + two candidate scenarios as A / B, arm identity removed,
                               A/B order coin-flipped per item on a fixed seed
    routed_samples_key.json    which of A / B came from which arm
A judge shown the verdict grades the label, not the item -- the same discipline the head-to-head
trial and the cluster-adjudication trial both used. Read the blind file, commit to a judgment,
THEN open the key. Reading the key first invalidates the exercise and there is no way to
un-see it.

THREE SAMPLES, each answering a question the aggregate cannot:
  DISAGREEMENT  turns both arms accept but route to DIFFERENT scenarios. The only place the
                arms can be compared head to head on the same input.
  REJECT-SPLIT  turns one arm sinks and the other accepts. Bears directly on whether the
                reject rate is a junk filter or just a number -- `routing_bench` counted
                rejections and never checked whether the rejected turns are junk.
  REJECTED      turns BOTH arms sink, as a floor: if these read as obvious junk the sink is
                doing its job; if they read as substance, both arms are discarding content.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_routed_samples.py
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
from calibration import routing_arms as ra
from calibration import routing_bench as rb

BLIND = ARTIFACTS_DIR / "routed_samples_blind.txt"
KEY = ARTIFACTS_DIR / "routed_samples_key.json"
SEED = 42
N_DISAGREE, N_SPLIT, N_REJECTED = 20, 12, 12
ARM_A, ARM_B = "description", "centroid_pooled"


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--seed", type=int, default=SEED)
    return p.parse_args()


def main() -> None:
    a = _args()
    adj_rows = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))["rows"]
    texts, call_ids = rb.build_pool(a.recordings)
    vecs = rb.embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    clusters = rb.cluster_pool(texts, vecs, call_ids, adj_rows)
    cl_keys, cl_coach, _ = ra.cluster_labels(adj_rows)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)

    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dvec = rb.embed_cache_only([t["text"] for t in tax])
    dvec = (dvec / (np.linalg.norm(dvec, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    desc_vecs = np.zeros((len(keys), vecs.shape[1]), dtype=np.float32)
    desc_have = np.zeros(len(keys), dtype=bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, v in zip(tax, dvec):
        if (j := pos.get(t["key"])) is not None:
            desc_vecs[j], desc_have[j] = v, True

    # Human-readable blurb per key, so a reader can judge the DESTINATION and not just the key
    # string. Sinks included -- a rejection is only judgeable if you can see what it was
    # rejected INTO.
    blurb = {}
    for r in adj_rows:
        k = r["scenario_key"] if r["kind"] != "merged" else r.get("merge_into_key")
        if k and k not in blurb:
            blurb[k] = ((r.get("business_description") or "").strip()
                        or " ".join(r.get("keyphrases") or [])[:160] or "(no description)")

    ctx = ra.ArmContext(vecs=vecs, eval_idx=np.arange(len(texts)),
                        fit_mask=np.ones(len(texts), bool),
                        cluster_members=[c["idxs"] for c in clusters], cluster_keys=cl_keys,
                        cluster_coach=cl_coach, desc_vecs=desc_vecs, desc_have=desc_have,
                        keys=keys, coach=coach, owner=owner, seed=a.seed, texts=texts)
    reg = dict(ra.FREE_ARMS)
    ra_, rb_ = reg[ARM_A](ctx), reg[ARM_B](ctx)

    disagree = [i for i in range(len(texts))
                if ra_.accepted[i] and rb_.accepted[i] and ra_.keys[i] != rb_.keys[i]]
    split = [i for i in range(len(texts)) if ra_.accepted[i] != rb_.accepted[i]]
    both_rej = [i for i in range(len(texts)) if not ra_.accepted[i] and not rb_.accepted[i]]
    print(f"disagree {len(disagree)}   reject-split {len(split)}   both-rejected "
          f"{len(both_rej)}   of {len(texts)} turns")

    rng = random.Random(a.seed)
    lines, key = [], {"arm_A": ARM_A, "arm_B": ARM_B, "items": []}

    def emit(tag, idx_list, n):
        lines.append("\n" + "=" * 92)
        lines.append(f"{tag}  (showing {min(n, len(idx_list))} of {len(idx_list)})")
        lines.append("=" * 92)
        for c, i in enumerate(rng.sample(idx_list, min(n, len(idx_list))), 1):
            ka, kb = ra_.keys[i], rb_.keys[i]
            flip = rng.random() < 0.5                     # coin-flip the display order
            first, second = (kb, ka) if flip else (ka, kb)
            lines.append(f"\n[{tag[:4]}-{c:02d}] call={call_ids[i]}")
            lines.append(f"  TURN: {texts[i][:420]}")
            for lbl, kk in (("A", first), ("B", second)):
                mark = "" if kk in blurb and coach[pos[kk]] else "   <-- SINK (rejected)"
                lines.append(f"    {lbl}) {kk}{mark}")
                lines.append(f"       {blurb.get(kk, '')[:170]}")
            key["items"].append({"id": f"{tag[:4]}-{c:02d}", "turn_index": int(i),
                                 "A_is": ARM_B if flip else ARM_A,
                                 "B_is": ARM_A if flip else ARM_B,
                                 "A_key": first, "B_key": second})

    emit("DISAGREEMENT -- both accept, different scenario", disagree, N_DISAGREE)
    emit("REJECT-SPLIT -- one sinks it, the other accepts", split, N_SPLIT)
    emit("BOTH REJECTED -- is the sink catching junk?", both_rej, N_REJECTED)

    BLIND.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"wrote {BLIND}\nwrote {KEY}   <-- do NOT open until judgments are committed")


if __name__ == "__main__":
    main()
