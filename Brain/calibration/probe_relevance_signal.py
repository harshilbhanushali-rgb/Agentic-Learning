#!/usr/bin/env python3
"""Can a clause tell its OWN scenario from a RANDOM one? Cache-only, no Layer C. Free.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md

*** WHY THIS IS THE DECISIVE MEASUREMENT. *** Every Layer B arm in this trial came back null,
and the permutation placebo showed Layer C produces a similar milestone set from randomly
routed pairs as from correctly routed ones. Two explanations were on the table:

  (a) `milestone_relevance_percentile: 40` is a PERCENTILE, so it keeps the top 60% of
      whatever it is given and cannot reject mis-routed content in absolute terms;
  (b) there is no separation to reject on -- a clause's cosine to its own scenario is not
      materially higher than to a random one.

(a) is proven arithmetic: survival was EXACTLY 60.0% in three arms with very different pools.
But (a) is only a problem if (b) is false. If real and random clauses are indistinguishable in
this space, then no filter of any shape -- percentile, absolute floor, or learned -- can help,
and the whole routing question is unanswerable rather than merely unanswered.

The milestone-level `relevance_mean` already hints at (b): 0.6340 real vs 0.6265 random, a
0.0075 gap against a ~0.06 spread. But that figure is DOUBLY SELECTED -- those clauses had
already survived the p40 cut AND formed a cluster -- so it understates the raw separation. This
measures it at the CLAUSE level, before any filtering, which is the honest test.

METHOD. For every clause routed to a coachable scenario, compute cosine to (1) its own
scenario's vector and (2) `--draws` randomly chosen OTHER coachable scenarios. Report both
distributions, the paired per-clause difference, and the AUC of using cosine to tell them
apart. AUC is the number that matters: 0.5 is chance, and this repo has retired signals at
0.617 as "nowhere near a value any threshold here was adopted at".

PAIRED, not two independent samples: the same clause is scored against both, so clause length
and topic are held constant and only the target scenario changes. An unpaired comparison would
confound the answer with which clauses happened to land where.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/probe_relevance_signal.py --taxonomy clean2_base
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


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(a random positive scores above a random negative). Rank-based, ties at 0.5."""
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    # average ranks for ties, so a perfectly flat signal scores exactly 0.5
    _, inv, counts = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    r_pos = ranks[:len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--taxonomy", default="clean2_base")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--draws", type=int, default=3, help="random scenarios per clause")
    p.add_argument("--width", type=int, default=3072)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()

    from calibration.layer_bc_arms import (scenario_map_from_rows, taxonomy_path,
                                           install_embedder_shim, prewarm, build_pairs)
    from shared.scenario_vectors import scenario_text, build_scenario_vecs
    from v1.layer_b import assign_scenarios
    from v2.layer_c import build_clause_pool
    from preprocessing import embedder

    art = json.loads(taxonomy_path(a.taxonomy).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(art["rows"])
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(a.width)

    pairs = build_pairs(a.recordings, "s0", "a0")
    assign_scenarios(pairs, scenario_map, None)

    keys, svecs = build_scenario_vecs(scenario_map)
    S = np.asarray(svecs, dtype=np.float32)
    S /= np.linalg.norm(S, axis=1, keepdims=True) + 1e-10
    pos_of = {k: i for i, k in enumerate(keys)}
    coachable = [i for i, k in enumerate(keys) if scenario_map[k]["is_coachable"]]
    print(f"[probe] {len(coachable)} coachable scenarios of {len(keys)}", flush=True)

    # Only clauses that ACTUALLY reach Layer C: pairs routed to a coachable scenario. Including
    # sink-filed pairs would measure a different population from the one the filter sees.
    by_key: dict[str, list[dict]] = {}
    for pr in pairs:
        k = pr["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key.setdefault(k, []).append(pr)

    rng = random.Random(a.seed)
    own, rnd = [], []
    for n, (key, ps) in enumerate(sorted(by_key.items()), 1):
        clauses, _, _, _ = build_clause_pool(ps)
        if not clauses:
            continue
        V = embedder.embed_document_matrix(clauses)
        V = np.asarray(V, dtype=np.float32)
        V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-10
        own.append(V @ S[pos_of[key]])
        others = [i for i in coachable if i != pos_of[key]]
        for _ in range(a.draws):
            rnd.append(V @ S[rng.choice(others)])
        if n % 10 == 0 or n == len(by_key):
            print(f"  {n}/{len(by_key)} scenarios", flush=True)

    own_v = np.concatenate(own)
    rnd_v = np.concatenate(rnd)
    # PAIRED: each clause's own score against the mean of its own random draws.
    paired = np.concatenate([o - sum(rnd[i * a.draws + d] for d in range(a.draws)) / a.draws
                             for i, o in enumerate(own)])

    def row(lbl, v):
        return (f"  {lbl:<22}{len(v):>9}{v.mean():>10.4f}"
                + "".join(f"{np.percentile(v, q):>9.4f}" for q in (10, 25, 50, 75, 90)))

    print("\n" + "=" * 84)
    print(f"CLAUSE -> SCENARIO COSINE, {a.taxonomy}   (own vs {a.draws} random scenarios)")
    print("=" * 84)
    print(f"  {'':<22}{'n':>9}{'mean':>10}{'p10':>9}{'p25':>9}{'p50':>9}{'p75':>9}{'p90':>9}")
    print(row("own scenario", own_v))
    print(row("random scenario", rnd_v))
    print(f"\n  mean gap              {own_v.mean() - rnd_v.mean():>+9.4f}")
    print(f"  PAIRED mean gap       {paired.mean():>+9.4f}   "
          f"(clause held constant, only the target changes)")
    print(f"  clauses scoring their OWN scenario higher: "
          f"{(paired > 0).mean():.1%}  (chance = 50%)")
    print(f"  AUC                   {auc(own_v, rnd_v):>9.4f}   "
          f"(0.5 = chance; this repo retired signals at 0.617)")

    out = ARTIFACTS_DIR / f"relevance_signal_{a.taxonomy}.json"
    out.write_text(json.dumps({
        "taxonomy": a.taxonomy, "draws": a.draws, "n_clauses": int(len(own_v)),
        "own_mean": float(own_v.mean()), "random_mean": float(rnd_v.mean()),
        "paired_mean_gap": float(paired.mean()),
        "share_own_higher": float((paired > 0).mean()),
        "auc": float(auc(own_v, rnd_v)),
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {out}\nZERO chat calls, cache-only embeddings, Layer C never ran.")


if __name__ == "__main__":
    main()
