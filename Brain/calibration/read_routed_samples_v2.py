#!/usr/bin/env python3
"""BLIND READ v2 -- bigger, and the reject sample is judged ARM-FREE. Free, read-only.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md section 11.

v1 asked "which arm's call is right", which shows the reader both answers and invites
rationalising. v2 fixes the reject half: the file contains ONLY the turn text -- no arm, no
candidate scenario, no accept/reject hint -- and the reader judges ONE arm-independent
question, "is this a substantive client moment worth coaching on?". All arms are then scored
against that single judgment. A judge who cannot see the arms cannot favour one.

The destination half necessarily shows both candidates (there is no way to ask "where should
this go" without offering somewhere), so it keeps v1's defence: A/B order coin-flipped per
item on a fixed seed, identity in a SEPARATE key file.

v1 was n=20 / n=12 and nothing reached significance (p = 0.648 / 0.344 / 0.388). v2 roughly
doubles both. It is still one reader who designed the arms; blinding mitigates that and does
not remove it.

Writes: routed_samples_v2_blind.txt (read first) and routed_samples_v2_key.json (read last).
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
from calibration import routing_arms as ra
from calibration import routing_bench as rb

BLIND = ARTIFACTS_DIR / "routed_samples_v2_blind.txt"
KEY = ARTIFACTS_DIR / "routed_samples_v2_key.json"
SEED = 202608
N_DEST, N_REJECT = 30, 40
ARMS = ["description", "centroid_pooled", "split_member_accept"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recordings", default="recordings")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()

    adj = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))["rows"]
    texts, call_ids = rb.build_pool(a.recordings)
    vecs = rb.embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    clusters = rb.cluster_pool(texts, vecs, call_ids, adj)
    cl_keys, cl_coach, _ = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)

    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dv = rb.embed_cache_only([t["text"] for t in tax])
    dv = (dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    desc_vecs = np.zeros((len(keys), vecs.shape[1]), dtype=np.float32)
    desc_have = np.zeros(len(keys), dtype=bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, v in zip(tax, dv):
        if (j := pos.get(t["key"])) is not None:
            desc_vecs[j], desc_have[j] = v, True

    blurb = {}
    for r in adj:
        k = r["scenario_key"] if r["kind"] != "merged" else r.get("merge_into_key")
        if k and k not in blurb:
            blurb[k] = ((r.get("business_description") or "").strip()
                        or " ".join(r.get("keyphrases") or [])[:150] or "(none)")

    ctx = ra.ArmContext(vecs=vecs, eval_idx=np.arange(len(texts)),
                        fit_mask=np.ones(len(texts), bool),
                        cluster_members=[c["idxs"] for c in clusters], cluster_keys=cl_keys,
                        cluster_coach=cl_coach, desc_vecs=desc_vecs, desc_have=desc_have,
                        keys=keys, coach=coach, owner=owner, seed=a.seed, texts=texts)
    out = {n: ra.FREE_ARMS[n](ctx) for n in ARMS}
    D, C = out["description"], out["centroid_pooled"]

    rng = random.Random(a.seed)
    lines, key = [], {"arms": ARMS, "dest": [], "reject": []}

    # --- A. destination: both accept, different scenario ---------------------------------
    pool = [i for i in range(len(texts))
            if D.accepted[i] and C.accepted[i] and D.keys[i] != C.keys[i]]
    lines += ["=" * 92, f"PART A -- DESTINATION. Both routers accept this turn but send it to "
              f"different scenarios.", "For each: which destination fits the turn better, A or "
              f"B? (or 'neither')", "=" * 92]
    for c, i in enumerate(rng.sample(pool, min(N_DEST, len(pool))), 1):
        flip = rng.random() < 0.5
        first, second = (C.keys[i], D.keys[i]) if flip else (D.keys[i], C.keys[i])
        lines += [f"\n[A{c:02d}] {texts[i][:400]}"]
        for lbl, kk in (("A", first), ("B", second)):
            lines += [f"    {lbl}) {kk}", f"       {blurb.get(kk, '')[:165]}"]
        key["dest"].append({"id": f"A{c:02d}", "turn": int(i),
                            "A_is": "centroid_pooled" if flip else "description",
                            "B_is": "description" if flip else "centroid_pooled"})

    # --- B. accept/reject: TURN ONLY, no arm information whatsoever -----------------------
    disagree = [i for i in range(len(texts))
                if len({bool(out[n].accepted[i]) for n in ARMS}) > 1]
    lines += ["\n\n" + "=" * 92,
              "PART B -- IS THIS A SUBSTANTIVE CLIENT MOMENT WORTH COACHING ON?",
              "Judge the TURN on its own. YES = carries real business/technical substance a",
              "CSM could be coached on. NO = backchannel, filler, logistics, introductions,",
              "scheduling, or too fragmentary to act on. No router information is shown here",
              "by design -- these are the turns the routers disagree about.", "=" * 92]
    for c, i in enumerate(rng.sample(disagree, min(N_REJECT, len(disagree))), 1):
        lines += [f"\n[B{c:02d}] {texts[i][:400]}"]
        key["reject"].append({"id": f"B{c:02d}", "turn": int(i),
                              **{n: bool(out[n].accepted[i]) for n in ARMS}})

    BLIND.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"destination pool {len(pool)}   accept/reject disagreements {len(disagree)}")
    for n in ARMS:
        print(f"  {n:<24} accepts {int(out[n].accepted.sum()):>6} "
              f"({out[n].accepted.mean()*100:.1f}%)")
    print(f"wrote {BLIND}\nwrote {KEY}  <-- open only after judging")


if __name__ == "__main__":
    main()
