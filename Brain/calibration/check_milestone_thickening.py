#!/usr/bin/env python3
"""Resolve THICKENING vs DILUTION for the by_cluster arm's support jumps.

replay_layer_c_admitted.py reported that admitting cluster-verdict-rescued pairs
raised several milestones' distinct-call support dramatically (e.g. 6 -> 36,
22 -> 133 calls) and called that "evidence thickening" -- the same recurring move,
now backed by far more calls.

There is a competing reading that number alone cannot distinguish. In
client_requests_operational_visualization, THREE separate baseline milestones all
landed at exactly 133 calls. If that is at or near the scenario's total call count,
each "milestone" now appears in essentially every call -- which makes it generic
background, not a distinctive coaching move. The support gate exists precisely to
prove a move RECURS; a move present everywhere proves nothing.

Two readings, opposite conclusions, same number. This script settles it by printing
what the milestone clusters actually CONTAIN before and after, alongside support as
a FRACTION of the scenario's own call count (which itself grows when pairs from new
calls are admitted -- 133 of 133 and 133 of 200 mean very different things).

Zero Gemma. Zero DB writes. Imports replay_layer_c_admitted's own _pass1/_route so
it measures the same thing that arm measured, not a re-implementation.

Usage (from Brain/, venv active):
    python check_milestone_thickening.py
    python check_milestone_thickening.py --clauses 12
"""
from __future__ import annotations
import argparse
import sys

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from shared import storage
from shared.tuning import load_tuning
from replay_layer_c_admitted import _load_everything, _route, _pass1


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--clauses", type=int, default=8,
                   help="clauses to print per milestone side")
    return p.parse_args()


def _best_match(base_clauses: set[str], arm_milestones: list[dict]):
    """Same majority-overlap rule replay_layer_c_admitted uses, but returns the
    whole arm milestone so its contents can be read rather than just counted."""
    best, best_overlap = None, 0
    for m in arm_milestones:
        overlap = len(base_clauses & set(m["clauses"]))
        if overlap > best_overlap:
            best, best_overlap = m, overlap
    if best is None or best_overlap / len(base_clauses) <= 0.5:
        return None, best_overlap
    return best, best_overlap


def main() -> None:
    args = _parse_args()
    config = load_config()
    tuning = load_tuning().layer_c
    conn = storage.get_connection(config.database_url)
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs = _load_everything(conn)
    conn.close()

    sink_pairs = [p for p in pairs if p["is_sink"]]
    by_key: dict[str, list[dict]] = {}
    for p in pairs:
        if not p["is_sink"]:
            by_key.setdefault(p["scenario_key"], []).append(p)

    admitted = _route("by_cluster", sink_pairs, scenario_map)
    targets = sorted(admitted, key=lambda k: -len(admitted[k]))
    print(f"by_cluster routes into {len(targets)} scenario(s): "
          f"{', '.join(f'{k} (+{len(admitted[k])} pairs)' for k in targets)}\n")

    for key in targets:
        info = scenario_map[key]
        base = _pass1(info, by_key.get(key, []), [], tuning)
        treat = _pass1(info, by_key.get(key, []), admitted[key], tuning)

        b_calls = base.get("scenario_calls", 0)
        t_calls = treat.get("scenario_calls", 0)
        print("=" * 78)
        print(f"{key}")
        print("=" * 78)
        print(f"  scenario call count : {b_calls} -> {t_calls} "
              f"(+{t_calls - b_calls} calls arrive with the admitted pairs)")
        print(f"  required support    : {base.get('required_support')} -> "
              f"{treat.get('required_support')}")
        print(f"  clause pool         : {base['n_clauses_total']} -> "
              f"{treat['n_clauses_total']} "
              f"({treat['extra_surviving_relevance']} admitted clauses survived relevance)")
        print(f"  milestones          : {len(base['milestones'])} -> "
              f"{len(treat['milestones'])}")

        t_supports = [m["support_calls"] for m in treat["milestones"]]
        if t_supports:
            saturated = sum(1 for s in t_supports if t_calls and s >= 0.9 * t_calls)
            print(f"  treatment supports  : {sorted(t_supports, reverse=True)}")
            print(f"  >=90% of all calls  : {saturated}/{len(t_supports)} "
                  f"<-- DILUTION INDICATOR: a milestone in nearly every call is "
                  f"background, not a distinctive move")

        for bm in base["milestones"]:
            bset = set(bm["clauses"])
            if not bset:
                continue
            match, overlap = _best_match(bset, treat["milestones"])
            if match is None or match["support_calls"] <= bm["support_calls"]:
                continue

            b_frac = bm["support_calls"] / b_calls if b_calls else 0
            t_frac = match["support_calls"] / t_calls if t_calls else 0
            print("\n  " + "-" * 74)
            print(f"  THICKENED: support {bm['support_calls']} -> "
                  f"{match['support_calls']} calls   "
                  f"({b_frac:.0%} -> {t_frac:.0%} of the scenario's calls)")
            print(f"    clause count : {len(bm['clauses'])} -> {len(match['clauses'])}")
            print(f"    admitted share of the new cluster: "
                  f"{match['extra_fraction']:.0%}")
            print(f"    overlap with the baseline cluster: {overlap}/{len(bset)} clauses")
            print(f"    BEFORE ({min(args.clauses, len(bm['clauses']))} of "
                  f"{len(bm['clauses'])} clauses):")
            for c in bm["clauses"][:args.clauses]:
                print(f"      - {c[:150]}")
            print(f"    AFTER ({min(args.clauses, len(match['clauses']))} of "
                  f"{len(match['clauses'])} clauses):")
            for c in match["clauses"][:args.clauses]:
                print(f"      + {c[:150]}")
        print()


if __name__ == "__main__":
    main()
