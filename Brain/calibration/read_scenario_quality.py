#!/usr/bin/env python3
"""READ the scenario-labelled clusters of two adjudication arms. Blinded. Free, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md

WHY. The adjudication A/B is a null -- the rescued arm's verdicts sit inside the ~14% jitter
two identical runs produce. But "the label did not change" is not "the population did not get
better or worse", and this repo's record is that reading real samples is what settles it:
coherence-lift turned out to REWARD junk, a 72.7% orphan rate turned out to be the fix
working, and `implementing_and_maintaining_tracking_pixels` passed every automated check
while really being one client's account.

TWO MODES.
  --mode compare  For clusters BOTH arms call `scenario`, show that cluster's population from
                  each arm side by side, A/B coin-flipped per item. Isolates population
                  quality from verdict jitter, because the label is held equal.
  --mode absolute For one arm, list its `scenario` clusters with their own key, description
                  and a sample -- the "are these good scenarios at all" question, which the
                  paired mode cannot answer because it only compares two arms to each other.

*** compare MODE WRITES TWO FILES AND THE SEPARATION IS THE POINT. ***
    scenario_quality_blind.txt   populations as SET A / SET B, arm identity removed
    scenario_quality_key.json    which set came from which arm
Read the blind file, COMMIT to a verdict per item, THEN open the key. A reader shown the arm
grades the arm.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_scenario_quality.py --arms nc_base_b,nc_rescued
    ..\\.venv\\Scripts\\python.exe calibration/read_scenario_quality.py --arms nc_base_b,nc_rescued --unblind
    ..\\.venv\\Scripts\\python.exe calibration/read_scenario_quality.py --mode absolute --arms nc_rescued
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

BLIND_OUT = ARTIFACTS_DIR / "scenario_quality_blind.txt"
KEY_OUT = ARTIFACTS_DIR / "scenario_quality_key.json"
BENCH = ARTIFACTS_DIR / "clustering_bench.json"
BENCH_MEMBERS = ARTIFACTS_DIR / "clustering_bench_members.json"
SEED = 42
N_ITEMS = 10
N_TURNS = 6


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arms", required=True)
    p.add_argument("--mode", default="compare", choices=("compare", "absolute"))
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--unblind", action="store_true")
    p.add_argument("--n", type=int, default=N_ITEMS)
    return p.parse_args()


def load_arm(name: str) -> dict:
    f = ARTIFACTS_DIR / f"adjudication_ab_{name}.json"
    if not f.exists():
        raise SystemExit(f"no artifact for arm {name!r}")
    return json.loads(f.read_text(encoding="utf-8-sig"))


def memberships(members_from: str | None) -> list[list[int]]:
    """Member indices per cluster POSITION. Both arms hold the base ordering (the harness
    fixes order deliberately), and `verify_against_bench` asserted position alignment, so
    position i is the same cluster in both."""
    if not members_from:
        bench = json.loads(BENCH.read_text(encoding="utf-8-sig"))
        return [[int(i) for i in c["idxs"]] for c in bench["incumbent_clusters"]]
    side = json.loads(BENCH_MEMBERS.read_text(encoding="utf-8-sig"))
    return [[int(i) for i in c] for c in side["arms"][members_from]["clusters"]]


def main() -> None:
    a = _args()
    names = [s.strip() for s in a.arms.split(",") if s.strip()]

    if a.unblind:
        key = json.loads(KEY_OUT.read_text(encoding="utf-8-sig"))
        print(f"\nUNBLINDING  arms={key['arms']}\n" + "=" * 80)
        for g in key["items"]:
            print(f"  ITEM {g['item']:02d}  A={g['A_is']:<12} B={g['B_is']:<12} "
                  f"n_base={g['n_base']:<5} n_rescued={g['n_rescued']:<5} {g['key_a'][:44]}")
        return

    from calibration import routing_bench as rb
    texts, _ = rb.build_pool(a.recordings)
    rng = random.Random(SEED)

    if a.mode == "absolute":
        art = load_arm(names[0])
        mem = memberships(art.get("members_from"))
        scen = [r for r in art["rows"] if r["kind"] == "scenario"]
        print(f"\n{'=' * 88}\n  ARM {names[0]}: {len(scen)} scenario-labelled clusters\n{'=' * 88}")
        for r in sorted(scen, key=lambda x: -x["n_items"])[:a.n]:
            idxs = mem[r["i"]]
            print(f"\n[{r['n_items']:>5} turns / {r['calls']:>3} calls]  {r['scenario_key']}")
            print(f"   desc: {r['business_description'][:150]}")
            print(f"   kw  : {r['keywords'][:110]}")
            for t in rng.sample(idxs, min(N_TURNS, len(idxs))):
                print(f"     - {' '.join(texts[t].split())[:190]}")
        return

    # --- compare -------------------------------------------------------------------------
    if len(names) != 2:
        raise SystemExit("--mode compare needs exactly two arms")
    arts = {n: load_arm(n) for n in names}
    mems = {n: memberships(arts[n].get("members_from")) for n in names}
    rowsby = {n: {r["i"]: r for r in arts[n]["rows"]} for n in names}
    common = [i for i in rowsby[names[0]]
              if rowsby[names[0]][i]["kind"] == "scenario"
              and rowsby[names[1]].get(i, {}).get("kind") == "scenario"]
    print(f"{len(common)} clusters labelled `scenario` by BOTH arms "
          f"({sum(1 for r in arts[names[0]]['rows'] if r['kind']=='scenario')} / "
          f"{sum(1 for r in arts[names[1]]['rows'] if r['kind']=='scenario')} per arm)")
    # only where membership actually differs -- an identical population is not a comparison
    common = [i for i in common if len(mems[names[0]][i]) != len(mems[names[1]][i])]
    print(f"{len(common)} of those where the rescue actually changed membership")
    pick = rng.sample(common, min(a.n, len(common)))

    items, lines = [], [
        "BLIND SCENARIO-POPULATION READING.",
        "Each ITEM is ONE cluster that both taxonomies call a real coachable scenario. The two",
        "SETS are that cluster's member turns under two different membership rules, sampled the",
        "same way. Judge: which SET reads as a more coherent single client situation a coach",
        "could train against? Answer TIE only if genuinely indistinguishable.",
        "=" * 80, ""]
    for i in pick:
        ra, rb_ = rowsby[names[0]][i], rowsby[names[1]][i]
        flip = rng.random() < 0.5
        pair = [(names[1], mems[names[1]][i]), (names[0], mems[names[0]][i])] if flip \
            else [(names[0], mems[names[0]][i]), (names[1], mems[names[1]][i])]
        items.append({"item": len(items) + 1, "cluster_i": i,
                      "A_is": pair[0][0], "B_is": pair[1][0],
                      "n_base": len(mems[names[0]][i]), "n_rescued": len(mems[names[1]][i]),
                      "key_a": ra["scenario_key"], "key_b": rb_["scenario_key"]})
        lines.append(f"ITEM {len(items):02d}   keywords: {ra['keywords'][:100]}")
        for tag, idxs in zip(("A", "B"), [p[1] for p in pair]):
            lines.append(f"  SET {tag}  ({len(idxs)} turns total):")
            for t in rng.sample(idxs, min(N_TURNS, len(idxs))):
                lines.append(f"     - {' '.join(texts[t].split())[:190]}")
        lines.append("")
    BLIND_OUT.write_text("\n".join(lines), encoding="utf-8")
    KEY_OUT.write_text(json.dumps({"arms": names, "seed": SEED, "items": items}, indent=1),
                       encoding="utf-8")
    print(f"\nwrote {BLIND_OUT} ({len(items)} items)\nwrote {KEY_OUT} -- do not open yet")


if __name__ == "__main__":
    main()
