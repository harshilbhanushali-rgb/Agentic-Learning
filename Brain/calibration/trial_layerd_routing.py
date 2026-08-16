#!/usr/bin/env python3
"""TEST 1 -- description vs member-centroid routing on the turns LAYER D ACTUALLY SEES.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md section 14.

Everything measured so far routed NAREN's client turns -- the same corpus the taxonomy was
built from. Layer D does something different and harder: it applies that taxonomy to turns from
CSM calls, a different corpus with different clients, different speakers and different topics.
Its very first act on a client turn is `is this a signal?`, decided entirely by whether the
best match is a SINK. That single decision gates whether a CSM is scored at all, so it is the
routing decision with the most consequence in the product.

WHY THIS IS THE CLEANEST ARM COMPARISON AVAILABLE. Both arms are FITTED on Naren's 400 calls
(descriptions were written from them; centroids are their cluster means) and EVALUATED on the
CSM corpus. No CSM turn can leak into either arm, for either arm, by construction -- so the
leakage asymmetry that forced 4-fold CV on the Naren corpus does not exist here at all.

Both arms share the embedder, the taxonomy, the key universe and the sink set. The ONLY thing
that differs is what a scenario is represented BY: its LLM prose, or the mean of its own
member turns.

The blind sample it emits is judged with the protocol that already passed its validity gates
(positive control 0/20 vs 16/20, plumbing audited 70/70, paired McNemar power at n=40) -- the
turn is shown ALONE, with no arm, no candidate scenario and no accept/reject hint.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/trial_layerd_routing.py            # cache only
    ..\\.venv\\Scripts\\python.exe calibration/trial_layerd_routing.py --embed    # allow spend
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

OUT = ARTIFACTS_DIR / "layerd_routing.json"
BLIND = ARTIFACTS_DIR / "layerd_blind.txt"
KEY = ARTIFACTS_DIR / "layerd_key.json"
N_BLIND = 50
SEED = 20260816


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--embed", action="store_true",
                    help="allow embedding uncached CSM turns (reports the count first)")
    ap.add_argument("--n-blind", type=int, default=N_BLIND)
    a = ap.parse_args()

    from config import load_config
    from calibration.validate_taxonomy_vs_layerd import csm_client_turns, load_new
    from calibration.trial_pool_unit_gemini import _cache_open, _key, embed_cached

    cfg = load_config()
    csm = csm_client_turns(cfg)
    uniq = sorted(set(csm))
    conn = _cache_open()
    miss = sum(1 for t in uniq
               if not conn.execute("SELECT 1 FROM vec WHERE k=?", (_key(t),)).fetchone())
    conn.close()
    print(f"CSM client turns: {len(csm)} ({len(uniq)} unique)   uncached: {miss}")
    if miss and not a.embed:
        raise SystemExit(f"{miss} uncached turns. Re-run with --embed to allow the spend.")
    cvecs = embed_cached(uniq, workers=20) if miss else rb.embed_cache_only(uniq)
    cvecs = (cvecs / (np.linalg.norm(cvecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)

    # --- the arms, FITTED ON NAREN'S CORPUS -------------------------------------------------
    adj = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))["rows"]
    ntexts, ncalls = rb.build_pool("recordings")
    nv = rb.embed_cache_only(ntexts)
    nv = (nv / (np.linalg.norm(nv, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    clusters = rb.cluster_pool(ntexts, nv, ncalls, adj)
    ck, cc, _ = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(ck, cc)

    tax = load_new()
    dv = rb.embed_cache_only([t["text"] for t in tax])
    dv = (dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    D = np.zeros((len(keys), nv.shape[1]), np.float32)
    H = np.zeros(len(keys), bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, x in zip(tax, dv):
        if (j := pos.get(t["key"])) is not None:
            D[j], H[j] = x, True

    fit = ra.ArmContext(vecs=nv, eval_idx=np.arange(len(ntexts)),
                        fit_mask=np.ones(len(ntexts), bool),
                        cluster_members=[c["idxs"] for c in clusters], cluster_keys=ck,
                        cluster_coach=cc, desc_vecs=D, desc_have=H, keys=keys, coach=coach,
                        owner=owner, seed=SEED, texts=ntexts)
    acc = ra.pooled_key_members(fit)
    cent = ra._unit(np.stack([nv[m].mean(axis=0) for m in acc.values()]).astype(np.float32))
    cent_key = np.array(list(acc), dtype=np.int32)

    # --- route the CSM turns ----------------------------------------------------------------
    have = np.flatnonzero(H)
    d_scores = np.full((len(uniq), len(keys)), -np.inf, np.float32)
    d_scores[:, have] = cvecs @ D[have].T
    c_scores = ra._pool_max(cvecs, cent, cent_key, len(keys))
    R = {"description": ra.routing_from_scores(d_scores, keys, coach, len(have), "prose"),
         "centroid_pooled": ra.routing_from_scores(c_scores, keys, coach, len(cent), "members")}

    print("\n" + "=" * 88)
    print("LAYER D SIGNAL DECISION -- arms fitted on Naren, evaluated on CSM turns")
    print("=" * 88)
    for n, r in R.items():
        print(f"  {n:<18} accepts {int(r.accepted.sum()):>5}/{len(uniq)} "
              f"({r.accepted.mean()*100:>5.1f}%)   margin p50 "
              f"{np.median(r.margin[np.isfinite(r.margin)]):.4f}")
    dis = [i for i in range(len(uniq))
           if R["description"].accepted[i] != R["centroid_pooled"].accepted[i]]
    same_key = sum(1 for i in range(len(uniq))
                   if R["description"].keys[i] == R["centroid_pooled"].keys[i])
    print(f"  accept/reject disagreements: {len(dis)} ({len(dis)/len(uniq)*100:.1f}%)")
    print(f"  identical scenario chosen:   {same_key} ({same_key/len(uniq)*100:.1f}%)")

    # --- blind sample: TURN ONLY, no arm information ---------------------------------------
    rng = random.Random(SEED)
    pick = rng.sample(dis, min(a.n_blind, len(dis)))
    lines = ["=" * 88,
             "IS THIS A SUBSTANTIVE CLIENT MOMENT WORTH COACHING ON? (YES / NO)",
             "These are real turns from CSM calls. Judge the turn alone. No router",
             "information is shown by design.", "=" * 88]
    key = {"items": []}
    for n, i in enumerate(pick, 1):
        lines.append(f"\n[L{n:02d}] {uniq[i][:340]}")
        key["items"].append({"id": f"L{n:02d}", "i": int(i),
                             **{arm: bool(R[arm].accepted[i]) for arm in R},
                             **{f"{arm}_key": R[arm].keys[i] for arm in R}})
    BLIND.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")

    OUT.write_text(json.dumps({
        "n_csm_turns": len(csm), "n_unique": len(uniq), "embedded_now": miss,
        "accept": {n: float(R[n].accepted.mean()) for n in R},
        "n_disagree": len(dis), "same_key_share": same_key / len(uniq),
        "n_keys": len(keys), "n_coachable": int(coach.sum()), "seed": SEED,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {BLIND}\nwrote {KEY}   <-- open only after judging")


if __name__ == "__main__":
    main()
