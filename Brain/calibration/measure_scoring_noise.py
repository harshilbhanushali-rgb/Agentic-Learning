#!/usr/bin/env python3
"""Measure Layer D's scoring NOISE FLOOR: two identical runs, nothing changed.

Run from Brain/:
    python calibration/measure_scoring_noise.py
    python calibration/measure_scoring_noise.py --a arm3_run1_20260810 --b public
    python calibration/measure_scoring_noise.py --dedup      # salvage a contaminated arm

Zero Gemma, zero writes -- compares two already-captured Layer D result sets.

WHY THIS EXISTS

The 2026-08-10 milestone-criteria rewrite reported "43 milestones improved, 17 worsened".
The 17 could not be interpreted, because there was no control: Step 3 runs at
temperature=0.2, so re-scoring the same response can flip a borderline partial/miss call.
Without knowing how much a run moves when NOTHING changes, an A/B cannot separate a real
regression from ordinary variance -- and the whole 43-vs-17 asymmetry argument was an
inference rather than a measurement.

This script measures that floor. Run Layer D twice on the same transcripts with no code or
config change, snapshot the first result, then compare. Whatever moves is noise. Any future
A/B must clear that bar before its per-milestone winners and losers mean anything.

WHY THE DUPLICATE GUARD EXISTS (added 2026-08-11, after this script reported a floor it
should have refused to report)

An earlier attempt compared a clean snapshot against a `public` schema that held a BLEND of
two concurrently running Layer D runs. One run was believed dead because the harness had
reported its background task as "stopped" -- but that is harness bookkeeping, not the OS
process state. The live process kept marking transcripts done in checkpoints.db, so the
second run skipped 10 of 19 as already complete, and because
upsert_milestone_performance does `attempts = attempts + 1` on conflict, 28 doubly-scored
signals inflated attempts from 889 to 905. The log still printed "Ego Trap batch complete".

This script then reported 15.6% movement and +0.000 drift as a noise floor. Nothing in its
output hinted that the comparison was meaningless. That is the same class of self-inflicted
harness error as the merge-blind _match_milestones and dry_run_ego_trap's silently empty
similarity band, so the fix is the same: measure the precondition and refuse.

HOW TO READ IT
  * `movement rate` is the fraction of milestones whose weighted score changed at all. That
    is the number to quote as the floor.
  * `net delta` should be ~0. A large net in either direction means the two runs were NOT
    identically configured -- check for a code change between them before trusting anything.
  * SHAPE matters as much as rate. Noise moves milestones up and down in roughly equal
    measure, so a symmetric net near zero is the signature of variance. An A/B whose movers
    are lopsided (the criteria rewrite: 43 up / 17 down, net +4.48) is showing something a
    symmetric floor does not explain, even when its raw movement rate is similar.
  * Milestones with <=2 attempts are reported separately: a single verdict flip moves their
    score by 0.5 or 1.0, so they dominate any movement count without carrying information.
"""
from __future__ import annotations

import argparse
import statistics as st

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import load_config
from shared import storage


def _weighted(hits: int, partial: int, attempts: int) -> float:
    return (hits + 0.5 * partial) / attempts if attempts else 0.0


def _schema_prefix(schema: str) -> str:
    return "" if schema == "public" else f"{schema}."


def duplicate_groups(cur, schema: str) -> tuple[int, int]:
    """(groups, excess rows) of gap_events recording the SAME signal more than once.

    A signal is (call_id, scenario_key, signal_turn_index). gap_events has only a SERIAL
    primary key, so re-processing a transcript appends rather than conflicting -- there is
    no constraint that would have caught this. Any non-zero result means the schema holds
    more than one run's worth of verdicts for at least one signal.
    """
    cur.execute(f"""
        SELECT count(*)::int, COALESCE(sum(n - 1), 0)::int
        FROM (
          SELECT call_id, scenario_key, signal_turn_index, count(*) AS n
          FROM {_schema_prefix(schema)}gap_events
          GROUP BY 1,2,3 HAVING count(*) > 1
        ) d
    """)
    return tuple(cur.fetchone())


def _load_rebuilt(cur, schema: str, dedup: bool) -> dict:
    """{(rubric_id, milestone_id, csm_id): {...}} rebuilt from gap_events.

    gap_events stores, per scored signal, the full verdict split across milestones_hit /
    milestones_partial_hit / milestones_missed. So milestone_performance is derivable by
    counting array membership, and deduplicating the signal first is what recovers a usable
    measurement from a schema that two runs wrote to. Faithfulness is checked, not assumed --
    see _assert_faithful.
    """
    cur.execute(f"""
        WITH src AS ({
            f'''SELECT DISTINCT ON (call_id, scenario_key, signal_turn_index) *
                FROM {_schema_prefix(schema)}gap_events
                ORDER BY call_id, scenario_key, signal_turn_index, gap_event_id'''
            if dedup else f'SELECT * FROM {_schema_prefix(schema)}gap_events'
        })
        SELECT e.rubric_id, m.mid, e.csm_id, min(e.scenario_key),
               count(*)::int AS attempts,
               count(*) FILTER (WHERE m.mid = ANY(e.milestones_hit))::int AS hits,
               count(*) FILTER (WHERE m.mid = ANY(e.milestones_partial_hit))::int AS partial
        FROM src e
        CROSS JOIN LATERAL unnest(
          e.milestones_hit || e.milestones_partial_hit || e.milestones_missed
        ) AS m(mid)
        WHERE e.rubric_id IS NOT NULL
        GROUP BY 1,2,3
    """)
    return {(r[0], r[1], r[2]): {"skey": r[3], "a": r[4], "h": r[5], "p": r[6]}
            for r in cur.fetchall()}


