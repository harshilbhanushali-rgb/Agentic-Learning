#!/usr/bin/env python3
"""POWERED blind read with built-in controls. F6, rebuilt to have power. Free.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md section 4.2

*** WHY THE FIRST BLIND READ WAS NOT ENOUGH. *** It ran 20 items, one reader, and that reader
had designed the arms. It answered "are the added milestones as good as the existing ones"
(9/10 vs 6/10, Fisher p=0.303) -- suggestive, underpowered, and asking the softer question.

THREE THINGS CHANGE HERE.

1. THE COMPARISON. `r1`-gained against PLACEBO-gained, not against the control's existing
   milestones. The aggregate says the permutation placebo reproduced `r1` (112 new milestones
   to `r1`'s 126), so the decisive content-level question is whether membership routing chose
   BETTER THAN A COIN FLIP. Comparing against the control asks something easier that both arms
   would likely pass.

2. THE READERS ARE INDEPENDENT. Three subagents who did not design the arms and are not told
   which item came from where. The author of a treatment is the worst available judge of it,
   and this repo has said so about its own earlier reads.

3. *** THE INSTRUMENT IS TESTED BEFORE ITS OUTPUT IS BELIEVED. *** Two controls are mixed in:

     NEGATIVE  clauses pulled from SEVERAL UNRELATED scenarios and glued together, with
               support numbers drawn from the real distribution so they cannot be spotted by
               metadata. A reader who accepts these is not discriminating.
     POSITIVE  the highest-support milestones the pipeline already produces. A reader who
               rejects these is applying a bar nothing could pass.

   Three judges in this repo have failed their own nulls -- the applicability judge at
   1.22:1, the coverage judge at 64.9% vs 65.7%, and the head-to-head judge at 0.669 on
   position-swap agreement. A read whose controls are not checked is a story.

   AND THE NEGATIVE CONTROL CARRIES ITS OWN FINDING. Its clauses are all real Naren speech --
   only their COHERENCE is destroyed. So if readers cannot reject them, the failure is not
   fluency: it means Layer C's clusters are not coherent objects, which is a larger result
   than anything the main comparison can produce.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/blind_read_powered.py \\
        --a s0a0r1_r --b s0a0r1p_r --control s0a0r0_r --n 30
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
from calibration.layer_bc_arms import match_milestones


def load(name: str) -> dict:
    p = ARTIFACTS_DIR / f"layer_bc_{name}.json"
    if not p.exists():
        raise SystemExit(f"no artifact for {name!r}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def gained_milestones(control: dict, arm: dict) -> list[dict]:
    """Milestones present in `arm` and unmatched in `control`, joined on cluster_id."""
    cby = {s["cluster_id"]: s for s in control["per_scenario"].values() if s.get("cluster_id")}
    aby = {s["cluster_id"]: s for s in arm["per_scenario"].values() if s.get("cluster_id")}
    out = []
    for cid in sorted(set(cby) & set(aby)):
        c, m = cby[cid], aby[cid]
        _, new = match_milestones(c["milestones"], m["milestones"],
                                  c.get("scenario_calls", 0), m.get("scenario_calls", 0))
        heads = {tuple(g["clauses"]) for g in new}
        out += [ms for ms in m["milestones"] if tuple(ms["clauses"][:3]) in heads]
    return out


def scrambled(pool: list[dict], n: int, rng: random.Random,
              real_support: list[tuple[int, int]]) -> list[dict]:
    """NEGATIVE CONTROL: real clauses from SEVERAL unrelated milestones, glued together.

    Every clause is genuine Naren speech, so a reader cannot reject these on fluency, register
    or vocabulary -- ONLY on the fact that they do not belong together. That is exactly the
    property a milestone is supposed to have, so it is the right thing to isolate.

    Support numbers are sampled from the REAL distribution rather than invented, because a
    reader who noticed that every scrambled item had, say, 3 calls would be grading metadata.
    """
    out = []
    for _ in range(n):
        srcs = rng.sample(pool, min(5, len(pool)))
        clauses = [rng.choice(s["clauses"]) for s in srcs]
        calls, cl = rng.choice(real_support)
        out.append({"clauses": clauses, "support_calls": calls, "support_clauses": cl})
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--a", required=True, help="treatment arm")
    p.add_argument("--b", required=True, help="its placebo")
    p.add_argument("--control", required=True)
    p.add_argument("--n", type=int, default=30, help="items per treatment side")
    p.add_argument("--controls", type=int, default=10, help="items per control side")
    p.add_argument("--clauses", type=int, default=5)
    p.add_argument("--seed", type=int, default=17)
    a = p.parse_args()

    ctrl, arm_a, arm_b = load(a.control), load(a.a), load(a.b)
    ga = gained_milestones(ctrl, arm_a)
    gb = gained_milestones(ctrl, arm_b)
    allc = [m for s in ctrl["per_scenario"].values() for m in s["milestones"]]
    if not ga or not gb:
        raise SystemExit("one arm gained nothing -- there is no comparison to read")

    rng = random.Random(a.seed)
    real_support = [(m["support_calls"], m["support_clauses"]) for m in ga + gb]

    items = ([("A_TREAT", m) for m in rng.sample(ga, min(a.n, len(ga)))]
             + [("B_PLACEBO", m) for m in rng.sample(gb, min(a.n, len(gb)))]
             + [("POS_CONTROL", m) for m in
                sorted(allc, key=lambda m: -m["support_calls"])[:a.controls]]
             + [("NEG_SCRAMBLED", m) for m in
                scrambled(allc, a.controls, rng, real_support)])
    rng.shuffle(items)

    out = ARTIFACTS_DIR / f"blindread2_{a.a}.txt"
    key = ARTIFACTS_DIR / f"blindread2_{a.a}_KEY.json"

    lines = [
        "BLIND READ -- milestone coherence",
        "",
        "Each ITEM below is a group of sentences taken from a sales expert's replies across",
        "several real client calls. A good group is one COHERENT COACHING MOVE: the sentences",
        "are different instances of the same thing the expert does.",
        "",
        "For each item answer exactly one line:   <n>: YES   or   <n>: NO",
        "",
        "YES = these sentences are instances of ONE coherent move that a different account",
        "      manager could learn and apply to a DIFFERENT client.",
        "NO  = they do not hold together as one move, or the 'move' is generic filler",
        "      (agreeing, offering to follow up, listing names) rather than a technique.",
        "",
        "Judge ONLY what is written. Items come from several sources in shuffled order; do not",
        "try to infer the source, and do not assume any particular share should be YES.",
        "=" * 96, ""]
    for i, (_, ms) in enumerate(items, 1):
        lines.append(f"--- ITEM {i}   ({ms['support_calls']} calls, "
                     f"{ms['support_clauses']} sentences total) ---")
        for cl in ms["clauses"][:a.clauses]:
            lines.append(f"    - {cl.strip()[:220]}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    key.write_text(json.dumps({
        "treatment": a.a, "placebo": a.b, "control": a.control, "seed": a.seed,
        "n_available": {"a": len(ga), "b": len(gb), "control": len(allc)},
        "answers": [{"item": i, "source": src, "support_calls": ms["support_calls"]}
                    for i, (src, ms) in enumerate(items, 1)],
    }, indent=1), encoding="utf-8")

    from collections import Counter
    print(f"{len(ga)} gained by {a.a}, {len(gb)} by {a.b} (placebo)")
    print(f"composition: {dict(Counter(s for s, _ in items))}")
    print(f"samples -> {out}")
    print(f"KEY     -> {key}   <- readers must never see this")


if __name__ == "__main__":
    main()
