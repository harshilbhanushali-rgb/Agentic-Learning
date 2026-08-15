#!/usr/bin/env python3
"""Does Gemma sink CAMOUFLAGED junk? ~8 Gemma calls, zero DB writes.

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

THE RISK THIS TESTS. Turn mode reduces obvious junk but may create INVISIBLE junk.
In clause mode a junk cluster is 98% "yeah yeah" and Gemma rejects it trivially. In
turn mode the `jovio` cluster is only 4% content-free -- 563 substantive-looking turns
across half the corpus, glued together by the company's own name, covering intros,
payment terms and performance reviews. Gemma sees keywords plus sample turns, all of
which READ like real content.

If Gemma marks that coachable, turn mode has traded obvious junk for camouflaged junk
and the headline result needs re-reading. That is worth ~8 calls to find out before
spending ~230 on a full adjudication pass, or thousands on a real run.

Deliberately hand-picked, NOT sampled -- this is a targeted probe of one hypothesis,
not an estimate of the sink rate. Four clusters that SHOULD be accepted and four that
SHOULD be sunk are sent, so the run has controls in both directions: if Gemma sinks
everything, or accepts everything, the probe is uninformative and says so.

STATED DEVIATION FROM PRODUCTION. `accepted` starts empty and accumulates as the probe
proceeds, so early clusters see no nearest-neighbour context. Production adjudicates the
whole corpus largest-first, so a real run gives Gemma MORE context than this does. That
makes a "sink" verdict here strong evidence and an "accept" verdict partly confounded --
noted in the report rather than papered over.

Embedder-independent by construction: it judges stored cluster TEXT, so switching to a
Gemini embedder does not invalidate it.

Usage (from Brain/, venv active):
    python calibration/spot_check_adjudication.py --dry-run   # print prompts, 0 calls
    python calibration/spot_check_adjudication.py             # ~8 Gemma calls
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

# Hand-picked by keyword substring against the turn @0.92 artifact, with the verdict each
# SHOULD get written down before the call is made. "sink" means mechanics or not_coachable.
EXPECTED = [
    ("spend, budget",        "scenario", "real business topic, 10% content-free"),
    ("pixel, pixels",        "scenario", "real technical topic, coherent samples"),
    ("landing, landing page", "scenario", "real topic, coherent samples"),
    ("chatbot, ai",          "scenario", "real product topic, coherent samples"),
    ("jovio, jovia",         "sink",     "THE PROBE: company name, 4% empty, 50% of corpus, incoherent"),
    ("yeah yeah",            "sink",     "control: 96% content-free backchannel"),
    ("okay okay",            "sink",     "control: 99% content-free backchannel"),
    ("sales, years",         "sink",     "over-merged remnant: careers + RFP + programmatic"),
]


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--artifact", default=str(ARTIFACTS_DIR / "pool_unit_turn_092.json"))
    p.add_argument("--total-calls", type=int, default=416)
    p.add_argument("--dry-run", action="store_true", help="print the prompts, make no calls")
    return p.parse_args()


def _pick(clusters, needle):
    for c in clusters:
        if needle in c["keywords"].lower():
            return c
    return None


def main() -> None:
    args = _args()
    from config import load_config
    from shared import cluster_evidence
    from v2 import layer_a

    clusters = json.loads(Path(args.artifact).read_text(encoding="utf-8-sig"))["arms"][0]["clusters"]
    config = load_config()

    picked = []
    for needle, expected, why in EXPECTED:
        c = _pick(clusters, needle)
        if c is None:
            print(f"  ! no cluster matching {needle!r} -- skipping")
            continue
        picked.append((c, expected, why))
    print(f"probing {len(picked)} cluster(s) from {Path(args.artifact).name}\n")

    accepted, results = [], []
    for c, expected, why in picked:
        # Minimal faithful stand-in for the production cluster dict. The centroid is a
        # placeholder: _nearest_accepted only consumes it once `accepted` is non-empty,
        # and every record we append carries a real one from this same artifact... which
        # it does not, so nearest-neighbour context stays empty for the whole probe. That
        # is the deviation named in the docstring, and it makes the probe HARDER, not
        # easier, than production.
        stats = SimpleNamespace(
            centroid=np.zeros(768, dtype=np.float32),
            distinct_calls=c["distinct_calls"],
            call_coverage=c["call_coverage"],
            n_items=c["n_items"],
        )
        cluster = {
            "stats": stats,
            "keywords": c["keywords"],
            "texts": c["samples"],
            "n_merged": 1,
        }
        verdict = cluster_evidence.triage(
            stats, 9, __import__("shared.tuning", fromlist=["x"]).load_tuning().layer_a.ubiquity_ceiling
        )

        if args.dry_run:
            print(f"--- {c['keywords'][:50]}  (triage={verdict}, expect {expected})")
            for s in c["samples"][:3]:
                print(f"      {s[:90]}")
            continue

        raw = layer_a._adjudicate(cluster, verdict, [], args.total_calls, config)
        decision = (raw.get("decision") or "").strip()
        kind = layer_a._KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)
        got = "scenario" if kind == cluster_evidence.KIND_SCENARIO else "sink"
        ok = got == expected
        results.append({
            "keywords": c["keywords"], "n_items": c["n_items"],
            "thin_fraction": c["thin_fraction"], "call_coverage": c["call_coverage"],
            "triage": verdict, "expected": expected, "decision": decision,
            "kind": kind, "got": got, "agrees": ok,
            "reason": (raw.get("reason") or "").strip(),
            "scenario_key": (raw.get("scenario_key") or "").strip(),
            "why_expected": why,
        })
        mark = "OK " if ok else "!! "
        print(f"{mark}{got:<9} (expected {expected:<9}) {c['n_items']:>5} items "
              f"{c['thin_fraction']:>4.0%} empty | {c['keywords'][:42]}")
        print(f"      decision={decision!r} key={results[-1]['scenario_key']!r}")
        print(f"      reason: {results[-1]['reason'][:150]}")

    if args.dry_run:
        return

    print("\n" + "=" * 78)
    agree = sum(1 for r in results if r["agrees"])
    print(f"agreement with pre-written expectations: {agree}/{len(results)}")
    probe = next((r for r in results if "jovio" in r["keywords"].lower()), None)
    if probe:
        print(f"\nTHE PROBE -- company-name cluster ({probe['n_items']} items, "
              f"{probe['thin_fraction']:.0%} content-free, "
              f"{probe['call_coverage']:.0%} of corpus):")
        print(f"  Gemma said: {probe['decision']!r} -> {probe['got'].upper()}")
        if probe["got"] == "sink":
            print("  => Gemma CAUGHT the camouflaged junk. The main risk to turn mode does\n"
                  "     not reproduce, and this is strong evidence because the probe gave it\n"
                  "     LESS context than production would.")
        else:
            print("  => Gemma ACCEPTED it as coachable. Turn mode trades obvious junk for\n"
                  "     camouflaged junk. Partly confounded: no nearest-neighbour context\n"
                  "     was supplied, which production would. Re-test with context before\n"
                  "     treating this as final.")
    sinks_all = all(r["got"] == "sink" for r in results)
    scen_all = all(r["got"] == "scenario" for r in results)
    if sinks_all or scen_all:
        print("\n  UNINFORMATIVE: every cluster got the same verdict, so the probe cannot\n"
              "  separate anything. Do not read the jovio result above as signal.")

    out = ARTIFACTS_DIR / "spot_check_adjudication.json"
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