def _load_stored(cur, schema: str) -> dict:
    cur.execute(f"""
        SELECT rubric_id, milestone_id, csm_id, scenario_key, attempts, hits, partial_hits
        FROM {_schema_prefix(schema)}milestone_performance
    """)
    return {(r[0], r[1], r[2]): {"skey": r[3], "a": r[4], "h": r[5], "p": r[6]}
            for r in cur.fetchall()}


def _assert_faithful(cur, schema: str) -> str:
    """Prove the gap_events rebuild reproduces stored counters, on THIS schema.

    Run before any --dedup number is reported. If the rebuild cannot reproduce the
    undeduplicated counters, then it does not model how milestone_performance was written
    and its deduplicated output is not evidence of anything.
    """
    stored = _load_stored(cur, schema)
    rebuilt = _load_rebuilt(cur, schema, dedup=False)
    if stored == rebuilt:
        return "exact"
    diffs = [k for k in set(stored) | set(rebuilt) if stored.get(k) != rebuilt.get(k)]
    return f"MISMATCH on {len(diffs)} row(s), e.g. {diffs[:3]}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", default="arm3_run1_20260810", help="first run's schema")
    ap.add_argument("--b", default="public", help="second run's schema")
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--dedup", action="store_true",
                    help="rebuild counters from gap_events, deduplicating each signal. "
                         "Recovers a floor from a schema two runs wrote to.")
    args = ap.parse_args()

    cfg = load_config()
    conn = storage.get_connection(cfg.database_url)
    try:
        with conn.cursor() as cur:
            for s in (args.a, args.b):
                cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                            (s,))
                if cur.fetchone() is None and s != "public":
                    print(f"ERROR: schema {s!r} does not exist.")
                    return

            # --- precondition: neither arm may hold two runs' verdicts ----------------
            print("=" * 82)
            print("PRECONDITION — is each arm exactly ONE run?")
            print("=" * 82)
            dirty = {}
            for s in (args.a, args.b):
                groups, excess = duplicate_groups(cur, s)
                dirty[s] = groups
                verdict = "clean" if groups == 0 else f"*** {groups} DUPLICATED SIGNAL(S) ***"
                print(f"  {s:<28} {verdict}"
                      + (f"  (+{excess} excess attempt-rows)" if excess else ""))

            if any(dirty.values()) and not args.dedup:
                print("\n" + "!" * 82)
                print("REFUSING TO REPORT A FLOOR.")
                print("!" * 82)
                print("  A schema with duplicated signals holds more than one run's verdicts,")
                print("  so the difference between these arms is not variance between two runs.")
                print("  gap_events has only a SERIAL primary key, so a re-processed transcript")
                print("  appends instead of conflicting, and upsert_milestone_performance does")
                print("  attempts = attempts + 1 on conflict -- double-counting every attempt.")
                print("\n  Two ways forward:")
                print("    * --dedup   rebuild the counters from gap_events, keeping one verdict")
                print("                per signal. Free, and self-checked against the stored")
                print("                counters before anything is reported.")
                print("    * re-run    ops/run_noisefloor.ps1, which guards against a")
                print("                concurrent run. Costs ~80 Gemma calls.")
                return

            source = "stored milestone_performance"
            if args.dedup:
                print("\n  --dedup requested. Verifying the rebuild reproduces stored counters:")
                for s in (args.a, args.b):
                    result = _assert_faithful(cur, s)
                    print(f"    {s:<28} {result}")
                    if result != "exact":
                        print("\n  REFUSING: the gap_events rebuild does not reproduce this")
                        print("  schema's stored counters, so its deduplicated output cannot be")
                        print("  trusted either.")
                        return
                source = "gap_events, deduplicated per signal"

            a_side = (_load_rebuilt(cur, args.a, True) if args.dedup
                      else _load_stored(cur, args.a))
            b_side = (_load_rebuilt(cur, args.b, True) if args.dedup
                      else _load_stored(cur, args.b))

        keys = set(a_side) | set(b_side)
        if not keys:
            print("No rows to compare.")
            return
        empty = {"skey": "?", "a": 0, "h": 0, "p": 0}

        recs = []
        for k in keys:
            x, y = a_side.get(k, empty), b_side.get(k, empty)
            recs.append({
                "skey": x["skey"] if x["skey"] != "?" else y["skey"], "mid": k[1],
                "aa": x["a"], "ah": x["h"], "ap": x["p"],
                "ba": y["a"], "bh": y["h"], "bp": y["p"],
                "delta": _weighted(y["h"], y["p"], y["a"]) - _weighted(x["h"], x["p"], x["a"]),
                "only_one_side": x["a"] == 0 or y["a"] == 0,
            })

        moved = [r for r in recs if r["delta"] != 0]
        up = [r for r in moved if r["delta"] > 0]
        down = [r for r in moved if r["delta"] < 0]
        moved_small = [r for r in moved if max(r["aa"], r["ba"]) <= 2]
        solid = [r for r in moved if min(r["aa"], r["ba"]) >= 6]

        ta = sum(r["aa"] for r in recs); th = sum(r["ah"] for r in recs)
        tp = sum(r["ap"] for r in recs)
        tb = sum(r["ba"] for r in recs); bh_ = sum(r["bh"] for r in recs)
        bp_ = sum(r["bp"] for r in recs)

        print("\n" + "=" * 82)
        print(f"SCORING NOISE FLOOR — {args.a}  vs  {args.b}")
        print(f"source: {source}")
        print("Nothing changed between these runs. Everything below is variance.")
        print("=" * 82)
        print(f"  run A: {ta:>5} attempts | {th:>3} hits ({th/max(ta,1):.1%}) | "
              f"{tp:>3} partial | weighted {_weighted(th,tp,ta):.3f}")
        print(f"  run B: {tb:>5} attempts | {bh_:>3} hits ({bh_/max(tb,1):.1%}) | "
              f"{bp_:>3} partial | weighted {_weighted(bh_,bp_,tb):.3f}")
        print(f"\n  aggregate weighted drift: "
              f"{_weighted(bh_,bp_,tb) - _weighted(th,tp,ta):+.3f}   (want ~0.000)")
        print(f"  attempt-count drift     : {ta} -> {tb} "
              f"({(tb-ta)/max(ta,1):+.1%})")
        if ta and abs(tb - ta) / ta > 0.05:
            print("  ! >5% attempt drift means the arms did not score the same population.")

        print(f"\n  MOVEMENT RATE: {len(moved)}/{len(recs)} milestones "
              f"({len(moved)/len(recs):.1%})  <-- THIS IS THE FLOOR")
        print(f"    improved {len(up)} (sum {sum(r['delta'] for r in up):+.2f}) | "
              f"worsened {len(down)} (sum {sum(r['delta'] for r in down):+.2f}) | "
              f"net {sum(r['delta'] for r in moved):+.2f}")
        if moved:
            mags = [abs(r["delta"]) for r in moved]
            print(f"    |delta| median {st.median(mags):.2f}  max {max(mags):.2f}")
        print(f"    of the movers, {len(moved_small)} have <=2 attempts "
              f"({len(moved_small)/max(len(moved),1):.0%}) — a single verdict flip")
        print(f"    movers with >=6 attempts on BOTH sides: {len(solid)} "
              f"— the only ones worth reading individually")
        print(f"    milestones present in only one run: "
              f"{sum(1 for r in recs if r['only_one_side'])}")

        print(f"\n{'=' * 82}\nINTERPRETING THE 2026-08-10 CRITERIA REWRITE AGAINST THIS FLOOR\n{'=' * 82}")
        print("  rewrite A/B moved  60/244 milestones (24.6%): 43 up / 17 down, net +4.48")
        print(f"  this noise floor   {len(moved)}/{len(recs)} milestones "
              f"({len(moved)/len(recs):.1%}): {len(up)} up / {len(down)} down, "
              f"net {sum(r['delta'] for r in moved):+.2f}")
        print("\n  Compare SHAPE, not only rate. A floor moves milestones up and down about")
        print("  equally, for a net near zero; the rewrite's 43-vs-17 is lopsided. If the")
        print("  floor's rate approaches 24.6%, the rewrite's INDIVIDUAL winners and losers")
        print("  are not citable — but a net far outside the floor's still is.")

        for title, group in (("LARGEST MOVES, run A -> run B", sorted(moved, key=lambda r: -abs(r["delta"]))),):
            print(f"\n  --- {title} (top {min(args.show, len(group))}) ---")
            print(f"    {'delta':>7}  {'A a/h/p':>10}  {'B a/h/p':>10}  milestone")
            for r in group[:args.show]:
                a_cnt = "{}/{}/{}".format(r["aa"], r["ah"], r["ap"])
                b_cnt = "{}/{}/{}".format(r["ba"], r["bh"], r["bp"])
                print(f"    {r['delta']:>+7.2f}  {a_cnt:>10}  {b_cnt:>10}  "
                      f"{r['skey']} :: {r['mid']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
