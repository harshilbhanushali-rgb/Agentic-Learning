#!/usr/bin/env python3
"""Score Layer B arms with the rev-4 cluster-level metric. FREE -- reads artifacts only.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md section 4

Scoring is deliberately SEPARATE from running. `layer_bc_arms.py` writes raw evidence
(`support_call_files` per milestone) and this reads it, which is what made three metric
revisions cost nothing: every one was applied to artifacts already on disk, with no re-run.
Keep it that way -- if a future metric needs a field the artifacts do not carry, ADD THE FIELD
and re-run, rather than making the runner compute a score.

*** THE NULL IS ONE FIXED YARDSTICK, LOADED FROM AN ARTIFACT, NOT DERIVED PER ARM. ***
`null_draw_weights.json` is built once from PRODUCTION's extraction by
`calibration/build_null_weights.py`. Deriving weights per arm would let an arm move the
yardstick it is measured against -- an arm routing more pairs into big calls would raise both
its own diversity and its expectation, in whatever ratio flattered it. The weights carry a
`weights_sha` so a report can prove which yardstick it used.

*** THE TABLE IS BUILT OVER THE UNION OF EVERY ARM'S ks. *** Built per arm, a cluster size
present in one and absent from another would raise `KeyError` -- or worse, two arms would be
scored against separately-sampled expectations. `union_cluster_ks` exists for this.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/score_layer_b_arms.py s0a0r0_b s0a4r0_b
    ..\\.venv\\Scripts\\python.exe calibration/score_layer_b_arms.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration import layer_b_arms as lb

WEIGHTS = ARTIFACTS_DIR / "null_draw_weights.json"


def load_arm(name: str) -> dict:
    p = ARTIFACTS_DIR / f"layer_bc_{name}.json"
    if not p.exists():
        raise SystemExit(f"no artifact for arm {name!r} ({p.name})")
    art = json.loads(p.read_text(encoding="utf-8-sig"))
    if art.get("incomplete"):
        raise SystemExit(f"{p.name} is stamped INCOMPLETE (--limit or failures). Scoring it "
                         f"would report a partial taxonomy as a result.")
    return art


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("arms", nargs="*", help="arm names; the FIRST is the control")
    p.add_argument("--all", action="store_true", help="every layer_bc_*.json on disk")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--trials", type=int, default=20_000)
    p.add_argument("--uniform", action="store_true",
                   help="ignore the weights artifact. For measuring what composition-matching "
                        "is worth, NOT for a verdict -- the uniform null was measured to leave "
                        "a residual drift the weighted one removes.")
    a = p.parse_args()

    names = a.arms
    if a.all:
        names = sorted(f.name[len("layer_bc_"):-len(".json")]
                       for f in ARTIFACTS_DIR.glob("layer_bc_*.json")
                       if "_ckpt" not in f.name and "criteria" not in f.name
                       and "embed_scope" not in f.name)
    if not names:
        p.print_help()
        return

    arts = {n: load_arm(n) for n in names}
    accounts, reason, merges = lb.load_account_map(a.recordings)

    weights = None
    wsha = "UNIFORM (no composition matching)"
    if not a.uniform:
        if not WEIGHTS.exists():
            raise SystemExit(f"{WEIGHTS.name} missing -- run calibration/build_null_weights.py "
                             f"first. Scoring against a uniform null would silently use a "
                             f"weaker yardstick than the one the metric was validated on.")
        w = json.loads(WEIGHTS.read_text(encoding="utf-8-sig"))
        weights, wsha = w["weights"], f"{w['weights_sha']} ({w['n_pairs']} pairs)"

    pool = lb.corpus_account_pool(accounts, weights)
    ks = lb.union_cluster_ks([art["per_scenario"] for art in arts.values()], accounts)
    table = lb.expected_neff_table(pool, ks, trials=a.trials)

    print("=" * 100)
    print("LAYER B ARMS -- rev-4 cluster account-diversity lift")
    print("=" * 100)
    print(f"  null: {wsha}   accounts {len(set(accounts.values()))}   "
          f"zero-weight calls {getattr(pool, 'n_zero_weight', 'n/a')}   trials {a.trials}")
    print(f"  sibling merges applied: {merges or 'none'}")
    print(f"  k range {min(ks)}..{max(ks)} over {len(ks)} distinct sizes\n")

    stats = {}
    print(f"  {'arm':<16}{'S/A/R':<11}{'clus':>6}{'miles':>7}{'mean lift':>11}"
          f"{'med lift':>10}{'mean k':>8}{'unscor':>8}{'acct%':>8}")
    for n in names:
        art = arts[n]
        ps = art["per_scenario"]
        st = lb.per_cluster_stats(ps, accounts, table)
        stats[n] = st
        d = lb.score_distribution(ps, accounts, table)
        ur = lb.unaccounted_rate(ps, accounts)
        ident = art.get("identity", {})
        sar = f"{ident.get('segment','?')}/{ident.get('admit','?')}/{ident.get('router','?')}"
        good = [v["lift"] for v in st.values() if v["lift"] == v["lift"]]
        kk = [v.get("k", 0) for v in st.values()]
        print(f"  {n:<16}{sar:<11}{len(st):>6}{art['stats']['n_milestones']:>7}"
              f"{(sum(good)/len(good) if good else float('nan')):>11.4f}"
              f"{d['lift']['median']:>10.4f}{(sum(kk)/len(kk) if kk else 0):>8.1f}"
              f"{d['unscoreable']:>8}{ur['accounted_frac']*100:>7.1f}%")

    if len(names) < 2:
        return

    print(f"\n  PAIRED SIGN TEST on cluster lift, joined on cluster_id. Control = {names[0]!r}")
    print(f"  {'arm':<16}{'shared':>8}{'up':>5}{'down':>6}{'tie':>5}{'unscor':>8}"
          f"{'net':>9}{'p':>9}")
    ctrl = stats[names[0]]
    for n in names[1:]:
        d = lb.compare_arms(ctrl, stats[n], "lift")
        print(f"  {n:<16}{d['n_shared']:>8}{d['up']:>5}{d['down']:>6}{d['tie']:>5}"
              f"{d['unscoreable_pairs']:>8}{d['net']:>+9.3f}{d['p']:>9.4f}")

    m = lb.multiplicity_note(max(1, len(names) - 1))
    print(f"\n  MULTIPLICITY: {m['n_arms']} arm(s) read at alpha={m['alpha']}. "
          f"Expected false passes {m['expected_false_passes']:.2f}; "
          f"P(at least one) {m['p_at_least_one']:.1%}.")
    print(f"  Reported, NOT corrected: Bonferroni would move the bar to "
          f"{m['bonferroni_alpha']:.4f}, which on ~26 clusters needs a near-unanimous flip "
          f"and would hide a real moderate effect.")
    print("\n  Lift is NOT a threshold count -- it is compared arm-to-arm directly. "
          "An arm that\n  materially SHRINKS cluster k needs its own placebo before this "
          "is readable.")


if __name__ == "__main__":
    main()
