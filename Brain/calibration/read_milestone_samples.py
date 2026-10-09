#!/usr/bin/env python3
"""BLIND READ of the milestones an arm GAINS. F6, the veto. Free -- artifacts only.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md section 4.2

*** THE UNIT OF READING IS THE MODIFICATION, NOT THE ARM. *** Sampling each arm independently
would compare two random draws from a mostly-shared milestone set -- with ~85% of milestones
matched between arms, that measures which draw was junk-heavier, not what the arm did. This
samples exactly the milestones the arm GAINED (present in the arm, unmatched in the control)
and pits them against the control's own milestones, which are the accepted standard. Precedent:
`clustering_bench --added`, and the routing trial's `read_routed_samples`.

*** THE KEY GOES IN A SEPARATE FILE. *** Samples to `--out`, answers to `--key`. The reader
commits every judgment before opening the key. A reader who can see which item came from which
arm is grading the label, not the content -- the same discipline the head-to-head trial used
for position-swapped judging.

WHAT A MILESTONE IS HERE. Layer C Pass 1 is Gemma-free, so a milestone is a CLUSTER of Naren
response clauses -- it has no written description (that is Pass 3, an LLM call this trial never
makes). So the reader sees the clauses themselves, which is the actual evidence, not a
paraphrase of it.

THE QUESTION THE READER ANSWERS is deliberately arm-independent: "is this a coherent, coachable
move a CSM could apply to a different client?" Asking "which arm is better" would let the
reader's model of the treatment drive the answer, which is how the routing trial's first blind
read got reversed by its own v2.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_milestone_samples.py \\
        --control s0a0r0_r --arm s0a0r1_r --n 12
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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--control", required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--n", type=int, default=12, help="items PER SIDE")
    p.add_argument("--clauses", type=int, default=5, help="clauses shown per milestone")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="")
    p.add_argument("--key", default="")
    a = p.parse_args()

    out = Path(a.out or ARTIFACTS_DIR / f"blindread_{a.arm}.txt")
    key = Path(a.key or ARTIFACTS_DIR / f"blindread_{a.arm}_KEY.json")

    ca, aa = load(a.control), load(a.arm)
    cby = {s["cluster_id"]: s for s in ca["per_scenario"].values() if s.get("cluster_id")}
    aby = {s["cluster_id"]: s for s in aa["per_scenario"].values() if s.get("cluster_id")}

    gained, kept = [], []
    for cid in sorted(set(cby) & set(aby)):
        c, m = cby[cid], aby[cid]
        _, new = match_milestones(c["milestones"], m["milestones"],
                                  c.get("scenario_calls", 0), m.get("scenario_calls", 0))
        # `new` carries only the first 3 clauses; re-find the full milestone by clause identity
        # so the reader sees the same amount of evidence for both sides. Showing gained items
        # truncated and control items in full would be an asymmetric filter on the READING.
        for g in new:
            head = tuple(g["clauses"])
            for ms in m["milestones"]:
                if tuple(ms["clauses"][:3]) == head:
                    gained.append((cid, ms))
                    break
        kept.extend((cid, ms) for ms in c["milestones"])

    if not gained:
        raise SystemExit(f"{a.arm} gained no milestones over {a.control} -- nothing to read")

    rng = random.Random(a.seed)
    g = rng.sample(gained, min(a.n, len(gained)))
    k = rng.sample(kept, min(a.n, len(kept)))
    items = [("GAINED", cid, ms) for cid, ms in g] + [("CONTROL", cid, ms) for cid, ms in k]
    rng.shuffle(items)

    lines = [
        f"BLIND READ -- {a.arm} vs {a.control}",
        f"{len(g)} gained + {len(k)} control, shuffled. Source is in the KEY file, not here.",
        "",
        "QUESTION for each item: is this a coherent, coachable move a CSM could apply to a",
        "DIFFERENT client?  Answer YES or NO. Do not guess which arm it came from.",
        "=" * 96, ""]
    for i, (_, _, ms) in enumerate(items, 1):
        lines.append(f"--- ITEM {i}   ({ms['support_calls']} calls, "
                     f"{ms['support_clauses']} clauses) ---")
        for cl in ms["clauses"][:a.clauses]:
            lines.append(f"    - {cl.strip()[:200]}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    key.write_text(json.dumps({
        "arm": a.arm, "control": a.control, "seed": a.seed,
        "n_gained_available": len(gained), "n_control_available": len(kept),
        "answers": [{"item": i, "source": src, "cluster_id": cid,
                     "support_calls": ms["support_calls"]}
                    for i, (src, cid, ms) in enumerate(items, 1)],
    }, indent=1), encoding="utf-8")

    print(f"{len(gained)} milestones gained by {a.arm} over {a.control}")
    print(f"samples -> {out}")
    print(f"KEY     -> {key}   <- DO NOT OPEN until judgments are committed")


if __name__ == "__main__":
    main()
