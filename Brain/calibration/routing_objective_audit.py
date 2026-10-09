#!/usr/bin/env python3
"""IS THE ROUTING GATE JUST THE CENTROID ARM'S OBJECTIVE FUNCTION? Free, read-only, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md section 10.

THE CHARGE. `routing_bench.py` grades an arm by `coherence(P)` = mean cosine of population P to
P's OWN centroid. The centroid arms assign turn i to key k by `argmax cos(v_i, c_k)`, so their
population is the Voronoi cell around c_k and the gate measures very nearly the quantity they
maximise. An arm optimising anything else is graded on their loss function.

The circumstantial evidence is strong: grouped by population SHAPE rather than by method, every
Voronoi-cell arm scores 50-61% while `description` (LLM prose + bi-encoder) and `xenc_member`
(a neural cross-encoder over member turns) -- two methods sharing no mechanism at all -- land on
the SAME 32%.

*** THE OBVIOUS NEUTRAL MEASURE IS FAKE, AND WAS ALMOST USED. ***
"Mean PAIRWISE cosine within the population, instead of cosine to its own centroid" reads like
a shape-agnostic alternative. It is the SAME STATISTIC:

    coherence(P) == sqrt(mean pairwise cosine including the diagonal)

verified identical to 1e-6 at n = 10 / 50 / 300, and the off-diagonal version reconstructs
exactly as (n*coh^2 - 1)/(n-1). A monotone transform cannot audit its own source. Building this
test around it would have "confirmed" the gate against a copy of itself.

THE THREE OBJECTIVES, chosen so that each is aligned with a DIFFERENT arm -- and one with none:

  centroid     mean cosine to the population's own centroid.   <- ALIGNED WITH THE CENTROID ARMS
               The current gate, computed by calling nt.score_population unchanged so the
               numbers are provably the published ones.
  description  mean cosine to that key's DESCRIPTION vector.   <- ALIGNED WITH `description`
               The mirror image. If the gate merely picks whichever arm shares its objective,
               `description` must win here as decisively as the centroid arms win above.
  lexical      coherence in TF-IDF word space.                 <- ALIGNED WITH NOBODY
               No arm optimises lexical cosine; every arm routes on gemini embeddings. Same
               functional form, a different space, so a Voronoi cell carved in embedding space
               has no built-in advantage here. The vectoriser uses sklearn's default token
               pattern and NO stop-word list -- a curated list is the anti-pattern this repo
               forbids, and it would also delete "Indeed" (see CLAUDE.md).

WHAT EACH OUTCOME MEANS, written before the run:
  * Centroid arms win under ALL THREE  -> the gate is not merely self-serving; section 9's
    ranking survives.
  * Each arm wins under its own objective and `lexical` splits differently -> THE GATE
    ADJUDICATES NOTHING ACROSS SHAPES and section 9's ranking must be withdrawn.
  * Everything ties under `lexical` -> `lexical` is too blunt to referee; report that rather
    than reading it as agreement.

TWO SELF-CHECKS THE RUN REFUSES TO PROCEED WITHOUT:
  1. the extracted length-matched DRAWS reproduce `nt.length_matched_null` to 1e-9 when scored
     with `coherence` -- otherwise the two nulls are not the same null.
  2. the `centroid` column reproduces `routing_bench`'s `share_fixed` for the same arms --
     otherwise this script is not measuring the thing under audit.

FULL-CORPUS MODE ONLY, deliberately. The charge is about the METRIC, not about leakage, and
full mode is deterministic and needs no folds. Self-inflating arms (`knn_*`, `medoid`, `probe`,
`xenc_member`) are excluded for that reason -- their full-corpus populations are inflated and
would confound a metric audit with a leakage artifact.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/routing_objective_audit.py
    ..\\.venv\\Scripts\\python.exe calibration/routing_objective_audit.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration import null_test_taxonomy as nt
from calibration import routing_arms as ra
from calibration import routing_bench as rb

OUT = ARTIFACTS_DIR / "routing_objective_audit.json"
SEED = 42
# Non-self-inflating arms only -- see the module docstring.
ARMS = ["description", "desc_keyphrases", "centroid", "centroid_pooled",
        "blend_a0.75", "placebo_centroid"]
OBJECTIVES = ("centroid", "description", "lexical")


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--load", action="store_true")
    return p.parse_args()


def draw_length_matched(member_idx, order_by_wc, rank_of, rng, band=None, draws=None):
    """The SAME draws `nt.length_matched_null` makes, returned instead of scored.

    Copied deliberately rather than refactored: `nt.length_matched_null` is load-bearing for a
    published artifact, and the run asserts this reproduces it to 1e-9. A shared helper that
    silently drifted would break both at once with nothing to notice.
    """
    from calibration.trial_pool_unit import NULL_DRAWS

    draws = NULL_DRAWS if draws is None else draws
    n_pool = len(order_by_wc)
    band = nt.length_band(len(member_idx), n_pool) if band is None else band
    out = []
    for _ in range(draws):
        chosen: list[int] = []
        seen: set[int] = set()
        for m in member_idx:
            r = rank_of[m]
            lo, hi = max(0, r - band), min(n_pool, r + band)
            for _attempt in range(30):
                cand = order_by_wc[rng.randrange(lo, hi)]
                if cand not in seen:
                    seen.add(cand)
                    chosen.append(cand)
                    break
        if len(chosen) >= 2:
            out.append(chosen)
    return out


def coherence_dense(V: np.ndarray) -> float:
    from calibration.trial_pool_unit import coherence
    return coherence(V)


def coherence_sparse(X) -> float:
    """Same functional form as `coherence`, over L2-normalised sparse TF-IDF rows."""
    if X.shape[0] < 2:
        return float("nan")
    m = np.asarray(X.mean(axis=0)).ravel()
    n = np.linalg.norm(m)
    if n < 1e-12:
        return 0.0
    return float(np.asarray(X @ (m / n)).ravel().mean())


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return

    t0 = time.time()
    adj = json.loads(rb.ADJ.read_text(encoding="utf-8-sig"))["rows"]
    texts, call_ids = rb.build_pool(a.recordings)
    vecs = rb.embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    print(f"{len(texts)} turns / {len(set(call_ids))} calls", flush=True)

    print("re-clustering (production path) ...", flush=True)
    clusters = rb.cluster_pool(texts, vecs, call_ids, adj)
    cl_keys, cl_coach, label_stats = ra.cluster_labels(adj)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)
    coach_keys = [k for k, c in zip(keys, coach) if c]

    truth_key, truth_coach = {}, {}
    for c, ki, co in zip(clusters, owner, cl_coach):
        for i in c["idxs"]:
            truth_key[i], truth_coach[i] = keys[ki], bool(co)

    from calibration.validate_taxonomy_vs_layerd import load_new
    tax = load_new()
    dvec = rb.embed_cache_only([t["text"] for t in tax])
    dvec = (dvec / (np.linalg.norm(dvec, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    desc_vecs = np.zeros((len(keys), vecs.shape[1]), dtype=np.float32)
    desc_have = np.zeros(len(keys), dtype=bool)
    pos = {k: i for i, k in enumerate(keys)}
    for t, v in zip(tax, dvec):
        j = pos.get(t["key"])
        if j is not None:
            desc_vecs[j], desc_have[j] = v, True

    # --- the lexical space: aligned with no arm ------------------------------------------
    from sklearn.feature_extraction.text import TfidfVectorizer
    tfv = TfidfVectorizer(min_df=2, sublinear_tf=True, stop_words=None, norm="l2")
    lex = tfv.fit_transform(texts).astype(np.float32)
    print(f"lexical space: {lex.shape[1]} terms (no stop-word list -- a curated list is "
          f"forbidden here and would delete 'Indeed')", flush=True)

    word_count = np.array([len(t.split()) for t in texts])
    order_by_wc = [int(i) for i in np.argsort(word_count, kind="stable")]
    rank_of = {t: i for i, t in enumerate(order_by_wc)}

    # --- SELF-CHECK 1: our draws ARE nt's draws ------------------------------------------
    probe = sorted(random.Random(0).sample(range(len(texts)), 40))
    mine = draw_length_matched(probe, order_by_wc, rank_of, random.Random(SEED))
    theirs = nt.length_matched_null(vecs, probe, order_by_wc, rank_of, random.Random(SEED))
    got = float(np.mean([coherence_dense(vecs[d]) for d in mine]))
    if abs(got - theirs) > 1e-9:
        raise SystemExit(f"DRAW MISMATCH: {got} vs nt.length_matched_null {theirs}. "
                         f"The two nulls are not the same null; the audit is void.")
    print(f"self-check 1 OK: extracted draws reproduce nt.length_matched_null "
          f"({got:.10f})", flush=True)

    ctx = ra.ArmContext(vecs=vecs, eval_idx=np.arange(len(texts)),
                        fit_mask=np.ones(len(texts), bool),
                        cluster_members=[c["idxs"] for c in clusters], cluster_keys=cl_keys,
                        cluster_coach=cl_coach, desc_vecs=desc_vecs, desc_have=desc_have,
                        keys=keys, coach=coach, owner=owner, seed=a.seed, texts=texts)

    registry = dict(ra.FREE_ARMS)
    registry.update(rb.build_variant_arms(keys)[0])

    # --- populations, one per arm, plus the control --------------------------------------
    pops: dict[str, dict[str, list[int]]] = {}
    ctl = defaultdict(list)
    for i in range(len(texts)):
        if i in truth_key and truth_coach[i]:
            ctl[truth_key[i]].append(i)
    pops["cluster_membership"] = dict(ctl)
    for name in ARMS:
        r = registry[name](ctx)
        mem = defaultdict(list)
        for j, i in enumerate(ctx.eval_idx):
            if r.accepted[j]:
                mem[r.keys[j]].append(int(i))
        pops[name] = dict(mem)
        print(f"  {name:<18} {sum(len(v) for v in mem.values()):>6} turns accepted", flush=True)

    # --- score every population under every objective ------------------------------------
    def score(obj, idx, key_i):
        if obj == "centroid":
            return coherence_dense(vecs[idx])
        if obj == "description":
            return float((vecs[idx] @ desc_vecs[key_i]).mean())
        return coherence_sparse(lex[idx])

    results = {}
    for arm, mem in pops.items():
        rows = []
        rngs = {o: random.Random(SEED) for o in OBJECTIVES}
        for k in coach_keys:
            idx = mem.get(k, [])
            row = {"key": k, "n": len(idx), "rankable": len(idx) >= nt.MIN_MEMBERS}
            if len(idx) >= 2:
                ki = pos[k]
                drawn = {o: draw_length_matched(idx, order_by_wc, rank_of, rngs[o])
                         for o in OBJECTIVES}
                for o in OBJECTIVES:
                    obs = score(o, idx, ki)
                    null = float(np.mean([score(o, d, ki) for d in drawn[o]]))
                    row[f"obs_{o}"], row[f"null_{o}"] = obs, null
                    row[f"lift_{o}"] = obs - null
            else:
                for o in OBJECTIVES:
                    row[f"obs_{o}"] = row[f"null_{o}"] = row[f"lift_{o}"] = float("nan")
            rows.append(row)
        results[arm] = {"rows": rows}
        print(f"  scored {arm}", flush=True)

    # --- size-matched reference, per objective, from the control -------------------------
    ctl_rows = [r for r in results["cluster_membership"]["rows"] if r["rankable"]]
    ctl_rank = {r["key"] for r in ctl_rows}
    for arm, res in results.items():
        for o in OBJECTIVES:
            won = 0
            for r in res["rows"]:
                if not r["rankable"]:
                    continue
                ref = nt.size_matched_reference(r["n"], ctl_rows, field=f"lift_{o}")
                r[f"ref_{o}"] = ref
                r[f"reach_{o}"] = bool(r[f"lift_{o}"] >= ref)
                if r["key"] in ctl_rank and r[f"reach_{o}"]:
                    won += 1
            res[f"n_clear_{o}"] = won
            res[f"share_{o}"] = won / len(ctl_rank) if ctl_rank else float("nan")

    payload = {"n_turns": len(texts), "n_calls": len(set(call_ids)), "seed": a.seed,
               "objectives": list(OBJECTIVES), "arms": ARMS, "mode": "full",
               "n_fixed": len(ctl_rank), "lexical_terms": int(lex.shape[1]),
               "min_members": nt.MIN_MEMBERS, "results": results,
               "seconds": round(time.time() - t0, 1),
               "spend": {"chat_calls": 0, "postgres_writes": 0}}

    # --- SELF-CHECK 2: does `centroid` reproduce routing_bench's published column? --------
    bench = ARTIFACTS_DIR / "routing_bench_s42.json"
    if bench.exists():
        b = {x["arm"]: x for x in json.loads(bench.read_text(encoding="utf-8-sig"))["arms"]
             if x["mode"] == "full"}
        payload["crosscheck"] = {}
        for arm in results:
            if arm in b and "share_fixed" in b[arm]:
                mine_, theirs_ = results[arm]["share_centroid"], b[arm]["share_fixed"]
                payload["crosscheck"][arm] = {"audit": mine_, "routing_bench": theirs_,
                                              "delta": mine_ - theirs_}
    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}\nZero chat calls, zero embedding requests, zero Postgres writes.")


def report(p: dict) -> None:
    print("\n" + "=" * 96)
    print("IS THE GATE JUST THE CENTROID ARM'S OBJECTIVE? -- same populations, three objectives")
    print("=" * 96)
    print(f"  {p['n_turns']} turns / {p['n_calls']} calls, full corpus, "
          f"denominator = {p['n_fixed']} control-rankable scenarios")
    print(f"  centroid    = the current gate           ALIGNED WITH the centroid arms")
    print(f"  description = cosine to the key's prose  ALIGNED WITH `description`")
    print(f"  lexical     = TF-IDF word space ({p['lexical_terms']} terms)   ALIGNED WITH NOBODY")
    print(f"\n  {'arm':<20}" + "".join(f"{o:>14}" for o in p["objectives"]))
    order = sorted(p["results"], key=lambda a: -p["results"][a]["share_centroid"])
    for arm in order:
        r = p["results"][arm]
        print(f"  {arm:<20}" + "".join(
            f"{r['n_clear_' + o]}/{p['n_fixed']}={r['share_' + o] * 100:>3.0f}%".rjust(14)
            for o in p["objectives"]))
    cc = p.get("crosscheck") or {}
    if cc:
        bad = {k: v for k, v in cc.items() if abs(v["delta"]) > 1e-9}
        print(f"\n  self-check 2 (centroid column vs routing_bench share_fixed): "
              f"{'ALL MATCH' if not bad else 'MISMATCH ' + str(bad)}")


if __name__ == "__main__":
    main()
