#!/usr/bin/env python3
"""READ what the noise-rescue actually ADDS to each scenario. Free: no chat, no DB, no fetch.

Spec: docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md ("Read real
samples before believing any aggregate -- non-negotiable").

*** THE UNIT OF READING IS THE MODIFICATION, NOT THE CLUSTER. *** `rescue_centroid` keeps the
incumbent's clusters and only GROWS them, so sampling whole clusters from each arm compares two
random draws from the SAME cluster set -- with ~2/3 of clusters being sinks, that measures which
draw was junk-heavier and nothing else. That mistake was made once already on this rule and had
to be redone with an `--added` mode. This script only ever prints the ADDED turns, against the
originals of the SAME cluster, so the comparison is symmetric by construction.

THE QUESTION IT ANSWERS: for each scenario the rescued taxonomy produced, do the turns the
rescue admitted actually belong to that scenario -- or is the rule dragging in adjacent
material that merely sits near the centroid?

Three things are printed per cluster, in this order deliberately:
  1. the scenario Gemma wrote FROM the grown cluster (key + description)
  2. the ORIGINAL member turns most central to the cluster
  3. the ADDED turns, most-central first AND least-central last
The least-central additions are where the rule fails if it fails: the p25 member-cosine floor
is a per-cluster property, so a loose cluster admits loosely.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_rescue_additions.py --arm clean2_rescued
    ..\\.venv\\Scripts\\python.exe calibration/read_rescue_additions.py --arm clean2_rescued --kind mechanics
    ..\\.venv\\Scripts\\python.exe calibration/read_rescue_additions.py --arm clean2_rescued --top 8 --samples 6
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default="clean2_rescued",
                   help="adjudication arm whose scenarios the additions are judged against")
    p.add_argument("--base-arm", default="clean2_base",
                   help="the un-rescued arm, for the same cluster's verdict before the rescue")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--kind", default="scenario",
                   choices=("scenario", "merged", "mechanics", "logistics", "all"))
    p.add_argument("--top", type=int, default=12, help="clusters to print, most-added first")
    p.add_argument("--samples", type=int, default=4, help="turns shown per section")
    p.add_argument("--chars", type=int, default=210)
    return p.parse_args()


def _one(t: str, n: int) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n - 1] + "…"


def main() -> None:
    a = _args()
    from calibration.adjudication_ab import build_clusters, paths as adj_paths
    from calibration.clustering_bench import rescue_centroid_additions
    from shared import cluster_evidence

    art = {}
    for name in (a.arm, a.base_arm):
        _, out = adj_paths(name)
        if not out.exists():
            raise SystemExit(f"missing {out.name} -- run adjudication_ab.py --arm {name} first")
        art[name] = json.loads(out.read_text(encoding="utf-8-sig"))
    rows = {r["cluster_id"]: r for r in art[a.arm]["rows"]}
    base_rows = {r["cluster_id"]: r for r in art[a.base_arm]["rows"]}

    # Base memberships, then the rescue recomputed IN PROCESS. Same call adjudication_ab makes,
    # so the additions read here are byte-identical to the ones the arm was adjudicated on --
    # a separate re-implementation is exactly how a reading stops describing the real run.
    clusters, texts, call_ids, vecs, total_calls, _ta = build_clusters(a.recordings, "", "")

    assigned = {i for c in clusters for i in c["idxs"]}
    noise = sorted(set(range(len(texts))) - assigned)

    class _Ctx:
        pass
    ctx = _Ctx()
    ctx.vecs = vecs
    adds = rescue_centroid_additions(ctx, clusters, noise)
    print(f"\n[rescue] +{sum(len(x) for x in adds)} turns across {len(clusters)} clusters "
          f"({len(noise)} were noise)\n", flush=True)

    # --- WHERE DOES THE RESCUE'S EFFORT ACTUALLY GO? -----------------------------------
    # Printed unconditionally, before any --kind filter, because it bounds every downstream
    # claim: additions that land in a SINK are discarded on arrival, so they cap the effect
    # the rescue can possibly have on a rubric no matter how good they are. The four kinds
    # mean four different things and are never collapsed:
    #   scenario   -> shaped a real scenario's description. CAN reach a rubric.
    #   merged     -> RETAINED, but only informed a "this is a duplicate of X" decision;
    #                 no description of its own was written.
    #   mechanics  } -> shaped a SINK's description. Discarded either way.
    #   logistics  }
    split: dict[str, dict] = {}
    for c, add in zip(clusters, adds):
        row = rows.get(c["cluster_id"])
        k = row["kind"] if row else "(not adjudicated: failed triage)"
        s = split.setdefault(k, {"clusters": 0, "added": 0, "orig": 0, "thin": 0})
        s["clusters"] += 1
        s["added"] += len(add)
        s["orig"] += len(c["idxs"])
        s["thin"] += sum(1 for i in add
                         if not cluster_evidence.is_substantive(texts[i], 5))
    tot_add = sum(s["added"] for s in split.values()) or 1

    print("=" * 100)
    print("WHERE THE RESCUE'S ADDED TURNS GO")
    print("=" * 100)
    print(f"  {'kind':<34}{'clusters':>9}{'added':>9}{'share':>8}{'orig':>9}"
          f"{'growth':>9}{'content-free':>14}")
    for k in ("scenario", "merged", "mechanics", "logistics",
              "(not adjudicated: failed triage)", "failed"):
        s = split.get(k)
        if not s:
            continue
        print(f"  {k:<34}{s['clusters']:>9}{s['added']:>9}{s['added']/tot_add*100:>7.1f}%"
              f"{s['orig']:>9}{s['added']/max(s['orig'],1)*100:>8.0f}%"
              f"{s['thin']/max(s['added'],1)*100:>13.1f}%")
    reach = sum(split.get(k, {}).get("added", 0) for k in ("scenario",))
    sunk = sum(split.get(k, {}).get("added", 0) for k in ("mechanics", "logistics"))
    print(f"\n  -> into a COACHABLE scenario : {reach:>6} ({reach/tot_add*100:.1f}%)")
    print(f"  -> into a SINK (discarded)   : {sunk:>6} ({sunk/tot_add*100:.1f}%)")
    print(f"  The sink share is a CEILING on the rescue's downstream effect: those turns are")
    print(f"  dropped by layer_b's sink short-circuit however good they are.\n")

    items = []
    for c, add in zip(clusters, adds):
        cid = c["cluster_id"]
        row = rows.get(cid)
        if not row or not add:
            continue
        if a.kind != "all" and row["kind"] != a.kind:
            continue
        cen = c["stats"].centroid
        orig = sorted(c["idxs"], key=lambda i: -float(vecs[i] @ cen))
        add_sorted = sorted(add, key=lambda i: -float(vecs[i] @ cen))
        items.append((len(add), cid, row, orig, add_sorted, cen))
    items.sort(key=lambda x: -x[0])

    thin_all, thin_add = [], []
    for _, _, _, orig, add_sorted, _ in items:
        thin_all += [not cluster_evidence.is_substantive(texts[i], 5) for i in orig]
        thin_add += [not cluster_evidence.is_substantive(texts[i], 5) for i in add_sorted]

    print("=" * 100)
    print(f"WHAT THE RESCUE ADDS -- kind={a.kind}, {len(items)} cluster(s) with >=1 addition")
    print("=" * 100)
    if thin_add:
        print(f"content-free share:  ORIGINAL members {np.mean(thin_all)*100:5.1f}%   "
              f"ADDED turns {np.mean(thin_add)*100:5.1f}%")
        print("  (added >> original would mean the rule is diluting these clusters with "
              "filler)\n")

    for n_add, cid, row, orig, add_sorted, cen in items[:a.top]:
        b = base_rows.get(cid, {})
        flip = ("" if b.get("kind") == row["kind"]
                else f"   [was '{b.get('kind','?')}' in {a.base_arm}]")
        print("\n" + "-" * 100)
        # `orig` is the BASE membership (rescue_centroid_additions does not mutate), so the
        # original count is len(orig) and the total is len(orig)+n_add. An earlier version
        # printed `len(orig)-n_add` as "original", which went NEGATIVE whenever the rescue
        # added more than the cluster started with -- which it does on the clusters it helps
        # most.
        print(f"cluster {cid}  |  {len(orig)} original + {n_add} ADDED = {len(orig)+n_add} "
              f"turns  |  {row['calls']} calls{flip}")
        print(f"  {row['kind'].upper()}: {row['scenario_key']}")
        print(f"  description: {_one(row.get('business_description') or '(none)', 300)}")
        kp = row.get("keyphrases") or []
        if kp:
            print(f"  keyphrases : {', '.join(str(k) for k in kp[:8])}")

        orig_only = [i for i in orig if i not in set(add_sorted)]
        print(f"\n  ORIGINAL members (most central):")
        for i in orig_only[:a.samples]:
            print(f"    [{float(vecs[i] @ cen):.3f}] {_one(texts[i], a.chars)}")
        print(f"\n  ADDED by the rescue (most central):")
        for i in add_sorted[:a.samples]:
            print(f"    [{float(vecs[i] @ cen):.3f}] {_one(texts[i], a.chars)}")
        if len(add_sorted) > a.samples:
            print(f"  ADDED by the rescue (LEAST central -- where the rule fails if it does):")
            for i in add_sorted[-min(a.samples, len(add_sorted) - a.samples):]:
                print(f"    [{float(vecs[i] @ cen):.3f}] {_one(texts[i], a.chars)}")

    print("\n" + "=" * 100)
    print("Judge each block on ONE question: do the ADDED turns belong to the scenario named")
    print("above them, or merely sit near its centroid? Aggregates cannot answer that.")


if __name__ == "__main__":
    main()
