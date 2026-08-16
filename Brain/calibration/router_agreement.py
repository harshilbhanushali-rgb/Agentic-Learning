#!/usr/bin/env python3
"""How much does each router actually CHANGE? Layer B only -- no Layer C, no UMAP. Free.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md sections 3.1-3.3

*** WHY THIS EXISTS AS A SEPARATE TOOL. *** A blind audit found that `r1_lookup_share`
overstates R1's treatment: it counts every pair whose turn carried a cluster label, INCLUDING
the pairs where the lookup landed on the same scenario `r0` would have chosen anyway. Those
contribute nothing to the treatment -- they are agreement, not effect. It is the "metric that
only counts the good outcome" shape this repo has already paid for twice.

The honest number is `resolved AND differs from r0`, and answering it needs pairs, member sets
and description similarities -- NOT clustering. Re-running a whole arm to recover one
diagnostic would spend ~3 minutes of UMAP per taxonomy to compute something Layer B already
knows. This does Layer B once and reports every router against `r0` in the same pass.

WHAT THE ANSWER IS FOR. A null result from a router is only interpretable if you know how much
of the population it actually moved. If R1 re-routes 8% of pairs, a null is F2 territory -- the
arm barely fired -- and reads completely differently from a null on 45%.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/router_agreement.py --taxonomy clean2_base
    ..\\.venv\\Scripts\\python.exe calibration/router_agreement.py --taxonomy clean2_base,clean2_rescued
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR


def run(taxonomy: str, parsed, width: int) -> dict:
    from shared.tuning import load_tuning
    from calibration.layer_bc_arms import (scenario_map_from_rows, taxonomy_path,
                                           install_embedder_shim, prewarm)
    from calibration.layer_b_routers import build_router_context, assign_scenarios_router
    from shared.scenario_vectors import scenario_text

    tax = taxonomy_path(taxonomy)
    art = json.loads(tax.read_text(encoding="utf-8-sig"))
    scenario_map, cluster_of_key = scenario_map_from_rows(art["rows"])
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(width)

    from calibration.layer_bc_arms import build_pairs
    pairs = build_pairs("recordings", "s0", "a0")

    # `taxonomy_identity` is what tells build_clusters whether to apply the noise-rescue.
    # Omitting it would silently rebuild clean2_rescued's memberships WITHOUT the rescue --
    # the arm would then be scored against a taxonomy whose descriptions came from grown
    # clusters while its member sets did not, which is the asymmetry this whole trial guards
    # against. It is passed explicitly for that reason, never defaulted.
    ident = art.get("identity") or {}

    # Each router is run on its OWN copy of the pairs AND its own context.
    # `assign_scenarios_router` MUTATES the pairs, so a shared list would leave every router
    # reading the previous one's decisions and the agreement matrix would be an artifact of
    # iteration order. `build_router_context` is router-aware (r1 needs the lookup, r2/r3 the
    # out-of-fold centroids), so it is built per router too.
    picks: dict[str, list[str]] = {}
    ctxs = {}
    for router in ("r0", "r1", "r2", "r3"):
        ctxs[router] = build_router_context(
            router, art["rows"], parsed, scenario_map,
            recordings="recordings", taxonomy_identity=ident, segment="s0", width=width)
        mine = [dict(p) for p in pairs]
        assign_scenarios_router(mine, scenario_map, router, ctxs[router])
        picks[router] = [p["scenario_key"] for p in mine]

    sink = {k: not v["is_coachable"] for k, v in scenario_map.items()}
    base = picks["r0"]
    out = {"taxonomy": taxonomy, "n_pairs": len(pairs), "routers": {}}

    ctx = ctxs["r1"]
    lookup = getattr(ctx, "lookup", None) or {}
    from calibration.layer_b_routers import pair_pool_indices
    move_len = getattr(ctx, "move_len", None) or {}
    resolved_mask = []
    for p in pairs:
        idxs = pair_pool_indices(p, ctx.turn_index_map, move_len.get(
            (p["call_filename"], p["turn_index"]), 1))
        resolved_mask.append(any(i in lookup for i in idxs))

    for router in ("r1", "r2", "r3"):
        mine = picks[router]
        differs = [i for i in range(len(base)) if mine[i] != base[i]]
        # THE NUMBER THE AUDIT ASKED FOR: resolved by lookup AND actually different.
        eff = [i for i in differs if resolved_mask[i]] if router == "r1" else differs
        out["routers"][router] = {
            "differs_from_r0": len(differs),
            "differs_share": len(differs) / max(1, len(base)),
            "resolved_by_lookup": int(sum(resolved_mask)) if router == "r1" else None,
            "resolved_share": (sum(resolved_mask) / max(1, len(base))
                               if router == "r1" else None),
            "EFFECTIVE_treatment": len(eff),
            "EFFECTIVE_share": len(eff) / max(1, len(base)),
            "sink_to_real": sum(1 for i in differs if sink[base[i]] and not sink[mine[i]]),
            "real_to_sink": sum(1 for i in differs if not sink[base[i]] and sink[mine[i]]),
            "real_to_other_real": sum(1 for i in differs
                                      if not sink[base[i]] and not sink[mine[i]]),
            "sink_to_other_sink": sum(1 for i in differs if sink[base[i]] and sink[mine[i]]),
            "r0_sink_share": sum(1 for k in base if sink[k]) / max(1, len(base)),
            "arm_sink_share": sum(1 for k in mine if sink[k]) / max(1, len(base)),
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--taxonomy", default="clean2_base",
                   help="comma-separated; one Layer B pass each, ONE shared parse")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--width", type=int, default=3072)
    p.add_argument("--out", default=str(ARTIFACTS_DIR / "router_agreement.json"))
    a = p.parse_args()

    from calibration.layer_bc_arms import parse_corpus
    parsed = parse_corpus(a.recordings)

    results = [run(t.strip(), parsed, a.width)
               for t in a.taxonomy.split(",") if t.strip()]

    for r in results:
        print("\n" + "=" * 92)
        print(f"ROUTER AGREEMENT vs r0 -- {r['taxonomy']}   ({r['n_pairs']} pairs)")
        print("=" * 92)
        print(f"  {'router':<8}{'differs':>9}{'share':>8}{'EFFECTIVE':>11}{'share':>8}"
              f"{'sink->real':>12}{'real->sink':>12}{'real->real':>12}{'sink%':>8}")
        for router, d in r["routers"].items():
            print(f"  {router:<8}{d['differs_from_r0']:>9}{d['differs_share']:>7.1%}"
                  f"{d['EFFECTIVE_treatment']:>11}{d['EFFECTIVE_share']:>7.1%}"
                  f"{d['sink_to_real']:>12}{d['real_to_sink']:>12}"
                  f"{d['real_to_other_real']:>12}{d['arm_sink_share']:>7.1%}")
        r1 = r["routers"]["r1"]
        print(f"\n  r1: {r1['resolved_by_lookup']} pairs carried a label "
              f"({r1['resolved_share']:.1%}), but only {r1['EFFECTIVE_treatment']} "
              f"({r1['EFFECTIVE_share']:.1%}) landed somewhere r0 would NOT have sent them.")
        print(f"      The rest AGREED with r0 -- they are not treatment. "
              f"r0 sink share {r1['r0_sink_share']:.1%}.")

    Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}\nZERO chat calls. Layer C was never run.")


if __name__ == "__main__":
    main()
