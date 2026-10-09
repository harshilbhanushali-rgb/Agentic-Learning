#!/usr/bin/env python3
"""Aggregate blind subagent cluster verdicts and compare granularities. Free.

Joins the independent judges' verdicts (written blind -- they never saw Gemma's decision,
scenario key, description or reason) back onto the adjudication artifact.

*** THE JOIN IS ON RANK, NOT ON A STABLE ID. *** The verdict files call their field
`cluster_id`, and this docstring used to repeat that claim, but the adjudication artifact has
no `cluster_id` column at all -- the key is `i`, the largest-first loop index. That is sound
only because both sides were produced from the SAME adjudication run. Joining a verdict set
against a DIFFERENT run's artifact would silently compare unrelated clusters, because any
change in cluster sizes reorders the rank. `adjudication_ab.py` records a stable
`cluster_id` (the raw-topic id set) precisely so its comparisons do not have this property;
this script predates that and is kept only for the frozen min16/min50 artifacts.

*** STALE-CORPUS WARNING. *** `adjudicate_gemini_min{16,50}.json` describe the 23,949-turn
pool. That corpus no longer exists: 13.2% of it was not client speech (job interviews,
unattributed speakers, Joveo staff read as client) and it is now 20,788 turns. These numbers
remain valid as a record of that run and must not be compared against anything newer.

Three things this answers that nothing before it could:

1. QUALITY BY GRANULARITY. Coherence and coachability rates at min_cluster_size 16 vs 50,
   judged by readers who had no idea which granularity they were looking at.

2. IS GEMMA'S SINK RATE RIGHT? Gemma sank 84.5% of clusters at min 16 and 77.6% at min 50.
   Independent agreement makes that a defensible taxonomy; systematic disagreement means
   either Gemma over-sinks (throwing away coachable material) or under-sinks.

3. WHAT THE CONTENT-FREE PROXY IS WORTH. That proxy drove every number in this effort
   before the adjudication run. It has already been shown to be an excellent junk detector
   and a poor quality measure; this puts a second, independent judgment on both sides.

Weighting note: rates are reported per-CLUSTER and per-TURN. A taxonomy where the junk is
concentrated in a few huge clusters is very different from one where it is spread across
many small ones, and the per-cluster number alone cannot tell them apart.

Usage (from Brain/):
    python calibration/aggregate_cluster_verdicts.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

BATCH_DIR = ARTIFACTS_DIR / "cluster_batches"


def load(mcs: int):
    rows = {r["i"]: r for r in json.loads(
        (ARTIFACTS_DIR / f"adjudicate_gemini_min{mcs}.json").read_text(encoding="utf-8-sig")
    )["rows"]}
    verdicts = {}
    files = sorted(BATCH_DIR.glob(f"verdict_min{mcs}_batch*.json"))
    for f in files:
        for v in json.loads(f.read_text(encoding="utf-8-sig"))["verdicts"]:
            verdicts[v["cluster_id"]] = v
    return rows, verdicts, files


def main() -> None:
    print("=" * 80)
    print("BLIND INDEPENDENT CLUSTER JUDGING -- min_cluster_size 16 vs 50")
    print("=" * 80)
    summary = {}
    for mcs in (16, 50):
        rows, ver, files = load(mcs)
        missing = set(rows) - set(ver)
        print(f"\n--- min_cluster_size={mcs} ---")
        print(f"  {len(files)} verdict file(s), {len(ver)} judged of {len(rows)} clusters"
              + (f"  ** {len(missing)} MISSING **" if missing else ""))
        if not ver:
            print("  no verdicts yet"); continue

        common = [i for i in rows if i in ver]
        tot_turns = sum(rows[i]["n_items"] for i in common)
        coh = Counter(ver[i]["coherent"] for i in common)
        cch = Counter(ver[i]["coachable"] for i in common)
        coh_y = sum(rows[i]["n_items"] for i in common if ver[i]["coherent"] == "yes")
        cch_y = sum(rows[i]["n_items"] for i in common if ver[i]["coachable"] == "yes")
        print(f"  coherent : " + "  ".join(f"{k}={v} ({v/len(common)*100:.0f}%)"
                                           for k, v in coh.most_common()))
        print(f"  coachable: " + "  ".join(f"{k}={v} ({v/len(common)*100:.0f}%)"
                                           for k, v in cch.most_common()))
        print(f"  by TURN VOLUME: coherent {coh_y}/{tot_turns} ({coh_y/tot_turns*100:.1f}%)"
              f" | coachable {cch_y}/{tot_turns} ({cch_y/tot_turns*100:.1f}%)")

        # --- agreement with Gemma ----------------------------------------------------
        # *** `merged` MEANS RETAINED. *** A merge_into verdict folds a duplicate cluster INTO
        # an existing scenario -- the turns are kept, they just do not mint a new scenario. The
        # line here used to read `rows[i]["kind"] == "scenario"`, which counted all 69 merged
        # clusters as SUNK and manufactured the "Gemma over-sinks 14.6% of the corpus" finding
        # that CLAUDE.md now retracts. The retraction reached the documentation and never
        # reached this code, so re-running the script reproduced the false number verbatim.
        #
        # The cross-tab below is the real fix, not the boolean. A four-valued enum collapsed to
        # a boolean can be got wrong silently; printed in full, this class of error is
        # impossible to miss -- which is the lesson CLAUDE.md draws from the original incident.
        RETAINED = ("scenario", "merged")
        g_keep = {i: rows[i]["kind"] in RETAINED for i in common}
        j_coach = {i: ver[i]["coachable"] == "yes" for i in common}
        agree = sum(1 for i in common if g_keep[i] == j_coach[i])
        gy_jn = [i for i in common if g_keep[i] and not j_coach[i]]
        gn_jy = [i for i in common if not g_keep[i] and j_coach[i]]

        print(f"\n  GEMMA kind x BLIND JUDGE coachable (full cross-tab, never collapsed):")
        print(f"    {'kind':<12}{'judge=yes':>11}{'judge=no':>10}{'turns':>9}   retained?")
        for kind in ("scenario", "merged", "mechanics", "logistics"):
            ks = [i for i in common if rows[i]["kind"] == kind]
            if not ks:
                continue
            print(f"    {kind:<12}{sum(1 for i in ks if j_coach[i]):>11}"
                  f"{sum(1 for i in ks if not j_coach[i]):>10}"
                  f"{sum(rows[i]['n_items'] for i in ks):>9}"
                  f"   {'YES' if kind in RETAINED else 'no'}")

        print(f"\n  vs GEMMA on RETAINED-vs-DISCARDED: agree {agree}/{len(common)} "
              f"({agree/len(common)*100:.0f}%)")
        print(f"    Gemma retained, judge says NOT      : {len(gy_jn)}  (Gemma may be admitting junk)")
        print(f"    Gemma DISCARDED, judge says COACHABLE: {len(gn_jy)}  (Gemma may be over-sinking)")
        if gn_jy:
            lost = sum(rows[i]["n_items"] for i in gn_jy)
            print(f"      -> {lost} turns ({lost/tot_turns*100:.1f}%) the judge would keep")
            for i in sorted(gn_jy, key=lambda x: -rows[x]["n_items"])[:5]:
                print(f"         {rows[i]['n_items']:>5}t [{rows[i]['scenario_key'][:40]}] "
                      f"{ver[i]['reason'][:70]}")

        # the content-free proxy, second opinion
        hi = [i for i in common if rows[i]["thin"] >= 0.70]
        lo = [i for i in common if rows[i]["thin"] < 0.30]
        if hi:
            print(f"\n  proxy check: {len(hi)} clusters >=70% content-free -> judge calls "
                  f"{sum(1 for i in hi if j_coach[i])} coachable "
                  f"({sum(1 for i in hi if j_coach[i])/len(hi)*100:.0f}%)")
        if lo:
            print(f"               {len(lo)} clusters <30% content-free -> judge calls "
                  f"{sum(1 for i in lo if j_coach[i])} coachable "
                  f"({sum(1 for i in lo if j_coach[i])/len(lo)*100:.0f}%)")
        summary[mcs] = {
            "clusters": len(common), "turns": tot_turns,
            "judge_coachable": sum(1 for i in common if j_coach[i]),
            "judge_coachable_turns": cch_y,
            "judge_coherent": coh["yes"],
            # RETAINED = scenario + merged. Reported under that name rather than "coachable"
            # because `merged` clusters are kept but do not mint a scenario, so calling the
            # sum "coachable" is what invited the collapse in the first place.
            "gemma_retained": sum(1 for i in common if g_keep[i]),
            "gemma_new_scenarios": sum(1 for i in common if rows[i]["kind"] == "scenario"),
            "agreement": agree / len(common),
        }

    if len(summary) == 2:
        print("\n" + "=" * 80)
        print("HEAD TO HEAD")
        print("=" * 80)
        print(f"{'':<26}{'min 16':>14}{'min 50':>14}")
        a, b = summary[16], summary[50]
        for lab, k, pct in [("clusters judged", "clusters", False),
                            ("coherent (judge)", "judge_coherent", True),
                            ("coachable (judge)", "judge_coachable", True),
                            ("RETAINED (Gemma)", "gemma_retained", True),
                            ("  of which NEW scenarios", "gemma_new_scenarios", True)]:
            av = f"{a[k]} ({a[k]/a['clusters']*100:.0f}%)" if pct else str(a[k])
            bv = f"{b[k]} ({b[k]/b['clusters']*100:.0f}%)" if pct else str(b[k])
            print(f"{lab:<26}{av:>14}{bv:>14}")
        print(f"{'coachable turn volume':<26}"
              f"{a['judge_coachable_turns']/a['turns']*100:>13.1f}%"
              f"{b['judge_coachable_turns']/b['turns']*100:>13.1f}%")
        print(f"{'judge-vs-Gemma agreement':<26}{a['agreement']*100:>13.0f}%{b['agreement']*100:>13.0f}%")
        out = ARTIFACTS_DIR / "cluster_verdict_summary.json"
        out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
